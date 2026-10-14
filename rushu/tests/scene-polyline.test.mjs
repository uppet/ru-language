import test from 'node:test';
import assert from 'node:assert/strict';
import {validateScene,drawScene,MAX_COMMANDS,MAX_FRAME_BYTES} from '../static/scene.mjs';
import {parseBook,serializeBook,newCell} from '../static/notebook.mjs';
import {createJSExecution} from '../static/js-execution.mjs';

const I=[1,0,0,1,0,0],T=[2,0,0,3,10,20];
const polyline=(extra={})=>({op:'polyline',points:[[10,20],[80,20],[80,60]],fill:'',stroke:'#ABCDEF80',stroke_width:3,...extra});
const frame=commands=>({canvas_id:'open-polylines',width:160,height:120,fps:30,running:false,handlers:[],commands});
const book=scene=>{const cell=newCell('code','');cell.outputs=[{type:'graphics',scene}];return {title:'折线',cells:[cell]};};
const clip=(transform=I)=>({x:5,y:6,width:70,height:50,transform:transform.slice()});
const bytes=value=>new TextEncoder().encode(JSON.stringify(value)).length;

function context({failOn,scoped=true}={}){
  const calls=[],paints=[],stack=[];
  let state={transform:I.slice(),clips:[],fillStyle:'#000000',strokeStyle:'#000000',lineWidth:1,lineJoin:'miter',lineCap:'butt',miterLimit:10};
  const copy=()=>({...state,transform:state.transform.slice(),clips:state.clips.map(matrix=>matrix.slice())});
  const initial=copy(),ctx={};
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
  return {calls,paints,initial,get state(){return state;},canvas:{getContext:()=>proxy}};
}
const pathCalls=calls=>calls.filter(([name])=>['beginPath','moveTo','lineTo','rect','ellipse','closePath','fill','stroke'].includes(name));
const pathFor=points=>[['beginPath'],['moveTo',...points[0]],...points.slice(1).map(point=>['lineTo',...point])];

test('polyline schema accepts 2 through 256 ordered bounded vertices and fractional widths',()=>{
  for(const points of [[[0,0],[1,1]],[[-100000,100000],[100000,-100000]],[[0.25,-0.5],[1.5,2.75]],Array.from({length:256},(_,i)=>[i,i%2])]){
    for(const stroke_width of [1,1.5,256]){
      const input=polyline({points,stroke_width,ignored:'never execute'}),output=validateScene(frame([input])).commands[0];
      assert.deepEqual(output,{op:'polyline',points,fill:'',stroke:'#abcdef80',stroke_width});
      assert.notEqual(output,input);assert.notEqual(output.points,points);
      for(let i=0;i<points.length;i++)assert.notEqual(output.points[i],points[i]);
      assert.equal(input.stroke,'#ABCDEF80');
    }
  }
});

test('polyline points must be a dense array with 2 through 256 exact coordinate pairs',()=>{
  const invalid=[undefined,null,true,false,0,'0,0;1,1',{},new Set([[0,0],[1,1]]),new Float64Array([0,0,1,1]),
    [],[[0,0]],Array(257).fill([0,0]),new Array(2),[[0,0],,[1,1]],
    [null,[1,1]],[undefined,[1,1]],[true,[1,1]],[0,[1,1]],['00',[1,1]],[{0:0,1:0,length:2},[1,1]],
    [new Float64Array([0,0]),[1,1]],[new Int32Array([0,0]),[1,1]],
    [[],[1,1]],[[0],[1,1]],[[0,0,0],[1,1]],[new Array(2),[1,1]],[[0,],[1,1]],[[,0],[1,1]]];
  for(const points of invalid)assert.throws(()=>validateScene(frame([polyline({points})])));
  const missing=polyline();delete missing.points;assert.throws(()=>validateScene(frame([missing])));
  const inheritedPair=Object.assign(new Array(2),{0:0});Object.setPrototypeOf(inheritedPair,{1:0});
  const inheritedPoints=Object.assign(new Array(2),{0:[0,0]});Object.setPrototypeOf(inheritedPoints,{1:[1,1]});
  for(const points of [[inheritedPair,[1,1]],inheritedPoints])assert.throws(()=>validateScene(frame([polyline({points})])));
});

