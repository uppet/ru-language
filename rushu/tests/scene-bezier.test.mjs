import test from 'node:test';
import assert from 'node:assert/strict';
import {validateScene,drawScene,MAX_COMMANDS,MAX_FRAME_BYTES} from '../static/scene.mjs';
import {parseBook,serializeBook,newCell} from '../static/notebook.mjs';
import {createJSExecution} from '../static/js-execution.mjs';

const I=[1,0,0,1,0,0],T=[2,0,0,3,10,20];
const coordinates=['x1','y1','cx1','cy1','cx2','cy2','x2','y2'];
const bezier=(extra={})=>({op:'bezier',x1:10,y1:20,cx1:30,cy1:90,cx2:60,cy2:-20,x2:80,y2:60,fill:'',stroke:'#ABCDEF80',stroke_width:3,...extra});
const frame=commands=>({canvas_id:'native-beziers',width:160,height:120,fps:30,running:false,handlers:[],commands});
const book=scene=>{const cell=newCell('code','');cell.outputs=[{type:'graphics',scene}];return {title:'贝塞尔',cells:[cell]};};
const clip=(transform=I)=>({x:5,y:6,width:70,height:50,transform:transform.slice()});
const bytes=value=>new TextEncoder().encode(JSON.stringify(value)).length;
const saved=scene=>JSON.stringify({format:'rushu-notebook',version:1,title:'贝塞尔',cells:[{id:'bezier-cell',type:'code',source:'',outputs:[{type:'graphics',scene}]}]});

function context({failOn,scoped=true}={}){
  const calls=[],paints=[],stack=[];
  let state={transform:I.slice(),clips:[],fillStyle:'#000000',strokeStyle:'#000000',lineWidth:1,lineJoin:'miter',lineCap:'butt',miterLimit:10};
  const copy=()=>({...state,transform:state.transform.slice(),clips:state.clips.map(matrix=>matrix.slice())});
  const initial=copy(),ctx={};
  for(const name of ['beginPath','moveTo','lineTo','bezierCurveTo','rect','ellipse','closePath','fill','stroke','fillText','clearRect','fillRect','setTransform','clip']){
    ctx[name]=(...args)=>{
      calls.push([name,...args]);
      if(name===failOn)throw new Error('native paint failed');
      if(name==='setTransform')state.transform=args;
      if(name==='clip')state.clips.push(state.transform.slice());
      if(['fill','stroke','fillRect','fillText'].includes(name))paints.push({name,...copy()});
    };
  }
  if(scoped){
    ctx.save=()=>{calls.push(['save']);stack.push(copy());};
    ctx.restore=()=>{calls.push(['restore']);state=stack.pop();};
  }
  const proxy=new Proxy(ctx,{set:(_,key,value)=>{calls.push(['set',key,value]);state[key]=value;return true;}});
  return {calls,paints,initial,get state(){return state;},canvas:{getContext:()=>proxy}};
}
const pathCalls=calls=>calls.filter(([name])=>['beginPath','moveTo','lineTo','bezierCurveTo','rect','ellipse','closePath','fill','stroke'].includes(name));
const pathFor=c=>[['beginPath'],['moveTo',c.x1,c.y1],['bezierCurveTo',c.cx1,c.cy1,c.cx2,c.cy2,c.x2,c.y2]];

function rejectLiveAndHistory(scene){
  const before=structuredClone(scene),effects=[];
  const canvas={set width(value){effects.push(['width',value]);},set height(value){effects.push(['height',value]);},getContext(){effects.push(['context']);throw new Error('must not touch canvas');}};
  assert.throws(()=>validateScene(scene));
  assert.throws(()=>drawScene(canvas,scene));assert.deepEqual(effects,[]);assert.deepEqual(scene,before);
  assert.throws(()=>serializeBook(book(scene)));assert.deepEqual(scene,before);
  assert.throws(()=>parseBook(saved(scene)));
}

