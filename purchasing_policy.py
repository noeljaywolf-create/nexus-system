"""Versioned purchasing policies and immutable, per-submission approval snapshots."""
import json
import uuid
from datetime import datetime,timezone

def uid():return uuid.uuid4().hex
def now():return datetime.now(timezone.utc).isoformat()

DEFAULT={'name':'Independent purchase review','threshold':0,'standard_stages':[{'label':'Independent manager review','reviewer_role':'manager'}],'high_value_stages':[{'label':'Independent manager review','reviewer_role':'manager'}]}

class PurchasingPolicy:
    def __init__(self,service,require,text,money):self.s=service;self.db=service.db;self.r=require;self.text=text;self.money=money
    def active_version(self):
        row=self.db.execute('SELECT active_version FROM purchasing_policy_state WHERE org_id=?',(self.s.org,)).fetchone()
        return row[0] if row else 0
    def definition(self,version):
        self.r(type(version) is int and version>=0,'Choose a saved policy version')
        if version==0:return json.loads(json.dumps(DEFAULT))
        row=self.db.execute('SELECT definition FROM purchasing_policies WHERE org_id=? AND version=?',(self.s.org,version)).fetchone();self.r(row is not None,'Policy version not found',404)
        return json.loads(row[0])
    def clean(self,data):
        self.r(isinstance(data,dict),'Choose a policy definition')
        result={'name':self.text(data,'name',limit=120),'threshold':self.money(data,'threshold')}
        for branch in ('standard_stages','high_value_stages'):
            stages=data.get(branch);self.r(isinstance(stages,list) and 1<=len(stages)<=5,'Each branch needs 1–5 approval stages')
            result[branch]=[]
            for stage in stages:
                self.r(isinstance(stage,dict),'Invalid approval stage');role=stage.get('reviewer_role')
                self.r(isinstance(role,str) and role in ('manager','finance','admin'),'Choose a supported reviewer role')
                result[branch].append({'label':self.text(stage,'label',limit=100),'reviewer_role':role})
        return result
    def list(self):
        self.s.allow('admin');versions=self.s.rows('SELECT version,definition,created_at FROM purchasing_policies WHERE org_id=? AND version>0 ORDER BY version DESC',(self.s.org,))
        for version in versions:version['definition']=json.loads(version['definition'])
        versions.append({'version':0,'definition':self.definition(0),'created_at':None})
        return {'active_version':self.active_version(),'versions':versions,'currency':self.db.execute('SELECT currency FROM organizations WHERE id=?',(self.s.org,)).fetchone()[0]}
    def post(self,action,data):
        self.s.allow('admin')
        if action=='versions':
            definition=self.clean(data.get('definition'));version=self.db.execute('SELECT COALESCE(MAX(version),0)+1 FROM purchasing_policies WHERE org_id=?',(self.s.org,)).fetchone()[0]
            self.r(version<=200,'This workspace supports at most 200 policy versions')
            self.db.execute('INSERT INTO purchasing_policies VALUES(?,?,?,?,?)',(self.s.org,version,json.dumps(definition),self.s.user,now()));self.s.audit('save_version','purchasing_policy',str(version),{'name':definition['name']});return self.list()
        version=data.get('version');definition=self.definition(version)
        if action=='simulate':
            amount=self.money(data,'amount');branch='high_value_stages' if amount>definition['threshold'] else 'standard_stages';stages=definition[branch]
            members=self.s.rows('SELECT user_id,role FROM memberships WHERE org_id=? AND active=1 AND user_id!=?',(self.s.org,self.s.user))
            counts=[sum(self.role_matches(member['role'],stage['reviewer_role']) for member in members) for stage in stages]
            return dict(version=version,amount=amount,branch=branch,stages=stages,available_by_role=counts,writes=False,distinct_reviewers_required=len(stages),note='Counts exclude you as a hypothetical requester. Actual record access and distinct reviewer availability are checked at execution time.')
        self.r(action=='activate','Unknown policy action',404)
        self.r(type(data.get('expected_active_version')) is int and data['expected_active_version']==self.active_version(),'The active policy changed. Refresh before activating another version.',409)
        if version==0:self.db.execute('INSERT OR IGNORE INTO purchasing_policies VALUES(?,?,?,?,?)',(self.s.org,0,json.dumps(DEFAULT),self.s.user,now()))
        self.db.execute('INSERT INTO purchasing_policy_state VALUES(?,?) ON CONFLICT(org_id) DO UPDATE SET active_version=excluded.active_version',(self.s.org,version))
        self.s.audit('activate','purchasing_policy',str(version),{'new_submissions_only':True});return self.list()
    @staticmethod
    def role_matches(actual,required):return actual==required or actual=='admin'
    def latest(self,requisition_id):
        row=self.db.execute('SELECT * FROM requisition_review_cycles WHERE org_id=? AND requisition_id=? ORDER BY cycle DESC LIMIT 1',(self.s.org,requisition_id)).fetchone()
        return dict(row) if row else None
    def bind(self,request,legacy=False):
        version=0 if legacy else self.active_version();definition=self.definition(version);amount=request['quantity']*request['unit_price'];branch='high_value_stages' if amount>definition['threshold'] else 'standard_stages'
        cycle=self.db.execute('SELECT COALESCE(MAX(cycle),0)+1 FROM requisition_review_cycles WHERE org_id=? AND requisition_id=?',(self.s.org,request['id'])).fetchone()[0]
        self.db.execute('INSERT INTO requisition_review_cycles VALUES(?,?,?,?,?,?,?,?,?,?)',(uid(),self.s.org,request['id'],cycle,version,definition['name'],amount,branch,json.dumps(definition[branch]),now()))
        return self.latest(request['id'])
    def eligible(self,request,stage,excluded):
        candidates=[]
        for member in self.s.rows('SELECT user_id,role FROM memberships WHERE org_id=? AND active=1',(self.s.org,)):
            if member['user_id'] in excluded or member['user_id']==request['created_by'] or not self.role_matches(member['role'],stage['reviewer_role']):continue
            try:type(self.s)(self.db,dict(org_id=self.s.org,user_id=member['user_id'],role=member['role'])).visible_record('requisitions',request['id'])
            except Exception as exc:
                if getattr(exc,'status',None) in (403,404):continue
                raise
            candidates.append(member['user_id'])
        return candidates
    def feasible(self,request,stages,excluded):
        """Bipartite matching avoids assigning one person to two approval stages."""
        edges=[self.eligible(request,stage,excluded) for stage in stages];assigned={}
        def match(index,visited):
            for candidate in edges[index]:
                if candidate in visited:continue
                visited.add(candidate)
                if candidate not in assigned or match(assigned[candidate],visited):assigned[candidate]=index;return True
            return False
        return all(match(index,set()) for index in sorted(range(len(stages)),key=lambda i:len(edges[i])))
    def decisions(self,cycle_id):
        return self.s.rows('SELECT d.*,u.name reviewer_name FROM requisition_stage_decisions d JOIN users u ON u.id=d.reviewer_id WHERE d.org_id=? AND d.cycle_id=? ORDER BY d.stage_index',(self.s.org,cycle_id))
    def progress(self,request):
        cycle=self.latest(request['id']);legacy=cycle is None
        if legacy:
            if request['status'] not in ('submitted',):return None
            cycle=dict(id=None,cycle=0,policy_version=0,policy_name='Independent purchase review (legacy submission)',amount=request['quantity']*request['unit_price'],branch='standard_stages',stages=json.dumps(DEFAULT['standard_stages']))
        stages=json.loads(cycle['stages']);decisions=[] if legacy else self.decisions(cycle['id']);approved={d['stage_index'] for d in decisions if d['decision']=='approved'};used={d['reviewer_id'] for d in decisions}
        pending=next((i for i in range(len(stages)) if i not in approved),None);submitted=request['status']=='submitted'
        eligible=submitted and pending is not None and self.s.user!=request['created_by'] and self.s.user not in used and self.role_matches(self.s.role,stages[pending]['reviewer_role'])
        can_approve=bool(eligible and self.feasible(request,stages[pending+1:],used|{self.s.user}))
        blocked=''
        if submitted and pending is not None and not self.feasible(request,stages[pending:],used):blocked='The remaining stages need different active reviewers with access to this request. Ask an administrator to review team roles and record access.'
        return {**{key:cycle[key] for key in ('id','cycle','policy_version','policy_name','amount','branch')},'legacy':legacy,'request_status':request['status'],'stages':[{**stage,'index':i,'state':'approved' if i in approved else 'rejected' if any(d['stage_index']==i and d['decision']=='rejected' for d in decisions) else 'pending' if submitted and i==pending else 'upcoming'} for i,stage in enumerate(stages)],'decisions':decisions,'pending_stage':pending,'can_review':bool(eligible),'can_approve':can_approve,'reviewer_note':'A different eligible reviewer must handle this stage so the remaining stages have distinct reviewers.' if eligible and not can_approve else '','blocked_reason':blocked,'requires_context':cycle['policy_version']>0 or len(stages)>1}
    def notify_stage(self,request,cycle):
        stages=json.loads(cycle['stages']);decisions=self.decisions(cycle['id']);used={d['reviewer_id'] for d in decisions};pending=len(decisions)
        if pending>=len(stages):return
        for reviewer in self.eligible(request,stages[pending],used):self.s.notify(reviewer,'Purchase review: '+request['item']+' · '+stages[pending]['label'],'requisition',request['id'])
    def submit(self,request):
        self.r(request['created_by']==self.s.user,'Only the requester may submit',403);self.r(request['status'] in ('draft','rejected'),'Only draft or rejected requests can be submitted',409)
        cycle=self.bind(request);self.db.execute("UPDATE requisitions SET status='submitted',submitted_at=? WHERE org_id=? AND id=?",(now(),self.s.org,request['id']));self.s.audit('submit','requisition',request['id'],{'cycle':cycle['cycle'],'policy_version':cycle['policy_version']});self.notify_stage(request,cycle)
    def review(self,request,data):
        self.r(request['created_by']!=self.s.user,'You cannot approve or reject your own requisition',403);self.r(request['status']=='submitted','This request is not awaiting review',409)
        cycle=self.latest(request['id']) or self.bind(request,True);stages=json.loads(cycle['stages']);decisions=self.decisions(cycle['id']);pending=len(decisions)
        self.r(pending<len(stages),'This approval cycle is complete',409)
        if cycle['policy_version']>0 or len(stages)>1 or 'cycle_id' in data or 'stage_index' in data:
            self.r(isinstance(data.get('cycle_id'),str) and data['cycle_id']==cycle['id'] and type(data.get('stage_index')) is int and data['stage_index']==pending,'The approval stage changed. Refresh this request before reviewing it.',409)
        self.r(self.role_matches(self.s.role,stages[pending]['reviewer_role']),'Your current role cannot review this stage',403)
        self.r(self.s.user not in {d['reviewer_id'] for d in decisions},'A different person must review each stage',403)
        decision=data.get('decision');self.r(isinstance(decision,str) and decision in ('approved','rejected'),'Choose approve or reject');comment=self.text(data,'comment',decision=='rejected',2000)
        if decision=='approved':self.r(self.feasible(request,stages[pending+1:],{d['reviewer_id'] for d in decisions}|{self.s.user}),'Another eligible reviewer must handle this stage so the remaining stages can be completed. Ask an administrator to review roles and access.',409)
        identifier=uid();timestamp=now()
        self.db.execute('INSERT INTO approvals VALUES(?,?,?,?,?,?,?)',(identifier,self.s.org,request['id'],self.s.user,decision,comment,timestamp))
        self.db.execute('INSERT INTO requisition_stage_decisions VALUES(?,?,?,?,?,?,?,?,?)',(identifier,self.s.org,cycle['id'],pending,self.s.user,self.s.role,decision,comment,timestamp))
        completed=decision=='approved' and pending+1==len(stages);status='rejected' if decision=='rejected' else 'approved' if completed else 'submitted'
        self.db.execute('UPDATE requisitions SET status=? WHERE org_id=? AND id=?',(status,self.s.org,request['id']))
        self.s.audit(decision if status!='submitted' else 'approve_stage','requisition',request['id'],{'cycle':cycle['cycle'],'policy_version':cycle['policy_version'],'stage_index':pending,'stage_label':stages[pending]['label'],'comment':comment})
        self.s.notify(request['created_by'],'Purchase review '+decision+': '+stages[pending]['label'],'requisition',request['id'])
        if status=='submitted':self.notify_stage(request,cycle)
    def assert_orderable(self,request):
        self.r(request['status']=='approved','Only approved requisitions can become purchase orders',409);cycle=self.latest(request['id'])
        if cycle:
            decisions=self.decisions(cycle['id']);stages=json.loads(cycle['stages'])
            self.r(len(decisions)==len(stages) and all(d['decision']=='approved' for d in decisions) and len({d['reviewer_id'] for d in decisions})==len(stages),'All distinct review stages must be approved before ordering',409)
