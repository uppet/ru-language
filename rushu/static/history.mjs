/** Data-only, bounded cell history. Imported text is never code, HTML, or instructions. */
export const MAX_REVISIONS=100;
export const MAX_HISTORY_BYTES=2*1024*1024;
export const MAX_HISTORY_TEXT=200000;
const encoder=new TextEncoder();
const kinds=new Set(['human','model','restore']);
function fail(message) { throw new Error(`生成历史：${message}`); }
function text(value,label) { if(typeof value!=='string'||value.length>MAX_HISTORY_TEXT) fail(`${label}需要是 200,000 字符以内的文字。`); return value; }
function keys(value,allowed) {
  if(!value||typeof value!=='object'||Array.isArray(value)||![Object.prototype,null].includes(Object.getPrototypeOf(value))) fail('数据格式无效。');
  if(Object.keys(value).some(key=>!allowed.includes(key))) fail('包含不支持的字段。');
}
export function validateGeneration(input) {
  keys(input,['prompt','revisions']);
  const prompt=text(input.prompt,'提示');
  if(!Array.isArray(input.revisions)||input.revisions.length>MAX_REVISIONS) fail('最多保存 100 个版本；导出仍会保留当前草稿和历史，请新建学习格继续。');
  const ids=new Set();let previous=-Infinity;
  const revisions=input.revisions.map(revision=>{
    keys(revision,['id','timestamp','kind','prompt','source','restoredFrom']);
    if(typeof revision.id!=='string'||! /^[\w-]{1,128}$/.test(revision.id)||ids.has(revision.id)) fail('版本编号无效或重复。');
    const stamp=typeof revision.timestamp==='string'?Date.parse(revision.timestamp):NaN;
    if(!Number.isFinite(stamp)||new Date(stamp).toISOString()!==revision.timestamp||stamp<previous) fail('版本时间或顺序无效。');
    if(!kinds.has(revision.kind)) fail('版本类型无效。');
    const result={id:revision.id,timestamp:revision.timestamp,kind:revision.kind,prompt:text(revision.prompt,'提示'),source:text(revision.source,'代码')};
    if(revision.kind==='restore') {
      if(typeof revision.restoredFrom!=='string'||!ids.has(revision.restoredFrom)) fail('恢复来源必须是前面的已有版本。');
      result.restoredFrom=revision.restoredFrom;
    } else if(Object.hasOwn(revision,'restoredFrom')) fail('只有恢复版本可以带恢复来源。');
    ids.add(revision.id);previous=stamp;return result;
  });
  const result={prompt,revisions};
  if(encoder.encode(JSON.stringify(revisions)).length>MAX_HISTORY_BYTES) fail('单格历史超过 2 MiB；导出仍会保留当前草稿和历史，请新建学习格继续。');
  return result;
}
function requireCell(cell) { if(!cell||cell.type!=='code') fail('只有代码格可以保存生成历史。');text(cell.source,'代码'); }
export function ensureGeneration(cell,prompt='') {
  requireCell(cell);
  if(cell.generation===undefined) cell.generation=validateGeneration({prompt,revisions:[]});
  else cell.generation=validateGeneration(cell.generation);
  return cell.generation;
}
function snapshot(generation,source,kind,extra={}) {
  if(!kinds.has(kind)) fail('版本类型无效。');
  text(source,'代码');text(generation.prompt,'提示');
  const last=generation.revisions.at(-1);
  if(kind==='human'&&last?.source===source&&last.prompt===generation.prompt) return last;
  const id='revision-'+(globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2));
  const timestamp=new Date(Math.max(Date.now(),last?Date.parse(last.timestamp):0)).toISOString();
  const revision={id,timestamp,kind,prompt:generation.prompt,source};
  if(kind==='restore') revision.restoredFrom=extra.restoredFrom;
  generation.revisions.push(revision);return revision;
}
/** Validates before committing; a rejected checkpoint leaves the cell untouched. */
export function checkpoint(cell,kind='human',extra={}) {
  requireCell(cell);
  const candidate=validateGeneration(cell.generation??{prompt:'',revisions:[]});
  const revision=snapshot(candidate,cell.source,kind,extra);
  cell.generation=validateGeneration(candidate);
  return cell.generation.revisions.find(item=>item.id===revision.id);
}
/** Atomic preflight + commit of the human checkpoint and replacement snapshot.
 * On capacity/validation errors neither source, prompt, nor history changes. */
export function replaceWithRevision(cell,{source,prompt,kind='model',restoredFrom}={}) {
  requireCell(cell);text(source,'代码');text(prompt,'提示');
  if(!['model','restore'].includes(kind)) fail('替换类型需要是 model 或 restore。');
  const candidate=validateGeneration(cell.generation??{prompt:'',revisions:[]});
  snapshot(candidate,cell.source,'human');
  candidate.prompt=prompt;
  const revision=snapshot(candidate,source,kind,{restoredFrom});
  const safe=validateGeneration(candidate);
  cell.generation=safe;cell.source=source;
  return safe.revisions.find(item=>item.id===revision.id);
}
export function restoreRevision(cell,id) {
  requireCell(cell);
  const generation=validateGeneration(cell.generation);
  const revision=generation.revisions.find(item=>item.id===id);
  if(!revision) fail('找不到要恢复的版本。');
  return replaceWithRevision(cell,{source:revision.source,prompt:revision.prompt,kind:'restore',restoredFrom:id});
}
/** Line diff as text chunks. LCS is capped at 100,000 cells; large changes use
 * a linear prefix/suffix comparison with a remove/add middle, never quadratic. */
