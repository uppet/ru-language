import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {lex,analyze,highlight,indentText,enterEdit,indentSelection,needsAutoDedent} from '../static/editor.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');

test('longest Unicode names; reserved word substrings are ordinary names',()=>{
  const result=analyze('为乐 取 1. 算法 取 2. 循环 取 3. 终点 取 4. 读者 取 5.');
  assert.equal(result.depth,0);assert.equal(result.blocks.length,0);
  for(const word of ['为乐','算法','循环','终点','读者'])assert.equal(result.tokens.find(t=>t.text===word).face,null);
});
test('four matching string pairs, escaping and comments hide keywords',()=>{
  const source=`显 '作 为'. 显 "算 法". 显 ‘若 \\’ 然’. 显 “试 \\” 终”. # 循 环\n// 形 象\n显 '多行\n作:\n为'.`;
  assert.equal(analyze(source).blocks.length,0);assert.equal(lex(source).filter(t=>t.kind==='string').length,5);
});
test('numbers obey decimal/exponent boundaries and statement dots',()=>{
  assert.deepEqual(lex('1. .5 3.25 2e-3 1E+2').map(t=>[t.kind,t.text]),[['number','1'],['punct','.'],['number','.5'],['number','3.25'],['number','2e-3'],['number','1E+2']]);
});
test('named functions, conversion 为, procedure closers and type annotations',()=>{
  const input='算 平方 根 为 数：\n得 根*根.\n法\n作 展示 值 为 句:\n为乐 取 值 为 阵.\n显 值 为 句.\n为 .\n显 1.';
  const expected='算 平方 根 为 数：\n    得 根*根.\n法\n作 展示 值 为 句:\n    为乐 取 值 为 阵.\n    显 值 为 句.\n为 .\n显 1.';
  assert.equal(indentText(input),expected);assert.equal(analyze(input).depth,0);
});
test('anonymous callable headers, types and references are distinguished',()=>{
  const source='外 取 算 值 为 数:\n内 取 作 文 为 句:\n显 文.\n为.\n得 值.\n法.\n引用 取 算 平方.\n转换 取 算 平方 为 句.\n作 应用 回调 为 算:\n显 回调().\n为';
  const result=analyze(source);assert.equal(result.depth,0);assert.equal(result.blocks.filter(b=>['算','作'].includes(b.kind)).length,3);
  assert.deepEqual(result.blocks.filter(b=>['算','作'].includes(b.kind)).map(b=>[b.kind,b.literal]),[['算',true],['作',true],['作',false]]);
  assert.equal(indentText(source),'外 取 算 值 为 数:\n    内 取 作 文 为 句:\n        显 文.\n    为.\n    得 值.\n法.\n引用 取 算 平方.\n转换 取 算 平方 为 句.\n作 应用 回调 为 算:\n    显 回调().\n为');
});
test('zero-argument anonymous callable, nested brackets and fullwidth punctuation',()=>{
  const source='列表 取 ［算：\n得 1.\n法，作：\n显 2.\n为］。';
  assert.equal(analyze(source).depth,0);assert.equal(analyze(source).blocks.length,3);
  assert.equal(indentText(source),'列表 取 ［算：\n        得 1.\n    法，作：\n        显 2.\n    为］。');
});
test('conditional, loops and recovery branches align with their blocks',()=>{
  const input='循 3 次\n若 1 则\n试\n卒 “失败”.\n救 原因\n显 原因.\n终.\n另\n破.\n然\n环';
  const depths=analyze(input).lines.map(l=>l.depth);assert.deepEqual(depths,[0,1,2,3,2,3,2,1,2,1,0]);
  assert.equal(analyze(input).depth,0);
});
test('终 in expressions, named arguments, rescue binding and top-level name remains a name',()=>{
  const source='终 取 2.\n试\n显 文 其 段 始:0\n终:终.\n显\n终.\n救 终\n显 终.\n终.';
  const result=analyze(source);assert.equal(result.depth,0);
  const ends=result.tokens.filter(t=>t.text==='终');assert.equal(ends.filter(t=>t.close==='试').length,1);
});
test('continued conversions do not accidentally close procedure',()=>{
  assert.equal(indentText('作 展示:\n值 取 "1"\n为 数.\n显 值.\n为'),'作 展示:\n    值 取 "1"\n    为 数.\n    显 值.\n为');
});
test('multiline strings retain all whitespace and string contents',()=>{
  const source='作 展示:\n显 “法\n  保持 缩进\n为” .\n显 "好".\n为';
  const indented=indentText(source);assert.equal(indented,'作 展示:\n    显 “法\n  保持 缩进\n为” .\n    显 "好".\n为');
  assert.deepEqual(lex(indented).filter(t=>t.kind==='string').map(t=>t.text),lex(source).filter(t=>t.kind==='string').map(t=>t.text));
});
test('highlight escapes HTML, code payloads and unsafe quotes',()=>{
  const rendered=highlight('显 "<script>alert(1)</script>&". # <img src=x onerror=x>');
  assert.ok(!rendered.includes('<script>'));assert.ok(!rendered.includes('<img'));assert.ok(rendered.includes('&lt;script&gt;'));assert.ok(rendered.includes('&amp;'));assert.ok(rendered.includes('tok-string'));
});
test('Enter respects anonymous blocks, comments and multiline strings',()=>{
  const source='平方 取 算 数值 为 数:';assert.equal(enterEdit(source,source.length).text,'\n    ');
  const quoted="显 '保持";assert.equal(enterEdit(quoted,quoted.length).text,'\n');
  const commented='# 作:';assert.equal(enterEdit(commented,commented.length).text,'\n');
});
test('selection indent and dedent preserve selection extents',()=>{
  assert.deepEqual(indentSelection('a\nb',0,3),{start:0,end:3,text:'    a\n    b',selectionStart:4,selectionEnd:11});
  assert.equal(indentSelection('    a\n  b',0,9,true).text,'a\nb');
});
test('all shipped examples analyze without unmatched structures; prefixes never throw',()=>{
  const files=fs.readdirSync(path.join(root,'examples')).filter(name=>name.endsWith('.ru'));
  for(const file of files){const source=fs.readFileSync(path.join(root,'examples',file),'utf8');assert.equal(analyze(source).depth,0,file);assert.equal(indentText(indentText(source)),indentText(source),file);}
  const sample=fs.readFileSync(path.join(root,'examples','anonymous.ru'),'utf8');
  for(let n=0;n<=sample.length;n++)assert.doesNotThrow(()=>analyze(sample.slice(0,n)));
});
test('large repeated blocks remain bounded and structurally balanced',()=>{
  const source='作 名:\n显 1.\n为\n'.repeat(4000),result=analyze(source);
  assert.equal(result.depth,0);assert.equal(result.blocks.length,4000);
});

