"""Nexus business system. Python 3.11+, standard library only."""
from __future__ import annotations
import argparse
import base64
import binascii
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, quote
import threading
import workflows
import ai_gateway
from document_store import DocumentStore,PREVIEWABLE
from exports import make_csv

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('NEXUS_DB', str(ROOT / 'data' / 'nexus.sqlite3')))
SESSION_SECONDS = 12 * 60 * 60
MAX_BODY = 30 * 1024 * 1024
ROLES = {'admin', 'manager', 'finance', 'member', 'viewer'}
PACKAGES = json.loads((ROOT / 'packages.json').read_text('utf-8'))
RECORD_TABLES={'product':'products','customer':'customers','supplier':'suppliers','invoice':'invoices','requisition':'requisitions','task':'tasks','asset':'assets','contract':'contracts','document':'documents','meeting':'meetings','purchase_order':'purchase_orders'}

def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')

def uid():
    return uuid.uuid4().hex

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def password_hash(password):
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600_000).hex()
    return f'pbkdf2_sha256$600000${salt}${hashed}'

def password_valid(password, stored):
    try:
        _, rounds, salt, expected = stored.split('$')
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False

class Database(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

def connect_db():
    db = sqlite3.connect(DB_PATH, timeout=15, factory=Database)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=15000')
    return db

def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect_db() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript((ROOT / 'schema.sql').read_text('utf-8'))

class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message

def require(condition, message, status=400):
    if not condition:
        raise APIError(status, message)

def text(data, key, required=True, limit=2000):
    value = data.get(key, '')
    require(isinstance(value, str), f'{key} must be text')
    value = value.strip()
    require(not required or bool(value), f'{key} is required')
    require(len(value) <= limit, f'{key} is too long (maximum {limit})')
    return value

def enum(data, key, allowed, default=None):
    value = data.get(key, default)
    require(isinstance(value,str) and value in allowed, f'Invalid {key}')
    return value

def money(data, key, positive=False):
    raw = data.get(key, '0')
    require(isinstance(raw, (str, int, float)) and not isinstance(raw, bool), f'Invalid {key}')
    try:
        amount = Decimal(str(raw))
        require(amount.is_finite() and amount >= 0 and amount <= Decimal('1000000000'), f'Invalid {key}')
        require(amount.as_tuple().exponent >= -2, f'{key} supports at most two decimal places')
        cents = int(amount * 100)
        require(not positive or cents > 0, f'{key} must be greater than zero')
        return cents
    except (InvalidOperation, ValueError):
        raise APIError(400, f'Invalid {key}')

def integer(data, key, minimum=1, maximum=1_000_000):
    raw = data.get(key)
    require(isinstance(raw, int) and not isinstance(raw, bool) and minimum <= raw <= maximum, f'{key} must be an integer between {minimum} and {maximum}')
    return raw

def date_value(data, key, required=False):
    value = text(data, key, required, 10)
    if value:
        require(re.fullmatch(r'\d{4}-\d{2}-\d{2}',value),'Use a date in YYYY-MM-DD format')
        try:
            datetime.strptime(value, '%Y-%m-%d')
        except ValueError:
            raise APIError(400, f'{key} must be YYYY-MM-DD')
    return value

class Service:
    def __init__(self, db, identity):
        self.db, self.me = db, identity
        self.org, self.user, self.role = identity['org_id'], identity['user_id'], identity['role']

    def document_store(self):
        return DocumentStore(self,require,text,APIError)

    def rows(self, sql, params=()):
        return [dict(r) for r in self.db.execute(sql, params)]

    def one(self, table, record_id):
        # table is always an application constant, never request input.
        row = self.db.execute(f'SELECT * FROM {table} WHERE org_id=? AND id=?', (self.org, record_id)).fetchone()
        require(row is not None, 'Record not found', 404)
        return dict(row)

    def allow(self, *roles):
        require(self.role in roles, 'You do not have permission for this action', 403)

    def write(self):
        self.allow('admin', 'manager', 'finance', 'member')

    def member(self, user_id):
        require(isinstance(user_id,str) and re.fullmatch(r'[a-f0-9]{32}',user_id),'Select a valid workspace member')
        row = self.db.execute('SELECT * FROM memberships WHERE org_id=? AND user_id=? AND active=1', (self.org, user_id)).fetchone()
        require(row is not None, 'Select an active workspace member')
        return dict(row)

    def project(self, project_id):
        p = self.one('projects', project_id)
        permitted = not p['private'] or self.role == 'admin' or self.db.execute('SELECT 1 FROM project_members WHERE project_id=? AND user_id=?', (project_id, self.user)).fetchone()
        require(permitted, 'Record not found', 404)
        return p

    def can_project(self, project_id):
        try:
            self.project(project_id)
            return True
        except APIError:
            return False

    def conversation(self, conversation_id):
        c = self.one('conversations', conversation_id)
        if c['project_id']:
            self.project(c['project_id'])
        if c['kind'] == 'direct':
            require(self.db.execute('SELECT 1 FROM conversation_members WHERE conversation_id=? AND user_id=?', (conversation_id, self.user)).fetchone(), 'Record not found', 404)
        link=self.db.execute('SELECT record_kind,record_id FROM conversation_records WHERE conversation_id=?',(conversation_id,)).fetchone()
        if link:self.business_record(link['record_kind'],link['record_id'])
        return c

    def business_record(self,kind,record_id):
        require(kind in RECORD_TABLES,'Record type not found',404)
        if kind=='invoice':self.allow('admin','finance')
        elif kind in ('supplier','contract','purchase_order'):self.allow('admin','manager','finance')
        record=self.visible_record(RECORD_TABLES[kind],record_id)
        if kind=='purchase_order':self.visible_record('requisitions',record['requisition_id'])
        return record

    def record_conversation(self,kind,record_id):
        record=self.business_record(kind,record_id)
        existing=self.db.execute('SELECT conversation_id FROM conversation_records WHERE org_id=? AND record_kind=? AND record_id=?',(self.org,kind,record_id)).fetchone()
        if existing:return self.one('conversations',existing['conversation_id'])
        self.write()
        conversation_id=uid();name=kind.replace('_',' ').title()+': '+str(record.get('name') or record.get('title') or record.get('number') or record.get('item') or record_id[:8])
        # Context conversations keep their project link in the authorization adapter,
        # not in the unique one-conversation-per-project column.
        self.db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?,?)',(conversation_id,self.org,name,'channel',None,self.user,now()))
        self.db.execute('INSERT INTO conversation_records VALUES(?,?,?,?)',(self.org,conversation_id,kind,record_id))
        self.audit('create_context','conversation',conversation_id,{'record_kind':kind,'record_id':record_id})
        return self.one('conversations',conversation_id)

    def message(self, message_id):
        m = self.one('messages', message_id)
        self.conversation(m['conversation_id'])
        return m

    def visible_record(self, table, record_id):
        record = self.one(table, record_id)
        if record.get('project_id'):
            self.project(record['project_id'])
        if record.get('source_message_id'):
            self.message(record['source_message_id'])
        if table=='documents':
            link=self.db.execute('SELECT record_kind,record_id FROM document_metadata WHERE org_id=? AND document_id=?',(self.org,record_id)).fetchone()
            if link and link['record_kind']:self.business_record(link['record_kind'],link['record_id'])
        if table=='tasks':self.workflow_source(record)
        return record

    def workflow_source(self,record):
        links=self.rows("SELECT source_kind,source_id FROM workflow_effects WHERE org_id=? AND output_kind='task' AND output_id=?",(self.org,record['id']))
        for link in links:self.business_record(link['source_kind'],link['source_id'])

    def can_record(self, record):
        try:
            self.workflow_source(record)
            if record.get('project_id'): self.project(record['project_id'])
            if record.get('source_message_id'): self.message(record['source_message_id'])
            return True
        except APIError:
            return False

    def audit(self, action, kind, record_id, details=None):
        self.db.execute('INSERT INTO audit_log(id,org_id,actor_id,action,record_type,record_id,details,created_at) VALUES(?,?,?,?,?,?,?,?)', (uid(), self.org, self.user, action, kind, record_id, json.dumps(details or {}), now()))

    def notify(self, user_id, message, kind, record_id):
        self.db.execute('INSERT INTO notifications VALUES(?,?,?,?,?,?,?,?)', (uid(), self.org, user_id, message, kind, record_id, None, now()))

    def project_id(self, data):
        project_id = data.get('project_id')
        if project_id is not None and project_id!='':
            require(isinstance(project_id,str) and re.fullmatch(r'[a-f0-9]{32}',project_id),'Select a valid project')
            self.project(project_id)
            return project_id
        return None

    def source(self, data, project_id):
        message_id = data.get('source_message_id')
        if message_id is not None and message_id!='':
            require(isinstance(message_id,str) and re.fullmatch(r'[a-f0-9]{32}',message_id),'Select a valid source message')
            m = self.message(message_id)
            require(not m['deleted_at'], 'Source message has been removed')
            c = self.conversation(m['conversation_id'])
            context_project=c['project_id']
            link=self.db.execute('SELECT record_kind,record_id FROM conversation_records WHERE conversation_id=?',(c['id'],)).fetchone()
            if link:context_project=self.business_record(link['record_kind'],link['record_id']).get('project_id')
            require(context_project == project_id, 'Source conversation and project must match')
            return message_id
        return None

    def projects(self):
        return [p for p in self.rows('SELECT p.*,u.name owner_name FROM projects p JOIN users u ON p.owner_id=u.id WHERE p.org_id=? ORDER BY p.created_at DESC', (self.org,)) if self.can_project(p['id'])]

    def get(self, path, query):
        parts = path.strip('/').split('/')
        if path == '/api/me':
            org = dict(self.db.execute('SELECT * FROM organizations WHERE id=?', (self.org,)).fetchone())
            org['is_demo']=bool(self.db.execute('SELECT 1 FROM demo_workspaces WHERE org_id=?',(self.org,)).fetchone())
            return {'user': {k: self.me[k] for k in ('user_id','name','email','role')}, 'organization': org, 'csrf': self.me['csrf']}
        if path == '/api/workspaces':
            return self.rows('SELECT o.id,o.name,m.role FROM memberships m JOIN organizations o ON o.id=m.org_id WHERE m.user_id=? AND m.active=1 ORDER BY o.name',(self.user,))
        if path == '/api/assistant/status':
            return ai_gateway.status()
        if path == '/api/people':
            return self.rows('SELECT u.id,u.name,u.email,m.role,m.department,MAX(s.last_seen) last_seen FROM memberships m JOIN users u ON u.id=m.user_id LEFT JOIN sessions s ON s.user_id=u.id AND s.org_id=m.org_id WHERE m.org_id=? AND m.active=1 GROUP BY u.id ORDER BY u.name', (self.org,))
        if path == '/api/projects':
            return self.projects()
        if len(parts) == 4 and parts[1] == 'projects' and parts[3] == 'members':
            self.project(parts[2])
            return self.rows('SELECT u.id,u.name,u.email FROM project_members pm JOIN users u ON u.id=pm.user_id WHERE pm.org_id=? AND pm.project_id=?', (self.org,parts[2]))
        if path == '/api/conversations':
            cs = self.rows('SELECT c.*,r.record_kind context_kind,r.record_id context_id FROM conversations c LEFT JOIN conversation_records r ON r.conversation_id=c.id WHERE c.org_id=? ORDER BY c.created_at', (self.org,))
            result = []
            for c in cs:
                try:
                    self.conversation(c['id'])
                    if c['context_kind']:
                        c['context_project_id']=self.business_record(c['context_kind'],c['context_id']).get('project_id')
                    c['unread'] = self.db.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=? AND author_id!=? AND deleted_at IS NULL AND created_at>COALESCE((SELECT last_read FROM conversation_members WHERE conversation_id=? AND user_id=?),'')", (c['id'],self.user,c['id'],self.user)).fetchone()[0]
                    result.append(c)
                except APIError:
                    pass
            return result
        if len(parts)==3 and parts[1]=='messages':
            return self.message(parts[2])
        if len(parts) == 4 and parts[1] == 'conversations' and parts[3] == 'messages':
            c = self.conversation(parts[2])
            q = query.get('q',[''])[0][:200]
            around=query.get('around',[''])[0]
            if around:
                target=self.message(around);require(target['conversation_id']==c['id'],'Source message belongs to another conversation',400)
                rows=self.rows('SELECT m.*,u.name author_name FROM messages m JOIN users u ON u.id=m.author_id WHERE m.conversation_id=? ORDER BY ABS(julianday(m.created_at)-julianday(?)) LIMIT 300',(c['id'],target['created_at']))
                rows.sort(key=lambda r:r['created_at'],reverse=True)
            else:
                rows = self.rows("SELECT m.*,u.name author_name FROM messages m JOIN users u ON u.id=m.author_id WHERE m.conversation_id=? AND (?='' OR m.body LIKE ? ESCAPE '\\') ORDER BY m.created_at DESC LIMIT 300", (c['id'],q,'%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'))
            for row in rows:
                row['reactions'] = self.rows('SELECT emoji,COUNT(*) count,MAX(user_id=?) mine FROM reactions WHERE message_id=? GROUP BY emoji', (self.user,row['id']))
                row['attachments'] = self.rows('SELECT id,filename,mime,length(content) size FROM attachments WHERE message_id=?', (row['id'],)) if not row['deleted_at'] else []
                row['read_by'] = self.rows('SELECT u.name FROM conversation_members cm JOIN users u ON cm.user_id=u.id WHERE cm.conversation_id=? AND cm.last_read>=? AND cm.user_id!=?', (c['id'],row['created_at'],row['author_id']))
            return list(reversed(rows))
        if path == '/api/tasks':
            return [t for t in self.rows('SELECT t.*,u.name assignee_name,p.name project_name FROM tasks t JOIN users u ON u.id=t.assignee_id LEFT JOIN projects p ON p.id=t.project_id WHERE t.org_id=? ORDER BY t.created_at DESC', (self.org,)) if self.can_record(t)]
        if path in ('/api/customers','/api/suppliers','/api/products'):
            return self.rows(f'SELECT * FROM {parts[1]} WHERE org_id=? ORDER BY created_at DESC', (self.org,))
        if path == '/api/requisitions':
            result = [r for r in self.rows('SELECT r.*,u.name requester_name,p.name project_name FROM requisitions r JOIN users u ON u.id=r.created_by LEFT JOIN projects p ON p.id=r.project_id WHERE r.org_id=? ORDER BY r.created_at DESC',(self.org,)) if self.can_record(r)]
            for r in result:
                r['approvals'] = self.rows('SELECT a.*,u.name reviewer_name FROM approvals a JOIN users u ON u.id=a.reviewer_id WHERE a.requisition_id=? ORDER BY a.created_at', (r['id'],))
            return result
        if path == '/api/purchase-orders':
            self.allow('admin','manager','finance')
            return [r for r in self.rows('SELECT po.*,r.item,r.quantity,r.project_id,r.source_message_id,s.name supplier_name FROM purchase_orders po JOIN requisitions r ON r.id=po.requisition_id JOIN suppliers s ON s.id=po.supplier_id WHERE po.org_id=? ORDER BY po.created_at DESC',(self.org,)) if self.can_record(r)]
        if path == '/api/invoices':
            self.allow('admin','finance')
            return self.rows('SELECT i.*,c.name customer_name FROM invoices i JOIN customers c ON c.id=i.customer_id WHERE i.org_id=? ORDER BY i.created_at DESC',(self.org,))
        if path == '/api/ledger':
            self.allow('admin','finance')
            lines = self.rows('SELECT l.*,e.created_at,e.description,e.invoice_id,e.kind FROM ledger_lines l JOIN ledger_entries e ON e.id=l.entry_id WHERE e.org_id=? ORDER BY e.created_at DESC',(self.org,))
            balances = self.rows('SELECT l.account,SUM(l.debit) debit,SUM(l.credit) credit,SUM(l.debit-l.credit) balance FROM ledger_lines l JOIN ledger_entries e ON e.id=l.entry_id WHERE e.org_id=? GROUP BY l.account',(self.org,))
            return {'lines':lines,'balances':balances}
        if path == '/api/documents':
            return self.document_store().list(query)
        if len(parts)==3 and parts[1]=='documents':
            return self.document_store().detail(parts[2])
        if path=='/api/document-contexts':
            result=[{'kind':'project','id':p['id'],'name':p['name']} for p in self.projects()]
            for kind,endpoint,label in [('customer','customers','name'),('task','tasks','title'),('requisition','requisitions','item'),('asset','assets','name'),('invoice','invoices','number'),('contract','contracts','title')]:
                if kind=='invoice' and self.role not in ('admin','finance'):continue
                if kind=='contract' and self.role not in ('admin','manager','finance'):continue
                result.extend({'kind':kind,'id':r['id'],'name':r[label]} for r in self.get('/api/'+endpoint,{})[:200])
            return result
        if path == '/api/organization-units':
            return self.rows('SELECT * FROM organization_units WHERE org_id=? ORDER BY kind,name',(self.org,))
        if path == '/api/assets':
            return [r for r in self.rows('SELECT a.*,u.name assignee_name,p.name project_name FROM assets a LEFT JOIN users u ON u.id=a.assignee_id LEFT JOIN projects p ON p.id=a.project_id WHERE a.org_id=? ORDER BY a.created_at DESC',(self.org,)) if self.can_record(r)]
        if path == '/api/contracts':
            self.allow('admin','manager','finance')
            return [r for r in self.rows('SELECT * FROM contracts WHERE org_id=? ORDER BY created_at DESC',(self.org,)) if self.can_record(r)]
        if path == '/api/packages':
            enabled={r['package_id'] for r in self.rows('SELECT package_id FROM installed_packages WHERE org_id=?',(self.org,))}
            return [{**p,'enabled':p['id'] in enabled,'contract_version':PACKAGES['contract_version']} for p in PACKAGES['packages']]
        if len(parts)==4 and parts[1]=='packages' and parts[3]=='records':
            require(any(p['id']==parts[2] for p in PACKAGES['packages']),'Package not found',404)
            rows=self.rows('SELECT e.*,p.name project_name,u.name author_name FROM extension_records e JOIN projects p ON p.id=e.project_id JOIN users u ON u.id=e.created_by WHERE e.org_id=? AND e.package_id=? ORDER BY e.created_at DESC',(self.org,parts[2]))
            return [{**r,'payload':json.loads(r['payload'])} for r in rows if self.can_record(r)]
        if path == '/api/meetings':
            result = []
            for m in self.rows('SELECT * FROM meetings WHERE org_id=? ORDER BY starts_at',(self.org,)):
                if m['project_id'] and not self.can_project(m['project_id']):
                    continue
                m['attendees'] = self.rows('SELECT a.user_id,a.rsvp,u.name FROM meeting_attendees a JOIN users u ON u.id=a.user_id WHERE a.meeting_id=?',(m['id'],))
                result.append(m)
            return result
        if path == '/api/notifications':
            rows = self.rows('SELECT * FROM notifications WHERE org_id=? AND user_id=? ORDER BY created_at DESC LIMIT 100',(self.org,self.user))
            # A notification must not preserve access to a record after revocation.
            result=[]
            for r in rows:
                try:
                    if r['record_type']=='workflow': self.allow('admin');self.one('workflow_rules',r['record_id'])
                    elif r['record_type']=='message': self.message(r['record_id'])
                    elif r['record_type'] in ('task','requisition','meeting'): self.visible_record({'task':'tasks','requisition':'requisitions','meeting':'meetings'}[r['record_type']],r['record_id'])
                    result.append(r)
                except APIError: pass
            return result
        if path == '/api/audit':
            self.allow('admin')
            return self.rows('SELECT a.*,u.name actor_name FROM audit_log a JOIN users u ON u.id=a.actor_id WHERE a.org_id=? ORDER BY a.seq DESC LIMIT 500',(self.org,))
        if path == '/api/dashboard':
            ps = self.projects()
            ts = self.get('/api/tasks',{})
            reqs = self.get('/api/requisitions',{})
            revenue = None
            if self.role in ('admin','finance'):
                revenue = self.db.execute("SELECT COALESCE(SUM(l.credit-l.debit),0) FROM ledger_lines l JOIN ledger_entries e ON e.id=l.entry_id WHERE e.org_id=? AND l.account='4000 Revenue'", (self.org,)).fetchone()[0]
            trend=[];receivables=None;cash=None;recent_invoices=[]
            if self.role in ('admin','finance'):
                current=datetime.now(timezone.utc)
                for offset in range(5,-1,-1):
                    year,month=divmod(current.year*12+current.month-1-offset,12);period=f'{year:04d}-{month+1:02d}'
                    amount=self.db.execute("SELECT COALESCE(SUM(l.credit-l.debit),0) FROM ledger_lines l JOIN ledger_entries e ON e.id=l.entry_id WHERE e.org_id=? AND l.account='4000 Revenue' AND substr(e.created_at,1,7)=?",(self.org,period)).fetchone()[0]
                    trend.append({'period':period,'label':datetime(year,month+1,1).strftime('%b'),'amount':amount})
                receivables=self.db.execute("SELECT COALESCE(SUM(l.debit-l.credit),0) FROM ledger_lines l JOIN ledger_entries e ON e.id=l.entry_id WHERE e.org_id=? AND l.account='1100 Accounts receivable'",(self.org,)).fetchone()[0]
                cash=self.db.execute("SELECT COALESCE(SUM(l.debit-l.credit),0) FROM ledger_lines l JOIN ledger_entries e ON e.id=l.entry_id WHERE e.org_id=? AND l.account='1000 Cash'",(self.org,)).fetchone()[0]
                recent_invoices=self.get('/api/invoices',{})[:6]
            meetings=self.get('/api/meetings',{})
            return {'revenue':revenue,'receivables':receivables,'cash':cash,'revenue_trend':trend,'recent_invoices':recent_invoices,'meetings':meetings,'projects':ps,'tasks':ts,'requisitions':reqs,'customers':self.db.execute('SELECT COUNT(*) FROM customers WHERE org_id=?',(self.org,)).fetchone()[0],'people':self.db.execute('SELECT COUNT(*) FROM memberships WHERE org_id=? AND active=1',(self.org,)).fetchone()[0]}
        raise APIError(404,'Endpoint not found')

    def post(self, path, data):
        parts = path.strip('/').split('/')
        record_id, timestamp = uid(), now()
        if path=='/api/document-uploads':
            return self.document_store().upload(data)
        if len(parts)==4 and parts[1]=='documents' and parts[3]=='versions':
            return self.document_store().upload(data,parts[2])
        if path=='/api/record-conversations':
            return self.record_conversation(text(data,'record_kind',limit=30),text(data,'record_id',limit=32))
        if path == '/api/invitations':
            self.allow('admin')
            email = text(data,'email',limit=254).lower()
            require(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email),'Enter a valid email')
            role = enum(data,'role',ROLES,'member')
            token = secrets.token_urlsafe(32)
            self.db.execute('INSERT INTO invitations VALUES(?,?,?,?,?,?,?,?,?)',(record_id,self.org,email,role,text(data,'department',False,100),digest(token),int(time.time())+86400,None,timestamp))
            self.audit('invite','membership',record_id,{'email':email,'role':role})
            return {'id':record_id,'token':token,'expires_in':86400,'email':email}
        if path == '/api/projects':
            self.write()
            private = data.get('private',False)
            require(isinstance(private,bool),'private must be a boolean')
            self.db.execute('INSERT INTO projects VALUES(?,?,?,?,?,?,?,?,?,?)',(record_id,self.org,text(data,'name',limit=160),text(data,'description',False,10000),self.user,int(private),money(data,'budget'),'active',date_value(data,'due_date'),timestamp))
            self.db.execute('INSERT INTO project_members VALUES(?,?,?)',(self.org,record_id,self.user))
            self.db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?,?)',(uid(),self.org,text(data,'name',limit=160),'project',record_id,self.user,timestamp))
            self.audit('create','project',record_id)
            return self.one('projects',record_id)
        if len(parts)==4 and parts[1]=='projects' and parts[3]=='members':
            p=self.project(parts[2]); self.write()
            require(self.role=='admin' or p['owner_id']==self.user,'Only the owner or administrator can manage access',403)
            member_id=text(data,'user_id',limit=32); self.member(member_id)
            if data.get('remove'):
                require(member_id!=p['owner_id'],'The project owner must retain access')
                self.db.execute('DELETE FROM project_members WHERE project_id=? AND user_id=?',(p['id'],member_id))
            else:
                self.db.execute('INSERT OR IGNORE INTO project_members VALUES(?,?,?)',(self.org,p['id'],member_id))
            self.audit('remove_member' if data.get('remove') else 'add_member','project',p['id'],{'user_id':member_id})
            return {'ok':True}
        if path=='/api/conversations':
            self.write()
            kind=enum(data,'kind',{'channel','direct'},'channel')
            name=text(data,'name',limit=160)
            members=data.get('members',[])
            require(isinstance(members,list) and len(members)<=100,'Invalid members')
            for member_id in members: self.member(member_id)
            if kind=='direct': require(len(set(members)-{self.user})==1,'Direct conversations require exactly one other member')
            self.db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?,?)',(record_id,self.org,name,kind,None,self.user,timestamp))
            for member_id in set(members+[self.user]): self.db.execute('INSERT INTO conversation_members(org_id,conversation_id,user_id) VALUES(?,?,?)',(self.org,record_id,member_id))
            self.audit('create','conversation',record_id)
            return self.one('conversations',record_id)
        if len(parts)==4 and parts[1]=='conversations' and parts[3]=='messages':
            self.write(); c=self.conversation(parts[2])
            body=text(data,'body',limit=10000)
            parent_id=data.get('parent_id') or None
            if parent_id:
                parent=self.message(parent_id)
                require(parent['conversation_id']==c['id'],'Reply must be in the same conversation')
            self.db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?)',(record_id,self.org,c['id'],self.user,body,parent_id,None,None,0,timestamp))
            for person in self.get('/api/people',{}):
                if person['id']!=self.user and ('@'+person['email']).lower() in body.lower():
                    try:
                        Service(self.db,{'org_id':self.org,'user_id':person['id'],'role':person['role']}).conversation(c['id']);allowed=True
                    except APIError:allowed=False
                    if allowed: self.notify(person['id'],f'{self.me["name"]} mentioned you in {c["name"]}','message',record_id)
            self.audit('send','message',record_id)
            return self.one('messages',record_id)
        if len(parts)==4 and parts[1]=='conversations' and parts[3]=='read':
            c=self.conversation(parts[2])
            through_id=data.get('through_id')
            if through_id:
                message=self.message(through_id);require(message['conversation_id']==c['id'],'Read marker belongs to another conversation');timestamp=message['created_at']
            self.db.execute('INSERT INTO conversation_members(org_id,conversation_id,user_id,last_read) VALUES(?,?,?,?) ON CONFLICT(conversation_id,user_id) DO UPDATE SET last_read=MAX(conversation_members.last_read,excluded.last_read)',(self.org,c['id'],self.user,timestamp))
            return {'ok':True}
        if len(parts)==4 and parts[1]=='messages' and parts[3]=='react':
            self.write(); m=self.message(parts[2]); require(not m['deleted_at'],'Message removed')
            emoji=enum(data,'emoji',{'👍','✅','❤️','👀','🎉'},'👍')
            existing=self.db.execute('SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(m['id'],self.user,emoji)).fetchone()
            if existing: self.db.execute('DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?',(m['id'],self.user,emoji))
            else: self.db.execute('INSERT INTO reactions VALUES(?,?,?,?)',(self.org,m['id'],self.user,emoji))
            return {'ok':True}
        if len(parts)==4 and parts[1]=='messages' and parts[3]=='attachments':
            self.write(); m=self.message(parts[2]); require(m['author_id']==self.user and not m['deleted_at'],'Only the author can attach files',403)
            filename=text(data,'filename',limit=180)
            require('/' not in filename and '\\' not in filename and not any(ord(c)<32 for c in filename),'Invalid filename')
            mime=enum(data,'mime',{'application/pdf','image/png','image/jpeg','text/plain','text/csv','application/octet-stream'},'application/octet-stream')
            try: content=base64.b64decode(text(data,'content',limit=MAX_BODY),validate=True)
            except (binascii.Error,ValueError): raise APIError(400,'Invalid attachment encoding')
            require(0<len(content)<=5*1024*1024,'Files must be between 1 byte and 5 MB')
            self.db.execute('INSERT INTO attachments VALUES(?,?,?,?,?,?,?,?,?)',(record_id,self.org,m['conversation_id'],m['id'],filename,mime,content,self.user,timestamp))
            self.audit('upload','attachment',record_id,{'filename':filename,'bytes':len(content)})
            return {'id':record_id,'filename':filename}
        if path=='/api/tasks':
            self.write(); p=self.project_id(data); source=self.source(data,p)
            assignee=text(data,'assignee_id',limit=32); self.member(assignee)
            if source:
                c=self.conversation(self.message(source)['conversation_id'])
                assignee_role=self.member(assignee)['role']
                try:Service(self.db,{'org_id':self.org,'user_id':assignee,'role':assignee_role}).conversation(c['id'])
                except APIError:raise APIError(400,'Assignee must have access to the source conversation')
            if p and self.project(p)['private']:
                member=self.member(assignee)
                require(member['role']=='admin' or self.db.execute('SELECT 1 FROM project_members WHERE project_id=? AND user_id=?',(p,assignee)).fetchone(),'Assignee needs project access')
            self.db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(record_id,self.org,p,text(data,'title',limit=200),text(data,'description',False,10000),assignee,'todo',enum(data,'priority',{'low','normal','high'},'normal'),date_value(data,'due_date'),source,self.user,timestamp))
            self.audit('create','task',record_id)
            if assignee!=self.user: self.notify(assignee,'A task was assigned to you','task',record_id)
            return self.one('tasks',record_id)
        if path=='/api/customers':
            self.write()
            self.db.execute('INSERT INTO customers VALUES(?,?,?,?,?,?,?,?,?)',(record_id,self.org,text(data,'name',limit=160),text(data,'email',False,254),text(data,'phone',False,80),text(data,'company',False,160),enum(data,'stage',{'lead','qualified','customer','inactive'},'lead'),text(data,'notes',False,10000),timestamp))
            self.audit('create','customer',record_id); return self.one('customers',record_id)
        if path=='/api/suppliers':
            self.allow('admin','manager','finance')
            self.db.execute('INSERT INTO suppliers VALUES(?,?,?,?,?,?)',(record_id,self.org,text(data,'name',limit=160),text(data,'email',False,254),text(data,'notes',False,10000),timestamp))
            self.audit('create','supplier',record_id); return self.one('suppliers',record_id)
        if path=='/api/products':
            self.allow('admin','manager')
            self.db.execute('INSERT INTO products VALUES(?,?,?,?,?,?,?,?)',(record_id,self.org,text(data,'name',limit=160),text(data,'sku',limit=80),text(data,'unit',False,40) or 'each',money(data,'unit_price'),0,timestamp))
            self.audit('create','product',record_id); return self.one('products',record_id)
        if len(parts)==4 and parts[1]=='products' and parts[3]=='stock':
            self.allow('admin','manager'); p=self.one('products',parts[2])
            quantity=integer(data,'quantity',-1_000_000,1_000_000)
            require(quantity!=0,'Quantity must not be zero'); require(p['stock']+quantity>=0,'Insufficient stock')
            self.db.execute('UPDATE products SET stock=stock+? WHERE id=?',(quantity,p['id']))
            reason=text(data,'reason',limit=500)
            self.db.execute('INSERT INTO stock_movements VALUES(?,?,?,?,?,?,?)',(record_id,self.org,p['id'],quantity,reason,self.user,timestamp))
            self.audit('adjust_stock','product',p['id'],{'quantity':quantity,'reason':reason}); return self.one('products',p['id'])
        if path=='/api/requisitions':
            self.write(); p=self.project_id(data); source=self.source(data,p)
            self.db.execute('INSERT INTO requisitions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(record_id,self.org,p,text(data,'item',limit=200),integer(data,'quantity'),money(data,'unit_price'),text(data,'notes',False,10000),'draft',source,self.user,None,timestamp))
            self.audit('create_draft','requisition',record_id); return self.one('requisitions',record_id)
        if len(parts)==4 and parts[1]=='requisitions':
            self.write(); r=self.visible_record('requisitions',parts[2]); action=parts[3]
            if action=='submit':
                require(r['created_by']==self.user,'Only the requester may submit',403)
                require(r['status'] in ('draft','rejected'),'Only draft or rejected requests can be submitted',409)
                self.db.execute("UPDATE requisitions SET status='submitted',submitted_at=? WHERE id=?",(timestamp,r['id']))
                self.audit('submit','requisition',r['id'])
            elif action=='review':
                self.allow('admin','manager'); require(r['created_by']!=self.user,'You cannot approve or reject your own requisition',403)
                require(r['status']=='submitted','This request is not awaiting review',409)
                decision=enum(data,'decision',{'approved','rejected'}); comment=text(data,'comment',decision=='rejected',2000)
                self.db.execute('INSERT INTO approvals VALUES(?,?,?,?,?,?,?)',(record_id,self.org,r['id'],self.user,decision,comment,timestamp))
                self.db.execute('UPDATE requisitions SET status=? WHERE id=?',(decision,r['id']))
                self.notify(r['created_by'],f'Your requisition was {decision}','requisition',r['id']); self.audit(decision,'requisition',r['id'],{'comment':comment})
            elif action=='order':
                self.allow('admin','manager'); require(r['status']=='approved','Only approved requisitions can become purchase orders',409)
                supplier=self.one('suppliers',text(data,'supplier_id',limit=32))
                require(r['unit_price']>0,'A priced requisition is required before ordering')
                self.db.execute('INSERT INTO purchase_orders VALUES(?,?,?,?,?,?,?,?)',(record_id,self.org,r['id'],supplier['id'],r['quantity']*r['unit_price'],self.user,'issued',timestamp))
                self.db.execute("UPDATE requisitions SET status='ordered' WHERE id=?",(r['id'],)); self.audit('issue_purchase_order','purchase_order',record_id,{'requisition_id':r['id']})
                return self.one('purchase_orders',record_id)
            else: raise APIError(404,'Endpoint not found')
            return self.one('requisitions',r['id'])
        if path=='/api/invoices':
            self.allow('admin','finance'); customer=self.one('customers',text(data,'customer_id',limit=32))
            self.db.execute('INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?,?,?)',(record_id,self.org,text(data,'number',limit=80),customer['id'],text(data,'description',limit=2000),money(data,'total',True),date_value(data,'due_date'),'draft',self.user,timestamp))
            self.audit('create_draft','invoice',record_id); return self.one('invoices',record_id)
        if len(parts)==4 and parts[1]=='invoices':
            self.allow('admin','finance'); inv=self.one('invoices',parts[2]); action=parts[3]
            rules={'issue':('draft','issued','1100 Accounts receivable','4000 Revenue'),'payment':('issued','paid','1000 Cash','1100 Accounts receivable'),'void':('issued','void','4000 Revenue','1100 Accounts receivable')}
            require(action in rules,'Unknown invoice action',404)
            before,after,debit,credit=rules[action]; require(inv['status']==before,f'Invoice must be {before} for this action',409)
            self.post_ledger(inv,action,debit,credit)
            self.db.execute('UPDATE invoices SET status=? WHERE id=?',(after,inv['id'])); self.audit(action,'invoice',inv['id'],{'amount_cents':inv['total']})
            return self.one('invoices',inv['id'])
        if path=='/api/documents':
            self.write(); p=self.project_id(data)
            self.db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?)',(record_id,self.org,text(data,'title',limit=200),text(data,'body',limit=100000),p,self.user,timestamp))
            self.audit('create','document',record_id); return self.one('documents',record_id)
        if path=='/api/organization-units':
            self.allow('admin')
            self.db.execute('INSERT INTO organization_units VALUES(?,?,?,?,?,?)',(record_id,self.org,text(data,'name',limit=160),enum(data,'kind',{'branch','department'}),text(data,'location',False,500),timestamp))
            self.audit('create','organization_unit',record_id); return self.one('organization_units',record_id)
        if path=='/api/assets':
            self.allow('admin','manager'); p=self.project_id(data); assignee=data.get('assignee_id') or None
            if assignee:
                member=self.member(assignee)
                if p and self.project(p)['private']: require(member['role']=='admin' or self.db.execute('SELECT 1 FROM project_members WHERE project_id=? AND user_id=?',(p,assignee)).fetchone(),'Assignee needs project access')
            self.db.execute('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?,?)',(record_id,self.org,text(data,'name',limit=160),text(data,'tag',limit=80),text(data,'category',limit=80),assignee,p,money(data,'purchase_value'),'assigned' if assignee else 'available',text(data,'notes',False,10000),timestamp))
            self.audit('create','asset',record_id); return self.one('assets',record_id)
        if path=='/api/contracts':
            self.allow('admin','manager','finance'); p=self.project_id(data)
            start=date_value(data,'starts_on',True); end=date_value(data,'ends_on')
            require(not end or end>=start,'Contract end must not precede its start')
            self.db.execute('INSERT INTO contracts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(record_id,self.org,text(data,'title',limit=200),text(data,'counterparty',limit=200),enum(data,'kind',{'customer','supplier','employment','other'}),money(data,'value'),start,end,'draft',p,text(data,'notes',False,20000),self.user,timestamp))
            self.audit('create','contract',record_id); return self.one('contracts',record_id)
        if len(parts)==4 and parts[1]=='packages':
            package=next((p for p in PACKAGES['packages'] if p['id']==parts[2]),None); require(package is not None,'Package not found',404)
            if parts[3]=='activate':
                self.allow('admin')
                self.db.execute('INSERT OR IGNORE INTO installed_packages VALUES(?,?,?,?,?)',(self.org,package['id'],PACKAGES['contract_version'],timestamp,self.user)); self.audit('activate','industry_package',package['id']);return {'ok':True}
            if parts[3]=='records':
                self.write(); require(self.db.execute('SELECT 1 FROM installed_packages WHERE org_id=? AND package_id=?',(self.org,package['id'])).fetchone(),'Activate the package first',409)
                p=self.project_id(data); require(p is not None,'A project is required')
                payload={}
                for f in package['fields']:
                    if f['type']=='text': payload[f['key']]=text(data,f['key'],f.get('required',True),10000)
                    elif f['type']=='money': payload[f['key']]=money(data,f['key'])
                    elif f['type']=='integer': payload[f['key']]=integer(data,f['key'],1,1440)
                    elif f['type']=='date': payload[f['key']]=date_value(data,f['key'],True)
                    elif f['type']=='enum': payload[f['key']]=enum(data,f['key'],set(f['options']))
                self.db.execute('INSERT INTO extension_records VALUES(?,?,?,?,?,?,?)',(record_id,self.org,package['id'],p,json.dumps(payload),self.user,timestamp));self.audit('create','extension_record',record_id,{'package':package['id'],'project_id':p});return {'id':record_id,'package_id':package['id'],'project_id':p,'payload':payload}
        if path=='/api/meetings':
            self.write(); p=self.project_id(data); start=text(data,'starts_at',limit=40); end=text(data,'ends_at',limit=40)
            try:
                a,b=datetime.fromisoformat(start),datetime.fromisoformat(end)
                require(a.tzinfo is not None and b.tzinfo is not None and b>a,'Meeting end must be after start; timezone is required')
            except ValueError: raise APIError(400,'Use valid date-times with timezone')
            attendees=data.get('attendees',[]); require(isinstance(attendees,list) and len(attendees)<=100,'Invalid attendees')
            for user_id in attendees:
                m=self.member(user_id)
                if p and self.project(p)['private']: require(m['role']=='admin' or self.db.execute('SELECT 1 FROM project_members WHERE project_id=? AND user_id=?',(p,user_id)).fetchone(),'All attendees need project access')
            self.db.execute('INSERT INTO meetings VALUES(?,?,?,?,?,?,?,?,?)',(record_id,self.org,text(data,'title',limit=200),start,end,p,text(data,'notes',False,20000),self.user,timestamp))
            for user_id in set(attendees+[self.user]):
                self.db.execute('INSERT INTO meeting_attendees VALUES(?,?,?,?)',(self.org,record_id,user_id,'accepted' if user_id==self.user else 'pending'))
                if user_id!=self.user: self.notify(user_id,'You have a meeting invitation','meeting',record_id)
            self.audit('create','meeting',record_id); return self.one('meetings',record_id)
        if len(parts)==4 and parts[1]=='meetings' and parts[3]=='rsvp':
            m=self.visible_record('meetings',parts[2]); rsvp=enum(data,'rsvp',{'accepted','declined'})
            changed=self.db.execute('UPDATE meeting_attendees SET rsvp=? WHERE meeting_id=? AND user_id=?',(rsvp,m['id'],self.user)).rowcount
            require(changed==1,'You are not an attendee',403); return {'ok':True}
        if path=='/api/notifications/read':
            self.db.execute('UPDATE notifications SET read_at=? WHERE org_id=? AND user_id=?',(timestamp,self.org,self.user)); return {'ok':True}
        if path=='/api/extract':
            self.write(); m=self.message(text(data,'message_id',limit=32)); require(not m['deleted_at'],'Source message removed')
            c=self.conversation(m['conversation_id']); match=re.search(r'\b(?:need|order|buy|request|require)\s+(\d+)\s+(.+?)(?:\s+for\b|[.!?]|$)',m['body'],re.I)
            project_id=c['project_id'];link=self.db.execute('SELECT record_kind,record_id FROM conversation_records WHERE conversation_id=?',(c['id'],)).fetchone()
            if link:project_id=self.business_record(link['record_kind'],link['record_id']).get('project_id')
            return {'method':'rule_based','source_message_id':m['id'],'project_id':project_id,'quantity':int(match.group(1)) if match else 1,'item':match.group(2).strip() if match else m['body'][:200],'notes':m['body'],'requires_review':True}
        raise APIError(404,'Endpoint not found')

    def post_ledger(self, invoice, kind, debit, credit,posted_at=None):
        entry_id=uid(); amount=invoice['total']
        self.db.execute('INSERT INTO ledger_entries VALUES(?,?,?,?,?,?,?)',(entry_id,self.org,invoice['id'],kind,f'{kind}: {invoice["number"]}',self.user,posted_at or now()))
        self.db.executemany('INSERT INTO ledger_lines VALUES(?,?,?,?,?)',[(uid(),entry_id,debit,amount,0),(uid(),entry_id,credit,0,amount)])
        sums=self.db.execute('SELECT SUM(debit),SUM(credit) FROM ledger_lines WHERE entry_id=?',(entry_id,)).fetchone()
        require(sums[0]==sums[1],'Unbalanced journal entry',500)

    def patch(self, path, data):
        parts=path.strip('/').split('/'); require(len(parts)==3,'Endpoint not found',404)
        table,record_id=parts[1],parts[2]; timestamp=now()
        if table=='people':
            self.allow('admin'); member=self.member(record_id); role=enum(data,'role',ROLES,member['role'])
            if member['role']=='admin' and role!='admin': require(self.db.execute("SELECT COUNT(*) FROM memberships WHERE org_id=? AND role='admin' AND active=1",(self.org,)).fetchone()[0]>1,'Workspace must retain an administrator')
            self.db.execute('UPDATE memberships SET role=?,department=? WHERE org_id=? AND user_id=?',(role,text(data,'department',False,100),self.org,record_id)); self.audit('change_role','membership',record_id,{'role':role}); return {'ok':True}
        self.write()
        if table=='tasks':
            task=self.visible_record('tasks',record_id)
            require(self.role in ('admin','manager') or self.user in (task['assignee_id'],task['created_by']),'Only the assignee, creator or manager may update this task',403)
            status=enum(data,'status',{'todo','doing','done'},task['status'])
            self.db.execute('UPDATE tasks SET status=? WHERE id=?',(status,record_id)); self.audit('status','task',record_id,{'status':status}); return self.one('tasks',record_id)
        if table=='projects':
            p=self.project(record_id); require(self.role=='admin' or p['owner_id']==self.user,'Only the owner or administrator may update the project',403)
            status=enum(data,'status',{'active','at_risk','complete','archived'},p['status'])
            self.db.execute('UPDATE projects SET status=? WHERE id=?',(status,record_id)); self.audit('status','project',record_id,{'status':status}); return self.one('projects',record_id)
        if table=='customers':
            self.one('customers',record_id); stage=enum(data,'stage',{'lead','qualified','customer','inactive'})
            self.db.execute('UPDATE customers SET stage=? WHERE id=?',(stage,record_id)); self.audit('stage','customer',record_id,{'stage':stage}); return self.one('customers',record_id)
        if table=='messages':
            m=self.message(record_id); require(not m['deleted_at'],'Message removed')
            if 'pinned' in data:
                self.allow('admin','manager'); require(isinstance(data['pinned'],bool),'pinned must be boolean')
                self.db.execute('UPDATE messages SET pinned=? WHERE id=?',(int(data['pinned']),record_id)); self.audit('pin','message',record_id)
            else:
                require(m['author_id']==self.user,'Only the author can edit or remove a message',403)
                window=self.db.execute('SELECT message_edit_minutes FROM organizations WHERE id=?',(self.org,)).fetchone()[0]
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(m['created_at'])).total_seconds()
                require(age<=window*60,'The organization’s message editing window has expired',403)
                removed=data.get('deleted') is True
                body='' if removed else text(data,'body',limit=10000)
                self.db.execute('INSERT INTO message_history VALUES(?,?,?,?,?,?,?)',(uid(),self.org,record_id,m['body'],self.user,'removed' if removed else 'edited',timestamp))
                self.db.execute('UPDATE messages SET body=?,edited_at=?,deleted_at=? WHERE id=?',(body,timestamp,timestamp if removed else None,record_id)); self.audit('remove' if removed else 'edit','message',record_id)
            return self.one('messages',record_id)
        if table=='documents':
            return self.document_store().patch(record_id,data)
        if table=='requisitions':
            r=self.visible_record('requisitions',record_id)
            require(r['created_by']==self.user,'Only the requester may edit',403); require(r['status'] in ('draft','rejected'),'Submitted requisitions cannot be edited',409)
            self.db.execute('UPDATE requisitions SET item=?,quantity=?,unit_price=?,notes=?,status=? WHERE id=?',(text(data,'item',limit=200),integer(data,'quantity'),money(data,'unit_price'),text(data,'notes',False,10000),'draft',record_id)); self.audit('edit_draft','requisition',record_id); return self.one('requisitions',record_id)
        if table=='assets':
            self.allow('admin','manager'); self.visible_record('assets',record_id)
            status=enum(data,'status',{'available','assigned','maintenance','retired'})
            self.db.execute('UPDATE assets SET status=? WHERE id=?',(status,record_id));self.audit('status','asset',record_id,{'status':status});return self.one('assets',record_id)
        if table=='contracts':
            self.allow('admin','manager','finance'); self.visible_record('contracts',record_id)
            status=enum(data,'status',{'draft','active','closed'})
            self.db.execute('UPDATE contracts SET status=? WHERE id=?',(status,record_id));self.audit('status','contract',record_id,{'status':status});return self.one('contracts',record_id)
        raise APIError(404,'Endpoint not found')

