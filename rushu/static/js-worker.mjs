/** Served with a dedicated CSP: default-src 'none'; script-src blob:; connect-src 'none'; worker-src 'none'.
 * Only server-compiled modules belong here. This is not an arbitrary-JavaScript security sandbox.
 * No imports: CSP permits only the one generated Blob module, not network script modules.
 */
const MAX_SOURCE=4*1024*1024,MAX_BATCH=1024*1024,MAX_OUTPUT=1024*1024,MAX_EVENTS=128;
const bytes=value=>new TextEncoder().encode(typeof value==='string'?value:JSON.stringify(value)).length;
let identity=null,controller=null,busy=false,totalOutput=0;
const same=id=>id&&['cell_id','execution_count','generation','token','source_version'].every(key=>id[key]===identity?.[key]);
let events=[],size=0;
function emit(event){
  if(!event||typeof event!=='object')throw new Error('JavaScript 输出无效。');
  if(events.length>=MAX_EVENTS)throw new Error('JavaScript 输出事件过多。');
  const length=bytes(event);size+=length;if(size>MAX_BATCH-81920)throw new Error('JavaScript 输出批次过大。');
  if(event.type==='output'){totalOutput+=bytes(String(event.text));if(totalOutput>MAX_OUTPUT)throw new Error('JavaScript 文本输出超过上限。');}
  events.push(event);
}
function failure(error,serial){
  const message=String(error?.message||error||'JavaScript 执行失败。').slice(0,8192);
  let diagnostic=error?.diagnostic||null;
  try{if(diagnostic&&bytes(diagnostic)>65536)diagnostic=null;}catch{diagnostic=null;}
  self.postMessage({type:'failure',identity,serial,message,diagnostic,events});
}
self.onmessage=async ({data})=>{
  if(!data||busy)return;
  if(data.type==='init'){
    if(identity)return;
    identity=data.identity;busy=true;events=[];size=0;let url;
    try{
      if(typeof data.javascript!=='string'||bytes(data.javascript)>MAX_SOURCE)throw new Error('JavaScript 编译产物过大。');
      url=URL.createObjectURL(new Blob([data.javascript],{type:'text/javascript'}));
      const module=await import(url);URL.revokeObjectURL(url);url=null;
      controller=module.default(Object.freeze({emit}));
      if(!controller||typeof controller.dispatch!=='function')throw new Error('JavaScript 编译产物接口无效。');
      self.postMessage({type:'batch',identity,serial:0,events});
    }catch(error){failure(error,0);controller=null;}finally{if(url)URL.revokeObjectURL(url);events=[];busy=false;}
  }else if(data.type==='dispatch'&&same(data.identity)&&controller){
    busy=true;events=[];size=0;
    try{const {canvas_id,...event}=data.event;controller.dispatch({canvas_id,event});self.postMessage({type:'batch',identity,serial:data.serial,events});}
    catch(error){failure(error,data.serial);controller=null;}finally{events=[];busy=false;}
  }
};