test('Chinese comments are adjacent whole markers, opaque and nonnested',()=>{
  const source='批. 算 假:\r\n批评 取 1. 解释 取 2. 总批 取 3.\n解。 "\n解. 若 1 则 foo释.\n显 "批. 解。 释.". 批。 inline\n';
  const result=analyze(source);
  assert.equal(result.depth,0);assert.equal(result.blocks.length,0);
  assert.equal(result.tokens.filter(t=>t.kind==='comment').length,3);
  for(const word of ['批评','解释','总批'])assert.equal(result.tokens.find(t=>t.text===word).kind,'name');
  assert.deepEqual(lex('批 . 解 。 1批. 𐐀批.').map(t=>t.kind),['name','punct','name','punct','number','name','punct','name','punct']);
  assert.ok(highlight(source).includes('tok-comment'));
  assert.equal(lex('解. no close')[0].kind,'comment');
  assert.equal(lex('解. "释.显')[1].text,'显');
});
test('block comment interiors preserve whitespace and do not change indentation',()=>{
  const source='作 名:\n解. 若\n  原样\n释.\n显 1. 批. 为\n为';
  assert.equal(indentText(source),'作 名:\n    解. 若\n  原样\n释.\n    显 1. 批. 为\n为');
  assert.equal(analyze(source).blocks.length,1);
  const unfinished='作 名:\n解. 为';
  assert.equal(enterEdit(unfinished,unfinished.length).text,'\n');
});
test('assignment hover is conservative and never annotates literals or name substrings',()=>{
  const html=highlight('甲 取 1. 获取 取 "取". 批. 取\n解. 取 释.');
  assert.equal((html.match(/data-help=/g)||[]).length,2);
  assert.ok(html.includes('不隐式改写模块变量'));
  assert.ok(html.includes('直接救正文'));
  assert.ok(html.includes('不判断具体名称'));
});

test('procedure finish is a keyword statement, never a block closer',()=>{
  const source='作 提前:\n若 1 则\n完。\n然\n完.\n完成 取 1.\n为';
  const result=analyze(source);
  assert.equal(result.depth,0);
  assert.deepEqual(result.blocks.map(b=>b.kind),['作','若']);
  assert.equal(result.tokens.filter(t=>t.text==='完').length,2);
  for(const token of result.tokens.filter(t=>t.text==='完'))assert.equal(token.face,'keyword');
  assert.equal(result.tokens.find(t=>t.text==='完成').face,null);
  assert.equal(indentText(source),'作 提前:\n    若 1 则\n        完。\n    然\n    完.\n    完成 取 1.\n为');
  const prefix='作 提前:\n    完.';
  assert.equal(enterEdit(prefix,prefix.length).text,'\n    ');
  assert.equal(analyze('作 提前:\n完.').depth,1);
  assert.equal(analyze('作 提前:\n完.').blocks[0].closed,false);
});
test('finish in strings and comments stays nonstructural',()=>{
  const source='作 提前:\n显 "完。". # 完.\n批. 完。\n解. 完. 释.\n完.\n为';
  const result=analyze(source);
  assert.equal(result.depth,0);assert.equal(result.blocks.length,1);
  assert.equal(result.tokens.filter(t=>t.text==='完'&&t.face==='keyword').length,1);
});

