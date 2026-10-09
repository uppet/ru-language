import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {lex,analyze,highlight,indentText,enterEdit,indentSelection} from '../static/editor.mjs';
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
