"""Sales, customer service, controlled app schemas and evidence-based knowledge lookup."""
import json
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation

def uid():return uuid.uuid4().hex
def now():return datetime.now(timezone.utc).isoformat()

class Business:
    def __init__(self,s,require,text,money,integer,date_value):
        self.s=s;self.db=s.db;self.r=require;self.text=text;self.money=money;self.integer=integer;self.date=date_value
    def revision(self,data,current):
        self.r(type(data.get('revision')) is int and data['revision']==current['revision'],'This record changed. Refresh before trying again.',409)
    def quote(self,record_id):
        record=self.s.visible_record('quotes',record_id)
        record['lines']=self.s.rows('SELECT * FROM quote_lines WHERE org_id=? AND quote_id=? ORDER BY position',(self.s.org,record_id))
        record['history']=[{**r,'snapshot':json.loads(r['snapshot'])} for r in self.s.rows('SELECT revision,snapshot,created_at FROM quote_history WHERE org_id=? AND quote_id=? ORDER BY revision DESC',(self.s.org,record_id))]
        return record
    def app(self,record_id):
        app=self.s.one('custom_apps',record_id)
        if app['scope']=='managers':self.s.allow('admin','manager','finance')
        app['fields']=json.loads(self.db.execute('SELECT fields FROM custom_schemas WHERE org_id=? AND app_id=? AND version=?',(self.s.org,record_id,app['current_version'])).fetchone()[0])
        return app
    def fields(self,fields):
        self.r(isinstance(fields,list) and 1<=len(fields)<=12,'Define between 1 and 12 fields')
        result=[];keys=set()
        for field in fields:
            self.r(isinstance(field,dict),'Invalid field definition')
            key=field.get('key');label=self.text(field,'label',limit=80);kind=field.get('type');required=field.get('required',False)
            self.r(isinstance(key,str) and re.fullmatch('[a-z][a-z0-9_]{0,39}',key) and key not in keys and key not in {'id','org_id','app_id','schema_version','created_at','created_by','project_id','revision','archived','payload','constructor','prototype'},'Field keys must be unique lowercase identifiers')
            self.r(isinstance(kind,str) and kind in ('text','longtext','number','money','date','boolean','choice','customer'),'Unsupported field type')
            self.r(type(required) is bool,'Required must be true or false');keys.add(key)
            item=dict(key=key,label=label,type=kind,required=required)
            if kind=='choice':
                options=field.get('options');self.r(isinstance(options,list) and 1<=len(options)<=20 and all(isinstance(o,str) and 0<len(o.strip())<=80 for o in options),'Choices need 1–20 nonempty text options')
                item['options']=list(dict.fromkeys(o.strip() for o in options))
            result.append(item)
        return result
    def payload(self,data,fields):
        self.r(isinstance(data,dict),'Form values must be an object')
        self.r(set(data)<= {f['key'] for f in fields},'Unrecognized form field')
        result={}
        for field in fields:
            key=field['key'];value=data.get(key);kind=field['type'];missing=value is None or value==''
            self.r(not field['required'] or not missing,field['label']+' is required')
            if missing:result[key]=None;continue
            if kind in ('text','longtext'):value=self.text(data,key,limit=10000 if kind=='longtext' else 500)
            elif kind=='money':value=self.money(data,key)
            elif kind=='number':
                self.r(isinstance(value,(str,int,float)) and not isinstance(value,bool),'Use a number for '+field['label'])
                try:
                    decimal=Decimal(str(value));self.r(decimal.is_finite() and abs(decimal)<=Decimal('1000000000') and decimal.as_tuple().exponent>=-6,'Number is outside the supported range');value=str(decimal)
                except InvalidOperation:self.r(False,'Invalid number')
            elif kind=='date':value=self.date(data,key,True)
            elif kind=='boolean':self.r(type(value) is bool,'Use a checkbox value')
            elif kind=='choice':self.r(isinstance(value,str) and value in field['options'],'Choose a valid '+field['label'])
            elif kind=='customer':value=self.s.one('customers',self.text(data,key,limit=32))['id']
            result[key]=value
        return result
    def get(self,path,query):
        parts=path.strip('/').split('/');resource=parts[1]
        if resource=='quotes':
            if len(parts)>2:return self.quote(parts[2])
            return [r for r in self.s.rows('SELECT q.*,c.name customer_name,p.name project_name FROM quotes q JOIN customers c ON c.id=q.customer_id LEFT JOIN projects p ON p.id=q.project_id WHERE q.org_id=? ORDER BY q.created_at DESC',(self.s.org,)) if self.s.can_record(r)]
        if resource=='sales-orders':
            if len(parts)>2:return self.s.visible_record('sales_orders',parts[2])
            return [r for r in self.s.rows('SELECT o.*,c.name customer_name FROM sales_orders o JOIN customers c ON c.id=o.customer_id WHERE o.org_id=? ORDER BY o.created_at DESC',(self.s.org,)) if self.s.can_record(r)]
        if resource=='tickets':
            if len(parts)>2:return self.s.visible_record('service_tickets',parts[2])
            return [r for r in self.s.rows('SELECT t.*,c.name customer_name,u.name assignee_name FROM service_tickets t LEFT JOIN customers c ON c.id=t.customer_id JOIN users u ON u.id=t.assignee_id WHERE t.org_id=? ORDER BY t.created_at DESC',(self.s.org,)) if self.s.can_record(r)]
        if resource=='custom-apps':
            if len(parts)==2:
                apps=[]
                for row in self.s.rows('SELECT id FROM custom_apps WHERE org_id=? ORDER BY created_at DESC',(self.s.org,)):
                    try:apps.append(self.app(row['id']))
                    except Exception as exc:
                        if getattr(exc,'status',None) not in (403,404):raise
                return apps
            app=self.app(parts[2])
            if len(parts)==3:
                app['versions']=[{**r,'fields':json.loads(r['fields'])} for r in self.s.rows('SELECT version,fields,created_at FROM custom_schemas WHERE org_id=? AND app_id=? ORDER BY version DESC',(self.s.org,app['id']))];return app
            self.r(parts[3]=='records','Not found',404)
            records=self.s.rows('SELECT * FROM custom_records WHERE org_id=? AND app_id=? ORDER BY created_at DESC',(self.s.org,app['id']))
            visible=[]
            for record in records:
                if not self.s.can_record(record):continue
                meta=self.db.execute('SELECT archived,revision FROM custom_record_state WHERE org_id=? AND record_id=?',(self.s.org,record['id'])).fetchone()
                record['archived']=bool(meta['archived']) if meta else False;record['revision']=meta['revision'] if meta else 1
                latest=self.db.execute('SELECT payload FROM custom_record_edits WHERE org_id=? AND record_id=? ORDER BY revision DESC LIMIT 1',(self.s.org,record['id'])).fetchone()
                record['original_payload']=json.loads(record['payload']);record['payload']=json.loads(latest[0] if latest else record['payload'])
                if len(parts)==5 and parts[4]==record['id']:
                    record['history']=[{**r,'payload':json.loads(r['payload'])} for r in self.s.rows('SELECT revision,payload,actor_id,created_at FROM custom_record_edits WHERE org_id=? AND record_id=? ORDER BY revision DESC',(self.s.org,record['id']))]
                    return record
                if len(parts)==4 and record['archived']==(query.get('archived',['0'])[0]=='1'):visible.append(record)
            self.r(len(parts)==4,'Record not found',404)
            return visible
        if resource=='brain':return self.brain(query)
        self.r(False,'Not found',404)
    def post(self,path,data):
        parts=path.strip('/').split('/');resource=parts[1];identifier=uid();timestamp=now()
        if resource=='quotes':
            if len(parts)==2:
                self.s.write();customer=self.s.one('customers',self.text(data,'customer_id',limit=32));project=self.s.project_id(data)
                lines=data.get('lines');self.r(isinstance(lines,list) and 1<=len(lines)<=50,'Add 1–50 quotation lines');clean=[];total=0
                for i,line in enumerate(lines):
                    self.r(isinstance(line,dict),'Invalid quotation line');description=self.text(line,'description',limit=500);quantity=self.integer(line,'quantity');price=self.money(line,'unit_price');amount=quantity*price;total+=amount;clean.append((uid(),self.s.org,identifier,i,description,quantity,price,amount))
                self.r(0<total<=100000000000,'Quotation total must be positive and within the supported limit')
                self.db.execute('INSERT INTO quotes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(identifier,self.s.org,self.text(data,'number',limit=80),customer['id'],project,self.text(data,'title',limit=200),self.text(data,'notes',False,10000),self.date(data,'valid_until'),total,'draft',1,self.s.user,timestamp,timestamp))
                self.db.executemany('INSERT INTO quote_lines VALUES(?,?,?,?,?,?,?,?)',clean);self.s.audit('create_draft','quote',identifier);return self.quote(identifier)
            quote=self.quote(parts[2]);action=parts[3] if len(parts)>3 else '';self.revision(data,quote)
            if action=='update':
                self.s.write();self.r(self.s.role in ('admin','manager') or quote['created_by']==self.s.user,'Only the author or a manager can edit this draft',403);self.r(quote['status']=='draft','Only draft quotations can be edited',409)
                project=self.s.project_id(data);self.r(project==quote['project_id'],'The original access context must remain unchanged')
                customer=self.s.one('customers',self.text(data,'customer_id',limit=32));lines=data.get('lines');self.r(isinstance(lines,list) and 1<=len(lines)<=50,'Add 1–50 quotation lines');clean=[];total=0
                for i,line in enumerate(lines):
                    self.r(isinstance(line,dict),'Invalid quotation line');description=self.text(line,'description',limit=500);quantity=self.integer(line,'quantity');price=self.money(line,'unit_price');amount=quantity*price;total+=amount;clean.append((uid(),self.s.org,quote['id'],i,description,quantity,price,amount))
                self.r(0<total<=100000000000,'Quotation total must be positive and within the supported limit')
                self.db.execute('INSERT INTO quote_history VALUES(?,?,?,?,?,?)',(self.s.org,quote['id'],quote['revision'],json.dumps({key:value for key,value in quote.items() if key!='history'}),self.s.user,timestamp))
                self.db.execute('UPDATE quotes SET number=?,customer_id=?,title=?,notes=?,valid_until=?,total=?,revision=revision+1,updated_at=? WHERE org_id=? AND id=?',(self.text(data,'number',limit=80),customer['id'],self.text(data,'title',limit=200),self.text(data,'notes',False,10000),self.date(data,'valid_until'),total,timestamp,self.s.org,quote['id']))
                self.db.execute('DELETE FROM quote_lines WHERE org_id=? AND quote_id=?',(self.s.org,quote['id']));self.db.executemany('INSERT INTO quote_lines VALUES(?,?,?,?,?,?,?,?)',clean);self.s.audit('edit_draft','quote',quote['id'],{'revision':quote['revision']+1});return self.quote(quote['id'])
            self.s.allow('admin','manager')
            transitions={'send':('draft','sent'),'accept':('sent','accepted'),'decline':('sent','declined')}
            if action in transitions:
                before,after=transitions[action];self.r(quote['status']==before,'Quotation must be '+before,409)
                if action=='accept':self.r(not quote['valid_until'] or quote['valid_until']>=datetime.now(timezone.utc).date().isoformat(),'This quotation has expired. Create a revised quotation.',409)
                self.db.execute('UPDATE quotes SET status=?,revision=revision+1,updated_at=? WHERE org_id=? AND id=?',(after,timestamp,self.s.org,quote['id']));self.s.audit(action,'quote',quote['id']);return self.quote(quote['id'])
            self.r(action=='order','Unknown sales action',404);self.r(quote['status']=='accepted','Record customer acceptance before creating an order',409)
            number='SO-'+quote['number']
            self.db.execute('INSERT INTO sales_orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(identifier,self.s.org,number,quote['id'],quote['customer_id'],quote['project_id'],quote['title'],quote['total'],'confirmed',None,self.s.user,timestamp))
            self.db.execute("UPDATE quotes SET status='converted',revision=revision+1,updated_at=? WHERE org_id=? AND id=?",(timestamp,self.s.org,quote['id']));self.s.audit('create_from_quote','sales_order',identifier);return self.s.one('sales_orders',identifier)
        if resource=='sales-orders':
            self.r(len(parts)==4,'Choose an order action',404);order=self.s.visible_record('sales_orders',parts[2]);action=parts[3]
            if action=='invoice':
                self.s.allow('admin','finance');self.r(order['status']!='cancelled' and not order['invoice_id'],'An eligible order without an invoice is required',409)
                invoice=self.s.post('/api/invoices',dict(number=self.text(data,'number',limit=80),customer_id=order['customer_id'],description='Sales order '+order['number']+': '+order['title'],total=f"{Decimal(order['total'])/100:.2f}",due_date=self.date(data,'due_date')))
                self.db.execute('UPDATE sales_orders SET invoice_id=? WHERE org_id=? AND id=?',(invoice['id'],self.s.org,order['id']));self.s.audit('draft_invoice','sales_order',order['id'],{'invoice_id':invoice['id']});return invoice
            self.s.allow('admin','manager');self.r(action in ('fulfil','cancel'),'Unknown order action',404);self.r(order['status']=='confirmed','Only confirmed orders can change state',409)
            if action=='cancel' and order['invoice_id']:
                linked=self.db.execute('SELECT status FROM invoices WHERE org_id=? AND id=?',(self.s.org,order['invoice_id'])).fetchone();self.r(linked and linked['status']=='void','Cancel the draft or reverse the linked invoice in Finance before cancelling this order',409)
            self.db.execute('UPDATE sales_orders SET status=? WHERE org_id=? AND id=?',('fulfilled' if action=='fulfil' else 'cancelled',self.s.org,order['id']));self.s.audit(action,'sales_order',order['id']);return self.s.one('sales_orders',order['id'])
        if resource=='tickets':
            self.s.write()
            if len(parts)==2:
                project=self.s.project_id(data);source=self.s.source(data,project);assignee=self.text(data,'assignee_id',limit=32);member=self.s.member(assignee);self.r(member['role']!='viewer','Select an owner who can process service tickets')
                if project:type(self.s)(self.db,dict(org_id=self.s.org,user_id=assignee,role=member['role'])).project(project)
                if source:type(self.s)(self.db,dict(org_id=self.s.org,user_id=assignee,role=member['role'])).message(source)
                customer=self.text(data,'customer_id',False,32) or None
                if customer:self.s.one('customers',customer)
                priority=data.get('priority','normal');self.r(isinstance(priority,str) and priority in ('low','normal','high','urgent'),'Choose a priority')
                self.db.execute('INSERT INTO service_tickets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(identifier,self.s.org,'TKT-'+identifier[:8].upper(),customer,project,self.text(data,'subject',limit=200),self.text(data,'description',limit=10000),priority,'open',assignee,source,'',1,self.s.user,timestamp,timestamp));self.s.audit('create','ticket',identifier)
                if assignee!=self.s.user:self.s.notify(assignee,'A service ticket was assigned to you','ticket',identifier)
                return self.s.one('service_tickets',identifier)
            self.r(len(parts)==4 and parts[3] in ('status','assign'),'Choose a ticket action',404);ticket=self.s.visible_record('service_tickets',parts[2]);self.revision(data,ticket)
            self.r(self.s.role in ('admin','manager') or self.s.user in (ticket['assignee_id'],ticket['created_by']),'Only the assignee, reporter or a manager can update this ticket',403)
            if parts[3]=='assign':
                assignee=self.text(data,'assignee_id',limit=32);member=self.s.member(assignee);self.r(member['role']!='viewer','Select an owner who can process service tickets');candidate=type(self.s)(self.db,dict(org_id=self.s.org,user_id=assignee,role=member['role']));candidate.visible_record('service_tickets',ticket['id'])
                self.db.execute('UPDATE service_tickets SET assignee_id=?,revision=revision+1,updated_at=? WHERE org_id=? AND id=?',(assignee,timestamp,self.s.org,ticket['id']));self.s.audit('assign','ticket',ticket['id'],{'from':ticket['assignee_id'],'to':assignee})
                if assignee!=self.s.user:self.s.notify(assignee,'A service ticket was assigned to you','ticket',ticket['id'])
                return self.s.one('service_tickets',ticket['id'])
            transitions={'open':('in_progress','waiting','resolved'),'in_progress':('waiting','resolved'),'waiting':('in_progress','resolved'),'resolved':('open','closed'),'closed':('open',)}
            status=data.get('status');self.r(isinstance(status,str) and status in transitions[ticket['status']],'Choose an allowed next status',409)
            resolution=self.text(data,'resolution',False,10000) or ticket['resolution'];self.r(status not in ('resolved','closed') or bool(resolution),'Add a resolution before resolving this ticket')
            self.db.execute('UPDATE service_tickets SET status=?,resolution=?,revision=revision+1,updated_at=? WHERE org_id=? AND id=?',(status,resolution,timestamp,self.s.org,ticket['id']));self.s.audit('status','ticket',ticket['id'],{'before':ticket['status'],'after':status});return self.s.one('service_tickets',ticket['id'])
        if resource=='custom-apps':
            if len(parts)==2 or (len(parts)==4 and parts[3]=='versions'):
                self.s.allow('admin');fields=self.fields(data.get('fields'))
                if len(parts)==2:
                    scope=data.get('scope','team');self.r(isinstance(scope,str) and scope in ('team','managers'),'Choose an app access scope')
                    self.r(self.db.execute('SELECT COUNT(*) FROM custom_apps WHERE org_id=?',(self.s.org,)).fetchone()[0]<50,'Workspace limit: 50 custom apps')
                    self.db.execute('INSERT INTO custom_apps VALUES(?,?,?,?,?,?,?,?,?)',(identifier,self.s.org,self.text(data,'name',limit=100),self.text(data,'description',False,2000),'layers',scope,1,self.s.user,timestamp));version=1
                else:
                    app=self.app(parts[2]);self.r(type(data.get('expected_version')) is int and data.get('expected_version')==app['current_version'],'This app definition changed. Refresh before saving.',409);identifier=app['id'];version=app['current_version']+1
                    prior={field['key']:field['type'] for version_row in self.s.rows('SELECT fields FROM custom_schemas WHERE org_id=? AND app_id=?',(self.s.org,identifier)) for field in json.loads(version_row['fields'])}
                    self.r(all(field['key'] not in prior or prior[field['key']]==field['type'] for field in fields),'Use a new field key when changing a field type')
                    self.db.execute('UPDATE custom_apps SET current_version=? WHERE org_id=? AND id=?',(version,self.s.org,identifier))
                self.db.execute('INSERT INTO custom_schemas VALUES(?,?,?,?,?)',(self.s.org,identifier,version,json.dumps(fields),timestamp));self.s.audit('save_schema','custom_app',identifier,{'version':version,'field_count':len(fields)});return self.app(identifier)
            if len(parts)==6 and parts[3]=='records':
                self.s.write();app=self.app(parts[2]);record=self.s.visible_record('custom_records',parts[4]);self.r(record['app_id']==app['id'],'Record not found',404)
                self.r(self.s.role in ('admin','manager') or record['created_by']==self.s.user,'Only the author or a manager can modify this record',403)
                self.db.execute('INSERT OR IGNORE INTO custom_record_state VALUES(?,?,0,1)',(self.s.org,record['id']))
                meta=self.db.execute('SELECT * FROM custom_record_state WHERE record_id=?',(record['id'],)).fetchone();self.revision(data,meta);revision=meta['revision']+1
                if parts[5]=='update':
                    self.r(not meta['archived'],'Restore the record before editing',409)
                    fields=json.loads(self.db.execute('SELECT fields FROM custom_schemas WHERE org_id=? AND app_id=? AND version=?',(self.s.org,app['id'],record['schema_version'])).fetchone()[0]);payload=self.payload(data.get('payload'),fields)
                    self.db.execute('INSERT INTO custom_record_edits VALUES(?,?,?,?,?,?)',(self.s.org,record['id'],revision,json.dumps(payload),self.s.user,timestamp));self.db.execute('UPDATE custom_record_state SET revision=? WHERE record_id=?',(revision,record['id']))
                else:
                    self.r(parts[5] in ('archive','restore'),'Unknown record action',404);archived=parts[5]=='archive';self.r(bool(meta['archived'])!=archived,'Record state already changed',409)
                    self.db.execute('UPDATE custom_record_state SET archived=?,revision=? WHERE record_id=?',(int(archived),revision,record['id']))
                self.s.audit(parts[5],'custom_record',record['id'],{'revision':revision});return self.get('/api/custom-apps/'+app['id']+'/records/'+record['id'],{})
            self.r(len(parts)==4 and parts[3]=='records','Unknown app action',404);self.s.write();app=self.app(parts[2])
            self.r(type(data.get('schema_version')) is int and data['schema_version']==app['current_version'],'The form changed. Reopen it before submitting.',409)
            project=self.s.project_id(data);payload=self.payload(data.get('payload'),app['fields'])
            self.db.execute('INSERT INTO custom_records VALUES(?,?,?,?,?,?,?,?)',(identifier,self.s.org,app['id'],app['current_version'],project,json.dumps(payload),self.s.user,timestamp));self.s.audit('create','custom_record',identifier,{'app_id':app['id'],'schema_version':app['current_version']});return {**self.s.one('custom_records',identifier),'payload':payload}
        self.r(False,'Not found',404)
    def brain(self,query):
        q=query.get('q',[''])[0].strip();self.r(len(q)<=160,'Search is too long');results=[]
        if q:
            self.r(len(q)>=2,'Enter at least two characters');needle=q.casefold()
            for endpoint,kind,title,body in [('customers','customer','name','notes'),('projects','project','name','description'),('tasks','task','title','description'),('documents','document','title','body'),('tickets','ticket','subject','description'),('quotes','quote','title','notes')]:
                records=self.get('/api/'+endpoint,{}) if endpoint in ('tickets','quotes') else self.s.get('/api/'+endpoint,{})
                for record in records:
                    content=str(record.get(title,''))+' '+str(record.get(body,''))+' '+str(record.get('number',''))+' '+str(record.get('filename',''))+' '+str(record.get('customer_name',''))
                    if needle in content.casefold():results.append(dict(kind=kind,id=record['id'],title=record[title],snippet=content[:240],created_at=record.get('updated_at') or record['created_at']))
            for app in self.get('/api/custom-apps',{}):
                for record in self.get('/api/custom-apps/'+app['id']+'/records',{}):
                    content=app['name']+' '+str(record['payload'])
                    if needle in content.casefold():results.append(dict(kind='custom_record',id=record['id'],app_id=app['id'],title=app['name']+' record',snippet=content[:240],created_at=record['created_at']))
            candidates=self.s.rows("SELECT id,body,created_at,conversation_id FROM messages WHERE org_id=? AND deleted_at IS NULL AND body LIKE ? ESCAPE '\\' ORDER BY created_at DESC LIMIT 300",(self.s.org,'%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'))
            for record in candidates:
                try:self.s.message(record['id'])
                except Exception as exc:
                    if getattr(exc,'status',None) in (403,404):continue
                    raise
                results.append(dict(kind='message',id=record['id'],title='Conversation evidence',snippet=record['body'][:240],created_at=record['created_at'],conversation_id=record['conversation_id']))
            results.sort(key=lambda r:r['created_at'],reverse=True)
        today=datetime.now(timezone.utc).date();tasks=self.s.get('/api/tasks',{});contracts=self.s.get('/api/contracts',{}) if self.s.role in ('admin','manager','finance') else []
        signals=[dict(kind='overdue_tasks',label='Overdue open tasks',count=len([t for t in tasks if t['status']!='done' and t['due_date'] and t['due_date']<today.isoformat()]),route='Tasks'),dict(kind='expiring_contracts',label='Contracts expiring in 30 days',count=len([c for c in contracts if c['status']=='active' and c['ends_on'] and today.isoformat()<=c['ends_on']<=(today+timedelta(days=30)).isoformat()]),route='Contracts')]
        finance=None
        if self.s.role in ('admin','finance'):
            invoices=self.s.get('/api/invoices',{});overdue=[i for i in invoices if i['status']=='issued' and i['due_date'] and i['due_date']<today.isoformat()];ledger=self.s.get('/api/ledger',{})
            cash=next((b['balance'] for b in ledger['balances'] if b['account']=='1000 Cash'),0)
            commitments=sum(o['total'] for o in self.s.get('/api/purchase-orders',{}) if o['status']=='issued')
            finance=dict(recorded_cash=cash,overdue_receivables=sum(i['total'] for i in overdue),issued_purchase_commitments=commitments,evidence=[dict(id=i['id'],number=i['number'],total=i['total'],due_date=i['due_date']) for i in overdue])
        return dict(query=q,results=results[:60],truncated=len(results)>60,signals=signals,finance=finance,generated=False,as_of=now())
