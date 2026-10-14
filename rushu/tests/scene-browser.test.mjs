// Real Chromium canvas + DOM tests; optional local browser dependency, no fake DOM.
import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);let chromium;try{({chromium}=require('playwright'));}catch{}
const enabled=process.env.RUN_RUSHU_BROWSER_TESTS==='1'&&!!chromium&&existsSync(process.env.CHROMIUM_PATH||'/usr/bin/chromium');
let server,browser,url;
before(async()=>{if(!enabled)return;server=createServer(async(req,res)=>{if(req.url==='/scene.mjs'){res.setHeader('Content-Type','text/javascript');res.end(await readFile(new URL('../static/scene.mjs',import.meta.url)));}else{res.setHeader('Content-Type','text/html');res.end('<button id="outside">其他控件</button><main></main><script type="module">import * as graphics from "/scene.mjs";window.graphics=graphics;</script>');}});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));url=`http://127.0.0.1:${server.address().port}`;browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});});
after(async()=>{await browser?.close();if(server)await new Promise(resolve=>server.close(resolve));});
async function page(){const page=await browser.newPage();await page.goto(url);await page.waitForFunction(()=>window.graphics);return page;}
const frame=()=>({canvas_id:'canvas-1',width:160,height:120,fps:30,running:false,handlers:['mouse_down','mouse_move','key_down'],commands:[{op:'background',color:'#ffffff'},{op:'rect',x:10,y:10,width:30,height:30,fill:'#ff0000',stroke:'',stroke_width:1},{op:'ellipse',x:60,y:10,width:40,height:20,fill:'#0000ff',stroke:'',stroke_width:1},{op:'line',x1:10,y1:80,x2:100,y2:80,width:2,color:'#00ff00'},{op:'text',x:0,y:95,size:16,color:'#000000',text:'如观'}]});
const options={skip:enabled?false:'Set RUN_RUSHU_BROWSER_TESTS=1 with local Chromium and Playwright; no fake DOM substitute.'};
test('real canvas renders primitive pixels and clears previous frame',options,async()=>{const p=await page();try{const result=await p.evaluate(s=>{const v=graphics.createSceneView(s,{historical:true});document.querySelector('main').append(v.root);const ctx=v.canvas.getContext('2d'),pixel=(x,y)=>[...ctx.getImageData(x,y,1,1).data];const result=[pixel(20,20),pixel(80,20),pixel(50,80),pixel(150,110)];v.update({...s,commands:[]});result.push(pixel(20,20));return result;},frame());assert.deepEqual(result,[[255,0,0,255],[0,0,255,255],[0,255,0,255],[255,255,255,255],[0,0,0,0]]);}finally{await p.close();}});
test('real focus scopes keys and CSS-scaled pointer coordinates',options,async()=>{const p=await page();try{await p.evaluate(s=>{window.events=[];window.v=graphics.createSceneView(s,{send:async e=>events.push(e)});document.querySelector('main').append(v.root);v.canvas.style.width='320px';v.canvas.style.height='240px';},frame());await p.locator('#outside').focus();await p.keyboard.press('a');await p.waitForTimeout(50);assert.equal(await p.evaluate(()=>events.length),0);await p.locator('canvas').click({position:{x:40,y:60}});await p.waitForTimeout(80);await p.keyboard.press('ArrowRight');await p.waitForTimeout(80);const events=await p.evaluate(()=>events);assert.ok(events.some(e=>e.type==='mouse_down'&&e.x===20&&e.y===30));assert.ok(events.some(e=>e.type==='key_down'&&e.key==='ArrowRight'));await p.keyboard.press('Tab');assert.notEqual(await p.evaluate(()=>document.activeElement.tagName),'CANVAS');}finally{await p.close();}});
test('real renderer waits for callback completion, throttles and stops',options,async()=>{const p=await page();try{await p.evaluate(s=>{window.events=[];window.releases=[];window.v=graphics.createSceneView({...s,running:true,handlers:['frame','mouse_move']},{send:e=>{events.push(e);return new Promise(r=>releases.push(r));}});document.querySelector('main').append(v.root);},frame());await p.waitForTimeout(140);assert.equal(await p.evaluate(()=>events.length),1);await p.evaluate(()=>{for(let i=0;i<100;i++)v.canvas.dispatchEvent(new PointerEvent('pointermove',{clientX:i,clientY:10}));releases.shift()();});await p.waitForTimeout(80);assert.equal(await p.evaluate(()=>events.length),2);assert.equal(await p.evaluate(()=>events[1].type),'mouse_move');await p.getByRole('button',{name:'停止画布',exact:true}).click();assert.equal(await p.evaluate(()=>events.at(-1).type),'close');await p.evaluate(()=>releases.forEach(r=>r()));await p.waitForTimeout(100);assert.equal(await p.evaluate(()=>events.length),3);assert.match(await p.locator('.scene-toolbar').innerText(),/已停止/);}finally{await p.close();}});
test('historical and disposed real canvases never send input',options,async()=>{const p=await page();try{await p.evaluate(s=>{window.events=[];window.v=graphics.createSceneView(s,{historical:true,send:async e=>events.push(e)});document.querySelector('main').append(v.root);},frame());await p.locator('canvas').click();await p.keyboard.press('x');await p.waitForTimeout(100);assert.equal(await p.evaluate(()=>events.length),0);await p.evaluate(s=>{v.dispose();v.root.remove();window.v=graphics.createSceneView({...s,running:true,handlers:['frame','key_down']},{send:async e=>events.push(e)});document.querySelector('main').append(v.root);v.dispose();},frame());await p.locator('canvas').focus();await p.keyboard.press('x');await p.waitForTimeout(100);assert.equal(await p.evaluate(()=>events.length),0);}finally{await p.close();}});

