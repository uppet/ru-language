import test from 'node:test';
import assert from 'node:assert/strict';
import {TRACE_LIMITS,createTraceState,mergeTrace,retainTrace,releaseTraceDownload,traceExport,redactTraceText,createTracePanel,startTracePolling} from '../static/generation-trace.mjs';
const trace=(id,events,extra={})=>({schema_version:1,generation_id:id,events,...extra});
const event=(seq,stage='waiting',extra={})=>({seq,stage,time:'2026-10-13T08:00:00Z',elapsed_ms:1250,detail:'Observed',...extra});

test('incremental stages retain failure output, reject other identities, and never duplicate',()=>{
  const state=createTraceState('a');
  assert.equal(mergeTrace(state,trace('b',[event(1)])),false);
  mergeTrace(state,trace('a',[event(1),event(2,'model_text',{text:'```ru\ninvalid\n```'})]));
  mergeTrace(state,trace('a',[event(1),event(2),event(3,'extracted_source',{text:'invalid'}),event(4,'final_failure',{detail:'parse failed'})],{complete:true}));
  assert.equal(state.events.length,4);assert.equal(state.events[1].text,'```ru\ninvalid\n```');
  assert.equal(state.events[2].text,'invalid');assert.equal(state.complete,true);
  assert.equal(JSON.parse(traceExport(state)).events.length,4);
  state.cleared=true;assert.equal(mergeTrace(state,trace('a',[event(5)])),false);
});

test('credential defense removes auth, credential URLs, key assignments, controls and opaque fields',()=>{
  const state=createTraceState('a');
  mergeTrace(state,trace('a',[event(1,'model_text',{text:'Bearer abcdefg https://user:pass@example.com/path?api_key=secret sk-secretabcdefgh api_key=another plain\u202e',encrypted_reasoning:'hidden',authorization:'secret'})]));
  const text=traceExport(state);
  for(const secret of ['abcdefg','user:pass','?api_key','sk-secretabcdefgh','another','encrypted_reasoning','hidden'])assert.equal(text.includes(secret),false,secret);
  assert.ok(text.includes('已脱敏'));assert.ok(text.includes('202e'));
  assert.equal(redactTraceText('<img onerror=evil()>'),'<img onerror=evil()>'); // Literal display, never HTML.
});

test('large text is retained up to byte caps and marked when truncated',()=>{
  const state=createTraceState('a'),large='中'.repeat(400000);
  mergeTrace(state,trace('a',[event(1,'model_text',{text:large}),event(2,'extracted_source',{text:large}),event(3,'model_text',{text:large})]));
  assert.ok(state.bytes<=TRACE_LIMITS.total);assert.equal(state.truncated,true);
  for(const entry of state.events)assert.ok(new TextEncoder().encode(entry.text).length<=TRACE_LIMITS.text);
  mergeTrace(state,trace('a',Array.from({length:80},(_,i)=>event(i+4))));
  assert.equal(state.events.length,64);assert.equal(state.truncated,true);
});

test('page-wide retention frees oldest text and explicitly marks eviction',()=>{
  const states=[];let first;
  for(let i=0;i<9;i++){const state=createTraceState(String(i));mergeTrace(state,trace(String(i),[event(1,'model_text',{text:'private'})]));if(!i)first=state;retainTrace(states,state);}
  assert.equal(states.length,8);assert.equal(first.events.length,0);assert.equal(first.bytes,0);assert.equal(first.cleared,true);assert.match(first.phase,/释放/);
});

test('polling is serial and cancellation/new generation blocks late results',async()=>{
  let tick,resolve,reads=0,updates=0,current=true,cleared=false;
  const state=createTraceState('a');
  const stop=startTracePolling({state,read:()=>{reads++;return new Promise(r=>resolve=r);},isCurrent:()=>current,onUpdate:()=>updates++,interval:cb=>{tick=cb;return 42;},clear:id=>{assert.equal(id,42);cleared=true;}});
  const first=tick();await tick();assert.equal(reads,1);current=false;
  resolve(trace('a',[event(1)]));await first;assert.equal(state.events.length,0);assert.equal(updates,0);
  current=true;const second=tick();stop();resolve(trace('a',[event(1)]));await second;
  assert.equal(cleared,true);assert.equal(state.events.length,0);
});