test('both point-list operations reject holes even when inherited numeric slots fill them',()=>{
  for(const op of ['polygon','polyline']){
    const inheritedPair=Object.assign(new Array(2),{0:0});
    Object.setPrototypeOf(inheritedPair,Object.assign(Object.create(Array.prototype),{1:0}));
    const inheritedPoints=Object.assign(new Array(3),{0:[0,0],2:[2,2]});
    Object.setPrototypeOf(inheritedPoints,Object.assign(Object.create(Array.prototype),{1:[1,1]}));
    for(const points of [[[0,0],,[2,2]],[[0,0],new Array(2),[2,2]],
      [[0,0],inheritedPair,[2,2]],inheritedPoints]){
      assert.throws(()=>validateScene(frame([polyline({op,points})])));
      assert.throws(()=>serializeBook(book(frame([polyline({op,points})]))));
    }
  }
});

test('polyline vertex coordinates and width are required finite bounded numbers without coercion',()=>{
  const invalid=[undefined,null,true,false,'0',[],{},NaN,Infinity,-Infinity,100001,-100001];
  for(const value of invalid){
    for(const index of [0,1]){
      const points=[[0,0],[1,1]];points[1][index]=value;
      assert.throws(()=>validateScene(frame([polyline({points})])));
    }
    assert.throws(()=>validateScene(frame([polyline({stroke_width:value})])));
  }
  for(const stroke_width of [-1,0,0.5,257])assert.throws(()=>validateScene(frame([polyline({stroke_width})])));
  const missing=polyline();delete missing.stroke_width;assert.throws(()=>validateScene(frame([missing])));
});

test('polyline fill must be exactly empty and stroke accepts only empty or six/eight ASCII hex digits',()=>{
  const invalid=[undefined,null,true,0,[],{},new String(''),'red','transparent','url(https://example.invalid)','var(--color)',
    '#fff','#ffff','#12345','#1234567','#123456789','#GG000080','#１２３４５６',' #123456','#123456 ',
    '#123456\n','#12345680\r\n','#123456\0','#12345680\u2028'];
  for(const value of invalid){
    assert.throws(()=>validateScene(frame([polyline({stroke:value})])));
    assert.throws(()=>validateScene(frame([polyline({fill:value})])));
  }
  for(const fill of ['#000000','#00000000','#FFFFFF80'])assert.throws(()=>validateScene(frame([polyline({fill})])));
  for(const stroke of ['','#000000','#ABCDEF','#ABCDEF00','#ABCDEF80','#ABCDEFff']){
    const command=validateScene(frame([polyline({stroke})])).commands[0];
    assert.equal(command.fill,'');assert.equal(command.stroke,stroke.toLowerCase());
  }
  for(const key of ['fill','stroke']){const missing=polyline();delete missing[key];assert.throws(()=>validateScene(frame([missing])));}
});

test('polyline state follows strict existing transform/clip schemas and excludes text-only enums',()=>{
  const patches=[{transform:null},{transform:new Float64Array(I)},{transform:[1,0,0,1,0]},
    {transform:[1,0,0,1,Infinity,0]},{transform:[1,0,0,1,'0',0]},{transform:new Array(6)},
    {clips:null},{clips:Array(33).fill(clip())},{clips:new Array(1)},{clips:[null]},
    {clips:[{...clip(),width:-1}]},{clips:[{...clip(),transform:null}]},
    {align:'left'},{align:undefined},{baseline:'top'},{baseline:undefined}];
  for(const patch of patches)assert.throws(()=>validateScene(frame([polyline(patch)])));
  const boundary=polyline({transform:[100000,0,0,0,-100000,0],clips:Array.from({length:32},()=>clip())});
  assert.doesNotThrow(()=>validateScene(frame([boundary])));
});

