/** Editing aids for 如 0.20.0. These are tolerant lexical aids, not a parser/checker.
 * The structural model mirrors emacs/ru-lang-mode.el, including anonymous
 * 算/作 headers, contextual 为/终, longest names and literal strings. */
export const KEYWORDS = new Set('显 取 为 得 完 破 若 则 另 然 循 次 环 算 作 法 其 且 或 非 空 对 形 象 如 新 外言 尽取 尽 试 救 卒 真 假 典 成'.split(' '));
const TYPES = new Set('数 句 阵 空 对 事实 典 件 录 件作成果'.split(' '));
const BUILTINS = new Set('读 件 录 件作成果 读取 显出 错误 __如竞 __如观'.split(' '));
const MEMBERS = new Set('含 位 段 增 删 弹 排序 另成 逐位 逐目 量 囫 囵 写 行 读 开 关 查 除 列 三角形 多边形 平移 旋转 缩放 保存 恢复 变换 重置变换 裁剪 取消裁剪 颜色 文字对齐 经过秒 间隔秒 弧 扇形 折线 贝塞尔 缓存 贴图'.split(' '));
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
function moduleTokens(tokens, index, declaration=false) {
  const code=tokens.slice(index).filter(t=>t.kind!=='comment');
  if(declaration && code[1]?.text!=='言') return null;
  const marked=declaration?[code[0],code[1]]:[];
  let i=declaration?2:1;
  while(true) {
    const token=code[i];
    if(token?.kind!=='name'||KEYWORDS.has(token.text)) return null;
    marked.push(token); i++;
    if(code[i]?.kind==='name'&&code[i].text==='其') { i++; continue; }
    if(declaration && (code[i]?.kind!=='punct'||code[i].text!=='.')) return null;
    return marked;
  }
}
export function analyze(source) {
  const tokens = lex(source), stack=[], blocks=[], lines=[], nexts=[], sourceLines=source.split('\n');
  let next, previous, rescueBinding, callableName, statementStart=true, index=0;
  const moduleFaces=new Map();
  for (let i=tokens.length-1;i>=0;i--) { nexts[i]=next; if(tokens[i].kind!=='comment') next=tokens[i]; }
  let offset=0;
  for (const line of sourceLines) {
    const end=offset+line.length; let depth=stack.length, first=true;
    const stringLine=index>0 && ['string','comment'].includes(tokens[index-1].kind) && tokens[index-1].end>offset;
    while (tokens[index] && tokens[index].start<=end) {
      const token=tokens[index], {text,kind}=token, next=nexts[index], binding=token===rescueBinding;
      if(kind==='name' && ((statementStart&&text==='吾')||text==='外言')) {
        const declaration=text==='吾', marked=moduleTokens(tokens,index,declaration);
        marked?.forEach((value,i)=>moduleFaces.set(value,declaration&&i<2?'keyword':'type'));
      }
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
        if(moduleFaces.has(token)) token.face=moduleFaces.get(token);
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
  '吾': '吾 言 工程 其 力学.：可选顶层一次模块声明。吾、言仍是普通名称，只在完整声明中识别。名称按包的正式根校验。',
  '言': '与吾组成完整模块声明：吾 言 工程 其 力学.；其他位置仍为普通名称。',
  '外言': '外言既接受原有字符串路径，也接受静态模块名：外言 工程 其 力学。整个其链属于模块名，不读取变量。包由集录.ru声明；缺远程依赖时显式 ru deps sync，运行和检查不联网。browser-js仍只允许固定标准库，不读取本机包。',
  '尽取': "尽取：模块顶层全量导入。写作 尽取 外言 '如:数学'.，尽取须连写，不能替换成 :=。旧 尽 取 已停用并给出迁移提示；单字尽继续保留。保留原有静态解析、导出和名称冲突规则，长名称尽取值不拆分。此提示不检查此处语义。",
  '尽': "旧语法 尽 取 外言 已停用；请改用 尽取 外言 '文件.ru'.，尽取须连写。单字尽继续保留用于迁移诊断，没有兼容别名。",
  '取': ASSIGNMENT_HELP, ':=': ASSIGNMENT_HELP,
  '典': '典：键值映射。字面量 {目: 相, 目: 相}，表达式位置的空典 {}；语句位置的 {} 是作用域块。也可写 典: 目 对 相. 成。支持全角｛｝和尾逗号。',
  '成': '成：结束典字面量；外层语句的句点另写。',
  '对': '对：二元素对；在典字面量中分隔目与相。',
  '事实': '事实：真或假，与数不同。比较和非／且／或返回事实。为 事实 转换时仅空、假为假。',
  '真': '真：事实字面量。', '假': '假：事实字面量。'
};
const PRACTICAL_MEMBER_HELP = {
  '缓存': '如:观画布：缓存 宽 高 绘制，三个参数全必需，只在初始化调用。绘制是恰好接收一个临时目标的算／作，返回不可变图像，图像只读宽／高。透明独立默认状态，录制后目标失效；禁止嵌套、事件中创建及录制期间改主画布。最多 8 张、合计 4M 像素／128 KiB 定义、每张 2047 命令。不是图片加载、导出或可变画层。用户同名方法按其声明。',
  '贴图': '如:观画布：贴图 图像 横 纵，三个参数全必需，返回空；本画布有效图像按原尺寸绘制，受变换和裁剪影响，不重着色。透明度 source-over，放大为位图平滑缩放。每帧根命令加唯一引用配方合计 2048；关闭或新画布使旧图像失效。每帧仍传完整定义，不承诺60fps。用户同名方法按其声明。',
  '贝塞尔': '如:观画布：贝塞尔 起横 起纵 控一横 控一纵 控二横 控二纵 终横 终纵，八参全必需，支持全位置或全命名调用，返回空。单段三次曲线经过起终点，控制点不必经过；坐标为有限数且绝对值不超过 100000，拒绝事实与空。原生一次 moveTo 加 bezierCurveTo，只描边一次，不闭合、不填充，忽略且保留填色。坐标与矩阵、裁剪、透明描边、线宽深复制；重合或共线沿用原生退化行为，空描边或退化仍计入原有预算。不是二次贝塞尔或通用路径构造器。用户同名方法按其声明。',
  '折线': '如:观画布：折线 点阵，唯一参数必需，支持位置或点阵:调用，返回空。2～256 个二维阵点，坐标为有限数且绝对值不超过 100000，拒绝事实与空。开放路径只描边一次，不闭合、不填充，忽略且保留填色，半透明折点不逐段叠色。顶点与变换、裁剪、描边、线宽深复制；重复或全重合点合法，空描边或零长度仍计入原有预算。封闭填充用多边形。用户同名方法按其声明。',
  '弧': '如:观画布：弧 横 纵 宽 高 始角 转角，六个参数均必需，支持全位置或全命名，返回空。外接框同椭圆；始角与带符号转角为弧度，局部正向顺时针，负缩放镜像。只描边，忽略填色；零转角无像素但保留命令，绝对转角至少 2π 只画一整圈。有限数绝对值不超过 100000，宽高非负且可为零；非圆椭圆使用参数角。用户同名方法按其声明。',
  '扇形': '如:观画布：扇形 横 纵 宽 高 始角 转角，六个参数均必需，支持全位置或全命名，返回空。外接框同椭圆；始角与带符号转角为弧度，局部正向顺时针，负缩放镜像。填充并描边，部分扇形含两条半径边；零转角无像素但保留命令，绝对转角至少 2π 为无中心辐条的整椭圆。有限数绝对值不超过 100000，宽高非负且可为零；非圆椭圆使用参数角。用户同名方法按其声明。',
  '经过秒': '如:观画布：经过秒，零参数只读数值，创建时为 0；从创建画布起的宿主单调经过秒，包含暂停和隐藏页间隔。同次回调内冻结，反复读取不会推进；不是日期或墙钟。用户同名方法按其声明。',
  '间隔秒': '如:观画布：间隔秒，零参数只读数值。帧回调中是距上一实际帧开始的秒差；首帧及暂停恢复首帧为 0，输入回调为 0。隐藏间隔不截断，不补帧；物理积分可自行限制步长。同次回调内冻结，每帧仍只收帧序号。用户同名方法按其声明。',
  '文字对齐': '如:观画布：文字对齐 横向 纵向，两项句参数均必需；横向为左／中／右，纵向为上／中／下／基线，默认左上。设置跨回调保留并纳入保存／恢复；中部依据字体 em 方框，不是笔画包围盒或宽度测量。用户同名方法按其声明。',
  '颜色': '如:观：颜色 红 绿 蓝 不透明度，四个参数均为必需的 0～255 有限整数；支持全位置或全命名实参。返回小写 #rrggbbaa，0 全透明、255 不透明；不钳位、不舍入。用户同名方法按其声明。',
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
