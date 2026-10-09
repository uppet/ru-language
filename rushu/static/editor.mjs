/** Editing aids for 如 0.8. These are tolerant lexical aids, not a parser/checker.
 * The structural model mirrors emacs/ru-lang-mode.el, including anonymous
 * 算/作 headers, contextual 为/终, longest names and literal strings. */
export const KEYWORDS = new Set('显 取 为 得 完 破 若 则 另 然 循 次 环 算 作 法 其 且 或 非 空 对 形 象 如 新 外言 尽 试 救 卒'.split(' '));
const TYPES = new Set('数 句 阵 空 对 件 录 件作成果'.split(' '));
const BUILTINS = new Set('读 件 录 件作成果 读取 显出 错误 __竞赛'.split(' '));
const MEMBERS = new Set('含 位 段 增 量 囫 囵 写 行 读 开 关'.split(' '));
const PAIRS = new Map(Object.entries({'算':'法','作':'为','若':'然','循':'环','形':'象','试':'终','(' : ')','[':']'}));
const PUNCT = {'。':'.','：':':','（':'(','）':')','，':',','［':'[','］':']'};
const nameStart = c => !!c && /[_\p{L}]/u.test(c);
const namePart = c => !!c && /[_\p{L}\p{N}]/u.test(c);
// Match complete markers without splitting a Unicode name (including astral letters).
const marker = (source, p, name) => source[p] === name && /[.。]/u.test(source[p+1] || '') &&
  (p === 0 || !namePart(Array.from(source.slice(Math.max(0,p-2),p)).at(-1)));