test('malformed live and saved polylines fail atomically before any canvas effects',()=>{
  const patches=[{points:undefined},{points:[[0,0]]},{points:Array(257).fill([0,0])},
    {points:new Array(2)},{points:[[0,0],new Array(2)]},{points:[[0,0],new Float64Array([1,1])]},
    {points:[[0,0],[Infinity,0]]},{points:[[0,0],[100001,0]]},{points:[[0,0],['1',0]]},
    {stroke_width:0},{stroke:'url(x)'},{fill:'#000000'},{op:'constructor'},{op:'__proto__'},
    {transform:[1,0,0,1,0,100001]},{clips:[{...clip(),height:-1}]},{align:'left'}];
  const raw=JSON.parse(serializeBook(book(frame([polyline()]))));
  for(const patch of patches){
    const scene=frame([{op:'background',color:'#ffffff'},polyline(),polyline(patch)]),effects=[];
    const before=structuredClone(scene);
    const canvas={set width(value){effects.push(['width',value]);},set height(value){effects.push(['height',value]);},getContext(){effects.push(['context']);throw new Error('must not touch canvas');}};
    assert.throws(()=>drawScene(canvas,scene));assert.deepEqual(effects,[]);assert.deepEqual(scene,before);
    assert.throws(()=>serializeBook(book(scene)));assert.deepEqual(scene,before);
    raw.cells[0].outputs[0].scene=scene;assert.throws(()=>parseBook(JSON.stringify(raw)));
  }
});

function arrayRecordScenes(){
  const scenes=[Object.assign([],frame([polyline()]))];
  const commands=[polyline(),{...polyline(),op:'polygon'},{op:'background',color:'#ffffff'},
    {op:'line',x1:0,y1:0,x2:1,y2:1,width:1,color:'#000000'},
    {op:'rect',x:0,y:0,width:1,height:1,fill:'#ffffff',stroke:'',stroke_width:1},
    {op:'ellipse',x:0,y:0,width:1,height:1,fill:'#ffffff',stroke:'',stroke_width:1},
    {op:'arc',x:0,y:0,width:1,height:1,start:0,sweep:1,fill:'',stroke:'#000000',stroke_width:1},
    {op:'sector',x:0,y:0,width:1,height:1,start:0,sweep:1,fill:'#ffffff',stroke:'',stroke_width:1},
    {op:'text',x:0,y:0,text:'如',color:'#000000',size:12}];
  for(const command of commands){
    scenes.push(frame([Object.assign([],command)]));
    scenes.push(frame([{...command,clips:[Object.assign([],clip())]}]));
  }
  return scenes;
}

test('scene, command and clip records reject arrays with otherwise valid own properties',()=>{
  for(const scene of arrayRecordScenes()){
    const effects=[],canvas={set width(value){effects.push(['width',value]);},set height(value){effects.push(['height',value]);},getContext(){effects.push(['context']);}};
    const clone=structuredClone(scene);
    assert.throws(()=>validateScene(clone));assert.throws(()=>drawScene(canvas,clone));assert.deepEqual(effects,[]);
    assert.throws(()=>serializeBook(book(clone)));
    const raw=JSON.parse(serializeBook(book(frame([]))));raw.cells[0].outputs[0].scene=clone;
    assert.throws(()=>parseBook(JSON.stringify(raw)));
  }
});

test('array-shaped point-list commands cannot hide an oversized frame from JSON byte accounting',()=>{
  for(const op of ['polygon','polyline']){
    const command=polyline({op,points:Array.from({length:256},()=>[-100000,100000])});
    const canonical=frame(Array(100).fill(command)),hidden=frame(Array(100).fill(Object.assign([],command)));
    assert.ok(bytes(canonical)>MAX_FRAME_BYTES);assert.ok(bytes(hidden)<1000);
    assert.ok(Array.isArray(structuredClone(hidden).commands[0]));
    assert.deepEqual(structuredClone(hidden).commands[0].points,command.points);
    assert.throws(()=>validateScene(hidden),/指令无效/);
    assert.throws(()=>serializeBook(book(hidden)),/指令无效/);
    const record=context();assert.throws(()=>drawScene(record.canvas,hidden));assert.deepEqual(record.calls,[]);
  }
});

