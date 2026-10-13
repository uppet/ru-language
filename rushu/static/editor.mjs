/** Editing aids for 如 0.11.1. These are tolerant lexical aids, not a parser/checker.
 * The structural model mirrors emacs/ru-lang-mode.el, including anonymous
 * 算/作 headers, contextual 为/终, longest names and literal strings. */
export const KEYWORDS = new Set('显 取 为 得 完 破 若 则 另 然 循 次 环 算 作 法 其 且 或 非 空 对 形 象 如 新 外言 尽 试 救 卒 真 假 典 成'.split(' '));
const TYPES = new Set('数 句 阵 空 对 事实 典 件 录 件作成果'.split(' '));
const BUILTINS = new Set('读 件 录 件作成果 读取 显出 错误 __如竞 __如观'.split(' '));
const MEMBERS = new Set('含 位 段 增 删 弹 排序 另成 逐位 逐目 量 囫 囵 写 行 读 开 关 查 除 列'.split(' '));
const PAIRS = new Map(Object.entries({'算':'法','作':'为','若':'然','循':'环','形':'象','试':'终','典':'成','段':'落','(' : ')','[':']','{':'}'}));
const PUNCT = {'。':'.','：':':','（':'(','）':')','，':',','［':'[','］':']','｛':'{','｝':'}'};
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
      } else if (/^[:：]=/.test(source.slice(p))) { p += 2; kind = 'punct'; text = ':='; }
      else { p += /^(==|!=|<=|>=)/.test(source.slice(p)) ? 2 : char.length; kind = 'punct'; text = PUNCT[char]; }
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
    if (token.kind !== 'name' || KEYWORDS.has(token.text)) return false;
    token = next();
    if (match(token,'为')) {
      token = next();
      if (token?.kind !== 'name' || (KEYWORDS.has(token.text) && !['空','对','典','算','作'].includes(token.text))) return false;
      token = next(); while (match(token,'阵')) token = next();
    }
    if (match(token,':','punct')) return true;
    if (match(token,',','punct')) { token = next(); if (match(token,':','punct')) return true; }
  }
  return false;
}
function referenceCallAhead(tokens,index) {
  const code=[]; let cursor=index+1;
  for(;cursor<tokens.length&&code.length<4;cursor++) if(tokens[cursor].kind!=='comment') code.push(tokens[cursor]);
  const [name,param,colon,value]=code;
  const bare=token=>token?.kind==='name'&&!KEYWORDS.has(token.text);
  if (!bare(name)||!bare(param)||colon?.text!==':'||!value) return false;
  const startsValue=['number','string'].includes(value.kind)||bare(value)||
    ['真','假','典','空','新','外言','其','非','(','[','{','+','-'].includes(value.text);
  if (!startsValue) return false;
  // Stop at this body's closer, ignoring closers owned by nested definitions.
  // In particular a later independent definition cannot close a reference call.
  const ends=[tokens[index].text==='算'?'法':'为']; let dot=false, previous=':';
  for(let i=cursor-1;i<tokens.length;i++) {
    const token=tokens[i]; if(['comment','string'].includes(token.kind)) continue;
    if(['算','作'].includes(token.text)&&previous!=='为'&&literalHeader(tokens,i)) {
      ends.push(token.text==='算'?'法':'为');
      while(tokens[i]?.text!==':') i++;
    } else if(token.text===ends.at(-1)) {
      let j=i+1; while(tokens[j]?.kind==='comment') j++;
      if(token.text!=='为'||['.',':'].includes(previous)||!tokens[j]||tokens[j].kind!=='name'||tokens[j].text==='.') {
        ends.pop(); if(!ends.length) return false;
      }
    } else if(token.kind==='punct'&&token.text==='.') dot=true;
    previous=token.text;
  }
  return dot;
}
function headerKind(tokens,index,allowIncomplete) {
  if (referenceCallAhead(tokens,index)) return null;
  const following=[]; for(let i=index+1;i<tokens.length&&following.length<3;i++) if(tokens[i].kind!=='comment') following.push(tokens[i]);
  const [name, after, third]=following;
  if (literalHeader(tokens,index)) {
    // At statement boundaries a bare first name belongs to the declaration.
    // Expression headers have no definition name, even with untyped parameters.
    return allowIncomplete && name?.kind==='name' && after?.text!=='为' && after?.text!==',' ? 'named' : 'literal';
  }
  if ((allowIncomplete && !name) || (name?.kind==='name' && !KEYWORDS.has(name.text) &&
      ((!after && allowIncomplete) || (after?.kind==='punct' && after.text===':') ||
       (after?.kind==='name' && !KEYWORDS.has(after.text) && (allowIncomplete || (third?.kind==='name' && third.text==='为')))))) return 'named';
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
      const scoped=!binding&&statementStart&&(text==='{'||(text==='段'&&next?.kind==='punct'&&next.text===':'));
      const closer=code&&!binding&&top&&text===PAIRS.get(top.kind)&&
        (text!=='终'||statementStart)&&
        (text!=='落'||(statementStart&&next?.kind==='punct'&&next.text==='.'))&&
        (text!=='为'||(!top.header&&(statementStart||(first&&![...TYPES,'算','作'].includes(next?.text)))));
      const branch=code&&top&&!binding&&((top.kind==='若'&&['则','另'].includes(text))||(top.kind==='试'&&text==='救'&&statementStart));
      if (kind!=='comment') {
        if(top?.kind==='试'&&top.header&&!binding&&!branch&&text!==':') top.header=false;
        if(first) { depth=Math.max(0,stack.length-((closer||branch)?1:0)); first=false; }
        if(binding) { rescueBinding=null; statementStart=true; }
        else if(kind==='string') statementStart=false;
        else if(closer) { top.end=token.end; top.endLine=lines.length; top.closed=true; token.close=top.kind; stack.pop(); statementStart=top.scoped||(!top.literal&&!['(','[','{','典'].includes(top.kind)); }
        else if(PAIRS.has(text)&&(!callable||definition)&&(text!=='段'||scoped)&&(text!=='典'||(previous!=='为'&&next?.kind==='punct'&&next.text===':'))) {
          const block={kind:text,start:token.start,end:source.length,startLine:lines.length,endLine:sourceLines.length-1,depth:stack.length,literal:definition==='literal'||text==='典'||(text==='{'&&!scoped),scoped,header:['算','作','形','若','试','典','段'].includes(text),closed:false};
          stack.push(block); blocks.push(block); token.open=text; statementStart=scoped&&text==='{'||['循','试'].includes(text);
        } else if(branch||(top&&top.header&&text===':'&&['算','作','形','典','段','试'].includes(top.kind))) {
          top.header=false;
          if(branch&&text==='救'&&next?.kind==='name'&&!KEYWORDS.has(next.text)) { rescueBinding=next; top.header=true; }
          statementStart=top.kind!=='典';
        } else if(text==='.'||text==='次') statementStart=top?.kind!=='典';
        else statementStart=false;
        if(kind==='name') {
          token.face=(token.open==='段'||(closer&&text==='落'))?'keyword':text==='对'&&top?.kind==='典'?'keyword':text==='典'&&token.open?'keyword':binding?'variable':closer&&text==='终'?'keyword':token===callableName?'function':callableType?'type':callable?'keyword':
            ['@','其'].includes(previous)&&MEMBERS.has(text)?'builtin':
            ['形','如','新'].includes(previous)||(previous==='为'&&!statementStart)||TYPES.has(text)?'type':
            KEYWORDS.has(text)?'keyword':BUILTINS.has(text)?'builtin':null;
        }
        if(kind==='punct'&&text===':=') token.face='keyword';
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
export const ASSIGNMENT_HELP = '取（词法规则）：函数内先更新当前局部，否则更新最近已有的非模块捕获绑定；未找到则新建当前局部，不隐式改写模块变量。直接救正文中的取写救局部；直接段／花括号作用域块中的取写块局部（含其中的若、循、试正文）；闭包共享捕获绑定，可更新捕获的块局部。:= 与取完全等价。参数属于本次调用局部。此提示不判断具体名称的运行时绑定。';
export const TOKEN_HELP = {
  '取': ASSIGNMENT_HELP, ':=': ASSIGNMENT_HELP,
  '典': '典：键值映射。字面量 {目: 相, 目: 相}，表达式位置的空典 {}；语句位置的 {} 是作用域块。也可写 典: 目 对 相. 成。支持全角｛｝和尾逗号。',
  '成': '成：结束典字面量；外层语句的句点另写。',
  '对': '对：二元素对；在典字面量中分隔目与相。',
  '事实': '事实：真或假，与数不同。比较和非／且／或返回事实。为 事实 转换时仅空、假为假。',
  '真': '真：事实字面量。', '假': '假：事实字面量。'
};
const PRACTICAL_MEMBER_HELP = {
  '逐位': '内置阵：逐位 回调:二参算或作，按初始浅快照从0开始传入位、值；忽略返回值（含假/空），整体空。空阵也验证回调，完只结束当前作。用户同名方法按其声明。',
  '逐目': '内置典：逐目 回调:二参算或作，按初始无序浅条目快照传入目、相；忽略返回值，整体空。空典也验证回调。旧典列已移除，请改用逐目；目录列不变。用户同名方法按其声明。',

  '排序': '内置阵：排序，可选先于:二参算，返回新浅复制阵并稳定排序。默认全为有限数升序、句按Unicode码点、或同一形身份的单参算先于（可继承）；返回须为事实，无须同，不改比较运算符。显式先于覆盖默认规则；空/单项也返回新阵并验证参数。旧如:竞排序仍用三路数值比较器。用户同名方法按其声明。',
  '另成': '内置阵：另成 算法:一参算，先取浅快照，从左到右对每个元素调用一次，返回新阵；保留空，不筛选或展开，不接受作，空阵也验证算及参数个数。元素仍共享引用，欲复制对象须在算法中显式新。用户同名方法按其声明。',

  '删': '内置阵：删 位，原地删除合法位置并返回原元素；越界报错。用户同名方法按其声明。',
  '弹': '内置阵：弹，裸成员零参调用，移出最后项并返回原元素；空阵报错。用户同名方法按其声明。',
  '增': '内置阵：增 值:，追加元素。典：增 目: 相:，新增或覆盖条目。用户同名方法按其声明。',
  '除': '典：除 目:，删除条目，返回是否删除的事实。用户同名方法按其声明。',
  '查': '内置阵：查 值，按相等协议从初始浅快照返回首个位置，未找到为空。典：查 目:，按目返回相。用户同名方法按其声明。'
};
export function tokenHelp(token) {
  if(token.face==='builtin' && PRACTICAL_MEMBER_HELP[token.text]) return PRACTICAL_MEMBER_HELP[token.text];
  if(token.open==='段'||token.close==='段') return '段: … 落.：独立词法作用域，与语句位置的 { … } 等价。每次进入创建新局部环境，落后必须有句点。';
  return token.kind === 'name'||token.text===':=' ? TOKEN_HELP[token.text] || null : null;
}
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

// Reindent a typed closer, including braces directly followed by commas or dots.
export const needsAutoDedent = line => /^\s*(?:(?:法|为|然|环|象|终|成|另|则|救)(?:\s|[。.：:]|$)|落\s*[。.]|[}｝])/.test(line);
