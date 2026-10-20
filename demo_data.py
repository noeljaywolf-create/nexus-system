"""Idempotent, isolated demonstration workspace populated through business services."""
import base64
from datetime import datetime,timedelta,timezone
import io
import json
import secrets
import uuid
import zipfile

def uid():return uuid.uuid4().hex
def iso(d):return d.isoformat(timespec='microseconds')

def sample_pdf(title,lines):
    def esc(t):return t.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
    commands=['BT /F1 22 Tf 48 780 Td ('+esc(title)+') Tj','/F1 10 Tf 0 -30 Td (MERIDIAN GROUP | DEMONSTRATION DOCUMENT) Tj']
    commands+=['0 -24 Td ('+esc(line)+') Tj' for line in lines]
    commands+=['0 -40 Td (SAMPLE DATA - NOT A COMMERCIAL OR LEGAL DOCUMENT) Tj ET']
    stream='\n'.join(commands).encode('latin-1','replace')
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    out=bytearray(b'%PDF-1.4\n');offsets=[0]
    for i,obj in enumerate(objects,1):offsets.append(len(out));out+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    xref=len(out);out+=f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()
    for offset in offsets[1:]:out+=f'{offset:010d} 00000 n \n'.encode()
    out+=f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return bytes(out)

def sample_docx():
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml','<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>MERIDIAN GROUP — Team onboarding guide</w:t></w:r></w:p><w:p><w:r><w:t>DEMONSTRATION DOCUMENT. Review your project assignments, read the safety handbook, and confirm your approval responsibilities with your manager.</w:t></w:r></w:p><w:sectPr/></w:body></w:document>')
    return output.getvalue()