test('bezier schema preserves eight ordered bounded coordinates and fractional widths',()=>{
  for(const value of [-100000,-0,0,0.25,100000])for(const stroke_width of [1,1.5,256]){
    const geometry=Object.fromEntries(coordinates.map(key=>[key,value]));
    const input=bezier({...geometry,stroke_width,ignored:'never execute'}),output=validateScene(frame([input])).commands[0];
    assert.deepEqual(output,{op:'bezier',...geometry,fill:'',stroke:'#abcdef80',stroke_width});
    assert.notEqual(output,input);assert.equal(input.stroke,'#ABCDEF80');
    assert.equal(Object.hasOwn(output,'transform'),false);assert.equal(Object.hasOwn(output,'clips'),false);
    for(const key of coordinates)assert.equal(Object.is(output[key],value),true);
  }
});

test('every bezier coordinate and width rejects missing, wrong-type, non-finite and out-of-range values',()=>{
  const invalid=[undefined,null,true,false,'0',[],{},NaN,Infinity,-Infinity,100001,-100001];
  for(const key of [...coordinates,'stroke_width']){
    for(const value of invalid)rejectLiveAndHistory(frame([bezier(),bezier({[key]:value})]));
    const missing=bezier();delete missing[key];rejectLiveAndHistory(frame([bezier(),missing]));
    assert.throws(()=>validateScene(frame([bezier({[key]:new Number(0)})])));
  }
  for(const stroke_width of [-1,0,0.5,257])rejectLiveAndHistory(frame([bezier({stroke_width})]));
});

test('bezier numeric fields never invoke number coercion',()=>{
  let coercions=0;
  const value={valueOf(){coercions++;return 0;},toString(){coercions++;return '0';},[Symbol.toPrimitive](){coercions++;return 0;}};
  for(const key of [...coordinates,'stroke_width']){
    assert.throws(()=>validateScene(frame([bezier({[key]:value})])));
    assert.throws(()=>serializeBook(book(frame([bezier({[key]:value})]))));
  }
  assert.equal(coercions,0);
});

test('bezier fill is exactly empty and stroke accepts only empty or six/eight ASCII hex digits',()=>{
  const invalid=[undefined,null,true,false,0,[],{},'red','transparent','url(https://example.invalid)','var(--color)',
    '#fff','#ffff','#12345','#1234567','#123456789','#GG000080','#１２３４５６',' #123456','#123456 ',
    '#123456\n','#12345680\r\n','#123456\0','#12345680\u2028'];
  for(const value of invalid)for(const key of ['fill','stroke'])rejectLiveAndHistory(frame([bezier({[key]:value})]));
  for(const fill of ['#000000','#00000000','#FFFFFF80'])rejectLiveAndHistory(frame([bezier({fill})]));
  for(const key of ['fill','stroke']){
    const missing=bezier();delete missing[key];rejectLiveAndHistory(frame([missing]));
    assert.throws(()=>validateScene(frame([bezier({[key]:new String('')})])));
  }
  for(const stroke of ['','#000000','#ABCDEF','#ABCDEF00','#ABCDEF80','#ABCDEFff']){
    const output=validateScene(frame([bezier({stroke})])).commands[0];
    assert.equal(output.fill,'');assert.equal(output.stroke,stroke.toLowerCase());
  }
});

test('bezier state retains existing strict transform and clip schemas and excludes text enums',()=>{
  const patches=[{transform:null},{transform:new Float64Array(I)},{transform:[1,0,0,1,0]},
    {transform:[1,0,0,1,Infinity,0]},{transform:[1,0,0,1,'0',0]},{transform:new Array(6)},
    {clips:null},{clips:Array(33).fill(clip())},{clips:new Array(1)},{clips:[null]},
    {clips:[{...clip(),width:-1}]},{clips:[{...clip(),height:-1}]},{clips:[{...clip(),transform:null}]},
    {clips:[{...clip(),x:NaN}]},{clips:[{...clip(),y:100001}]},
    {align:'left'},{align:undefined},{baseline:'top'},{baseline:undefined}];
  for(const patch of patches){
    // JSON omits undefined text-only fields, so test that in-memory restriction separately.
    if(Object.values(patch).includes(undefined))assert.throws(()=>validateScene(frame([bezier(patch)])));
    else rejectLiveAndHistory(frame([bezier(patch)]));
  }
  const boundary=bezier({transform:[100000,0,0,0,-100000,0],clips:Array.from({length:32},()=>clip())});
  assert.doesNotThrow(()=>validateScene(frame([boundary])));
});

