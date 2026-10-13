import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
class Node {
 constructor(tag='',className='',text=''){Object.assign(this,{tag,className,textContent:text,children:[],dataset:{},attributes:{},listeners:{},style:{setProperty(key,value){this[key]=value;}},disabled:false});}
 append(...nodes){this.children.push(...nodes);}
 prepend(...nodes){this.children.unshift(...nodes);}
 setAttribute(key,value){this.attributes[key]=value;}
 addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
 fire(type,event={}){for(const fn of this.listeners[type]||[])fn(event);}
 querySelectorAll(){const all=[];const walk=n=>{if(n.dataset?.mutates)all.push(n);for(const c of n.children||[])walk(c);};walk(this);return all;}
}
function harness(type='code',learning=false){
 const cell={id:'test-cell',type,source:'显 1.\n'.repeat(300),outputs:[],status:'idle'};if(learning)cell.generation={prompt:'修改意图'};
 const globals=new Map(),calls=[],views=new Map();
 const context={cell,views,book:{cells:[cell]},activeRun:null,runAllActive:false,transition:false,generationRequest:null,connected:true,session:'session',token:'token',MAX_CELLS:500,hasBook:true,sceneViews:new Map(),
 document:{querySelectorAll:()=>[],createTextNode:text=>({textContent:text})},$:selector=>{if(!globals.has(selector))globals.set(selector,new Node());return globals.get(selector);},
 el:(...args)=>new Node(...args),button:(text,title,handler,cls)=>{const n=new Node('button',cls,text);n.title=title;n.addEventListener('click',handler);return n;},
 copyButton:get=>{const n=new Node('button','copy-input','复制输入');n.addEventListener('click',()=>calls.push(['copy',get()]));return n;},
 buildEditor:(c,v)=>{v.input=new Node('textarea');v.input.value=c.source;return new Node('div','editor-shell');},buildGenerationPanel:()=>new Node('div','generation-panel'),buildHistory:()=>new Node('div','history-panel'),
 renderOutput:()=>{},renderMarkdown:()=>{},markDirty:()=>calls.push(['dirty']),stopBrowserRun:()=>calls.push(['stopBrowser']),stopScenes:()=>calls.push(['stopScenes']),
 runCell:async c=>{context.activeRun={cellId:c.id};context.refreshControls();calls.push(['run',c.id]);return true;},focusNext:()=>{},notice:()=>calls.push(['busy']),resetSession:reason=>{calls.push(['stop',reason]);context.activeRun=null;context.refreshControls();}};
 vm.createContext(context);
 for(const [a,b] of [['function busy()','async function api('],['function appendExecutionControls(','function toggleMarkdown('],['async function runAndMove(','async function runCell(']])vm.runInContext(source.slice(source.indexOf(a),source.indexOf(b)),context);
 const element=context.renderCell(cell);context.refreshControls();return {context,cell,view:views.get(cell.id),element,calls};
}
for(const learning of [false,true])test(`two toolbars surround ${learning?'learning':'ordinary'} source and share state/actions`,async()=>{
 const h=harness('code',learning),{view,context,cell,element,calls}=h;
 assert.equal(view.runs.length,2);assert.equal(view.stops.length,2);assert.equal(view.backendChoices.length,2);
 const names=element.children.map(n=>n.className);assert.ok(names.indexOf('cell-tools cell-footer')>names.indexOf('editor-shell'));assert.ok(names.indexOf('cell-tools cell-footer')<names.indexOf('cell-output'));
 const [top,bottom]=view.backendChoices;bottom.checked=true;bottom.fire('change');assert.equal(cell.execution_backend,'browser-js');assert.ok(top.checked&&bottom.checked);assert.equal(calls.filter(x=>x[0]==='dirty').length,1);
 top.checked=false;top.fire('change');assert.equal(cell.execution_backend,'python');assert.ok(!top.checked&&!bottom.checked);
 view.runs[1].fire('click');view.runs[0].fire('click');assert.equal(calls.filter(x=>x[0]==='run').length,1);assert.ok(view.runs.every(n=>n.disabled));assert.ok(view.stops.every(n=>!n.disabled));assert.ok(view.backendChoices.every(n=>n.disabled));
 view.stops[0].fire('click');assert.deepEqual(calls.filter(x=>x[0]==='stop'),[['stop','stop']]);assert.ok(view.stops.every(n=>n.disabled));assert.ok(view.runs.every(n=>!n.disabled));
 context.transition=true;context.refreshControls();assert.ok(view.stops.every(n=>n.disabled));assert.ok(view.runs.every(n=>n.disabled));
});
test('both copy controls read current raw text without dirtying or executing',()=>{
 const h=harness(),nodes=[];const walk=n=>{if(n.className==='copy-input')nodes.push(n);for(const c of n.children||[])walk(c);};walk(h.element);assert.equal(nodes.length,2);h.view.input.value='中文 😀\r\n';for(const n of nodes)n.fire('click');assert.deepEqual(h.calls,[['copy','中文 😀\r\n'],['copy','中文 😀\r\n']]);
});
test('backend tooltip IDs are unique, described, focus reachable, and dismissible',()=>{
 const h=harness();const ids=[];for(const choice of h.view.backendChoices){ids.push(choice.attributes['aria-describedby']);assert.equal(choice.type,'checkbox');}
 assert.equal(new Set(ids).size,2);
 const wrappers=[];const walk=n=>{if(n.className==='execution-option')wrappers.push(n);for(const c of n.children||[])walk(c);};walk(h.element);
 for(const wrapper of wrappers){const help=wrapper.children[1];wrapper.offsetLeft=180;wrapper.offsetTop=4;wrapper.offsetHeight=27;wrapper.fire('mouseenter');assert.equal(help.style['--tooltip-left'],'180px');assert.equal(help.style.top,help.id.endsWith('-top')?'31px':'auto');assert.ok(ids.includes(help.id));assert.equal(help.attributes.role,'tooltip');assert.match(help.textContent,/独立 Worker/);assert.match(help.textContent,/不共享 Python/);assert.match(help.textContent,/无法强制 64 MiB/);wrapper.fire('keydown',{key:'Escape'});assert.equal(wrapper.dataset.dismissed,'true');wrapper.fire('focusout');assert.equal(wrapper.dataset.dismissed,undefined);}
 const css=fs.readFileSync(new URL('../static/style.css',import.meta.url),'utf8');assert.match(css,/execution-option:focus-within/);assert.ok(!css.includes('.execution-options{'));
});
test('current views refresh after rerender; histories never run and listener count stays bounded',()=>{
 const h=harness('code',true),old=h.view;const element=h.context.renderCell(h.cell),view=h.context.views.get(h.cell.id);assert.notEqual(view,old);assert.equal(view.runs.length,2);assert.equal(view.backendChoices.length,2);
 view.backendChoices[0].checked=true;view.backendChoices[0].fire('change');assert.ok(view.backendChoices.every(n=>n.checked));assert.ok(old.backendChoices.every(n=>!n.checked));assert.equal(h.calls.filter(x=>x[0]==='run').length,0);
 for(const c of view.backendChoices)assert.equal(c.listeners.change.length,1);
});
test('stop is scoped to its running cell or live scene and both copies agree',()=>{
 const h=harness();h.context.activeRun={cellId:'other'};h.context.refreshControls();assert.ok(h.view.stops.every(n=>n.disabled));h.context.activeRun=null;h.context.sceneViews.set('canvas',{cell:h.cell,view:{live:true}});h.context.refreshControls();assert.ok(h.view.stops.every(n=>!n.disabled));h.context.sceneViews.get('canvas').view.live=false;h.context.refreshControls();assert.ok(h.view.stops.every(n=>n.disabled));
});
test('Markdown keeps one edit action and has no execution selector or footer',()=>{
 const h=harness('markdown');assert.equal(h.view.runs.length,1);assert.equal(h.view.stops.length,0);assert.equal(h.view.backendChoices.length,0);assert.ok(!h.element.children.some(n=>n.className==='cell-tools cell-footer'));
});
test('busy backend events cannot mutate the canonical model or create side effects',()=>{
 const h=harness();h.context.activeRun={cellId:h.cell.id};h.context.refreshControls();h.view.backendChoices[1].checked=true;h.view.backendChoices[1].fire('change');assert.equal(h.cell.execution_backend,undefined);assert.ok(h.view.backendChoices.every(n=>!n.checked));assert.deepEqual(h.calls,[]);
});
test('connection and token gating applies identically to both run buttons',()=>{
 const h=harness();h.context.connected=false;h.context.refreshControls();assert.ok(h.view.runs.every(n=>n.disabled));h.cell.execution_backend='browser-js';h.context.refreshControls();assert.ok(h.view.runs.every(n=>!n.disabled));h.context.token='';h.context.refreshControls();assert.ok(h.view.runs.every(n=>n.disabled));h.context.token='token';h.context.session=null;h.context.refreshControls();assert.ok(h.view.runs.every(n=>n.disabled));
});
