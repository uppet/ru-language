import test from 'node:test';
import assert from 'node:assert/strict';
import {templates,createTemplateBook} from '../static/templates.mjs';
import {parseBook,serializeBook} from '../static/notebook.mjs';

test('six discoverable templates including an explicit blank starting point',()=>{
 assert.deepEqual(templates.map(t=>t.id),['basics','text','contest','graphics','generation','blank']);
 for(const t of templates){assert.ok(t.title&&t.description&&t.detail);assert.ok(Object.isFrozen(t));}
 assert.throws(()=>createTemplateBook('missing'),/找不到/);
 const blank=createTemplateBook('blank');assert.equal(blank.cells.length,1);assert.equal(blank.cells[0].source,'');assert.equal(blank.cells[0].type,'code');
});
test('every selection creates independent pristine cells, outputs and generation histories',()=>{
 const ids=new Set();
 for(const template of templates){
  const a=createTemplateBook(template.id),b=createTemplateBook(template.id);
  for(const book of [a,b])for(const cell of book.cells){assert.ok(!ids.has(cell.id));ids.add(cell.id);assert.equal(cell.status,'idle');assert.equal(cell.execution_count,null);assert.deepEqual(cell.outputs,[]);assert.equal(cell.historical,false);}
  a.cells[0].source='changed';a.cells[0].outputs.push({type:'stdout',text:'changed'});
  assert.notEqual(b.cells[0].source,'changed');assert.deepEqual(b.cells[0].outputs,[]);
  if(template.id==='generation'){
   const left=a.cells.find(c=>c.generation),right=b.cells.find(c=>c.generation);
   assert.equal(left.source,'');assert.match(left.generation.prompt,/如是我言$/);
   left.generation.revisions.push({changed:true});assert.notDeepEqual(left.generation.revisions,right.generation.revisions);
  }
 }
});
test('templates roundtrip through the existing portable notebook format',()=>{
 for(const template of templates){const book=createTemplateBook(template.id),copy=parseBook(serializeBook(book));assert.equal(copy.title,book.title);assert.deepEqual(copy.cells,book.cells);}
});
test('ordinary scenarios have one or two short runnable examples, not generation markers',()=>{
 for(const template of templates.filter(t=>!['blank','generation'].includes(t.id))){const code=createTemplateBook(template.id).cells.filter(c=>c.type==='code');assert.ok(code.length>=1&&code.length<=2);for(const c of code){assert.ok(c.source.trim());assert.ok(c.source.split('\n').length<25);assert.ok(!c.generation);assert.ok(!c.source.includes('如是我言'));}}
});