test('bezier validates the whole scene before canvas resizing, context access or earlier painting',()=>{
  const patches=[{cx1:null},{cy1:NaN},{cx2:Infinity},{cy2:100001},{x2:'1'},{stroke_width:0},
    {stroke:'url(x)'},{fill:'#00000080'},{op:'constructor'},{op:'__proto__'},
    {transform:[1,0,0,1,0,100001]},{clips:[{...clip(),height:-1}]},{align:'left'}];
  for(const patch of patches)rejectLiveAndHistory(frame([{op:'background',color:'#ffffff'},bezier(),bezier(patch)]));
});

test('bezier retains strict object records for scenes, commands and clipping rectangles',()=>{
  for(const scene of [Object.assign([],frame([bezier()])),frame([Object.assign([],bezier())]),
    frame([bezier({clips:[Object.assign([],clip())]})])])rejectLiveAndHistory(scene);
  for(const command of [undefined,null,false,0,'bezier',[],new Array(1)])rejectLiveAndHistory(frame([command]));
});

test('bezier retains the string-only operation guard without coercing executable property keys',()=>{
  for(const op of [undefined,null,true,0,{},[],['bezier'],[['bezier']],['polyline'],['text'],'constructor','__proto__','quadratic','path']){
    const command=bezier({op,text:'untrusted',color:'#000000',size:12,x:0,y:0});
    rejectLiveAndHistory(frame([command]));
  }
  let coercions=0;
  const coercible={toString(){coercions++;return 'bezier';},[Symbol.toPrimitive](){coercions++;return 'bezier';}};
  for(const op of [new String('bezier'),coercible]){
    assert.throws(()=>validateScene(frame([bezier({op})])));
    assert.throws(()=>serializeBook(book(frame([bezier({op})]))));
  }
  assert.equal(coercions,0);
});

test('bezier validation independently snapshots geometry, styles, matrices and clips in both directions',()=>{
  const sharedClip=clip(),command=bezier({transform:T.slice(),clips:[sharedClip,sharedClip]});
  const input=frame([command,command]),output=validateScene(input),expected=structuredClone(output);
  assert.notEqual(output.commands[0],output.commands[1]);
  assert.notEqual(output.commands[0].transform,output.commands[1].transform);
  assert.notEqual(output.commands[0].clips,output.commands[1].clips);
  assert.notEqual(output.commands[0].clips[0],output.commands[0].clips[1]);
  assert.notEqual(output.commands[0].clips[0].transform,output.commands[0].clips[1].transform);
  for(const key of coordinates)command[key]=999;
  command.stroke='#000000';command.stroke_width=99;command.transform[4]=999;
  sharedClip.width=999;sharedClip.transform[4]=999;command.clips.push(clip());input.handlers.push('frame');
  assert.deepEqual(output,expected);
  const untouched=structuredClone(input);
  for(const key of coordinates)output.commands[0][key]=777;
  output.commands[0].stroke='#ffffff';output.commands[0].stroke_width=77;output.commands[0].transform[5]=777;
  output.commands[0].clips[0].height=777;output.commands[0].clips[0].transform[5]=777;
  assert.deepEqual(input,untouched);assert.deepEqual(output.commands[1],expected.commands[1]);
});

