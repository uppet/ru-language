import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';

test('standalone legacy to cache preparation preserves the committed visible backing on failure',()=>{
  // The standalone public API owns its lifetime; an isolated module/process
  // keeps its retained visible backing separate from view-ledger tests.
  const sceneURL=new URL('../static/scene.mjs',import.meta.url).href;
  const result=spawnSync(process.execPath,['--input-type=module','-e',`
    import assert from 'node:assert/strict';
    import {drawScene,disposeScene,createSceneView,backingStorePixels} from ${JSON.stringify(sceneURL)};
    class Canvas {
      constructor(doc){this.ownerDocument=doc;this._w=0;this._h=0;this.pixels='empty';this.ctx={save(){},restore(){},setTransform(){},clearRect:()=>{this.pixels='empty'},fillRect:()=>{if(doc.fail)throw Error('resource raster failure');this.pixels=this.ctx.fillStyle},drawImage:c=>{this.pixels=c.pixels}};}
      set width(v){this._w=v;this.pixels='empty'} get width(){return this._w}
      set height(v){this._h=v;this.pixels='empty'} get height(){return this._h}
      getContext(){return this.ownerDocument.nullContext?null:this.ctx;}
      append(){} setAttribute(){} addEventListener(){} removeEventListener(){}
    }
    const doc={fail:false,createElement(){return new Canvas(this)}},canvas=new Canvas(doc);
    const old={canvas_id:'c',width:8,height:8,fps:30,running:false,handlers:[],commands:[{op:'background',color:'#ff0000'}]};
    drawScene(canvas,old);
    const next={...old,commands:[{op:'image',resource:'r',x:0,y:0}],resources:[{id:'r',kind:'drawing',width:1,height:1,commands:[{op:'background',color:'#00ff00'}]}]};
    doc.fail=true;assert.throws(()=>drawScene(canvas,next),/raster/);
    assert.equal(canvas.pixels,'#ff0000');assert.equal(canvas.width,8);assert.equal(canvas.height,8);assert.equal(backingStorePixels(),64);
    doc.fail=false;doc.nullContext=true;assert.throws(()=>drawScene(canvas,next));
    assert.equal(canvas.pixels,'#ff0000');assert.equal(canvas.width,8);assert.equal(backingStorePixels(),64);
    doc.nullContext=false;drawScene(canvas,next);assert.equal(canvas.pixels,'#00ff00');assert.equal(backingStorePixels(),129);
    disposeScene(canvas);assert.equal(backingStorePixels(),0);assert.equal(canvas.width,0);
    drawScene(canvas,next);assert.equal(canvas.pixels,'#00ff00');assert.equal(backingStorePixels(),129);
    disposeScene(canvas);disposeScene(canvas);assert.equal(backingStorePixels(),0);
    drawScene(canvas,old);disposeScene(canvas);assert.equal(canvas.width,0);assert.equal(backingStorePixels(),0);
    // Pin other real view mains so candidate reservation must fail without
    // reclaiming this standalone frame or allocating candidate pixels.
    globalThis.document=doc;doc.addEventListener=()=>{};doc.removeEventListener=()=>{};
    const large={...old,width:2048,height:2048};
    const first=createSceneView({...large,canvas_id:'first'},{historical:true});
    const second=createSceneView({...large,canvas_id:'second'},{historical:true});
    first.pinBacking(true);second.pinBacking(true);
    const retained=new Canvas(doc);drawScene(retained,{...large,canvas_id:'retained'});
    const rejected={...large,canvas_id:'retained',commands:[{op:'image',resource:'big',x:0,y:0}],resources:[{id:'big',kind:'drawing',width:2048,height:2048,commands:[]}]};
    assert.throws(()=>drawScene(retained,rejected),/预算不足/);
    assert.equal(retained.pixels,'#ff0000');assert.equal(retained.width,2048);assert.equal(retained.height,2048);
    assert.equal(backingStorePixels(),3*2048*2048);
    first.pinBacking(false);second.pinBacking(false);first.dispose();second.dispose();
    assert.equal(backingStorePixels(),2048*2048);disposeScene(retained);assert.equal(backingStorePixels(),0);
  `],{encoding:'utf8'});
  assert.equal(result.status,0,result.stdout+result.stderr);
});