class Handler(BaseHTTPRequestHandler):
    server_version='Nexus/1.0'

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, fmt, *args):
        # Avoid logging invitations, queries or message contents.
        print(f'{self.address_string()} {self.command} {urlsplit(self.path).path} {args[1] if len(args)>1 else ""}',flush=True)

    def headers_common(self,allow_frame=False):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','SAMEORIGIN' if allow_frame else 'DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors "+("'self'" if allow_frame else "'none'")+"; base-uri 'none'; form-action 'self'")

    def reply(self, value, status=200, cookie=None):
        payload=json.dumps(value,ensure_ascii=False).encode('utf-8')
        self.send_response(status); self.headers_common(); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(payload)))
        if cookie: self.send_header('Set-Cookie',cookie)
        self.end_headers(); self.wfile.write(payload)

    def body(self):
        if hasattr(self,'_request_data'):
            return self._request_data
        try: length=int(self.headers.get('Content-Length','0'))
        except ValueError: raise APIError(400,'Invalid body length')
        require(0<length<=MAX_BODY,'Request body missing or too large',413)
        require(self.headers.get_content_type()=='application/json','Use application/json',415)
        try: data=json.loads(self.rfile.read(length))
        except (ValueError,UnicodeDecodeError): raise APIError(400,'Invalid JSON')
        require(isinstance(data,dict),'JSON object required')
        self._request_data=data
        return data

    def check_origin(self):
        origin=self.headers.get('Origin')
        expected=f'{"https" if os.environ.get("NEXUS_SECURE_COOKIE")=="1" else "http"}://{self.headers.get("Host","")}'
        require(origin is None or origin==expected,'Cross-origin request denied',403)
        require(self.headers.get('Sec-Fetch-Site') not in ('cross-site',),'Cross-site request denied',403)

    def identity(self, db):
        cookies=SimpleCookie()
        try: cookies.load(self.headers.get('Cookie',''))
        except Exception: raise APIError(401,'Sign in required')
        token=cookies.get('nexus_session'); require(token is not None,'Sign in required',401)
        row=db.execute('SELECT s.*,u.name,u.email,m.role FROM sessions s JOIN users u ON u.id=s.user_id JOIN memberships m ON m.org_id=s.org_id AND m.user_id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND m.active=1',(digest(token.value),int(time.time()))).fetchone()
        require(row is not None,'Session expired. Sign in again.',401)
        if self.command!='GET': require(hmac.compare_digest(self.headers.get('X-CSRF-Token',''),row['csrf']),'Invalid CSRF token',403)
        if self.command!='GET':
            db.execute('UPDATE sessions SET last_seen=? WHERE token_hash=?',(int(time.time()),row['token_hash']))
        return dict(row)

    def session(self, db, user_id, org_id):
        token,csrf=secrets.token_urlsafe(40),secrets.token_urlsafe(24)
        current=int(time.time()); db.execute('DELETE FROM sessions WHERE expires_at<?',(current,))
        db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?)',(digest(token),user_id,org_id,csrf,current+SESSION_SECONDS,current))
        cookie=f'nexus_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}'
        if os.environ.get('NEXUS_SECURE_COOKIE')=='1': cookie+='; Secure'
        return {'ok':True,'csrf':csrf},cookie

    def auth(self, db, path, data):
        email=text(data,'email',limit=254).lower()
        password=data.get('password','')
        require(isinstance(password,str) and 0<len(password)<=1024,'Password is required (maximum 1024 characters)')
        require(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email),'Enter a valid email')
        key=digest(self.client_address[0]+'|'+email); current=int(time.time())
        attempt=db.execute('SELECT * FROM login_attempts WHERE key=?',(key,)).fetchone()
        require(not attempt or current-attempt['window_start']>=900 or attempt['failures']<10,'Too many attempts. Try again in 15 minutes.',429)
        user=db.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
        if path=='/api/auth/login':
            valid=password_valid(password,user['password_hash'] if user else 'pbkdf2_sha256$600000$'+'00'*16+'$'+'00'*32)
            if not user or not valid:
                db.execute('INSERT INTO login_attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET failures=CASE WHEN ?-window_start>=900 THEN 1 ELSE failures+1 END,window_start=CASE WHEN ?-window_start>=900 THEN ? ELSE window_start END',(key,current,current,current,current)); db.commit()
                raise APIError(401,'Email or password is incorrect')
            org=db.execute('SELECT org_id FROM memberships WHERE user_id=? AND active=1 ORDER BY org_id',(user['id'],)).fetchone()
            require(org is not None,'No active organization membership',403)
            db.execute('DELETE FROM login_attempts WHERE key=?',(key,)); return self.session(db,user['id'],org['org_id'])
        require(len(password)>=12,'Use a password with at least 12 characters')
        require(len(password.encode('utf-8'))<=1024,'Password is too long')
        if path=='/api/auth/register':
            require(user is None,'This email already has an account. Sign in or use an invitation.',409)
            name=text(data,'name',limit=160); org_name=text(data,'organization',limit=160)
            currency=enum(data,'currency',{'USD','EUR','GBP','ZAR'},'USD')
            user_id,org_id,timestamp=uid(),uid(),now()
            db.execute('INSERT INTO users VALUES(?,?,?,?,?)',(user_id,email,name,password_hash(password),timestamp))
            db.execute('INSERT INTO organizations(id,name,industry,currency,created_at) VALUES(?,?,?,?,?)',(org_id,org_name,text(data,'industry',False,100) or 'General',currency,timestamp))
            db.execute('INSERT INTO memberships(org_id,user_id,role) VALUES(?,?,?)',(org_id,user_id,'admin'))
            db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?,?)',(uid(),org_id,'general','channel',None,user_id,timestamp))
            service=Service(db,{'org_id':org_id,'user_id':user_id,'role':'admin'})
            service.audit('create_workspace','organization',org_id)
            return self.session(db,user_id,org_id)
        if path=='/api/auth/join':
            token=text(data,'token',limit=128)
            invitation=db.execute('SELECT * FROM invitations WHERE token_hash=? AND accepted_at IS NULL AND expires_at>?',(digest(token),current)).fetchone()
            require(invitation is not None and invitation['email'].lower()==email,'Invalid or expired invitation',400)
            if user:
                require(password_valid(password,user['password_hash']),'Email or password is incorrect',401); user_id=user['id']
            else:
                user_id=uid(); db.execute('INSERT INTO users VALUES(?,?,?,?,?)',(user_id,email,text(data,'name',limit=160),password_hash(password),now()))
            existing=db.execute('SELECT 1 FROM memberships WHERE org_id=? AND user_id=?',(invitation['org_id'],user_id)).fetchone()
            require(existing is None,'You already belong to this workspace',409)
            db.execute('INSERT INTO memberships(org_id,user_id,role,department) VALUES(?,?,?,?)',(invitation['org_id'],user_id,invitation['role'],invitation['department']))
            db.execute('UPDATE invitations SET accepted_at=? WHERE id=?',(now(),invitation['id']))
            Service(db,{'org_id':invitation['org_id'],'user_id':user_id,'role':invitation['role']}).audit('accept_invitation','membership',user_id)
            return self.session(db,user_id,invitation['org_id'])
        raise APIError(404,'Endpoint not found')

    def dispatch(self):
        path=urlsplit(self.path).path
        try:
            # Consume bounded bodies before returning an authorization error, avoiding
            # a TCP reset when a client is still sending its request.
            if self.command!='GET': self.body()
            # Reject DNS rebinding. Remote deployments must explicitly list their hosts.
            host=self.headers.get('Host','').split(':')[0].lower()
            allowed={'127.0.0.1','localhost'}|set(os.environ.get('NEXUS_ALLOWED_HOSTS','').lower().split(','))
            require(host in allowed,'Host is not allowed',403)
            if path=='/api/health' and self.command=='GET': return self.reply({'status':'ok','database':'sqlite','schema_version':5,'release':'2.1'})
            if not path.startswith('/api/'):
                require(self.command=='GET','Method not allowed',405)
                files={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/style.css':'style.css','/premium.css':'premium.css','/icons.js':'icons.js','/experience.js':'experience.js','/automation.js':'automation.js','/favicon.svg':'favicon.svg','/pdf-preview.html':'pdf-preview.html','/pdf-viewer.js':'pdf-viewer.js','/pdf-viewer.css':'pdf-viewer.css'}
                if path in files:file=ROOT/'web'/files[path]
                elif path.startswith('/vendor/pdfjs/'):
                    file=(ROOT/'web'/path.lstrip('/')).resolve()
                    require(file.is_relative_to((ROOT/'web/vendor/pdfjs').resolve()) and file.is_file(),'Not found',404)
                else:raise APIError(404,'Not found')
                payload=file.read_bytes();mime='text/javascript' if file.suffix in ('.js','.mjs') else mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
                self.send_response(200); self.headers_common(allow_frame=path=='/pdf-preview.html'); self.send_header('Content-Type',mime); self.send_header('Content-Length',str(len(payload))); self.end_headers(); self.wfile.write(payload); return
            if self.command!='GET': self.check_origin()
            with connect_db() as db:
                db.execute('BEGIN IMMEDIATE' if self.command!='GET' or path.startswith('/api/exports/') else 'BEGIN')
                if path=='/api/auth/demo' and self.command=='POST':
                    require(os.environ.get('NEXUS_DISABLE_DEMO')!='1','Demo workspaces are disabled',403)
                    require(self.client_address[0] in ('127.0.0.1','::1'),'Public demo creation is available on this computer only',403)
                    key=digest('demo|'+self.client_address[0]);current=int(time.time())
                    attempt=db.execute('SELECT * FROM login_attempts WHERE key=?',(key,)).fetchone()
                    require(not attempt or current-attempt['window_start']>=3600 or attempt['failures']<10,'Demo creation is limited to ten workspaces per hour',429)
                    db.execute('INSERT INTO login_attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET failures=CASE WHEN ?-window_start>=3600 THEN 1 ELSE failures+1 END,window_start=CASE WHEN ?-window_start>=3600 THEN ? ELSE window_start END',(key,current,current,current,current))
                    user_id=uid();db.execute('INSERT INTO users VALUES(?,?,?,?,?)',(user_id,'demo-'+user_id+'@example.invalid','Alex Morgan',password_hash(secrets.token_urlsafe(48)),now()))
                    import demo_data
                    org_id=demo_data.seed_demo(db,user_id,Service,password_hash)
                    value,cookie=self.session(db,user_id,org_id);db.commit();return self.reply(value,cookie=cookie)
                if path in ('/api/auth/register','/api/auth/login','/api/auth/join') and self.command=='POST':
                    value,cookie=self.auth(db,path,self.body()); db.commit(); return self.reply(value,cookie=cookie)
                identity=self.identity(db); service=Service(db,identity)
                if path=='/api/workflows' or path.startswith('/api/workflows/'):
                    engine=workflows.Workflows(service,require);parts=path.split('/')
                    if self.command=='GET':value=engine.list() if len(parts)==3 else engine.detail(parts[3])
                    elif self.command=='POST':value=engine.post(parts[3] if len(parts)>3 else None,parts[4] if len(parts)>4 else '',self.body())
                    else:raise APIError(405,'Method not allowed')
                    db.commit();return self.reply(value)
                if path.startswith('/api/exports/') and path.endswith('.csv') and self.command=='GET':
                    resource=path.split('/')[-1][:-4]
                    payload=make_csv(service,resource,parse_qs(urlsplit(self.path).query),require)
                    service.audit('export','report',resource,{'format':'csv'})
                    db.commit();self.send_response(200);self.headers_common();self.send_header('Content-Type','text/csv; charset=utf-8')
                    self.send_header('Content-Disposition','attachment; filename="nexus-'+resource+'.csv"');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload);return
                if path=='/api/demo-workspace' and self.command=='POST':
                    service.allow('admin');require(os.environ.get('NEXUS_DISABLE_DEMO')!='1','Demo workspaces are disabled',403)
                    import demo_data
                    org_id=demo_data.seed_demo(db,identity['user_id'],Service,password_hash)
                    db.execute('DELETE FROM sessions WHERE token_hash=?',(identity['token_hash'],))
                    value,cookie=self.session(db,identity['user_id'],org_id);db.commit();return self.reply(value,cookie=cookie)
                if path.startswith('/api/document-files/') and self.command=='GET':
                    f=service.document_store().file(path.split('/')[-1]);preview=parse_qs(urlsplit(self.path).query).get('preview',['0'])[0]=='1'
                    require(not preview or f['mime'] in PREVIEWABLE,'This format is available as a download only',415)
                    db.commit();self.send_response(200);self.headers_common(allow_frame=preview)
                    self.send_header('Content-Type',f['mime'] if preview else 'application/octet-stream')
                    self.send_header('Content-Disposition',('inline' if preview else 'attachment')+"; filename*=UTF-8''"+quote(f['filename'],safe=''))
                    self.send_header('Content-Length',str(len(f['content'])));self.end_headers();self.wfile.write(f['content']);return
                if path=='/api/assistant' and self.command=='POST':
                    data=self.body();conversation_id=text(data,'conversation_id',limit=32);service.conversation(conversation_id)
                    action=enum(data,'action',{'summary','actions','reply','translate'},'summary')
                    cutoff=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(timespec='microseconds')
                    count=db.execute("SELECT COUNT(*) FROM audit_log WHERE org_id=? AND actor_id=? AND record_type='ai_assistance' AND created_at>?",(identity['org_id'],identity['user_id'],cutoff)).fetchone()[0]
                    require(count<10,'AI assistance is limited to 10 requests per minute',429)
                    prompts={'summary':'Summarize the discussion, decisions and unresolved questions.','actions':'Extract proposed action items. For each, state an owner and deadline only when explicitly given. List decisions still requiring approval.','reply':'Draft a concise professional reply to the latest messages. Do not send it.','translate':'Translate the latest message into '+text(data,'language',False,50)+'. Preserve its meaning.'}
                    require(action!='translate' or bool(text(data,'language',False,50)),'Choose a target language')
                    rows=service.get('/api/conversations/'+conversation_id+'/messages',{})
                    context=[{k:r[k] for k in ('id','author_name','body')} for r in rows if not r['deleted_at']][-100:]
                    require(context,'The conversation has no messages to process')
                    service.audit('request_'+action,'ai_assistance',conversation_id,{'provider':ai_gateway.status()['destination']})
                    # Release the DB lock while the configured provider processes the request.
                    db.commit()
                    try: result=ai_gateway.generate(context,prompts[action])
                    except ai_gateway.ProviderError as exc: raise APIError(503,str(exc))
                    # Authorization may have changed while the provider was running.
                    refreshed=self.identity(db);Service(db,refreshed).conversation(conversation_id);db.commit()
                    return self.reply({'text':result,'source_message_ids':[r['id'] for r in context],'provider':ai_gateway.status()['destination'],'generated':True})
                if path=='/api/auth/switch' and self.command=='POST':
                    org_id=text(self.body(),'org_id',limit=32)
                    require(db.execute('SELECT 1 FROM memberships WHERE org_id=? AND user_id=? AND active=1',(org_id,identity['user_id'])).fetchone(),'You do not belong to this workspace',403)
                    db.execute('DELETE FROM sessions WHERE token_hash=?',(identity['token_hash'],))
                    value,cookie=self.session(db,identity['user_id'],org_id);db.commit();return self.reply(value,cookie=cookie)
                if path=='/api/auth/logout' and self.command=='POST':
                    db.execute('DELETE FROM sessions WHERE token_hash=?',(identity['token_hash'],)); db.commit(); return self.reply({'ok':True},cookie='nexus_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
                if path.startswith('/api/attachments/') and self.command=='GET':
                    a=service.one('attachments',path.split('/')[-1]); service.conversation(a['conversation_id']); m=service.message(a['message_id']); require(not m['deleted_at'],'Attachment unavailable',404)
                    db.commit(); self.send_response(200); self.headers_common(); self.send_header('Content-Type','application/octet-stream'); self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(a['filename'],safe='')); self.send_header('Content-Length',str(len(a['content']))); self.end_headers(); self.wfile.write(a['content']); return
                if self.command=='GET': value=service.get(path,parse_qs(urlsplit(self.path).query))
                elif self.command=='POST':
                    value=service.post(path,self.body())
                    creation_kinds={'/api/'+table:kind for kind,table in RECORD_TABLES.items()}
                    kind=creation_kinds.get(path)
                    if path.startswith('/api/requisitions/') and path.endswith('/order'):kind='purchase_order'
                    if kind and isinstance(value,dict) and value.get('id'):
                        value['conversation_id']=service.record_conversation(kind,value['id'])['id']
                elif self.command=='PATCH': value=service.patch(path,self.body())
                else: raise APIError(405,'Method not allowed')
                db.commit()
                if self.command=='GET':
                    db.execute('UPDATE sessions SET last_seen=? WHERE token_hash=?',(int(time.time()),identity['token_hash']))
                    db.commit()
                self.reply(value)
        except APIError as exc:
            self.reply({'error':exc.message},exc.status)
        except sqlite3.IntegrityError:
            self.reply({'error':'This operation conflicts with an existing record or record constraint.'},409)
        except sqlite3.OperationalError:
            self.reply({'error':'Database is busy or unavailable. Please retry.'},503)
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception as exc:
            # Trace server-side failures for operators; never include request bodies or credentials.
            import traceback
            traceback.print_exc()
            self.reply({'error':'Unexpected server error. The change was not saved.'},500)

    do_GET=dispatch
    do_POST=dispatch
    do_PATCH=dispatch
    do_DELETE=dispatch

def main():
    parser=argparse.ArgumentParser(description='Nexus business system')
    parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=4180)
    args=parser.parse_args(); initialize()
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    print(f'NEXUS is running at http://{args.host}:{args.port}',flush=True)
    print(f'Database: {DB_PATH}',flush=True)
    stop=threading.Event()
    def automation_worker():
        import sys
        while not stop.is_set():
            try:workflows.schedule_once(sys.modules[__name__])
            except Exception:
                import traceback;traceback.print_exc()
            stop.wait(60)
    worker=threading.Thread(target=automation_worker,daemon=True);worker.start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: stop.set();worker.join(timeout=20);server.server_close()

if __name__=='__main__': main()