test('real alpha pixels distinguish transparency, opaque legacy colors and source-over blending',options,async()=>{
  const p=await page();try{
    const result=await p.evaluate(s=>{
      const rectangle=(x,fill)=>({op:'rect',x,y:0,width:20,height:20,fill,stroke:'',stroke_width:1});
      const v=graphics.createSceneView({...s,commands:[rectangle(0,'#FF000000'),rectangle(20,'#FF000080'),rectangle(40,'#FF0000FF'),rectangle(60,'#FF0000')]},{historical:true});
      document.querySelector('main').append(v.root);
      const ctx=v.canvas.getContext('2d'),pixel=(x,y)=>[...ctx.getImageData(x,y,1,1).data];
      const result=[pixel(10,10),pixel(30,10),pixel(50,10),pixel(70,10)];
      v.update({...s,commands:[{op:'background',color:'#0000FF'},rectangle(0,'#FF000080')]});
      result.push(pixel(10,10));v.dispose();return result;
    },frame());
    assert.deepEqual(result,[[0,0,0,0],[255,0,0,128],[255,0,0,255],[255,0,0,255],[128,0,127,255]]);
  }finally{await p.close();}
});

test('real translucent frames fully redraw with no accumulated opacity or movement trails',options,async()=>{
  const p=await page();try{
    const result=await p.evaluate(s=>{
      const rectangle=x=>({op:'rect',x,y:0,width:20,height:20,fill:'#FF000080',stroke:'',stroke_width:1});
      const v=graphics.createSceneView({...s,commands:[rectangle(0)]},{historical:true});
      document.querySelector('main').append(v.root);
      const ctx=v.canvas.getContext('2d'),pixel=(x,y)=>[...ctx.getImageData(x,y,1,1).data];
      const result=[pixel(10,10)];
      for(let i=0;i<3;i++)v.update({...s,commands:[rectangle(0)]});
      result.push(pixel(10,10));
      v.update({...s,commands:[rectangle(30)]});result.push(pixel(10,10),pixel(40,10));
      const background={...s,commands:[{op:'background',color:'#0000FF40'}]};
      v.update(background);result.push(pixel(40,10));
      for(let i=0;i<3;i++)v.update(background);
      result.push(pixel(40,10));
      v.update({...s,commands:[]});result.push(pixel(40,10));v.dispose();return result;
    },frame());
    assert.deepEqual(result,[[255,0,0,128],[255,0,0,128],[0,0,0,0],[255,0,0,128],[0,0,255,64],[0,0,255,64],[0,0,0,0]]);
  }finally{await p.close();}
});

