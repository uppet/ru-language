import test from 'node:test';
import assert from 'node:assert/strict';
import {validateScene,drawScene,MAX_COMMANDS,MAX_FRAME_BYTES} from '../static/scene.mjs';
import {parseBook,serializeBook,newCell} from '../static/notebook.mjs';

const frame=commands=>({canvas_id:'text-anchor',width:160,height:100,fps:30,running:false,handlers:[],commands});
const text=(extra={})=>({op:'text',x:80,y:50,text:'如观 😀',color:'#AABBCC80',size:16,...extra});
const alignments=['left','center','right'],baselines=['top','middle','bottom','alphabetic'];
const book=scene=>{const cell=newCell('code','');cell.outputs=[{type:'graphics',scene}];return {title:'文字锚点',cells:[cell]};};

function context(scoped=true){
  const calls=[],state={textAlign:'end',textBaseline:'hanging'},stack=[];
  const ctx={
    fillText(...args){calls.push(['fillText',...args,state.textAlign,state.textBaseline,state.fillStyle,state.font]);},
    setTransform(...args){calls.push(['setTransform',...args]);},
    beginPath(){calls.push(['beginPath']);},rect(...args){calls.push(['rect',...args]);},clip(){calls.push(['clip']);},
  };
  if(scoped){ctx.save=()=>{stack.push({...state});calls.push(['save']);};ctx.restore=()=>{Object.assign(state,stack.pop());calls.push(['restore']);};}
  const proxy=new Proxy(ctx,{set:(_,key,value)=>{calls.push(['set',key,value]);state[key]=value;return true;}});
  return {calls,state,canvas:{getContext:()=>proxy}};
}

test('optional text enums accept all native values and preserve absent legacy fields',()=>{
  for(const align of [undefined,...alignments])for(const baseline of [undefined,...baselines]){
    const command=text({...(align===undefined?{}:{align}),...(baseline===undefined?{}:{baseline})});
    const output=validateScene(frame([command])).commands[0];
    assert.deepEqual(output,{...command,color:'#aabbcc80'});
    assert.notEqual(output,command);
  }
});

test('untrusted worker and history enums reject explicit invalid values without coercion',()=>{
  const invalid=[undefined,null,true,false,0,1,{},[],['left'],'','中','start','end','hanging','ideographic',
    'left ',' center','middle\n','top\0','LEFT','constructor','__proto__','toString','url(x)'];
  for(const key of ['align','baseline'])for(const value of invalid){
    const scene=frame([text({[key]:value})]);
    assert.throws(()=>validateScene(scene),/文字对齐/);
    assert.throws(()=>serializeBook(book(scene)),/文字对齐/);
    if(value!==undefined){
      const raw=JSON.parse(serializeBook(book(frame([text()]))));
      raw.cells[0].outputs[0].scene.commands[0][key]=value;
      assert.throws(()=>parseBook(JSON.stringify(raw)),/文字对齐/);
    }
  }
  for(const [key,value] of [['align','top'],['baseline','left']])assert.throws(()=>validateScene(frame([text({[key]:value})])));
});

test('text fields are rejected on every non-text operation',()=>{
  const commands=[{op:'background',color:'#000000'},
    {op:'rect',x:0,y:0,width:1,height:1,fill:'#000000',stroke:'',stroke_width:1},
    {op:'ellipse',x:0,y:0,width:1,height:1,fill:'#000000',stroke:'',stroke_width:1},
    {op:'line',x1:0,y1:0,x2:1,y2:1,color:'#000000',width:1},
    {op:'polygon',points:[[0,0],[1,0],[0,1]],fill:'#000000',stroke:'',stroke_width:1}];
  for(const command of commands)for(const [key,value] of [['align','left'],['baseline','top']]){
    assert.throws(()=>validateScene(frame([{...command,[key]:value}])),/文字对齐/);
  }
});

test('prototype enum properties cannot change an absent default',()=>{
  const command=Object.assign(Object.create({align:'right',baseline:'alphabetic'}),text());
  const output=validateScene(frame([command])).commands[0];
  assert.equal(Object.hasOwn(output,'align'),false);assert.equal(Object.hasOwn(output,'baseline'),false);
  const {calls,canvas}=context(false);drawScene(canvas,frame([command]));
  assert.deepEqual(calls.find(call=>call[0]==='fillText').slice(4,6),['left','top']);
});

