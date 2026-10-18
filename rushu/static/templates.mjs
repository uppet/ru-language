import {newCell,blankBook} from './notebook.mjs';
import {ensureGeneration} from './history.mjs';

/** Starting points are local document data. Choosing one never runs code or a model. */
export const templates=Object.freeze([
  {id:'basics',title:'基础入门',description:'第一次写如言，从显示一句话开始。',detail:'试试「显」和「取」，改一句问候就能运行。'},
  {id:'text',title:'文本处理',description:'整理一小段文字，清理空白或替换词语。',detail:'使用如:文本，两个短例都可以直接修改。'},
  {id:'contest',title:'如竞题解',description:'先用固定样本验证解题思路。',detail:'从一句样本读出两个数并求和，不等待终端输入。'},
  {id:'graphics',title:'如观互动',description:'画一个圆，再用鼠标和键盘改变画面。',detail:'点击画布画圆，聚焦画布后按 r 清空。'},
  {id:'generation',title:'如是我言生成',description:'用一句意图，请模型起草如言代码。',detail:'需先配置生成提供方；选择模板不会请求模型。'},
  {id:'blank',title:'空白如书',description:'直接开始写。',detail:'只有一个空代码格。'}
].map(template=>Object.freeze(template)));

const definitions={
  basics:()=>[
    newCell('markdown','# 从一句问候开始\n\n点击代码格的「运行」，或按 Shift + Enter。「显」把内容显示出来。'),
    newCell('code',"显 '你好，如书'."),
    newCell('markdown','「取」给内容起一个名字。把下面的问候改成你自己的话，再运行；预期显示「今天开始写如言」。'),
    newCell('code',"问候 取 '今天开始写如言'.\n显 问候.")
  ],
  text:()=>[
    newCell('markdown','# 整理一小段文字\n\n先导入「如:文本」，去掉句子首尾的空格。运行后显示「你好，如书」。'),
    newCell('code',"文 取 外言 '如:文本'.\n显 文 其 去空白 '  你好，如书  '."),
    newCell('markdown','也可以替换一个词。下面显示「小明喜欢梨」；试着换成你喜欢的水果。'),
    newCell('code',"文 取 外言 '如:文本'.\n显 文 其 替换 '小明喜欢苹果' '苹果' '梨'.")
  ],
  contest:()=>[
    newCell('markdown','# 两个数求和\n\n题目：给定两个整数，输出它们的和。这里把样本写在代码里，用如竞的「扫句」读取；「3 5」应输出 8。换一组数，就能再次验证。\n\n本例不读取终端输入。如竞的「读入」会等待标准输入结束，适合提交到评测环境时使用。'),
    newCell('code',"竞 取 外言 '如:竞'.\n入 取 竞 其 扫句 '3 5'.\n左数 取 入 其 数.\n右数 取 入 其 数.\n显 左数 + 右数.")
  ],
  graphics:()=>[
    newCell('markdown','# 点击画布画一个圆\n\n运行后出现蓝色圆点。点击画布，圆点移到点击处；先点击画布让它获得焦点，再按 r 清空。\n\n创建画布和回调放在同一格。运行其他代码格会结束这幅画的互动，重跑本格即可恢复。'),
    newCell('code',"观 取 外言 '如:观'.\n图 取 观 其 画布 360 200.\n图 其 背景 '#f4f6fb'.\n图 其 描边 空.\n图 其 填色 '#4677ff'.\n图 其 椭圆 164 84 32 32.\n图 其 鼠标按下 (作 横 纵 键:\n    图 其 背景 '#f4f6fb'.\n    图 其 椭圆 (横 - 16) (纵 - 16) 32 32.\n为).\n图 其 按键 (作 键:\n    若 键 == 'r' 则\n        图 其 背景 '#f4f6fb'.\n    然.\n为).")
  ],
  generation:()=>{
    const cell=newCell();
    ensureGeneration(cell,'请写一个如言程序，显示 1 到 5 的平方，每行一个结果。\n如是我言');
    return [newCell('markdown','# 从意图生成草稿\n\n先配置生成提供方，再修改下方意图，保留末行「如是我言」，点击「如是我言 · 生成」。选择本模板不会请求模型；点击生成时会把本格意图和当前源码发送给所配置的提供方，可能产生费用。\n\n生成后先审阅源码，再单独点击「运行」。这次意图的预期结果是依次显示 1、4、9、16、25，每个数占一行。'),cell];
  }
};

export function createTemplateBook(id) {
  const template=templates.find(item=>item.id===id);
  if(!template)throw new Error('找不到这个如书模板。');
  if(id==='blank')return blankBook();
  return {title:template.title,cells:definitions[id]()};
}
