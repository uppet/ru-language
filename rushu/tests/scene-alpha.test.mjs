import test from 'node:test';
import assert from 'node:assert/strict';
import {validateScene,drawScene,MAX_COMMANDS} from '../static/scene.mjs';
import {parseBook,serializeBook,newCell} from '../static/notebook.mjs';

const frame=commands=>({canvas_id:'alpha',width:100,height:80,fps:30,running:false,handlers:[],commands});
const colored=value=>[
  {op:'background',color:value},
  {op:'rect',x:0,y:0,width:10,height:10,fill:value,stroke:value,stroke_width:1},
  {op:'ellipse',x:0,y:0,width:10,height:10,fill:value,stroke:value,stroke_width:1},
  {op:'polygon',points:[[0,0],[10,0],[0,10]],fill:value,stroke:value,stroke_width:1},
  {op:'line',x1:0,y1:0,x2:10,y2:10,color:value,width:1},
  {op:'text',x:0,y:0,text:'如',color:value,size:12},
];

test('all scene colors accept exactly six/eight ASCII hex digits and normalize case',()=>{
  for(const value of ['#000000','#FFFFFF','#Ab12EF','#00000000','#FFFFFFff','#Ab12EF80','#12345601','#123456FE']){
    const input=frame(colored(value)),output=validateScene(input);
    for(const command of output.commands){
      for(const key of ['color','fill','stroke'])if(key in command)assert.equal(command[key],value.toLowerCase());
    }
    assert.equal(input.commands[0].color,value);
  }
});

test('untrusted live or historical colors reject CSS, non-ASCII, bad lengths and suffixes',()=>{
  const invalid=['red','transparent','rgb(0,0,0)','rgba(0,0,0,0)','url(https://example.invalid)','var(--color)',
    '#fff','#ffff','#12345','#1234567','#123456789','#GG000080','#１２３４５６','#ａｂｃｄｅｆ',
    ' #123456','#123456 ','#12345680\t','#123456\0',null,0,true,{},[]];
  for(const suffix of ['\n','\r','\r\n','\u2028','\u2029']){
    for(const color of ['#123456','#1234567','#12345678'])invalid.push(color+suffix);
  }
  for(const value of invalid){
    for(const command of colored(value))assert.throws(()=>validateScene(frame([command])),undefined,JSON.stringify(value));
  }
});

test('empty fill, stroke, line and text colors remain invisible while empty background is invalid',()=>{
  assert.throws(()=>validateScene(frame([colored('')[0]])));
  assert.doesNotThrow(()=>validateScene(frame(colored('').slice(1))));
  const calls=[],ctx=new Proxy({}, {get:(_,name)=>(...args)=>calls.push([name,...args]),set:()=>true});
  drawScene({getContext:()=>ctx},frame(colored('').slice(1)));
  for(const name of ['fill','stroke','fillText'])assert.equal(calls.filter(call=>call[0]===name).length,0);
});

test('alpha scenes retain strict command, size and geometry boundaries',()=>{
  assert.throws(()=>validateScene(frame(Array(MAX_COMMANDS+1).fill(colored('#00000000')[0]))));
  for(const mutate of [s=>s.width=2049,s=>s.fps=61,s=>s.commands[0].transform=[1,0,0,1,Infinity,0],s=>s.commands[0].clips=Array(33).fill({})]){
    const scene=frame(colored('#FF000080'));mutate(scene);assert.throws(()=>validateScene(scene));
  }
});

test('every historical background clears before filling and ignores validated geometry',()=>{
  const calls=[],ctx=new Proxy({}, {get:(_,name)=>(...args)=>calls.push([name,...args]),set:()=>true});
  const rectangle=colored('#00ff0080')[1];
  const backgrounds=['#ff000080','#0000ff00'].map(color=>({op:'background',color,
    transform:[1,0,0,1,50,50],clips:[{x:0,y:0,width:1,height:1,transform:[1,0,0,1,0,0]}]}));
  drawScene({getContext:()=>ctx},frame([rectangle,backgrounds[0],rectangle,backgrounds[1]]));
  assert.deepEqual(calls.filter(([name])=>name==='clearRect'||name==='fillRect'),[
    ['clearRect',0,0,100,80],['fillRect',0,0,100,80],
    ['clearRect',0,0,100,80],['fillRect',0,0,100,80],
  ]);
  assert.equal(calls.filter(([name])=>name==='setTransform'||name==='clip').length,0);
});

test('alpha and empty styles survive history round trip as inert normalized data',()=>{
  const cell=newCell('code','');cell.outputs=[{type:'graphics',scene:frame([...colored('#ABCDEF80'),...colored('').slice(1)])}];
  const restored=parseBook(serializeBook({title:'透明',cells:[cell]})).cells[0];
  assert.equal(restored.historical,true);
  assert.deepEqual(restored.outputs[0].scene.commands,validateScene(cell.outputs[0].scene).commands);
  assert.equal(restored.outputs[0].scene.running,false);
  assert.deepEqual(restored.outputs[0].scene.handlers,[]);
});