test('bezier uses one native open cubic and one stroke with native alpha and default cap/join',()=>{
  for(const stroke of ['#ABCDEF','#ABCDEF80','#ABCDEF00'])for(const scoped of [false,true]){
    const command=bezier({stroke}),record=context({scoped});
    const scene=drawScene(record.canvas,frame([command]));
    assert.deepEqual(pathCalls(record.calls),[...pathFor(command),['stroke']]);
    assert.equal(record.paints.length,1);assert.equal(record.paints[0].strokeStyle,stroke.toLowerCase());
    assert.equal(record.paints[0].lineWidth,3);assert.equal(record.paints[0].lineJoin,'miter');
    assert.equal(record.paints[0].lineCap,'butt');assert.equal(record.paints[0].miterLimit,10);
    assert.equal(record.calls.some(([name,key])=>name==='set'&&['lineJoin','lineCap','miterLimit','globalAlpha'].includes(key)),false);
    assert.deepEqual(scene.commands[0],{...command,stroke:stroke.toLowerCase()});
  }
});

test('coincident, collinear, reversed and looping cubics preserve native geometry without sampling',()=>{
  const patches=[Object.fromEntries(coordinates.map(key=>[key,20])),
    {x1:10,y1:20,cx1:30,cy1:20,cx2:60,cy2:20,x2:80,y2:20},
    {x1:80,y1:60,cx1:60,cy1:-20,cx2:30,cy2:90,x2:10,y2:20},
    {x1:80,y1:60,cx1:-100000,cy1:100000,cx2:100000,cy2:-100000,x2:80,y2:60},
    {cx1:10,cy1:20,cx2:80,cy2:60}];
  for(const patch of patches){
    const command=bezier(patch),record=context(),scene=drawScene(record.canvas,frame([command]));
    assert.deepEqual(pathCalls(record.calls),[...pathFor(command),['stroke']]);
    assert.equal(record.paints.length,1);assert.equal(scene.commands.length,1);
    const restored=parseBook(serializeBook(book(scene))).cells[0].outputs[0].scene;
    assert.deepEqual(restored.commands,scene.commands);
  }
});

test('empty bezier stroke retains its full native path, snapshot and byte cost without painting',()=>{
  for(const patch of [{},Object.fromEntries(coordinates.map(key=>[key,0]))]){
    const command=bezier({...patch,stroke:''}),record=context(),scene=drawScene(record.canvas,frame([command]));
    assert.deepEqual(pathCalls(record.calls),pathFor(command));assert.deepEqual(record.paints,[]);
    assert.deepEqual(scene.commands,[command]);
    const restored=parseBook(serializeBook(book(scene))).cells[0].outputs[0].scene;
    assert.deepEqual(restored.commands,[command]);assert.equal(bytes(restored),bytes(scene));
  }
});

test('bezier clips use snapshot matrices before its transform and never leak state to later drawing',()=>{
  for(const stroke of ['','#12345680']){
    const record=context(),clips=[clip(),clip([1,0,0,1,7,8])];
    drawScene(record.canvas,frame([bezier({transform:T.slice(),clips,stroke}),
      {op:'rect',x:1,y:2,width:3,height:4,fill:'#ff0000',stroke:'',stroke_width:1}]));
    assert.deepEqual(record.calls.filter(([name])=>name==='setTransform'),[['setTransform',...I],['setTransform',1,0,0,1,7,8],['setTransform',...T]]);
    assert.equal(record.calls.filter(([name])=>name==='clip').length,2);
    for(const paint of record.paints.slice(0,-1)){assert.deepEqual(paint.transform,T);assert.deepEqual(paint.clips,[I,[1,0,0,1,7,8]]);}
    assert.deepEqual(record.paints.at(-1).transform,I);assert.deepEqual(record.paints.at(-1).clips,[]);
    assert.equal(record.calls.filter(([name])=>name==='save').length,2);assert.equal(record.calls.filter(([name])=>name==='restore').length,2);
    assert.deepEqual(record.state,record.initial);
  }
  const record=context();drawScene(record.canvas,frame([bezier({clips:[clip(T)]})]));
  assert.deepEqual(record.calls.filter(([name])=>name==='setTransform'),[['setTransform',...T],['setTransform',...I]]);
  assert.deepEqual(record.paints[0].transform,I);assert.deepEqual(record.paints[0].clips,[T]);
});

