import {outputBytes} from './notebook.mjs';
export const PREVIEW_CHARS=2000,PREVIEW_LINES=8,PAGE_CHARS=32768;
// UTF-16 display indices only; all retention and transport budgets use UTF-8.
const boundary=(text,index)=>index>0&&index<text.length&&/[\uDC00-\uDFFF]/.test(text[index])?index+1:index;
export function outputWindow(outputs,expanded=false,page=0){
  const total=outputs.reduce((n,item)=>n+(item.text?.length||0),0);
  let preview=0,lines=0,records=0;
  outer:for(const item of outputs){if(!item.text)continue;if(++records>32)break;for(const char of item.text){if(preview+char.length>PREVIEW_CHARS||lines>=PREVIEW_LINES)break outer;preview+=char.length;if(char==='\n')lines++;}}
  // Bound both character volume and node count, even for alternating streams.
  const starts=[0];let offset=0,used=0,nodes=0;
  for(const item of outputs){if(!item.text)continue;let local=0;while(local<item.text.length){if(used>=PAGE_CHARS||nodes>=128){starts.push(offset);used=nodes=0;}const end=boundary(item.text,Math.min(item.text.length,local+PAGE_CHARS-used));const count=end-local;used+=count;offset+=count;local=end;nodes++;}}
  const foldable=preview<total,pages=starts.length;page=Math.max(0,Math.min(page,pages-1));
  const start=expanded?starts[page]:0,end=expanded?(starts[page+1]??total):preview;
  offset=0;const items=[];
  for(const item of outputs){if(item.type==='graphics'){items.push(item);continue;}const a=Math.max(0,start-offset),b=Math.min(item.text.length,end-offset);if(a<b)items.push({type:item.type,text:item.text.slice(boundary(item.text,a),boundary(item.text,b))});offset+=item.text.length;}
  return {items,foldable,page,pages,bytes:outputs.reduce((n,item)=>n+outputBytes(item),0)};
}
