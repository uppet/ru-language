import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {generationTraceId,createTraceState,retainTrace,releaseTraceDownload,mergeTrace,redactTraceText} from '../static/generation-trace.mjs';

// Exercise the actual request lifecycle with fake DOM, time, and HTTP results.
// No browser, credentials, provider calls, or artificial 30-minute waits.
const source=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const statusUI=source.slice(source.indexOf('function createGenerationStatus('),source.indexOf('async function loadProvider('));
class Node {
  constructor(text=''){this.textContent=text;this.children=[];this.attributes={};this.hidden=false;this.classList={toggle(){}};}
  setAttribute(name,value){this.attributes[name]=value;}
  append(...nodes){this.children.push(...nodes);}
}
const lifecycle=source.slice(source.indexOf('function diagnosticLocation('),source.indexOf('function buildHistory('));
function harness({configured=true,confirm=true}={}){
  const cell={id:'cell',source:'private draft',generation:{prompt:'private intent\n如是我言',revisions:[]},outputs:[]};
  const diagnostic={textContent:''},intervals=new Map(),calls=[],statuses=[],pendingResponses=[];
  let clock=1000,resolveResponse,nextTimer=1;
  const context={
    generationTraces:new WeakMap(),retainedGenerationTraces:[],generationTraceId,createTraceState,retainTrace,releaseTraceDownload,mergeTrace,redactTraceText,startTracePolling:()=>()=>{},
    generationRequest:null,book:{cells:[cell]},epoch:0,providerInfo:null,token:'private-token',MAX_SOURCE:200000,
    views:new Map([[cell.id,{prompt:{value:''},input:{value:cell.source},generationDiagnostic:diagnostic,renderEditor(){}}]]),
    AbortController,structuredClone,performance:{now:()=>clock},
    busy:()=>false,withGenerationMarker:text=>text,generationIntent:text=>text,
    checkpoint(){},serializeBook(){},renderHistory(){},markDirty(){},refreshControls(){},renderOutput(){},notice(){},
    el:(tag,cls,text)=>new Node(text),document:{createElementNS:()=>new Node()},
    replaceWithRevision:(candidate,revision)=>{candidate.source=revision.source;candidate.generation.revisions.push(revision);},
    api:async()=>({configured,provider_host:'provider.example',message:'Missing configuration'}),
    confirm:()=>confirm,
    fetch:(path,options)=>{calls.push({path,options});return new Promise(resolve=>{resolveResponse=resolve;pendingResponses.push(resolve);});},
    setTimeout(){throw new Error('Generation must not have a shorter frontend deadline');},
    setInterval:(callback,delay)=>{assert.equal(delay,1000);const id=nextTimer++;intervals.set(id,callback);return id;},
    clearInterval:id=>intervals.delete(id),
  };
  context.invalidateEditedBrowserCell=()=>{};vm.createContext(context);vm.runInContext(statusUI+lifecycle,context);
  const view=context.views.get(cell.id);view.generationStatus=context.createGenerationStatus(view);
  const setStatus=context.generationStatus;context.generationStatus=(...args)=>{statuses.push(args);setStatus(...args);};
  return {cell,diagnostic,intervals,calls,statuses,context,
    async start(){const promise=context.generateCell(cell);await new Promise(resolve=>setImmediate(resolve));return {promise};},
    advance(milliseconds){clock+=milliseconds;for(const callback of intervals.values())callback();},
    respond(result={source:'显 42.\n',valid:true},ok=true){resolveResponse({ok,json:async()=>result});},
    respondAt(index,result,ok=true){pendingResponses[index]({ok,json:async()=>result});},
  };
}

test('generation waits beyond the old cutoff and reports only observed elapsed time',async()=>{
  const h=harness(),{promise}=await h.start();
  assert.equal(h.calls.length,1);assert.equal(h.calls[0].path,'/api/generate');
  await h.context.generateCell(h.cell);assert.equal(h.calls.length,1);
  assert.match(h.diagnostic.textContent,/等待本机服务返回/);
  h.advance(1801000);
  assert.match(h.diagnostic.textContent,/1801 秒/);
  assert.equal(h.calls[0].options.signal.aborted,false);
  for(const secret of ['private intent','private draft','private-token'])assert.ok(!h.diagnostic.textContent.includes(secret));
  h.respond();await promise;
  assert.equal(h.cell.source,'显 42.\n');assert.equal(h.cell.generation.revisions.length,1);
  assert.match(h.diagnostic.textContent,/检查通过，未执行/);
  assert.equal(h.intervals.size,0);assert.equal(h.context.generationRequest,null);
});

