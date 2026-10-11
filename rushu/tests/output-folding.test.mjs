import test from 'node:test';
import assert from 'node:assert/strict';
import {newCell,appendOutput,serializeBook,parseBook,MAX_OUTPUT,MAX_BOOK_OUTPUT,bookOutputBytes,cellOutputBytes,clipBytes} from '../static/notebook.mjs';
import {outputWindow,PAGE_CHARS} from '../static/output-view.mjs';
test('large Unicode output survives save and reopen, bounded previews and pages concatenate exactly',()=>{
  const cell=newCell(),text=('中😀\n').repeat(100000),book={title:'大输出',cells:[cell]};appendOutput(cell,'stdout',text,book);
  assert.equal(cell.outputs[0].text,text);const restored=parseBook(serializeBook(book));assert.equal(restored.cells[0].outputs[0].text,text);
  assert.ok(outputWindow(cell.outputs).items[0].text.length<=2000);assert.ok(outputWindow(cell.outputs).items[0].text.split('\n').length<=9);
  let whole='';const count=outputWindow(cell.outputs,true).pages;for(let page=0;page<count;page++){const w=outputWindow(cell.outputs,true,page);whole+=w.items.map(x=>x.text||'').join('');assert.ok(w.items.reduce((n,x)=>n+(x.text?.length||0),0)<=PAGE_CHARS+1);}assert.equal(whole,text);
});
test('byte clipping preserves emoji and errors remain after overflow',()=>{
  assert.equal(clipBytes('😀中',3),'');assert.equal(clipBytes('😀中',6),'😀');
  const cell=newCell();appendOutput(cell,'stdout','😀'.repeat(MAX_OUTPUT));appendOutput(cell,'error','真正错误');assert.ok(cell.outputs.some(x=>x.text.includes('真正错误')));assert.ok(cellOutputBytes(cell)<=MAX_OUTPUT);assert.ok(cell.outputs.some(x=>x.text.includes('已截断')));
});
test('whole book budget preserves old cells and roundtrips without extra loss',()=>{
  const book={title:'整书',cells:Array.from({length:8},()=>newCell())};for(const cell of book.cells)appendOutput(cell,'stdout','a'.repeat(MAX_OUTPUT),book);
  assert.ok(bookOutputBytes(book)<=MAX_BOOK_OUTPUT);assert.ok(book.cells[0].outputs[0].text.length>1000000);assert.deepEqual(parseBook(serializeBook(book)).cells.map(c=>c.outputs),book.cells.map(c=>c.outputs));
});
test('mixed stdout stderr graphics preserve order within bounded view',()=>{
  const outputs=[{type:'stdout',text:'a\n'},{type:'graphics',scene:{}},{type:'stderr',text:'oops\n'},{type:'stdout',text:'z'.repeat(100000)}];const view=outputWindow(outputs);assert.deepEqual(view.items.map(x=>x.type),['stdout','graphics','stderr','stdout']);assert.ok(view.items.at(-1).text.length<2000);
});
test('alternating tiny stream records have bounded DOM counts on every page',()=>{
  const outputs=Array.from({length:2048},(_,i)=>({type:i%2?'stderr':'stdout',text:'😀'}));assert.ok(outputWindow(outputs).items.length<=32);let text='';const pages=outputWindow(outputs,true).pages;for(let page=0;page<pages;page++){const window=outputWindow(outputs,true,page);assert.ok(window.items.length<=128);text+=window.items.map(x=>x.text).join('');}assert.equal(text,'😀'.repeat(2048));
});
