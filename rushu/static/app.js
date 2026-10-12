import {sourceVersion,captureDiagnostic,currentDiagnostic,mountDiagnosticMarkers} from './diagnostics.mjs';
import {templates,createTemplateBook} from './templates.mjs';
import {outputWindow} from './output-view.mjs';
import {createSceneView,validateScene} from './scene.mjs';
import {versionLabel} from './versions.mjs';
import {analyze,highlight,enterEdit,indentSelection,needsAutoDedent} from './editor.mjs';
import {newCell,parseBook,serializeBook,appendOutput as appendCellOutput,retainGraphics,historicalBook,MAX_FILE_BYTES,MAX_CELLS,MAX_SOURCE} from './notebook.mjs';

import {ensureGeneration,checkpoint,replaceWithRevision,restoreRevision,lineDiff,generationIntent,withGenerationMarker,prepareGenerationFromMarker} from './history.mjs';

const $=selector=>document.querySelector(selector);
const el=(tag,cls,text)=>{const node=document.createElement(tag);if(cls)node.className=cls;if(text!=null)node.textContent=text;return node;};
const button=(text,title,handler,cls='')=>{const node=el('button',cls,text);node.type='button';node.title=title;node.setAttribute('aria-label',title);node.addEventListener('click',handler);return node;};
let hasBook=false;
let book={title:'',cells:[]},session=null,cursor=0,generation=1,activeRun=null,runAllActive=false,polling=false,epoch=0,dirty=false,transition=false,connected=false,lastExecutionCount=0,kernelDead=false;
const views=new Map();
function appendOutput(cell,type,text){appendCellOutput(cell,type,text,book);}
// Live handlers are deliberately separate from portable notebook snapshots.
const sceneViews=new Map(),scenePending=new Map();
function stopScenes(close=false){for(const [id,record] of sceneViews){record.view.deactivate();if(close&&record.session===session&&record.epoch===epoch)api(sessionPath('/graphics'),'POST',{canvas_id:id,cell_id:record.cell.id,execution_count:record.count,expected_generation:record.generation,event:{type:'close'}}).catch(()=>{});}for(const pending of scenePending.values())pending.resolve();scenePending.clear();}
async function closeScenesBeforeRun(id,myEpoch,myGeneration){
  stopScenes();const path=`/sessions/${encodeURIComponent(id)}`;
  const current=()=>id===session&&myEpoch===epoch&&myGeneration===generation;
  let state=await api(path+'/events?after='+cursor);if(!current())throw new Error('会话已切换，本次运行已取消。');
  if(state.graphics)await api(path+'/graphics','POST',{canvas_id:state.graphics.canvas_id,cell_id:state.cell_id,execution_count:state.execution_count,expected_generation:myGeneration,event:{type:'close'}});
  const deadline=performance.now()+4000;
  while(state.graphics_busy||state.graphics){if(performance.now()>deadline)throw new Error('正在结束画布回调，请稍后重试或停止会话。');await new Promise(resolve=>setTimeout(resolve,50));state=await api(path+'/events?after='+cursor);if(!current()||state.generation!==myGeneration)throw new Error('画布回调已中断并重置会话，请重新运行。');}
}
function clearScene(cell){for(const [id,record] of sceneViews)if(record.cell===cell){record.view.dispose();sceneViews.delete(id);const pending=scenePending.get(id);if(pending){pending.resolve();scenePending.delete(id);}}}
function sceneOutput(cell,item){
  const scene=validateScene(item.scene);let record=sceneViews.get(scene.canvas_id);
  if(!record){record={cell,session,epoch,generation,count:cell.execution_count};
    const send=async event=>{if(record.session!==session||record.epoch!==epoch||record.generation!==generation||record.count!==cell.execution_count)return;
      if(event.type==='close'){const pending=scenePending.get(scene.canvas_id);if(pending){pending.resolve();scenePending.delete(scene.canvas_id);}await api(sessionPath('/graphics'),'POST',{canvas_id:scene.canvas_id,cell_id:cell.id,execution_count:record.count,expected_generation:record.generation,event});return;}
      if(activeRun||transition||!connected)return;
      let resolve,reject;const completed=new Promise((yes,no)=>{resolve=yes;reject=no;});const pending={resolve,reject};scenePending.set(scene.canvas_id,pending);
      try{await api(sessionPath('/graphics'),'POST',{canvas_id:scene.canvas_id,cell_id:cell.id,execution_count:record.count,expected_generation:record.generation,event});pollSoon(0);await completed;}
      catch(error){if(scenePending.get(scene.canvas_id)===pending)scenePending.delete(scene.canvas_id);throw error;}
    };
    record.view=createSceneView(scene,{historical:cell.historical||cell.execution_count!==lastExecutionCount,send,onError:error=>notice(error.message,true)});sceneViews.set(scene.canvas_id,record);
  }else record.view.update(scene,cell.historical);
  return record.view.root;
}
let generationRequest=null;
let providerInfo=null;
let token=new URLSearchParams(location.hash.slice(1)).get('token')||'';
try { const key='rushu-token:'+location.origin; if(token){sessionStorage.setItem(key,token);history.replaceState(null,'',location.pathname+location.search);} else token=sessionStorage.getItem(key)||''; } catch { /* Session storage is optional. */ }
let noticeTimer;
function notice(message,error=false,persistent=false) { clearTimeout(noticeTimer);const node=$('#notice');node.textContent=message;node.classList.toggle('error',error);node.hidden=false;if(!persistent)noticeTimer=setTimeout(()=>node.hidden=true,7000); }
function markDirty(){dirty=true;$('#document-status').textContent='有未保存的更改';}
function updateMeta() { $('#cell-count').textContent=`${book.cells.length} 格`;document.title=`${book.title||'未命名如书'} · 如书`; }
function runtimeStatus(state,label) { const node=$('#runtime-status');node.className='runtime-status '+(state==='running'||state==='waiting_input'?'running':state==='dead'?'error':'');node.querySelector('span').textContent=label||({idle:'会话就绪',running:'正在运行',waiting_input:'等待输入',dead:'会话已断开'}[state]||'连接中'); }
function busy(){return !!activeRun||runAllActive||transition||!!generationRequest;}
function refreshControls() {
  $('#run-all').disabled=!connected||busy();$('#restart').disabled=!session||transition;$('#stop').disabled=(!activeRun&&![...sceneViews.values()].some(record=>record.view.live))||transition;
  $('#new-book').disabled=transition;$('#open-book').disabled=transition;$('#save-book').disabled=!hasBook||transition;
  for(const choice of document.querySelectorAll('[data-template],.blank-shortcut'))choice.disabled=transition;
  $('#add-code').disabled=busy()||book.cells.length>=MAX_CELLS;$('#add-markdown').disabled=busy()||book.cells.length>=MAX_CELLS;$('#add-learning').disabled=busy()||book.cells.length>=MAX_CELLS;
  for(const cell of book.cells){const view=views.get(cell.id);if(!view)continue;for(const b of view.element.querySelectorAll('[data-mutates]'))b.disabled=busy();view.run.disabled=!connected||busy();if(view.input)view.input.readOnly=cell.status==='running';if(view.generate)view.generate.disabled=busy()||!!generationRequest||!token;if(view.cancelGeneration)view.cancelGeneration.hidden=generationRequest?.cell!==cell;if(view.restore)view.restore.disabled=busy()||!!generationRequest;}
}
async function api(path,method='GET',body) {
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),12000);
  try {
    const response=await fetch('/api'+path,{method,headers:{'X-Rushu-Token':token,...(method!=='GET'?{'Content-Type':'application/json'}:{})},body:method==='GET'?undefined:JSON.stringify(body??{}),signal:controller.signal,cache:'no-store',credentials:'same-origin'});
    let data;try{data=await response.json();}catch{throw new Error('服务没有返回有效响应，请检查启动终端。');}
    if(!response.ok){const error=new Error(data.error||`请求失败（${response.status}）`);error.definite=true;error.status=response.status;throw error;}return data;
  } catch(error){if(error.name==='AbortError')throw new Error('本机服务响应超时，请检查启动终端。');throw error;}finally{clearTimeout(timeout);}
}
function sessionPath(suffix=''){return `/sessions/${encodeURIComponent(session)}${suffix}`;}
function finishActive(success=false) { if(!activeRun)return;const run=activeRun;activeRun=null;run.resolve(success);refreshControls(); }
async function replaceBook(next) {
  if(transition)return false;
  transition=true;refreshControls();
  try {
    const result=token?await api('/sessions','POST',{}):{id:null};const old=session;cancelGeneration(false);stopScenes();for(const cell of book.cells)clearScene(cell);epoch++;finishActive(false);runAllActive=false;
    session=result.id;cursor=result.cursor||0;generation=result.generation||1;lastExecutionCount=0;kernelDead=false;connected=!!result.id;book=next;hasBook=true;
    $('#start-page').hidden=true;$('#book-workspace').hidden=false;
    $('#book-title').value=book.title;renderBook();runtimeStatus(connected?'idle':'dead',connected?undefined:'缺少连接凭据');markDirty();
    if(old)api(`/sessions/${encodeURIComponent(old)}`,'DELETE',{}).catch(error=>notice('新会话已创建，但旧会话未能关闭：'+error.message,true,true));
    if(session)pollSoon(0);return true;
  } finally {transition=false;refreshControls();}
}
function confirmReplace(){return !hasBook||!dirty&&!activeRun&&!generationRequest||confirm((activeRun?'当前代码仍在运行，继续会结束旧会话。\n':'')+(generationRequest?'生成仍在等待，继续会丢弃返回结果；已发送的请求无法撤回。\n':'')+'尚未保存的内容可能丢失。要继续吗？');}

