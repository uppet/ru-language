/** Declarative local canvas output. No script, URLs, HTML or saved callbacks. */
export const MAX_COMMANDS=2048,MAX_FRAME_BYTES=262144;
const eventNames=['frame','mouse_down','mouse_up','mouse_move','key_down','key_up'];
// Only complete ASCII six/eight-digit hex values cross the worker/history boundary.
const color=value=>typeof value==='string'&&[7,9].includes(value.length)&&/^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$/.test(value);
const codePoints=value=>Array.from(value).length;
const textEnums={align:['left','center','right'],baseline:['top','middle','bottom','alphabetic']};
function textState(c){
  const state={};
  for(const [key,values] of Object.entries(textEnums)){
    if(!Object.hasOwn(c,key))continue;
    if(c.op!=='text'||typeof c[key]!=='string'||!values.includes(c[key]))throw new Error('画布文字对齐无效。');
    state[key]=c[key];
  }
  return state;
}
// Account for actual backing stores, not CSS boxes or assumed device ratios.
export const MAX_BACKING_PIXELS=16*1024*1024;
const backingViews=new Map();
let backingPixels=0;
function releaseBacking(entry){if(!backingViews.has(entry))return;backingPixels-=backingViews.get(entry);backingViews.delete(entry);entry.release();}
function reserveGroup(group){
  const total=[...group.values()].reduce((a,b)=>a+b,0);
  if(total>MAX_BACKING_PIXELS)throw new Error('画布实际像素工作集超过 16 Mi。');
  for(const entry of group.keys())entry.pinned=true;
  const added=[...group].reduce((sum,[entry,pixels])=>sum+pixels-(backingViews.get(entry)||0),0);
  while(backingPixels+added>MAX_BACKING_PIXELS){
    const entries=[...backingViews.keys()].filter(entry=>!entry.pinned);
    const victim=entries.find(entry=>entry.kind!=='main')||entries[0];
    if(!victim)throw new Error('画布实际像素预算不足。');releaseBacking(victim);
  }
  for(const [entry,pixels] of group){backingPixels+=pixels-(backingViews.get(entry)||0);backingViews.set(entry,pixels);}
}
export function backingStorePixels(){return backingPixels;}
const finite=value=>typeof value==='number'&&Number.isFinite(value)&&Math.abs(value)<=100000;
const identity=[1,0,0,1,0,0];
function matrix(value){if(!Array.isArray(value)||value.length!==6||!Array.from(value).every(finite))throw new Error('画布变换无效。');return value.slice();}
function drawingState(c,strict=false){
  const state={};
  if(Object.hasOwn(c,'transform'))state.transform=matrix(c.transform);
  if(Object.hasOwn(c,'clips')){
    if(!Array.isArray(c.clips)||c.clips.length>32)throw new Error('画布裁剪无效。');
    state.clips=Array.from(c.clips,clip=>{
      if(!clip||typeof clip!=='object'||Array.isArray(clip)||!['x','y','width','height'].every(key=>finite(clip[key]))||clip.width<0||clip.height<0)throw new Error('画布裁剪无效。');
      if(strict)exact(clip,['x','y','width','height','transform']);
      return {x:clip.x,y:clip.y,width:clip.width,height:clip.height,transform:matrix(clip.transform)};
    });
  }
  return state;
}
const bytes=value=>new TextEncoder().encode(JSON.stringify(value)).length;
const resourceId=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(value);
function exact(value,fields){if(Object.keys(value).some(key=>!fields.includes(key)))throw new Error('画布资源含不支持的字段。');}
function validateCommands(commands,{strict=false,resources=null}={}){
  return Array.from(commands,command=>{
    if(!command||typeof command!=='object'||Array.isArray(command))throw new Error('画布指令无效。');
    const c=command;
    if(c.op==='image'){
      exact(c,['op','resource','x','y','transform','clips']);
      if(!resources||!resources.has(c.resource)||!finite(c.x)||!finite(c.y))throw new Error('画布图像引用无效。');
      return {op:'image',resource:c.resource,x:c.x,y:c.y,...drawingState(c,true)};
    }
    const names={background:[],line:['x1','y1','x2','y2','width'],rect:['x','y','width','height','stroke_width'],ellipse:['x','y','width','height','stroke_width'],arc:['x','y','width','height','start','sweep','stroke_width'],sector:['x','y','width','height','start','sweep','stroke_width'],text:['x','y','size'],polygon:['stroke_width'],polyline:['stroke_width'],bezier:['x1','y1','cx1','cy1','cx2','cy2','x2','y2','stroke_width']};
    if(typeof c.op!=='string'||!Object.hasOwn(names,c.op)||!names[c.op].every(key=>finite(c[key])))throw new Error('画布坐标无效。');
    if(strict){const extras=c.op==='background'?['color']:c.op==='line'?['color']:c.op==='text'?['text','color','align','baseline']:c.op==='polygon'||c.op==='polyline'?['points','fill','stroke']:['fill','stroke'];exact(c,['op',...names[c.op],...extras,...(c.op==='background'?[]:['transform','clips'])]);}
    const state={...drawingState(c,strict),...textState(c)};
    if(c.op==='polygon'||c.op==='polyline'){
      const open=c.op==='polyline',label=open?'折线':'多边形';
      if(!Array.isArray(c.points)||c.points.length<(open?2:3)||c.points.length>256)throw new Error(`画布${label}无效。`);
      const points=Array.from({length:c.points.length},(_,index)=>{const point=c.points[index];if(!Object.hasOwn(c.points,index)||!Array.isArray(point)||point.length!==2||!Object.hasOwn(point,0)||!Object.hasOwn(point,1)||!finite(point[0])||!finite(point[1]))throw new Error(`画布${label}坐标无效。`);return [point[0],point[1]];});
      if(c.stroke_width<1||c.stroke_width>256||![c.fill,c.stroke].every(x=>x===''||color(x))||(open&&c.fill!==''))throw new Error('图形尺寸或颜色无效。');
      return {op:c.op,points,fill:c.fill.toLowerCase(),stroke:c.stroke.toLowerCase(),stroke_width:c.stroke_width,...state};
    }
    if(c.op==='bezier'){
      if(c.fill!==''||c.stroke_width<1||c.stroke_width>256||!(c.stroke===''||color(c.stroke)))throw new Error('图形尺寸或颜色无效。');
      return {op:c.op,x1:c.x1,y1:c.y1,cx1:c.cx1,cy1:c.cy1,cx2:c.cx2,cy2:c.cy2,x2:c.x2,y2:c.y2,fill:'',stroke:c.stroke.toLowerCase(),stroke_width:c.stroke_width,...state};
    }
    if(c.op==='rect'||c.op==='ellipse'||c.op==='arc'||c.op==='sector'){
      if(c.width<0||c.height<0||c.stroke_width<1||c.stroke_width>256||![c.fill,c.stroke].every(x=>x===''||color(x))||(c.op==='arc'&&c.fill!==''))throw new Error('图形尺寸或颜色无效。');
      const angles=c.op==='arc'||c.op==='sector'?{start:c.start,sweep:c.sweep}:{};
      return {op:c.op,x:c.x,y:c.y,width:c.width,height:c.height,...angles,fill:c.fill.toLowerCase(),stroke:c.stroke.toLowerCase(),stroke_width:c.stroke_width,...state};
    }
    if(!(c.color===''&&c.op!=='background')&&!color(c.color))throw new Error('画布颜色无效。');
    if(c.op==='background')return {op:c.op,color:c.color.toLowerCase()};
    if(c.op==='line'){if(c.width<=0||c.width>256)throw new Error('画布线宽无效。');return {op:c.op,x1:c.x1,y1:c.y1,x2:c.x2,y2:c.y2,color:c.color.toLowerCase(),width:c.width,...state};}
    if(typeof c.text!=='string'||codePoints(c.text)>4096||c.size<=0||c.size>256)throw new Error('画布文字无效。');
    return {op:c.op,x:c.x,y:c.y,text:c.text,color:c.color.toLowerCase(),size:c.size,...state};
  });
}
export function validateScene(value) {
  if(!value||typeof value!=='object'||Array.isArray(value)||typeof value.canvas_id!=='string'||!/^[\w-]{1,128}$/.test(value.canvas_id))throw new Error('画布标识无效。');
  if(!Number.isInteger(value.width)||!Number.isInteger(value.height)||value.width<1||value.height<1||value.width>2048||value.height>2048)throw new Error('画布尺寸无效（最大 2048 × 2048）。');
  if(!Array.isArray(value.commands)||value.commands.length>MAX_COMMANDS)throw new Error('画布指令过多。');
  if(new TextEncoder().encode(JSON.stringify(value)).length>MAX_FRAME_BYTES)throw new Error('画布帧过大。');
  let resources,resourceMap=new Map();
  if(Object.hasOwn(value,'resources')){
    if(!Array.isArray(value.resources)||value.resources.length>8||bytes(value.resources)>131072)throw new Error('画布缓存定义超过 8 张或 128 KiB。');
    let pixels=0;
    resources=Array.from(value.resources,r=>{
      if(!r||typeof r!=='object'||Array.isArray(r))throw new Error('画布缓存无效。');
      exact(r,['id','kind','width','height','commands']);
      if(!resourceId(r.id)||resourceMap.has(r.id)||r.kind!=='drawing'||!Number.isInteger(r.width)||!Number.isInteger(r.height)||r.width<1||r.height<1||r.width>2048||r.height>2048)throw new Error('画布缓存标识或尺寸无效。');
      pixels+=r.width*r.height;if(pixels>4194304)throw new Error('画布缓存像素超过 4 Mi。');
      if(!Array.isArray(r.commands)||r.commands.length>2047)throw new Error('单张缓存最多 2047 条指令。');
      const resource={id:r.id,kind:'drawing',width:r.width,height:r.height,commands:validateCommands(r.commands,{strict:true})};
      resourceMap.set(r.id,resource);return resource;
    });
    if(bytes(resources)>131072)throw new Error('画布缓存定义超过 128 KiB。');
  }
  const commands=validateCommands(value.commands,{resources:resourceMap});
  const referenced=new Set(commands.filter(c=>c.op==='image').map(c=>c.resource));
  if(referenced.size!==resourceMap.size)throw new Error('画布含未引用的缓存。');
  if(commands.length+[...resourceMap.values()].reduce((n,r)=>n+r.commands.length,0)>MAX_COMMANDS)throw new Error('画布及缓存合计指令超过 2048。');
  if(!Array.isArray(value.handlers)||!value.handlers.every(x=>eventNames.includes(x)))throw new Error('画布交互无效。');
  if(!Number.isInteger(value.fps)||value.fps<1||value.fps>60)throw new Error('画布帧率无效。');
  if(typeof value.running!=='boolean')throw new Error('画布运行状态无效。');
  const scene={...(resources===undefined?{}:{resources}),canvas_id:value.canvas_id,width:value.width,height:value.height,commands,fps:value.fps,handlers:[...new Set(value.handlers)],running:value.running};
  // Both wire input and canonical snapshots must fit, even when input JSON omits properties.
  if(new TextEncoder().encode(JSON.stringify(scene)).length>MAX_FRAME_BYTES)throw new Error('画布帧过大。');
  return scene;
}
function renderCommands(ctx,scene,resources=new Map()) {
  for(const c of scene.commands){
    // Canvas resizing above resets state. Legacy commands need no new context APIs.
    const hasState=c.op!=='background'&&(c.transform||c.clips?.length);
    const scoped=hasState||(typeof ctx.save==='function'&&typeof ctx.restore==='function');
    if(scoped)ctx.save();
    try{
      if(hasState){
        for(const clip of c.clips||[]){ctx.setTransform(...clip.transform);ctx.beginPath();ctx.rect(clip.x,clip.y,clip.width,clip.height);ctx.clip();}
        ctx.setTransform(...(c.transform||identity));
      }
      // Each background replaces earlier drawing, including historical scenes
      // with multiple backgrounds. Scoped primitives cannot leak a clip/matrix.
      if(c.op==='background'){ctx.clearRect(0,0,scene.width,scene.height);ctx.fillStyle=c.color;ctx.fillRect(0,0,scene.width,scene.height);}
      else if(c.op==='image'){ctx.drawImage(resources.get(c.resource).canvas,c.x,c.y);}
      else if(c.op==='text'){if(!c.color)continue;ctx.fillStyle=c.color;ctx.font=`${c.size}px sans-serif`;ctx.textAlign=c.align??'left';ctx.textBaseline=c.baseline??'top';ctx.fillText(c.text,c.x,c.y);}
      else {if((c.op==='arc'||c.op==='sector')&&c.sweep===0)continue;
        ctx.beginPath();if(c.op==='line'){if(!c.color)continue;ctx.moveTo(c.x1,c.y1);ctx.lineTo(c.x2,c.y2);ctx.strokeStyle=c.color;ctx.lineWidth=c.width;ctx.stroke();}
        else {
          if(c.op==='rect')ctx.rect(c.x,c.y,c.width,c.height);
          else if(c.op==='polygon'||c.op==='polyline'){ctx.moveTo(...c.points[0]);for(const point of c.points.slice(1))ctx.lineTo(...point);if(c.op==='polygon')ctx.closePath();}
          else if(c.op==='bezier'){ctx.moveTo(c.x1,c.y1);ctx.bezierCurveTo(c.cx1,c.cy1,c.cx2,c.cy2,c.x2,c.y2);}
          else if((c.op==='arc'||c.op==='sector')&&Math.abs(c.sweep)<Math.PI*2){
            const cx=c.x+c.width/2,cy=c.y+c.height/2;
            if(c.op==='sector')ctx.moveTo(cx,cy);
            ctx.ellipse(cx,cy,c.width/2,c.height/2,0,c.start,c.start+c.sweep,c.sweep<0);
            if(c.op==='sector')ctx.closePath();
          }
          // Complete turns use exactly the legacy ellipse path, with no radial seam.
          else ctx.ellipse(c.x+c.width/2,c.y+c.height/2,c.width/2,c.height/2,0,0,Math.PI*2);
          if(c.fill){ctx.fillStyle=c.fill;ctx.fill();}if(c.stroke&&c.stroke_width>0){ctx.strokeStyle=c.stroke;ctx.lineWidth=c.stroke_width;ctx.stroke();}}
      }
    }finally{if(scoped)ctx.restore();}
  }
}
// Canonical immutable values are trusted only by identity inside this module.
const snapshots=new WeakSet();
function freeze(value){if(value&&typeof value==='object'){for(const child of Object.values(value))freeze(child);Object.freeze(value);}return value;}
export function canonicalScene(value){if(snapshots.has(value))return value;const scene=freeze(validateScene(value));snapshots.add(scene);return scene;}
function surface(canvas,kind,release=()=>{},reset=true){
  if(reset){canvas.width=0;canvas.height=0;}
  return {canvas,kind,pinned:false,release(){canvas.width=0;canvas.height=0;release();}};
}
function context(entry,width,height){
  if(entry.canvas.width!==width)entry.canvas.width=width;
  if(entry.canvas.height!==height)entry.canvas.height=height;
  const ctx=entry.canvas.getContext('2d');if(!ctx)throw new Error('浏览器不支持二维画布。');return ctx;
}
function renderer(canvas,onEvict=()=>{},previous=null){
  const make=kind=>surface((canvas.ownerDocument||globalThis.document).createElement('canvas'),kind);
  const main=surface(canvas,'main',onEvict,!previous);let cache=new Map(),stage=null,committed=previous;
  if(previous){
    // Adopt already-visible standalone pixels without clearing them. Their
    // backing joins the same ledger before any candidate allocation.
    try{reserveGroup(new Map([[main,previous.width*previous.height]]));}
    finally{main.pinned=false;}
  }
  function releaseAux(){for(const item of cache.values())releaseBacking(item);cache.clear();if(stage)releaseBacking(stage);stage=null;}
  function paint(value){
    const scene=canonicalScene(value);if(scene===committed&&backingViews.has(main))return scene;
    if(committed&&backingViews.has(main)&&(scene.width!==committed.width||scene.height!==committed.height||scene.canvas_id!==committed.canvas_id))throw new Error('画布尺寸或身份变化需要新的视图。');
    const next=new Map(),created=[],group=new Map([[main,scene.width*scene.height]]);
    let candidateStage=stage;if(!candidateStage||!backingViews.has(candidateStage)){candidateStage=make('staging');created.push(candidateStage);}
    group.set(candidateStage,scene.width*scene.height);
    for(const resource of scene.resources||[]){const recipe=JSON.stringify(resource);let item=cache.get(resource.id);
      if(!item||!backingViews.has(item)||item.recipe!==recipe){item=make('cache');item.recipe=recipe;created.push(item);}
      next.set(resource.id,item);group.set(item,resource.width*resource.height);
    }
    try{
      reserveGroup(group);
      for(const resource of scene.resources||[]){const item=next.get(resource.id);if(created.includes(item)){const ctx=context(item,resource.width,resource.height);renderCommands(ctx,resource);}}
      const ctx=context(candidateStage,scene.width,scene.height);
      // A resized staging surface resets even clips/state after a failed render.
      candidateStage.canvas.width=scene.width;renderCommands(ctx,scene,next);
      const visible=context(main,scene.width,scene.height);
      try{visible.save();visible.setTransform(1,0,0,1,0,0);visible.globalAlpha=1;visible.globalCompositeOperation='copy';visible.drawImage(candidateStage.canvas,0,0);}
      catch(error){error.graphicsCommitFailed=true;throw error;}finally{try{visible.restore();}catch(error){error.graphicsCommitFailed=true;throw error;}}
      for(const item of cache.values())if(![...next.values()].includes(item))releaseBacking(item);
      cache=next;stage=candidateStage;committed=scene;return scene;
    }catch(error){for(const item of created)releaseBacking(item);if(!committed)releaseBacking(main);throw error;}
    finally{for(const entry of group.keys())entry.pinned=false;}
  }
  return {paint,releaseAux,pinBacking(value){main.pinned=value;},dispose(){releaseAux();releaseBacking(main);},get scene(){return committed;}};
}
const standaloneRenderers=new WeakMap(),standaloneSnapshots=new WeakMap();
export function drawScene(canvas,value){
  const scene=validateScene(value);
  // Legacy standalone callers keep their existing direct primitive path.
  if(!scene.resources?.length&&!standaloneRenderers.has(canvas)){canvas.width=scene.width;canvas.height=scene.height;const ctx=canvas.getContext('2d');if(!ctx)throw new Error('浏览器不支持二维画布。');renderCommands(ctx,scene);standaloneSnapshots.set(canvas,canonicalScene(scene));return scene;}
  let instance=standaloneRenderers.get(canvas);if(!instance){instance=renderer(canvas,()=>{},standaloneSnapshots.get(canvas)||null);standaloneRenderers.set(canvas,instance);standaloneSnapshots.delete(canvas);}return instance.paint(scene);
}
/** Release a standalone drawScene owner, its recipes and all backing stores.
 * Does not affect createSceneView ownership; those callers use view.dispose(). */
