import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const replaceSource=source.slice(source.indexOf('async function replaceBook('),source.indexOf('// Markdown is'));
function fixture(api){
 const old={title:'old',cells:[{id:'old',source:'unsaved'}]},nodes=new Map();
 const context={book:old,hasBook:true,session:'old-session',token:'token',transition:false,dirty:true,activeRun:null,generationRequest:null,epoch:3,connected:true,generation:1,cursor:0,lastExecutionCount:0,kernelDead:false,runAllActive:false,
  $:key=>{if(!nodes.has(key))nodes.set(key,{});return nodes.get(key);},api,confirm:()=>false,
  refreshControls(){},cancelGeneration(){},stopScenes(){},clearScene(){},finishActive(){},renderBook(){},runtimeStatus(){},markDirty(){},pollSoon(){},notice(){}};
 vm.createContext(context);vm.runInContext(replaceSource,context);return {context,old,nodes};
}
test('failed new-session request keeps old book and session intact and releases transition',async()=>{
 const {context,old}=fixture(async()=>{throw new Error('offline');});
 await assert.rejects(context.replaceBook({title:'new',cells:[]}),/offline/);
 assert.equal(context.book,old);assert.equal(context.session,'old-session');assert.equal(context.epoch,3);assert.equal(context.transition,false);
});
test('repeated selection during a pending transition creates one session and only closes the old one',async()=>{
 let release;const pending=new Promise(resolve=>release=resolve),calls=[];
 const {context,nodes}=fixture(async(path,method)=>{calls.push([path,method]);return method==='POST'?pending:{};});
 const next={title:'new',cells:[]},first=context.replaceBook(next);
 assert.equal(await context.replaceBook({title:'double-click',cells:[]}),false);release({id:'new-session',generation:1});
 assert.equal(await first,true);assert.equal(context.book,next);assert.equal(context.session,'new-session');assert.equal(context.epoch,4);
 assert.deepEqual(calls,[['/sessions','POST'],['/sessions/old-session','DELETE']]);assert.equal(nodes.get('#start-page').hidden,true);assert.equal(nodes.get('#book-workspace').hidden,false);
});
test('no-token selection produces editable local content without any API calls',async()=>{
 const {context}=fixture(async()=>{throw new Error('must not call');});context.token='';context.session=null;context.hasBook=false;
 const next={title:'offline',cells:[]};await context.replaceBook(next);assert.equal(context.book,next);assert.equal(context.session,null);assert.equal(context.connected,false);assert.equal(context.hasBook,true);
});
test('canceling unsaved replacement has no mutation, including pending generation',()=>{
 const {context,old}=fixture(()=>{});assert.equal(context.confirmReplace(),false);assert.equal(context.book,old);
 context.dirty=false;context.generationRequest={};assert.equal(context.confirmReplace(),false);
 context.hasBook=false;assert.equal(context.confirmReplace(),true);
});
test('startup does not create a default document or kernel session',()=>{
 assert.match(source,/let hasBook=false/);assert.doesNotMatch(source,/let book=welcomeBook/);
 const startup=source.slice(source.lastIndexOf('refreshControls();\nif(!token)'));
 assert.doesNotMatch(startup,/replaceBook|\/sessions|generateCell/);
});
