import test from 'node:test';
import assert from 'node:assert/strict';
import {newCell,parseBook,serializeBook} from '../static/notebook.mjs';
import {validateGeneration,ensureGeneration,checkpoint,replaceWithRevision,restoreRevision,lineDiff,generationIntent,withGenerationMarker,MAX_HISTORY_BYTES} from '../static/history.mjs';
const cell=()=>newCell('code','显 1.');
const revision=(i,overrides={})=>({id:`v-${i}`,timestamp:new Date(i).toISOString(),kind:'human',prompt:'p',source:`${i}`,...overrides});
const book=c=>({title:'历史',cells:[c]});
test('old books remain v1 without generation; history roundtrips as isolated data',()=>{
  const c=cell();assert.equal(parseBook(serializeBook(book(c))).cells[0].generation,undefined);
  ensureGeneration(c,'写一句问候');checkpoint(c);replaceWithRevision(c,{source:'显 "你好".',prompt:'写一句问候'});
  const restored=parseBook(serializeBook(book(c))).cells[0];assert.deepEqual(restored.generation,c.generation);assert.equal(restored.status,'idle');
  const safe=validateGeneration(c.generation);safe.revisions[0].source='changed';assert.equal(c.generation.revisions[0].source,'显 1.');
});
test('human no-op deduplicates; prompt and code edits checkpoint independently',()=>{
  const c=cell();ensureGeneration(c,'p');const first=checkpoint(c);assert.equal(checkpoint(c).id,first.id);assert.equal(c.generation.revisions.length,1);
  c.generation.prompt='new';checkpoint(c);c.source+='\n';checkpoint(c);assert.equal(c.generation.revisions.length,3);
});
test('replacement and restore preserve human changes and add immutable snapshots',()=>{
  const c=cell();ensureGeneration(c,'first');const first=checkpoint(c);replaceWithRevision(c,{source:'显 2.',prompt:'second'});
  c.source='显 3.';c.generation.prompt='manual';const original=structuredClone(c.generation.revisions);
  const restored=restoreRevision(c,first.id);assert.equal(restored.kind,'restore');assert.equal(restored.restoredFrom,first.id);assert.notEqual(restored.id,first.id);
  assert.deepEqual(c.generation.revisions.slice(0,2),original);assert.equal(c.generation.revisions.at(-2).source,'显 3.');assert.equal(c.generation.revisions.at(-2).prompt,'manual');assert.equal(c.source,'显 1.');assert.equal(c.generation.prompt,'first');
});
test('strict validation rejects credentials, malformed metadata, order and restore targets',()=>{
  for(const bad of [null,[],{}, {prompt:'',revisions:[],apiKey:'secret'}, {prompt:3,revisions:[]}, {prompt:'x'.repeat(200001),revisions:[]}])assert.throws(()=>validateGeneration(bad));
  const badRevisions=[revision(1,{id:'bad id'}),revision(1,{timestamp:'2020-01-01'}),revision(1,{kind:'run'}),revision(1,{source:2}),revision(1,{apiKey:'secret'}),revision(1,{kind:'restore',restoredFrom:'absent'}),revision(1,{restoredFrom:'absent'})];
  for(const r of badRevisions)assert.throws(()=>validateGeneration({prompt:'',revisions:[r]}));
  assert.throws(()=>validateGeneration({prompt:'',revisions:[revision(2),revision(1)]}));assert.throws(()=>validateGeneration({prompt:'',revisions:[revision(1),revision(1)]}));
  assert.throws(()=>validateGeneration({prompt:'',revisions:[revision(1,{kind:'restore',restoredFrom:'v-2'}),revision(2)]}));
  assert.throws(()=>ensureGeneration(newCell('markdown','x')));
  const c=newCell('markdown','x');c.generation={prompt:'',revisions:[]};assert.throws(()=>serializeBook(book(c)));
});
test('history count exhaustion rejects atomically without losing drafts or originals',()=>{
  const c=cell();c.generation={prompt:'p',revisions:Array.from({length:99},(_,i)=>revision(i))};
  const before=structuredClone(c);assert.throws(()=>replaceWithRevision(c,{source:'new',prompt:'new'}),/100/);assert.deepEqual(c,before);
  assert.throws(()=>restoreRevision(c,'v-0'),/100/);assert.deepEqual(c,before);
  checkpoint(c);const full=structuredClone(c);c.source='changed';const edited=structuredClone(c);assert.throws(()=>checkpoint(c),/100/);assert.deepEqual(c,edited);assert.equal(full.generation.revisions.length,100);
});
test('aggregate UTF-8 history byte budget is enforced atomically',()=>{
  const c=cell();c.generation={prompt:'p',revisions:Array.from({length:3},(_,i)=>revision(i,{source:'汉'.repeat(200000)}))};
  validateGeneration(c.generation);c.source='字'.repeat(200000);const before=structuredClone(c);assert.throws(()=>checkpoint(c),/2 MiB/);assert.deepEqual(c,before);assert.ok(MAX_HISTORY_BYTES<2400000);
});
test('overall book history still obeys 10 MiB import/export limit',()=>{
  const cells=Array.from({length:6},()=>{const c=cell();c.generation={prompt:'p',revisions:Array.from({length:3},(_,i)=>revision(i,{source:'汉'.repeat(200000)}))};return c;});
  assert.throws(()=>serializeBook({title:'big',cells}),/10 MB/);
});
test('diff reconstructs both sources, treats HTML as data, preserves line endings',()=>{
  for(const [before,after] of [['',''],['a\nb\n','a\nc\n'],['same','same\n'],['<img onerror=evil>\n','<script>evil</script>\n'],['a\r\nb','a\r\nx\nb'],['x\n'.repeat(99999),'y\n'.repeat(99999)]]){
    const diff=lineDiff(before,after);assert.equal(diff.filter(x=>x.type!=='add').map(x=>x.text).join(''),before);assert.equal(diff.filter(x=>x.type!=='remove').map(x=>x.text).join(''),after);assert.ok(diff.every(x=>['equal','add','remove'].includes(x.type)));
  }
  assert.throws(()=>lineDiff('x'.repeat(200001),''));
});
test('intent marker matches lexical boundaries and prose contractions',()=>{
  for(const prefix of ['Make it work.\n',"Don't repeat yourself.\n",'显 "如是我言".\n','# quote "\n','解. " 释.\n','批。 "\n','显 “done”.\n'])assert.equal(generationIntent(prefix+'如是我言\n\n'),prefix);
  for(const source of ['如是我言 extra','x如是我言','显 "\n如是我言',"显'\n如是我言",'解.\n如是我言','如是我言\n显 1.','// 如是我言'])assert.equal(generationIntent(source),null);
  assert.equal(generationIntent('\ufeff如是我言'),null);assert.equal(generationIntent('如是我言'),'');assert.equal(generationIntent('p\r\n如是我言\r\n'),'p\r\n');
  assert.equal(withGenerationMarker('p'),'p\n如是我言');assert.equal(withGenerationMarker('p\n如是我言'),'p\n如是我言');
});

