import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {captureDiagnostic,currentDiagnostic} from '../static/diagnostics.mjs';
import {copyInput} from '../static/clipboard.mjs';
import {parseBook,serializeBook,newCell} from '../static/notebook.mjs';
const source=fs.readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const browserSource=source.slice(source.indexOf('let browserRun=null'),source.indexOf('async function runAndMove('));
const flush=()=>new Promise(r=>setImmediate(r));
function harness({compile,driver}={}){
 const cell=newCell('code',"显 '中文 😀'.");cell.execution_backend='browser-js';let disposed=0,options;
 const context={cell,book:{cells:[cell]},epoch:1,session:'python-session',generation:1,activeRun:null,sceneViews:new Map(),crypto:{randomUUID:()=>`token-${Math.random()}`},
 clearScene(){},renderOutput(){},refreshControls(){},runtimeStatus(){},markDirty(){},sourceVersion:async s=>'hash:'+s,
 closeScenesBeforeRun:async()=>{},api:compile||(async(path,method,body)=>({javascript:'COMPILED'})),
 appendOutput:(c,type,text)=>c.outputs.push({type,text}),captureDiagnostic:()=>null,validateScene:e=>e,retainGraphics(){},
 createJSExecution:opts=>{options=opts;return driver?.(opts)||{ready:Promise.resolve(),active:true,dispose(){disposed++;}};},
 stopScenes(){context.stopBrowserRun();},finishActive(ok){const run=context.activeRun;context.activeRun=null;run?.resolve(ok);}};
 vm.createContext(context);vm.runInContext(browserSource,context);
 return {context,cell,get options(){return options;},get disposed(){return disposed;}};
}
test('backend preference round trips as data, old books stay Python, invalid values rejected',()=>{
 const cell=newCell();cell.execution_backend='browser-js';cell.driver={secret:'worker'};const book={title:'JS',cells:[cell]};const text=serializeBook(book),restored=parseBook(text);
 assert.equal(restored.cells[0].execution_backend,'browser-js');assert.equal(restored.cells[0].status,'idle');assert.ok(!text.includes('worker'));assert.equal(parseBook(serializeBook({title:'Old',cells:[newCell()]})).cells[0].execution_backend,undefined);
 for(const backend of [true,'jit','<script>']){cell.execution_backend=backend;assert.throws(()=>serializeBook(book),/运行方式/);}
 cell.execution_backend='browser-js';cell.type='markdown';assert.throws(()=>serializeBook(book),/运行方式/);
});
test('copy writes exact current raw text including empty, CJK, newline and emoji, never reads',async()=>{
 const writes=[],clipboard={writeText:async text=>writes.push(text),readText(){throw Error('must not read');}};
 for(const text of ['',"如是我言\n😀\r\n **原文** <div>"])await copyInput(text,clipboard);
 assert.deepEqual(writes,['',"如是我言\n😀\r\n **原文** <div>"]);
 await assert.rejects(copyInput('文字',{writeText:async()=>{throw Error('denied');}}),/复制未成功/);
 await assert.rejects(copyInput('文字',{}),/手动复制/);
});
test('copy buttons read live input and report without dirtying notebook',()=>{
 const block=source.slice(source.indexOf('function copyButton('),source.indexOf('let hasBook='));assert.ok(!block.includes('markDirty'));assert.ok(!block.includes('cell.'));
 assert.match(source,/copyButton\(\(\)=>view\.input\?\.value\?\?cell\.source\)/);assert.match(source,/copyButton\(\(\)=>prompt\.value,'复制意图'\)/);
});
test('browser run uses actual compiler/driver and independent identity; stop rejects stale events',async()=>{
 const h=harness();assert.equal(await h.context.runBrowserCell(h.cell),true);assert.equal(h.options.javascript,'COMPILED');assert.equal(h.options.identity.cell_id,h.cell.id);assert.equal(h.cell.runtimeBackend,'browser-js');
 h.options.onEvent({type:'output',text:'current',stream:'stdout'});assert.equal(h.cell.outputs[0].text,'current');h.context.stopBrowserRun();assert.equal(h.disposed,1);
 h.options.onEvent({type:'output',text:'STALE',stream:'stdout'});assert.equal(h.cell.outputs.length,1);
});
test('stopping during pending compile prevents any worker and resolves the run',async()=>{
 let release;const h=harness({compile:()=>new Promise(r=>release=r)});const done=h.context.runBrowserCell(h.cell);await flush();h.context.stopBrowserRun();release({javascript:'OLD'});assert.equal(await done,false);assert.equal(h.options,undefined);
});
test('compile errors do not fall back to Python or start a worker',async()=>{
 const h=harness({compile:async()=>({error:'语法错误'})});assert.equal(await h.context.runBrowserCell(h.cell),false);assert.equal(h.options,undefined);assert.equal(h.cell.status,'error');assert.equal(h.cell.outputs[0].text,'语法错误\n');
});
test('rerun disposes old worker and ignores stale callbacks even with same cell source',async()=>{
 const h=harness();await h.context.runBrowserCell(h.cell);const old=h.options;await h.context.runBrowserCell(h.cell);assert.equal(h.disposed,1);assert.notEqual(old.identity.token,h.options.identity.token);assert.notEqual(old.identity.execution_count,h.options.identity.execution_count);old.onEvent({type:'error',message:'OLD'});assert.equal(h.cell.outputs.length,0);
});
test('worker fatal stops execution and resolves initial run honestly',async()=>{
 let fail,reject;const h=harness({driver:opts=>{fail=error=>{opts.onFatal(error);reject(error);};return {ready:new Promise((_,no)=>reject=no),active:true,dispose(){}};}});const done=h.context.runBrowserCell(h.cell);await flush();fail(new Error('超时'));assert.equal(await done,false);assert.equal(h.cell.status,'error');assert.equal(h.context.activeRun,null);assert.equal(h.cell.outputs.length,1);assert.equal(h.cell.outputs[0].text,'超时\n');
});
test('stopping while initial worker runs rejects ready and resolves caller',async()=>{
 let reject;const h=harness({driver:()=>({ready:new Promise((_,no)=>reject=no),active:true,dispose(){reject(new Error('已停止'));}})});const done=h.context.runBrowserCell(h.cell);await flush();h.context.stopBrowserRun();assert.equal(await done,false);assert.equal(h.cell.outputs.length,0);
});
test('Python canvas preflight explicitly preserves only the new browser record',async()=>{
 const h=harness();const fn=source.slice(source.indexOf('async function closeScenesBeforeRun('),source.indexOf('function clearScene('));
 h.context.cursor=0;h.context.performance={now:()=>0};h.context.setTimeout=fn=>fn();const calls=[];
 h.context.stopScenes=(close,preserve)=>{calls.push([close,preserve]);if(!preserve)h.context.stopBrowserRun();};
 h.context.api=async path=>path==='/compile'?{javascript:'COMPILED'}:{state:'idle',generation:1};vm.runInContext(fn,h.context);
 assert.equal(await h.context.runBrowserCell(h.cell),true);assert.deepEqual(calls,[[undefined,undefined],[false,true]]);
});