test('real historical mid-scene backgrounds replace pixels across transform and clip boundaries',options,async()=>{
  const p=await page();try{
    const result=await p.evaluate(s=>{
      const transform=[1,0,0,1,20,20],clips=[{x:0,y:0,width:5,height:5,transform:[1,0,0,1,0,0]}];
      const rectangle={op:'rect',x:0,y:0,width:s.width,height:s.height,fill:'#00FF00',stroke:'',stroke_width:1};
      const background=color=>({op:'background',color,transform,clips});
      const v=graphics.createSceneView({...s,commands:[rectangle,{...rectangle,transform,clips},background('#FF000080')]},{historical:true});
      document.querySelector('main').append(v.root);
      const ctx=v.canvas.getContext('2d'),pixel=(x,y)=>[...ctx.getImageData(x,y,1,1).data];
      const result=[pixel(1,1),pixel(150,110)];
      v.update({...s,commands:[rectangle,background('#FF000080'),rectangle,background('#0000FF40')]});
      result.push(pixel(1,1),pixel(150,110));
      v.update({...s,commands:[rectangle,background('#FF000080'),rectangle,background('#0000FF00')]});
      result.push(pixel(1,1),pixel(150,110));v.dispose();return result;
    },frame());
    assert.deepEqual(result,[[255,0,0,128],[255,0,0,128],[0,0,255,64],[0,0,255,64],[0,0,0,0],[0,0,0,0]]);
  }finally{await p.close();}
});

test('real ellipse, polygon, stroke and text respect alpha while empty styles stay invisible',options,async()=>{
  const p=await page();try{
    const result=await p.evaluate(s=>{
      const v=graphics.createSceneView({...s,commands:[
        {op:'ellipse',x:0,y:0,width:20,height:20,fill:'#FF000080',stroke:'',stroke_width:1},
        {op:'polygon',points:[[30,0],[50,0],[50,20],[30,20]],fill:'#00FF0080',stroke:'',stroke_width:1},
        {op:'line',x1:60,y1:10,x2:80,y2:10,color:'#0000FF80',width:4},
        {op:'rect',x:90,y:0,width:20,height:20,fill:'',stroke:'#FF000080',stroke_width:4},
        {op:'rect',x:120,y:0,width:20,height:20,fill:'',stroke:'',stroke_width:1},
        {op:'text',x:0,y:30,size:30,color:'#00000080',text:'Alpha'},
      ]},{historical:true});
      document.querySelector('main').append(v.root);
      const ctx=v.canvas.getContext('2d'),pixel=(x,y)=>[...ctx.getImageData(x,y,1,1).data];
      const result=[pixel(10,10),pixel(40,10),pixel(70,10),pixel(90,10),pixel(100,10),pixel(130,10)];
      const text=ctx.getImageData(0,30,100,40).data;
      let maximumAlpha=0;for(let i=3;i<text.length;i+=4)maximumAlpha=Math.max(maximumAlpha,text[i]);
      result.push(maximumAlpha);v.dispose();return result;
    },frame());
    assert.deepEqual(result,[[255,0,0,128],[0,255,0,128],[0,0,255,128],[255,0,0,128],[0,0,0,0],[0,0,0,0],128]);
  }finally{await p.close();}
});

