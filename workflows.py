"""Bounded, versioned automation. Runs and effects commit atomically with business actions."""
import json
import uuid
from datetime import datetime, timezone, timedelta

def stamp():return datetime.now(timezone.utc).isoformat()
def uid():return uuid.uuid4().hex

class Workflows:
    def __init__(self,service,require):self.s=service;self.db=service.db;self.require=require
    def definition(self,data):
        r=self.require
        r(isinstance(data,dict),'Choose a workflow definition')
        r(set(data)<= {'source','days','threshold','action','schedule'},'Unsupported workflow option')
        source=data.get('source');action=data.get('action');days=data.get('days',0);threshold=data.get('threshold',0)
        r(isinstance(source,str) and source in ('overdue_invoice','low_stock','expiring_contract'),'Choose a supported trigger')
        r(isinstance(action,str) and action in ('task','notification'),'Choose a supported action')
        r(type(days) is int and 0<=days<=365,'Days must be an integer from 0 to 365')
        r(type(threshold) is int and 0<=threshold<=1000000,'Stock threshold must be an integer from 0 to 1,000,000')
        r(data.get('schedule','manual') in ('manual','daily'),'Choose manual or daily execution')
        return dict(source=source,action=action,days=days,threshold=threshold,schedule=data.get('schedule','manual'))
    def list(self):
        self.s.allow('admin')
        rules=self.s.rows('SELECT * FROM workflow_rules WHERE org_id=? ORDER BY created_at DESC',(self.s.org,))
        for rule in rules:rule.update(self.detail(rule['id']))
        return rules
    def detail(self,rule_id):
        self.s.allow('admin');rule=self.s.one('workflow_rules',rule_id)
        versions=self.s.rows('SELECT * FROM workflow_versions WHERE org_id=? AND rule_id=? ORDER BY version DESC',(self.s.org,rule_id))
        for v in versions:v['definition']=json.loads(v['definition'])
        return {**rule,'versions':versions,'runs':self.s.rows('SELECT * FROM workflow_runs WHERE org_id=? AND rule_id=? ORDER BY created_at DESC LIMIT 30',(self.s.org,rule_id))}
    def create(self,data):
        self.s.allow('admin');name=data.get('name');self.require(isinstance(name,str) and 0<len(name.strip())<=160,'Use a name of 1–160 characters')
        definition=self.definition(data.get('definition'))
        self.require(self.db.execute('SELECT COUNT(*) FROM workflow_rules WHERE org_id=?',(self.s.org,)).fetchone()[0]<100,'This workspace supports at most 100 automation rules')
        rule=uid();self.db.execute('INSERT INTO workflow_rules VALUES(?,?,?,?,?,?,?)',(rule,self.s.org,name.strip(),self.s.user,0,0,stamp()))
        self.version(rule,definition);self.s.audit('create','workflow',rule);return self.detail(rule)
    def version(self,rule,definition):
        version=self.db.execute('SELECT COALESCE(MAX(version),0)+1 FROM workflow_versions WHERE rule_id=?',(rule,)).fetchone()[0]
        self.db.execute('INSERT INTO workflow_versions VALUES(?,?,?,?,?,?)',(self.s.org,rule,version,json.dumps(definition),self.s.user,stamp()))
        self.s.audit('save_version','workflow',rule,{'version':version})
    def owner(self,rule):
        member=self.db.execute('SELECT role FROM memberships WHERE org_id=? AND user_id=? AND active=1',(self.s.org,rule['owner_id'])).fetchone()
        self.require(member and member['role']=='admin','Rule owner must still be an active administrator',403)
        return type(self.s)(self.db,dict(org_id=self.s.org,user_id=rule['owner_id'],role=member['role']))
    def matches(self,definition,actor):
        today=datetime.now(timezone.utc).date();source=definition['source'];days=definition['days']
        if source=='overdue_invoice':
            rows=actor.get('/api/invoices',{});selected=[r for r in rows if r['status']=='issued' and r['due_date'] and r['due_date']<(today-timedelta(days=days)).isoformat()];kind='invoice'
        elif source=='low_stock':
            selected=[r for r in actor.get('/api/products',{}) if r['stock']<=definition['threshold']];kind='product'
        else:
            selected=[r for r in actor.get('/api/contracts',{}) if r['status']=='active' and r['ends_on'] and today.isoformat()<=r['ends_on']<=(today+timedelta(days=days)).isoformat()];kind='contract'
        self.require(len(selected)<=250,'More than 250 records match. Narrow the condition before executing.')
        return [dict(id=r['id'],kind=kind,label=r.get('number') or r.get('title') or r.get('name'),project_id=r.get('project_id')) for r in selected]
    def execute(self,rule,version,definition,trigger):
        actor=self.owner(rule);matches=self.matches(definition,actor);day=datetime.now(timezone.utc).date().isoformat();applied=0
        for item in matches:
            exists=self.db.execute('SELECT 1 FROM workflow_effects WHERE rule_id=? AND source_kind=? AND source_id=? AND run_day=?',(rule['id'],item['kind'],item['id'],day)).fetchone()
            if exists:continue
            if definition['action']=='task':
                output=actor.post('/api/tasks',dict(title=('Follow up: '+item['label'])[:200],description='Created by automation '+rule['name']+'. Source: '+item['kind']+' '+item['id'],assignee_id=rule['owner_id'],project_id=item['project_id'],due_date=day))['id'];kind='task'
            else:
                output=uid();kind='notification'
                self.db.execute('INSERT INTO notifications VALUES(?,?,?,?,?,?,?,?)',(output,self.s.org,rule['owner_id'],'Automation “'+rule['name']+'” matched '+item['label'],'workflow',rule['id'],None,stamp()))
            self.db.execute('INSERT INTO workflow_effects VALUES(?,?,?,?,?,?,?,?,?)',(uid(),self.s.org,rule['id'],item['kind'],item['id'],day,kind,output,stamp()));applied+=1
        result=dict(id=uid(),org_id=self.s.org,rule_id=rule['id'],version=version,run_day=day,trigger_kind=trigger,status='success',matched=len(matches),applied=applied,skipped=len(matches)-applied,error='',created_at=stamp())
        self.db.execute('INSERT INTO workflow_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',tuple(result.values()))
        actor.audit('execute','workflow',rule['id'],{'version':version,'matched':len(matches),'applied':applied,'trigger':trigger})
        return result
    def post(self,rule_id,action,data):
        self.s.allow('admin')
        if not rule_id:return self.create(data)
        rule=self.s.one('workflow_rules',rule_id)
        if action=='versions':self.version(rule_id,self.definition(data.get('definition')));return self.detail(rule_id)
        if action=='pause':
            self.db.execute('UPDATE workflow_rules SET enabled=0 WHERE org_id=? AND id=?',(self.s.org,rule_id));self.s.audit('pause','workflow',rule_id);return self.detail(rule_id)
        version=data.get('version',rule['active_version'])
        self.require(type(version) is int and version>0,'Select a saved version')
        row=self.db.execute('SELECT definition FROM workflow_versions WHERE org_id=? AND rule_id=? AND version=?',(self.s.org,rule_id,version)).fetchone();self.require(row is not None,'Version not found',404)
        definition=self.definition(json.loads(row[0]))
        if action=='simulate':return {'version':version,'matches':self.matches(definition,self.owner(rule)),'writes':False}
        if action=='activate':
            self.owner(rule);self.db.execute('UPDATE workflow_rules SET active_version=?,enabled=1 WHERE org_id=? AND id=?',(version,self.s.org,rule_id));self.s.audit('activate','workflow',rule_id,{'version':version});return self.detail(rule_id)
        if action=='run':
            self.require(rule['enabled'] and version==rule['active_version'],'Activate this version before running',409)
            return self.execute(rule,version,definition,'manual')
        self.require(False,'Unknown automation action',404)