test('manual cancellation stops elapsed updates and ignores late results',async()=>{
  const h=harness(),{promise}=await h.start();h.advance(90000);
  h.context.cancelGeneration();const cancelled=h.diagnostic.textContent;
  assert.match(cancelled,/已取消页面等待/);assert.match(cancelled,/90 秒/);
  assert.equal(h.calls[0].options.signal.aborted,true);assert.equal(h.intervals.size,0);
  h.respond();await promise;h.advance(5000);
  assert.equal(h.cell.source,'private draft');assert.equal(h.cell.generation.revisions.length,0);
  assert.equal(h.diagnostic.textContent,cancelled);
});

test('new edits survive stale generation results and elapsed timer is cleaned up',async()=>{
  const h=harness(),{promise}=await h.start();h.cell.source='new manual draft';
  h.respond();await promise;
  assert.equal(h.cell.source,'new manual draft');assert.equal(h.cell.generation.revisions.length,0);
  assert.match(h.diagnostic.textContent,/因编辑改变，结果已丢弃/);
  assert.equal(h.intervals.size,0);
});

test('configuration failure and declined confirmation do not send or time a request',async()=>{
  for(const options of [{configured:false},{confirm:false}]){
    const h=harness(options),{promise}=await h.start();await promise;
    assert.equal(h.calls.length,0);assert.equal(h.intervals.size,0);
    assert.equal(h.cell.source,'private draft');assert.equal(h.context.generationRequest,null);
    assert.ok(!h.diagnostic.textContent.includes('请求已用时'));
  }
});

test('safe server errors and failed validation preserve their actual outcomes',async()=>{
  const failed=harness(),{promise:failure}=await failed.start();
  failed.respond({error:'TLS 证书验证失败；未自动重试。'},false);await failure;
  assert.match(failed.diagnostic.textContent,/TLS 证书验证失败/);
  assert.equal(failed.cell.source,'private draft');assert.equal(failed.intervals.size,0);
  const invalid=harness(),{promise:validation}=await invalid.start();
  invalid.respond({source:'invalid source',valid:false,validation:{message:'语法错误',line:3,col:7}});await validation;
  assert.equal(invalid.cell.source,'invalid source');
  assert.ok(invalid.statuses.some(([,message])=>message.includes('第 3 行，第 7 列')));
  assert.equal(invalid.calls.length,1); // Validation does not execute or retry generation.
  assert.match(invalid.diagnostic.textContent,/检查未通过，未执行/);
  assert.equal(invalid.intervals.size,0);
});

test('repeated graphics generation keeps review history and never runs the cell',async()=>{
  const h=harness();
  const source="观 取 外言 '如:观'. 图 取 观 其 画布 80 60. 图 其 每帧 (作 帧: 图 其 矩形 帧 0 10 10. 为).\n";
  for (const [candidate,valid] of [[source,true],[source.replace('为).','法).'),false],[source,true]]) {
    const {promise}=await h.start();h.respond({source:candidate,valid,validation:{message:'尚未执行。'}});await promise;
    assert.equal(h.cell.source,candidate);
  }
  assert.equal(h.calls.length,3);
  assert.ok(h.calls.every(call=>call.path==='/api/generate'));
  assert.equal(h.cell.generation.revisions.length,3);
  assert.equal(h.cell.generation.revisions[0].source,source);
  assert.equal(h.cell.generation.revisions[1].source,source.replace('为).','法).'));
  assert.equal(h.cell.outputs.length,0);
  assert.equal(h.context.generationRequest,null);
});