test('bezier rendering restores native state if path, clipping, transform or stroke throws',()=>{
  for(const failOn of ['beginPath','moveTo','bezierCurveTo','setTransform','clip','stroke']){
    const record=context({failOn});
    assert.throws(()=>drawScene(record.canvas,frame([bezier({transform:T.slice(),clips:[clip()]})])),/native paint failed/);
    assert.deepEqual(record.calls.at(-1),['restore']);assert.deepEqual(record.state,record.initial);
  }
});

const legacyCommands=()=>[
  {op:'background',color:'#ffffff'},
  {op:'line',x1:0,y1:0,x2:10,y2:10,color:'#00000080',width:1},
  {op:'rect',x:1,y:2,width:3,height:4,fill:'#ff000080',stroke:'',stroke_width:1},
  {op:'ellipse',x:1,y:2,width:3,height:4,fill:'',stroke:'#000000',stroke_width:1},
  {op:'arc',x:1,y:2,width:3,height:4,start:0,sweep:1,fill:'',stroke:'#000000',stroke_width:1},
  {op:'sector',x:1,y:2,width:3,height:4,start:0,sweep:1,fill:'#ffffff',stroke:'',stroke_width:1},
  {op:'polygon',points:[[0,0],[10,0],[0,10]],fill:'#FF000080',stroke:'#000000',stroke_width:1},
  {op:'polyline',points:[[0,0],[10,0],[0,10]],fill:'',stroke:'#00000080',stroke_width:1},
  {op:'text',x:0,y:0,text:'如',color:'#000000',size:12}];

test('bezier snapshots round-trip alongside every legacy operation as inert history',()=>{
  const commands=[...legacyCommands(),bezier({transform:T.slice(),clips:[clip()]}),
    bezier({stroke:''}),bezier({stroke:'#FFFFFF00'})];
  const input={...frame(commands),running:true,handlers:['frame','mouse_down']},before=structuredClone(input);
  for(const restored of [parseBook(serializeBook(book(input))),parseBook(saved(input))]){
    const cell=restored.cells[0],scene=cell.outputs[0].scene;
    assert.equal(cell.historical,true);assert.equal(scene.running,false);assert.deepEqual(scene.handlers,[]);
    assert.deepEqual(scene.commands,validateScene(input).commands);
    const replay=context(),live=context();drawScene(replay.canvas,scene);drawScene(live.canvas,input);
    assert.deepEqual(replay.calls,live.calls);
  }
  assert.deepEqual(input,before);
});

test('legacy operations retain their native paths when no bezier context method exists',()=>{
  const record=context(),ctx=record.canvas.getContext();delete ctx.bezierCurveTo;
  assert.doesNotThrow(()=>drawScene(record.canvas,frame(legacyCommands())));
  assert.equal(record.calls.some(([name])=>name==='bezierCurveTo'),false);
  const paths=pathCalls(record.calls);
  assert.equal(paths.filter(([name])=>name==='closePath').length,2);
  assert.equal(paths.filter(([name])=>name==='ellipse').length,3);
});

test('2048 invisible coincident beziers still reach the command limit without exemptions',()=>{
  const command=bezier({...Object.fromEntries(coordinates.map(key=>[key,0])),stroke:'',stroke_width:1});
  const scene=frame(Array(MAX_COMMANDS).fill(command));
  assert.ok(bytes(scene)<MAX_FRAME_BYTES);assert.equal(validateScene(scene).commands.length,MAX_COMMANDS);
  assert.equal(parseBook(serializeBook(book(scene))).cells[0].outputs[0].scene.commands.length,MAX_COMMANDS);
  scene.commands.push(command);rejectLiveAndHistory(scene);
  assert.throws(()=>validateScene(scene),/指令过多/);
});

