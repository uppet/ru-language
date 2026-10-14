import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const polling=source.slice(source.indexOf('let pollTimer;'),source.indexOf('function saveBook('));
function harness(overrides={},cellOverrides={},activeRun=null){
  const cell={id:'cell',execution_count:2,status:'done',outputs:[],...cellOverrides};
  const effects={rendered:0,deactivated:0,rejected:0,resolved:0};
  const context={cell,session:'s',epoch:1,generation:1,cursor:0,polling:false,transition:false,book:{cells:[cell]},activeRun,connected:true,kernelDead:false,lastExecutionCount:2,
    sceneKey:(cell,id)=>JSON.stringify([cell.id,cell.execution_count,id]),
    scenePending:new Map([[JSON.stringify(['cell',2,'canvas']),{reject:()=>effects.rejected++,resolve:()=>effects.resolved++}]]),sceneViews:new Map([[JSON.stringify(['cell',2,'canvas']),{view:{deactivate:()=>effects.deactivated++}}]]),
    api:async()=>({events:[{seq:1,generation:1,cell_id:'cell',execution_count:2,type:'graphics_done',canvas_id:'canvas',status:'error',...overrides}],cursor:1,state:'idle',execution_count:2}),
    renderOutput(){effects.rendered++;},markDirty(){},runtimeStatus(){},refreshControls(){},notice(){},stopScenes(){},setTimeout(){return 1;},clearTimeout(){},
  };
  context.browserRun=null;vm.createContext(context);vm.runInContext(polling,context);return {context,cell,effects};
}
test('matching callback failure marks the cell failed, renders it and stops its canvas',async()=>{
 const {context,cell,effects}=harness();await context.pollEvents();
 assert.equal(cell.status,'error');assert.deepEqual(effects,{rendered:1,deactivated:1,rejected:1,resolved:0});
});
test('late callback errors from other generations, executions and deleted cells cannot change current state',async()=>{
 for(const event of [{generation:0},{execution_count:1},{cell_id:'deleted'}]){
  const {context,cell,effects}=harness(event);await context.pollEvents();assert.equal(cell.status,'done');assert.deepEqual(effects,{rendered:0,deactivated:0,rejected:0,resolved:0});
 }
 const {context,cell,effects}=harness({}, {status:'running',execution_count:null}, {cellId:'cell',beforeCount:2});
 await context.pollEvents();assert.equal(cell.status,'running');assert.equal(cell.execution_count,null);assert.equal(effects.rendered,0);
});
test('normal callback completion and intentional canvas close do not label the cell an error',async()=>{
 for(const event of [{status:'ok'},{type:'graphics_closed',status:'ok'},{type:'graphics_closed',status:undefined}]){
  const {context,cell,effects}=harness(event);await context.pollEvents();assert.equal(cell.status,'done');assert.equal(effects.rejected,0);assert.equal(effects.resolved,1);
 }
});
