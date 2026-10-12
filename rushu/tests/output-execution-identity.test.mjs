import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const runSource=source.slice(source.indexOf('async function runCell('),source.indexOf('async function runAll('));
const pollSource=source.slice(source.indexOf('let pollTimer;'),source.indexOf('function saveBook('));
test('late previous callback cannot enter a new execution or finish it during canvas preflight',async()=>{
 let release;const preflight=new Promise(r=>release=r),cell={id:'cell',type:'code',source:"显 'new'.",execution_count:7,status:'done',outputs:[]};
 let events=[{type:'output',stream:'stdout',text:'OLD CALLBACK\n',seq:1,generation:1,cell_id:'cell',execution_count:7},{type:'done',status:'ok',seq:2,generation:1,cell_id:'cell',execution_count:7}],posts=0;
 const context={sourceVersion:async()=>"test-hash",cell,connected:true,session:'s',activeRun:null,epoch:1,generation:1,lastExecutionCount:7,views:new Map(),scenePending:new Map(),sceneViews:new Map(),book:{cells:[cell]},cursor:0,polling:false,transition:false,kernelDead:false,
 generationIntent:()=>null,stopScenes(){},clearScene(){},renderOutput(){},refreshControls(){},runtimeStatus(){},markDirty(){},notice(){},closeScenesBeforeRun:()=>preflight,
 appendOutput:(c,type,text)=>c.outputs.push({type,text}),setTimeout:()=>1,clearTimeout(){},sessionPath:s=>s,
 finishActive(ok){const run=context.activeRun;context.activeRun=null;run?.resolve(ok);},
 api:async(path,method)=>{if(method==='POST'){posts++;return {execution_count:8,generation:1};}return {events,cursor:events.at(-1)?.seq||0,state:'idle',execution_count:events.at(-1)?.execution_count||7};},
 };
 context.browserRun=null;vm.createContext(context);vm.runInContext(runSource+pollSource,context);const running=context.runCell(cell);await context.pollEvents();
 assert.equal(cell.execution_count,null);assert.equal(cell.status,'running');assert.equal(cell.outputs.length,0);assert.ok(context.activeRun);
 release();await new Promise(resolve=>setImmediate(resolve));assert.equal(posts,1);assert.equal(cell.execution_count,8);
 events=[{type:'output',stream:'stdout',text:'NEW\n',seq:3,generation:1,cell_id:'cell',execution_count:8},{type:'done',status:'ok',seq:4,generation:1,cell_id:'cell',execution_count:8}];await context.pollEvents();
 assert.equal(await running,true);assert.equal(cell.outputs.map(o=>o.text).join(''),'NEW\n');assert.equal(cell.status,'done');
});