test('real text anchors match native Canvas pixels for every enum pair and legacy defaults',options,async()=>{
  const p=await page();try{
    const result=await p.evaluate(s=>{
      const actual=document.createElement('canvas'),expected=document.createElement('canvas');
      expected.width=s.width;expected.height=s.height;
      const reference=expected.getContext('2d'),checks=[];
      const compare=label=>{
        const a=actual.getContext('2d').getImageData(0,0,s.width,s.height).data;
        const b=reference.getImageData(0,0,s.width,s.height).data;
        checks.push({label,same:a.every((value,index)=>value===b[index]),visible:a.some((value,index)=>index%4===3&&value>0)});
      };
      const native=(value,align,baseline)=>{
        reference.fillStyle=value.color;reference.font=`${value.size}px sans-serif`;
        reference.textAlign=align;reference.textBaseline=baseline;reference.fillText(value.text,value.x,value.y);
      };
      for(const align of ['left','center','right'])for(const baseline of ['top','middle','bottom','alphabetic']){
        const value={op:'text',x:80,y:60,size:18,color:'#12345680',text:'锚 Ag',align,baseline};
        graphics.drawScene(actual,{...s,commands:[value]});
        expected.width=s.width;native(value,align,baseline);compare(`${align}/${baseline}`);
      }
      const values=[{op:'text',x:140,y:30,size:18,color:'#ff000080',text:'先',align:'right',baseline:'alphabetic'},
        {op:'text',x:30,y:55,size:18,color:'#0000ff80',text:'旧 Ag'},
        {op:'text',x:140,y:85,size:18,color:'#00aa0080',text:'横',align:'right'},
        {op:'text',x:30,y:105,size:18,color:'#20202080',text:'纵',baseline:'alphabetic'}];
      graphics.drawScene(actual,{...s,commands:values});
      expected.width=s.width;
      native(values[0],'right','alphabetic');native(values[1],'left','top');
      native(values[2],'right','top');native(values[3],'left','alphabetic');compare('mixed legacy and partial defaults');
      return checks;
    },frame());
    assert.equal(result.length,13);
    for(const check of result){assert.equal(check.same,true,check.label);assert.equal(check.visible,true,check.label);}
  }finally{await p.close();}
});

test('real transformed clipped alpha text matches native anchors and historical repaint',options,async()=>{
  const p=await page();try{
    const result=await p.evaluate(s=>{
      const actual=document.createElement('canvas'),expected=document.createElement('canvas');
      expected.width=s.width;expected.height=s.height;
      const commands=[{op:'background',color:'#ddeeFF80'},
        {op:'text',x:50,y:30,size:24,color:'#ff000080',text:'Ag 如观',align:'center',baseline:'middle',
          transform:[1.1,.2,-.1,1,25,25],clips:[{x:15,y:15,width:100,height:70,transform:[1,0,0,1,0,0]}]},
        {op:'text',x:110,y:95,size:20,color:'#0000ff80',text:'尾 Ag',align:'right',baseline:'alphabetic'},
        {op:'text',x:15,y:90,size:16,color:'#00660080',text:'旧'},
        {op:'text',x:100,y:50,size:24,color:'',text:'隐藏',align:'center',baseline:'bottom'}];
      const scene={...s,commands},reference=expected.getContext('2d');
      reference.fillStyle='#ddeeFF80';reference.fillRect(0,0,s.width,s.height);
      reference.save();reference.beginPath();reference.rect(15,15,100,70);reference.clip();
      reference.setTransform(1.1,.2,-.1,1,25,25);reference.fillStyle='#ff000080';reference.font='24px sans-serif';
      reference.textAlign='center';reference.textBaseline='middle';reference.fillText('Ag 如观',50,30);reference.restore();
      reference.fillStyle='#0000ff80';reference.font='20px sans-serif';reference.textAlign='right';reference.textBaseline='alphabetic';reference.fillText('尾 Ag',110,95);
      reference.fillStyle='#00660080';reference.font='16px sans-serif';reference.textAlign='left';reference.textBaseline='top';reference.fillText('旧',15,90);
      const pixels=reference.getImageData(0,0,s.width,s.height).data;
      const same=canvas=>canvas.getContext('2d').getImageData(0,0,s.width,s.height).data.every((value,index)=>value===pixels[index]);
      graphics.drawScene(actual,scene);
      const serialized=JSON.parse(JSON.stringify(scene));
      const view=graphics.createSceneView(serialized,{historical:true,send:async()=>{throw new Error('history must remain inert');}});
      document.querySelector('main').append(view.root);
      const results=[same(actual),same(view.canvas),view.live===false];
      view.update(serialized,true);results.push(same(view.canvas));view.dispose();return results;
    },frame());
    assert.deepEqual(result,[true,true,true,true]);
  }finally{await p.close();}
});

