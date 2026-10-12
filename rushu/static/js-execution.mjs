/** One independent browser execution. Workers are isolation/liveness tools, not a memory sandbox. */
import {validateScene} from './scene.mjs';
export const JS_LIMITS=Object.freeze({sourceBytes:4*1024*1024,batchBytes:1024*1024,outputBytes:1024*1024,events:128,queue:32,initMs:5000,callbackMs:1000});
const bytes=value=>new TextEncoder().encode(typeof value==='string'?value:JSON.stringify(value)).length;
const keys=['cell_id','execution_count','generation','token','source_version'];
export function createJSExecution({javascript,identity,onEvent=()=>{},onFatal=()=>{},workerFactory=url=>new Worker(url,{type:'module'}),limits={}}) {
  const budget={...JS_LIMITS,...limits};
  if(typeof javascript!=='string'||bytes(javascript)>budget.sourceBytes)throw new Error('JavaScript 编译产物过大。');
  if(!identity||typeof identity.cell_id!=='string'||!identity.cell_id||!Number.isSafeInteger(identity.execution_count)||!Number.isSafeInteger(identity.generation)||typeof identity.token!=='string'||!identity.token)throw new Error('JavaScript 执行标识无效。');
  const id=Object.freeze({...identity}),worker=workerFactory(new URL('./js-worker.mjs',import.meta.url));
  let live=true,initialized=false,timer=null,serial=0,inFlight=null,queue=[],totalOutput=0;
  let resolveReady,rejectReady;const ready=new Promise((resolve,reject)=>{resolveReady=resolve;rejectReady=reject;});
  // A synchronous stop before the UI awaits ready must not create an unhandled rejection.
  ready.catch(()=>{});
  function release(error){if(!live)return;live=false;clearTimeout(timer);timer=null;worker.onmessage=null;worker.onerror=null;worker.onmessageerror=null;worker.terminate();rejectReady(error);inFlight?.reject(error);inFlight=null;for(const item of queue)item.reject(error);queue=[];}
  function fatal(error,diagnostic=null){if(!live)return;const message=String(error?.message||error||'JavaScript 执行失败。');release(new Error(message));onFatal({type:'error',...id,message,diagnostic});}
  function arm(ms){clearTimeout(timer);timer=setTimeout(()=>fatal(new Error('JavaScript 执行超时，已终止独立 Worker。')),ms);}
  function post(message){try{worker.postMessage({...message,identity:id});}catch(error){fatal(error);}}
  function pump(){if(!live||!initialized||inFlight||!queue.length)return;inFlight=queue.shift();arm(budget.callbackMs);post({type:'dispatch',serial:inFlight.serial,event:inFlight.event});}
  function receive(message){
    if(!live||!message||!keys.every(key=>message.identity?.[key]===id[key]))return;
    const expected=initialized?inFlight?.serial:0;if(message.serial!==expected)return;
    if(message.type!=='batch'&&message.type!=='failure')return;
    try{
      if(bytes(message)>budget.batchBytes)throw new Error('JavaScript 输出批次过大。');
      if(message.type==='failure'&&message.events==null)message={...message,events:[]};
      if(!Array.isArray(message.events)||message.events.length>budget.events)throw new Error('JavaScript 输出事件过多。');
      // Validate the entire batch before exposing any event to the UI.
      const events=message.events.map(event=>{
        if(!event||typeof event!=='object')throw new Error('JavaScript 输出无效。');
        if(event.type==='graphics')return {...validateScene(event),type:'graphics',...id};
        if(event.type==='output'){
          if(typeof event.text!=='string'||!['stdout','stderr'].includes(event.stream))throw new Error('JavaScript 文本输出无效。');
          totalOutput+=bytes(event.text);if(totalOutput>budget.outputBytes)throw new Error('JavaScript 文本输出超过上限。');
          return {type:'output',text:event.text,stream:event.stream,...id};
        }
        if(['graphics_closed','graphics_done'].includes(event.type)&&typeof event.canvas_id==='string')return {...event,...id};
        if(event.type==='error'&&typeof event.message==='string')return {...event,...id};
        throw new Error('JavaScript 输出类型无效。');
      });
      clearTimeout(timer);timer=null;
      for(const event of events){if(!live)return;onEvent(event);}
      if(!live)return;
      if(message.type==='failure'){fatal(new Error(message.message||'JavaScript 执行失败。'),message.diagnostic);return;}
      if(!initialized){initialized=true;resolveReady();}else{const completed=inFlight;inFlight=null;completed?.resolve();}
      pump();
    }catch(error){fatal(error);}
  }
  worker.onmessage=event=>receive(event.data);
  worker.onerror=event=>{event.preventDefault?.();fatal(new Error(event.message||'JavaScript Worker 启动失败。'));};
  worker.onmessageerror=()=>fatal(new Error('JavaScript Worker 消息无法读取。'));
  arm(budget.initMs);post({type:'init',serial:0,javascript});
  return {ready,get active(){return live;},send(event){
    if(!live)return Promise.reject(new Error('JavaScript 执行已停止。'));
    if(!event||typeof event.canvas_id!=='string'||!['frame','mouse_move','mouse_down','mouse_up','key_down','key_up','close'].includes(event.type))return Promise.reject(new Error('JavaScript 图形事件无效。'));
    if(bytes(event)>4096)return Promise.reject(new Error('JavaScript 图形输入过大。'));
    if(event.type==='close'){release(new Error('JavaScript 画布已停止。'));onEvent({type:'graphics_closed',canvas_id:event.canvas_id,...id});return Promise.resolve();}
    // Frames and mouse moves are replaceable. Resolve superseded requests, never grow an unbounded waiter list.
    if(['frame','mouse_move'].includes(event.type)){const old=queue.findIndex(item=>item.event.type===event.type&&item.event.canvas_id===event.canvas_id);if(old>=0){queue.splice(old,1)[0].resolve();}}
    if(queue.length>=budget.queue)return Promise.reject(new Error('JavaScript 图形输入队列已满。'));
    return new Promise((resolve,reject)=>{queue.push({event:{...event},serial:++serial,resolve,reject});pump();});
  },stop(){release(new Error('JavaScript 执行已停止。'));},dispose(){release(new Error('JavaScript 执行已释放。'));}};
}
