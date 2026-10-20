import * as pdfjs from '/vendor/pdfjs/pdf.mjs';
pdfjs.GlobalWorkerOptions.workerSrc='/vendor/pdfjs/pdf.worker.mjs';
const $=id=>document.getElementById(id);
const file=new URLSearchParams(location.search).get('file');
let documentHandle=null,pageNumber=1,renderJob=null,generation=0;
function error(message){$('status').hidden=false;$('status').textContent=message;$('status').className='error';$('page').hidden=true;}
async function render(){
  const current=++generation;if(renderJob){renderJob.cancel();try{await renderJob.promise;}catch{}}
  const page=await documentHandle.getPage(pageNumber);if(current!==generation)return;
  const original=page.getViewport({scale:1}),width=Math.max(180,$('canvasHost').clientWidth-34),choice=$('zoom').value;
  let scale=choice==='fit'?width/original.width:Number(choice);scale=Math.min(scale,Math.sqrt(8_000_000/(original.width*original.height)));
  const viewport=page.getViewport({scale}),canvas=$('page'),density=Math.min(window.devicePixelRatio||1,2);
  canvas.width=Math.floor(viewport.width*density);canvas.height=Math.floor(viewport.height*density);$('pageLabel').textContent=`${pageNumber} / ${documentHandle.numPages}`;
  canvas.style.width=Math.floor(viewport.width)+'px';canvas.style.height=Math.floor(viewport.height)+'px';
  canvas.setAttribute('aria-label',`PDF page ${pageNumber} of ${documentHandle.numPages}`);$('previous').disabled=pageNumber<=1;$('next').disabled=pageNumber>=documentHandle.numPages;
  $('status').hidden=false;$('status').className='';$('status').textContent='Rendering page…';canvas.hidden=true;
  renderJob=page.render({canvasContext:canvas.getContext('2d'),viewport,transform:density===1?null:[density,0,0,density,0,0]});
  try{await renderJob.promise;}catch(e){if(e.name==='RenderingCancelledException')return;throw e;}
  if(current!==generation)return;canvas.hidden=false;$('status').hidden=true;
  const content=await page.getTextContent();if(current!==generation)return;
  $('pageText').textContent=content.items.map(item=>item.str+(item.hasEOL?'\n':' ')).join('');$('accessibleText').hidden=false;
}
async function start(){
  if(!/^[a-f0-9]{32}$/.test(file||'')){error('No valid document was selected.');return;}
  $('download').href='/api/document-files/'+file;
  try{
    const response=await fetch('/api/document-files/'+file+'?preview=1',{credentials:'same-origin'});
    if(!response.ok){const result=await response.json().catch(()=>({}));throw new Error(result.error||'The document is unavailable.');}
    const data=new Uint8Array(await response.arrayBuffer());
    documentHandle=await pdfjs.getDocument({data,isEvalSupported:false,useSystemFonts:true,useWasm:false,cMapUrl:'/vendor/pdfjs/cmaps/',cMapPacked:true,standardFontDataUrl:'/vendor/pdfjs/standard_fonts/',wasmUrl:'/vendor/pdfjs/wasm/',iccUrl:'/vendor/pdfjs/iccs/'}).promise;
    await render();
  }catch(e){error(e.name==='PasswordException'?'This PDF is password protected. Download it to open in a compatible reader.':e.message||'The PDF could not be rendered. You can still download the original file.');}
}
$('previous').addEventListener('click',()=>{if(pageNumber>1){pageNumber--;render().catch(e=>error(e.message));}});
$('next').addEventListener('click',()=>{if(documentHandle&&pageNumber<documentHandle.numPages){pageNumber++;render().catch(e=>error(e.message));}});
$('zoom').addEventListener('change',()=>{if(documentHandle)render().catch(e=>error(e.message));});
let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(documentHandle&&$('zoom').value==='fit')render().catch(e=>error(e.message));},150);});
start();
