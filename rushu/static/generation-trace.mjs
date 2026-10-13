import {copyInput} from './clipboard.mjs';

// Deliberately independent of notebook data, history, and browser storage.
export const TRACE_LIMITS=Object.freeze({events:64,text:1048576,total:2097152});
const labels={preparation:'准备请求',request_sent:'发起 API 请求',waiting:'等待提供方（非流式）',http_response:'HTTP 响应',response_parse:'解析响应',response_validation:'响应格式检查',model_text:'模型实际返回文本',refusal:'模型拒绝',incomplete:'响应不完整',source_extraction:'提取如源码',extracted_source:'提取的如源码',target_validation:'目标检查（未执行）',provider_error:'提供方错误',response_status:'响应状态',final_success:'生成完成',final_failure:'生成失败'};
export function redactTraceText(value,limit=TRACE_LIMITS.text){
  return String(value??'').slice(0,limit)
    .replace(/https?:\/\/[^\s<>"']+/gi,url=>{try{const u=new URL(url);return u.protocol+'//'+u.hostname+(u.port?':'+u.port:'')+'/[地址已脱敏]';}catch{return '[地址已脱敏]';}})
    .replace(/\b(?:Bearer|Basic)\s+[A-Za-z0-9+/_=.~-]+/gi,'[认证信息已脱敏]')
    .replace(/\b(?:sk-|rk-|sess-)[A-Za-z0-9_-]{8,}/g,'[密钥已脱敏]')
    .replace(/((?:api[_-]?key|authorization|access[_-]?token|password|secret)\s*["']?\s*[:=]\s*)[^\s,;}]+/gi,'$1[已脱敏]')
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
}
export function generationTraceId(){return [...crypto.getRandomValues(new Uint8Array(16))].map(n=>n.toString(16).padStart(2,'0')).join('');}
export function createTraceState(id){return {generation_id:id,events:[],truncated:false,complete:false,cleared:false,bytes:0,phase:'尚未开始生成。'};}
export function mergeTrace(state,trace){
  if(state.cleared||!trace||trace.schema_version!==1||trace.generation_id!==state.generation_id||!Array.isArray(trace.events))return false;
  let changed=false,last=state.events.at(-1)?.seq??-1;
  for(const raw of trace.events.slice(0,TRACE_LIMITS.events)){
    if(!raw||!Number.isSafeInteger(raw.seq)||raw.seq<=last)continue;
    if(state.events.length>=TRACE_LIMITS.events){state.truncated=true;break;}
    const metadataTruncated=String(raw.detail??'').length>2048||String(raw.time??'').length>40;
    const event={seq:raw.seq,stage:Object.hasOwn(labels,raw.stage)?raw.stage:'unknown',time:redactTraceText(raw.time,40),elapsed_ms:Number.isFinite(raw.elapsed_ms)?Math.max(0,raw.elapsed_ms):0,detail:redactTraceText(raw.detail,2048)};
    if(typeof raw.text==='string'){
      const available=Math.max(0,Math.min(TRACE_LIMITS.text,TRACE_LIMITS.total-state.bytes));
      const redacted=redactTraceText(raw.text,available),encoded=new TextEncoder().encode(redacted);
      event.text=encoded.length>available?new TextDecoder().decode(encoded.slice(0,Math.max(0,available-3))):redacted;state.bytes+=new TextEncoder().encode(event.text).length;
      event.truncated=metadataTruncated||!!raw.truncated||raw.text.length>available||encoded.length>available;
    }else event.truncated=metadataTruncated||!!raw.truncated;
    state.truncated ||= event.truncated;state.events.push(event);last=raw.seq;changed=true;
  }
  state.truncated ||= !!trace.truncated||trace.events.length>TRACE_LIMITS.events;
  state.complete ||= !!trace.complete;return changed;
}
let pendingDownload=null;
export function releaseTraceDownload(state){
  if(pendingDownload&&(!state||pendingDownload.state===state)){
    URL.revokeObjectURL(pendingDownload.url);clearTimeout(pendingDownload.timer);pendingDownload=null;
  }
}
export function retainTrace(states,state,limit=8){
  states.push(state);const evicted=[];
  while(states.length>limit){const old=states.shift();releaseTraceDownload(old);old.events=[];old.bytes=0;old.cleared=true;old.evicted=true;old.phase='此格诊断已释放：页面最多保留最近 8 次生成记录（正文最多 16 MiB）。';evicted.push(old);}
  return evicted;
}
export function traceExport(state){
  return JSON.stringify({schema_version:1,generation_id:state.generation_id,phase:redactTraceText(state.phase,2048),limits:TRACE_LIMITS,events:state.events,truncated:state.truncated,complete:state.complete,notice:'仅含本次已观察到的记录；可能含意图、源码或其他私人文本。凭据脱敏不保证移除所有个人信息。'},null,2);
}
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
export function createTracePanel(state,{onClear=()=>{},notify=()=>{}}={}){
  const root=node('details',undefined,'generation-diagnostics generation-disclosure'),summary=node('summary','生成诊断 · API 过程与模型原文');
  const phase=node('p',state.phase),identity=node('p','', 'generation-trace-identity'),limits=node('p'),events=node('ol',undefined,'generation-trace-events'),controls=node('div',undefined,'generation-trace-actions');
  const pollStatus=node('p');
  const warning=node('p','非流式请求只显示已观察到的阶段，不显示 token 进度。记录仅在内存中，不随如书或版本保存；重新生成会替换本格记录，页面最多保留最近 8 次记录（正文最多 16 MiB）。模型文本可能含私人信息，复制或下载前请检查。');
  function action(label,handler){const b=node('button',label);b.type='button';b.addEventListener('click',handler);controls.append(b);return b;}
  let copying=false;
  const copy=action('复制诊断 JSON',async()=>{if(copying||state.cleared)return;copying=true;copy.disabled=true;try{await copyInput(traceExport(state));notify('已复制已脱敏的诊断 JSON。分享前请检查私人文本。');}catch(error){notify(error.message,true);}finally{copying=false;copy.disabled=state.cleared||!state.generation_id;}});
  const download=action('下载诊断 JSON',()=>{try{releaseTraceDownload();const blob=new Blob([traceExport(state)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=node('a');pendingDownload={state,url,timer:setTimeout(()=>releaseTraceDownload(state),10000)};a.href=url;a.download='rushu-generation-'+state.generation_id+'.json';document.body.append(a);a.click();a.remove();notify('已请求下载诊断 JSON。分享前请检查私人文本。');}catch{notify('诊断下载未成功，请使用复制或手动选择文字。',true);}});
  const clear=action('清除此格诊断',()=>onClear());
  root.append(summary,phase,identity,warning,controls,limits,pollStatus,events);
  let rendered=0;
  function update(){
    if(phase.textContent!==state.phase)phase.textContent=state.phase;
    pollStatus.textContent=state.cleared?'':state.pollWarning||'';pollStatus.hidden=!pollStatus.textContent;
    identity.textContent=state.generation_id?'本次生成 ID：'+state.generation_id:'尚无生成记录';
    copy.disabled=copying||state.cleared||!state.generation_id;download.disabled=clear.disabled=state.cleared||!state.generation_id;
    limits.textContent=state.cleared?(state.evicted?'较早诊断已释放；请及时下载需要保留的记录。':'诊断已清除；不会再接收本次记录。'):state.truncated?'记录已截断：最多 64 阶段、阶段说明 2048 字符、每段正文 1 MiB、正文合计 2 MiB。':'记录上限：64 阶段；每段正文 1 MiB，正文合计 2 MiB；长文本分页显示。';
    if(state.events.length<rendered){events.replaceChildren();rendered=0;}
    for(const event of state.events.slice(rendered)){
      const li=node('li'),title=`${event.time} · ${(event.elapsed_ms/1000).toFixed(1)} 秒 · ${labels[event.stage]||'其他阶段'}${event.truncated?'（本阶段已截断）':''}`;
      li.append(node('p',title,'generation-trace-stage'),node('p',event.detail));
      if(event.text!==undefined){const body=node('details'),heading=event.stage==='model_text'?'查看模型实际返回文本（已脱敏）':event.stage==='extracted_source'?'查看提取的如源码（已脱敏）':'查看阶段文本';body.append(node('summary',heading+(event.truncated?'（已截断）':'')));
        let page=0;const size=16384,count=Math.max(1,Math.ceil(event.text.length/size)),pre=node('pre','','generation-trace-text'),position=node('span'),pages=node('div',undefined,'generation-trace-actions');
        const previous=node('button','上一页'),next=node('button','下一页');previous.type=next.type='button';
        const show=()=>{pre.textContent=event.text.slice(page*size,(page+1)*size);position.textContent=`第 ${page+1} / ${count} 页（复制／下载包含全部已保留文本）`;previous.disabled=page===0;next.disabled=page===count-1;};
        previous.addEventListener('click',()=>{page--;show();});next.addEventListener('click',()=>{page++;show();});pages.append(previous,position,next);pages.hidden=count===1;body.append(pages,pre);show();li.append(body);}
      events.append(li);rendered++;
    }
  }
  update();return {root,phase,update};
}

/** One bounded, serial poll stream. A late read can never alter a replaced trace. */
export function startTracePolling({state,read,isCurrent,onUpdate,onError=()=>{},interval=globalThis.setInterval,clear=globalThis.clearInterval}){
  let stopped=false,pending=false;
  const tick=async()=>{if(stopped||pending||state.cleared||!isCurrent())return;pending=true;try{const trace=await read();if(!stopped&&!state.cleared&&isCurrent()){mergeTrace(state,trace);state.pollWarning='';onUpdate();}}catch(error){if(!stopped&&isCurrent())onError(error);}finally{pending=false;}};
  const timer=interval(tick,1000);return ()=>{stopped=true;clear(timer);};
}
