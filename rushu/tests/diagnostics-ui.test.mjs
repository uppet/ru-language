import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const locations=source.slice(source.indexOf('function diagnosticLocation('),source.indexOf('function generationDiagnostic('));
const polling=source.slice(source.indexOf('let pollTimer;'),source.indexOf('function saveBook('));
function harness(event){
  const cell={id:'cell',execution_count:1,outputs:[],status:'error'};
  const context={Number,cell,scenePending:new Map(),session:'session',epoch:1,generation:1,cursor:0,polling:false,transition:false,
    book:{cells:[cell]},activeRun:null,connected:true,kernelDead:false,lastExecutionCount:1,
    api:async()=>({events:[{seq:1,generation:1,cell_id:'cell',execution_count:1,type:'error',...event}],cursor:1,state:'idle',execution_count:1}),
    appendOutput:(target,type,text)=>target.outputs.push({type,text}),renderOutput(){},markDirty(){},runtimeStatus(){},refreshControls(){},notice(){},
    setTimeout(){return 1;},clearTimeout(){},
  };
  vm.createContext(context);vm.runInContext(locations+polling,context);
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
