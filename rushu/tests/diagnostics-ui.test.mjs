import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {captureDiagnostic} from '../static/diagnostics.mjs';

const source=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const locations=source.slice(source.indexOf('function diagnosticLocation('),source.indexOf('function generationDiagnostic('));
const polling=source.slice(source.indexOf('let pollTimer;'),source.indexOf('function saveBook('));
function harness(event,extra={}){
  const cell={id:'cell',execution_count:1,outputs:[],status:'error',...extra};
  const context={Number,captureDiagnostic,cell,scenePending:new Map(),session:'session',epoch:1,generation:1,cursor:0,polling:false,transition:false,
    book:{cells:[cell]},activeRun:null,connected:true,kernelDead:false,lastExecutionCount:1,
    api:async()=>({events:[{seq:1,generation:1,cell_id:'cell',execution_count:1,type:'error',...event}],cursor:1,state:'idle',execution_count:1}),
    appendOutput:(target,type,text)=>target.outputs.push({type,text}),renderOutput(){},markDirty(){},runtimeStatus(){},refreshControls(){},notice(){},
    setTimeout(){return 1;},clearTimeout(){},
  };
  context.browserRun=null;vm.createContext(context);vm.runInContext(locations+polling,context);
  return {context,cell};
}

test('actual event polling retains imported error origin and its line and column',async()=>{
  const {context,cell}=harness({source_name:'/本机/练习/module.ru',line:4,col:8,message:'未定义名称'});
  await context.pollEvents();
  assert.equal(cell.outputs[0].text,'来源：/本机/练习/module.ru\n第 4 行，第 8 列\n未定义名称\n');
  assert.equal(cell.outputs[0].type,'error');
});

test('cell errors without source keep positions and errors without positions remain readable',async()=>{
  for(const [event,expected] of [
    [{source_name:'',line:2,col:1,message:'错误'},'第 2 行，第 1 列\n错误\n'],
    [{message:'错误'},'错误\n'],
    [{line:0,col:5,message:'错误'},'错误\n'],
    [{line:2,col:-1,message:'错误'},'第 2 行\n错误\n'],
    [{line:'2',col:'1',message:'错误'},'错误\n'],
  ]){
    const {context,cell}=harness(event);await context.pollEvents();assert.equal(cell.outputs[0].text,expected);
  }
});

test('origin controls are escaped and markup stays ordinary output text',async()=>{
  const {context,cell}=harness({source_name:'<img src=x onerror=bad()>\n\u202e模块.ru',line:1,col:1,message:'错误'});
  await context.pollEvents();
  assert.equal(cell.outputs[0].text,'来源：<img src=x onerror=bad()>\\u000a\\u202e模块.ru\n第 1 行，第 1 列\n错误\n');
  // The output path remains the existing text-only renderer, never innerHTML.
  assert.ok(source.includes("else output.append(el('pre',item.type,item.text));"));
  assert.ok(source.includes('if(text!=null)node.textContent=text'));
  assert.ok(context.diagnosticLocation({source_name:'x'.repeat(5000)},true).length<=4099);
});

test('generation locations never include source metadata and reject invalid numeric positions',()=>{
  const {context}=harness({});
  assert.equal(context.diagnosticLocation({source_name:'private path',line:3,col:7}),'第 3 行，第 7 列');
  for(const line of [null,NaN,Infinity,-1,0,1.5,Number.MAX_SAFE_INTEGER+1])assert.equal(context.diagnosticLocation({line,col:1}),'');
});


test('actual event polling captures only the matching structured execution snapshot',async()=>{
 const extra={source:'甲😀未定义',diagnosticSnapshot:{source:'甲😀未定义',version:'hash',generation:1,execution:1}};
 const diagnostic={line:1,col:3,message:'错误',source:{kind:'cell',cell_id:'cell',execution_count:1,generation:1,source_version:'hash'}};
 const {context,cell}=harness({line:1,col:3,message:'错误',diagnostic},extra);await context.pollEvents();
 assert.equal(cell.diagnostics.length,1);assert.equal(cell.diagnostics[0].range.start,3);assert.equal(cell.diagnostics[0].range.end,4);
 for(const late of [{execution_count:2},{generation:2}]){
  const result=harness({line:1,col:3,message:'错误',diagnostic,...late},extra);await result.context.pollEvents();assert.equal(result.cell.diagnostics,undefined);assert.equal(result.cell.outputs.length,0);
 }
});

test('budget detail stays readable and retains matching callback source highlight',async()=>{
 const message='如观回调超过时间预算（实际约 1.0000000000000002 秒墙钟耗时，阈值 1 秒）；已关闭交互，请简化回调后重跑';
 const code='图 其 每帧 (作 帧: 为).';
 const extra={source:code,diagnosticSnapshot:{source:code,version:'budget-hash',generation:1,execution:1}};
 const diagnostic={line:1,col:3,message,source_name:'rushu://s/1/cell/1.ru',source:{kind:'cell',cell_id:'cell',execution_count:1,generation:1,source_version:'budget-hash'}};
 const {context,cell}=harness({line:1,col:3,message,diagnostic},extra);await context.pollEvents();
 assert.equal(cell.diagnostics.length,1);assert.equal(cell.diagnostics[0].message,message);
 assert.equal(cell.diagnostics[0].range.start,2);assert.equal(cell.diagnostics[0].range.end,3);
 assert.ok(cell.outputs[0].text.includes(message));assert.equal(cell.outputs[0].type,'error');
});
