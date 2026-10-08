import test from 'node:test';
import assert from 'node:assert/strict';
import {parseBook,serializeBook,newCell,blankBook,welcomeBook,appendOutput,historicalBook,MAX_OUTPUT} from '../static/notebook.mjs';
const wrap=cells=>JSON.stringify({format:'rushu-notebook',version:1,title:'测试',cells});
test('portable roundtrip includes source/output but never runtime session',()=>{
  const book=welcomeBook();book.session='SECRET';book.cells[1].execution_count=3;book.cells[1].status='running';book.cells[1].outputs=[{type:'stdout',text:'你好\n'}];
  const text=serializeBook(book),restored=parseBook(text);assert.ok(!text.includes('SECRET'));assert.ok(!text.includes('running'));assert.equal(restored.cells[1].source,book.cells[1].source);assert.equal(restored.cells[1].historical,true);assert.equal(restored.cells[1].status,'idle');assert.equal(restored.cells[1].execution_count,3);
});
test('restored error/output HTML is plain data',()=>{
  const payload='<img src=x onerror=alert(1)>';const book=parseBook(wrap([{...newCell(),outputs:[{type:'error',text:payload}]}]));assert.equal(book.cells[0].outputs[0].text,payload);assert.equal(book.cells[0].historical,true);
});
test('unknown schema, malformed source/output/count rejected',()=>{
  for(const text of ['nope','{}','null',JSON.stringify({format:'rushu-notebook',version:9,title:'x',cells:[]})])assert.throws(()=>parseBook(text));
  for(const bad of [{type:'html',source:''},{type:'code',source:5},{type:'code',source:'',execution_count:-1},{type:'code',source:'',outputs:[{type:'html',text:'x'}]}])assert.throws(()=>parseBook(wrap([bad])));
});
test('duplicate or unsafe IDs normalized and blank document remains editable',()=>{
  const restored=parseBook(wrap([{...newCell(),id:'duplicate'},{...newCell(),id:'duplicate'},{...newCell(),id:'" onload="evil'}]));assert.equal(new Set(restored.cells.map(c=>c.id)).size,3);assert.equal(restored.cells[0].id,'duplicate');assert.equal(parseBook(wrap([])).cells.length,1);
});
test('source and cell count limits apply on import and own export',()=>{
  assert.throws(()=>parseBook(wrap([{...newCell(),source:'x'.repeat(200001)}])));
  assert.throws(()=>parseBook(wrap(Array.from({length:501},()=>newCell()))));
  const book=blankBook();book.cells=Array.from({length:60},()=>newCell('code','x'.repeat(190000)));assert.throws(()=>serializeBook(book),/文件太大/);
});
test('append merges matching streams and caps output with an explicit marker',()=>{
  const cell=newCell();appendOutput(cell,'stdout','a');appendOutput(cell,'stdout','b');assert.deepEqual(cell.outputs,[{type:'stdout',text:'ab'}]);
  appendOutput(cell,'stdout','x'.repeat(MAX_OUTPUT));appendOutput(cell,'stdout','ignored');assert.ok(cell.outputs.some(o=>o.text.includes('已截断')));assert.ok(cell.outputs.reduce((n,o)=>n+o.text.length,0)<=MAX_OUTPUT);assert.doesNotThrow(()=>parseBook(wrap([cell])));
});
test('alternating streams cannot create an unopenable file',()=>{
  const cell=newCell();for(let i=0;i<5000;i++)appendOutput(cell,i%2?'stderr':'stdout','x');assert.ok(cell.outputs.length<=2048);assert.ok(cell.outputs.at(-1).text.includes('已截断'));assert.doesNotThrow(()=>parseBook(wrap([cell])));
});
test('session reset marks all prior execution snapshots historical',()=>{
  const book=blankBook();book.cells[0].execution_count=1;book.cells[0].status='running';historicalBook(book);assert.equal(book.cells[0].historical,true);assert.equal(book.cells[0].status,'idle');
});