def seed_demo(db,owner_id,service_class,password_hash):
    existing=db.execute('SELECT org_id FROM demo_workspaces WHERE owner_id=?',(owner_id,)).fetchone()
    if existing:return existing['org_id']
    now=datetime.now(timezone.utc);today=now.date();org=uid()
    owner=db.execute('SELECT name,email FROM users WHERE id=?',(owner_id,)).fetchone()
    db.execute('INSERT INTO organizations(id,name,industry,currency,created_at) VALUES(?,?,?,?,?)',(org,'Meridian Group','Diversified business services','USD',iso(now)))
    db.execute('INSERT INTO memberships(org_id,user_id,role,department) VALUES(?,?,?,?)',(org,owner_id,'admin','Executive office'))
    db.execute('INSERT INTO demo_workspaces VALUES(?,?,?,?)',(org,owner_id,2,iso(now)))
    def actor(user_id,role,name):return service_class(db,{'org_id':org,'user_id':user_id,'role':role,'name':name,'email':'demo@example.invalid'})
    admin=actor(owner_id,'admin',owner['name']);team=[]
    for name,role,dept in [('Sarah Chen','manager','Operations'),('James Wilson','manager','Procurement'),('Priya Patel','finance','Finance'),('Daniel Okafor','member','Engineering'),('Amara Ndlovu','member','Client success'),('Lerato Moyo','member','Marketing'),('David Lewis','manager','Delivery'),('Grace Mbeki','viewer','Operations')]:
        person=uid();email=name.lower().replace(' ','.')+'.'+org[:8]+'@example.invalid'
        db.execute('INSERT INTO users VALUES(?,?,?,?,?)',(person,email,name,password_hash(secrets.token_urlsafe(40)),iso(now)))
        db.execute('INSERT INTO memberships(org_id,user_id,role,department) VALUES(?,?,?,?)',(org,person,role,dept));team.append({'id':person,'name':name,'role':role,'service':actor(person,role,name)})
    sarah,james,priya,daniel,amara,lerato,david,grace=team
    for name,kind,location in [('Head office','branch','Harare'),('Regional office','branch','Johannesburg'),('Operations','department',''),('Finance','department',''),('Procurement','department',''),('Engineering','department',''),('Client success','department','')]:admin.post('/api/organization-units',{'name':name,'kind':kind,'location':location})
    general=admin.post('/api/conversations',{'name':'company-updates','kind':'channel'})
    ops=admin.post('/api/conversations',{'name':'operations','kind':'channel'})
    admin.post('/api/conversations/'+general['id']+'/messages',{'body':'Welcome to Meridian Group. This workspace contains sample business records so you can explore the full workflows. Changes here are saved only in this demo workspace.'})
    sarah['service'].post('/api/conversations/'+general['id']+'/messages',{'body':'Monday priorities: Riverside procurement review, Eastgate launch readiness, and the Q4 supplier review. Keep decisions in the relevant project conversation.'})
    priya['service'].post('/api/conversations/'+general['id']+'/messages',{'body':'Finance update: the latest invoices are ready for review. Please use the invoice discussion to resolve questions before posting.'})
    specs=[('Riverside Development','Site delivery and safety procurement for the Riverside commercial development.','248000',45,False,'active'),('Eastgate Retail Launch','Coordinate supplier onboarding, store setup and launch activities.','95000',21,False,'active'),('Client Portal Upgrade','Deliver the next release of the customer self-service portal.','42500',32,False,'active'),('Q4 Supply Chain Optimization','Reduce lead times and resolve delayed shipments with key suppliers.','86000',14,False,'at_risk'),('Solar Installation Program','Coordinate equipment, commissioning and delivery for the energy portfolio.','168000',65,True,'active'),('Brand & Website Refresh','Publish the updated website and customer communications.','32500',-6,False,'complete')]
    projects=[]
    for i,(name,description,budget,days,private,status) in enumerate(specs):
        p=admin.post('/api/projects',{'name':name,'description':description,'budget':budget,'due_date':str(today+timedelta(days=days)),'private':private})
        for person in team[:7]:admin.post('/api/projects/'+p['id']+'/members',{'user_id':person['id']})
        if status!='active':admin.patch('/api/projects/'+p['id'],{'status':status})
        conversation=db.execute('SELECT id FROM conversations WHERE project_id=?',(p['id'],)).fetchone()['id'];p['conversation_id']=conversation;projects.append(p)
        sarah['service'].post('/api/conversations/'+conversation+'/messages',{'body':f'{name}: this conversation is linked to our project record. Use it to capture decisions, raise blockers and assign follow-up work.'})
    river=projects[0]
    m=james['service'].post('/api/conversations/'+river['conversation_id']+'/messages',{'body':'We need 40 fire extinguishers for the new site. The safety inspection is scheduled for next week.'})
    sarah['service'].post('/api/conversations/'+river['conversation_id']+'/messages',{'body':'Please confirm the unit specification and supplier quote, then submit the requisition for review. We need the equipment on site before inspection.','parent_id':m['id']})
    daniel['service'].post('/api/conversations/'+river['conversation_id']+'/messages',{'body':'Site access is confirmed. I will coordinate delivery with the contractor once the purchase order is approved.'})
    sarah['service'].post('/api/messages/'+m['id']+'/react',{'emoji':'👀'})
    admin.patch('/api/messages/'+m['id'],{'pinned':True})
    task_names=['Confirm site safety equipment specification','Review supplier quotation','Complete contractor onboarding','Prepare weekly project update','Resolve delayed shipment','Approve revised delivery schedule','Validate inventory counts','Publish launch checklist','Review customer feedback','Finalize project handover','Prepare commissioning plan','Confirm site access arrangements','Update project cost forecast','Book customer review meeting','Review design acceptance criteria','Send monthly customer update','Prepare launch communication','Reconcile delivered quantities','Collect signed delivery notes','Update supplier lead times','Schedule quality inspection','Complete acceptance testing','Review budget variance','Close out resolved actions','Publish team onboarding guide','Review service renewal dates','Confirm warehouse allocation','Review project risk register','Update stakeholder contact list','Approve final website content']
    for i,title in enumerate(task_names):
        p=projects[i%len(projects)];person=team[i%7]
        t=admin.post('/api/tasks',{'title':title,'description':'Confirm the required information, document the outcome and update the project team.','project_id':p['id'],'assignee_id':person['id'],'priority':'high' if i%5==0 else 'normal','due_date':str(today+timedelta(days=(i%16)-3))})
        status='done' if p['id']==projects[-1]['id'] or i%4==0 else 'doing' if i%3==0 else 'todo'
        if status!='todo':admin.patch('/api/tasks/'+t['id'],{'status':status})
    customers=[]
    for i,(name,company) in enumerate([('Tariro Maseko','Riverside Partners'),('Michael Reed','Northstar Logistics'),('Nadia Khan','Eastgate Retail'),('Samuel Dube','Greenline Energy'),('Olivia Chen','Urban Property Group'),('James Kamau','Summit Engineering'),('Amina Banda','Bluewater Hospitality'),('David Ncube','Apex Manufacturing'),('Emma Wilson','Horizon Advisory'),('Liam Patel','Cedar Technology'),('Faith Moyo','Atlas Wholesale'),('Noah Mensah','Crest Professional Services')]):
        customers.append(admin.post('/api/customers',{'name':name,'company':company,'email':name.lower().replace(' ','.')+'@example.invalid','phone':'+000 555 '+str(1000+i),'stage':'customer' if i<8 else 'qualified' if i<10 else 'lead','notes':'Sample customer record for demonstration. Key account contacts and next steps are maintained by the client success team.'}))
    suppliers=[]
    for name in ['SafeGuard Industrial Supplies','Atlas Equipment Services','Northstar Distribution','Greenline Components','Precision Engineering Works','Metro Office Solutions','Prime Logistics Partners','Cedar Technology Services']:
        suppliers.append(admin.post('/api/suppliers',{'name':name,'email':name.lower().replace(' ','')+'@example.invalid','notes':'Demonstration supplier. Pricing and delivery details require purchasing review.'}))
    for i,(name,price,stock) in enumerate([('Fire extinguisher — 9 kg','120',12),('Safety helmet','24.50',120),('High-visibility vest','12.75',85),('First aid kit','65',24),('Site generator','2450',4),('Solar panel — 550 W','180',46),('Safety boots','58',32),('Cable reel — 100 m','145',18),('LED floodlight','78',26),('Workstation laptop','1250',8),('Office monitor','285',14),('Network switch','340',6),('Protective gloves','8.50',250),('Portable radio','96',20),('Mounting bracket set','36',55)]):
        product=admin.post('/api/products',{'name':name,'sku':f'MER-{i+1:04d}','unit':'each','unit_price':price})
        admin.post('/api/products/'+product['id']+'/stock',{'quantity':stock,'reason':'Demonstration opening stock'})
    requisitions=[]
    for i,(item,quantity,price,status) in enumerate([('Fire extinguishers — 9 kg',40,'120','submitted'),('Safety helmets',60,'24.50','submitted'),('Solar mounting brackets',80,'36','submitted'),('Warehouse handheld scanners',6,'460','draft'),('Site communication radios',12,'96','draft'),('LED floodlights',20,'78','approved'),('Protective gloves',100,'8.50','ordered'),('Network switches',4,'340','ordered'),('Portable generator',1,'2450','rejected')]):
        requester=james['service'];p=projects[i%5]
        payload={'item':item,'quantity':quantity,'unit_price':price,'project_id':p['id'],'notes':'Confirm specification, delivery date and budget allocation before ordering.'}
        if i==0:payload['source_message_id']=m['id']
        req=requester.post('/api/requisitions',payload);requisitions.append(req)
        if status!='draft':requester.post('/api/requisitions/'+req['id']+'/submit',{})
        if status in ('approved','ordered','rejected'):sarah['service'].post('/api/requisitions/'+req['id']+'/review',{'decision':'rejected' if status=='rejected' else 'approved','comment':'Please obtain a comparative quote.' if status=='rejected' else 'Specification and budget reviewed. Proceed within the approved amount.'})
        if status=='ordered':admin.post('/api/requisitions/'+req['id']+'/order',{'supplier_id':suppliers[i%len(suppliers)]['id']})
    invoice_amounts=[32500,18750,24600,19800,41200,28600,46250,23500,37800,24800,18500,32750,42400,15200,9600,12850,18600,22800]
    invoices=[]
    for i,amount in enumerate(invoice_amounts):
        offset=5-i%6 if i<12 else 0;month=now.year*12+now.month-1-offset;year,month0=divmod(month,12)
        day=min(4+i%12,max(1,today.day-2)) if offset==0 else 4+i%12
        issued=datetime(year,month0+1,day,9,0,tzinfo=timezone.utc);status='paid' if i<10 else 'issued' if i<15 else 'draft'
        inv=priya['service'].post('/api/invoices',{'number':f'MER-{today.year}-{i+1:04d}','customer_id':customers[i%len(customers)]['id'],'description':['Project delivery milestone','Monthly advisory services','Equipment and installation services'][i%3],'total':str(amount),'due_date':str((issued+timedelta(days=30)).date())});invoices.append(inv)
        db.execute('UPDATE invoices SET created_at=? WHERE id=?',(iso(issued),inv['id']))
        if status!='draft':
            priya['service'].post_ledger(inv,'issue','1100 Accounts receivable','4000 Revenue',iso(issued))
            if status=='paid':priya['service'].post_ledger(inv,'payment','1000 Cash','1100 Accounts receivable',iso(min(now,issued+timedelta(days=12))))
            db.execute('UPDATE invoices SET status=? WHERE id=?',(status,inv['id']))
            priya['service'].audit('seed_'+status,'invoice',inv['id'],{'demonstration':True,'amount_cents':inv['total']})
    for i,(name,category,value) in enumerate([('Site generator A','Power equipment','2450'),('Operations vehicle 01','Vehicles','28500'),('Engineering laptop 04','IT equipment','1250'),('Delivery vehicle 02','Vehicles','34200'),('Site survey equipment','Surveying','6800'),('Office network cabinet','IT infrastructure','3200'),('Solar test equipment','Electrical','4800'),('Project camera kit','Site equipment','1150')]):
        a=admin.post('/api/assets',{'name':name,'tag':f'AST-{i+1:04d}','category':category,'assignee_id':team[i%7]['id'],'project_id':projects[i%5]['id'],'purchase_value':value,'notes':'Sample asset register entry. Track assignment and condition changes in the asset record.'})
        if i==4:admin.patch('/api/assets/'+a['id'],{'status':'maintenance'})
    for i,title in enumerate(['Riverside delivery agreement','Eastgate launch services','Equipment maintenance agreement','Customer support renewal','Solar installation scope','Office lease schedule']):
        c=admin.post('/api/contracts',{'title':title,'counterparty':customers[i]['company'],'kind':'customer' if i%2==0 else 'supplier','value':str(15000+i*8500),'starts_on':str(today-timedelta(days=60)),'ends_on':str(today+timedelta(days=20+i*45)),'project_id':projects[i%5]['id'],'notes':'Demonstration contract metadata. This record is not an executed agreement.'});admin.patch('/api/contracts/'+c['id'],{'status':'active'})
    document_store=admin.document_store()
    fixtures=[
        ('Riverside safety procurement brief.pdf','Projects',['safety','riverside'],river['id'],sample_pdf('Riverside Safety Procurement Brief',['Project: Riverside Development','Requested equipment: 40 fire extinguishers, 9 kg','Estimated unit price: USD 120.00','Estimated total: USD 4,800.00','Review: specification, delivery date and budget approval','Owner: James Wilson | Reviewer: Sarah Chen'])),
        ('Quarterly operating review.pdf','General',['quarterly','operations'],None,sample_pdf('Quarterly Operating Review',['Portfolio: construction, services, logistics and energy','Focus areas: delivery reliability and customer follow-up','Review open purchase requests and overdue actions weekly.','Keep operational decisions linked to their business records.'])),
        ('Supplier review checklist.pdf','Operations',['supplier','procurement'],None,sample_pdf('Supplier Review Checklist',['1. Confirm specification and available stock.','2. Obtain and compare written quotations.','3. Check delivery terms and lead time.','4. Confirm purchasing authority and budget.','5. Record the decision before issuing an order.'])),
        ('Team onboarding guide.docx','People',['onboarding','team'],None,sample_docx()),
        ('Inventory planning.csv','Operations',['inventory','planning'],None,b'SKU,Product,Available,Reorder point\nMER-0001,Fire extinguisher 9 kg,12,25\nMER-0002,Safety helmet,120,40\nMER-0006,Solar panel 550 W,46,30\n'),
        ('Project delivery handbook.md','Projects',['delivery','handbook'],None,b'# Project delivery handbook\n\nEvery project has a clear owner, budget and due date.\n\n## Weekly review\n- Review overdue tasks and project risks.\n- Resolve purchase requests before making commitments.\n- Record decisions in the project conversation.\n\nThis is a demonstration handbook.\n'),
        ('Customer follow-up plan.txt','General',['customers','follow-up'],None,b'MERIDIAN GROUP - CUSTOMER FOLLOW-UP PLAN\n\nReview open customer actions every Monday.\nConfirm meeting notes and assigned owners.\nKeep relationship stages current.\n\nDemonstration document.\n'),
        ('Q4 supplier lead times.csv','Operations',['suppliers','q4'],projects[3]['id'],b'Supplier,Category,Lead time days,Review status\nSafeGuard Industrial Supplies,Safety,7,Confirmed\nAtlas Equipment Services,Equipment,14,Review\nNorthstar Distribution,Distribution,10,Confirmed\n')]
    documents=[]
    for filename,folder,tags,project_id,content in fixtures:
        documents.append(document_store.upload({'filename':filename,'content':base64.b64encode(content).decode(),'folder':folder,'tags':tags,'project_id':project_id,'body':'Demonstration business document. Open the file to review its contents.'}))
    document_store.upload({'filename':'Riverside safety procurement brief.pdf','content':base64.b64encode(sample_pdf('Riverside Safety Procurement Brief - Revision 2',['Quantity confirmed: 40 fire extinguishers','Budget estimate: USD 4,800.00','Delivery required before the site inspection.','Confirm final supplier selection after approval.'])).decode(),'version_note':'Updated delivery requirements and confirmed quantity.'},documents[0]['id'])
    for i,title in enumerate(['Weekly operations review','Riverside procurement decision','Eastgate launch readiness','Customer portfolio check-in']):
        start=(now+timedelta(days=i+1)).replace(hour=8+i,minute=0,second=0,microsecond=0)
        admin.post('/api/meetings',{'title':title,'starts_at':iso(start),'ends_at':iso(start+timedelta(minutes=45)),'project_id':projects[i]['id'],'attendees':[team[i]['id'],team[(i+1)%7]['id']],'notes':'Review progress, resolve blockers and confirm the next actions. Bring the current project record and open approval requests.'})
    for package in ['construction-costing','professional-timesheets']:admin.post('/api/packages/'+package+'/activate',{})
    for i,(category,amount) in enumerate([('materials','12400'),('labor','8600'),('equipment','3200'),('subcontractor','14800')]):admin.post('/api/packages/construction-costing/records',{'project_id':river['id'],'description':category.title()+' — site delivery','category':category,'amount':amount,'date':str(today-timedelta(days=i*4)),'notes':'Demonstration cost allocation.'})
    for i in range(5):admin.post('/api/packages/professional-timesheets/records',{'project_id':projects[2]['id'],'description':['Customer discovery workshop','Portal design review','Implementation planning','Acceptance testing','Project coordination'][i],'minutes':[90,120,180,150,60][i],'hourly_rate':'85','date':str(today-timedelta(days=i)),'billing':'billable'})
    admin.audit('seed_demo','organization',org,{'seed_version':2,'sample_data':True})
    return org