test('canonical snapshots also enforce frame bytes when object inheritance hides input fields',()=>{
  const command=polyline({points:Array.from({length:256},()=>[-100000,100000])});
  const scene=Object.create(frame(Array(100).fill(command)));
  assert.equal(bytes(scene),2);assert.throws(()=>validateScene(scene),/帧过大/);
  assert.throws(()=>serializeBook(book(scene)),/帧过大/);
  const record=context();assert.throws(()=>drawScene(record.canvas,scene));assert.deepEqual(record.calls,[]);
});

test('worker batches reject array-shaped graphics atomically before releasing earlier valid events',async()=>{
  const identity={cell_id:'polyline-cell',execution_count:1,generation:1,token:'polyline-worker'};
  const large=polyline({points:Array.from({length:256},()=>[-100000,100000])});
  for(const scene of [...arrayRecordScenes(),frame(Array(100).fill(Object.assign([],large)))]){
    const worker={postMessage(){},terminate(){this.terminated=true;}},events=[],fatal=[];
    const run=createJSExecution({javascript:'export default ()=>({dispatch(){}})',identity,
      onEvent:event=>events.push(event),onFatal:event=>fatal.push(event),workerFactory:()=>worker});
    const message={identity,serial:0,type:'batch',events:[{type:'output',stream:'stdout',text:'must stay private'},
      {...frame([polyline()]),type:'graphics'},Object.assign(scene,{type:'graphics'})]};
    worker.onmessage({data:structuredClone(message)});
    await assert.rejects(run.ready);
    assert.deepEqual(events,[]);assert.equal(fatal.length,1);assert.equal(worker.terminated,true);assert.equal(run.active,false);
  }
});

test('polyline does not weaken the existing string-only operation guard',()=>{
  for(const op of [undefined,null,true,0,{},[],['polyline'],[['polyline']],['polygon'],['text']]){
    const command=polyline({op,text:'untrusted',color:'#000000',size:12,x:0,y:0});
    assert.throws(()=>validateScene(frame([command])));assert.throws(()=>serializeBook(book(frame([command]))));
    const raw=JSON.parse(serializeBook(book(frame([polyline()]))));raw.cells[0].outputs[0].scene.commands=[command];
    assert.throws(()=>parseBook(JSON.stringify(raw)));
  }
  let coercions=0;
  const coercible={toString(){coercions++;return 'polyline';},[Symbol.toPrimitive](){coercions++;return 'polyline';}};
  for(const op of [new String('polyline'),coercible]){
    assert.throws(()=>validateScene(frame([polyline({op})])));
    assert.throws(()=>serializeBook(book(frame([polyline({op})]))));
  }
  assert.equal(coercions,0);
});

test('validation deep-copies vertices, matrices and clip geometry in both directions',()=>{
  const shared=[10,20],input=frame([polyline({points:[shared,shared,[80,60]],transform:T.slice(),clips:[clip()]})]);
  const output=validateScene(input),expected=structuredClone(output);
  assert.notEqual(output.commands[0].points[0],output.commands[0].points[1]);
  shared[0]=999;input.commands[0].points.push([4,5]);input.commands[0].transform[4]=999;
  input.commands[0].clips[0].width=999;input.commands[0].clips[0].transform[4]=999;
  assert.deepEqual(output,expected);
  const untouched=structuredClone(input);
  output.commands[0].points[1][1]=777;output.commands[0].transform[5]=777;
  output.commands[0].clips[0].height=777;output.commands[0].clips[0].transform[5]=777;
  assert.deepEqual(input,untouched);
});

test('polyline uses one native open path and one stroke without fill, closure or per-segment alpha',()=>{
  for(const points of [[[10,20],[80,20]],[[10,20],[80,20],[80,60]],[[10,20],[80,20],[80,60],[10,20]]]){
    for(const stroke of ['#ABCDEF','#ABCDEF80','#ABCDEF00'])for(const scoped of [false,true]){
      const record=context({scoped}),scene=drawScene(record.canvas,frame([polyline({points,stroke})]));
      assert.deepEqual(pathCalls(record.calls),[...pathFor(points),['stroke']]);
      assert.equal(record.paints.length,1);assert.equal(record.paints[0].strokeStyle,stroke.toLowerCase());
      assert.equal(record.paints[0].lineWidth,3);assert.equal(record.paints[0].lineJoin,'miter');
      assert.equal(record.paints[0].lineCap,'butt');assert.equal(record.paints[0].miterLimit,10);
      assert.equal(record.calls.some(([name,key])=>name==='set'&&['lineJoin','lineCap','miterLimit'].includes(key)),false);
      assert.deepEqual(scene.commands[0].points,points);
    }
  }
});