class Element {
  constructor(tag){this.tag=tag;this.children=[];this.listeners={};this.textContent='';this.hidden=false;}
  append(...children){this.children.push(...children);}
  addEventListener(type,handler){this.listeners[type]=handler;}
  replaceChildren(...children){this.children=children;}
}
function walk(n){return [n,...n.children.flatMap(walk)];}
test('panel appends stages without repaint, displays raw HTML as text, and pages long output',()=>{
  const old=globalThis.document;globalThis.document={createElement:tag=>new Element(tag)};
  try{
    const state=createTraceState('a'),panel=createTracePanel(state);
    mergeTrace(state,trace('a',[event(1,'model_text',{text:'<script>evil()</script>'+'x'.repeat(40000)})]));panel.update();
    const list=walk(panel.root).find(n=>n.tag==='ol'),first=list.children[0],pre=walk(first).find(n=>n.tag==='pre');
    assert.equal(pre.textContent.length,16384);assert.ok(pre.textContent.startsWith('<script>'));
    const next=walk(first).find(n=>n.tag==='button'&&n.textContent==='下一页');next.listeners.click();assert.equal(pre.textContent.length,16384);
    mergeTrace(state,trace('a',[event(2,'target_validation',{detail:'browser-js 编译通过，未执行'})]));panel.update();
    assert.equal(list.children[0],first);assert.equal(list.children.length,2);
    assert.equal(walk(panel.root).some(n=>n.tag==='script'),false);
    state.events=[];state.cleared=true;panel.update();assert.equal(list.children.length,0);
  }finally{globalThis.document=old;}
});

test('copy occurs only on click and reports clipboard rejection honestly',async()=>{
  const old=globalThis.document,descriptor=Object.getOwnPropertyDescriptor(globalThis,'navigator');let copies=0;
  globalThis.document={createElement:tag=>new Element(tag)};
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{clipboard:{writeText:async()=>{copies++;throw new Error('denied');}}}});
  try{
    const messages=[],panel=createTracePanel(createTraceState('a'),{notify:(...args)=>messages.push(args)});
    assert.equal(copies,0);const copy=walk(panel.root).find(n=>n.tag==='button'&&n.textContent==='复制诊断 JSON');await copy.listeners.click();
    assert.equal(copies,1);assert.match(messages[0][0],/复制未成功/);assert.equal(messages[0][1],true);
  }finally{globalThis.document=old;if(descriptor)Object.defineProperty(globalThis,'navigator',descriptor);else delete globalThis.navigator;}
});


test('download is explicit and retains at most one revocable artifact across panels',()=>{
  const oldDocument=globalThis.document,oldCreate=URL.createObjectURL,oldRevoke=URL.revokeObjectURL;
  const created=[],revoked=[],clicked=[];
  globalThis.document={body:new Element('body'),createElement:tag=>{const n=new Element(tag);n.click=()=>clicked.push(n.download);n.remove=()=>{};return n;}};
  URL.createObjectURL=blob=>{assert.ok(blob.size>0);const url='blob:'+created.length;created.push(url);return url;};
  URL.revokeObjectURL=url=>revoked.push(url);
  try{
    const one=createTraceState('a'),two=createTraceState('b');
    const first=createTracePanel(one),second=createTracePanel(two);
    const download=panel=>walk(panel.root).find(n=>n.tag==='button'&&n.textContent==='下载诊断 JSON').listeners.click();
    assert.equal(created.length,0);download(first);download(second);
    assert.equal(created.length,2);assert.deepEqual(revoked,['blob:0']);assert.equal(clicked.length,2);
    releaseTraceDownload(two);assert.deepEqual(revoked,['blob:0','blob:1']);
  }finally{releaseTraceDownload();globalThis.document=oldDocument;URL.createObjectURL=oldCreate;URL.revokeObjectURL=oldRevoke;}
});

test('budget, usage and output summaries retain named stages without opaque fields',()=>{
  const state=createTraceState('budget');
  const stages=['request_budget','response_usage','output_summary'];
  mergeTrace(state,trace('budget',stages.map((stage,index)=>event(index+1,stage,{detail:index===0?'未发送 max_output_tokens；提供方默认值未知。':index===1?'reasoning_tokens=16384':'reasoning=1；未返回可识别助手文本。',reasoning:{text:'PRIVATE_REASONING'}}))));
  assert.deepEqual(state.events.map(entry=>entry.stage),stages);
  const exported=traceExport(state);
  assert.ok(exported.includes('reasoning_tokens=16384'));
  assert.equal(exported.includes('PRIVATE_REASONING'),false);
  assert.equal(state.events.some(entry=>entry.stage==='model_text'),false);
});