def schedule_once(server):
    """One durable daily evaluation per rule. One transaction per tenant-scoped rule."""
    with server.connect_db() as db:ids=[r[0] for r in db.execute('SELECT id FROM workflow_rules WHERE enabled=1')]
    for rule_id in ids:
        with server.connect_db() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT * FROM workflow_rules WHERE id=? AND enabled=1',(rule_id,)).fetchone()
            if row is None:continue
            rule=dict(row);day=datetime.now(timezone.utc).date().isoformat()
            if db.execute("SELECT 1 FROM workflow_runs WHERE rule_id=? AND run_day=? AND trigger_kind='scheduled'",(rule_id,day)).fetchone():continue
            saved=db.execute('SELECT definition FROM workflow_versions WHERE rule_id=? AND version=?',(rule_id,rule['active_version'])).fetchone()
            definition=json.loads(saved[0])
            if definition['schedule']!='daily':continue
            service=server.Service(db,dict(org_id=rule['org_id'],user_id=rule['owner_id'],role='admin'));engine=Workflows(service,server.require)
            db.execute('SAVEPOINT execution')
            try:engine.execute(rule,rule['active_version'],definition,'scheduled')
            except server.APIError as exc:
                db.execute('ROLLBACK TO execution')
                db.execute('INSERT INTO workflow_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(uid(),rule['org_id'],rule_id,rule['active_version'],day,'scheduled','blocked',0,0,0,exc.message,stamp()))
            db.execute('RELEASE execution')
