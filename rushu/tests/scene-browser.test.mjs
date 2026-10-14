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