test('optional annotations preserve named declarations, literal parameters and references',()=>{
  const source='算 保留 值, 次数 为 数, 后:\n得 值.\n法\n副本 取 算 值，次数 为 数 后：\n得 值.\n法。\n作 输出 值:\n回 取 作 参数:\n显 参数.\n为.\n为\n引用 取 算 保留.\n转换 取 算 保留 为 句.';
  const result=analyze(source);
  assert.equal(result.depth,0);
  assert.deepEqual(result.blocks.map(b=>[b.kind,b.literal,b.closed]),[['算',false,true],['算',true,true],['作',false,true],['作',true,true]]);
  assert.equal(result.tokens.find(t=>t.text==='保留').face,'function');
  for(const token of result.tokens.filter(t=>['值','次数','后','参数'].includes(t.text))) assert.equal(token.face,null);
  assert.equal(indentText(indentText(source)),indentText(source));
  assert.ok(indentText(source).includes('    回 取 作 参数:\n        显 参数.\n    为.'));
  for(let i=0;i<=source.length;i++) assert.doesNotThrow(()=>analyze(source.slice(0,i)));
});
test('optional anonymous headers accept comments, mixed types and fullwidth separators',()=>{
  const source='列表 取 ［算 # 参数\n左，右 为 数，后：\n得 左.\n法，作 值：\n完.\n为］。\n算 参数 为 数: 得 参数. 法.';
  const result=analyze(source);
  assert.equal(result.depth,0);
  assert.equal(result.blocks.filter(b=>b.literal).length,3);
  assert.equal(indentText(source), '列表 取 ［算 # 参数\n        左，右 为 数，后：\n        得 左.\n    法，作 值：\n        完.\n    为］。\n算 参数 为 数: 得 参数. 法.');
  const incomplete='算 名 左 右'; assert.equal(enterEdit(incomplete,incomplete.length).text,'\n    ');
  const prefix='回 取 算 值:'; assert.equal(enterEdit(prefix,prefix.length).text,'\n    ');
  const html=highlight('回 取 算 值: 得 值. 法.');
  assert.equal((html.match(/data-help=/g)||[]).length,1);
});

test('reference calls with named arguments do not leave open optional headers',()=>{
  for(const source of ['算 回 值:1.','显 算 回 值:1.','引用 取 作 回 值:空.']) {
    assert.equal(analyze(source).depth,0);
    assert.equal(analyze(source).blocks.length,0);
    assert.equal(enterEdit(source,source.length).text,'\n');
  }
  const prefix='回 取 算 值:'; assert.equal(analyze(prefix).depth,1);
  assert.equal(analyze('回 取 算 回 值: 1. 法.').blocks[0].literal,true);
});

test('later independent definitions do not close reference named calls',()=>{
  const source='算 回 值:1.\n算 其他 参数: 得 参数. 法\n显 算 回 值:1.\n作 输出 值: 显 值. 为';
  assert.equal(analyze(source).depth,0);
  assert.deepEqual(analyze(source).blocks.map(b=>[b.kind,b.literal]),[['算',false],['作',false]]);
  assert.equal(indentText(source),source);
  const many='算 返回 值: 值. 法\n'.repeat(4000);
  assert.equal(analyze(many).blocks.length,4000);
  assert.equal(analyze(many).depth,0);
});

