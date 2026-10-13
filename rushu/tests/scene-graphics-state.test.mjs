import test from 'node:test';
import assert from 'node:assert/strict';
import {validateScene,drawScene} from '../static/scene.mjs';
import {parseBook,serializeBook,newCell} from '../static/notebook.mjs';
const I=[1,0,0,1,0,0],T=[2,0,0,3,10,20];
const clip=()=>({x:0,y:0,width:20,height:30,transform:I.slice()});
const polygon=()=>({op:'polygon',points:[[0,0],[10,0],[0,10]],fill:'#ff0000',stroke:'#000000',stroke_width:2,transform:T.slice(),clips:[clip()]});
const frame=(commands=[polygon()])=>({canvas_id:'safe-worker',width:100,height:100,fps:30,running:false,handlers:[],commands});
test('untrusted worker transforms, clips and polygons reject malformed and extreme fields',()=>{
  const changes=[c=>c.transform=null,c=>c.transform=[1,0,0,1,0],c=>c.transform=[1,0,0,1,0,Infinity],c=>c.transform=[1,0,0,1,0,100001],c=>c.transform=[true,0,0,1,0,0],c=>c.clips=null,c=>c.clips=Array(33).fill(clip()),c=>c.clips=[null],c=>c.clips[0].width=-1,c=>delete c.clips[0].transform,c=>c.clips[0].transform=null,c=>c.points=[[0,0],[1,1]],c=>c.points=Array(257).fill([0,0]),c=>c.points[0]=[0,0,0],c=>c.points[0]=[NaN,0],c=>c.points[0]=[100001,0],c=>c.points[0]=['0',0],c=>c.stroke_width=0,c=>c.fill='url(x)',c=>c.points[0]=new Array(2),c=>c.transform=new Array(6)];
  for(const change of changes){const c=polygon();change(c);assert.throws(()=>validateScene(frame([c])));}
});
test('normalized scenes deep-copy safe state and preserve it in history',()=>{
  const input=frame();const output=validateScene(input);assert.deepEqual(output,input);
  output.commands[0].points[0][0]=42;output.commands[0].clips[0].transform[4]=42;output.commands[0].transform[4]=42;
  assert.equal(input.commands[0].points[0][0],0);assert.equal(input.commands[0].clips[0].transform[4],0);assert.equal(input.commands[0].transform[4],10);
  const cell=newCell('code','');cell.outputs=[{type:'graphics',scene:input}];
  const restored=parseBook(serializeBook({title:'state',cells:[cell]})).cells[0];assert.deepEqual(restored.outputs[0].scene.commands,input.commands);assert.equal(restored.historical,true);
});
function context(throws=false){const calls=[];const ctx=new Proxy({}, {get:(_,key)=>(...args)=>{calls.push([key,...args]);if(throws&&key==='fill')throw new Error('paint failed');},set:()=>true});return {calls,canvas:{getContext:()=>ctx}};}
test('each primitive installs frozen clips then its matrix and restores native state',()=>{
  const shapes=[polygon(),{op:'rect',x:0,y:0,width:5,height:5,fill:'#ff0000',stroke:'',stroke_width:1},{op:'ellipse',x:0,y:0,width:5,height:5,fill:'#ff0000',stroke:'',stroke_width:1},{op:'line',x1:0,y1:0,x2:1,y2:1,color:'#000000',width:1},{op:'text',x:0,y:0,text:'如',color:'#000000',size:16}];
  for(const command of shapes){command.transform=T.slice();command.clips=[clip(),{...clip(),transform:T.slice()}];const {calls,canvas}=context();drawScene(canvas,frame([command]));assert.deepEqual(calls[0],['save']);assert.deepEqual(calls.at(-1),['restore']);assert.equal(calls.filter(c=>c[0]==='clip').length,2);assert.deepEqual(calls.filter(c=>c[0]==='setTransform'),[['setTransform',...I],['setTransform',...T],['setTransform',...T]]);}
});
test('polygon closes its native path; exceptions and skipped invisible commands restore state',()=>{
  const {canvas,calls}=context();drawScene(canvas,frame());assert.ok(calls.some(c=>c[0]==='closePath'));
  const failed=context(true);assert.throws(()=>drawScene(failed.canvas,frame()),/paint failed/);assert.deepEqual(failed.calls.at(-1),['restore']);
  const hidden=context();drawScene(hidden.canvas,frame([{op:'text',x:0,y:0,text:'',color:'',size:16,transform:T}]));assert.deepEqual(hidden.calls.at(-1),['restore']);
});
test('background ignores geometry and following legacy command has no leaked state',()=>{
  const {canvas,calls}=context();drawScene(canvas,frame([polygon(),{op:'background',color:'#ffffff',transform:T,clips:[clip()]},{op:'text',x:0,y:0,text:'legacy',color:'#000000',size:16}]));assert.equal(calls.filter(c=>c[0]==='save').length,3);assert.deepEqual(calls.find(c=>c[0]==='fillRect'),['fillRect',0,0,100,100]);
});