test('repeated and all-identical vertices retain every native segment without special degeneration',()=>{
  for(const points of [[[20,20],[20,20]],[[10,20],[10,20],[80,60],[80,60]],Array.from({length:256},()=>[20,20])]){
    const record=context(),scene=drawScene(record.canvas,frame([polyline({points})]));
    assert.deepEqual(pathCalls(record.calls),[...pathFor(points),['stroke']]);
    assert.deepEqual(scene.commands[0].points,points);assert.equal(record.paints.length,1);
    const restored=parseBook(serializeBook(book(scene))).cells[0].outputs[0].scene;
    assert.deepEqual(restored.commands,scene.commands);
  }
});

test('empty stroke retains geometry, command count and bytes while skipping native paint',()=>{
  const points=[[20,20],[20,20],[20,20]],command=polyline({points,stroke:''}),record=context();
  const scene=drawScene(record.canvas,frame([command]));
  assert.equal(scene.commands.length,1);assert.deepEqual(scene.commands[0],command);
  assert.deepEqual(pathCalls(record.calls),pathFor(points));assert.deepEqual(record.paints,[]);
  const restored=parseBook(serializeBook(book(scene))).cells[0].outputs[0].scene;
  assert.deepEqual(restored.commands,[command]);assert.equal(bytes(restored),bytes(scene));
});

test('polyline clips use snapshot matrices then its own transform and never leak to later drawing',()=>{
  for(const stroke of ['','#12345680']){
    const record=context(),clips=[clip(),clip([1,0,0,1,7,8])];
    drawScene(record.canvas,frame([polyline({transform:T.slice(),clips,stroke}),
      {op:'rect',x:1,y:2,width:3,height:4,fill:'#ff0000',stroke:'',stroke_width:1}]));
    assert.deepEqual(record.calls.filter(([name])=>name==='setTransform'),[['setTransform',...I],['setTransform',1,0,0,1,7,8],['setTransform',...T]]);
    assert.equal(record.calls.filter(([name])=>name==='clip').length,2);
    for(const paint of record.paints.slice(0,-1)){assert.deepEqual(paint.transform,T);assert.deepEqual(paint.clips,[I,[1,0,0,1,7,8]]);}
    assert.deepEqual(record.paints.at(-1).transform,I);assert.deepEqual(record.paints.at(-1).clips,[]);
    assert.equal(record.calls.filter(([name])=>name==='save').length,2);assert.equal(record.calls.filter(([name])=>name==='restore').length,2);
    assert.deepEqual(record.state,record.initial);
  }
  const record=context();drawScene(record.canvas,frame([polyline({clips:[clip(T)]})]));
  assert.deepEqual(record.calls.filter(([name])=>name==='setTransform'),[['setTransform',...T],['setTransform',...I]]);
  assert.deepEqual(record.paints[0].transform,I);assert.deepEqual(record.paints[0].clips,[T]);
});

test('polyline rendering restores native state even if path, clipping, transform or stroke throws',()=>{
  for(const failOn of ['beginPath','moveTo','lineTo','setTransform','clip','stroke']){
    const record=context({failOn});
    assert.throws(()=>drawScene(record.canvas,frame([polyline({transform:T.slice(),clips:[clip()]})])),/native paint failed/);
    assert.deepEqual(record.calls.at(-1),['restore']);assert.deepEqual(record.state,record.initial);
  }
});

