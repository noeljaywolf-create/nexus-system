"""CSV exports from authorized server records, in the selected table order."""
import csv
import io
import json
from decimal import Decimal
import re

SCHEMAS={
 'projects':('/api/projects',[('name','PROJECT'),('owner_name','OWNER'),('status','STATUS'),('budget','BUDGET',True),('due_date','DUE DATE')]),
 'tasks':('/api/tasks',[('title','TASK'),('assignee_name','ASSIGNEE'),('project_name','PROJECT'),('due_date','DUE DATE'),('priority','PRIORITY'),('status','STATUS')]),
 'customers':('/api/customers',[('name','NAME'),('company','COMPANY'),('email','EMAIL'),('phone','PHONE'),('stage','STAGE')]),
 'products':('/api/products',[('name','PRODUCT'),('sku','SKU'),('unit_price','UNIT PRICE',True),('stock','ON HAND'),('unit','UNIT')]),
 'suppliers':('/api/suppliers',[('name','SUPPLIER'),('email','EMAIL'),('notes','NOTES')]),
 'purchase-orders':('/api/purchase-orders',[('id','ORDER ID'),('supplier_name','SUPPLIER'),('item','ITEM'),('quantity','QUANTITY'),('total','TOTAL',True),('status','STATUS')]),
 'requisitions':('/api/requisitions',[('item','ITEM'),('requester_name','REQUESTER'),('project_name','PROJECT'),('quantity','QUANTITY'),('unit_price','UNIT PRICE',True),('status','STATUS')]),
 'invoices':('/api/invoices',[('number','INVOICE'),('customer_name','CUSTOMER'),('description','DESCRIPTION'),('total','TOTAL',True),('due_date','DUE DATE'),('status','STATUS')]),
 'ledger':('/api/ledger',[('created_at','POSTED AT'),('description','REFERENCE'),('account','ACCOUNT'),('debit','DEBIT',True),('credit','CREDIT',True)]),
 'assets':('/api/assets',[('name','ASSET'),('tag','TAG'),('category','CATEGORY'),('assignee_name','ASSIGNEE'),('project_name','PROJECT'),('purchase_value','VALUE',True),('status','STATUS')]),
 'contracts':('/api/contracts',[('title','CONTRACT'),('counterparty','COUNTERPARTY'),('kind','TYPE'),('value','VALUE',True),('starts_on','START'),('ends_on','END'),('status','STATUS')]),
 'people':('/api/people',[('name','NAME'),('email','EMAIL'),('department','DEPARTMENT'),('role','ROLE')]),
 'meetings':('/api/meetings',[('title','MEETING'),('starts_at','START'),('ends_at','END'),('notes','NOTES')]),
 'documents':('/api/documents',[('title','DOCUMENT'),('filename','FILENAME'),('folder','FOLDER'),('mime','FILE TYPE'),('version','VERSION'),('updated_at','UPDATED AT')]),
 'audit':('/api/audit',[('created_at','TIME'),('actor_name','ACTOR'),('action','ACTION'),('record_type','RECORD TYPE'),('record_id','RECORD ID'),('details','DETAILS')])
}

def make_csv(service,resource,query,require):
    if resource=='extension':
        package_id=query.get('package',[''])[0]
        package=next((p for p in service.get('/api/packages',{}) if p['id']==package_id),None)
        require(package is not None,'Package not found',404)
        records=service.get('/api/packages/'+package_id+'/records',{})
        records=[{**r,**r['payload']} for r in records]
        columns=[('project_name','PROJECT')]+[(f['key'],f['label'].upper(),True) if f['type']=='money' else (f['key'],f['label'].upper()) for f in package['fields']]+[('author_name','AUTHOR')]
    else:
        require(resource in SCHEMAS,'Export type not found',404)
        endpoint,columns=SCHEMAS[resource]
        records=service.get(endpoint,{'archived':query.get('archived',['0'])} if resource=='documents' else {})
        if resource=='ledger':records=records['lines']
    ids=query.get('ids',[''])[0].split(',') if query.get('ids',[''])[0] else None
    if ids is not None:
        require(len(ids)<=1000 and all(re.fullmatch(r'[a-f0-9]{32}',i) for i in ids),'Export at most 1,000 valid records at once')
        by_id={r['id']:r for r in records}
        require(all(i in by_id for i in ids),'Some records are no longer available. Refresh the table before exporting.',404)
        records=[by_id[i] for i in dict.fromkeys(ids)]
    require(len(records)<=1000,'Apply a filter to export no more than 1,000 records at once')
    currency=service.db.execute('SELECT currency FROM organizations WHERE id=?',(service.org,)).fetchone()[0]
    output=io.StringIO(newline='');writer=csv.writer(output)
    writer.writerow([c[1]+(' ('+currency+')' if len(c)>2 and c[2] else '') for c in columns])
    for record in records:
        values=[]
        for c in columns:
            value=record.get(c[0])
            if len(c)>2 and c[2]:value=f'{Decimal(value or 0)/100:.2f}'
            elif value is None:value=''
            elif isinstance(value,(list,dict)):value=json.dumps(value,ensure_ascii=False)
            value=str(value)
            if value.lstrip().startswith(('=','+','-','@','\t','\r')):value="'"+value
            values.append(value)
        writer.writerow(values)
    return ('\ufeff'+output.getvalue()).encode('utf-8')
