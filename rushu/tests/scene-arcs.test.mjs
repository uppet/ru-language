import test from 'node:test';
import assert from 'node:assert/strict';
import {validateScene,drawScene,MAX_COMMANDS,MAX_FRAME_BYTES} from '../static/scene.mjs';
import {parseBook,serializeBook,newCell} from '../static/notebook.mjs';

const TAU=Math.PI*2,I=[1,0,0,1,0,0],T=[2,0,0,3,10,20];
const curve=(op='arc',extra={})=>({op,x:10,y:20,width:80,height:40,start:0.25,sweep:Math.PI/2,fill:op==='arc'?'':'#ABCDEF80',stroke:'#12345680',stroke_width:3,...extra});
const frame=commands=>({canvas_id:'native-curves',width:160,height:120,fps:30,running:false,handlers:[],commands});
const book=scene=>{const cell=newCell('code','');cell.outputs=[{type:'graphics',scene}];return {title:'弧与扇形',cells:[cell]};};
const clip=(transform=I)=>({x:5,y:6,width:70,height:50,transform:transform.slice()});

function context({failOn,scoped=true}={}){
  const calls=[],paints=[],stack=[];
  let state={transform:I.slice(),clips:[],fillStyle:'#000000',strokeStyle:'#000000',lineWidth:1};
  const copy=()=>({...state,transform:state.transform.slice(),clips:state.clips.slice()});
  const ctx={};
  for(const name of ['beginPath','moveTo','lineTo','rect','ellipse','closePath','fill','stroke','clearRect','fillRect','setTransform','clip']){
    ctx[name]=(...args)=>{
      calls.push([name,...args]);
      if(name===failOn)throw new Error('native paint failed');
      if(name==='setTransform')state.transform=args;
      if(name==='clip')state.clips.push(state.transform.slice());
      if(['fill','stroke','fillRect'].includes(name))paints.push({name,...copy()});
    };
  }
  if(scoped){
    ctx.save=()=>{calls.push(['save']);stack.push(copy());};
    ctx.restore=()=>{calls.push(['restore']);state=stack.pop();};
  }
  const proxy=new Proxy(ctx,{set:(_,key,value)=>{calls.push(['set',key,value]);state[key]=value;return true;}});
  return {calls,paints,get state(){return state;},canvas:{getContext:()=>proxy}};
}
const pathCalls=calls=>calls.filter(([name])=>['beginPath','moveTo','lineTo','rect','ellipse','closePath','fill','stroke'].includes(name));

test('arc and sector schemas retain bounded raw angles and normalize only colors',()=>{
  for(const op of ['arc','sector'])for(const start of [-100000,-TAU,0,TAU,100000])for(const sweep of [-100000,-TAU,0,TAU,100000]){
    const input=curve(op,{x:-100000,y:100000,width:0,height:100000,start,sweep,stroke_width:256,script:'never execute'});
    const output=validateScene(frame([input])).commands[0];
    assert.deepEqual(output,{op,x:-100000,y:100000,width:0,height:100000,start,sweep,fill:op==='arc'?'':'#abcdef80',stroke:'#12345680',stroke_width:256});
    assert.notEqual(output,input);
    assert.equal(input.fill,op==='arc'?'':'#ABCDEF80');
  }
  for(const op of ['arc','sector'])assert.doesNotThrow(()=>validateScene(frame([curve(op,{width:100000,height:0,stroke_width:1})])));
});

test('untrusted curve numbers are required finite bounded numbers without coercion',()=>{
  const invalid=[undefined,null,true,false,'0',[],{},NaN,Infinity,-Infinity,100001,-100001];
  for(const op of ['arc','sector'])for(const key of ['x','y','width','height','start','sweep','stroke_width']){
    for(const value of invalid)assert.throws(()=>validateScene(frame([curve(op,{[key]:value})])),undefined,`${op}.${key} = ${String(value)}`);
    const command=curve(op);delete command[key];assert.throws(()=>validateScene(frame([command])));
  }
  for(const op of ['arc','sector'])for(const patch of [{width:-1},{height:-1},{stroke_width:0},{stroke_width:0.5},{stroke_width:257}]){
    assert.throws(()=>validateScene(frame([curve(op,patch)])));
  }
});