test('facts, map types, reserved closers and longest names',()=>{
  const result=analyze('值 为 事实 取 真. 空表 为 典 取 典: 成. 假设 取 假. 成果 取 1. 典籍 取 2.');
  assert.equal(result.depth,0);
  assert.deepEqual(result.blocks.map(b=>b.kind),['典']);
  for(const word of ['真','假','成'])assert.equal(result.tokens.find(t=>t.text===word).face,'keyword');
  assert.equal(result.tokens.find(t=>t.text==='事实').face,'type');
  assert.deepEqual(result.tokens.filter(t=>t.text==='典').map(t=>t.face),['type','keyword']);
  for(const word of ['假设','成果','典籍'])assert.equal(result.tokens.find(t=>t.text===word).face,null);
});
test('map nesting, callable values, fullwidth and annotation boundaries',()=>{
  const source="资料 取 典：\n'设置' 对 典：\n'就绪' 对 真。\n成。\n'回调' 对 算 值 为 事实：\n得 值。\n法。\n成。\n作 展示 数据 为 典：\n显 数据。\n为";
  assert.equal(indentText(source),"资料 取 典：\n    '设置' 对 典：\n        '就绪' 对 真。\n    成。\n    '回调' 对 算 值 为 事实：\n        得 值。\n    法。\n成。\n作 展示 数据 为 典：\n    显 数据。\n为");
  const result=analyze(source);assert.equal(result.depth,0);assert.ok(result.blocks.every(b=>b.closed));
  assert.deepEqual(result.blocks.map(b=>[b.kind,b.literal]),[['典',true],['典',true],['算',true],['作',false]]);
  assert.equal(enterEdit('资料 取 典：',8).text,'\n    ');
});
test('maps in references, strings, comments, conversions and every prefix',()=>{
  assert.equal(analyze('算 回 值:真. 算 回 值:假. 算 回 值:典: 成.').blocks.filter(b=>b.kind==='算').length,0);
  assert.equal(analyze("显 '典: 成 真'. 批. 典: 成\n解。 典： 成 释。\n作 展示:\n显 值\n为 事实.\n显 值\n为 典.\n为").depth,0);
  const source="空表 为 典.\n表 取 典: '回' 对 算 参数 为 典: 得 参数. 法. 成.\n";
  for(let end=0;end<=source.length;end++){
    const prefix=source.slice(0,end),formatted=indentText(prefix);
    assert.equal(indentText(formatted),formatted);highlight(prefix);enterEdit(prefix,prefix.length);
  }
});
test('map and fact hover help is escaped and literal-safe',()=>{
  const html=highlight('显 真. 显 假. 值 为 事实. 表 取 典: 1 对 2. 成.');
  assert.ok(html.includes('事实字面量'));assert.ok(html.includes('键值映射'));
  assert.ok(!highlight("显 '事实 典 成'. # 真 假").includes('data-help'));
});


test('symbolic maps normalize braces and preserve offsets and literal contents',()=>{
  const source='表 取 ｛“｛}”:真，\n"空":{}，｝';
  const result=analyze(source);
  assert.deepEqual(result.tokens.filter(t=>t.kind==='punct').map(t=>t.text),['{',':',',',':','{','}',',','}']);
  assert.equal(result.depth,0);
  assert.deepEqual(result.blocks.map(b=>[b.kind,b.literal,b.closed]),[['{',true,true],['{',true,true]]);
  assert.equal(source.slice(result.blocks[0].start,result.blocks[0].end),source.slice(4));
  assert.ok(highlight(source).includes('tok-keyword'));
  assert.ok(highlight(source).includes('“｛}”'));
  assert.equal(analyze('显 "{成}". # ｛\n解. } 释.').blocks.length,0);
});
test('symbolic and Chinese maps nest with arrays and anonymous callbacks',()=>{
  const source="表 取 {\n'子': 典:\n'阵' 对 [｛｝, {}].\n成,\n'回': 算 值:\n得 {'值': 值}.\n法,\n}.";
  assert.equal(indentText(source),"表 取 {\n    '子': 典:\n        '阵' 对 [｛｝, {}].\n    成,\n    '回': 算 值:\n        得 {'值': 值}.\n    法,\n}.");
  const result=analyze(source);
  assert.equal(result.depth,0);assert.ok(result.blocks.every(b=>b.closed));
  assert.equal(result.blocks.find(b=>b.kind==='算').literal,true);
  assert.equal(result.tokens.find(t=>t.text==='值').face,null);
});
test('map Enter and typed closing braces use expression indentation',()=>{
  for(const opening of ['表 取 {','表 取 ｛'])assert.equal(enterEdit(opening,opening.length).text,'\n    ');
  for(const line of ['    },','    ｝。','    }','    成.'])assert.equal(needsAutoDedent(line),true);
  for(const line of ['    成果','    "}"','    # }'])assert.equal(needsAutoDedent(line),false);
  assert.deepEqual(analyze('作 展示:\n表 取 {\n1:\n2 +\n3,\n}.\n显 表.\n为').lines.map(l=>l.depth),[0,1,2,2,2,1,1,0]);
});
test('map-valued named reference calls remain calls and incomplete maps stay tolerant',()=>{
  for(const source of ['算 回 值:{}.','显 算 回 值:｛1：真｝.','引用 取 作 回 值:{1:2,}.']) {
    const result=analyze(source);assert.equal(result.depth,0);
    assert.deepEqual(result.blocks.map(b=>b.kind),['{']);
  }
  const source="表 为 典 取 {\n'回': 算 值: 得 ｛'值': 值｝. 法,\n'子': 典: 1 对 {}. 成,\n}.";
  for(let end=0;end<=source.length;end++){
    const prefix=source.slice(0,end),formatted=indentText(prefix);
    assert.equal(indentText(formatted),formatted);highlight(prefix);enterEdit(prefix,prefix.length);
  }
});

