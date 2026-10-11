import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const app=fs.readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const source=app.slice(app.indexOf('async function closeScenesBeforeRun('),app.indexOf('function clearScene('));
function context(api){return {api,session:'session-1',epoch:3,generation:2,cursor:17,stopScenes(){},performance:{now:()=>0},setTimeout:fn=>fn()};}
test('preflight uses the existing events route for idle ordinary cells',async()=>{
 const calls=[];const ctx=context(async path=>{calls.push(path);assert.equal(path,'/sessions/session-1/events?after=17');return {generation:2,graphics:null,graphics_busy:false};});
 await vm.runInNewContext(source+"closeScenesBeforeRun('session-1',3,2)",ctx);
 assert.equal(calls.length,1);
});
test('preflight closes a busy scene and waits without posting execute or clearing context',async()=>{
 const calls=[];let reads=0;const ctx=context(async(path,method='GET',body)=>{
  calls.push({path,method,body});if(method==='POST'){assert.equal(path,'/sessions/session-1/graphics');assert.equal(body.event.type,'close');assert.equal(body.execution_count,4);return {};}
  assert.equal(path,'/sessions/session-1/events?after=17');reads++;
  return reads===1?{generation:2,graphics:{canvas_id:'canvas'},graphics_busy:true,cell_id:'old-cell',execution_count:4}:{generation:2,graphics:null,graphics_busy:false};
 });
 await vm.runInNewContext(source+"closeScenesBeforeRun('session-1',3,2)",ctx);
 assert.equal(reads,2);assert.equal(calls.filter(c=>c.method==='POST').length,1);assert.equal(ctx.generation,2);
});
test('a changed session cancels preflight before sending mutations',async()=>{
 let mutations=0;let ctx;ctx=context(async(path,method='GET')=>{if(method!=='GET')mutations++;ctx.epoch=4;return {generation:2,graphics:null,graphics_busy:false};});
 await assert.rejects(vm.runInNewContext(source+"closeScenesBeforeRun('session-1',3,2)",ctx),/会话已切换/);assert.equal(mutations,0);
});