test('bezier raw frames retain the exact UTF-8 byte boundary before unknown fields are dropped',()=>{
  const scene=frame([bezier({padding:''})]);scene.commands[0].padding='x'.repeat(MAX_FRAME_BYTES-bytes(scene));
  assert.equal(bytes(scene),MAX_FRAME_BYTES);assert.equal(validateScene(scene).commands.length,1);
  assert.doesNotThrow(()=>serializeBook(book(scene)));assert.doesNotThrow(()=>parseBook(saved(scene)));
  scene.commands[0].padding+='x';rejectLiveAndHistory(scene);assert.throws(()=>validateScene(scene),/帧过大/);
  scene.commands[0].padding=scene.commands[0].padding.slice(0,-2)+'如';
  assert.equal(bytes(scene),MAX_FRAME_BYTES+2);rejectLiveAndHistory(scene);
});

test('invisible boundary-coordinate beziers consume the frame byte budget below 2048 commands',()=>{
  const command=bezier({...Object.fromEntries(coordinates.map(key=>[key,-100000])),stroke:''}),scene=frame([command]);
  const count=Math.floor((MAX_FRAME_BYTES-bytes(frame([]))+1)/(bytes(command)+1));
  scene.commands=Array(count).fill(command);
  assert.ok(count<MAX_COMMANDS);assert.ok(bytes(scene)<=MAX_FRAME_BYTES);
  assert.equal(validateScene(scene).commands.length,count);assert.doesNotThrow(()=>serializeBook(book(scene)));
  scene.commands.push(command);assert.ok(bytes(scene)>MAX_FRAME_BYTES);rejectLiveAndHistory(scene);
});

test('bezier canonical snapshots enforce bytes when inherited object properties hide input geometry',()=>{
  const command=bezier({...Object.fromEntries(coordinates.map(key=>[key,-100000])),stroke:''});
  const canonical=frame(Array(MAX_COMMANDS).fill(command));assert.ok(bytes(canonical)>MAX_FRAME_BYTES);
  for(const scene of [Object.create(canonical),frame(Array.from({length:MAX_COMMANDS},()=>Object.create(command)))]){
    assert.ok(bytes(scene)<MAX_FRAME_BYTES);
    assert.throws(()=>validateScene(scene),/帧过大/);assert.throws(()=>serializeBook(book(scene)),/帧过大/);
    const record=context();assert.throws(()=>drawScene(record.canvas,scene),/帧过大/);assert.deepEqual(record.calls,[]);
  }
});

test('array-shaped bezier commands cannot hide oversized frames from JSON byte accounting',()=>{
  const command=bezier({...Object.fromEntries(coordinates.map(key=>[key,-100000])),stroke:''});
  const scene=frame(Array(MAX_COMMANDS).fill(Object.assign([],command)));
  assert.ok(bytes(scene)<MAX_FRAME_BYTES);assert.ok(bytes(frame(Array(MAX_COMMANDS).fill(command)))>MAX_FRAME_BYTES);
  assert.ok(Array.isArray(structuredClone(scene).commands[0]));
  rejectLiveAndHistory(scene);assert.throws(()=>validateScene(scene),/指令无效/);
});

test('worker accepts native bezier snapshots but exposes independently copied safe graphics',async()=>{
  const identity={cell_id:'bezier-cell',execution_count:1,generation:1,token:'bezier-worker'};
  const worker={postMessage(){},terminate(){}},events=[];
  const run=createJSExecution({javascript:'export default ()=>({dispatch(){}})',identity,onEvent:event=>events.push(event),workerFactory:()=>worker});
  try{
    const scene=frame([bezier({transform:T.slice(),clips:[clip()]})]);
    worker.onmessage({data:{identity,serial:0,type:'batch',events:[{...scene,type:'graphics'}]}});
    await run.ready;
    assert.equal(events.length,1);assert.equal(events[0].commands[0].stroke,'#abcdef80');
    assert.deepEqual(events[0].commands,validateScene(scene).commands);
    scene.commands[0].cx1=999;scene.commands[0].transform[4]=999;scene.commands[0].clips[0].width=999;
    assert.equal(events[0].commands[0].cx1,30);assert.equal(events[0].commands[0].transform[4],10);
    assert.equal(events[0].commands[0].clips[0].width,70);
  }finally{run.dispose();}
});