test('polyline snapshots round-trip with alpha and state as inert history alongside legacy commands',()=>{
  const commands=[{op:'background',color:'#ffffff'},polyline({transform:T.slice(),clips:[clip()]}),
    polyline({points:[[20,20],[20,20]],stroke:''}),polyline({stroke:'#FFFFFF00'}),
    {op:'polygon',points:[[0,0],[10,0],[0,10]],fill:'#FF000080',stroke:'#000000',stroke_width:1},
    {op:'line',x1:0,y1:0,x2:10,y2:10,color:'#000000',width:1}];
  const input={...frame(commands),running:true,handlers:['frame','mouse_down']},before=structuredClone(input);
  const text=serializeBook(book(input)),raw=JSON.parse(text);raw.cells[0].outputs[0].scene=input;
  for(const restored of [parseBook(text),parseBook(JSON.stringify(raw))]){
    const cell=restored.cells[0],scene=cell.outputs[0].scene;
    assert.equal(cell.historical,true);assert.equal(scene.running,false);assert.deepEqual(scene.handlers,[]);
    assert.deepEqual(scene.commands,validateScene(input).commands);
    const replay=context(),live=context();drawScene(replay.canvas,scene);drawScene(live.canvas,input);
    assert.deepEqual(replay.calls,live.calls);
  }
  assert.deepEqual(input,before);
});

test('polyline keeps the 2048-command limit even for invisible zero-length paths',()=>{
  const command=polyline({points:[[0,0],[0,0]],stroke:''}),scene=frame(Array(MAX_COMMANDS).fill(command));
  assert.ok(bytes(scene)<MAX_FRAME_BYTES);assert.equal(validateScene(scene).commands.length,MAX_COMMANDS);
  assert.equal(parseBook(serializeBook(book(scene))).cells[0].outputs[0].scene.commands.length,MAX_COMMANDS);
  scene.commands.push(command);
  assert.throws(()=>validateScene(scene),/指令过多/);assert.throws(()=>serializeBook(book(scene)),/指令过多/);
  const raw=JSON.parse(serializeBook(book(frame([]))));raw.cells[0].outputs[0].scene=scene;
  assert.throws(()=>parseBook(JSON.stringify(raw)),/指令过多/);
});

test('polyline retains the exact UTF-8 frame byte boundary before dropping unknown fields',()=>{
  const scene=frame([polyline({padding:''})]);scene.commands[0].padding='x'.repeat(MAX_FRAME_BYTES-bytes(scene));
  assert.equal(bytes(scene),MAX_FRAME_BYTES);assert.equal(validateScene(scene).commands.length,1);
  assert.doesNotThrow(()=>serializeBook(book(scene)));
  scene.commands[0].padding+='x';
  assert.throws(()=>validateScene(scene),/帧过大/);assert.throws(()=>serializeBook(book(scene)),/帧过大/);
  const raw=JSON.parse(serializeBook(book(frame([]))));raw.cells[0].outputs[0].scene=scene;
  assert.throws(()=>parseBook(JSON.stringify(raw)),/帧过大/);
  scene.commands[0].padding=scene.commands[0].padding.slice(0,-2)+'如';
  assert.equal(bytes(scene),MAX_FRAME_BYTES+2);assert.throws(()=>validateScene(scene),/帧过大/);
});

test('large repeated invisible point arrays consume the byte budget without command exemptions',()=>{
  const command=polyline({points:Array.from({length:256},()=>[100000,-100000]),stroke:''});
  const scene=frame([command]);
  while(bytes(scene)<=MAX_FRAME_BYTES)scene.commands.push(command);
  assert.ok(scene.commands.length<MAX_COMMANDS);
  assert.throws(()=>validateScene(scene),/帧过大/);assert.throws(()=>serializeBook(book(scene)),/帧过大/);
  scene.commands.pop();assert.equal(validateScene(scene).commands.length,scene.commands.length);
  assert.doesNotThrow(()=>serializeBook(book(scene)));
});

test('existing polygons still require three vertices and keep their native closed fill/stroke path',()=>{
  assert.throws(()=>validateScene(frame([{...polyline({points:[[0,0],[1,1]]}),op:'polygon'}])));
  const command={...polyline({fill:'#FF000080'}),op:'polygon'},record=context();
  drawScene(record.canvas,frame([command]));
  assert.deepEqual(pathCalls(record.calls),[...pathFor(command.points),['closePath'],['fill'],['stroke']]);
});