test('scoped keyword and statement brace blocks nest and preserve map expressions',()=>{
  const source="段：\n落 取 2.\n｛\n表 := {'值': 落}.\n显 表.\n｝\n落。\n显 {}.\n({}).\n{}";
  const result=analyze(source);
  assert.equal(result.depth,0);
  assert.deepEqual(result.blocks.map(b=>[b.kind,b.scoped,b.literal,b.closed]),[
    ['段',true,false,true],['{',true,false,true],['{',false,true,true],
    ['{',false,true,true],['(',false,false,true],['{',false,true,true],['{',true,false,true]
  ]);
  assert.equal(indentText(source),"段：\n    落 取 2.\n    ｛\n        表 := {'值': 落}.\n        显 表.\n    ｝\n落。\n显 {}.\n({}).\n{}");
});
test('段 and 落 are contextual whole names, preserve member and binding positions',()=>{
  const source="段 取 1. 落 := 2. 段落 取 3. 落叶 取 4.\n段:\n落 取 落+1.\n显 文 其 段 始:0 终:2.\n显 落.\nf 段: {} 落: 2.\n落 .";
  const result=analyze(source);
  assert.equal(result.depth,0);assert.equal(result.blocks.filter(b=>b.scoped).length,1);
  assert.equal(result.tokens.filter(t=>t.open==='段').length,1);
  assert.equal(result.tokens.filter(t=>t.close==='段').length,1);
  assert.equal(result.tokens.filter(t=>t.text==='段'&&t.face==='builtin').length,1);
  for(const name of ['段落','落叶']) assert.equal(result.tokens.find(t=>t.text===name).face,null);
  assert.equal(result.tokens.find(t=>t.text==='段').face,null);
  assert.equal(result.tokens.find(t=>t.text==='落').face,null);
  for(const invalid of ['段: 落',"段: 落 '.'", '段: 落 取 2.']) assert.equal(analyze(invalid).depth,1);
  assert.equal(analyze('段 # 开头\n：\n落 # 结束\n。').depth,0);
});
test('scoped blocks preserve function classification and outer control flow indentation',()=>{
  const source='作 主:\n循 2 次\n段:\n算 内:\n{\n得 {}.\n}\n法\n试\n{ 完. }\n救 原因\n{ 破. }\n终.\n落.\n环\n为';
  const result=analyze(source);
  assert.equal(result.depth,0);assert.ok(result.blocks.every(b=>b.closed));
  assert.deepEqual(result.blocks.filter(b=>['算','作'].includes(b.kind)).map(b=>[b.kind,b.literal]),[['作',false],['算',false]]);
  assert.equal(result.tokens.find(t=>t.text==='内').face,'function');
  assert.equal(indentText(indentText(source)),indentText(source));
});
test('assignment aliases are whole punct tokens with conservative hover, never headers',()=>{
  const source="段:=1. 落：=2. 表 := {'键': 1}. 表['键'] := 2. 对象 其 段 := 3. 显 ':='。 # ：=\n解. := 释.";
  const result=analyze(source),aliases=result.tokens.filter(t=>t.text===':=');
  assert.equal(aliases.length,5);assert.ok(aliases.every(t=>t.kind==='punct'&&t.face==='keyword'));
  assert.equal(result.depth,0);assert.ok(result.blocks.every(b=>!b.scoped));
  assert.deepEqual(lex(': = ：＝').map(t=>t.text),[':','=',':','＝']);
  const html=highlight(source);assert.equal((html.match(/data-help=/g)||[]).length,5);
  assert.ok(html.includes('写块局部'));assert.ok(html.includes(':= 与取完全等价'));
  assert.equal(highlight("显 ':='。 # :=").includes('data-help'),false);
});
test('scope Enter, closing marker dedent and incomplete prefixes remain tolerant',()=>{
  for(const source of ['段:','段：','{','｛','段:\n{']) assert.equal(enterEdit(source,source.length).text,source==='段:\n{'?'\n        ':'\n    ');
  for(const line of ['落.','落 。','落. 显 1.','｝','}。'])assert.equal(needsAutoDedent(line),true);
  for(const line of ['落 取 2.','落 := 2.','落叶.','落','"落."','# 落.'])assert.equal(needsAutoDedent(line),false);
  const source="段：\n落 ：= 2.\n{\n回 := 算 值: 得 {'值': 值}. 法.\n回 值: {}.\n}\n落。";
  for(let end=0;end<=source.length;end++){
    const prefix=source.slice(0,end),formatted=indentText(prefix);
    assert.equal(indentText(formatted),formatted);highlight(prefix);enterEdit(prefix,prefix.length);
  }
});