// Markdown is a deliberately small DOM renderer. HTML is always plain text.
function inlineMarkdown(target,text) {
  const pattern=/(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*|\[[^\]\n]+\]\([^\s)]+\))/g;let at=0;
  for(const match of text.matchAll(pattern)) {
    target.append(document.createTextNode(text.slice(at,match.index)));const value=match[0];let node;
    if(value.startsWith('`'))node=el('code','',value.slice(1,-1));
    else if(value.startsWith('**'))node=el('strong','',value.slice(2,-2));
    else if(value.startsWith('*'))node=el('em','',value.slice(1,-1));
    else {const parts=value.match(/^\[([^\]]+)\]\(([^)]+)\)$/);let safe=false;try{safe=['https:','http:'].includes(new URL(parts[2]).protocol);}catch{}if(safe){node=el('a','',parts[1]);node.href=parts[2];node.target='_blank';node.rel='noopener noreferrer';}else node=document.createTextNode(value);}
    target.append(node);at=match.index+value.length;
  }
  target.append(document.createTextNode(text.slice(at)));
}
function renderMarkdown(target,source) {
  target.replaceChildren();if(!source.trim()){target.append(el('p','markdown-placeholder','双击这里写下想法，或点击“编辑”。'));return;}
  const lines=source.split('\n');let paragraph=[],list=null,code=null;
  const flush=()=>{if(paragraph.length){const p=el('p');inlineMarkdown(p,paragraph.join('\n'));target.append(p);paragraph=[];}};
  for(const line of lines){
    if(/^\s*```/.test(line)){flush();list=null;if(code){target.append(code);code=null;}else{code=el('pre');code.append(el('code'));}continue;}
    if(code){code.firstChild.textContent+=line+'\n';continue;}
    const heading=line.match(/^(#{1,6})\s+(.+)$/),item=line.match(/^\s*(?:([-*])|\d+[.)])\s+(.+)$/);
    if(heading){flush();list=null;const h=el('h'+heading[1].length);inlineMarkdown(h,heading[2]);target.append(h);}
    else if(/^\s*(---+|\*\*\*+)\s*$/.test(line)){flush();list=null;target.append(el('hr'));}
    else if(item){flush();const tag=item[1]?'UL':'OL';if(!list||list.tagName!==tag){list=el(tag.toLowerCase());target.append(list);}const li=el('li');inlineMarkdown(li,item[2]);list.append(li);}
    else if(!line.trim()){flush();list=null;}
    else{list=null;paragraph.push(line);}
  }
  flush();if(code)target.append(code);
}
function buildEditor(cell,view) {
  const shell=el('div','editor-shell'),numbers=el('div','line-numbers'),layer=el('div','code-editor'),guides=el('div','guide-layer'),pre=el('pre'),input=el('textarea');
  numbers.setAttribute('aria-hidden','true');pre.setAttribute('aria-hidden','true');guides.setAttribute('aria-hidden','true');
  input.value=cell.source;input.spellcheck=false;input.autocapitalize='off';input.autocomplete='off';input.wrap='off';input.setAttribute('aria-label',`如代码，第 ${book.cells.indexOf(cell)+1} 格`);input.setAttribute('aria-describedby','editor-keyboard-help');input.maxLength=MAX_SOURCE;
  layer.append(guides,pre,input);shell.append(numbers,layer);view.input=input;
  let escapeTab=false,composing=false;
  const sync=()=>{pre.scrollLeft=input.scrollLeft;guides.style.transform=`translateX(${-input.scrollLeft}px)`;};
  const render=()=>{
    const source=input.value,lines=source.split('\n');
    const height=Math.max(87,lines.length*25+36+18);input.style.height=height+'px';pre.style.height=height+'px';
    numbers.textContent=lines.map((_,i)=>i+1).join('\n');pre.innerHTML=highlight(source)+'\n';
    const result=analyze(source),fragment=document.createDocumentFragment();
    for(let row=0;row<Math.min(lines.length,3000);row++){
      const depth=result.lines[row].depth;
      if(depth!=null)for(let d=0;d<Math.min(depth,20);d++){const guide=el('i','guide');guide.style.left=`${d*4}ch`;guide.style.top=`${row*25}px`;fragment.append(guide);}
    }
    guides.replaceChildren(fragment);sync();view.diagnosticMarkers?.render();
  };
  function applyEdit(edit){input.setRangeText(edit.text,edit.start,edit.end,'end');input.setSelectionRange(edit.selectionStart??edit.selection??input.selectionStart,edit.selectionEnd??edit.selection??input.selectionEnd);update();}
  function update(auto=false){
    if(auto&&!composing){const pos=input.selectionStart,start=input.value.lastIndexOf('\n',pos-1)+1,end=input.value.indexOf('\n',pos),line=input.value.slice(start,end<0?undefined:end);
      if(needsAutoDedent(line)){
        const result=analyze(input.value),lineIndex=input.value.slice(0,start).split('\n').length-1,depth=result.lines[lineIndex].depth;
        if(depth!=null){const old=line.match(/^\s*/)[0].length,wanted=depth*4;if(old!==wanted){input.setRangeText(' '.repeat(wanted),start,start+old,'preserve');input.setSelectionRange(Math.max(start,pos+wanted-old),Math.max(start,pos+wanted-old));}}
      }
    }
    if(cell.source!==input.value&&(cell.execution_count||cell.outputs.length))cell.stale=true;cell.source=input.value;markDirty();render();if(cell.stale)renderOutput(cell);
  }
  // The textarea overlays the highlighted mirror; use the mirror's real glyph
  // rectangles so CJK, proportional fallback fonts and horizontal scroll agree.
  input.addEventListener('mousemove',event=>{
    let help='';
    for(const token of pre.querySelectorAll('[data-help]')){
      if(Array.from(token.getClientRects()).some(r=>event.clientX>=r.left&&event.clientX<r.right&&event.clientY>=r.top&&event.clientY<r.bottom)){help=token.dataset.help;break;}
    }
    input.title=help;
  });
  input.addEventListener('mouseleave',()=>input.removeAttribute('title'));
  input.addEventListener('scroll',sync);input.addEventListener('input',()=>update(true));input.addEventListener('compositionstart',()=>composing=true);input.addEventListener('compositionend',()=>{composing=false;update(true);});
  input.addEventListener('keydown',event=>{
    if(event.isComposing||composing)return;
    if(event.key==='Escape'){escapeTab=true;notice('下一次 Tab 将移出编辑器。');return;}
    if(event.key==='Tab'){if(escapeTab){escapeTab=false;return;}event.preventDefault();if(input.readOnly)return;
      if(input.selectionStart===input.selectionEnd&&!event.shiftKey){const column=input.selectionStart-(input.value.lastIndexOf('\n',input.selectionStart-1)+1);applyEdit({start:input.selectionStart,end:input.selectionEnd,text:' '.repeat(4-column%4)});}
      else applyEdit(indentSelection(input.value,input.selectionStart,input.selectionEnd,event.shiftKey));return;}
    escapeTab=false;
    if(event.key==='Enter'&&(event.shiftKey||event.ctrlKey||event.metaKey)){event.preventDefault();runAndMove(cell,event.shiftKey);return;}
    if(event.key==='Enter'&&!input.readOnly){event.preventDefault();applyEdit(enterEdit(input.value,input.selectionStart,input.selectionEnd));}
  });
  view.diagnosticMarkers=mountDiagnosticMarkers({input,pre,layer,numbers,records:()=>activeDiagnostics(cell)});
  view.renderEditor=render;render();return shell;
}
// Generation is a separate, explicit network action. It never calls the kernel.
function enableLearning(cell){
  if(busy()||generationRequest)return;
  ensureGeneration(cell,'');renderBook();markDirty();focusCell(cell);
}
function createLearning(cell){
  if(busy()||generationRequest)return;
  if(book.cells.length>=MAX_CELLS){notice('一本如书最多 500 格。',true);return;}
  try{const next=newCell('code');ensureGeneration(next,withGenerationMarker(cell.source));book.cells.splice(book.cells.indexOf(cell)+1,0,next);renderBook();markDirty();focusCell(next);notice('已将文字作为本次意图，原文字格保留。确认发送范围后生成源码。');generateCell(next);}catch(error){notice(error.message,true,true);}
}
function createGenerationStatus(view){
  const node=el('p','generation-status');
  view.generationStatusText=el('span','','生成后先审阅源码，再单独点击本格「运行」。全部运行会跳过学习格。');
  view.generationStatusText.setAttribute('role','status');
  const indicator=el('span','generation-activity');indicator.hidden=true;indicator.setAttribute('aria-hidden','true');
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox','0 0 16 16');svg.setAttribute('width','16');svg.setAttribute('height','16');svg.setAttribute('focusable','false');
  const arc=document.createElementNS('http://www.w3.org/2000/svg','circle');
  for(const [name,value] of Object.entries({cx:'8',cy:'8',r:'6',fill:'none',stroke:'currentColor','stroke-width':'2','stroke-linecap':'round','stroke-dasharray':'27 11'}))arc.setAttribute(name,value);
  svg.append(arc);indicator.append(svg);node.append(view.generationStatusText,indicator);
  view.generationActivity=indicator;return node;
}
function generationActivity(cell,active){
  const indicator=views.get(cell.id)?.generationActivity;if(indicator)indicator.hidden=!active;
}
function generationStatus(cell,message,error=false,active=false){
  const view=views.get(cell.id);if(!view?.generationStatus)return;
  // Preserve both the text and SVG nodes while waiting. Only real state changes
  // enter the live region; animation never mutates text or rebuilds the cell.
  if(view.generationStatusText.textContent!==message)view.generationStatusText.textContent=message;
  view.generationStatus.classList.toggle('error',error);generationActivity(cell,active);
}
async function loadProvider(view){
  try{
    const result=await api('/generation/config');providerInfo=result;
    if(!view.element.isConnected)return;
    view.provider.textContent=result.configured?`生成服务：${result.provider_host}。点击生成会发送本格的意图、当前源码草稿，以及随附的完整如语言规范。其他格、历史版本、输出、运行变量和本机文件不会发送。`:`生成功能尚未配置：${result.message}。请在启动如书的终端配置后重试；不要把密钥写入书本。`;
  }catch{if(view.element.isConnected)view.provider.textContent='无法读取生成配置。请检查本机服务，密钥只在服务端配置。';}
}
function buildGenerationPanel(cell,view){
  const panel=el('div','generation-panel'),label=el('label','generation-label','学习模式 · 写下这次想要的程序或修改'),prompt=el('textarea','generation-prompt');
  prompt.id='prompt-'+cell.id;label.htmlFor=prompt.id;prompt.value=cell.generation.prompt;prompt.maxLength=MAX_SOURCE;prompt.spellcheck=false;prompt.placeholder='例如：显示一到十的平方，并逐行加注释。\n如是我言';view.prompt=prompt;
  prompt.addEventListener('input',()=>{cell.generation.prompt=prompt.value;markDirty();});
  const controls=el('div','generation-actions'),generate=button('如是我言 · 生成','给意图补上结语并发送本格意图与当前源码，生成新版本',()=>generateCell(cell),'primary'),cancel=button('取消等待','丢弃尚未返回的生成结果，保留当前编辑',()=>cancelGeneration());
  const save=button('记下手动修改','把当前意图和源码保存为一个人工版本',()=>{try{checkpoint(cell);markDirty();renderHistory(cell);generationStatus(cell,'手动修改已记入版本历史。');}catch(error){notice(error.message,true,true);}});save.dataset.mutates='true';
  view.generate=generate;view.cancelGeneration=cancel;cancel.hidden=true;const branch=button('另起学习格','保留这格全部历史，把当前意图和草稿复制到新格继续学习',()=>{if(busy()||book.cells.length>=MAX_CELLS)return;const next=newCell('code',cell.source);ensureGeneration(next,cell.generation.prompt);book.cells.splice(book.cells.indexOf(cell)+1,0,next);renderBook();markDirty();focusCell(next);});branch.dataset.mutates='true';controls.append(generate,cancel,save,branch);
  view.provider=el('p','generation-disclosure','正在读取服务端生成配置…');view.generationStatus=createGenerationStatus(view);
  const diagnostics=el('details','generation-diagnostics generation-disclosure');
  view.generationDiagnostic=el('p','','尚未开始生成。');
  diagnostics.append(el('summary','','生成诊断'),view.generationDiagnostic,el('p','','仅显示本机可观察到的阶段和耗时；等待期间无法知道模型的 token 进度。不记录意图、源码、凭据或提供方响应原文。'));
  panel.append(label,prompt,controls,view.provider,view.generationStatus,diagnostics,el('div','draft-label','当前如源码草稿 · 可直接修改'));
  // This is only a local configuration read, never a provider request.
  queueMicrotask(()=>loadProvider(view));return panel;
}
// Locations are local metadata, never provider response text or executable HTML.
function diagnosticLocation(detail={},includeSource=false){
  const parts=[];
  if(includeSource&&typeof detail.source_name==='string'&&detail.source_name){
    // Keep paths readable while preventing controls and bidi overrides from
    // disguising their origin or injecting extra diagnostic lines.
    const name=detail.source_name.slice(0,4096).replace(/[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u2028-\u202e\u2066-\u2069]/g,ch=>'\\u'+ch.charCodeAt(0).toString(16).padStart(4,'0'));
    parts.push('来源：'+name);
  }
  if(Number.isSafeInteger(detail.line)&&detail.line>0){
    const column=Number.isSafeInteger(detail.col)&&detail.col>0?'，第 '+detail.col+' 列':'';
    parts.push('第 '+detail.line+' 行'+column);
  }
  return parts.join('\n');
}
function generationDiagnostic(request,phase=request.diagnosticPhase){
  if(generationRequest!==request)return;
  request.diagnosticPhase=phase;
  const node=views.get(request.cell.id)?.generationDiagnostic;if(!node)return;
  const elapsed=request.sentAt==null?'':` · 请求已用时 ${Math.max(0,Math.floor((performance.now()-request.sentAt)/1000))} 秒`;
  node.textContent=phase+elapsed;
}
function cancelGeneration(announce=true){
  const pending=generationRequest;if(!pending)return;
  generationDiagnostic(pending,pending.sentAt==null?'已取消，未发送生成请求。':'已取消页面等待；提供方请求状态未知。');
  clearInterval(pending.elapsedTimer);
  generationRequest=null;pending.controller.abort();refreshControls();
  generationStatus(pending.cell,'已取消等待，编辑内容未被替换。提供方可能仍在处理或计费；本机服务在请求结束前会拒绝新的生成。');
  if(announce)notice('已取消等待并丢弃后续结果。提供方可能仍在处理或计费，请勿连续重试。',false,true);
}
async function generateCell(cell){
  if(busy()||generationRequest||!cell.generation||!book.cells.includes(cell))return;
  const owner=book,view=views.get(cell.id);
  try{
    const marked=withGenerationMarker(cell.generation.prompt);
    cell.generation.prompt=marked;view.prompt.value=marked;markDirty();
    if(!generationIntent(marked)?.trim())throw new Error('请先写下非空的意图，并在最后单独一行写「如是我言」。');
    // Save a human revision before sending. A failed request never deletes it.
    checkpoint(cell);serializeBook(book);renderHistory(cell);
    const capacityProbe={...cell,generation:structuredClone(cell.generation)};replaceWithRevision(capacityProbe,{source:'',prompt:cell.generation.prompt,kind:'model'});serializeBook({...book,cells:book.cells.map(c=>c===cell?capacityProbe:c)});
  }catch(error){notice(error.message,true,true);return;}
  const request={cell,book:owner,epoch,prompt:cell.generation.prompt,source:cell.source,controller:new AbortController()};
  generationRequest=request;refreshControls();generationStatus(cell,'正在生成新版本…你可以继续编辑；若内容改变，返回结果不会覆盖它。',false,true);
  generationDiagnostic(request,'正在读取本机生成配置，尚未发送生成请求。');
  // The server owns the configurable generation deadline. Abort only when the
  // user cancels or changes books/sessions, never through a shorter page timer.
  try{
    // Re-read configuration before every request; the service enforces it too.
    const config=await api('/generation/config');providerInfo=config;
    if(generationRequest!==request)return;
    if(!config.configured)throw new Error(config.message+'。请在启动如书的终端配置，勿把密钥写入书本。');
    if(!confirm(`发送给 ${config.provider_host}？\n\n仅发送本格意图（${request.prompt.length} 字符）、当前源码草稿（${request.source.length} 字符）和完整如语言规范。可能按提供方计费。\n\n生成结果只供审阅，不自动运行。`)){generationStatus(cell,'已取消发送。当前编辑和版本记录保留。');generationDiagnostic(request,'已取消确认，未发送生成请求。');return;}
    request.sentAt=performance.now();
    generationDiagnostic(request,'正在请求生成并等待本机服务返回。');
    request.elapsedTimer=setInterval(()=>generationDiagnostic(request),1000);
    const response=await fetch('/api/generate',{method:'POST',headers:{'X-Rushu-Token':token,'Content-Type':'application/json'},body:JSON.stringify({prompt:request.prompt,draft:request.source}),signal:request.controller.signal,cache:'no-store',credentials:'same-origin'});
    generationDiagnostic(request,'已收到本机服务响应，正在读取生成结果。');
    let result;try{result=await response.json();}catch{throw new Error('本机服务返回了无法读取的生成响应；没有替换草稿。');}
    if(!response.ok)throw new Error(result.error||'生成请求失败，草稿未改变。');
    if(generationRequest!==request||book!==owner||epoch!==request.epoch||!book.cells.includes(cell))return;
    if(cell.source!==request.source||cell.generation.prompt!==request.prompt){generationStatus(cell,'生成期间有新的编辑，已丢弃过期结果。当前编辑未被覆盖，请重新生成。',true);generationDiagnostic(request,'已收到结果；因编辑改变，结果已丢弃。');return;}
    if(typeof result.source!=='string'||result.source.length>MAX_SOURCE)throw new Error('生成源码超过本格上限或响应无效；草稿未替换。');
    const candidate={...cell,generation:structuredClone(cell.generation)};
    replaceWithRevision(candidate,{source:result.source,prompt:request.prompt,kind:'model'});
    // Preflight the entire portable book before replacing any current edits.
    serializeBook({...book,cells:book.cells.map(c=>c===cell?candidate:c)});
    cell.source=candidate.source;cell.generation=candidate.generation;cell.stale=!!(cell.execution_count||cell.outputs.length);markDirty();
    const currentView=views.get(cell.id);if(currentView){currentView.input.value=cell.source;currentView.renderEditor();}renderOutput(cell);renderHistory(cell);
    const validationPosition=diagnosticLocation(result.validation||{});
    generationStatus(cell,result.valid?'新版本已加入历史。语法／结构检查通过；未检查外言依赖，未执行。请审阅后单独运行。':`新版本已加入历史，但尚未通过语法／结构检查：${validationPosition?validationPosition+'；':''}${result.validation?.message||'请检查源码'}。未执行。`,!result.valid);
    generationDiagnostic(request,result.valid?'生成结果已加入历史；服务端语法／结构检查通过，未执行。':'生成结果已加入历史；服务端语法／结构检查未通过，未执行。');
  }catch(error){if(generationRequest===request){generationDiagnostic(request,error.name==='AbortError'?'等待已取消，当前编辑保留。':'生成未完成：'+error.message);generationStatus(cell,error.name==='AbortError'?'等待已取消，当前编辑保留。':error.message,true);notice(error.name==='AbortError'?'已取消生成等待。':error.message,true,true);}}
  finally{clearInterval(request.elapsedTimer);if(generationRequest===request){generationActivity(cell,false);generationRequest=null;refreshControls();}}
}
function buildHistory(cell,view){
  const details=el('details','generation-history'),summary=el('summary','','版本历史与变化'),body=el('div','history-body');
  details.append(summary,body);view.historyBody=body;view.historySummary=summary;
  details.addEventListener('toggle',()=>{if(details.open)renderHistory(cell);});renderHistory(cell);return details;
}
function renderHistory(cell){
  const view=views.get(cell.id);if(!view?.historyBody)return;
  const revisions=cell.generation.revisions,body=view.historyBody;body.replaceChildren();view.historySummary.textContent=`版本历史与变化 · ${revisions.length} 个已记录版本`;
  const names={human:'人工修改',model:'模型生成',restore:'恢复版本'};
  const label=r=>`${names[r.kind]} · ${r.timestamp} · ${r.id}`;
  const controls=el('div','history-controls'),before=el('select'),after=el('select');before.setAttribute('aria-label','对比起点版本');after.setAttribute('aria-label','查看与对比的版本');
  for(const select of [before,after]){const draft=el('option','','当前草稿（未记入的编辑）');draft.value='draft';select.append(draft);for(const r of revisions){const option=el('option','',label(r));option.value=r.id;select.append(option);}}
  before.value=revisions.at(-2)?.id||revisions.at(-1)?.id||'draft';after.value=revisions.at(-1)?.id||'draft';
  controls.append(el('label','','从'),before,el('label','','到 / 查看'),after);body.append(controls);
  const all=el('ol','revision-list');for(const r of revisions){const li=el('li');li.append(button(label(r),'查看这个版本的意图和源码',()=>{after.value=r.id;show();}));all.append(li);}if(!revisions.length)all.append(el('li','','尚无版本。生成、记下手动修改或保存书本时会记录。'));body.append(all);
  const content=el('div','history-content'),restore=button('恢复所选版本为新版本','先保存当前手动修改，再新增一个恢复版本',()=>{
    if(busy()||generationRequest||after.value==='draft')return;
    try{const candidate={...cell,generation:structuredClone(cell.generation)};restoreRevision(candidate,after.value);serializeBook({...book,cells:book.cells.map(c=>c===cell?candidate:c)});cell.source=candidate.source;cell.generation=candidate.generation;cell.stale=!!(cell.execution_count||cell.outputs.length);view.input.value=cell.source;view.prompt.value=cell.generation.prompt;view.renderEditor();renderOutput(cell);markDirty();renderHistory(cell);generationStatus(cell,'已新增恢复版本，原历史和手动修改都保留。未执行。');}catch(error){notice(error.message,true,true);}
  });view.restore=restore;body.append(restore,content);
  const snapshot=id=>id==='draft'?{prompt:cell.generation.prompt,source:cell.source}:revisions.find(r=>r.id===id);
  function show(){
    const a=snapshot(before.value),b=snapshot(after.value);content.replaceChildren();if(!a||!b)return;restore.disabled=after.value==='draft'||busy()||!!generationRequest;
    content.append(el('h4','','所选版本 · 意图'),el('pre','history-source',b.prompt),el('h4','','所选版本 · 如源码'),el('pre','history-source',b.source));
    for(const [key,title] of [['prompt','意图变化'],['source','源码变化']]){
      const pre=el('pre','history-diff');let shown=0;for(const part of lineDiff(a[key],b[key])){if(shown>=60000)break;const prefix=part.type==='add'?'+ ':part.type==='remove'?'- ':'  ';const lines=part.text.split('\n');if(lines.at(-1)==='')lines.pop();const text=lines.map(line=>prefix+line).join('\n')+'\n'+(!part.text.endsWith('\n')&&part.type!=='equal'?'\\ 无末尾换行\n':'');const span=el('span','diff-'+part.type,text.slice(0,60000-shown));pre.append(span);shown+=text.length;}
      if(shown>=60000)pre.append(document.createTextNode('\n[差异预览达到显示上限；完整原文请在所选版本源码中查看或导出书本。]'));content.append(el('h4','',title+'（− 删除 / ＋ 新增）'),pre);
    }
  }
  before.addEventListener('change',show);after.addEventListener('change',show);show();
}

function renderCell(cell) {
  const element=el('section','cell '+cell.type),head=el('div','cell-head'),kind=el('div','cell-type'),count=el('span','counter'),tools=el('div','cell-tools');element.dataset.cellId=cell.id;
  const view={element,count,input:null,renderEditor:null,output:el('div','cell-output'),diagnosticLinks:el('div','diagnostic-links')};views.set(cell.id,view);
  kind.append(el('span','kind-icon',cell.type==='code'?'⌘':'¶'),el('span','',cell.type==='code'?'如代码':'文字'),count);
  const run=button(cell.type==='code'?'▶ 运行':'编辑',cell.type==='code'?'运行此代码格，Ctrl 或 Command + Enter':'编辑文字',()=>cell.type==='code'?runAndMove(cell,false):toggleMarkdown(cell), 'run-cell');view.run=run;
  tools.append(run);
  if(cell.type==='code'){const clear=button('清除输出','清除这格的输出快照',()=>{stopScenes(true);clearScene(cell);cell.outputs=[];cell.diagnostics=[];delete cell.diagnosticSnapshot;cell.execution_count=null;cell.historical=false;cell.status='idle';renderOutput(cell);markDirty();},'clear-output');clear.dataset.mutates='true';tools.append(clear);}
  for(const [text,title,handler,cls] of [['↑','向上移动格子',()=>moveCell(cell,-1),'icon-button'],['↓','向下移动格子',()=>moveCell(cell,1),'icon-button'],['×','删除这格',()=>deleteCell(cell),'icon-button danger']]){const b=button(text,title,handler,cls);b.dataset.mutates='true';tools.append(b);}
  if(cell.type==='markdown'){const learn=button('如是我言','以这段文字生成如源码，先确认发送范围',()=>createLearning(cell));learn.dataset.mutates='true';tools.prepend(learn);}
  else if(!cell.generation){const learn=button('学习模式','把当前源码作为学习草稿，另写修改意图',()=>enableLearning(cell));learn.dataset.mutates='true';tools.prepend(learn);}
  head.append(kind,tools);element.append(head);
  if(cell.generation)element.append(buildGenerationPanel(cell,view));
  if(cell.type==='code')element.append(buildEditor(cell,view));
  else {
    const preview=el('div','markdown-view');preview.tabIndex=0;preview.setAttribute('aria-label','文字内容，按 Enter 编辑');renderMarkdown(preview,cell.source);
    preview.addEventListener('dblclick',()=>toggleMarkdown(cell,true));preview.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();toggleMarkdown(cell,true);}});view.preview=preview;element.append(preview);
  }
  element.append(view.output);if(cell.generation)element.append(buildHistory(cell,view));renderOutput(cell);return element;
}
function toggleMarkdown(cell,forceEdit=false) {
  const view=views.get(cell.id);if(!view||cell.type!=='markdown')return;
  if(view.editing&&!forceEdit){view.editing.remove();view.editing=null;view.input=null;view.preview.hidden=false;view.run.textContent='编辑';renderMarkdown(view.preview,cell.source);view.preview.focus();return;}
  if(view.editing){view.input.focus();return;}
  view.preview.hidden=true;const edit=el('div','markdown-edit'),input=el('textarea');input.value=cell.source;input.maxLength=MAX_SOURCE;input.setAttribute('aria-label','Markdown 文字');input.addEventListener('input',()=>{cell.source=input.value;markDirty();});
  input.addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey||event.shiftKey)){event.preventDefault();if(generationIntent(cell.source)!==null){createLearning(cell);return;}toggleMarkdown(cell);if(event.shiftKey)focusNext(cell);}});
  edit.append(input,el('div','markdown-hint','Markdown · Shift + Enter 完成编辑；末行「如是我言」则生成源码'));view.preview.after(edit);view.editing=edit;view.input=input;view.run.textContent='完成';input.focus();
}
function renderBook(){for(const view of views.values())view.diagnosticMarkers?.dispose();views.clear();$('#cells').replaceChildren(...book.cells.map(renderCell));updateMeta();refreshControls();}
function activeDiagnostics(cell){
  return book.cells.flatMap(owner=>owner.diagnostics||[]).filter(record=>record.targetId===cell.id&&currentDiagnostic(cell,record)).slice(0,20);
}
function refreshDiagnosticMarkers(){for(const cell of book.cells){const view=views.get(cell.id);view?.diagnosticMarkers?.render();if(view?.diagnosticLinks){view.diagnosticLinks.replaceChildren();renderDiagnosticLinks(cell,view.diagnosticLinks);}}}
function renderDiagnosticLinks(cell,output){
  for(const record of cell.diagnostics||[]){
    const target=book.cells.find(item=>item.id===record.targetId),current=target&&currentDiagnostic(target,record);
    const label=`第 ${book.cells.indexOf(target)+1} 格 · 第 ${record.range.line} 行`+(record.range.col==null?'':`，第 ${record.range.col} 列`);
    if(current){const jump=button('定位错误 · '+label,record.message+'；定位到 '+label,()=>{
      if(currentDiagnostic(target,record))views.get(target.id)?.diagnosticMarkers?.focus(record);
    },'diagnostic-jump');output.append(jump);}
    else output.append(el('span','diagnostic-stale','错误来自旧版源码，重新运行后可定位。'));
  }
}
function renderOutput(cell) {
  const view=views.get(cell.id);if(!view)return;refreshDiagnosticMarkers();
  view.element.classList.toggle('running',cell.status==='running');view.count.textContent=cell.type==='code'?(cell.status==='running'?'[ * ]':`[ ${cell.execution_count??' '} ]`):'';
  const output=view.output,form=view.form,focused=output.contains(document.activeElement)?document.activeElement:null,selection=focused&&focused.selectionStart!=null?[focused.selectionStart,focused.selectionEnd]:null;output.replaceChildren();output.hidden=cell.type!=='code'||(!cell.outputs.length&&cell.status!=='running'&&!cell.execution_count&&!form);
  if(output.hidden)return;
  const heading=el('div','output-heading'),left=el('span','','输出');heading.append(left);
  if(cell.historical)heading.append(el('span','history-label','历史输出 · 未在本会话执行'));
  else if(cell.stale)heading.append(el('span','history-label','源码已修改 · 输出来自上次运行'));
  else heading.append(el('span','cell-state'+(cell.status==='error'?' failed':''),cell.status==='running'?'运行中…':cell.status==='error'?'运行出错':cell.status==='done'?'已完成':''));
  output.append(heading,view.diagnosticLinks);
  const window=outputWindow(cell.outputs,view.outputExpanded,view.outputPage||0);view.outputPage=window.page;
  if(window.foldable){const controls=el('div','output-controls');controls.append(el('span','',`已保留 ${window.bytes.toLocaleString()} UTF-8 字节 · ${view.outputExpanded?`第 ${window.page+1}/${window.pages} 页`:'预览前 8 行 / 2,000 字符'}`));controls.append(button(view.outputExpanded?'收起输出':'展开输出','展开或收起已保留的原文',()=>{view.outputExpanded=!view.outputExpanded;view.outputPage=0;renderOutput(cell);}));if(view.outputExpanded){for(const [label,delta] of [['上一页',-1],['下一页',1]]){const nav=button(label,label,()=>{view.outputPage+=delta;renderOutput(cell);});nav.disabled=window.page+delta<0||window.page+delta>=window.pages;controls.append(nav);}}output.append(controls);}
  for(const item of window.items){if(item.type==='graphics'){try{output.append(sceneOutput(cell,item));}catch(error){output.append(el('pre','error',error.message));}}else output.append(el('pre',item.type,item.text));}
  // Diagnostics remain visible even when the text page containing them is folded.
  if(window.foldable)for(const item of cell.outputs.filter(item=>item.type==='error'||item.type==='stderr'&&item.text.includes('已截断')).slice(-2))output.append(el('pre',item.type,item.text.slice(-2000)));

  if(form)output.append(form);if(focused){focused.focus({preventScroll:true});if(selection)focused.setSelectionRange(...selection);}
}
function addCell(type,after) {if(busy())return;if(book.cells.length>=MAX_CELLS){notice('一本如书最多 500 格。',true);return;}const cell=newCell(type==='learning'?'code':type);if(type==='learning')ensureGeneration(cell,'');if(after){book.cells.splice(book.cells.indexOf(after)+1,0,cell);}else book.cells.push(cell);renderBook();markDirty();focusCell(cell);}
function focusCell(cell){const view=views.get(cell.id);if(!view)return;if(cell.type==='markdown')toggleMarkdown(cell,true);else (view.prompt||view.input).focus();view.element.scrollIntoView({block:'nearest',behavior:'smooth'});}
function focusNext(cell){const next=book.cells[book.cells.indexOf(cell)+1];if(next)focusCell(next);else if(!busy())addCell('code',cell);}
function moveCell(cell,delta){if(busy())return;const index=book.cells.indexOf(cell),next=index+delta;if(next<0||next>=book.cells.length)return;[book.cells[index],book.cells[next]]=[book.cells[next],book.cells[index]];renderBook();markDirty();focusCell(cell);}
function deleteCell(cell){if(busy())return;if((cell.source||cell.outputs.length||cell.generation?.prompt||cell.generation?.revisions.length)&&!confirm('删除这格、输出及全部版本历史？此操作无法撤销。'))return;stopScenes(true);clearScene(cell);const index=book.cells.indexOf(cell);book.cells.splice(index,1);if(!book.cells.length)book.cells.push(newCell());renderBook();markDirty();focusCell(book.cells[Math.min(index,book.cells.length-1)]);}
async function runAndMove(cell,move){if(busy()){notice('当前会话正在运行，请等待或停止后再试。');return;}const success=await runCell(cell);if(move&&success)focusNext(cell);}
async function runCell(cell) {
  if(!connected||!session){notice('会话尚未连接。请使用启动终端显示的完整网址。',true);return false;}
  if(activeRun)return false;
  if(cell.type==='markdown'){if(generationIntent(cell.source)!==null){createLearning(cell);return false;}if(views.get(cell.id)?.editing)toggleMarkdown(cell);return true;}
  const markedIntent=generationIntent(cell.source);
  if(markedIntent!==null){
    try{
      prepareGenerationFromMarker(cell);
      renderBook();markDirty();await generateCell(cell);
    }catch(error){notice(error.message,true,true);}return false;
  }
  if(cell.generation){try{checkpoint(cell);markDirty();renderHistory(cell);}catch(error){notice(error.message,true,true);return false;}}
  const myEpoch=epoch,mySession=session,myGeneration=generation;let submitted=false;let resolve;const done=new Promise(r=>resolve=r),run={cellId:cell.id,resolve,epoch:myEpoch,beforeCount:lastExecutionCount};activeRun=run;
  stopScenes();cell.outputs=[];cell.diagnostics=[];delete cell.diagnosticSnapshot;cell.outputTruncated=false;cell.stale=false;cell.historical=false;cell.status='running';cell.execution_count=null;renderOutput(cell);refreshControls();runtimeStatus('running');markDirty();
  try{
    const snapshot={source:cell.source,version:await sourceVersion(cell.source),generation:myGeneration,execution:null};
    if(myEpoch!==epoch||activeRun!==run)return done;cell.diagnosticSnapshot=snapshot;
    await closeScenesBeforeRun(mySession,myEpoch,myGeneration);if(myEpoch!==epoch||activeRun!==run)return done;clearScene(cell);submitted=true;
    const result=await api(sessionPath('/execute'),'POST',{code:snapshot.source,cell_id:cell.id,expected_generation:generation});
    if(myEpoch!==epoch)return false;if(activeRun!==run)return done;
    cell.execution_count=result.execution_count;if(cell.diagnosticSnapshot)cell.diagnosticSnapshot.execution=result.execution_count;lastExecutionCount=result.execution_count;generation=result.generation;renderOutput(cell);pollSoon(0);
  }catch(error){if(activeRun===run){if(error.definite||!submitted){cell.status='error';appendOutput(cell,'error',error.message);renderOutput(cell);finishActive(false);runtimeStatus('idle');return false;}run.uncertain=true;connected=false;runtimeStatus('dead','运行状态待确认');notice(error.message+' 请求可能已经执行，正在确认运行状态。',true,true);pollSoon(0);}return done;}
  return done;
}
async function runAll(){if(busy()||!connected)return;if(book.cells.some(c=>c.generation||generationIntent(c.source)!==null))notice('全部运行会跳过学习格和意图文档。请先审阅，再单独运行生成的代码。',false,true);runAllActive=true;const myEpoch=epoch;refreshControls();for(const cell of [...book.cells]){if(myEpoch!==epoch)break;if(cell.type==='markdown'){if(views.get(cell.id)?.editing)toggleMarkdown(cell);continue;}if(cell.generation||generationIntent(cell.source)!==null)continue;if(!await runCell(cell)){if(myEpoch===epoch)notice('运行已停在这一格。请修正错误后继续。',true);break;}}runAllActive=false;refreshControls();}
function clearInputForms(){for(const view of views.values()){if(view.form){view.form.remove();view.form=null;}}}
async function resetSession(reason){if(!session||transition)return;if(reason==='restart'&&!confirm('重启会清空本书全部变量、函数和文件句柄，已有输出将标为历史。继续吗？'))return;
  cancelGeneration(false);stopScenes();transition=true;refreshControls();epoch++;runAllActive=false;
  try{const result=await api(sessionPath('/'+reason),'POST',{});finishActive(false);clearInputForms();generation=result.generation;cursor=result.cursor;lastExecutionCount=0;kernelDead=false;historicalBook(book);connected=true;for(const cell of book.cells)renderOutput(cell);runtimeStatus('idle');markDirty();notice(reason==='stop'?'已停止。会话已重置，全部变量已清空。':'会话已重启，全部变量已清空。');}
  catch(error){connected=false;finishActive(false);runtimeStatus('dead');notice(error.message+' 运行是否停止尚未确认，请检查启动终端。',true,true);}
  finally{transition=false;refreshControls();pollSoon(0);}
}
function requestInput(cell,requestId){const view=views.get(cell.id);if(!view||view.form?.dataset.requestId===requestId)return;
  const form=el('form','input-form'),label=el('label','','程序在等你输入'),input=el('input'),submit=el('button','','提交 ↵'),eof=button('结束输入 EOF','发送输入结束 EOF，完成整段输入',()=>send(true),'input-eof');
  form.dataset.requestId=requestId;input.type='text';input.autocomplete='off';input.maxLength=65536;input.id='stdin-'+cell.id;label.htmlFor=input.id;submit.type='submit';form.append(label,input,submit,eof);view.form=form;
  async function send(end=false){if(form.dataset.pending)return;const inputEpoch=epoch,inputSession=session,inputExecution=cell.execution_count;form.dataset.pending='true';submit.disabled=true;eof.disabled=true;input.disabled=true;
    try{await api(`/sessions/${encodeURIComponent(inputSession)}/input`,'POST',{request_id:requestId,text:end?'':input.value,eof:end});if(inputEpoch!==epoch||inputSession!==session||inputExecution!==cell.execution_count)return;appendOutput(cell,'input',end?'[输入结束]\n':'> '+input.value+'\n');if(view.form===form)view.form=null;renderOutput(cell);if(activeRun?.cellId===cell.id)runtimeStatus(view.form?'waiting_input':'running');markDirty();pollSoon(0);}
    catch(error){if(inputEpoch!==epoch||inputSession!==session||inputExecution!==cell.execution_count||view.form!==form)return;delete form.dataset.pending;submit.disabled=false;eof.disabled=false;input.disabled=false;notice(error.message,true);}
  }
  form.addEventListener('submit',event=>{event.preventDefault();send();});renderOutput(cell);input.focus();runtimeStatus('waiting_input');
}
let pollTimer;
function pollSoon(delay=150){clearTimeout(pollTimer);pollTimer=setTimeout(pollEvents,delay);}
async function pollEvents(){if(polling){pollSoon();return;}if(!session||transition){pollSoon(500);return;}polling=true;const id=session,myEpoch=epoch;let more=false;
  try{
    const result=await api(`/sessions/${encodeURIComponent(id)}/events?after=${cursor}`);if(id!==session||myEpoch!==epoch)return;
    const changed=new Set();
    if(result.truncated){notice('部分较早的运行输出已超过服务保留上限。当前显示可能不完整。',true,true);const cell=book.cells.find(c=>c.id===result.cell_id);if(cell){appendOutput(cell,'error','[会话历史超限：部分未接收的输出已丢弃；此快照可能不完整。]\n');changed.add(cell);}}
    for(const event of result.events||[]){
      if(event.seq<=cursor)continue;cursor=event.seq;
      if(event.type==='reset'){stopScenes();generation=event.generation;historicalBook(book);clearInputForms();finishActive(false);book.cells.forEach(c=>changed.add(c));continue;}
      if(event.generation!==generation)continue;
      const cell=book.cells.find(c=>c.id===event.cell_id);if(!cell)continue;
      // A closing canvas can still emit events from the previous execution.
      if(activeRun?.cellId===cell.id&&event.execution_count<=activeRun.beforeCount)continue;
      // A poll may beat the execute response: use the authoritative event count.
      if(cell.status==='running'&&cell.execution_count==null){cell.execution_count=event.execution_count;if(cell.diagnosticSnapshot)cell.diagnosticSnapshot.execution=event.execution_count;}
      if(cell.execution_count!==event.execution_count)continue;
      if(event.type==='graphics'){
        try{const scene=validateScene(event);const prior=cell.outputs.find(item=>item.type==='graphics');if(prior){if(prior.scene.canvas_id!==scene.canvas_id)clearScene(cell);retainGraphics(cell,scene,book);}else retainGraphics(cell,scene,book);changed.add(cell);}catch(error){appendOutput(cell,'error',error.message+'\n');changed.add(cell);}
      }else if(event.type==='graphics_done'||event.type==='graphics_closed'){if(event.type==='graphics_done'&&event.status==='error'){cell.status='error';changed.add(cell);}const pending=scenePending.get(event.canvas_id);if(pending){scenePending.delete(event.canvas_id);if(event.status==='error')pending.reject(new Error('画布回调运行出错'));else pending.resolve();}if(event.type==='graphics_closed'||event.status==='error')sceneViews.get(event.canvas_id)?.view.deactivate();
      }else if(event.type==='output'){appendOutput(cell,event.stream==='stderr'?'stderr':'stdout',event.text);changed.add(cell);}
      else if(event.type==='error'){const position=diagnosticLocation(event,true);const text=typeof event.diagnostic?.formatted==='string'?event.diagnostic.formatted:(position?position+'\n':'')+event.message;appendOutput(cell,'error',text+'\n');const diagnostic=captureDiagnostic(book,event);if(diagnostic){cell.diagnostics??=[];if(cell.diagnostics.length<20)cell.diagnostics.push(diagnostic);}changed.add(cell);}
      else if(event.type==='input_request'){requestInput(cell,event.request_id);}
      else if(event.type==='done'){cell.status=event.status==='ok'?'done':'error';changed.add(cell);if(activeRun?.cellId===cell.id)finishActive(event.status==='ok');}
    }
    cursor=Math.max(cursor,result.cursor||0);lastExecutionCount=result.execution_count;kernelDead=result.state==='dead';connected=!kernelDead;runtimeStatus(result.state);
    if(activeRun?.uncertain&&result.state==='idle'&&result.execution_count<=activeRun.beforeCount){const cell=book.cells.find(c=>c.id===activeRun.cellId);if(cell){cell.status='error';appendOutput(cell,'error','已确认本次请求未执行。请重试。\n');changed.add(cell);}finishActive(false);}
    changed.forEach(renderOutput);if(changed.size)markDirty();
    if(result.state==='dead'){stopScenes();if(activeRun){const cell=book.cells.find(c=>c.id===activeRun.cellId);if(cell){cell.status='error';appendOutput(cell,'error','运行进程已退出。请重启会话。\n');renderOutput(cell);}finishActive(false);}notice('运行进程已退出，请重启会话。',true,true);}
    refreshControls();more=!!result.more;
  }catch(error){if(id===session&&myEpoch===epoch){connected=false;stopScenes();runtimeStatus('dead','连接中断');refreshControls();notice(error.message+' 正在等待本机服务恢复。',true,true);}}
  finally{polling=false;if(session&&!kernelDead)pollSoon(more?0:connected?(activeRun||scenePending.size?50:1200):2500);}
}
function saveBook(){if(!hasBook||transition)return;try{let fullHistory=false;for(const cell of book.cells)if(cell.generation){try{checkpoint(cell);}catch{fullHistory=true;}renderHistory(cell);}book.title=$('#book-title').value.trim()||'未命名如书';const text=serializeBook(book),blob=new Blob([text],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),link=el('a');link.href=url;link.download=book.title.replace(/[\\/:*?"<>|\x00-\x1f]/g,'_').slice(0,100)+'.rushu.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);dirty=false;$('#document-status').textContent='已导出保存快照';notice(fullHistory?'已下载保存当前草稿与已有历史。部分历史已满，最新编辑保留为当前草稿；请点击「另起学习格」继续记录。':'已下载如书文件。重新打开时，输出会标为历史；运行状态不会被保存。',false,fullHistory);}catch(error){notice('无法保存：'+error.message+' 请减少内容或清除部分输出后重试。',true,true);}}
$('#book-title').addEventListener('input',()=>{book.title=$('#book-title').value;markDirty();updateMeta();});
function showTemplates(){if(transition)return;$('#template-dialog').showModal();}
async function chooseTemplate(id){
  if(transition||!confirmReplace())return;
  const next=createTemplateBook(id);if($('#template-dialog').open)$('#template-dialog').close();
  try{if(await replaceBook(next)){notice('已新建如书。代码尚未运行；可先阅读，再逐格试试。');focusCell(book.cells.find(cell=>cell.type==='code')||book.cells[0]);}}
  catch(error){notice(error.message+(hasBook?' 原书内容仍保留，可重试。':' 尚未创建如书，可重试。'),true,true);}
}
function renderTemplates(target){
  for(const template of templates){
    const choice=button('',`新建${template.title}`,()=>chooseTemplate(template.id),'template-card'+(template.id==='blank'?' template-blank':''));
    choice.dataset.template=template.id;
    choice.append(el('span','template-title',template.title),el('span','template-description',template.description));
    if(template.detail)choice.append(el('span','template-detail',template.detail));
    choice.append(el('span','template-action',template.id==='blank'?'直接开始 →':'使用模板 →'));target.append(choice);
  }
}
renderTemplates($('#start-templates'));renderTemplates($('#dialog-templates'));
$('#new-book').addEventListener('click',showTemplates);
$('#start-blank').addEventListener('click',()=>chooseTemplate('blank'));$('#dialog-blank').addEventListener('click',()=>chooseTemplate('blank'));
$('#close-templates').addEventListener('click',()=>$('#template-dialog').close());
$('#template-dialog').addEventListener('click',event=>{if(event.target===$('#template-dialog')){const r=event.target.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)event.target.close();}});
$('#open-book').addEventListener('click',()=>$('#file-picker').click());
$('#file-picker').addEventListener('change',async event=>{const file=event.target.files?.[0];event.target.value='';if(!file)return;try{if(file.size>MAX_FILE_BYTES)throw new Error('文件太大，请打开 64 MiB 以内的如书。');const next=parseBook(await file.text());if(!confirmReplace())return;if(await replaceBook(next)){dirty=false;$('#document-status').textContent='已打开本地文件';notice('已打开。未自动执行任何代码，保存的输出仅为历史快照。',false,true);}}catch(error){notice(error.message,true,true);}});
$('#save-book').addEventListener('click',saveBook);$('#run-all').addEventListener('click',runAll);$('#stop').addEventListener('click',()=>resetSession('stop'));$('#restart').addEventListener('click',()=>resetSession('restart'));
$('#add-code').addEventListener('click',()=>addCell('code'));$('#add-markdown').addEventListener('click',()=>addCell('markdown'));$('#add-learning').addEventListener('click',()=>addCell('learning'));
$('#help-button').addEventListener('click',()=>$('#help-dialog').showModal());$('#close-help').addEventListener('click',()=>$('#help-dialog').close());
$('#help-dialog').addEventListener('click',event=>{if(event.target===$('#help-dialog')){const r=event.target.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)event.target.close();}});
document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();saveBook();}});
window.addEventListener('pagehide',()=>{stopScenes();cancelGeneration(false);if(session)fetch('/api'+sessionPath(),{method:'DELETE',headers:{'X-Rushu-Token':token,'Content-Type':'application/json'},body:'{}',keepalive:true}).catch(()=>{});});
window.addEventListener('pageshow',event=>{if(event.persisted&&hasBook){historicalBook(book);replaceBook(book).catch(error=>notice(error.message,true,true));}});
window.addEventListener('beforeunload',event=>{if(dirty||activeRun||generationRequest){event.preventDefault();event.returnValue='';}});
const keyboardHelp=el('span','sr-only','按 Tab 缩进。按 Escape 后再按 Tab 可移出编辑器。Shift 加 Enter 运行。');keyboardHelp.id='editor-keyboard-help';document.body.append(keyboardHelp);
refreshControls();
if(!token){runtimeStatus('dead','缺少连接凭据');notice('请使用启动终端显示的完整本机网址打开如书（包含 #token=…）。内容仍可编辑和保存。',true,true);}
else{api('/versions').then(info=>{$('#versions').textContent=versionLabel(info);}).catch(()=>{$('#versions').textContent='版本读取失败';});}