test('open arcs require exactly empty fill; sector styles require exact six/eight digit hex',()=>{
  const invalid=[undefined,null,true,0,[],{},'red','transparent','url(https://example.invalid)','var(--color)',
    '#fff','#ffff','#12345','#1234567','#123456789','#GG000080','#１２３４５６',' #123456','#123456 ',
    '#123456\n','#12345680\r\n','#123456\0','#12345680\u2028'];
  for(const value of invalid){
    for(const op of ['arc','sector'])assert.throws(()=>validateScene(frame([curve(op,{stroke:value})])));
    assert.throws(()=>validateScene(frame([curve('sector',{fill:value})])));
  }
  for(const value of [...invalid,'#000000','#00000000','#FFFFFF80']){
    assert.throws(()=>validateScene(frame([curve('arc',{fill:value})])));
  }
  for(const value of ['','#000000','#ABCDEF','#ABCDEF00','#ABCDEF80','#ABCDEFff']){
    for(const op of ['arc','sector']){
      const command=curve(op,{stroke:value,...(op==='sector'?{fill:value}:{})});
      const normalized=validateScene(frame([command])).commands[0];
      assert.equal(normalized.stroke,value.toLowerCase());
      assert.equal(normalized.fill,op==='arc'?'':value.toLowerCase());
    }
  }
});

test('curve transforms and clips use strict existing state schemas and reject text-only fields',()=>{
  const patches=[{transform:null},{transform:[1,0,0,1,0]},{transform:[1,0,0,1,Infinity,0]},
    {transform:[1,0,0,1,'0',0]},{transform:new Array(6)},{clips:null},{clips:Array(33).fill(clip())},
    {clips:[null]},{clips:[{...clip(),width:-1}]},{clips:[{...clip(),transform:null}]},
    {align:'left'},{baseline:'top'}];
  for(const op of ['arc','sector'])for(const patch of patches)assert.throws(()=>validateScene(frame([curve(op,patch)])));
});

test('malformed live and saved curves fail before any canvas resizing or drawing',()=>{
  const patches=[{start:null},{sweep:'1'},{width:-1},{stroke_width:0},{stroke:'url(x)'},{fill:'#000000'},
    {op:'constructor'},{op:'__proto__'},{transform:[1,0,0,1,0,100001]},{clips:[{...clip(),height:-1}]},{align:'left'}];
  for(const patch of patches){
    const scene=frame([{op:'background',color:'#ffffff'},curve('arc',patch)]),effects=[];
    const canvas={set width(value){effects.push(['width',value]);},set height(value){effects.push(['height',value]);},getContext(){effects.push(['context']);throw new Error('must not touch canvas');}};
    assert.throws(()=>drawScene(canvas,scene));assert.deepEqual(effects,[]);
    assert.throws(()=>serializeBook(book(scene)));
    const raw=JSON.parse(serializeBook(book(frame([curve()]))));
    raw.cells[0].outputs[0].scene=scene;
    assert.throws(()=>parseBook(JSON.stringify(raw)));
  }
});

test('operation names must be strings before lookup, including coercible arc and sector arrays',()=>{
  const names=['arc','sector','background','line','rect','ellipse','text','polygon'];
  const invalid=[undefined,null,true,0,{},[],...names.flatMap(name=>[[name],[[name]]])];
  for(const op of invalid){
    // Supply all primitive fields so a coerced name cannot escape through text validation.
    const command=curve('arc',{op,x1:1,y1:2,x2:3,y2:4,text:'untrusted',color:'#000000',size:12,points:[[0,0],[1,0],[0,1]]});
    const scene=frame([{op:'background',color:'#ffffff'},command]),effects=[];
    const canvas={set width(value){effects.push(['width',value]);},set height(value){effects.push(['height',value]);},getContext(){effects.push(['context']);throw new Error('must not touch canvas');}};
    assert.throws(()=>validateScene(scene));assert.throws(()=>drawScene(canvas,scene));assert.deepEqual(effects,[]);
    assert.throws(()=>serializeBook(book(scene)));
    const raw=JSON.parse(serializeBook(book(frame([curve()]))));raw.cells[0].outputs[0].scene=scene;
    assert.throws(()=>parseBook(JSON.stringify(raw)));
  }
});

test('operation validation never coerces boxed strings or executable property keys',()=>{
  for(const name of ['arc','sector','text']){
    let coercions=0;
    const coercible={toString(){coercions++;return name;},[Symbol.toPrimitive](){coercions++;return name;}};
    for(const op of [new String(name),coercible]){
      const scene=frame([curve('arc',{op,text:'untrusted',color:'#000000',size:12})]);
      assert.throws(()=>validateScene(scene));assert.throws(()=>serializeBook(book(scene)));
    }
    assert.equal(coercions,0);
  }
});