export function disposeScene(canvas){
  const instance=standaloneRenderers.get(canvas),legacy=standaloneSnapshots.delete(canvas);
  standaloneRenderers.delete(canvas);
  if(instance)instance.dispose();else if(legacy){canvas.width=0;canvas.height=0;}
}
/** send resolves after the server's graphics_done, not merely HTTP acceptance. */
export function createSceneView(value,{send=async()=>{},historical=false,onError=()=>{},backend='python'}={}) {
  let scene=canonicalScene(value),disposed=false,inFlight=false,timer=null,pendingMove=null,queue=[],live=!historical,lastDispatch=0,failure='',suspended=false,retryAt=0,retryEvent=null,moveEpoch=0;
  // Each held input reserves a queue slot for its release, even under overload.
  const pointers=new Map(),keys=new Map(),MAX_INPUTS=16;
  const root=document.createElement('section');root.className='scene-output';
  const canvas=document.createElement('canvas');canvas.tabIndex=0;canvas.setAttribute('aria-label','如观画布；点击或按 Tab 聚焦后可使用键盘');
  const toolbar=document.createElement('div');toolbar.className='scene-toolbar';
  const status=document.createElement('span');status.setAttribute('aria-live','polite');
  const stop=document.createElement('button');stop.type='button';stop.textContent='停止画布';
  const restore=document.createElement('button');restore.type='button';restore.textContent='重新查看画面';restore.hidden=true;
  toolbar.append(status,stop,restore);root.append(canvas,toolbar);
  const painter=renderer(canvas,()=>{deactivate();suspended=true;canvas.hidden=true;restore.hidden=false;label();});
  const listeners=[];
  function listen(type,fn,target=canvas){if(!target?.addEventListener)return;target.addEventListener(type,fn);listeners.push([target,type,fn]);}
  function unlisten(){for(const [target,type,fn] of listeners)target.removeEventListener(type,fn);listeners.length=0;}
  function label(){status.textContent=suspended?'画面已暂存，点击重新查看':failure|| (historical?'历史画布 · 重新运行后可交互':!live?'画布已停止':scene.running?'动画运行中 · 聚焦画布可交互':scene.handlers.some(x=>x!=='frame')?'可交互 · 点击画布或按 Tab 聚焦':'静态画布');stop.hidden=!live||!scene.handlers.length;}
  function cancelSchedule(){if(timer===null)return;if(backend==='javascript')cancelAnimationFrame(timer);else clearTimeout(timer);timer=null;}
  function schedule(){if(timer!==null)return;if(!live||disposed||inFlight||document.hidden)return;if(!retryEvent&&!queue.length&&!pendingMove&&!(scene.running&&scene.handlers.includes('frame')))return;
    const fire=()=>{timer=null;const now=performance.now();
      if(backend==='javascript'&&now+1<Math.max(lastDispatch+1000/scene.fps,retryAt)){schedule();return;}
      const next=retryEvent||queue.shift()||pendingMove||(scene.running&&scene.handlers.includes('frame')?{type:'frame'}:null);if(next===retryEvent)retryEvent=null;if(next===pendingMove)pendingMove=null;if(next)dispatch(next);};
    timer=backend==='javascript'?requestAnimationFrame(fire):setTimeout(fire,Math.max(0,Math.ceil(1000/scene.fps)+2-(performance.now()-lastDispatch),retryAt-performance.now()));}

  async function dispatch(event){if(!live||disposed||document.hidden)return;if(inFlight)return;inFlight=true;lastDispatch=performance.now();const dispatchedMoveEpoch=moveEpoch;
    try{await send(event);}catch(error){if(disposed||!live)return;if(error.status===429){retryAt=performance.now()+100;if(event.type!=='frame'&&(event.type!=='mouse_move'||dispatchedMoveEpoch===moveEpoch))retryEvent=event;}else{deactivate();failure='画布交互中断：'+error.message;onError(error);}}
    finally{inFlight=false;if(!disposed&&live)schedule();label();}}
  function heldCount(){let count=keys.size;for(const buttons of pointers.values())count+=buttons.size;return count;}
  function room(slots=1){if(queue.length+heldCount()+slots<=MAX_INPUTS)return true;failure='交互较快，部分输入已忽略';label();return false;}
  function enqueue(event){if(!live||disposed||document.hidden)return false;if(event.type==='mouse_move')pendingMove=event;else if(event.type!=='frame'){if(!room())return false;queue.push(event);}if(!inFlight)schedule();return true;}
  function position(event,fallback){const r=canvas.getBoundingClientRect();if(!r.width||!r.height||!Number.isFinite(event.clientX)||!Number.isFinite(event.clientY))return fallback;
    const x=(event.clientX-r.left)*scene.width/r.width,y=(event.clientY-r.top)*scene.height/r.height;
    return Number.isFinite(x)&&Number.isFinite(y)?{x:Math.max(0,Math.min(scene.width,x)),y:Math.max(0,Math.min(scene.height,y))}:fallback;}
  function releasePointer(id,button,event){const buttons=pointers.get(id),held=buttons?.get(button);if(!held)return;
    buttons.delete(button);if(!buttons.size){pointers.delete(id);try{canvas.releasePointerCapture?.(id);}catch{}}
    if(scene.handlers.includes('mouse_up'))queue.push({type:'mouse_up',...position(event||{},held),button});schedule();}
  function pressPointer(event,button=event.button){if(!live||disposed||document.hidden||event.isPrimary===false||!Number.isInteger(button)||button<0||button>2)return;
    if(!scene.handlers.some(type=>type.startsWith('mouse_')))return;
    canvas.focus({preventScroll:true});const id=event.pointerId??1;if(pointers.size&&!pointers.has(id))return;const buttons=pointers.get(id)||new Map();if(buttons.has(button))return;
    const point=position(event);if(!point||!room(scene.handlers.includes('mouse_down')?2:1))return;
    buttons.set(button,point);pointers.set(id,buttons);try{canvas.setPointerCapture?.(id);}catch{}
    if(scene.handlers.includes('mouse_down'))queue.push({type:'mouse_down',...point,button});schedule();}
  function movePointer(event){if(!live||disposed||document.hidden||event.isPrimary===false)return;const id=event.pointerId??1;if(pointers.size&&!pointers.has(id))return;const buttons=pointers.get(id);
    if(buttons){for(const [button,held] of buttons)Object.assign(held,position(event,held));
      // Mouse chords arrive as pointermove rather than another pointerdown/up.
      if(event.pointerType==='mouse'&&Number.isInteger(event.buttons))for(const [button,mask] of [[0,1],[1,4],[2,2]]){
        if(event.buttons&mask){if(!pointers.get(id)?.has(button))pressPointer(event,button);}else releasePointer(id,button,event);
      }}
    const point=position(event);if(point&&scene.handlers.includes('mouse_move'))enqueue({type:'mouse_move',...point});}
  function releaseKey(id){const key=keys.get(id);if(key===undefined)return;keys.delete(id);if(scene.handlers.includes('key_up'))queue.push({type:'key_up',key});schedule();}
  function releaseInputs(){moveEpoch++;pendingMove=null;if(retryEvent?.type==='mouse_move')retryEvent=null;for(const [id,buttons] of [...pointers])for(const button of [...buttons.keys()])releasePointer(id,button);for(const id of [...keys.keys()])releaseKey(id);}
  listen('pointermove',movePointer);
  listen('pointerdown',pressPointer);
  const pointerUp=event=>{const id=event.pointerId??1;releasePointer(id,event.button,event);if(event.buttons===0)for(const button of [...(pointers.get(id)?.keys()||[])])releasePointer(id,button,event);};
  const pointerCancel=event=>{const id=event.pointerId??1;if(!pointers.has(id))return;moveEpoch++;for(const button of [...(pointers.get(id)?.keys()||[])])releasePointer(id,button);pendingMove=null;if(retryEvent?.type==='mouse_move')retryEvent=null;};
  listen('pointerup',pointerUp);listen('pointercancel',pointerCancel);listen('lostpointercapture',pointerCancel);
  const win=document.defaultView||globalThis.window;
  listen('pointerup',pointerUp,win);listen('pointercancel',pointerCancel,win);
  listen('keydown',event=>{if(!live||disposed||document.hidden||event.ctrlKey||event.metaKey||event.altKey||event.key==='Tab'||event.repeat||event.isComposing||event.keyCode===229||event.key==='Process'||typeof event.key!=='string')return;
    if(!scene.handlers.includes('key_down')&&!scene.handlers.includes('key_up'))return;
    const id=event.code||event.key;if(keys.has(id))return;if(!room(scene.handlers.includes('key_down')?2:1))return;
    const key=Array.from(event.key).slice(0,64).join('');keys.set(id,key);
    if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight',' '].includes(event.key))event.preventDefault();event.stopPropagation();
    if(scene.handlers.includes('key_down'))queue.push({type:'key_down',key});schedule();});
  const keyUp=event=>releaseKey(event.code||event.key);
  listen('keyup',keyUp);listen('keyup',keyUp,win);listen('blur',releaseInputs);listen('blur',releaseInputs,win);
  function deactivate(){painter.releaseAux();live=false;cancelSchedule();pendingMove=null;retryEvent=null;queue=[];keys.clear();const ids=[...pointers.keys()];pointers.clear();for(const id of ids)try{canvas.releasePointerCapture?.(id);}catch{}unlisten();label();}
  stop.addEventListener('click',()=>{if(!live)return;deactivate();Promise.resolve().then(()=>send({type:'close'})).catch(onError);});
  const visibility=()=>{if(document.hidden){cancelSchedule();releaseInputs();}else schedule();};listen('visibilitychange',visibility,document);
  function paint(next=scene){try{const result=painter.paint(next);scene=result;suspended=false;canvas.hidden=false;restore.hidden=true;}catch(error){if(error.graphicsCommitFailed){deactivate();failure=error.message;label();}throw error;}}
  restore.addEventListener('click',()=>{if(disposed)return;try{paint();}catch(error){failure=error.message;onError(error);}label();});
  function update(value,isHistorical=historical){if(disposed)return;const next=canonicalScene(value);paint(next);historical=isHistorical;if(historical)deactivate();label();schedule();}
  function dispose(){disposed=true;deactivate();painter.dispose();unlisten();}
  try{update(scene);}catch(error){dispose();throw error;}return {root,canvas,update,deactivate,dispose,pinBacking:painter.pinBacking,get live(){return live&&!disposed&&scene.handlers.length>0;}};
}
