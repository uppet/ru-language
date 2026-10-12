import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {diagnosticRange,captureDiagnostic,currentDiagnostic,sourceVersion} from '../static/diagnostics.mjs';

test('Unicode scalar coordinates map Chinese, emoji, tabs, CRLF and EOF without splitting surrogate pairs',()=>{
  assert.deepEqual(diagnosticRange('甲😀\t乙\r\n末',1,2),{line:1,col:2,start:1,end:3});
  assert.deepEqual(diagnosticRange('甲😀\t乙\r\n末',1,4),{line:1,col:4,start:4,end:5});
  assert.deepEqual(diagnosticRange('甲😀\t乙\r\n末',2,2),{line:2,col:2,start:8,end:8});
  assert.deepEqual(diagnosticRange('甲\n',2,1),{line:2,col:1,start:2,end:2});
  assert.deepEqual(diagnosticRange('甲😀',1,null),{line:1,col:null,start:0,end:3});
  for(const [line,col] of [[0,1],[2,1],[1,4],[1,-1],[1,0],[1,1.5],['1',1],[Infinity,1]])assert.equal(diagnosticRange('甲😀',line,col),null);
});

function fixture(){
 const original={id:'origin',source:'显 未定义.',execution_count:1,diagnosticSnapshot:{source:'显 未定义.',version:'hash',generation:1,execution:1}};
 const trigger={id:'trigger',source:'调用函数.',execution_count:2};
 const event={cell_id:'trigger',execution_count:2,generation:1,message:'未定义',diagnostic:{line:1,col:3,message:'未定义',source_name:'rushu://s/1/origin/1.ru',source:{kind:'cell',cell_id:'origin',execution_count:1,generation:1,source_version:'hash'}}};
 return {original,trigger,book:{cells:[original,trigger]},event};
}

test('structured source identity resolves earlier cell functions rather than caller coordinates',()=>{
 const {original,book,event}=fixture(),record=captureDiagnostic(book,event);
 assert.equal(record.targetId,'origin');assert.equal(currentDiagnostic(original,record),true);
 assert.deepEqual(record.range,{line:1,col:3,start:2,end:3});
});
test('file paths and legacy/malformed messages never become editor locations',()=>{
 const {book,event}=fixture();
 for(const source of [{kind:'file'},{kind:'cell',cell_id:'missing'},null])assert.equal(captureDiagnostic(book,{...event,diagnostic:{...event.diagnostic,source,source_name:'C:\\用户\\a:b.ru'}}),null);
 assert.equal(captureDiagnostic(book,{line:1,col:1,message:'C:\\a.ru:1:1: error: bad'}),null);
 for(const changes of [{source_version:'different'},{execution_count:2},{generation:2}])assert.equal(captureDiagnostic(book,{...event,diagnostic:{...event.diagnostic,source:{...event.diagnostic.source,...changes}}}),null);
});
test('edits, history, clear, newer executions, reset and deleted cells invalidate markers',()=>{
 for(const change of [c=>c.source+=' ',c=>c.stale=true,c=>c.historical=true,c=>delete c.diagnosticSnapshot,c=>c.execution_count++,c=>c.diagnosticSnapshot.generation++]){
  const {original,book,event}=fixture(),record=captureDiagnostic(book,event);change(original);assert.equal(currentDiagnostic(original,record),false);
 }
 const {book,event}=fixture();book.cells.shift();assert.equal(captureDiagnostic(book,event),null);
});
test('source fingerprints match UTF-8 SHA256 including non-BMP text',async()=>{
 if(!globalThis.crypto)globalThis.crypto=webcrypto;
 assert.equal(await sourceVersion('甲😀'), '073180bf23b2fa6e40f0cbd457994f12cea215841043a9b51ca686c4bec341bc');
});