test('malicious worker bezier batches reject atomically before exposing earlier output or graphics',async()=>{
  const identity={cell_id:'bezier-cell',execution_count:1,generation:1,token:'bezier-worker'};
  const malformed=[];
  for(const key of [...coordinates,'stroke_width']){
    for(const value of [undefined,null,true,'0',[],{},NaN,Infinity,-Infinity,100001,-100001])malformed.push(frame([bezier({[key]:value})]));
    const missing=bezier();delete missing[key];malformed.push(frame([missing]));
  }
  for(const patch of [{stroke_width:0},{stroke_width:0.5},{stroke_width:257},{fill:'#00000000'},
    {fill:null},{stroke:'url(x)'},{op:['bezier']},{op:'__proto__'},
    {transform:[1,0,0,1,0,Infinity]},{clips:[{...clip(),width:-1}]},{align:'left'}])malformed.push(frame([bezier(patch)]));
  malformed.push(Object.assign([],frame([bezier()])),frame([Object.assign([],bezier())]),
    frame([bezier({clips:[Object.assign([],clip())]})]),frame(Array(MAX_COMMANDS+1).fill(bezier())),
    frame([bezier({padding:'x'.repeat(MAX_FRAME_BYTES)})]));
  for(const scene of malformed){
    const worker={postMessage(){},terminate(){this.terminated=true;}},events=[],fatal=[];
    const run=createJSExecution({javascript:'export default ()=>({dispatch(){}})',identity,
      onEvent:event=>events.push(event),onFatal:event=>fatal.push(event),workerFactory:()=>worker});
    const message={identity,serial:0,type:'batch',events:[{type:'output',stream:'stdout',text:'must stay private'},
      {...frame([bezier()]),type:'graphics'},Object.assign(scene,{type:'graphics'})]};
    worker.onmessage({data:structuredClone(message)});
    await assert.rejects(run.ready);
    assert.deepEqual(events,[]);assert.equal(fatal.length,1);assert.equal(worker.terminated,true);assert.equal(run.active,false);
  }
});

test('malicious bezier callback batches preserve the earlier frame and reject active and queued sends',async()=>{
  const identity={cell_id:'bezier-cell',execution_count:1,generation:1,token:'bezier-worker'};
  const worker={postMessage(){},terminate(){this.terminated=true;}},events=[],fatal=[];
  const run=createJSExecution({javascript:'export default ()=>({dispatch(){}})',identity,
    onEvent:event=>events.push(event),onFatal:event=>fatal.push(event),workerFactory:()=>worker});
  worker.onmessage({data:{identity,serial:0,type:'batch',events:[{...frame([bezier()]),type:'graphics'}]}});
  await run.ready;
  const before=structuredClone(events),active=run.send({type:'mouse_down',canvas_id:'native-beziers'});
  const queued=run.send({type:'mouse_up',canvas_id:'native-beziers'});
  const rejected=Promise.all([assert.rejects(active),assert.rejects(queued)]);
  worker.onmessage({data:{identity,serial:1,type:'batch',events:[{type:'output',stream:'stdout',text:'must stay private'},
    {...frame([bezier({stroke:'#ffffff'})]),type:'graphics'},
    {...frame([bezier({cx2:Infinity})]),type:'graphics'}]}});
  await rejected;
  assert.deepEqual(events,before);assert.equal(fatal.length,1);assert.equal(worker.terminated,true);assert.equal(run.active,false);
});