test('full revision history still exports edited source and current prompt without a checkpoint',()=>{
  const c=cell();c.generation={prompt:'p',revisions:Array.from({length:100},(_,i)=>revision(i))};
  c.source='current manual draft';c.generation.prompt='edited prompt';
  const restored=parseBook(serializeBook(book(c))).cells[0];
  assert.equal(restored.source,c.source);assert.equal(restored.generation.prompt,c.generation.prompt);assert.equal(restored.generation.revisions.length,100);
  const before=structuredClone(c);assert.throws(()=>checkpoint(c),/100/);assert.deepEqual(c,before);
});
test('current prompt budget is independent of historical revision byte budget',()=>{
  const c=cell();c.generation={prompt:'汉'.repeat(200000),revisions:Array.from({length:3},(_,i)=>revision(i,{source:'汉'.repeat(200000)}))};
  c.source='edited draft';
  const restored=parseBook(serializeBook(book(c))).cells[0];assert.deepEqual(restored.generation,c.generation);assert.equal(restored.source,c.source);
  const before=structuredClone(c);assert.throws(()=>checkpoint(c),/2 MiB/);assert.deepEqual(c,before);
});


test('explicit marker routing preserves prose and repeated edited source without executing',async()=>{
  const {prepareGenerationFromMarker}=await import('../static/history.mjs');
  const cell=newCell('code','生成一个典\n如是我言');
  assert.equal(prepareGenerationFromMarker(cell),true);
  assert.equal(cell.source,'');assert.equal(cell.generation.prompt,'生成一个典\n如是我言');
  cell.source="显 '手动修改'.\n如是我言";
  assert.equal(prepareGenerationFromMarker(cell),true);
  assert.equal(cell.source,"显 '手动修改'.\n");
  assert.equal(cell.generation.prompt,'生成一个典\n如是我言');
  assert.equal(cell.generation.revisions.at(-1).source,"显 '手动修改'.\n如是我言");
  const ordinary=newCell('code',"显 '如是我言'.");
  assert.equal(prepareGenerationFromMarker(ordinary),false);assert.equal(ordinary.generation,undefined);
});
