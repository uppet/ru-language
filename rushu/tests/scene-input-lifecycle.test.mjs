import test from 'node:test';
import assert from 'node:assert/strict';
import {createSceneView} from '../static/scene.mjs';
class Target {
  constructor(){this.listeners=new Map();this.children=[];this.captures=new Set();}
  addEventListener(type,fn){if(!this.listeners.has(type))this.listeners.set(type,new Set());this.listeners.get(type).add(fn);}
  removeEventListener(type,fn){this.listeners.get(type)?.delete(fn);}
  emit(type,event={}){for(const fn of [...(this.listeners.get(type)||[])])fn(event);}
  append(...children){this.children.push(...children);}
  setAttribute(){}
  focus(){this.focused=true;}
  setPointerCapture(id){this.captures.add(id);}
  releasePointerCapture(id){if(this.captures.delete(id))this.emit('lostpointercapture',{pointerId:id});}
  getBoundingClientRect(){return {left:10,top:20,width:200,height:100};}
  getContext(){return {clearRect(){},fillRect(){}};}
}
const frame=()=>({canvas_id:'c',width:400,height:200,fps:60,running:false,handlers:['mouse_down','mouse_up','mouse_move','key_down','key_up'],commands:[]});
const pointer=(more={})=>({pointerId:1,pointerType:'mouse',isPrimary:true,button:0,buttons:1,clientX:60,clientY:45,...more});
const key=(value='a',more={})=>({key:value,code:'Key'+value.toUpperCase(),preventDefault(){},stopPropagation(){},...more});
function harness(t,backend,send){
  const saved={};for(const name of ['document','window','performance','requestAnimationFrame','cancelAnimationFrame','setTimeout','clearTimeout'])saved[name]=globalThis[name];
  const doc=new Target(),win=new Target(),timers=new Map();let time=1000,id=0;
  doc.hidden=false;doc.defaultView=win;doc.createElement=()=>new Target();globalThis.document=doc;globalThis.window=win;globalThis.performance={now:()=>time};
  globalThis.requestAnimationFrame=globalThis.setTimeout=fn=>{timers.set(++id,fn);return id;};globalThis.cancelAnimationFrame=globalThis.clearTimeout=id=>timers.delete(id);
  const events=[],view=createSceneView(frame(),{backend,send:send|| (async event=>events.push(event))});
  t.after(()=>{view.dispose();for(const [name,value] of Object.entries(saved))globalThis[name]=value;});
  const tick=async()=>{time+=1000;const next=[...timers.values()];timers.clear();for(const fn of next)fn();for(let i=0;i<5;i++)await Promise.resolve();};
  const drain=async()=>{for(let i=0;i<80&&timers.size;i++)await tick();assert.equal(timers.size,0);};
  return {doc,win,view,events,tick,drain,timers};
}
for(const backend of ['python','javascript']){
  test(`${backend}: drag-out/window release is bounded, deduplicated and button-correct`,async t=>{
    const h=harness(t,backend);h.view.canvas.emit('pointerdown',pointer({button:2,buttons:2}));assert.equal(h.view.canvas.focused,true);assert.equal(h.view.canvas.captures.size,1);
    h.win.emit('pointerup',pointer({button:2,buttons:0,clientX:10000,clientY:-500}));h.view.canvas.emit('pointerup',pointer({button:2}));await h.drain();
    assert.deepEqual(h.events,[{type:'mouse_down',x:100,y:50,button:2},{type:'mouse_up',x:400,y:0,button:2}]);
  });
  for(const cancellation of ['pointercancel','lostpointercapture','blur','window-blur','hidden'])test(`${backend}: ${cancellation} reconciles once without move`,async t=>{
    const h=harness(t,backend);h.view.canvas.emit('pointerdown',pointer());h.view.canvas.emit('keydown',key());await h.drain();
    h.view.canvas.emit('pointermove',pointer({clientX:80}));
    if(cancellation==='window-blur')h.win.emit('blur');else if(cancellation==='hidden'){h.doc.hidden=true;h.doc.emit('visibilitychange');}else h.view.canvas.emit(cancellation,pointer());
    if(['pointercancel','lostpointercapture'].includes(cancellation))h.view.canvas.emit('blur');
    h.win.emit('pointerup',pointer());h.win.emit('keyup',key());
    if(cancellation==='hidden'){await h.tick();assert.equal(h.events.length,2);h.doc.hidden=false;h.doc.emit('visibilitychange');}
    await h.drain();assert.deepEqual(h.events.map(e=>e.type),['mouse_down','key_down','mouse_up','key_up']);assert.equal(h.events[2].x,140);
  });
  test(`${backend}: queued press survives hide in order and extra touch does not release primary`,async t=>{
    const h=harness(t,backend);h.view.canvas.emit('pointerdown',pointer({pointerType:'touch'}));h.view.canvas.emit('pointerdown',pointer({pointerId:2,pointerType:'touch',isPrimary:false}));h.win.emit('pointerup',pointer({pointerId:2,isPrimary:false}));
    h.doc.hidden=true;h.doc.emit('visibilitychange');await h.tick();assert.equal(h.events.length,0);h.doc.hidden=false;h.doc.emit('visibilitychange');await h.drain();assert.deepEqual(h.events.map(e=>e.type),['mouse_down','mouse_up']);
  });
  test(`${backend}: capacity reserves releases for accepted downs, dropped downs have no up`,async t=>{
    const h=harness(t,backend);for(let i=0;i<30;i++)h.view.canvas.emit('keydown',key(String(i)));h.win.emit('blur');await h.drain();
    const downs=h.events.filter(e=>e.type==='key_down'),ups=h.events.filter(e=>e.type==='key_up');assert.equal(downs.length,8);assert.deepEqual(ups.map(e=>e.key),downs.map(e=>e.key));
  });
  test(`${backend}: in-flight 429 press retries before reserved release under pressure`,async t=>{
    const events=[];let reject;const h=harness(t,backend,event=>{events.push(event);if(events.length===1)return new Promise((_,no)=>reject=no);return Promise.resolve();});
    h.view.canvas.emit('keydown',key('a'));await h.tick();for(let i=0;i<30;i++)h.view.canvas.emit('keydown',key(String(i)));h.win.emit('blur');reject(Object.assign(new Error('busy'),{status:429}));for(let i=0;i<5;i++)await Promise.resolve();await h.drain();
    assert.deepEqual(events[0],events[1]);const accepted=events.slice(1).filter(e=>e.type==='key_down').map(e=>e.key),ups=events.filter(e=>e.type==='key_up').map(e=>e.key);assert.deepEqual(ups,accepted);
  });
  test(`${backend}: key release uses physical identity despite modifiers and ignores repeats`,async t=>{
    const h=harness(t,backend);h.view.canvas.emit('keydown',key('A',{code:'KeyA',shiftKey:true}));h.view.canvas.emit('keydown',key('A',{code:'KeyA',repeat:true}));h.win.emit('keyup',key('a',{code:'KeyA',ctrlKey:true}));h.view.canvas.emit('blur');await h.drain();assert.deepEqual(h.events,[{type:'key_down',key:'A'},{type:'key_up',key:'A'}]);
  });
  test(`${backend}: invalid coordinates/buttons cannot poison payload, cancellation uses last point`,async t=>{
    const h=harness(t,backend);h.view.canvas.emit('pointerdown',pointer({clientX:NaN}));h.view.canvas.emit('pointerdown',pointer({button:4}));h.view.canvas.emit('pointerdown',pointer());h.view.canvas.emit('pointermove',pointer({clientX:Infinity}));h.view.canvas.emit('pointercancel',pointer({clientX:NaN}));await h.drain();assert.deepEqual(h.events,[{type:'mouse_down',x:100,y:50,button:0},{type:'mouse_up',x:100,y:50,button:0}]);
  });
  test(`${backend}: IME, shortcuts and Tab leave native keyboard behavior intact`,async t=>{
    const h=harness(t,backend);let prevented=0;for(const more of [{isComposing:true},{keyCode:229},{key:'Process'},{key:'Tab'},{ctrlKey:true},{metaKey:true},{altKey:true}])h.view.canvas.emit('keydown',key(' ',{...more,preventDefault(){prevented++;}}));await h.drain();assert.equal(prevented,0);assert.deepEqual(h.events,[]);
  });
  test(`${backend}: chorded mouse buttons preserve native mapping`,async t=>{
    const h=harness(t,backend);h.view.canvas.emit('pointerdown',pointer());h.view.canvas.emit('pointermove',pointer({buttons:3}));h.view.canvas.emit('pointermove',pointer({buttons:2}));h.win.emit('pointerup',pointer({button:2,buttons:0}));await h.drain();assert.deepEqual(h.events.filter(e=>e.type!=='mouse_move').map(e=>[e.type,e.button]),[['mouse_down',0],['mouse_down',2],['mouse_up',0],['mouse_up',2]]);
  });
  test(`${backend}: blur cancels an in-flight move retry without replaying drawing`,async t=>{
    const events=[];let reject;const h=harness(t,backend,event=>{events.push(event);return new Promise((_,no)=>reject=no);});h.view.canvas.emit('pointermove',pointer());await h.tick();h.win.emit('blur');reject(Object.assign(new Error('busy'),{status:429}));for(let i=0;i<5;i++)await Promise.resolve();await h.drain();assert.equal(events.length,1);
  });
  test(`${backend}: release-only handlers track presses without inventing down callbacks`,async t=>{
    const h=harness(t,backend);h.view.update({...frame(),handlers:['mouse_up','key_up']});h.view.canvas.emit('pointerdown',pointer());h.view.canvas.emit('keydown',key());await h.drain();assert.deepEqual(h.events,[]);h.win.emit('blur');h.win.emit('pointerup',pointer());h.win.emit('keyup',key());await h.drain();assert.deepEqual(h.events,[{type:'mouse_up',x:100,y:50,button:0},{type:'key_up',key:'a'}]);
  });
  test(`${backend}: stop closes once and discards input even while a callback is pending`,async t=>{
    const events=[];let finish;const h=harness(t,backend,event=>{events.push(event);return event.type==='close'?Promise.resolve():new Promise(yes=>finish=yes);});h.view.canvas.emit('pointerdown',pointer());await h.tick();h.view.canvas.emit('keydown',key());const stop=h.view.root.children[1].children[1];stop.emit('click');stop.emit('click');for(let i=0;i<5;i++)await Promise.resolve();finish();await h.drain();assert.deepEqual(events.map(e=>e.type),['mouse_down','close']);assert.equal(h.view.live,false);
  });
  test(`${backend}: ignored second primary pointer cannot move or release the accepted stream`,async t=>{
    const h=harness(t,backend);h.view.canvas.emit('pointerdown',pointer());h.view.canvas.emit('pointerdown',pointer({pointerId:2,pointerType:'pen'}));h.view.canvas.emit('pointermove',pointer({pointerId:2,pointerType:'pen',clientX:150}));h.win.emit('pointerup',pointer({pointerId:2}));h.view.canvas.emit('pointercancel',pointer());await h.drain();assert.deepEqual(h.events,[{type:'mouse_down',x:100,y:50,button:0},{type:'mouse_up',x:100,y:50,button:0}]);
  });
  test(`${backend}: final window release clears remaining chord if capture was unavailable`,async t=>{
    const h=harness(t,backend);h.view.canvas.setPointerCapture=()=>{throw new Error('unsupported');};h.view.canvas.emit('pointerdown',pointer());h.view.canvas.emit('pointermove',pointer({buttons:3}));h.win.emit('pointerup',pointer({button:2,buttons:0}));h.win.emit('blur');await h.drain();const ups=h.events.filter(e=>e.type==='mouse_up');assert.deepEqual(ups.map(e=>e.button).sort(),[0,2]);assert.equal(ups.length,2);
  });
  for(const action of ['deactivate','dispose','replace','error'])test(`${backend}: ${action} detaches global input and never resumes stale callbacks`,async t=>{
    let finish;const events=[];const h=harness(t,backend,event=>{events.push(event);return new Promise((yes,no)=>finish=action==='error'?()=>no(new Error('budget')):yes);});
    h.view.canvas.emit('pointerdown',pointer());await h.tick();h.view.canvas.emit('keydown',key());
    if(action==='replace')h.view.update({...frame(),canvas_id:'new'});else if(action!=='error')h.view[action]();finish();for(let i=0;i<5;i++)await Promise.resolve();
    h.win.emit('blur');h.win.emit('pointerup',pointer());h.win.emit('keyup',key());h.doc.emit('visibilitychange');await h.drain();assert.equal(events.length,1);assert.equal(h.view.live,false);assert.equal([...h.win.listeners.values()].reduce((n,s)=>n+s.size,0),0);assert.equal([...h.doc.listeners.values()].reduce((n,s)=>n+s.size,0),0);
  });
}