test('real immutable cache pixels retain alpha, clips, transforms and transparent frame replacement',options,async()=>{
  const p=await page();try{
    const result=await p.evaluate(()=>{
      const recipe={id:'cache-1',kind:'drawing',width:20,height:20,commands:[{op:'rect',x:0,y:0,width:20,height:20,fill:'#ff000080',stroke:'',stroke_width:1}]};
      const scene={canvas_id:'cache',width:100,height:80,fps:30,running:false,handlers:[],resources:[recipe],commands:[{op:'image',resource:'cache-1',x:0,y:0,transform:[1,0,0,1,30,20],clips:[{x:35,y:20,width:10,height:20,transform:[1,0,0,1,0,0]}]}]};
      const view=graphics.createSceneView(scene);document.querySelector('main').append(view.root);const ctx=view.canvas.getContext('2d'),pixel=(x,y)=>[...ctx.getImageData(x,y,1,1).data];
      const out=[pixel(40,25),pixel(32,25),pixel(47,25)];for(let i=0;i<10;i++)view.update(structuredClone(scene));out.push(pixel(40,25));
      view.update({...scene,resources:[],commands:[]});out.push(pixel(40,25));view.dispose();out.push(graphics.backingStorePixels());return out;
    });assert.deepEqual(result,[[255,0,0,128],[0,0,0,0],[0,0,0,0],[255,0,0,128],[0,0,0,0],0]);
  }finally{await p.close();}
});

test('real failed cache or root preparation preserves visible pixels and releases resources',options,async()=>{
  const p=await page();try{
    const result=await p.evaluate(()=>{
      const base={canvas_id:'atomic',width:40,height:40,fps:30,running:false,handlers:[],commands:[{op:'background',color:'#00ff00'}]};const v=graphics.createSceneView(base);document.querySelector('main').append(v.root);
      const prototype=CanvasRenderingContext2D.prototype,original=prototype.fillText;prototype.fillText=function(){throw Error('injected paint failure');};let failed=false;
      try{v.update({...base,commands:[{op:'background',color:'#ff0000'},{op:'text',text:'x',x:0,y:0,size:12,color:'#ffffff'}]});}catch{failed=true;}finally{prototype.fillText=original;}
      const pixel=[...v.canvas.getContext('2d').getImageData(5,5,1,1).data];v.dispose();return {failed,pixel,pixels:graphics.backingStorePixels()};
    });assert.deepEqual(result,{failed:true,pixel:[0,255,0,255],pixels:0});
  }finally{await p.close();}
});

test('real standalone legacy-to-cache failure preserves original pixels and dimensions',options,async()=>{
  const p=await page();try{
    const result=await p.evaluate(()=>{
      const canvas=document.createElement('canvas');document.querySelector('main').append(canvas);
      const scene={canvas_id:'standalone',width:40,height:40,fps:30,running:false,handlers:[],commands:[{op:'background',color:'#00ff00'}]};graphics.drawScene(canvas,scene);
      const prototype=CanvasRenderingContext2D.prototype,original=prototype.fillText;prototype.fillText=function(){throw Error('injected cache failure');};let failed=false;
      try{graphics.drawScene(canvas,{...scene,resources:[{id:'r',kind:'drawing',width:8,height:8,commands:[{op:'text',text:'x',x:0,y:0,size:12,color:'#ffffff'}]}],commands:[{op:'image',resource:'r',x:0,y:0}]});}catch{failed=true;}finally{prototype.fillText=original;}
      const result={failed,width:canvas.width,height:canvas.height,pixel:[...canvas.getContext('2d').getImageData(5,5,1,1).data],backing:graphics.backingStorePixels()};graphics.disposeScene(canvas);result.released=graphics.backingStorePixels();return result;
    });assert.deepEqual(result,{failed:true,width:40,height:40,pixel:[0,255,0,255],backing:1600,released:0});
  }finally{await p.close();}
});
