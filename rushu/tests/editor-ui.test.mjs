import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {analyze,highlight,enterEdit,indentSelection,needsAutoDedent} from '../static/editor.mjs';

// Run the real editor event handlers against a minimal DOM, without a browser.
const app=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const source=app.slice(app.indexOf('function buildEditor('),app.indexOf('// Generation is a separate'));
class Element {
  constructor(){this.style={};this.handlers={};this.children=[];this.value='';this.selectionStart=0;this.selectionEnd=0;this.scrollLeft=0;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(){}
  addEventListener(name,handler){this.handlers[name]=handler;}
  setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;}
  setRangeText(text,start,end){this.value=this.value.slice(0,start)+text+this.value.slice(end);this.setSelectionRange(start+text.length,start+text.length);}
}
function editor(text){
  const cell={source:text,outputs:[]},view={};
  const context={analyze,highlight,enterEdit,indentSelection,needsAutoDedent,
    book:{cells:[cell]},MAX_SOURCE:200000,el:()=>new Element(),document:{createDocumentFragment:()=>new Element()},
    markDirty(){},renderOutput(){},notice(){},runAndMove(){},cell,view};
  vm.createContext(context);vm.runInContext(source+';buildEditor(cell,view)',context);
  const input=view.input;input.setSelectionRange(text.length,text.length);
  return {cell,input,press(key){input.handlers.keydown({key,preventDefault(){}});},
    type(text){input.setRangeText(text,input.selectionStart,input.selectionEnd);input.handlers.input();}};
}
test('actual editor Enter and input handlers indent and dedent symbolic maps',()=>{
  for(const [left,right] of [['{','}'],['｛','｝']]){
    const h=editor('表 取 '+left);h.press('Enter');
    assert.equal(h.input.value,'表 取 '+left+'\n    ');
    h.type(right);assert.equal(h.input.value,'表 取 '+left+'\n'+right);
    assert.equal(h.cell.source,h.input.value);
    assert.equal(h.input.selectionStart,h.input.value.length);
  }
});
test('actual editor defers fullwidth closer dedent until IME composition ends',()=>{
  const h=editor('表 取 ｛\n    ');
  h.input.handlers.compositionstart();h.type('｝');
  assert.equal(h.input.value,'表 取 ｛\n    ｝');
  h.input.handlers.compositionend();assert.equal(h.input.value,'表 取 ｛\n｝');
  assert.equal(h.cell.source,h.input.value);
});
test('actual editor dedents a nested map closer without closing its outer map',()=>{
  const h=editor('表 取 {\n    1: {\n        ');h.type('}');h.type(',');
  assert.equal(h.input.value,'表 取 {\n    1: {\n    },');
  h.press('Enter');assert.ok(h.input.value.endsWith('\n    '));
  h.type('}');assert.ok(h.input.value.endsWith('\n}'));
});
