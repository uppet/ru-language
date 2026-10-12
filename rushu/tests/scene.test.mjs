import test from 'node:test';
import assert from 'node:assert/strict';
import {validateScene,MAX_COMMANDS} from '../static/scene.mjs';
import {parseBook,serializeBook,newCell,appendOutput} from '../static/notebook.mjs';
const frame=()=>({canvas_id:'canvas-1',width:320,height:200,fps:30,running:true,handlers:['frame','mouse_down'],commands:[{op:'background',color:'#ffffff'},{op:'rect',x:1,y:2,width:30,height:40,fill:'#ff0000',stroke:'',stroke_width:1}]});
test('graphics protocol clones only safe data',()=>{const input=frame();input.script='bad';const output=validateScene(input);assert.equal(output.script,undefined);assert.deepEqual(output.commands,input.commands);output.commands[1].x=4;assert.equal(input.commands[1].x,1);});
test('malformed and excessive drawing instructions fail closed',()=>{for(const change of [s=>s.width=2049,s=>s.height=0,s=>s.fps=61,s=>s.canvas_id='../x',s=>s.handlers=['click'],s=>s.commands=[{op:'eval',code:'bad'}],s=>s.commands[1].x=Infinity,s=>s.commands[1].fill='url(https://x)',s=>s.commands[1].width=-1,s=>s.commands[1].stroke_width=513,s=>s.commands=Array(MAX_COMMANDS+1).fill(s.commands[0]),s=>s.commands=[{op:'text',text:'x'.repeat(4097),x:0,y:0,size:12,color:'#000000'}]]){const s=frame();change(s);assert.throws(()=>validateScene(s));}});
test('all primitive commands use bounded numeric fields and exact colors',()=>{const s=frame();s.commands.push({op:'line',x1:0,y1:0,x2:50,y2:50,color:'#00ff00',width:2},{op:'ellipse',x:20,y:20,width:10,height:20,fill:'',stroke:'#0000ff',stroke_width:2},{op:'text',x:0,y:0,text:'<script>不执行</script>',color:'#000000',size:16});assert.equal(validateScene(s).commands.length,5);});
test('saved graphics are inert snapshots even if imported data asks for callbacks',()=>{const cell=newCell('code','显 1.');cell.outputs=[{type:'graphics',scene:frame()}];const text=serializeBook({title:'图',cells:[cell]});const restored=parseBook(text).cells[0];assert.equal(restored.historical,true);assert.equal(restored.outputs[0].scene.running,false);assert.deepEqual(restored.outputs[0].scene.handlers,[]);assert.equal(cell.outputs[0].scene.running,true);const raw=JSON.parse(text);raw.cells[0].outputs[0].scene=frame();assert.equal(parseBook(JSON.stringify(raw)).cells[0].outputs[0].scene.running,false);});
test('text limits account for graphics snapshots without crashing',()=>{const cell=newCell();cell.outputs=[{type:'graphics',scene:frame()}];appendOutput(cell,'stdout','hello');assert.equal(cell.outputs[1].text,'hello');assert.doesNotThrow(()=>serializeBook({title:'图',cells:[cell]}));});

test('text limit counts Unicode code points rather than UTF-16 units',()=>{
  for(const count of [2048,2049,3000,4096]){const s=frame();s.commands=[{op:'text',x:0,y:0,size:16,color:'#000000',text:'😀'.repeat(count)}];assert.equal(validateScene(s).commands[0].text,'😀'.repeat(count));}
  const s=frame();s.commands=[{op:'text',x:0,y:0,size:16,color:'#000000',text:'😀'.repeat(4097)}];assert.throws(()=>validateScene(s));
});
