import test from 'node:test';
import assert from 'node:assert/strict';
import {parseBook, serializeBook, newCell, appendOutput, historicalBook,
  FORMAT, MAX_FILE_BYTES, MAX_SOURCE, MAX_OUTPUT} from '../static/notebook.mjs';
import {analyze, highlight, lex} from '../static/editor.mjs';

const document = cells => JSON.stringify({format:FORMAT,version:1,title:'审阅',cells});
const code = source => ({id:'review',type:'code',source,outputs:[],execution_count:null});

test('imported source, outputs and counts never restore runtime status',()=>{
  const source={...code("显 '保存的代码'."),execution_count:51,outputs:[{type:'stdout',text:'old result'}],
    status:'running',historical:false,state:{secret:'do not restore'},request_id:'stale'};
  const result=parseBook(document([source]));
  assert.equal(result.cells[0].execution_count,51);
  assert.equal(result.cells[0].historical,true);
  assert.equal(result.cells[0].status,'idle');
  assert.equal('state' in result.cells[0],false);
  assert.equal('request_id' in result.cells[0],false);
});

test('round trip retains text literally including markup and prototype-like ids',()=>{
  const payload='<img src=x onerror="alert(1)"><script>bad()</script> & \\u0000';
  const cell={...code(payload),id:'__proto__',outputs:[{type:'stdout',text:payload}]};
  const result=parseBook(serializeBook(parseBook(document([cell]))));
  assert.equal(result.cells[0].source,payload);
  assert.equal(result.cells[0].outputs[0].text,payload);
  assert.equal(result.cells[0].historical,true);
  assert.equal(Object.prototype.polluted,undefined);
});

test('duplicate, dangerous, missing ids become independent safe ids',()=>{
  const cells=[code('a'),code('b'),{...code('c'),id:'x" onclick="bad()'}, {...code('d'),id:null}];
  const result=parseBook(document(cells));
  assert.equal(new Set(result.cells.map(c=>c.id)).size,cells.length);
  assert.ok(result.cells.every(c=>/^[\w-]{1,128}$/.test(c.id)));
});

test('document validation rejects malformed executable output types and limits',()=>{
  for (const cell of [
    {...code('a'),type:'javascript'},
    {...code('a'),source:{}},
    {...code('a'),source:'x'.repeat(MAX_SOURCE+1)},
    {...code('a'),execution_count:-1},
    {...code('a'),execution_count:1.2},
    {...code('a'),execution_count:Infinity},
    {...code('a'),outputs:[{type:'html',text:'<script>bad()</script>'}]},
    {...code('a'),outputs:[{type:'stdout',text:{}}]},
    {...code('a'),outputs:[{type:'stdout',text:'x'.repeat(MAX_OUTPUT+1)}]},
  ]) {
    // JSON null is valid as "never executed", so Infinity is checked raw below.
    if (cell.execution_count===Infinity) continue;
    assert.throws(()=>parseBook(document([cell])));
  }
  assert.throws(()=>parseBook('{"format":"rushu-notebook","version":1,"title":"x","cells":[{"type":"code","source":"","execution_count":1e400}]}'));
  assert.throws(()=>parseBook(' '.repeat(MAX_FILE_BYTES+1)));
  assert.throws(()=>parseBook(document(Array.from({length:501},()=>code('')))));
});

test('normal output growth is bounded and adjacent same-stream writes merge',()=>{
  const cell=newCell();
  appendOutput(cell,'stdout','a'); appendOutput(cell,'stdout','b');
  assert.deepEqual(cell.outputs,[{type:'stdout',text:'ab'}]);
  appendOutput(cell,'stderr','x'.repeat(MAX_OUTPUT));
  appendOutput(cell,'stdout','discarded');
  assert.ok(cell.outputs.reduce((n,o)=>n+o.text.length,0)<=MAX_OUTPUT);
  assert.ok(cell.outputs.some(o=>o.text.includes('截断')));
});

test('historical marking keeps snapshot while clearing pending cell state',()=>{
  const cell={...newCell(),execution_count:3,status:'waiting_input'};
  historicalBook({title:'book',cells:[cell]});
  assert.equal(cell.historical,true); assert.equal(cell.status,'idle');
  assert.equal(cell.execution_count,3);
});

test('highlight escapes arbitrary input while generating only fixed spans',()=>{
  for(const source of ['<img src=x onerror=alert(1)>', "显 '<script>bad()</script>'.", '# </span><svg/onload=bad()>',
    '显 "&quot; & < > \\"".', '😀 <a href="javascript:bad()">click</a>']) {
    const rendered=highlight(source);
    assert.doesNotMatch(rendered,/<\/?(?:img|script|svg|a)(?:\s|>)/i);
    assert.doesNotMatch(rendered.replaceAll(/<\/?span(?: class="tok-[a-z]+")?>/g,''),/[<>]/);
  }
});

test('strings and comments never produce executable structure guides',()=>{
  const result=analyze("# 算 若 循 形 (\n显 '算 若 循 法 环 象 ( )'.\n显 1.");
  assert.equal(result.blocks.length,0);
  assert.equal(result.depth,0);
  const tokens=lex('长名字算值 取 3. 显 长名字算值.');
  assert.equal(tokens.filter(t=>t.text==='算').length,0);
});
