import test from 'node:test';
import assert from 'node:assert/strict';
import {createJSExecution} from '../static/js-execution.mjs';
const identity={cell_id:'cell-a',execution_count:3,generation:4,token:'unique'};
class FakeWorker {
  messages=[];terminated=false;
  postMessage(message){this.messages.push(message);}
  terminate(){this.terminated=true;}
  reply(data){this.onmessage?.({data:{identity,serial:0,type:'batch',events:[],...data}});}
}
function setup(options={}){const worker=new FakeWorker(),events=[],fatal=[];const run=createJSExecution({javascript:'export default ()=>({dispatch(){}})',identity,onEvent:event=>events.push(event),onFatal:event=>fatal.push(event),workerFactory:()=>worker,...options});return {worker,events,fatal,run};}
const output=text=>({type:'output',stream:'stdout',text});
test('isolated initialization batches output and rejects old identity/serial',async()=>{
  const {worker,run,events}=setup();assert.equal(worker.messages[0].type,'init');
  const late=worker.onmessage;
  for(const key of ['cell_id','execution_count','generation','token'])worker.reply({identity:{...identity,[key]:'old'},events:[output('old')]});
  worker.reply({serial:7,events:[output('old')]});assert.equal(events.length,0);
  worker.reply({events:[output('<img src=x onerror=alert(1)>')]});await run.ready;assert.equal(events[0].text,'<img src=x onerror=alert(1)>');assert.equal(events[0].token,identity.token);
  run.stop();late({data:{identity,serial:0,type:'batch',events:[output('late')]}});assert.equal(events.length,1);assert.ok(worker.terminated);
});
test('one flight, coalesced frame/move and ack even without output',async()=>{
  const {worker,run}=setup();worker.reply({});await run.ready;
  const a=run.send({canvas_id:'c',type:'frame'}),b=run.send({canvas_id:'c',type:'frame'}),c=run.send({canvas_id:'c',type:'frame'});await b;
  assert.equal(worker.messages.length,2);worker.reply({serial:1});await a;assert.equal(worker.messages.length,3);assert.equal(worker.messages[2].serial,3);worker.reply({serial:3});await c;run.dispose();
});
test('init hard timeout terminates and reports exactly once without fallback',async()=>{
  const {worker,run,fatal}=setup({limits:{initMs:5}});await assert.rejects(run.ready,/超时/);assert.equal(worker.terminated,true);assert.equal(fatal.length,1);assert.equal(worker.messages.length,1);run.stop();assert.equal(fatal.length,1);
});
test('callback hard timeout rejects flight and queue',async()=>{
  const {worker,run,fatal}=setup({limits:{callbackMs:5}});worker.reply({});await run.ready;
  const a=run.send({canvas_id:'c',type:'frame'}),b=run.send({canvas_id:'c',type:'mouse_down'});
  await Promise.all([assert.rejects(a,/超时/),assert.rejects(b,/超时/)]);assert.equal(fatal.length,1);assert.ok(worker.terminated);
});
test('structured failure preserves source diagnostics',async()=>{
  const {worker,run,fatal}=setup();const diagnostic={source:{kind:'cell',cell_id:'cell-a'},line:7,col:3,message:'未定义'};
  worker.reply({type:'failure',message:'未定义',diagnostic});await assert.rejects(run.ready,/未定义/);assert.deepEqual(fatal[0].diagnostic,diagnostic);assert.equal(fatal[0].execution_count,3);
});
test('output and malformed scene limits fail closed before rendering',async()=>{
  for(const events of [[output('12345')],[{type:'graphics',canvas_id:'x',width:1,height:1,fps:60,handlers:[],running:false,commands:[{op:'eval'}]}]]){
    const {worker,run,fatal,events:received}=setup({limits:{outputBytes:4}});worker.reply({events});await assert.rejects(run.ready);assert.equal(received.length,0);assert.equal(fatal.length,1);assert.ok(worker.terminated);
  }
});
test('queue remains bounded; disposal settles outstanding requests',async()=>{
  const {worker,run}=setup({limits:{queue:1}});worker.reply({});await run.ready;
  const a=run.send({canvas_id:'c',type:'frame'}),b=run.send({canvas_id:'c',type:'key_down',key:'a'});await assert.rejects(run.send({canvas_id:'c',type:'key_up',key:'a'}),/队列/);
  const checks=[assert.rejects(a,/释放/),assert.rejects(b,/释放/)];run.dispose();await Promise.all(checks);await assert.rejects(run.send({canvas_id:'c',type:'frame'}),/停止/);
});
test('canvas close immediately terminates even an in-flight callback',async()=>{
  const {worker,run,events}=setup();worker.reply({});await run.ready;
  const pending=run.send({canvas_id:'c',type:'frame'}),check=assert.rejects(pending,/停止/);
  await run.send({canvas_id:'c',type:'close'});await check;assert.equal(worker.terminated,true);assert.equal(run.active,false);assert.equal(events.at(-1).type,'graphics_closed');assert.equal(worker.messages.length,2);
});
test('failure preserves prior bounded stdout before structured fatal',async()=>{
  const {worker,run,events,fatal}=setup();worker.reply({type:'failure',events:[output('before\n')],message:'undefined'});await assert.rejects(run.ready,/undefined/);assert.equal(events[0].text,'before\n');assert.equal(fatal.length,1);
});