test('actual status DOM stays fixed during elapsed ticks and each terminal outcome stops animation',async()=>{
  for(const outcome of ['success','error','cancel','edited','switch']){
    const h=harness(),view=h.context.views.get(h.cell.id),status=view.generationStatus,text=view.generationStatusText,indicator=view.generationActivity,svg=indicator.children[0];
    assert.equal(indicator.hidden,true);assert.equal(indicator.attributes['aria-hidden'],'true');
    assert.equal(text.attributes.role,'status');assert.equal(status.attributes.role,undefined);
    const {promise}=await h.start();assert.equal(indicator.hidden,false);
    const waiting=text.textContent;
    for(let i=0;i<4;i++)h.advance(1000);
    assert.equal(view.generationStatus,status);assert.equal(view.generationStatusText,text);assert.equal(text.textContent,waiting);assert.equal(indicator.children[0],svg);
    if(outcome==='cancel'||outcome==='switch')h.context.cancelGeneration(false);
    if(outcome==='switch'){h.context.book={cells:[]};h.context.epoch++;}
    if(outcome==='edited')h.cell.source='new manual draft';
    h.respond(outcome==='error'?{error:'mock failure'}:undefined,outcome!=='error');await promise;
    assert.equal(indicator.hidden,true,outcome);assert.equal(h.intervals.size,0,outcome);
    assert.equal(view.generationStatus,status);assert.equal(indicator.children[0],svg);
    if(outcome==='success'){
      const second=await h.start();assert.equal(indicator.hidden,false);h.respond();await second.promise;assert.equal(indicator.hidden,true);
    }
  }
});

test('no-send configuration and confirmation paths also stop the indicator',async()=>{
  for(const options of [{configured:false},{confirm:false}]){
    const h=harness(options),{promise}=await h.start();await promise;
    assert.equal(h.context.views.get(h.cell.id).generationActivity.hidden,true);
  }
});


test('browser target reports compiler capability checks and preserves invalid source for review',async()=>{
  for(const valid of [true,false]){
    const h=harness();h.cell.execution_backend='browser-js';const {promise}=await h.start();
    assert.equal(JSON.parse(h.calls[0].options.body).runtime_target,'browser-js');
    const message=valid?'已通过浏览器 JS 编译与能力检查；仅检查内置标准外言，尚未执行。':'生成源码使用浏览器 JS 不支持的能力；尚未执行。';
    h.respond({source:'generated candidate',valid,validation:{message}});await promise;
    assert.equal(h.cell.source,'generated candidate');assert.equal(h.cell.generation.revisions.length,1);
    assert.ok(h.statuses.some(([,text])=>text.includes(message)));
    assert.ok(!h.statuses.some(([,text])=>text.includes('未检查外言依赖')));
    assert.match(h.diagnostic.textContent,/浏览器 JS 编译／能力检查/);
    assert.equal(h.cell.outputs.length,0);assert.equal(h.calls.length,1);
  }
});

test('target changes discard late generation without modifying source or history',async()=>{
  for(const initial of ['python','browser-js']){
    const h=harness();h.cell.execution_backend=initial;const {promise}=await h.start();
    h.cell.execution_backend=initial==='python'?'browser-js':'python';h.respond();await promise;
    assert.equal(h.cell.source,'private draft');assert.equal(h.cell.generation.revisions.length,0);
    assert.match(h.diagnostic.textContent,/运行目标改变，结果已丢弃/);
    assert.equal(h.intervals.size,0);assert.equal(h.context.generationRequest,null);
  }
});


test('failure preserves actual model output and extracted source only in transient trace',async()=>{
  const h=harness(),{promise}=await h.start(),id=h.context.generationTraces.get(h.cell).generation_id;
  h.respond({error:'源码提取失败',trace:{schema_version:1,generation_id:id,complete:true,events:[
    {seq:1,stage:'model_text',text:'<script>bad()</script> not Ru'},
    {seq:2,stage:'extracted_source',text:'not Ru'},
    {seq:3,stage:'final_failure',detail:'源码提取失败'},
  ]}},false);await promise;
  const trace=h.context.generationTraces.get(h.cell);
  assert.equal(trace.events[0].text,'<script>bad()</script> not Ru');
  assert.equal(trace.events[1].text,'not Ru');assert.equal(trace.complete,true);
  assert.equal(h.cell.generation.revisions.length,0);assert.equal(h.cell.source,'private draft');
  assert.equal(JSON.stringify(h.cell).includes('<script>'),false);
});

