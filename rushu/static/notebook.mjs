import {validateScene} from './scene.mjs';
import {validateGeneration} from './history.mjs';
/** Portable document data only. No executable JavaScript or kernel state. */
export const FORMAT='rushu-notebook';
export const MAX_FILE_BYTES=64*1024*1024;
export const MAX_CELLS=500;
export const MAX_SOURCE=200000;
export const MAX_OUTPUT=2*1024*1024; // UTF-8 bytes, including diagnostics
export const MAX_BOOK_OUTPUT=8*1024*1024;
export function newId() { return 'cell-'+(globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2)+Date.now().toString(36)); }
export function newCell(type='code',source='') { return {id:newId(),type,source,execution_count:null,outputs:[],historical:false,status:'idle'}; }
export function blankBook() { return {title:'未命名如书',cells:[newCell()]}; }
export function welcomeBook() {
  return {title:'第一本如书',cells:[
    newCell('markdown','# 从一句话开始\n\n如书，让想法与代码写在一起。每个代码格共享这本书的运行会话，你可以一步步试验，也可以从头运行。\n\n按 **Shift + Enter** 运行当前格并移到下一格。先试试下面的问候。'),
    newCell('code',"问候 取 '你好，如书'.\n显 问候."),
    newCell('markdown','## 把想法接下去\n\n上一格的名字依然可用。下面用匿名函数，把一个数变成它的平方。'),
    newCell('code',"平方 取 算 数值 为 数:\n    得 数值 * 数值.\n法.\n\n显 问候.\n显 (平方 9)."),
    newCell('markdown','## 保存事实与典\n\n事实只有 `真`、`假` 两个值。用 `典: 目 对 相. 成` 保存目与相，`查 目:` 读取。'),
    newCell('code',"资料 取 典:\n    '标题' 对 问候.\n    '就绪' 对 真.\n成.\n显 (资料 其 查 目: '标题').\n显 (资料 其 查 目: '就绪').")
  ]};
}
export function parseBook(text) {
  if(typeof text!=='string'||new TextEncoder().encode(text).length>MAX_FILE_BYTES) throw new Error('文件太大，请打开 64 MiB 以内的如书。');
  let raw; try { raw=JSON.parse(text); } catch { throw new Error('无法读取 JSON，请选择 .rushu.json 文件。'); }
  if(!raw||raw.format!==FORMAT||raw.version!==1) throw new Error('不支持的如书格式。需要 rushu-notebook 第 1 版文件。');
  if(typeof raw.title!=='string'||raw.title.length>200) throw new Error('书名需要是 200 字以内的文字。');
  if(!Array.isArray(raw.cells)||raw.cells.length>MAX_CELLS) throw new Error('一本如书最多容纳 500 格。');
  const ids=new Set();let bookOutput=0;
  const cells=raw.cells.map((cell,index)=>{
    const fail=message=>{throw new Error(`第 ${index+1} 格：${message}`);};
    if(!cell||!['code','markdown'].includes(cell.type)) fail('格子类型无效。');
    if(typeof cell.source!=='string'||cell.source.length>MAX_SOURCE) fail('内容需要是 200,000 字符以内的文字。');
    const id=typeof cell.id==='string'&&/^[\w-]{1,128}$/.test(cell.id)&&!ids.has(cell.id)?cell.id:newId(); ids.add(id);
    if(cell.execution_count!=null&&(!Number.isSafeInteger(cell.execution_count)||cell.execution_count<1)) fail('运行次数无效。');
    const outputs=cell.outputs??[];
    if(!Array.isArray(outputs)||outputs.length>2048) fail('输出数量无效。');
    let count=0;
    const safeOutputs=outputs.map(output=>{
      if(output?.type==='graphics'){let scene;try{scene=validateScene(output.scene);}catch(error){fail(error.message);}count+=byteLength(JSON.stringify(scene));if(count>MAX_OUTPUT)fail('保存的输出过大。');return {type:'graphics',scene:{...scene,running:false,handlers:[]}};}
      if(!output||!['stdout','stderr','error','input'].includes(output.type)||typeof output.text!=='string') fail('输出内容无效。');
      count+=byteLength(output.text); if(count>MAX_OUTPUT) fail('保存的输出过大。');
      return {type:output.type,text:output.text};
    });
    bookOutput+=count;if(bookOutput>MAX_BOOK_OUTPUT)fail('全书保存输出超过 8 MiB。');
    const backend=cell.execution_backend;
    if(backend!==undefined&&(!['python','browser-js'].includes(backend)||cell.type!=='code'))fail('运行方式无效。');
    let generation;
    if(Object.hasOwn(cell,'generation')) {
      if(cell.type!=='code') fail('只有代码格可以保存生成历史。');
      try { generation=validateGeneration(cell.generation); } catch(error) { fail(error.message); }
    }
    return {...newCell(cell.type,cell.source),...(generation?{generation}:{}),...(backend?{execution_backend:backend}:{}),id,execution_count:cell.execution_count??null,outputs:safeOutputs,historical:!!(safeOutputs.length||cell.execution_count),status:'idle'};
  });
  return {title:raw.title||'未命名如书',cells:cells.length?cells:[newCell()]};
}
export function serializeBook(book) {
  const text=JSON.stringify({format:FORMAT,version:1,title:book.title,updated_at:new Date().toISOString(),cells:book.cells.map(cell=>({id:cell.id,type:cell.type,source:cell.source,...(cell.execution_backend===undefined?{}:{execution_backend:cell.execution_backend}),...(cell.generation===undefined?{}:{generation:validateGeneration(cell.generation)}),execution_count:cell.execution_count??null,outputs:cell.outputs.map(item=>item.type==='graphics'?{type:'graphics',scene:{...validateScene(item.scene),running:false,handlers:[]}}:{type:item.type,text:item.text})}))},null,2)+'\n';
  parseBook(text); // Validate our own export against the exact import contract.
  return text;
}
const encoder=new TextEncoder(),decoder=new TextDecoder();
export const byteLength=text=>encoder.encode(text).length;
export function clipBytes(text,limit){const bytes=encoder.encode(text);if(bytes.length<=limit)return text;let end=Math.max(0,limit);while(end>0&&(bytes[end]&0xc0)===0x80)end--;return decoder.decode(bytes.subarray(0,end));}
const sizes=new WeakMap();
export function outputBytes(output){const text=output.type==='graphics'?JSON.stringify(output.scene):output.text;const cached=sizes.get(output);if(cached?.text===text)return cached.size;const size=byteLength(text);sizes.set(output,{text,size});return size;}
export const cellOutputBytes=cell=>cell.outputs.reduce((sum,item)=>sum+outputBytes(item),0);
export const bookOutputBytes=book=>book.cells.reduce((sum,cell)=>sum+cellOutputBytes(cell),0);
export function appendOutput(cell,type,text,book={cells:[cell]}) {
  if(!text||cell.outputTruncated&&type!=='error')return;
  text=String(text);
  const total=cellOutputBytes(cell),bookTotal=bookOutputBytes(book);
  // Leave room for a later runtime diagnostic even after an infinite print loop.
  const reserve=type==='error'?256:20000,bookReserve=reserve+(book.cells.length-1)*256;
  const remaining=Math.max(0,Math.min(MAX_OUTPUT-reserve-total,MAX_BOOK_OUTPUT-bookReserve-bookTotal));
  const last=cell.outputs.at(-1),tooMany=cell.outputs.length>=2046&&last?.type!==type;
  const clipped=tooMany?'':clipBytes(text,remaining);
  if(clipped){if(last?.type===type)last.text+=clipped;else cell.outputs.push({type,text:clipped});}
  if(clipped.length<text.length&&!cell.outputTruncated){
    const reason=tooMany?'条目数量':MAX_BOOK_OUTPUT-bookReserve-bookTotal<MAX_OUTPUT-reserve-total?'全书 8 MiB':'本格 2 MiB';
    cell.outputs.push({type:'stderr',text:`\n[输出已截断：达到${reason}保留上限，后续文本已丢弃；已保留 ${cellOutputBytes(cell).toLocaleString('en-US')} UTF-8 字节。]\n`});
    cell.outputTruncated=true;
  }
}
/** Preflight without mutating either the last snapshot or diagnostics. */
export function prepareGraphics(cell,scene,book){
  const prior=cell.outputs.find(item=>item.type==='graphics'),previous=prior?outputBytes(prior):0;
  const size=byteLength(JSON.stringify(scene));
  if(cellOutputBytes(cell)-previous+size>MAX_OUTPUT-256||bookOutputBytes(book)-previous+size>MAX_BOOK_OUTPUT-book.cells.length*256)throw new Error('画布快照未保留：输出容量已满，请清除部分输出。');
  return ()=>{if(prior)prior.scene=scene;else cell.outputs.push({type:'graphics',scene});};
}
export function retainGraphics(cell,scene,book){
  const prior=cell.outputs.find(item=>item.type==='graphics'),previous=prior?outputBytes(prior):0;
  const size=byteLength(JSON.stringify(scene));
  if(cellOutputBytes(cell)-previous+size>MAX_OUTPUT-256||bookOutputBytes(book)-previous+size>MAX_BOOK_OUTPUT-book.cells.length*256){appendOutput(cell,'error','[画布快照未保留：输出容量已满，请清除部分输出。]\n',book);return false;}
  if(prior)prior.scene=scene;else cell.outputs.push({type:'graphics',scene});return true;
}
export function historicalBook(book) {
  for(const cell of book.cells) { if(cell.outputs.length||cell.execution_count) cell.historical=true; cell.status='idle'; }
}
