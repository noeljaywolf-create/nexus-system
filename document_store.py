"""Authorized document library, immutable file versions and bounded uploads."""
import base64
import binascii
import hashlib
import io
import json
from pathlib import PurePath
import uuid
import zipfile
from datetime import datetime,timezone

MAX_FILE=20*1024*1024
FORMATS={'.pdf':'application/pdf','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','.pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation','.txt':'text/plain','.csv':'text/csv','.md':'text/markdown','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg'}
PREVIEWABLE={'application/pdf','image/png','image/jpeg','text/plain','text/csv','text/markdown'}

def timestamp():return datetime.now(timezone.utc).isoformat(timespec='microseconds')
def new_id():return uuid.uuid4().hex

class DocumentStore:
    def __init__(self,service,require,text,error):
        self.s=service;self.db=service.db;self.require=require;self.text=text;self.error=error

    def metadata(self,document_id):
        row=self.db.execute('SELECT * FROM document_metadata WHERE org_id=? AND document_id=?',(self.s.org,document_id)).fetchone()
        return dict(row) if row else {'folder':'General','tags':'[]','archived_at':None,'record_kind':None,'record_id':None}

    def authorize(self,document_id):return self.s.visible_record('documents',document_id)

    def list(self,query):
        archived=query.get('archived',['0'])[0]=='1'
        rows=self.s.rows("SELECT d.*,u.name author_name,COALESCE(md.folder,'General') folder,COALESCE(md.tags,'[]') tags,md.archived_at,md.record_kind,md.record_id,p.name project_name,f.id file_id,f.filename,f.mime,f.size,f.version FROM documents d JOIN users u ON u.id=d.created_by LEFT JOIN document_metadata md ON md.document_id=d.id LEFT JOIN projects p ON p.id=d.project_id LEFT JOIN document_files f ON f.id=(SELECT id FROM document_files WHERE document_id=d.id ORDER BY version DESC LIMIT 1) WHERE d.org_id=? ORDER BY d.updated_at DESC",(self.s.org,))
        result=[]
        for r in rows:
            if bool(r['archived_at'])!=archived:continue
            try:self.authorize(r['id'])
            except self.error:continue
            r['tags']=json.loads(r['tags']);r['previewable']=r['mime'] in PREVIEWABLE
            result.append(r)
        return result

    def detail(self,document_id):
        d=self.authorize(document_id);meta=self.metadata(document_id)
        d.update(meta);d['id']=document_id;d['tags']=json.loads(meta['tags'])
        d['versions']=self.s.rows('SELECT f.id,f.version,f.filename,f.mime,f.size,f.sha256,f.version_note,f.created_at,u.name uploaded_by_name FROM document_files f JOIN users u ON u.id=f.uploaded_by WHERE f.org_id=? AND f.document_id=? ORDER BY f.version DESC',(self.s.org,document_id))
        for v in d['versions']:v['previewable']=v['mime'] in PREVIEWABLE
        return d

    def file(self,file_id):
        file=self.s.one('document_files',file_id);self.authorize(file['document_id']);return file

    def parse_file(self,data):
        name=self.text(data,'filename',limit=180)
        self.require('/' not in name and '\\' not in name and not any(ord(c)<32 for c in name),'Use a filename without path or control characters')
        ext=PurePath(name).suffix.lower();self.require(ext in FORMATS,'Supported formats: PDF, DOCX, XLSX, PPTX, TXT, CSV, MD, PNG and JPG')
        encoded=self.text(data,'content',limit=28*1024*1024)
        try:content=base64.b64decode(encoded,validate=True)
        except (ValueError,binascii.Error):self.require(False,'The file encoding is invalid')
        self.require(0<len(content)<=MAX_FILE,'Choose a file between 1 byte and 20 MB')
        if ext=='.pdf':self.require(content.lstrip().startswith(b'%PDF-'),'This file is not a valid PDF')
        elif ext=='.png':self.require(content.startswith(b'\x89PNG\r\n\x1a\n'),'This file is not a valid PNG')
        elif ext in ('.jpg','.jpeg'):self.require(content.startswith(b'\xff\xd8\xff'),'This file is not a valid JPEG')
        elif ext in ('.docx','.xlsx','.pptx'):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    infos=archive.infolist();names={i.filename for i in infos}
                    required={'.docx':'word/document.xml','.xlsx':'xl/workbook.xml','.pptx':'ppt/presentation.xml'}[ext]
                    self.require(required in names and '[Content_Types].xml' in names,'The Office document structure is invalid')
                    self.require(not any('vbaproject' in name.lower() for name in names),'Macro-enabled documents are not supported')
                    self.require(len(infos)<=10000 and sum(i.file_size for i in infos)<=200*1024*1024,'The Office document expands beyond supported limits')
            except (zipfile.BadZipFile,ValueError):self.require(False,'This file is not a valid Office document')
        else:
            try:content.decode('utf-8-sig')
            except UnicodeDecodeError:self.require(False,'Text documents must use UTF-8 encoding')
            self.require(b'\x00' not in content,'Text documents must not contain binary null bytes')
        return name,FORMATS[ext],content

    def tags(self,data):
        values=data.get('tags',[])
        if isinstance(values,str):values=[x.strip() for x in values.split(',') if x.strip()]
        self.require(isinstance(values,list) and len(values)<=12,'Use no more than 12 tags')
        self.require(all(isinstance(x,str) and 0<len(x.strip())<=40 for x in values),'Each tag must have 1–40 characters')
        return list(dict.fromkeys(x.strip() for x in values))

    def upload(self,data,document_id=None):
        self.s.write();filename,mime,content=self.parse_file(data);created=timestamp()
        if document_id:
            doc=self.authorize(document_id)
            self.require(self.s.role in ('admin','manager') or doc['created_by']==self.s.user,'Only the document owner or a manager may upload a version',403)
            self.require(not self.metadata(document_id)['archived_at'],'Restore the document before adding a version',409)
        else:
            project_id=self.s.project_id(data);kind=data.get('record_kind') or None;linked_id=data.get('record_id') or None
            if kind:
                self.require(kind in ('customer','supplier','invoice','requisition','task','asset','contract','meeting','purchase_order'),'Unsupported linked record')
                linked_id=self.text(data,'record_id',limit=32)
                linked=self.s.business_record(kind,linked_id)
                linked_project=linked.get('project_id')
                self.require(not linked_project or not project_id or linked_project==project_id,'The linked record belongs to a different project')
                project_id=linked_project or project_id
            else:self.require(not linked_id,'Choose a linked record type')
            title=self.text(data,'title',False,200) or PurePath(filename).stem
            body=self.text(data,'body',False,100000)
            if not body and mime in ('text/plain','text/csv','text/markdown'):body=content.decode('utf-8-sig')[:100000]
            document_id=new_id()
            self.db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?)',(document_id,self.s.org,title,body,project_id,self.s.user,created))
            folder=self.text(data,'folder',False,80) or 'General';tags=self.tags(data)
            self.db.execute('INSERT INTO document_metadata VALUES(?,?,?,?,?,?,?)',(self.s.org,document_id,folder,json.dumps(tags),None,kind,linked_id))
        latest=self.db.execute('SELECT version,sha256,id FROM document_files WHERE document_id=? ORDER BY version DESC LIMIT 1',(document_id,)).fetchone()
        sha=hashlib.sha256(content).hexdigest()
        if latest and latest['sha256']==sha:return {'id':document_id,'file_id':latest['id'],'version':latest['version'],'unchanged':True}
        version=latest['version']+1 if latest else 1;file_id=new_id()
        self.db.execute('INSERT INTO document_files VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(file_id,self.s.org,document_id,version,filename,mime,len(content),sha,content,self.s.user,self.text(data,'version_note',False,2000),created))
        self.db.execute('UPDATE documents SET updated_at=? WHERE id=?',(created,document_id))
        self.s.audit('upload_version' if latest else 'upload','document',document_id,{'filename':filename,'size':len(content),'version':version,'sha256':sha})
        self.s.record_conversation('document',document_id)
        return {'id':document_id,'file_id':file_id,'version':version,'unchanged':False}

    def patch(self,document_id,data):
        self.s.write();doc=self.authorize(document_id)
        self.require(self.s.role in ('admin','manager') or doc['created_by']==self.s.user,'Only the document owner or a manager may edit this document',403)
        meta=self.metadata(document_id);created=timestamp()
        title=self.text(data,'title',limit=200) if 'title' in data else doc['title']
        body=self.text(data,'body',False,100000) if 'body' in data else doc['body']
        folder=self.text(data,'folder',False,80) if 'folder' in data else meta['folder']
        tags=self.tags(data) if 'tags' in data else json.loads(meta['tags'])
        archived=meta['archived_at']
        if 'archived' in data:
            self.require(isinstance(data['archived'],bool),'archived must be true or false')
            archived=created if data['archived'] else None
        self.db.execute('UPDATE documents SET title=?,body=?,updated_at=? WHERE id=?',(title,body,created,document_id))
        self.db.execute('INSERT INTO document_metadata VALUES(?,?,?,?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET folder=excluded.folder,tags=excluded.tags,archived_at=excluded.archived_at',(self.s.org,document_id,folder or 'General',json.dumps(tags),archived,meta['record_kind'],meta['record_id']))
        self.s.audit('archive' if 'archived' in data and data['archived'] else 'restore' if 'archived' in data else 'edit','document',document_id)
        return self.detail(document_id)