test('new commands retain existing frame byte and command limits',()=>{
  assert.throws(()=>validateScene(frame(Array(MAX_COMMANDS+1).fill(curve()))),/指令过多/);
  const scene=frame([curve('sector',{ignored:'x'.repeat(MAX_FRAME_BYTES)})]);
  assert.throws(()=>validateScene(scene),/帧过大/);
});

test('partial arcs use one native ellipse in the signed direction and never fill or close',()=>{
  for(const start of [-100000,-TAU,0.25,TAU,100000])for(const sweep of [-Math.PI/2,Math.PI/2])for(const scoped of [false,true]){
    const {calls,paints,canvas}=context({scoped});
    const output=drawScene(canvas,frame([curve('arc',{start,sweep})]));
    assert.deepEqual(pathCalls(calls),[['beginPath'],['ellipse',50,40,40,20,0,start,start+sweep,sweep<0],['stroke']]);
    assert.equal(paints.length,1);assert.equal(paints[0].strokeStyle,'#12345680');assert.equal(paints[0].lineWidth,3);
    assert.equal(output.commands[0].start,start);assert.equal(output.commands[0].sweep,sweep);
  }
});

test('partial sectors close the center-connected native ellipse once before fill and stroke',()=>{
  for(const sweep of [-Math.PI/2,Math.PI/2]){
    const {calls,paints,canvas}=context();drawScene(canvas,frame([curve('sector',{sweep})]));
    assert.deepEqual(pathCalls(calls),[['beginPath'],['moveTo',50,40],['ellipse',50,40,40,20,0,0.25,0.25+sweep,sweep<0],['closePath'],['fill'],['stroke']]);
    assert.equal(paints[0].fillStyle,'#abcdef80');assert.equal(paints[1].strokeStyle,'#12345680');
  }
});

test('complete positive or negative turns draw exactly one legacy ellipse with no radial seam',()=>{
  for(const op of ['arc','sector'])for(const start of [-100000,0.25,100000])for(const sweep of [-100000,-2*TAU,-TAU,TAU,2*TAU,100000]){
    const command=curve(op,{start,sweep}),actual=context(),legacy=context();
    const {start:unusedStart,sweep:unusedSweep,...ellipse}=command;
    drawScene(actual.canvas,frame([command]));drawScene(legacy.canvas,frame([{...ellipse,op:'ellipse'}]));
    assert.deepEqual(actual.calls,legacy.calls);
    assert.equal(actual.calls.filter(([name])=>name==='ellipse').length,1);
    for(const name of ['moveTo','lineTo','closePath'])assert.equal(actual.calls.filter(([call])=>call===name).length,0);
  }
});

test('zero sweeps remain serialized commands but perform no path, fill or stroke',()=>{
  for(const op of ['arc','sector'])for(const sweep of [0,-0]){
    const recorded=context();const scene=drawScene(recorded.canvas,frame([curve(op,{sweep})]));
    assert.equal(scene.commands.length,1);assert.equal(Object.is(scene.commands[0].sweep,sweep),true);
    assert.deepEqual(pathCalls(recorded.calls),[]);assert.deepEqual(recorded.paints,[]);
    assert.deepEqual(recorded.calls,[['save'],['restore']]);
    const restored=parseBook(serializeBook(book(scene))).cells[0].outputs[0].scene;
    assert.equal(restored.commands.length,1);assert.equal(restored.commands[0].sweep,0);
  }
});

test('zero width or height are legal and use native ellipse degeneration without sampling',()=>{
  for(const op of ['arc','sector'])for(const [width,height] of [[0,0],[0,40],[80,0]])for(const sweep of [-TAU,-Math.PI/2,Math.PI/2,TAU]){
    const {calls,canvas}=context();drawScene(canvas,frame([curve(op,{width,height,sweep})]));
    const ellipses=calls.filter(([name])=>name==='ellipse');assert.equal(ellipses.length,1);
    assert.deepEqual(ellipses[0].slice(1,6),[10+width/2,20+height/2,width/2,height/2,0]);
    assert.equal(calls.filter(([name])=>name==='lineTo').length,0);
  }
});

