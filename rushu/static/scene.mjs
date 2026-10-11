/** Declarative local canvas output. No script, URLs, HTML or saved callbacks. */
export const MAX_COMMANDS=2048,MAX_FRAME_BYTES=262144;
const eventNames=['frame','mouse_down','mouse_up','mouse_move','key_down','key_up'];
const color=value=>typeof value==='string'&&/^#[\da-f]{6}$/i.test(value);
const codePoints=value=>Array.from(value).length;
// Account for actual backing stores, not CSS boxes or assumed device ratios.
export const MAX_BACKING_PIXELS=16*1024*1024;
const backingViews=new Map();
let backingPixels=0;
function releaseBacking(entry){if(!backingViews.has(entry))return;backingPixels-=backingViews.get(entry);backingViews.delete(entry);entry.release();}
function reserveBacking(entry,pixels){
  if(backingViews.has(entry)){backingPixels-=backingViews.get(entry);backingViews.delete(entry);}
  while(backingPixels+pixels>MAX_BACKING_PIXELS){const entries=[...backingViews.keys()];const victim=entries.find(item=>!item.active())||entries[0];if(!victim)break;releaseBacking(victim);}
  backingViews.set(entry,pixels);backingPixels+=pixels;
}
export function backingStorePixels(){return backingPixels;}
const finite=value=>typeof value==='number'&&Number.isFinite(value)&&Math.abs(value)<=100000;
export function validateScene(value) {
  if(!value||typeof value!=='object'||typeof value.canvas_id!=='string'||!/^[\w-]{1,128}$/.test(value.canvas_id))throw new Error('画布标识无效。');
  if(!Number.isInteger(value.width)||!Number.isInteger(value.height)||value.width<1||value.height<1||value.width>2048||value.height>2048)throw new Error('画布尺寸无效（最大 2048 × 2048）。');
  if(!Array.isArray(value.commands)||value.commands.length>MAX_COMMANDS)throw new Error('画布指令过多。');
  if(new TextEncoder().encode(JSON.stringify(value)).length>MAX_FRAME_BYTES)throw new Error('画布帧过大。');
  const commands=value.commands.map(command=>{
    if(!command||typeof command!=='object')throw new Error('画布指令无效。');
    const c=command,names={background:[],line:['x1','y1','x2','y2','width'],rect:['x','y','width','height','stroke_width'],ellipse:['x','y','width','height','stroke_width'],text:['x','y','size']};
    if(!Object.hasOwn(names,c.op)||!names[c.op].every(key=>finite(c[key])))throw new Error('画布坐标无效。');
    if(c.op==='rect'||c.op==='ellipse'){
      if(c.width<0||c.height<0||c.stroke_width<1||c.stroke_width>256||![c.fill,c.stroke].every(x=>x===''||color(x)))throw new Error('图形尺寸或颜色无效。');
      return {op:c.op,x:c.x,y:c.y,width:c.width,height:c.height,fill:c.fill,stroke:c.stroke,stroke_width:c.stroke_width};
    }
    if(!(c.color===''&&c.op!=='background')&&!color(c.color))throw new Error('画布颜色无效。');
    if(c.op==='background')return {op:c.op,color:c.color};
    if(c.op==='line'){if(c.width<=0||c.width>256)throw new Error('画布线宽无效。');return {op:c.op,x1:c.x1,y1:c.y1,x2:c.x2,y2:c.y2,color:c.color,width:c.width};}
    if(typeof c.text!=='string'||codePoints(c.text)>4096||c.size<=0||c.size>256)throw new Error('画布文字无效。');
    return {op:c.op,x:c.x,y:c.y,text:c.text,color:c.color,size:c.size};
  });
  if(!Array.isArray(value.handlers)||!value.handlers.every(x=>eventNames.includes(x)))throw new Error('画布交互无效。');
  if(!Number.isInteger(value.fps)||value.fps<1||value.fps>30)throw new Error('画布帧率无效。');
  if(typeof value.running!=='boolean')throw new Error('画布运行状态无效。');
  return {canvas_id:value.canvas_id,width:value.width,height:value.height,commands,fps:value.fps,handlers:[...new Set(value.handlers)],running:value.running};
}
export function drawScene(canvas,value) {
  const scene=validateScene(value);canvas.width=scene.width;canvas.height=scene.height;
  const ctx=canvas.getContext('2d');if(!ctx)throw new Error('浏览器不支持二维画布。');
  for(const c of scene.commands){
    if(c.op==='background'){ctx.fillStyle=c.color;ctx.fillRect(0,0,scene.width,scene.height);}
    else if(c.op==='text'){if(!c.color)continue;ctx.fillStyle=c.color;ctx.font=`${c.size}px sans-serif`;ctx.textBaseline='top';ctx.fillText(c.text,c.x,c.y);}
    else {ctx.beginPath();if(c.op==='line'){if(!c.color)continue;ctx.moveTo(c.x1,c.y1);ctx.lineTo(c.x2,c.y2);ctx.strokeStyle=c.color;ctx.lineWidth=c.width;ctx.stroke();}
      else {if(c.op==='rect')ctx.rect(c.x,c.y,c.width,c.height);else ctx.ellipse(c.x+c.width/2,c.y+c.height/2,c.width/2,c.height/2,0,0,Math.PI*2);
        if(c.fill){ctx.fillStyle=c.fill;ctx.fill();}if(c.stroke&&c.stroke_width>0){ctx.strokeStyle=c.stroke;ctx.lineWidth=c.stroke_width;ctx.stroke();}}}
  }return scene;
}
/** send resolves after the server's graphics_done, not merely HTTP acceptance. */
export function createSceneView(value,{send=async()=>{},historical=false,onError=()=>{}}={}) {
  let scene=validateScene(value),disposed=false,inFlight=false,timer=null,pendingMove=null,queue=[],live=!historical,lastDispatch=0,failure='',suspended=false,retryAt=0;
  const root=document.createElement('section');root.className='scene-output';
  const canvas=document.createElement('canvas');canvas.tabIndex=0;canvas.setAttribute('aria-label','如观画布；点击或按 Tab 聚焦后可使用键盘');
  const toolbar=document.createElement('div');toolbar.className='scene-toolbar';
  const status=document.createElement('span');status.setAttribute('aria-live','polite');
  const stop=document.createElement('button');stop.type='button';stop.textContent='停止画布';
  const restore=document.createElement('button');restore.type='button';restore.textContent='重新查看画面';restore.hidden=true;
  toolbar.append(status,stop,restore);root.append(canvas,toolbar);
  const backing={active:()=>live&&scene.handlers.length>0,release:()=>{deactivate();suspended=true;canvas.width=0;canvas.height=0;canvas.hidden=true;restore.hidden=false;label();}};
  const listeners=[];
  function listen(type,fn){canvas.addEventListener(type,fn);listeners.push([type,fn]);}
  function label(){status.textContent=suspended?'画面已暂存，点击重新查看':failure|| (historical?'历史画布 · 重新运行后可交互':!live?'画布已停止':scene.running?'动画运行中 · 聚焦画布可交互':scene.handlers.some(x=>x!=='frame')?'可交互 · 点击画布或按 Tab 聚焦':'静态画布');stop.hidden=!live||!scene.handlers.length;}
  function schedule(){if(timer!==null)return;if(!live||disposed||inFlight||document.hidden)return;if(!queue.length&&!pendingMove&&!(scene.running&&scene.handlers.includes('frame')))return;timer=setTimeout(()=>{timer=null;const next=queue.shift()||pendingMove||(scene.running&&scene.handlers.includes('frame')?{type:'frame'}:null);if(next===pendingMove)pendingMove=null;if(next)dispatch(next);},Math.max(0,Math.ceil(1000/scene.fps)+2-(performance.now()-lastDispatch),retryAt-performance.now()));}
  async function dispatch(event){if(!live||disposed||document.hidden)return;if(inFlight){enqueue(event);return;}inFlight=true;lastDispatch=performance.now();
    try{await send(event);}catch(error){if(error.status===429){retryAt=performance.now()+100;if(event.type==='mouse_move')pendingMove=pendingMove||event;else if(event.type!=='frame'&&queue.length<16)queue.unshift(event);}else{live=false;pendingMove=null;queue=[];failure='画布交互中断：'+error.message;onError(error);}}
    finally{inFlight=false;if(!disposed&&live)schedule();label();}}
  function enqueue(event){if(!live||disposed)return;if(event.type==='mouse_move')pendingMove=event;else if(event.type!=='frame'){if(queue.length>=16){failure='交互较快，部分输入已忽略';label();return;}queue.push(event);}if(!inFlight)schedule();}
  function pointer(type,event){if(!live||!scene.handlers.includes(type))return;if(type==='mouse_down')canvas.focus({preventScroll:true});const r=canvas.getBoundingClientRect();if(!r.width||!r.height)return;const input={type,x:Math.max(0,Math.min(scene.width,(event.clientX-r.left)*scene.width/r.width)),y:Math.max(0,Math.min(scene.height,(event.clientY-r.top)*scene.height/r.height))};if(type!=='mouse_move')input.button=event.button;enqueue(input);}
  listen('pointermove',event=>pointer('mouse_move',event));listen('pointerdown',event=>pointer('mouse_down',event));listen('pointerup',event=>pointer('mouse_up',event));
  for(const [native,type] of [['keydown','key_down'],['keyup','key_up']])listen(native,event=>{if(!live||!scene.handlers.includes(type)||event.ctrlKey||event.metaKey||event.altKey||event.key==='Tab'||event.repeat)return;if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight',' '].includes(event.key))event.preventDefault();event.stopPropagation();enqueue({type,key:event.key.slice(0,64)});});
  function deactivate(){live=false;clearTimeout(timer);timer=null;pendingMove=null;queue=[];label();}
  stop.addEventListener('click',()=>{if(!live)return;deactivate();Promise.resolve(send({type:'close'})).catch(onError);});
  const visibility=()=>{if(document.hidden){clearTimeout(timer);timer=null;pendingMove=null;queue=[];}else schedule();};document.addEventListener('visibilitychange',visibility);
  function paint(){reserveBacking(backing,scene.width*scene.height);scene=drawScene(canvas,scene);suspended=false;canvas.hidden=false;restore.hidden=true;}
  restore.addEventListener('click',()=>{if(disposed)return;paint();label();});
  function update(value,isHistorical=historical){scene=validateScene(value);historical=isHistorical;if(historical)deactivate();paint();label();schedule();}
  function dispose(){disposed=true;deactivate();releaseBacking(backing);for(const [type,fn] of listeners)canvas.removeEventListener(type,fn);document.removeEventListener('visibilitychange',visibility);}
  update(scene);return {root,canvas,update,deactivate,dispose,get live(){return live&&!disposed&&scene.handlers.length>0;}};
}
