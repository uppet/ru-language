// Diagnostic coordinates are one-based Unicode code points, not UTF-16 offsets.
export function diagnosticRange(source,line,col) {
  if(typeof source!=='string'||!Number.isSafeInteger(line)||line<1)return null;
  const lines=source.split('\n');if(line>lines.length)return null;
  const text=lines[line-1].replace(/\r$/,''),points=Array.from(text);
  if(col!=null&&(!Number.isSafeInteger(col)||col<1||col>points.length+1))return null;
  const start=lines.slice(0,line-1).reduce((n,s)=>n+s.length+1,0),offset=col==null?0:points.slice(0,col-1).join('').length;
  return {line,col:col??null,start:start+offset,end:start+offset+(col==null?text.length:points[col-1]?.length||0)};
}

// Never infer source identity by splitting formatted output (paths may contain ':').
export async function sourceVersion(source) {
  const bytes=new TextEncoder().encode(source),hash=await crypto.subtle.digest('SHA-256',bytes);
  return Array.from(new Uint8Array(hash),byte=>byte.toString(16).padStart(2,'0')).join('');
}
export function captureDiagnostic(book,event) {
  const detail=event.diagnostic,origin=detail?.source;
  if(!detail||origin?.kind!=='cell')return null;
  const target=book.cells.find(cell=>cell.id===origin.cell_id),snapshot=target?.diagnosticSnapshot;
  if(!snapshot||snapshot.execution!==origin.execution_count||snapshot.generation!==origin.generation||snapshot.version!==origin.source_version)return null;
  const range=diagnosticRange(snapshot.source,detail.line,detail.col);if(!range)return null;
  return {targetId:target.id,snapshot:snapshot.source,execution:snapshot.execution,generation:snapshot.generation,version:snapshot.version,range,message:String(detail.message||event.message||'运行错误')};
}
export function currentDiagnostic(cell,record) {
  return !cell.historical&&!cell.stale&&record.snapshot===cell.source&&record.execution===cell.execution_count&&cell.diagnosticSnapshot?.version===record.version&&cell.diagnosticSnapshot?.generation===record.generation;
}

function textPoint(root,offset) {
  const walker=root.ownerDocument.createTreeWalker(root,4);let node,last;
  while((node=walker.nextNode())){last=node;if(offset<=node.length)return [node,offset];offset-=node.length;}
  return last?[last,last.length]:null;
}
function glyphRect(pre,range) {
  const start=textPoint(pre,range.start),end=textPoint(pre,range.end);if(!start||!end)return null;
  const selection=pre.ownerDocument.createRange();selection.setStart(...start);selection.setEnd(...end);
  return selection.getBoundingClientRect();
}

let nextDiagnosticId=0;
export function mountDiagnosticMarkers({input,pre,layer,numbers,records}) {
  const doc=input.ownerDocument,overlay=doc.createElement('div');overlay.className='diagnostic-layer';overlay.setAttribute('aria-hidden','true');layer.append(overlay);
  const summary=doc.createElement('span');summary.className='diagnostic-accessible';summary.id='diagnostic-summary-'+(++nextDiagnosticId);layer.append(summary);input.setAttribute('aria-errormessage',summary.id);
  function render() {
    overlay.replaceChildren();const active=records();
    input.setAttribute('aria-invalid',active.length?'true':'false');
    const description=active.map(record=>`第 ${record.range.line} 行`+(record.range.col==null?'':`，第 ${record.range.col} 列`)+`：${record.message}`).join('；');if(summary.textContent!==description)summary.textContent=description;
    if(!active.length){numbers.textContent=input.value.split('\n').map((_,i)=>i+1).join('\n');return;}
    numbers.replaceChildren();
    const errorLines=new Set(active.map(record=>record.range.line));
    const lines=input.value.split('\n');lines.forEach((_,i)=>{const number=doc.createElement('span');number.textContent=String(i+1);if(errorLines.has(i+1))number.className='diagnostic-line-number';numbers.append(number);if(i<lines.length-1)numbers.append(doc.createTextNode('\n'));});
    for(const record of active){
      const row=doc.createElement('div');row.className='diagnostic-row';row.style.top=(18+(record.range.line-1)*25)+'px';overlay.append(row);
      const rect=glyphRect(pre,record.range),box=layer.getBoundingClientRect();
      if(rect&&rect.height){const mark=doc.createElement('div');mark.className='diagnostic-column';mark.style.left=(rect.left-box.left)+'px';mark.style.top=(rect.bottom-box.top-3)+'px';mark.style.width=Math.max(7,rect.width)+'px';overlay.append(mark);}
    }
  }
  function focus(record) {
    const range=record.range;input.focus({preventScroll:true});input.setSelectionRange(range.start,range.end);
    const rect=glyphRect(pre,range),box=input.getBoundingClientRect();
    if(rect){if(rect.left<box.left+20)input.scrollLeft=Math.max(0,input.scrollLeft+rect.left-box.left-24);else if(rect.right>box.right-20)input.scrollLeft+=rect.right-box.right+24;}
    input.dispatchEvent(new Event('scroll'));render();
    const row=Array.from(overlay.querySelectorAll('.diagnostic-row')).find(node=>node.style.top===(18+(range.line-1)*25)+'px');if(row)row.scrollIntoView({block:'center',behavior:'instant'});else input.scrollIntoView({block:'nearest'});
  }
  input.addEventListener('scroll',render);
  const observer=typeof ResizeObserver==='function'?new ResizeObserver(render):null;observer?.observe(layer);
  // Disconnected editors are garbage collected after the observer is released.
  return {render,focus,dispose:()=>observer?.disconnect()};
}