test('practical array members are contextual and library functions stay ordinary',()=>{
  const result=analyze("列 其 删 位:0. 列 其 弹. 列 其 查 值:1. 拆分 取 1. 定点 取 2. 造源 取 3.");
  for(const name of ['删','弹','查'])assert.equal(result.tokens.find(t=>t.text===name).face,'builtin');
  for(const name of ['拆分','定点','造源'])assert.equal(result.tokens.find(t=>t.text===name).face,null);
  assert.match(highlight('列 其 查 1.'), /初始浅快照/);
  assert.doesNotMatch(highlight('查 取 1.'), /初始浅快照/);
});


test('dictionary member hints use mu and xiang without reserving user names',()=>{
  assert.match(highlight('表 其 查 目:1.'), /典：查 目:/);
  assert.match(highlight('表 其 增 目:1 相:2.'), /典：增 目: 相:/);
  assert.match(highlight('表 其 除 目:1.'), /典：除 目:/);
  const tokens=analyze('目 取 1. 相 取 2. 值 取 3.').tokens;
  for(const name of ['目','相','值'])assert.equal(tokens.find(t=>t.text===name).face,null);
});

// The import name is an ordinary string, never a new language keyword.
test('renamed rujing bridge alone is built in; old and user names remain ordinary',()=>{
  const result=analyze("竞 取 外言 '如:竞'. 显 __如竞. 竞赛 取 1. 如竞 取 2. __竞赛 取 3. __如竞者 取 4.");
  assert.equal(result.tokens.find(t=>t.text==='__如竞').face,'builtin');
  for(const name of ['竞赛','如竞','__竞赛','__如竞者']) assert.equal(result.tokens.find(t=>t.text===name).face,null);
});

test('graphics bridge is builtin while public visualization names stay ordinary',()=>{
  const tokens=analyze('__如观 画布 每帧 鼠标按下 如观 __如观者').tokens;
  assert.equal(tokens.find(t=>t.text==='__如观').face,'builtin');
  for(const name of ['画布','每帧','鼠标按下','如观','__如观者'])assert.equal(tokens.find(t=>t.text===name).face,null);
});

test('canonical module imports keep colons inside opaque strings',()=>{
  for(const module of ['如:竞','如:观']) for(const [open,close] of [["'","'"],['"','"'],['‘','’'],['“','”']]) {
    const source=`模块 取 外言 ${open}${module}${close}.\n显 '完成'.`;
    const result=analyze(source), literal=`${open}${module}${close}`;
    assert.equal(result.tokens.find(t=>t.text===literal).kind,'string');
    assert.ok(highlight(source).includes('tok-string'));
    assert.ok(highlight(source).includes(module));
    assert.equal(result.tokens.filter(t=>t.text===':').length,0);
    assert.equal(result.blocks.length,0);
    assert.equal(indentText(source),source);
  }
});


test('array sorting and transformation help stays contextual',()=>{
  for(const name of ['排序','另成']) {
    const source=`列 其 ${name}.`;
    assert.equal(analyze(source).tokens.find(t=>t.text===name).face,'builtin');
    assert.match(highlight(source), /新阵|新浅复制阵/);
    for(const text of [`${name} 取 1.`, `# 其 ${name}.`, `'其 ${name}.'`, `批. 其 ${name}.`, `解. 其 ${name}. 释.`])
      assert.doesNotMatch(highlight(text), /内置阵：/);
  }
  assert.match(highlight('列 其 排序.'), /先于:二参算/);
  assert.match(highlight('列 其 另成 算法:回调.'), /不接受作/);
});


test('array and dictionary traversal help distinguishes positional callbacks',()=>{
  assert.match(highlight('列 其 逐位 回调:遍历.'), /位、值/);
  assert.match(highlight('表 其 逐目 回调:遍历.'), /目、相/);
  for(const name of ['逐位','逐目']) {
    assert.equal(analyze(`列 其 ${name}.`).tokens.find(t=>t.text===name).face,'builtin');
    for(const source of [`${name} 取 1.`, `# 其 ${name}.`, `'其 ${name}.'`, `批. 其 ${name}.`, `解. 其 ${name}. 释.`])
      assert.doesNotMatch(highlight(source), /内置阵：|内置典：/);
  }
});