test('each text command explicitly installs its own native anchor including legacy defaults',()=>{
  for(const scoped of [false,true]){
    const commands=[];
    for(const align of alignments)for(const baseline of baselines)commands.push(text({align,baseline}));
    commands.push(text(),text({align:'right'}),text({baseline:'alphabetic'}));
    const {calls,canvas}=context(scoped);drawScene(canvas,frame(commands));
    assert.deepEqual(calls.filter(call=>call[0]==='fillText'),commands.map(command=>[
      'fillText',command.text,command.x,command.y,command.align??'left',command.baseline??'top','#aabbcc80','16px sans-serif']));
    assert.equal(calls.filter(call=>call[0]==='set'&&call[1]==='textAlign').length,commands.length);
    assert.equal(calls.filter(call=>call[0]==='set'&&call[1]==='textBaseline').length,commands.length);
  }
});

test('text anchors compose with frozen transforms, clips, empty fill and alpha',()=>{
  const transform=[2,0,0,3,5,6],clips=[{x:0,y:0,width:100,height:60,transform:[1,0,0,1,0,0]}];
  const {calls,state,canvas}=context();
  drawScene(canvas,frame([text({align:'right',baseline:'alphabetic',transform,clips}),text({color:'',align:'center',baseline:'middle'}),text()]));
  assert.deepEqual(calls.filter(call=>call[0]==='setTransform'),[['setTransform',1,0,0,1,0,0],['setTransform',...transform]]);
  assert.equal(calls.filter(call=>call[0]==='clip').length,1);
  assert.equal(calls.filter(call=>call[0]==='fillText').length,2);
  assert.deepEqual(calls.filter(call=>call[0]==='fillText').map(call=>call.slice(4,7)),[
    ['right','alphabetic','#aabbcc80'],['left','top','#aabbcc80']]);
  assert.equal(calls.filter(call=>call[0]==='restore').length,3);
  assert.equal(state.textAlign,'end');assert.equal(state.textBaseline,'hanging');
});

test('text rendering restores native state after a failed fillText',()=>{
  const calls=[],ctx={save(){calls.push('save');},restore(){calls.push('restore');},fillText(){throw new Error('paint failed');}};
  assert.throws(()=>drawScene({getContext:()=>ctx},frame([text({align:'center',baseline:'middle'})])),/paint failed/);
  assert.deepEqual(calls,['save','restore']);
});

test('nondefault and legacy anchors round-trip history as inert data with no callback revival',()=>{
  const commands=[text(),text({align:'center',baseline:'middle'}),text({align:'right',baseline:'alphabetic'}),text({baseline:'bottom'})];
  const scene={...frame(commands),running:true,handlers:['frame','mouse_down']};
  const restored=parseBook(serializeBook(book(scene))).cells[0];
  assert.equal(restored.historical,true);
  assert.deepEqual(restored.outputs[0].scene.commands,commands.map(command=>({...command,color:'#aabbcc80'})));
  assert.equal(restored.outputs[0].scene.running,false);assert.deepEqual(restored.outputs[0].scene.handlers,[]);
  const {calls,canvas}=context(false);drawScene(canvas,restored.outputs[0].scene);
  assert.deepEqual(calls.filter(call=>call[0]==='fillText').map(call=>call.slice(4,6)),[
    ['left','top'],['center','middle'],['right','alphabetic'],['left','bottom']]);
});

test('alignment fields retain scene bytes, command, text and geometry budgets',()=>{
  assert.throws(()=>validateScene(frame(Array(MAX_COMMANDS+1).fill(text({align:'center'})))));
  const oversized=frame(Array(64).fill(text({align:'center',baseline:'middle',text:'x'.repeat(4096)})));
  assert.ok(new TextEncoder().encode(JSON.stringify(oversized)).length>MAX_FRAME_BYTES);
  assert.throws(()=>validateScene(oversized),/帧过大/);
  for(const patch of [{text:'x'.repeat(4097)},{size:257},{size:0},{x:Infinity},{y:100001},{transform:[1,0,0,1,Infinity,0]},{clips:Array(33).fill({})}]){
    assert.throws(()=>validateScene(frame([text({align:'center',baseline:'middle',...patch})])));
  }
});