export function lineDiff(before,after) {
  text(before,'旧代码');text(after,'新代码');
  const lines=value=>value.match(/[^\n]*\n|[^\n]+$/g)||[];
  const a=lines(before),b=lines(after),out=[];
  const emit=(type,value)=>{if(!value)return;const last=out.at(-1);if(last?.type===type)last.text+=value;else out.push({type,text:value});};
  let start=0,endA=a.length,endB=b.length;
  while(start<endA&&start<endB&&a[start]===b[start])start++;
  while(endA>start&&endB>start&&a[endA-1]===b[endB-1]){endA--;endB--;}
  emit('equal',a.slice(0,start).join(''));
  const n=endA-start,m=endB-start;
  if((n+1)*(m+1)<=100000) {
    const width=m+1,dp=new Uint32Array((n+1)*width);
    for(let i=n-1;i>=0;i--)for(let j=m-1;j>=0;j--)dp[i*width+j]=a[start+i]===b[start+j]?1+dp[(i+1)*width+j+1]:Math.max(dp[(i+1)*width+j],dp[i*width+j+1]);
    let i=0,j=0;
    while(i<n||j<m) {
      if(i<n&&j<m&&a[start+i]===b[start+j]){emit('equal',a[start+i]);i++;j++;}
      else if(i<n&&(j===m||dp[(i+1)*width+j]>=dp[i*width+j+1]))emit('remove',a[start+i++]);
      else emit('add',b[start+j++]);
    }
  } else {emit('remove',a.slice(start,endA).join(''));emit('add',b.slice(start,endB).join(''));}
  emit('equal',a.slice(endA).join(''));return out;
}

export const GENERATION_MARKER='如是我言';
/** Advisory counterpart of rulang.modules.generation_intent; server is authoritative. */
export function generationIntent(source) {
  if(typeof source!=='string'||source.length>MAX_HISTORY_TEXT)return null;
  // Match Python splitlines(keepends=True), including Unicode line separators.
  const lines=source.match(/[^\n\r\v\f\x1c-\x1e\x85\u2028\u2029]*(?:\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029])|[^\n\r\v\f\x1c-\x1e\x85\u2028\u2029]+$/g)||[];
  const strip=value=>value.replace(/^[ \t\n\r\v\f\x1c-\x1f\x85\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[ \t\n\r\v\f\x1c-\x1f\x85\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g,'');
  while(lines.length&&!strip(lines.at(-1)))lines.pop();
  if(!lines.length||strip(lines.at(-1))!==GENERATION_MARKER)return null;
  const prefix=lines.slice(0,-1).join(''),quotes={"'":"'",'"':'"','‘':'’','“':'”'};
  const marker=(i,name)=>prefix[i]===name&&/[.。]/.test(prefix[i+1]||'')&&(i===0||!/[\p{L}\p{N}_]/u.test(Array.from(prefix.slice(Math.max(0,i-2),i)).at(-1)));
  let closing=null,i=0;
  while(i<prefix.length) {
    const char=prefix[i];
    if(closing) {
      if(char==='\\'){i+=2;continue;}
      if(char===closing)closing=null;
    } else if(char==='#'||prefix.startsWith('//',i)||marker(i,'批')) {
      const newline=prefix.indexOf('\n',i);i=newline<0?prefix.length:newline;
    } else if(marker(i,'解')) {
      const close=/释[.。]/u.exec(prefix.slice(i+2));
      if(!close)return null;
      i+=2+close.index+close[0].length;continue;
    } else if(Object.hasOwn(quotes,char)) {
      const contraction=char==="'"&&/[A-Za-z]/.test(prefix[i-1]||'')&&/[A-Za-z]/.test(prefix[i+1]||'');
      if(!contraction)closing=quotes[char];
    }
    i++;
  }
  return closing===null?prefix:null;
}
export function withGenerationMarker(source) {
  text(source,'提示');
  if(generationIntent(source)!==null)return source;
  const result=source+(source.endsWith('\n')?'':'\n')+GENERATION_MARKER;
  text(result,'提示');return result;
}

/** Convert an explicitly run marker document to generation input, atomically.
 * Existing learning drafts keep their prompt and checkpoint the typed marker.
 * This function never sends requests or executes source. */
export function prepareGenerationFromMarker(cell) {
  requireCell(cell);
  const intent=generationIntent(cell.source);
  if(intent===null)return false;
  const candidate={...cell,generation:cell.generation===undefined?undefined:validateGeneration(cell.generation)};
  if(candidate.generation){
    checkpoint(candidate);candidate.source=intent;
    candidate.generation.prompt=withGenerationMarker(candidate.generation.prompt.trim()?candidate.generation.prompt:'请根据当前源码草稿生成完整的如程序，保留已有修改。');
    candidate.generation=validateGeneration(candidate.generation);
  }else{const prompt=candidate.source;candidate.source='';ensureGeneration(candidate,prompt);}
  cell.source=candidate.source;cell.generation=candidate.generation;return true;
}