test('graphics upgrade names are contextual members, not keywords',()=>{
  for(const word of '三角形 多边形 平移 旋转 缩放 保存 恢复 变换 重置变换 裁剪 取消裁剪'.split(' ')) {
    assert.equal(analyze(`图 其 ${word}.`).tokens.find(t=>t.text===word).face,'builtin');
    assert.equal(analyze(`${word} 取 1.`).tokens.find(t=>t.text===word).face,null);
  }
});

test('alpha color helper highlights and explains only member contexts',()=>{
  for(const source of ['观 其 颜色 255 64 64 128.','观@颜色 红:255 绿:64 蓝:64 不透明度:128.']) {
    assert.equal(analyze(source).tokens.find(t=>t.text==='颜色').face,'builtin');
    assert.match(highlight(source), /颜色 红 绿 蓝 不透明度/);
    assert.match(highlight(source), /0 全透明、255 不透明/);
    assert.match(highlight(source), /不钳位、不舍入/);
  }
  for(const source of ['颜色 取 1.', '颜色表 取 1.', '作 调色 颜色: 显 颜色. 为.',
      '# 观 其 颜色 1 2 3 4.', "'观 其 颜色 1 2 3 4.'", '批. 观 其 颜色.', '解. 观 其 颜色. 释.']) {
    assert.doesNotMatch(highlight(source), /如:观：/);
    for(const token of analyze(source).tokens.filter(t=>t.text==='颜色')) assert.equal(token.face,null);
  }
  for(const color of ["'#RRGGBB'", "'#12345678'", "'#abcdef00'"])
    assert.equal(lex(color)[0].kind,'string');
});

test('text alignment highlights and explains only exact member contexts',()=>{
  for(const source of ["图 其 文字对齐 '中' '中'.", "图@文字对齐 横向:'右' 纵向:'基线'."]) {
    assert.equal(analyze(source).tokens.find(t=>t.text==='文字对齐').face,'builtin');
    assert.match(highlight(source), /文字对齐 横向 纵向/);
    assert.match(highlight(source), /默认左上/);
    assert.match(highlight(source), /跨回调保留/);
    assert.match(highlight(source), /不是笔画包围盒或宽度测量/);
  }
  for(const source of ['文字对齐 取 1.', '文字对齐表 取 1.', '作 调整 文字对齐: 显 文字对齐. 为.',
      "# 图 其 文字对齐 '中' '中'.", "'图 其 文字对齐'", '批. 图 其 文字对齐.', '解. 图 其 文字对齐. 释.']) {
    assert.doesNotMatch(highlight(source), /如:观画布：/);
    for(const token of analyze(source).tokens.filter(t=>t.text==='文字对齐')) assert.equal(token.face,null);
  }
});

test('real-time getters are contextual zero-argument value members',()=>{
  for(const word of ['经过秒','间隔秒']) {
    for(const source of [`显 图 其 ${word}.`, `显 图@${word}.`]) {
      assert.equal(analyze(source).tokens.find(t=>t.text===word).face,'builtin');
      assert.match(highlight(source), /零参数只读数值/);
      assert.match(highlight(source), /同次回调内冻结/);
    }
    for(const source of [`${word} 取 1.`, `${word}数 取 1.`, `作 读值 ${word}: 显 ${word}. 为.`,
        `# 图 其 ${word}.`, `'图 其 ${word}'`, `批. 图 其 ${word}.`, `解. 图 其 ${word}. 释.`]) {
      assert.doesNotMatch(highlight(source), /如:观画布：/);
      for(const token of analyze(source).tokens.filter(t=>t.text===word)) assert.equal(token.face,null);
    }
  }
  assert.match(highlight('显 图 其 经过秒.'), /包含暂停和隐藏页间隔/);
  assert.match(highlight('显 图 其 间隔秒.'), /隐藏间隔不截断/);
  assert.match(highlight('显 图 其 间隔秒.'), /每帧仍只收帧序号/);
});