test('empty and transparent curve styles preserve normal compositing semantics',()=>{
  for(const op of ['arc','sector'])for(const sweep of [Math.PI/2,TAU]){
    const invisible=context();drawScene(invisible.canvas,frame([curve(op,{fill:'',stroke:'',sweep})]));
    assert.deepEqual(invisible.paints,[]);
    const transparent=context();drawScene(transparent.canvas,frame([curve(op,{fill:op==='arc'?'':'#ABCDEF00',stroke:'#FFFFFF00',sweep})]));
    assert.deepEqual(transparent.paints.map(p=>p.name),op==='arc'?['stroke']:['fill','stroke']);
    for(const paint of transparent.paints){if(paint.name==='fill')assert.equal(paint.fillStyle,'#abcdef00');else assert.equal(paint.strokeStyle,'#ffffff00');}
  }
});

test('curve clips install their snapshot matrices before drawing and cannot leak to later shapes',()=>{
  for(const op of ['arc','sector'])for(const sweep of [-TAU,-Math.PI/2,0,Math.PI/2,TAU]){
    const record=context(),clips=[clip(),clip([1,0,0,1,7,8])];
    drawScene(record.canvas,frame([curve(op,{transform:T.slice(),clips,sweep}),{op:'ellipse',x:1,y:2,width:3,height:4,fill:'#ff0000',stroke:'',stroke_width:1}]));
    assert.deepEqual(record.calls.filter(([name])=>name==='setTransform'),[['setTransform',...I],['setTransform',1,0,0,1,7,8],['setTransform',...T]]);
    assert.equal(record.calls.filter(([name])=>name==='clip').length,2);
    for(const paint of record.paints.slice(0,-1)){assert.deepEqual(paint.transform,T);assert.deepEqual(paint.clips,[I,[1,0,0,1,7,8]]);}
    assert.deepEqual(record.paints.at(-1).transform,I);assert.deepEqual(record.paints.at(-1).clips,[]);
    assert.equal(record.calls.filter(([name])=>name==='save').length,2);assert.equal(record.calls.filter(([name])=>name==='restore').length,2);
    assert.deepEqual(record.state,{transform:I,clips:[],fillStyle:'#000000',strokeStyle:'#000000',lineWidth:1});
  }
});

test('curve rendering restores matrix, clips and styles even when native drawing throws',()=>{
  for(const [op,failOn] of [['arc','ellipse'],['arc','stroke'],['sector','ellipse'],['sector','fill'],['sector','stroke']]){
    const record=context({failOn});
    assert.throws(()=>drawScene(record.canvas,frame([curve(op,{transform:T.slice(),clips:[clip()]})])),/native paint failed/);
    assert.deepEqual(record.calls.at(-1),['restore']);
    assert.deepEqual(record.state,{transform:I,clips:[],fillStyle:'#000000',strokeStyle:'#000000',lineWidth:1});
  }
});

test('arc and sector raw geometry, alpha and deep-copied state round-trip as inert history',()=>{
  const commands=[curve('arc',{start:100000,sweep:-TAU,transform:T.slice(),clips:[clip()]}),
    curve('sector',{start:-100000,sweep:100000,transform:T.slice(),clips:[clip(T)]}),curve('sector',{sweep:0}),
    curve('arc',{stroke:''}),{op:'ellipse',x:1,y:2,width:3,height:4,fill:'#ABCDEF',stroke:'',stroke_width:1}];
  const input={...frame(commands),running:true,handlers:['frame','mouse_down']},normalized=validateScene(input);
  normalized.commands[0].transform[4]=999;normalized.commands[0].clips[0].transform[4]=999;normalized.commands[0].clips[0].width=999;
  assert.equal(input.commands[0].transform[4],10);assert.equal(input.commands[0].clips[0].transform[4],0);assert.equal(input.commands[0].clips[0].width,70);
  const restored=parseBook(serializeBook(book(input))).cells[0];
  assert.equal(restored.historical,true);assert.equal(restored.outputs[0].scene.running,false);assert.deepEqual(restored.outputs[0].scene.handlers,[]);
  assert.deepEqual(restored.outputs[0].scene.commands,validateScene(input).commands);
  assert.equal(input.running,true);assert.deepEqual(input.handlers,['frame','mouse_down']);
  const replay=context(),live=context();drawScene(replay.canvas,restored.outputs[0].scene);drawScene(live.canvas,input);
  assert.deepEqual(replay.calls,live.calls);
});
