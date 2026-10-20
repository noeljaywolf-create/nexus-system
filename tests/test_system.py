"""Integration tests against the real HTTP server and an isolated temporary database."""
import base64
import concurrent.futures
import http.client
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

class Client:
    def __init__(self,port): self.port=port;self.cookie='';self.csrf=''
    def call(self,path,method='GET',data=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=60)
        hs={'Content-Type':'application/json','Cookie':self.cookie,'X-CSRF-Token':self.csrf}
        if headers: hs.update(headers)
        body=json.dumps(data or {}) if method!='GET' else None
        conn.request(method,'/api'+path,body,hs)
        response=conn.getresponse();payload=response.read();content_type=response.getheader('Content-Type','')
        if response.getheader('Set-Cookie'): self.cookie=response.getheader('Set-Cookie').split(';')[0]
        result=json.loads(payload) if 'json' in content_type else payload
        if isinstance(result,dict) and result.get('csrf'): self.csrf=result['csrf']
        status=response.status;conn.close();return status,result
    def ok(self,path,method='GET',data=None):
        status,result=self.call(path,method,data)
        if status!=200: raise AssertionError(f'{method} {path} -> {status}: {result}')
        return result

class SystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp_root=server.ROOT/'.test-runs'
        temp_root.mkdir(exist_ok=True)
        cls.test_dir=temp_root/('run-'+uuid.uuid4().hex)
        cls.test_dir.mkdir()
        cls.old_db=server.DB_PATH;server.DB_PATH=cls.test_dir/'test.sqlite3';server.initialize()
        class QuietHandler(server.Handler):
            def log_message(self,*args): pass
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start();cls.port=cls.http.server_port
        cls.password='Integration-test-passphrase-42'
        cls.admin=Client(cls.port);cls.admin.ok('/auth/register','POST',{'email':'owner@alpha.test','password':cls.password,'name':'Alpha Owner','organization':'Alpha Business','currency':'USD'})
        cls.me=cls.admin.ok('/me');cls.org=cls.me['organization']['id'];cls.owner_id=cls.me['user']['user_id']
        cls.actors={}
        for role in ['manager','member','finance','viewer']:
            inv=cls.admin.ok('/invitations','POST',{'email':role+'@alpha.test','role':role,'department':'Testing'})
            c=Client(cls.port);c.ok('/auth/join','POST',{'token':inv['token'],'email':role+'@alpha.test','password':cls.password,'name':role.title()})
            cls.actors[role]=(c,c.ok('/me')['user']['user_id'])
        cls.other=Client(cls.port);cls.other.ok('/auth/register','POST',{'email':'owner@beta.test','password':cls.password,'name':'Beta Owner','organization':'Beta Business'})
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.thread.join(timeout=3)
        server.DB_PATH=cls.old_db
        for name in ('test.sqlite3','test.sqlite3-wal','test.sqlite3-shm'):
            (cls.test_dir/name).unlink(missing_ok=True)
        cls.test_dir.rmdir()
    def project(self,private=False,client=None):
        return (client or self.admin).ok('/projects','POST',{'name':'Project '+uuid.uuid4().hex[:8],'private':private,'budget':'1200.55'})
    def channel(self,project):
        return next(c for c in self.admin.ok('/conversations') if c['project_id']==project['id'])
    def request(self,client=None,project_id=None):
        return (client or self.admin).ok('/requisitions','POST',{'item':'Fire extinguishers','quantity':40,'unit_price':'120.25','project_id':project_id})
    def invoice(self,total='180.25'):
        customer=self.admin.ok('/customers','POST',{'name':'Customer '+uuid.uuid4().hex[:8]})
        return self.admin.ok('/invoices','POST',{'number':'INV-'+uuid.uuid4().hex[:8],'customer_id':customer['id'],'description':'Consulting services','total':total})

    def test_authentication_csrf_and_origin(self):
        self.assertEqual(Client(self.port).call('/projects')[0],401)
        self.assertEqual(self.admin.call('/projects','POST',{'name':'Blocked'},{'X-CSRF-Token':''})[0],403)
        self.assertEqual(self.admin.call('/projects','POST',{'name':'Blocked'},{'Origin':'https://evil.test'})[0],403)
        self.assertEqual(self.admin.call('/projects','POST',{'name':'Blocked'},{'Host':'evil.test'})[0],403)
        status,html=self.admin.call('/health');self.assertEqual(status,200)

    def test_persistence_and_password_storage(self):
        p=self.project()
        with server.connect_db() as db:
            self.assertEqual(db.execute('SELECT name FROM projects WHERE id=?',(p['id'],)).fetchone()[0],p['name'])
            hashed=db.execute('SELECT password_hash FROM users WHERE email=?',('owner@alpha.test',)).fetchone()[0]
            self.assertTrue(hashed.startswith('pbkdf2_sha256$600000$'));self.assertNotIn(self.password,hashed)
            session=db.execute('SELECT token_hash FROM sessions LIMIT 1').fetchone()[0];self.assertEqual(len(session),64)

    def test_tenant_isolation(self):
        p=self.project();self.assertNotIn(p['id'],[x['id'] for x in self.other.ok('/projects')])
        self.assertEqual(self.other.call('/projects/'+p['id'],'PATCH',{'status':'complete'})[0],404)
        c=self.channel(p);self.assertEqual(self.other.call('/conversations/'+c['id']+'/messages')[0],404)
        self.assertEqual(self.other.call('/tasks','POST',{'title':'Attack','project_id':p['id'],'assignee_id':self.owner_id})[0],404)

    def test_private_project_membership_and_revocation(self):
        p=self.project(True);c=self.channel(p);member,user_id=self.actors['member']
        self.assertEqual(member.call('/conversations/'+c['id']+'/messages')[0],404)
        self.admin.ok('/projects/'+p['id']+'/members','POST',{'user_id':user_id})
        member.ok('/conversations/'+c['id']+'/messages','POST',{'body':'Authorized update'})
        self.admin.ok('/projects/'+p['id']+'/members','POST',{'user_id':user_id,'remove':True})
        self.assertEqual(member.call('/conversations/'+c['id']+'/messages')[0],404)

    def test_project_ownership_permission(self):
        p=self.project();member,user_id=self.actors['member']
        self.assertEqual(member.call('/projects/'+p['id'],'PATCH',{'status':'complete'})[0],403)
        self.assertEqual(member.call('/projects/'+p['id']+'/members','POST',{'user_id':user_id})[0],403)
        self.admin.ok('/projects/'+p['id'],'PATCH',{'status':'at_risk'})

    def test_messages_threads_reactions_read_receipts(self):
        p=self.project();c=self.channel(p);member,_=self.actors['member']
        first=self.admin.ok('/conversations/'+c['id']+'/messages','POST',{'body':'We need 40 fire extinguishers for the new site.'})
        reply=member.ok('/conversations/'+c['id']+'/messages','POST',{'body':'Review before ordering.','parent_id':first['id']})
        self.assertEqual(reply['parent_id'],first['id'])
        member.ok('/messages/'+first['id']+'/react','POST',{'emoji':'👍'})
        member.ok('/conversations/'+c['id']+'/read','POST')
        rows=self.admin.ok('/conversations/'+c['id']+'/messages')
        self.assertEqual(rows[0]['reactions'][0]['count'],1);self.assertTrue(rows[0]['read_by'])
        member.ok('/messages/'+first['id']+'/react','POST',{'emoji':'👍'})
        self.assertEqual(self.admin.ok('/conversations/'+c['id']+'/messages')[0]['reactions'],[])
        self.admin.ok('/messages/'+first['id'],'PATCH',{'pinned':True})
        self.assertEqual(self.admin.ok('/conversations/'+c['id']+'/messages')[0]['pinned'],1)

    def test_context_action_extraction_and_task(self):
        p=self.project();c=self.channel(p)
        m=self.admin.ok('/conversations/'+c['id']+'/messages','POST',{'body':'We need 40 fire extinguishers for the new site.'})
        draft=self.admin.ok('/extract','POST',{'message_id':m['id']})
        self.assertEqual((draft['quantity'],draft['item']),(40,'fire extinguishers'))
        self.assertTrue(draft['requires_review']);self.assertEqual(draft['method'],'rule_based')
        task=self.admin.ok('/tasks','POST',{'title':'Arrange equipment','project_id':p['id'],'source_message_id':m['id'],'assignee_id':self.owner_id,'due_date':'2026-11-02'})
        self.assertEqual(task['source_message_id'],m['id'])
        task=self.admin.ok('/tasks/'+task['id'],'PATCH',{'status':'done'});self.assertEqual(task['status'],'done')
        wrong=self.project()
        self.assertEqual(self.admin.call('/requisitions','POST',{'item':'Mismatch','quantity':1,'project_id':wrong['id'],'source_message_id':m['id']})[0],400)

    def test_message_edits_history_and_expiration(self):
        c=self.channel(self.project());m=self.admin.ok('/conversations/'+c['id']+'/messages','POST',{'body':'Original'})
        self.admin.ok('/messages/'+m['id'],'PATCH',{'body':'Edited'})
        with server.connect_db() as db:
            self.assertEqual(db.execute('SELECT body FROM message_history WHERE message_id=?',(m['id'],)).fetchone()[0],'Original')
            db.execute('UPDATE messages SET created_at=? WHERE id=?',('2020-01-01T00:00:00+00:00',m['id']))
        self.assertEqual(self.admin.call('/messages/'+m['id'],'PATCH',{'body':'Too late'})[0],403)

    def test_attachments_access_and_removal(self):
        p=self.project(True);c=self.channel(p);m=self.admin.ok('/conversations/'+c['id']+'/messages','POST',{'body':'Safety document'})
        a=self.admin.ok('/messages/'+m['id']+'/attachments','POST',{'filename':'Safety.txt','mime':'text/plain','content':base64.b64encode(b'Authorized data').decode()})
        self.assertEqual(self.admin.ok('/attachments/'+a['id']),b'Authorized data')
        self.assertEqual(self.actors['member'][0].call('/attachments/'+a['id'])[0],404)
        self.admin.ok('/messages/'+m['id'],'PATCH',{'deleted':True})
        self.assertEqual(self.admin.call('/attachments/'+a['id'])[0],404)

    def test_direct_conversation_is_private_even_from_other_admin(self):
        manager,manager_id=self.actors['manager'];member,member_id=self.actors['member']
        c=member.ok('/conversations','POST',{'name':'Private discussion','kind':'direct','members':[manager_id]})
        member.ok('/conversations/'+c['id']+'/messages','POST',{'body':'Private message'})
        self.assertEqual(self.admin.call('/conversations/'+c['id']+'/messages')[0],404)
        self.assertEqual(len(manager.ok('/conversations/'+c['id']+'/messages')),1)

    def test_viewer_write_and_finance_permissions(self):
        viewer,_=self.actors['viewer'];member,_=self.actors['member']
        viewer.ok('/projects')
        self.assertEqual(viewer.call('/projects','POST',{'name':'Blocked'})[0],403)
        self.assertEqual(viewer.call('/tasks','POST',{'title':'Blocked','assignee_id':self.owner_id})[0],403)
        self.assertEqual(member.call('/invoices')[0],403)
        self.assertEqual(member.call('/audit')[0],403)
        self.assertIsNone(member.ok('/dashboard')['revenue'])

    def test_requisition_full_approval_and_purchase_order(self):
        manager,_=self.actors['manager'];r=self.request();rid=r['id']
        supplier=self.admin.ok('/suppliers','POST',{'name':'Safety supplier'})
        self.assertEqual(self.admin.call('/requisitions/'+rid+'/order','POST',{'supplier_id':supplier['id']})[0],409)
        self.admin.ok('/requisitions/'+rid+'/submit','POST')
        self.assertEqual(self.admin.call('/requisitions/'+rid+'/review','POST',{'decision':'approved'})[0],403)
        manager.ok('/requisitions/'+rid+'/review','POST',{'decision':'approved','comment':'Budget checked'})
        order=self.admin.ok('/requisitions/'+rid+'/order','POST',{'supplier_id':supplier['id']})
        self.assertEqual(order['total'],481000)
        self.assertEqual(self.admin.call('/requisitions/'+rid+'/order','POST',{'supplier_id':supplier['id']})[0],409)
        approvals=next(x for x in self.admin.ok('/requisitions') if x['id']==rid)['approvals'];self.assertEqual(len(approvals),1)

    def test_rejected_request_can_be_edited_and_resubmitted(self):
        r=self.request();rid=r['id'];manager,_=self.actors['manager']
        self.admin.ok('/requisitions/'+rid+'/submit','POST')
        self.assertEqual(manager.call('/requisitions/'+rid+'/review','POST',{'decision':'rejected','comment':''})[0],400)
        manager.ok('/requisitions/'+rid+'/review','POST',{'decision':'rejected','comment':'Please amend quantity'})
        updated=self.admin.ok('/requisitions/'+rid,'PATCH',{'item':'Fire extinguishers','quantity':20,'unit_price':'110','notes':'Amended'})
        self.assertEqual(updated['status'],'draft');self.admin.ok('/requisitions/'+rid+'/submit','POST')

    def test_concurrent_approval_only_one_transition(self):
        r=self.request();self.admin.ok('/requisitions/'+r['id']+'/submit','POST');manager,_=self.actors['manager']
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:manager.call('/requisitions/'+r['id']+'/review','POST',{'decision':'approved'})[0],range(2)))
        self.assertEqual(sorted(results),[200,409])

    def test_finance_double_entry_payment_and_duplicate_protection(self):
        inv=self.invoice();iid=inv['id']
        self.admin.ok('/invoices/'+iid+'/issue','POST')
        self.assertEqual(self.admin.call('/invoices/'+iid+'/issue','POST')[0],409)
        self.admin.ok('/invoices/'+iid+'/payment','POST')
        self.assertEqual(self.admin.call('/invoices/'+iid+'/payment','POST')[0],409)
        with server.connect_db() as db:
            entries=db.execute('SELECT e.id,SUM(l.debit) debit,SUM(l.credit) credit FROM ledger_entries e JOIN ledger_lines l ON l.entry_id=e.id WHERE e.invoice_id=? GROUP BY e.id',(iid,)).fetchall()
            self.assertEqual(len(entries),2)
            for e in entries:self.assertEqual(e['debit'],e['credit']);self.assertEqual(e['debit'],18025)
        self.assertEqual(next(i for i in self.admin.ok('/invoices') if i['id']==iid)['status'],'paid')

    def test_void_reverses_original_posting(self):
        inv=self.invoice('99.99');iid=inv['id'];self.admin.ok('/invoices/'+iid+'/issue','POST');self.admin.ok('/invoices/'+iid+'/void','POST')
        with server.connect_db() as db:
            balance=db.execute('SELECT SUM(l.debit-l.credit) FROM ledger_lines l JOIN ledger_entries e ON e.id=l.entry_id WHERE e.invoice_id=?',(iid,)).fetchone()[0]
            self.assertEqual(balance,0)
            revenue=db.execute("SELECT SUM(l.credit-l.debit) FROM ledger_lines l JOIN ledger_entries e ON e.id=l.entry_id WHERE e.invoice_id=? AND l.account='4000 Revenue'",(iid,)).fetchone()[0];self.assertEqual(revenue,0)

    def test_money_validation_and_no_partial_write(self):
        before=len(self.admin.ok('/requisitions'))
        for amount in ['NaN','Infinity','-1','0.001']:
            self.assertEqual(self.admin.call('/requisitions','POST',{'item':'Invalid','quantity':2,'unit_price':amount})[0],400)
        self.assertEqual(self.admin.call('/requisitions','POST',{'item':'Invalid','quantity':1.5,'unit_price':'1'})[0],400)
        self.assertEqual(len(self.admin.ok('/requisitions')),before)

    def test_stock_transactions_prevent_negative_inventory(self):
        p=self.admin.ok('/products','POST',{'name':'Extinguisher','sku':'SKU-'+uuid.uuid4().hex,'unit_price':'25.50'})
        p=self.admin.ok('/products/'+p['id']+'/stock','POST',{'quantity':40,'reason':'Initial delivery'});self.assertEqual(p['stock'],40)
        self.assertEqual(self.admin.call('/products/'+p['id']+'/stock','POST',{'quantity':-41,'reason':'Overdraw'})[0],400)
        self.assertEqual(next(x for x in self.admin.ok('/products') if x['id']==p['id'])['stock'],40)

    def test_documents_meetings_and_notifications(self):
        p=self.project(True);member,member_id=self.actors['member']
        doc=self.admin.ok('/documents','POST',{'title':'Private policy','body':'Do not disclose','project_id':p['id']})
        self.assertNotIn(doc['id'],[d['id'] for d in member.ok('/documents')])
        meeting=self.admin.ok('/meetings','POST',{'title':'Planning','starts_at':'2026-11-02T08:00:00+02:00','ends_at':'2026-11-02T09:00:00+02:00','attendees':[member_id],'notes':'Review agenda'})
        member.ok('/meetings/'+meeting['id']+'/rsvp','POST',{'rsvp':'accepted'})
        self.assertTrue(any(n['record_id']==meeting['id'] for n in member.ok('/notifications')))

    def test_mentions_do_not_leak_private_context(self):
        p=self.project(True);c=self.channel(p);member,_=self.actors['member']
        msg=self.admin.ok('/conversations/'+c['id']+'/messages','POST',{'body':'@member@alpha.test please review'})
        self.assertFalse(any(n['record_id']==msg['id'] for n in member.ok('/notifications')))

    def test_invitation_single_use_and_role_validation(self):
        email='new-'+uuid.uuid4().hex[:8]+'@alpha.test';inv=self.admin.ok('/invitations','POST',{'email':email,'role':'viewer'})
        c=Client(self.port);d={'email':email,'name':'New Viewer','password':self.password,'token':inv['token']}
        c.ok('/auth/join','POST',d);self.assertEqual(c.ok('/me')['user']['role'],'viewer')
        self.assertEqual(Client(self.port).call('/auth/join','POST',d)[0],400)
        self.assertEqual(self.admin.call('/invitations','POST',{'email':'x@alpha.test','role':'root'})[0],400)

    def test_audit_and_ledger_are_append_only(self):
        inv=self.invoice();self.admin.ok('/invoices/'+inv['id']+'/issue','POST')
        with server.connect_db() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('UPDATE ledger_lines SET debit=1')
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM ledger_entries')
            with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE audit_log SET action='hidden'")
        rows=self.admin.ok('/audit');self.assertTrue(any(a['action']=='issue' and a['record_id']==inv['id'] for a in rows))

    def test_last_admin_and_existing_session_role_change(self):
        self.assertEqual(self.admin.call('/people/'+self.owner_id,'PATCH',{'role':'viewer'})[0],400)
        email='role-'+uuid.uuid4().hex[:8]+'@alpha.test';inv=self.admin.ok('/invitations','POST',{'email':email,'role':'member'})
        c=Client(self.port);c.ok('/auth/join','POST',{'email':email,'name':'Role Change','password':self.password,'token':inv['token']});user_id=c.ok('/me')['user']['user_id']
        self.admin.ok('/people/'+user_id,'PATCH',{'role':'viewer'})
        self.assertEqual(c.call('/projects','POST',{'name':'Blocked after demotion'})[0],403)

    def test_login_logout_and_invalid_credentials(self):
        c=Client(self.port);self.assertEqual(c.call('/auth/login','POST',{'email':'owner@alpha.test','password':'wrong'})[0],401)
        c.ok('/auth/login','POST',{'email':'owner@alpha.test','password':self.password});c.ok('/me');c.ok('/auth/logout','POST')
        self.assertEqual(c.call('/me')[0],401)

    def test_private_message_derived_records_keep_access(self):
        manager,manager_id=self.actors['manager'];member,member_id=self.actors['member']
        c=member.ok('/conversations','POST',{'name':'Confidential buying','kind':'direct','members':[manager_id]})
        m=member.ok('/conversations/'+c['id']+'/messages','POST',{'body':'We need 3 confidential devices.'})
        r=member.ok('/requisitions','POST',{'item':'Confidential devices','quantity':3,'source_message_id':m['id']})
        task=member.ok('/tasks','POST',{'title':'Confidential follow-up','source_message_id':m['id'],'assignee_id':manager_id})
        self.assertNotIn(r['id'],[r['id'] for r in self.admin.ok('/requisitions')])
        self.assertNotIn(task['id'],[t['id'] for t in self.admin.ok('/tasks')])
        self.assertEqual(member.call('/tasks','POST',{'title':'Leak attempt','source_message_id':m['id'],'assignee_id':self.owner_id})[0],400)
        self.assertEqual(self.admin.call('/requisitions/'+r['id']+'/submit','POST')[0],404)

    def test_parallel_reads_and_workspace_switch_authorization(self):
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            statuses=list(pool.map(lambda _:self.admin.call('/projects')[0],range(16)))
        self.assertTrue(all(s==200 for s in statuses))
        other_org=self.other.ok('/me')['organization']['id']
        self.assertEqual(self.admin.call('/auth/switch','POST',{'org_id':other_org})[0],403)
        self.assertEqual(self.admin.ok('/workspaces')[0]['id'],self.org)

    def test_assets_contracts_and_organization_units(self):
        p=self.project(True)
        asset=self.admin.ok('/assets','POST',{'name':'Site generator','tag':'AS-'+uuid.uuid4().hex,'category':'Equipment','project_id':p['id'],'purchase_value':'1200.50'})
        self.assertEqual(asset['purchase_value'],120050)
        self.admin.ok('/assets/'+asset['id'],'PATCH',{'status':'maintenance'})
        self.assertNotIn(asset['id'],[a['id'] for a in self.actors['member'][0].ok('/assets')])
        contract=self.admin.ok('/contracts','POST',{'title':'Generator hire','counterparty':'Equipment supplier','kind':'supplier','value':'2500','starts_on':'2026-10-20','ends_on':'2026-11-20','project_id':p['id']})
        self.admin.ok('/contracts/'+contract['id'],'PATCH',{'status':'active'})
        self.assertEqual(self.actors['member'][0].call('/contracts')[0],403)
        unit=self.admin.ok('/organization-units','POST',{'name':'Branch '+uuid.uuid4().hex[:6],'kind':'branch','location':'Harare'})
        self.assertTrue(any(u['id']==unit['id'] for u in self.admin.ok('/organization-units')))

    def test_extension_contracts_validate_and_isolate(self):
        p=self.project(True);package='construction-costing'
        self.assertEqual(self.actors['member'][0].call('/packages/'+package+'/activate','POST')[0],403)
        self.admin.ok('/packages/'+package+'/activate','POST')
        record=self.admin.ok('/packages/'+package+'/records','POST',{'project_id':p['id'],'description':'Safety materials','category':'materials','amount':'4800.25','date':'2026-10-20','notes':'Supplier quote'})
        self.assertEqual(record['payload']['amount'],480025)
        self.assertNotIn(record['id'],[r['id'] for r in self.actors['member'][0].ok('/packages/'+package+'/records')])
        self.assertEqual(self.other.ok('/packages/'+package+'/records'),[])
        self.assertEqual(self.admin.call('/packages/'+package+'/records','POST',{'project_id':p['id'],'description':'Bad','category':'invalid','amount':'1','date':'2026-10-20'})[0],400)
        package='professional-timesheets';self.admin.ok('/packages/'+package+'/activate','POST')
        r=self.admin.ok('/packages/'+package+'/records','POST',{'project_id':p['id'],'description':'Design review','minutes':90,'hourly_rate':'60','date':'2026-10-20','billing':'billable'})
        self.assertEqual(r['payload']['minutes'],90)

    def test_ai_provider_receives_only_authorized_selected_context(self):
        received=[]
        class Provider(server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append(data)
                body=json.dumps({'choices':[{'message':{'content':'Generated verification response'}}]}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        provider=server.ThreadingHTTPServer(('127.0.0.1',0),Provider)
        thread=threading.Thread(target=provider.serve_forever,daemon=True);thread.start()
        try:
            p=self.project(True);c=self.channel(p);self.admin.ok('/conversations/'+c['id']+'/messages','POST',{'body':'Authorized context only'})
            with patch.dict(os.environ,{'NEXUS_AI_ENDPOINT':f'http://127.0.0.1:{provider.server_port}/v1/chat/completions','NEXUS_AI_MODEL':'test-model','NEXUS_AI_API_KEY':''}):
                result=self.admin.ok('/assistant','POST',{'conversation_id':c['id'],'action':'summary'})
                self.assertEqual(result['text'],'Generated verification response')
                self.assertEqual(len(received),1);self.assertIn('Authorized context only',received[0]['messages'][1]['content'])
                self.assertEqual(self.actors['member'][0].call('/assistant','POST',{'conversation_id':c['id'],'action':'summary'})[0],404)
                self.assertEqual(len(received),1)
            with patch.dict(os.environ,{'NEXUS_AI_ENDPOINT':'','NEXUS_AI_MODEL':''}):
                self.assertEqual(self.admin.call('/assistant','POST',{'conversation_id':c['id'],'action':'summary'})[0],503)
        finally:provider.shutdown();provider.server_close();thread.join(timeout=3)

    def test_invoice_context_enforces_finance_permission(self):
        inv=self.invoice();c=self.admin.ok('/record-conversations','POST',{'record_kind':'invoice','record_id':inv['id']})
        m=self.admin.ok('/conversations/'+c['id']+'/messages','POST',{'body':'@member@alpha.test confidential invoice review'})
        member,member_id=self.actors['member']
        self.assertEqual(member.call('/conversations/'+c['id']+'/messages')[0],403)
        self.assertNotIn(c['id'],[c['id'] for c in member.ok('/conversations')])
        self.assertFalse(any(n['record_id']==m['id'] for n in member.ok('/notifications')))
        self.assertEqual(self.admin.call('/tasks','POST',{'title':'Accounts task','source_message_id':m['id'],'assignee_id':member_id})[0],400)
        self.assertEqual(self.other.call('/record-conversations','POST',{'record_kind':'invoice','record_id':inv['id']})[0],404)

    def test_context_conversation_follows_private_record_revocation(self):
        p=self.project(True);member,member_id=self.actors['member']
        self.admin.ok('/projects/'+p['id']+'/members','POST',{'user_id':member_id})
        task=self.admin.ok('/tasks','POST',{'title':'Private task','project_id':p['id'],'assignee_id':member_id})
        c=self.admin.ok('/record-conversations','POST',{'record_kind':'task','record_id':task['id']})
        m=member.ok('/conversations/'+c['id']+'/messages','POST',{'body':'We need 5 devices for this project.'})
        extracted=member.ok('/extract','POST',{'message_id':m['id']});self.assertEqual(extracted['project_id'],p['id'])
        self.admin.ok('/projects/'+p['id']+'/members','POST',{'user_id':member_id,'remove':True})
        self.assertEqual(member.call('/conversations/'+c['id']+'/messages')[0],404)
        self.assertEqual(member.call('/messages/'+m['id'])[0],404)

    def test_source_message_context_lookup(self):
        c=self.channel(self.project());m=self.admin.ok('/conversations/'+c['id']+'/messages','POST',{'body':'Source action context'})
        rows=self.admin.ok('/conversations/'+c['id']+'/messages?around='+m['id'])
        self.assertTrue(any(x['id']==m['id'] for x in rows))
        self.assertEqual(self.admin.ok('/messages/'+m['id'])['conversation_id'],c['id'])

    def upload(self,client=None,**options):
        d={'filename':'operations.txt','content':base64.b64encode(b'Verified document content').decode(),'folder':'Operations','tags':['safety','policy']}
        d.update(options)
        return (client or self.admin).ok('/document-uploads','POST',d)

    def test_document_upload_preview_and_version_history(self):
        from demo_data import sample_pdf
        pdf=sample_pdf('Verification PDF',['Approved content fixture'])
        result=self.upload(filename='verification.pdf',content=base64.b64encode(pdf).decode(),title='Verification policy')
        d=self.admin.ok('/documents/'+result['id']);self.assertEqual(d['title'],'Verification policy');self.assertEqual(d['versions'][0]['version'],1)
        self.assertEqual(self.admin.ok('/document-files/'+result['file_id']),pdf)
        self.assertEqual(self.admin.ok('/document-files/'+result['file_id']+'?preview=1'),pdf)
        v2=self.admin.ok('/documents/'+result['id']+'/versions','POST',{'filename':'verification.pdf','content':base64.b64encode(sample_pdf('Revision two',['Updated fixture'])).decode(),'version_note':'Updated policy'})
        self.assertEqual(v2['version'],2)
        d=self.admin.ok('/documents/'+result['id']);self.assertEqual(len(d['versions']),2);self.assertEqual(d['versions'][0]['version_note'],'Updated policy')
        self.assertEqual(self.admin.ok('/document-files/'+result['file_id']),pdf)
        with server.connect_db() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('UPDATE document_files SET version_note=? WHERE id=?',('Tamper',result['file_id']))

    def test_document_file_private_access_and_revocation(self):
        p=self.project(True);member,member_id=self.actors['member'];d=self.upload(project_id=p['id'])
        self.assertEqual(member.call('/document-files/'+d['file_id'])[0],404)
        self.assertNotIn(d['id'],[r['id'] for r in member.ok('/documents')])
        self.admin.ok('/projects/'+p['id']+'/members','POST',{'user_id':member_id})
        self.assertEqual(member.ok('/document-files/'+d['file_id']),b'Verified document content')
        self.admin.ok('/projects/'+p['id']+'/members','POST',{'user_id':member_id,'remove':True})
        self.assertEqual(member.call('/document-files/'+d['file_id'])[0],404)
        self.assertEqual(self.other.call('/document-files/'+d['file_id'])[0],404)
        self.assertEqual(Client(self.port).call('/document-files/'+d['file_id'])[0],401)

    def test_document_linked_finance_permissions(self):
        invoice=self.invoice();d=self.upload(record_kind='invoice',record_id=invoice['id'],title='Restricted invoice attachment')
        self.assertEqual(self.actors['member'][0].call('/document-files/'+d['file_id'])[0],403)
        self.assertNotIn(d['id'],[r['id'] for r in self.actors['member'][0].ok('/documents')])
        self.assertTrue(any(r['id']==d['id'] for r in self.actors['finance'][0].ok('/documents')))
        contexts=self.actors['member'][0].ok('/document-contexts');self.assertFalse(any(c['kind']=='invoice' for c in contexts))

    def test_document_archive_restore_and_edit_permissions(self):
        d=self.upload();member,_=self.actors['member']
        self.assertEqual(member.call('/documents/'+d['id'],'PATCH',{'title':'Unauthorized rename'})[0],403)
        self.admin.ok('/documents/'+d['id'],'PATCH',{'folder':'Policies','tags':['approved'],'archived':True})
        self.assertNotIn(d['id'],[r['id'] for r in self.admin.ok('/documents')])
        self.assertTrue(any(r['id']==d['id'] for r in self.admin.ok('/documents?archived=1')))
        self.assertEqual(self.admin.call('/documents/'+d['id']+'/versions','POST',{'filename':'new.txt','content':base64.b64encode(b'New').decode()})[0],409)
        self.admin.ok('/documents/'+d['id'],'PATCH',{'archived':False})
        self.assertTrue(any(r['id']==d['id'] and r['folder']=='Policies' for r in self.admin.ok('/documents')))

    def test_document_file_format_validation(self):
        from demo_data import sample_docx
        valid=sample_docx();d=self.upload(filename='onboarding.docx',content=base64.b64encode(valid).decode())
        self.assertEqual(self.admin.call('/document-files/'+d['file_id']+'?preview=1')[0],415)
        for filename,data in [('bad.pdf',b'<html>not a PDF</html>'),('bad.docx',b'not a zip'),('../secret.txt',b'bad'),('script.exe',b'MZ'),('binary.txt',b'bad\x00data')]:
            self.assertEqual(self.admin.call('/document-uploads','POST',{'filename':filename,'content':base64.b64encode(data).decode()})[0],400)
        self.assertEqual(self.actors['viewer'][0].call('/document-uploads','POST',{'filename':'view.txt','content':base64.b64encode(b'Blocked').decode()})[0],403)

    def test_concurrent_identical_document_versions_are_idempotent(self):
        d=self.upload();payload={'filename':'operations.txt','content':base64.b64encode(b'Revision two content').decode()}
        with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.admin.ok('/documents/'+d['id']+'/versions','POST',payload),range(2)))
        self.assertEqual(sorted(r['unchanged'] for r in results),[False,True]);self.assertEqual(len(self.admin.ok('/documents/'+d['id'])['versions']),2)

    def test_demo_workspace_is_isolated_and_seed_is_idempotent(self):
        c=Client(self.port);email='demo-owner-'+uuid.uuid4().hex[:8]+'@alpha.test'
        c.ok('/auth/register','POST',{'name':'Demo Owner','email':email,'password':self.password,'organization':'Real organization'})
        real_org=c.ok('/me')['organization']['id'];customer=c.ok('/customers','POST',{'name':'Real customer'})
        c.ok('/demo-workspace','POST');me=c.ok('/me');demo_org=me['organization']['id'];self.assertNotEqual(real_org,demo_org);self.assertTrue(me['organization']['is_demo'])
        self.assertEqual(len(c.ok('/projects')),6);self.assertEqual(len(c.ok('/tasks')),30);self.assertEqual(len(c.ok('/documents')),8)
        before=len(c.ok('/invoices'));c.ok('/demo-workspace','POST');self.assertEqual(c.ok('/me')['organization']['id'],demo_org);self.assertEqual(len(c.ok('/invoices')),before)
        c.ok('/auth/switch','POST',{'org_id':real_org});self.assertFalse(c.ok('/me')['organization']['is_demo']);self.assertEqual(c.ok('/customers')[0]['id'],customer['id']);self.assertEqual(c.ok('/projects'),[])
        with server.connect_db() as db:
            entries=db.execute('SELECT e.id FROM ledger_entries e JOIN ledger_lines l ON e.id=l.entry_id WHERE e.org_id=? GROUP BY e.id HAVING SUM(l.debit)!=SUM(l.credit)',(demo_org,)).fetchall();self.assertEqual(entries,[])

    def test_public_demo_creates_no_access_to_existing_workspaces(self):
        c=Client(self.port);c.ok('/auth/demo','POST');me=c.ok('/me');self.assertTrue(me['organization']['is_demo'])
        self.assertEqual(len(c.ok('/workspaces')),1);self.assertNotEqual(me['organization']['id'],self.org)
        self.assertEqual(c.call('/auth/switch','POST',{'org_id':self.org})[0],403)
        self.assertGreater(c.ok('/dashboard')['revenue'],0)

    def test_malformed_typed_fields_fail_as_client_errors(self):
        for invalid in ({'id':'x'},['x'],42,True):
            self.assertEqual(self.admin.call('/projects','POST',{'name':'Bad field','budget':'10','due_date':'2026-10-20','private':str(invalid) if isinstance(invalid,bool) else invalid})[0],400)
            self.assertEqual(self.admin.call('/tasks','POST',{'title':'Bad field','assignee_id':self.owner_id,'project_id':invalid})[0],400)
            self.assertEqual(self.admin.call('/customers','POST',{'name':'Bad enum','stage':invalid})[0],400)
        self.assertEqual(self.admin.call('/conversations','POST',{'name':'Invalid members','kind':'direct','members':[{'id':'invalid'}]})[0],400)
        self.assertEqual(self.admin.call('/tasks','POST',{'title':'Bad date','assignee_id':self.owner_id,'due_date':'2026-1-1'})[0],400)

    def test_document_metadata_uses_canonical_record_id(self):
        invoice=self.invoice();d=self.upload(record_kind='invoice',record_id=' '+invoice['id'])
        # Whitespace-bearing IDs must either be normalized consistently or rejected.
        self.assertEqual(self.admin.ok('/documents/'+d['id'])['record_id'],invoice['id'])

    def test_csv_export_enforces_access_and_escapes_formulas(self):
        import csv,io
        task=self.admin.ok('/tasks','POST',{'title':'=HYPERLINK("bad")','assignee_id':self.owner_id})
        data=self.admin.ok('/exports/tasks.csv?ids='+task['id'])
        rows=list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
        self.assertEqual(len(rows),2);self.assertTrue(rows[1][0].startswith("'="))
        self.assertEqual(self.other.call('/exports/tasks.csv?ids='+task['id'])[0],404)
        self.assertEqual(self.actors['viewer'][0].call('/exports/invoices.csv')[0],403)
        self.assertEqual(Client(self.port).call('/exports/tasks.csv')[0],401)


    def workflow(self,source='low_stock',action='task',schedule='manual'):
        return self.admin.ok('/workflows','POST',{'name':'Workflow '+uuid.uuid4().hex[:6],'definition':{'source':source,'action':action,'threshold':0,'days':30,'schedule':schedule}})

    def test_workflow_simulation_activation_idempotency_and_pause(self):
        product=self.admin.ok('/products','POST',{'name':'Reorder fixture','sku':uuid.uuid4().hex,'unit_price':'10','stock':0})
        rule=self.workflow();base='/workflows/'+rule['id']
        before=len(self.admin.ok('/tasks'));sim=self.admin.ok(base+'/simulate','POST',{'version':1})
        self.assertFalse(sim['writes']);self.assertIn(product['id'],[r['id'] for r in sim['matches']]);self.assertEqual(before,len(self.admin.ok('/tasks')))
        self.assertEqual(self.admin.call(base+'/run','POST',{'version':1})[0],409)
        self.admin.ok(base+'/activate','POST',{'version':1});first=self.admin.ok(base+'/run','POST',{'version':1});second=self.admin.ok(base+'/run','POST',{'version':1})
        self.assertGreater(first['applied'],0);self.assertEqual(second['applied'],0)
        self.admin.ok(base+'/pause','POST');self.assertEqual(self.admin.call(base+'/run','POST',{'version':1})[0],409)

    def test_workflow_versions_rollback_and_immutable_history(self):
        rule=self.workflow();base='/workflows/'+rule['id'];definition=rule['versions'][0]['definition'];definition['threshold']=5
        self.admin.ok(base+'/versions','POST',{'definition':definition});self.admin.ok(base+'/activate','POST',{'version':2});self.admin.ok(base+'/activate','POST',{'version':1})
        self.assertEqual(self.admin.ok(base)['active_version'],1)
        with server.connect_db() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE workflow_versions SET definition='{}' WHERE rule_id=?",(rule['id'],))

    def test_workflow_tenant_role_and_validation(self):
        rule=self.workflow();base='/workflows/'+rule['id']
        self.assertEqual(self.other.call(base)[0],404)
        for client,_ in self.actors.values():self.assertEqual(client.call('/workflows')[0],403)
        self.assertEqual(self.admin.call(base+'/versions','POST',{'definition':{'source':[],'action':'task'}})[0],400)
        self.assertEqual(self.admin.call(base+'/versions','POST',{'definition':{'source':'low_stock','action':'task','threshold':True}})[0],400)
        self.assertEqual(self.admin.call(base+'/activate','POST',{'version':True})[0],400)
        self.assertEqual(self.admin.call(base+'/activate','POST',{'version':999})[0],404)

    def test_workflow_invoice_tasks_preserve_finance_access(self):
        invoice=self.invoice();self.admin.ok('/invoices/'+invoice['id']+'/issue','POST')
        with server.connect_db() as db:db.execute("UPDATE invoices SET due_date='2020-01-01' WHERE id=?",(invoice['id'],))
        rule=self.workflow('overdue_invoice');base='/workflows/'+rule['id'];self.admin.ok(base+'/activate','POST',{'version':1});self.admin.ok(base+'/run','POST',{'version':1})
        with server.connect_db() as db:task=db.execute("SELECT output_id FROM workflow_effects WHERE rule_id=? AND source_id=?",(rule['id'],invoice['id'])).fetchone()[0]
        self.assertIn(task,[r['id'] for r in self.admin.ok('/tasks')]);self.assertNotIn(task,[r['id'] for r in self.actors['member'][0].ok('/tasks')])
        self.assertEqual(self.actors['member'][0].call('/tasks/'+task,'PATCH',{'status':'done'})[0],403)
        self.assertEqual(self.actors['member'][0].call('/exports/tasks.csv?ids='+task)[0],404)

    def test_workflow_scheduler_is_restart_safe_and_stops_for_revoked_owner(self):
        import workflows
        rule=self.workflow(schedule='daily');base='/workflows/'+rule['id'];self.admin.ok(base+'/activate','POST',{'version':1})
        workflows.schedule_once(server);workflows.schedule_once(server)
        runs=self.admin.ok(base)['runs'];self.assertEqual(len(runs),1);self.assertEqual(runs[0]['trigger_kind'],'scheduled')
        with server.connect_db() as db:db.execute("UPDATE workflow_rules SET enabled=0 WHERE id=?",(rule['id'],))
        second=self.workflow(schedule='daily');self.admin.ok('/workflows/'+second['id']+'/activate','POST',{'version':1})
        with server.connect_db() as db:db.execute("UPDATE memberships SET role='member' WHERE org_id=? AND user_id=?",(self.org,self.owner_id))
        try:
            workflows.schedule_once(server)
            with server.connect_db() as db:self.assertEqual(db.execute('SELECT status FROM workflow_runs WHERE rule_id=?',(second['id'],)).fetchone()[0],'blocked')
        finally:
            with server.connect_db() as db:
                db.execute("UPDATE memberships SET role='admin' WHERE org_id=? AND user_id=?",(self.org,self.owner_id));db.execute('UPDATE workflow_rules SET enabled=0 WHERE id=?',(second['id'],))

if __name__=='__main__':unittest.main(verbosity=2)
