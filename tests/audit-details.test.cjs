const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const helpers=source.slice(source.indexOf('function auditLabel('),source.indexOf('async function audit('));
const context=vm.createContext({escape:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;')});
vm.runInContext(helpers,context);
test('request-only details show a collapsed technical reference, not JSON',()=>{
  const html=context.auditDetails('{"request_id":"trace-123"}');
  assert.match(html,/No additional details/);assert.match(html,/<details class="audit-trace">/);
  assert.doesNotMatch(html,/\{"request_id"| open[ >]/);
});
test('business fields are readable and values are escaped',()=>{
  const html=context.auditDetails({active:false,department:'<script>alert(1)</script>',unit_price:3000});
  assert.match(html,/Active/);assert.match(html,/No/);assert.match(html,/Unit price/);
  assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
});
test('nested values and malformed data are handled without raw JSON',()=>{
  assert.match(context.auditDetails({changes:{role:'finance'},members:['John','Jane']}),/Role: finance/);
  for(const value of ['not json','null','[]','{}'])assert.doesNotThrow(()=>context.auditDetails(value));
  assert.equal(context.auditLabel('create_workspace'),'Create workspace');
});