export function lex(source) {
  const tokens = []; let p = 0;
  while (p < source.length) {
    const start = p, char = String.fromCodePoint(source.codePointAt(p)); let kind, text;
    if (/\s/u.test(char) || char === '\uFEFF') { p += char.length; continue; }
    if (char === '#' || source.startsWith('//', p) || marker(source,p,'批')) {
      p = source.indexOf('\n', p); if (p < 0) p = source.length; kind = 'comment';
    } else if (marker(source,p,'解')) {
      const close = /释[.。]/u.exec(source.slice(p+2));
      p = close ? p+2+close.index+close[0].length : source.length; kind = 'comment';
    } else if (`'"‘“`.includes(char)) {
      const close = {'‘':'’','“':'”'}[char] || char; p += char.length;
      while (p < source.length && source[p] !== close) { p += source[p] === '\\' ? Math.min(2, source.length - p) : 1; }
      if (source[p] === close) p++; kind = 'string';
    } else {
      const number = source.slice(p).match(/^(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?/);
      if (number) { p += number[0].length; kind = 'number'; }
      else if (nameStart(char)) {
        p += char.length;
        while (p < source.length) { const next = String.fromCodePoint(source.codePointAt(p)); if (!namePart(next)) break; p += next.length; }
        kind = 'name';
      } else { p += /^(==|!=|<=|>=)/.test(source.slice(p)) ? 2 : char.length; kind = 'punct'; text = PUNCT[char]; }
    }
    tokens.push({start, end:p, kind, text:text || source.slice(start,p)});
  }
  return tokens;
}
function literalHeader(tokens, index) {
  let i = index + 1;
  const next = () => { while (tokens[i]?.kind === 'comment') i++; return tokens[i++]; };
  const match = (token,text,kind='name') => token?.kind === kind && token.text === text;
  let token = next(); if (match(token,':','punct')) return true;
  while (token) {
    if (token.kind !== 'name' || KEYWORDS.has(token.text) || !match(next(),'为')) return false;
    token = next();
    if (token?.kind !== 'name' || (KEYWORDS.has(token.text) && !['空','对','算','作'].includes(token.text))) return false;
    token = next(); while (match(token,'阵')) token = next();
    if (match(token,':','punct')) return true;
    if (match(token,',','punct')) { token = next(); if (match(token,':','punct')) return true; }
  }
  return false;
}
function headerKind(tokens,index,allowIncomplete) {
  if (literalHeader(tokens,index)) return 'literal';
  const following=[]; for(let i=index+1;i<tokens.length&&following.length<3;i++) if(tokens[i].kind!=='comment') following.push(tokens[i]);
  const [name, after, third]=following;
  if ((allowIncomplete && !name) || (name?.kind==='name' && !KEYWORDS.has(name.text) &&
      ((!after && allowIncomplete) || (after?.kind==='punct' && after.text===':') ||
       (after?.kind==='name' && !KEYWORDS.has(after.text) && ((!third && allowIncomplete) || (third?.kind==='name' && third.text==='为')))))) return 'named';
  return null;
}
export function analyze(source) {
  const tokens = lex(source), stack=[], blocks=[], lines=[], nexts=[], sourceLines=source.split('\n');
  let next, previous, rescueBinding, callableName, statementStart=true, index=0;
  for (let i=tokens.length-1;i>=0;i--) { nexts[i]=next; if(tokens[i].kind!=='comment') next=tokens[i]; }
  let offset=0;
  for (const line of sourceLines) {
    const end=offset+line.length; let depth=stack.length, first=true;
    const stringLine=index>0 && ['string','comment'].includes(tokens[index-1].kind) && tokens[index-1].end>offset;
    while (tokens[index] && tokens[index].start<=end) {
      const token=tokens[index], {text,kind}=token, next=nexts[index], binding=token===rescueBinding;
      const callable=['算','作'].includes(text), callableType=callable&&previous==='为';
      const definition=callable&&!callableType ? headerKind(tokens,index,statementStart) : null;
      const top=stack.at(-1), code=kind!=='comment'&&kind!=='string';
      const closer=code&&!binding&&top&&text===PAIRS.get(top.kind)&&
        (text!=='终'||statementStart)&&
        (text!=='为'||(!top.header&&(statementStart||(first&&!['数','句','阵','算','作'].includes(next?.text)))));
      const branch=code&&top&&!binding&&((top.kind==='若'&&['则','另'].includes(text))||(top.kind==='试'&&text==='救'&&statementStart));
      if (kind!=='comment') {
        if(top?.kind==='试'&&top.header&&!binding&&!branch&&text!==':') top.header=false;
        if(first) { depth=Math.max(0,stack.length-((closer||branch)?1:0)); first=false; }
        if(binding) { rescueBinding=null; statementStart=true; }
        else if(kind==='string') statementStart=false;
        else if(closer) { top.end=token.end; top.endLine=lines.length; top.closed=true; token.close=top.kind; stack.pop(); statementStart=!top.literal&&!['(','['].includes(top.kind); }
        else if(PAIRS.has(text)&&(!callable||definition)) {
          const block={kind:text,start:token.start,end:source.length,startLine:lines.length,endLine:sourceLines.length-1,depth:stack.length,literal:definition==='literal',header:['算','作','若','试'].includes(text),closed:false};
          stack.push(block); blocks.push(block); token.open=text; statementStart=['循','试'].includes(text);
        } else if(branch||(top&&text===':'&&(['算','作','形'].includes(top.kind)||(top.kind==='试'&&top.header)))) {
          top.header=false;
          if(branch&&text==='救'&&next?.kind==='name'&&!KEYWORDS.has(next.text)) { rescueBinding=next; top.header=true; }
          statementStart=true;
        } else if(text==='.'||text==='次') statementStart=true;
        else statementStart=false;
        if(kind==='name') {
          token.face=binding?'variable':closer&&text==='终'?'keyword':token===callableName?'function':callableType?'type':callable?'keyword':
            ['@','其'].includes(previous)&&MEMBERS.has(text)?'builtin':
            ['形','如','新'].includes(previous)||(previous==='为'&&!statementStart)||TYPES.has(text)?'type':
            KEYWORDS.has(text)?'keyword':BUILTINS.has(text)?'builtin':null;
        }
        if(token===callableName) callableName=null;
        if(callable&&!callableType&&definition!=='literal'&&next?.kind==='name'&&!KEYWORDS.has(next.text)) callableName=next;
        previous=closer?null:text;
      }
      index++;
    }
    lines.push({start:offset,end,depth:stringLine?null:depth,afterDepth:stack.length}); offset=end+1;
  }
  return {tokens,blocks,lines,depth:stack.length};
}
export const ASSIGNMENT_HELP = '取（词法规则）：函数内先更新当前局部，否则更新最近已有的非模块捕获绑定；未找到则新建当前局部，不隐式改写模块变量。直接救正文中的取写救局部；闭包共享捕获绑定。参数属于本次调用局部。此提示不判断具体名称的运行时绑定。';
export function tokenHelp(token) { return token.kind === 'name' && token.text === '取' ? ASSIGNMENT_HELP : null; }
export const escapeHTML = text => text.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
export function highlight(source) {
  const {tokens}=analyze(source); let html='',at=0;
  for(const t of tokens) { html+=escapeHTML(source.slice(at,t.start)); const face=t.face||(['string','comment','number'].includes(t.kind)?t.kind:null); const text=escapeHTML(source.slice(t.start,t.end)); html+=face?`<span class="tok-${face}"${tokenHelp(t)?` data-help="${escapeHTML(tokenHelp(t))}"`:""}>${text}</span>`:text; at=t.end; }
  return html+escapeHTML(source.slice(at));
}
export function indentText(source, size=4) {
  const {lines}=analyze(source); return source.split('\n').map((line,i)=>lines[i].depth===null?line:' '.repeat(lines[i].depth*size)+line.trimStart()).join('\n');
}
export function enterEdit(source, start, end=start, size=4) {
  const before=source.slice(0,start), after=source.slice(end);
  const analysis=analyze(before+'\n'); const line=analysis.lines.at(-1);
  // Never inject whitespace into a multiline string's value.
  const last=analysis.tokens.at(-1);
  const openComment=last?.kind==='comment' && /^解[.。]/u.test(last.text) && !/释[.。]$/u.test(last.text.trimEnd());
  const indent=line.depth===null||openComment?'':' '.repeat(line.depth*size);
  return {start,end,text:'\n'+indent,selection:start+1+indent.length};
}
export function indentSelection(source,start,end,backward=false,size=4) {
  const from=source.lastIndexOf('\n',start-1)+1;
  const to=end>start&&source[end-1]==='\n'?end-1:(source.indexOf('\n',end)<0?source.length:source.indexOf('\n',end));
  const old=source.slice(from,to), lines=old.split('\n');
  const changes=lines.map(line=>backward?-(line.match(new RegExp(`^( {1,${size}}|\\t)`))?.[0].length||0):size);
  const text=lines.map((line,i)=>backward?line.slice(-changes[i]):' '.repeat(size)+line).join('\n');
  return {start:from,end:to,text,selectionStart:Math.max(from,start+changes[0]),selectionEnd:Math.max(from,end+changes.reduce((a,b)=>a+b,0))};
}
