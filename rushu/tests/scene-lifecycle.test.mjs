import test from 'node:test';
import assert from 'node:assert/strict';
import {createSceneView,backingStorePixels,MAX_BACKING_PIXELS} from '../static/scene.mjs';
class Node {
  constructor(tag){this.tagName=tag;this.children=[];this.listeners=new Map();this.width=300;this.height=150;this.hidden=false;this.style={};}
  append(...nodes){this.children.push(...nodes);}
  setAttribute(){}
  addEventListener(name,fn){this.listeners.set(name,fn);}
  removeEventListener(name){this.listeners.delete(name);}
  emit(name,event={}){return this.listeners.get(name)?.(event);}
  focus(){}
  getBoundingClientRect(){return {left:0,top:0,width:320,height:200};}
  getContext(){return {fillRect(){},fillText(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},rect(){},ellipse(){},fill(){}};}
}
const fakeDocument=()=>({hidden:false,listeners:new Map(),createElement:tag=>new Node(tag),addEventListener(name,fn){this.listeners.set(name,fn);},removeEventListener(name){this.listeners.delete(name);}});
const scene=(id='view',size=320)=>({canvas_id:id,width:size,height:size,fps:30,running:false,handlers:[],commands:[{op:'background',color:'#ffffff'}]});
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function setup(t){const prior=globalThis.document,cleanup=[];globalThis.document=fakeDocument();t.after(()=>{for(const fn of cleanup)fn();globalThis.document=prior;});return fn=>cleanup.push(fn);}
test('LRU caps actual backing pixels; restoration only replays static commands',t=>{
  setup(t);const views=[];let calls=0;
  for(let i=0;i<6;i++)views.push(createSceneView(scene('canvas-'+i,2048),{historical:true,send:()=>calls++}));
  assert.ok(backingStorePixels()<=MAX_BACKING_PIXELS);
  assert.equal(views[0].canvas.width,0);assert.equal(views[0].canvas.hidden,true);
  const restore=views[0].root.children[1].children[2];assert.equal(restore.hidden,false);restore.emit('click');
  assert.equal(views[0].canvas.width,2048);assert.equal(views[0].canvas.hidden,false);assert.equal(calls,0);
  assert.ok(backingStorePixels()<=MAX_BACKING_PIXELS);
  for(const view of views)view.dispose();assert.equal(backingStorePixels(),0);
});
test('pointer movement omits negative PointerEvent.button and remains single-flight',async t=>{
  const cleanup=setup(t);const payloads=[];let finish;const s=scene();s.handlers=['mouse_move'];
  const view=createSceneView(s,{send:event=>{payloads.push(event);return new Promise(resolve=>finish=resolve);}});cleanup(()=>view.dispose());
  view.canvas.emit('pointermove',{clientX:20,clientY:40,button:-1});await wait(60);
  assert.equal(payloads.length,1);assert.equal(payloads[0].type,'mouse_move');assert.equal(Object.hasOwn(payloads[0],'button'),false);
  for(let i=0;i<50;i++)view.canvas.emit('pointermove',{clientX:i,clientY:40,button:-1});await wait(50);assert.equal(payloads.length,1);
  finish();await wait(60);assert.equal(payloads.length,2);assert.equal(payloads[1].x,49);finish();view.deactivate();
});
test('definite 429 is retried with a bound instead of permanently closing the canvas',async t=>{
  const cleanup=setup(t);const s=scene();s.handlers=['mouse_down'];let calls=0;const errors=[];
  const view=createSceneView(s,{send:async()=>{calls++;if(calls===1)throw Object.assign(new Error('限流'),{status:429});},onError:e=>errors.push(e)});cleanup(()=>view.dispose());
  view.canvas.emit('pointerdown',{clientX:20,clientY:40,button:0});await wait(260);
  assert.equal(calls,2);assert.equal(errors.length,0);assert.equal(view.live,true);
});
test('hidden documents clear pending events and disposal cancels scheduled work',async t=>{
  setup(t);const s=scene();s.handlers=['mouse_move'];let calls=0;
  const view=createSceneView(s,{send:async()=>calls++});
  document.hidden=true;document.listeners.get('visibilitychange')();
  view.canvas.emit('pointermove',{clientX:20,clientY:40,button:-1});await wait(60);assert.equal(calls,0);
  view.dispose();document.hidden=false;await wait(60);assert.equal(calls,0);assert.equal(backingStorePixels(),0);
});

test('JavaScript animation uses RAF, supports 60 fps, and retains one flight',async t=>{
  setup(t);const previousRAF=globalThis.requestAnimationFrame,previousCancel=globalThis.cancelAnimationFrame,previousPerformance=globalThis.performance;
  let now=1000,next=0,calls=0,resolve;const callbacks=new Map();
  globalThis.performance={now:()=>now};globalThis.requestAnimationFrame=fn=>{callbacks.set(++next,fn);return next;};globalThis.cancelAnimationFrame=id=>callbacks.delete(id);
  t.after(()=>{globalThis.requestAnimationFrame=previousRAF;globalThis.cancelAnimationFrame=previousCancel;globalThis.performance=previousPerformance;});
  const s={...scene(),fps:60,running:true,handlers:['frame']};
  const view=createSceneView(s,{backend:'javascript',send:()=>{calls++;return new Promise(done=>resolve=done);}});
  function frame(){now+=1000/60;const list=[...callbacks.values()];callbacks.clear();for(const fn of list)fn(now);}
  frame();assert.equal(calls,1);assert.equal(callbacks.size,0);for(let i=0;i<10;i++)frame();assert.equal(calls,1);
  resolve();await Promise.resolve();await Promise.resolve();assert.equal(callbacks.size,1);frame();assert.equal(calls,2);
  resolve();await Promise.resolve();await Promise.resolve();view.dispose();assert.equal(callbacks.size,0);frame();assert.equal(calls,2);
});
