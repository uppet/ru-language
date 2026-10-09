import {analyze,highlight,enterEdit,indentSelection} from './editor.mjs';
import {welcomeBook,blankBook,newCell,parseBook,serializeBook,appendOutput,historicalBook,MAX_FILE_BYTES,MAX_CELLS,MAX_SOURCE} from './notebook.mjs';

const $=selector=>document.querySelector(selector);
const el=(tag,cls,text)=>{const node=document.createElement(tag);if(cls)node.className=cls;if(text!=null)node.textContent=text;return node;};
const button=(text,title,handler,cls='')=>{const node=el('button',cls,text);node.type='button';node.title=title;node.setAttribute('aria-label',title);node.addEventListener('click',handler);return node;};
let book=welcomeBook(),session=null,cursor=0,generation=1,activeRun=null,runAllActive=false,polling=false,epoch=0,dirty=true,transition=false,connected=false,lastExecutionCount=0,kernelDead=false;
const views=new Map();
let token=new URLSearchParams(location.hash.slice(1)).get('token')||'';
try { const key='rushu-token:'+location.origin; if(token){sessionStorage.setItem(key,token);history.replaceState(null,'',location.pathname+location.search);} else token=sessionStorage.getItem(key)||''; } catch { /* Session storage is optional. */ }
let noticeTimer;
function notice(message,error=false,persistent=false) { clearTimeout(noticeTimer);const node=$('#notice');node.textContent=message;node.classList.toggle('error',error);node.hidden=false;if(!persistent)noticeTimer=setTimeout(()=>node.hidden=true,7000); }
function markDirty(){dirty=true;$('#document-status').textContent='有未保存的更改';}
function updateMeta() { $('#cell-count').textContent=`${book.cells.length} 格`;document.title=`${book.title||'未命名如书'} · 如书`; }
function runtimeStatus(state,label) { const node=$('#runtime-status');node.className='runtime-status '+(state==='running'||state==='waiting_input'?'running':state==='dead'?'error':'');node.querySelector('span').textContent=label||({idle:'会话就绪',running:'正在运行',waiting_input:'等待输入',dead:'会话已断开'}[state]||'连接中'); }
function busy(){return !!activeRun||runAllActive||transition;}
function refreshControls() {
  $('#run-all').disabled=!connected||busy();$('#restart').disabled=!session||transition;$('#stop').disabled=!activeRun||transition;
  $('#new-book').disabled=transition;$('#open-book').disabled=transition;
  $('#add-code').disabled=busy()||book.cells.length>=MAX_CELLS;$('#add-markdown').disabled=busy()||book.cells.length>=MAX_CELLS;
  for(const cell of book.cells){const view=views.get(cell.id);if(!view)continue;for(const b of view.element.querySelectorAll('[data-mutates]'))b.disabled=busy();view.run.disabled=!connected||busy();if(view.input)view.input.readOnly=cell.status==='running';}
}
async function api(path,method='GET',body) {
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),12000);
  try {
    const response=await fetch('/api'+path,{method,headers:{'X-Rushu-Token':token,...(method!=='GET'?{'Content-Type':'application/json'}:{})},body:method==='GET'?undefined:JSON.stringify(body??{}),signal:controller.signal,cache:'no-store',credentials:'same-origin'});
    let data;try{data=await response.json();}catch{throw new Error('服务没有返回有效响应，请检查启动终端。');}
    if(!response.ok){const error=new Error(data.error||`请求失败（${response.status}）`);error.definite=true;throw error;}return data;
  } catch(error){if(error.name==='AbortError')throw new Error('本机服务响应超时，请检查启动终端。');throw error;}finally{clearTimeout(timeout);}
}
function sessionPath(suffix=''){return `/sessions/${encodeURIComponent(session)}${suffix}`;}
function finishActive(success=false) { if(!activeRun)return;const run=activeRun;activeRun=null;run.resolve(success);refreshControls(); }
async function replaceBook(next) {
  transition=true;refreshControls();
  try {
    const result=await api('/sessions','POST',{});const old=session;epoch++;finishActive(false);runAllActive=false;
    session=result.id;cursor=result.cursor||0;generation=result.generation||1;lastExecutionCount=0;kernelDead=false;connected=true;book=next;
    $('#book-title').value=book.title;renderBook();runtimeStatus('idle');markDirty();
    if(old)api(`/sessions/${encodeURIComponent(old)}`,'DELETE',{}).catch(error=>notice('新会话已创建，但旧会话未能关闭：'+error.message,true,true));
    pollSoon(0);
  } finally {transition=false;refreshControls();}
}
function confirmReplace(){return !dirty&&!activeRun||confirm((activeRun?'当前代码仍在运行，继续会结束旧会话。\n':'')+'尚未保存的内容可能丢失。要继续吗？');}

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
    guides.replaceChildren(fragment);sync();
  };
  function applyEdit(edit){input.setRangeText(edit.text,edit.start,edit.end,'end');input.setSelectionRange(edit.selectionStart??edit.selection??input.selectionStart,edit.selectionEnd??edit.selection??input.selectionEnd);update();}
  function update(auto=false){
    if(auto&&!composing){const pos=input.selectionStart,start=input.value.lastIndexOf('\n',pos-1)+1,end=input.value.indexOf('\n',pos),line=input.value.slice(start,end<0?undefined:end);
      if(/^\s*(法|为|然|环|象|终|成|另|则|救)(?:\s|[。.：:]|$)/.test(line)){
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
  view.renderEditor=render;render();return shell;
}
function renderCell(cell) {
  const element=el('section','cell '+cell.type),head=el('div','cell-head'),kind=el('div','cell-type'),count=el('span','counter'),tools=el('div','cell-tools');element.dataset.cellId=cell.id;
  const view={element,count,input:null,renderEditor:null,output:el('div','cell-output')};views.set(cell.id,view);
  kind.append(el('span','kind-icon',cell.type==='code'?'⌘':'¶'),el('span','',cell.type==='code'?'如代码':'文字'),count);
  const run=button(cell.type==='code'?'▶ 运行':'编辑',cell.type==='code'?'运行此代码格，Ctrl 或 Command + Enter':'编辑文字',()=>cell.type==='code'?runAndMove(cell,false):toggleMarkdown(cell), 'run-cell');view.run=run;
  tools.append(run);
  if(cell.type==='code'){const clear=button('清除输出','清除这格的输出快照',()=>{cell.outputs=[];cell.execution_count=null;cell.historical=false;cell.status='idle';renderOutput(cell);markDirty();},'clear-output');clear.dataset.mutates='true';tools.append(clear);}
  for(const [text,title,handler,cls] of [['↑','向上移动格子',()=>moveCell(cell,-1),'icon-button'],['↓','向下移动格子',()=>moveCell(cell,1),'icon-button'],['×','删除这格',()=>deleteCell(cell),'icon-button danger']]){const b=button(text,title,handler,cls);b.dataset.mutates='true';tools.append(b);}
  head.append(kind,tools);element.append(head);
  if(cell.type==='code')element.append(buildEditor(cell,view));
  else {
    const preview=el('div','markdown-view');preview.tabIndex=0;preview.setAttribute('aria-label','文字内容，按 Enter 编辑');renderMarkdown(preview,cell.source);
    preview.addEventListener('dblclick',()=>toggleMarkdown(cell,true));preview.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();toggleMarkdown(cell,true);}});view.preview=preview;element.append(preview);
  }
  element.append(view.output);renderOutput(cell);return element;
}
function toggleMarkdown(cell,forceEdit=false) {
  const view=views.get(cell.id);if(!view||cell.type!=='markdown')return;
  if(view.editing&&!forceEdit){view.editing.remove();view.editing=null;view.input=null;view.preview.hidden=false;view.run.textContent='编辑';renderMarkdown(view.preview,cell.source);view.preview.focus();return;}
  if(view.editing){view.input.focus();return;}
  view.preview.hidden=true;const edit=el('div','markdown-edit'),input=el('textarea');input.value=cell.source;input.maxLength=MAX_SOURCE;input.setAttribute('aria-label','Markdown 文字');input.addEventListener('input',()=>{cell.source=input.value;markDirty();});
  input.addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey||event.shiftKey)){event.preventDefault();toggleMarkdown(cell);if(event.shiftKey)focusNext(cell);}});
  edit.append(input,el('div','markdown-hint','Markdown · Shift + Enter 完成编辑'));view.preview.after(edit);view.editing=edit;view.input=input;view.run.textContent='完成';input.focus();
}
function renderBook(){views.clear();$('#cells').replaceChildren(...book.cells.map(renderCell));updateMeta();refreshControls();}
function renderOutput(cell) {
  const view=views.get(cell.id);if(!view)return;
  view.element.classList.toggle('running',cell.status==='running');view.count.textContent=cell.type==='code'?(cell.status==='running'?'[ * ]':`[ ${cell.execution_count??' '} ]`):'';
  const output=view.output,form=view.form,focused=form?.contains(document.activeElement)?document.activeElement:null,selection=focused&&focused.selectionStart!=null?[focused.selectionStart,focused.selectionEnd]:null;output.replaceChildren();output.hidden=cell.type!=='code'||(!cell.outputs.length&&cell.status!=='running'&&!cell.execution_count&&!form);
  if(output.hidden)return;
  const heading=el('div','output-heading'),left=el('span','','输出');heading.append(left);
  if(cell.historical)heading.append(el('span','history-label','历史输出 · 未在本会话执行'));
  else if(cell.stale)heading.append(el('span','history-label','源码已修改 · 输出来自上次运行'));
  else heading.append(el('span','cell-state'+(cell.status==='error'?' failed':''),cell.status==='running'?'运行中…':cell.status==='error'?'运行出错':cell.status==='done'?'已完成':''));
  output.append(heading);
  for(const item of cell.outputs)output.append(el('pre',item.type,item.text));
  if(form)output.append(form);if(focused){focused.focus({preventScroll:true});if(selection)focused.setSelectionRange(...selection);}
}
function addCell(type,after) {if(busy())return;if(book.cells.length>=MAX_CELLS){notice('一本如书最多 500 格。',true);return;}const cell=newCell(type);if(after){book.cells.splice(book.cells.indexOf(after)+1,0,cell);}else book.cells.push(cell);renderBook();markDirty();focusCell(cell);}
function focusCell(cell){const view=views.get(cell.id);if(!view)return;if(cell.type==='markdown')toggleMarkdown(cell,true);else view.input.focus();view.element.scrollIntoView({block:'nearest',behavior:'smooth'});}
function focusNext(cell){const next=book.cells[book.cells.indexOf(cell)+1];if(next)focusCell(next);else if(!busy())addCell('code',cell);}
function moveCell(cell,delta){if(busy())return;const index=book.cells.indexOf(cell),next=index+delta;if(next<0||next>=book.cells.length)return;[book.cells[index],book.cells[next]]=[book.cells[next],book.cells[index]];renderBook();markDirty();focusCell(cell);}
function deleteCell(cell){if(busy())return;if((cell.source||cell.outputs.length)&&!confirm('删除这格及其输出？此操作无法撤销。'))return;const index=book.cells.indexOf(cell);book.cells.splice(index,1);if(!book.cells.length)book.cells.push(newCell());renderBook();markDirty();focusCell(book.cells[Math.min(index,book.cells.length-1)]);}
async function runAndMove(cell,move){if(busy()){notice('当前会话正在运行，请等待或停止后再试。');return;}const success=await runCell(cell);if(move&&success)focusNext(cell);}
async function runCell(cell) {
  if(!connected||!session){notice('会话尚未连接。请使用启动终端显示的完整网址。',true);return false;}
  if(activeRun)return false;
  if(cell.type==='markdown'){if(views.get(cell.id)?.editing)toggleMarkdown(cell);return true;}
  const myEpoch=epoch;let resolve;const done=new Promise(r=>resolve=r),run={cellId:cell.id,resolve,epoch:myEpoch,beforeCount:lastExecutionCount};activeRun=run;
  cell.outputs=[];cell.outputTruncated=false;cell.stale=false;cell.historical=false;cell.status='running';cell.execution_count=null;renderOutput(cell);refreshControls();runtimeStatus('running');markDirty();
  try{
    const result=await api(sessionPath('/execute'),'POST',{code:cell.source,cell_id:cell.id,expected_generation:generation});
    if(myEpoch!==epoch)return false;if(activeRun!==run)return done;
    cell.execution_count=result.execution_count;lastExecutionCount=result.execution_count;generation=result.generation;renderOutput(cell);pollSoon(0);
  }catch(error){if(activeRun===run){if(error.definite){cell.status='error';appendOutput(cell,'error',error.message);renderOutput(cell);finishActive(false);runtimeStatus('idle');return false;}run.uncertain=true;connected=false;runtimeStatus('dead','运行状态待确认');notice(error.message+' 请求可能已经执行，正在确认运行状态。',true,true);pollSoon(0);}return done;}
  return done;
}
async function runAll(){if(busy()||!connected)return;runAllActive=true;const myEpoch=epoch;refreshControls();for(const cell of [...book.cells]){if(myEpoch!==epoch)break;if(cell.type==='markdown'){if(views.get(cell.id)?.editing)toggleMarkdown(cell);continue;}if(!await runCell(cell)){if(myEpoch===epoch)notice('运行已停在这一格。请修正错误后继续。',true);break;}}runAllActive=false;refreshControls();}
function clearInputForms(){for(const view of views.values()){if(view.form){view.form.remove();view.form=null;}}}
async function resetSession(reason){if(!session||transition)return;if(reason==='restart'&&!confirm('重启会清空本书全部变量、函数和文件句柄，已有输出将标为历史。继续吗？'))return;
  transition=true;refreshControls();epoch++;runAllActive=false;
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
async function pollEvents(){if(polling){pollSoon();return;}if(!session||transition){pollSoon(500);return;}polling=true;const id=session,myEpoch=epoch;
  try{
    const result=await api(`/sessions/${encodeURIComponent(id)}/events?after=${cursor}`);if(id!==session||myEpoch!==epoch)return;
    if(result.truncated)notice('部分较早的运行输出已超过服务保留上限。当前显示可能不完整。',true,true);
    const changed=new Set();
    for(const event of result.events||[]){
      if(event.seq<=cursor)continue;cursor=event.seq;
      if(event.type==='reset'){generation=event.generation;historicalBook(book);clearInputForms();finishActive(false);book.cells.forEach(c=>changed.add(c));continue;}
      if(event.generation!==generation)continue;
      const cell=book.cells.find(c=>c.id===event.cell_id);if(!cell)continue;
      // A poll may beat the execute response: use the authoritative event count.
      if(cell.status==='running'&&cell.execution_count==null)cell.execution_count=event.execution_count;
      if(cell.execution_count!==event.execution_count)continue;
      if(event.type==='output'){appendOutput(cell,event.stream==='stderr'?'stderr':'stdout',event.text);changed.add(cell);}
      else if(event.type==='error'){const position=event.line?`第 ${event.line} 行${event.col?'，第 '+event.col+' 列':''}\n`:'';appendOutput(cell,'error',position+event.message+'\n');changed.add(cell);}
      else if(event.type==='input_request'){requestInput(cell,event.request_id);}
      else if(event.type==='done'){cell.status=event.status==='ok'?'done':'error';changed.add(cell);if(activeRun?.cellId===cell.id)finishActive(event.status==='ok');}
    }
    cursor=Math.max(cursor,result.cursor||0);lastExecutionCount=result.execution_count;kernelDead=result.state==='dead';connected=!kernelDead;runtimeStatus(result.state);
    if(activeRun?.uncertain&&result.state==='idle'&&result.execution_count<=activeRun.beforeCount){const cell=book.cells.find(c=>c.id===activeRun.cellId);if(cell){cell.status='error';appendOutput(cell,'error','已确认本次请求未执行。请重试。\n');changed.add(cell);}finishActive(false);}
    changed.forEach(renderOutput);if(changed.size)markDirty();
    if(result.state==='dead'){if(activeRun){const cell=book.cells.find(c=>c.id===activeRun.cellId);if(cell){cell.status='error';appendOutput(cell,'error','运行进程已退出。请重启会话。\n');renderOutput(cell);}finishActive(false);}notice('运行进程已退出，请重启会话。',true,true);}
    refreshControls();
  }catch(error){if(id===session&&myEpoch===epoch){connected=false;runtimeStatus('dead','连接中断');refreshControls();notice(error.message+' 正在等待本机服务恢复。',true,true);}}
  finally{polling=false;if(session&&!kernelDead)pollSoon(connected?(activeRun?150:1200):2500);}
}
function saveBook(){try{book.title=$('#book-title').value.trim()||'未命名如书';const text=serializeBook(book),blob=new Blob([text],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),link=el('a');link.href=url;link.download=book.title.replace(/[\\/:*?"<>|\x00-\x1f]/g,'_').slice(0,100)+'.rushu.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);dirty=false;$('#document-status').textContent='已导出保存快照';notice('已下载如书文件。重新打开时，输出会标为历史；运行状态不会被保存。');}catch(error){notice('无法保存：'+error.message+' 请减少内容或清除部分输出后重试。',true,true);}}
$('#book-title').addEventListener('input',()=>{book.title=$('#book-title').value;markDirty();updateMeta();});
$('#new-book').addEventListener('click',async()=>{if(!confirmReplace())return;try{await replaceBook(blankBook());notice('已新建独立会话。');focusCell(book.cells[0]);}catch(error){notice(error.message,true,true);}});
$('#open-book').addEventListener('click',()=>$('#file-picker').click());
$('#file-picker').addEventListener('change',async event=>{const file=event.target.files?.[0];event.target.value='';if(!file)return;try{if(file.size>MAX_FILE_BYTES)throw new Error('文件太大，请打开 10 MB 以内的如书。');const next=parseBook(await file.text());if(!confirmReplace())return;await replaceBook(next);dirty=false;$('#document-status').textContent='已打开本地文件';notice('已打开。未自动执行任何代码，保存的输出仅为历史快照。',false,true);}catch(error){notice(error.message,true,true);}});
$('#save-book').addEventListener('click',saveBook);$('#run-all').addEventListener('click',runAll);$('#stop').addEventListener('click',()=>resetSession('stop'));$('#restart').addEventListener('click',()=>resetSession('restart'));
$('#add-code').addEventListener('click',()=>addCell('code'));$('#add-markdown').addEventListener('click',()=>addCell('markdown'));
$('#help-button').addEventListener('click',()=>$('#help-dialog').showModal());$('#close-help').addEventListener('click',()=>$('#help-dialog').close());
$('#help-dialog').addEventListener('click',event=>{if(event.target===$('#help-dialog')){const r=event.target.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)event.target.close();}});
document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();saveBook();}});
window.addEventListener('pagehide',()=>{if(session)fetch('/api'+sessionPath(),{method:'DELETE',headers:{'X-Rushu-Token':token,'Content-Type':'application/json'},body:'{}',keepalive:true}).catch(()=>{});});
window.addEventListener('pageshow',event=>{if(event.persisted){historicalBook(book);replaceBook(book).catch(error=>notice(error.message,true,true));}});
window.addEventListener('beforeunload',event=>{if(dirty||activeRun){event.preventDefault();event.returnValue='';}});
const keyboardHelp=el('span','sr-only','按 Tab 缩进。按 Escape 后再按 Tab 可移出编辑器。Shift 加 Enter 运行。');keyboardHelp.id='editor-keyboard-help';document.body.append(keyboardHelp);
renderBook();
if(!token){runtimeStatus('dead','缺少连接凭据');notice('请使用启动终端显示的完整本机网址打开如书（包含 #token=…）。内容仍可编辑和保存。',true,true);}
else{replaceBook(book).catch(error=>{runtimeStatus('dead','连接失败');notice(error.message+' 请使用启动终端显示的完整网址。',true,true);});}
