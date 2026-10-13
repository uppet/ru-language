import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

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
  const diagnostic={textContent:''},intervals=new Map(),calls=[],statuses=[];
  let clock=1000,resolveResponse,nextTimer=1;
  const context={
    generationRequest:null,book:{cells:[cell]},epoch:0,providerInfo:null,token:'private-token',MAX_SOURCE:200000,
    views:new Map([[cell.id,{prompt:{value:''},input:{value:cell.source},generationDiagnostic:diagnostic,renderEditor(){}}]]),
    AbortController,structuredClone,performance:{now:()=>clock},
    busy:()=>false,withGenerationMarker:text=>text,generationIntent:text=>text,
    checkpoint(){},serializeBook(){},renderHistory(){},markDirty(){},refreshControls(){},renderOutput(){},notice(){},
    el:(tag,cls,text)=>new Node(text),document:{createElementNS:()=>new Node()},
    replaceWithRevision:(candidate,revision)=>{candidate.source=revision.source;candidate.generation.revisions.push(revision);},
    api:async()=>({configured,provider_host:'provider.example',message:'Missing configuration'}),
    confirm:()=>confirm,
    fetch:(path,options)=>{calls.push({path,options});return new Promise(resolve=>{resolveResponse=resolve;});},
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