test('cancelled late trace cannot replace newer generation diagnostics',async()=>{
  const h=harness(),{promise:old}=await h.start();
  const oldId=h.context.generationTraces.get(h.cell).generation_id;
  // Settle the old fetch after cancellation, before starting another generation.
  h.context.cancelGeneration();h.respond({source:'old',valid:true,trace:{schema_version:1,generation_id:oldId,events:[{seq:1,stage:'model_text',text:'late'}]}});await old;
  assert.equal(h.context.generationTraces.get(h.cell).events.length,0);
  const {promise}=await h.start(),fresh=h.context.generationTraces.get(h.cell);
  assert.notEqual(fresh.generation_id,oldId);
  h.respond({source:'new',valid:true,trace:{schema_version:1,generation_id:oldId,events:[{seq:1,stage:'model_text',text:'wrong identity'}]}});await promise;
  assert.equal(fresh.events.length,0);
});

test('clear erases evidence and suppresses late trace but does not cancel authorized generation',async()=>{
  const h=harness(),{promise}=await h.start(),state=h.context.generationTraces.get(h.cell),id=state.generation_id;
  mergeTrace(state,{schema_version:1,generation_id:id,events:[{seq:1,stage:'model_text',text:'private model'}]});
  h.context.clearGenerationTrace(h.cell);
  assert.equal(state.events.length,0);assert.equal(state.cleared,true);assert.equal(h.calls[0].options.signal.aborted,false);
  h.respond({source:'显 1.',valid:true,trace:{schema_version:1,generation_id:id,events:[{seq:2,stage:'model_text',text:'late private'}]}});await promise;
  assert.equal(state.events.length,0);assert.equal(h.cell.source,'显 1.');
});

test('replacing the book with an identical cell id cannot leak trace into that book',async()=>{
  const h=harness(),{promise}=await h.start(),oldState=h.context.generationTraces.get(h.cell);
  const next={...h.cell,generation:structuredClone(h.cell.generation)};h.context.book={cells:[next]};h.context.epoch++;
  h.respond({source:'late',valid:true,trace:{schema_version:1,generation_id:oldState.generation_id,events:[{seq:1,stage:'model_text',text:'other book'}]}});await promise;
  assert.equal(h.context.generationTraces.get(next),undefined);assert.equal(oldState.events.length,0);assert.equal(next.source,'private draft');
});

test('timeout trace preserves observed HTTP stages without inventing model text or running code',async()=>{
  const h=harness(),{promise}=await h.start(),state=h.context.generationTraces.get(h.cell);
  h.respond({error:'等待超过配置时限，提供方可能仍在处理。',trace:{schema_version:1,generation_id:state.generation_id,complete:true,events:[{seq:1,stage:'request_sent'},{seq:2,stage:'waiting'},{seq:3,stage:'final_failure',detail:'timeout'}]}},false);await promise;
  assert.equal(state.events.length,3);assert.equal(state.events.some(event=>event.text!==undefined),false);
  assert.equal(h.cell.generation.revisions.length,0);assert.equal(h.cell.outputs.length,0);assert.match(state.phase,/时限/);
});


test('old response resolving during a newer request leaves its trace and busy state untouched',async()=>{
  const h=harness(),{promise:old}=await h.start(),oldId=h.context.generationTraces.get(h.cell).generation_id;
  h.context.cancelGeneration();const {promise:latest}=await h.start(),fresh=h.context.generationTraces.get(h.cell);
  const current=h.context.generationRequest;
  h.respondAt(0,{source:'old',valid:true,trace:{schema_version:1,generation_id:oldId,events:[{seq:1,stage:'model_text',text:'old private'}]}});await old;
  assert.equal(h.context.generationRequest,current);assert.equal(h.context.generationTraces.get(h.cell),fresh);assert.equal(fresh.events.length,0);
  assert.equal(h.cell.source,'private draft');assert.equal(h.context.views.get(h.cell.id).generationActivity.hidden,false);
  h.respond({source:'new',valid:true,trace:{schema_version:1,generation_id:fresh.generation_id,events:[{seq:1,stage:'model_text',text:'new model'}]}});await latest;
  assert.equal(fresh.events[0].text,'new model');assert.equal(h.cell.source,'new');
});