test('arc and sector help stays contextual and states the six-argument contract',()=>{
  for(const word of ['弧','扇形']) {
    for(const source of [`图 其 ${word} 0 0 30 20 0 1.`, `图@${word} 横:0 纵:0 宽:30 高:20 始角:0 转角:1.`]) {
      assert.equal(analyze(source).tokens.find(t=>t.text===word).face,'builtin');
      const html=highlight(source);
      for(const fragment of [`${word} 横 纵 宽 高 始角 转角`,'六个参数均必需','全位置或全命名','返回空','带符号转角为弧度','负缩放镜像','零转角无像素但保留命令','100000','非圆椭圆使用参数角']) assert.ok(html.includes(fragment),fragment);
    }
    for(const source of [`${word} 取 1.`, `${word}图 取 1.`, `作 描画 ${word}: 显 ${word}. 为.`,
        `# 图 其 ${word}.`, `'图 其 ${word}'`, `批. 图 其 ${word}.`, `解. 图 其 ${word}. 释.`]) {
      assert.doesNotMatch(highlight(source), /如:观画布：/);
      for(const token of analyze(source).tokens.filter(t=>t.text===word)) assert.equal(token.face,null);
    }
  }
  assert.match(highlight('图 其 弧 0 0 30 20 0 1.'), /只描边，忽略填色/);
  assert.match(highlight('图 其 扇形 0 0 30 20 0 1.'), /部分扇形含两条半径边/);
  assert.match(highlight('图 其 扇形 0 0 30 20 0 1.'), /无中心辐条/);
  for(const word of ['横','纵','宽','高','始角','转角']) assert.equal(analyze(`${word} 取 1.`).tokens.find(t=>t.text===word).face,null);
});

test('polyline help stays contextual and states the open-path contract',()=>{
  for(const source of ['图 其 折线 [[1,2],[3,4]].','图@折线 点阵:[[1,2],[3,4]].']) {
    assert.equal(analyze(source).tokens.find(t=>t.text==='折线').face,'builtin');
    const html=highlight(source);
    for(const fragment of ['折线 点阵','唯一参数必需','位置或点阵:调用','返回空','2～256',
      '100000','拒绝事实与空','开放路径只描边一次','不闭合、不填充','忽略且保留填色',
      '不逐段叠色','深复制','全重合点合法','空描边或零长度仍计入原有预算','封闭填充用多边形']) assert.ok(html.includes(fragment),fragment);
  }
  for(const source of ['折线 取 1.','折线图 取 1.','作 描画 折线: 显 折线. 为.',
    '# 图 其 折线.','\'图 其 折线\'','批. 图 其 折线.','解. 图 其 折线. 释.']) {
    assert.doesNotMatch(highlight(source), /如:观画布：/);
    for(const token of analyze(source).tokens.filter(t=>t.text==='折线')) assert.equal(token.face,null);
  }
  assert.equal(analyze('点阵 取 1.').tokens.find(t=>t.text==='点阵').face,null);
});

test('bezier help is contextual and states the native cubic contract',()=>{
  for(const source of ['图 其 贝塞尔 0 0 10 20 30 20 40 0.',
    '图@贝塞尔 起横:0 起纵:0 控一横:10 控一纵:20 控二横:30 控二纵:20 终横:40 终纵:0.']) {
    assert.equal(analyze(source).tokens.find(t=>t.text==='贝塞尔').face,'builtin');
    const html=highlight(source);
    for(const fragment of ['贝塞尔 起横 起纵 控一横 控一纵 控二横 控二纵 终横 终纵','八参全必需',
      '全位置或全命名调用','返回空','单段三次曲线','控制点不必经过','100000','拒绝事实与空',
      'moveTo','bezierCurveTo','只描边一次','不闭合、不填充','忽略且保留填色','深复制',
      '原生退化行为','空描边或退化仍计入原有预算','用户同名方法按其声明']) assert.ok(html.includes(fragment),fragment);
  }
  for(const source of ['贝塞尔 取 1.','贝塞尔图 取 1.','作 描画 贝塞尔: 显 贝塞尔. 为.',
    '# 图 其 贝塞尔.','\'图 其 贝塞尔\'','批. 图 其 贝塞尔.','解. 图 其 贝塞尔. 释.']) {
    assert.doesNotMatch(highlight(source), /如:观画布：/);
    for(const token of analyze(source).tokens.filter(t=>t.text==='贝塞尔')) assert.equal(token.face,null);
  }
  for(const word of ['起横','起纵','控一横','控一纵','控二横','控二纵','终横','终纵'])
    assert.equal(analyze(`${word} 取 1.`).tokens.find(t=>t.text===word).face,null);
});

test('cache and image remain contextual ordinary members with lifecycle and budget help',()=>{
  for(const [word,source,parts] of [['缓存','图 其 缓存 32 32 (作 层: 为).',['只在初始化','不可变图像','2047','128 KiB']],['贴图','图@贴图 图像:星空 横:0 纵:0.',['原尺寸','返回空','关闭','完整定义']]]){
    assert.equal(analyze(source).tokens.find(t=>t.text===word).face,'builtin');for(const part of parts)assert.ok(highlight(source).includes(part));
    for(const plain of [`${word} 取 1.`,`作 方法 ${word}: 显 ${word}. 为.`,`# 图 其 ${word}.`,`'图 其 ${word}'`]){for(const t of analyze(plain).tokens.filter(t=>t.text===word))assert.equal(t.face,null);}
  }
});