test('runtime fatal captures exact submitted diagnostic and never underlines edited source',async()=>{
 const h=harness();h.context.captureDiagnostic=captureDiagnostic;await h.context.runBrowserCell(h.cell);
 const diagnostic={formatted:'第1行错误',message:'运行错误',line:1,col:1,source:{kind:'cell',...h.options.identity}};
 h.options.onFatal({message:'运行错误',diagnostic});assert.equal(h.cell.outputs[0].text,'第1行错误\n');assert.equal(h.cell.diagnostics.length,1);assert.equal(currentDiagnostic(h.cell,h.cell.diagnostics[0]),true);
 h.cell.source='新源码';assert.equal(currentDiagnostic(h.cell,h.cell.diagnostics[0]),false);
});
test('editing JS source immediately terminates once, drops diagnostics, undo never revives worker',async()=>{
 const h=harness();await h.context.runBrowserCell(h.cell);const old=h.options;h.cell.diagnostics=[{old:true}];
 h.context.invalidateEditedBrowserCell(h.cell,h.cell.source);assert.equal(h.disposed,0);
 h.context.invalidateEditedBrowserCell(newCell(), 'unrelated');assert.equal(h.disposed,0);
 const before=h.cell.source;h.context.invalidateEditedBrowserCell(h.cell,'输入中');h.cell.source='输入中';assert.equal(h.disposed,1);assert.equal(h.cell.diagnostics.length,0);assert.equal(h.cell.diagnosticSnapshot,undefined);
 h.context.invalidateEditedBrowserCell(h.cell,before);h.cell.source=before;assert.equal(h.disposed,1);old.onEvent({type:'output',text:'OLD',stream:'stdout'});assert.equal(h.cell.outputs.length,0);
 const update=source.slice(source.indexOf('  function update(auto=false)'),source.indexOf('  // The textarea overlays'));
 assert.match(update,/invalidateEditedBrowserCell\(cell,input.value\)/);assert.ok(update.indexOf('invalidateEditedBrowserCell')>update.indexOf('if(auto&&!composing)'));
 // The invalidation is outside the IME-only indentation guard and input calls update even while composing.
 assert.match(source,/addEventListener\('input',\(\)=>update\(true\)\)/);assert.match(source,/compositionend'.*update\(true\)/);
});
test('ordinary runtime error event destroys worker and preserves structured diagnostic',async()=>{
 const h=harness();h.context.captureDiagnostic=captureDiagnostic;await h.context.runBrowserCell(h.cell);
 h.options.onEvent({type:'error',message:'循环预算',diagnostic:{message:'循环预算',line:1,col:1,source:{kind:'cell',...h.options.identity}}});
 assert.equal(h.disposed,1);assert.equal(h.cell.status,'error');assert.equal(h.cell.diagnostics.length,1);assert.equal(h.cell.outputs.length,1);
});
