"""Immutable browser drawing resources, phase isolation and exact closure budgets."""
from pathlib import Path
import subprocess
import unittest

import test_browser_js

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "观 取 外言 '如:观'. 图 取 观 其 画布 180 120. "


@unittest.skipUnless(test_browser_js.NODE, 'Node required for browser cache tests')
class BrowserGraphicsCacheTests(unittest.TestCase):
    run_js = test_browser_js.BrowserCompilerTests.run_js

    def test_build_once_named_return_and_self_contained_frames(self):
        events = self.run_js(PREFIX + """
次数 取 [0]. 点 取 [[0,0],[3,4]].
图 其 填色 '#abcdef'. 图 其 平移 90 90.
像 取 图 其 缓存 宽:20 高:30 绘制:(作 层:
 次数[0] 取 次数[0] + 1.
 层 其 折线 点. 层 其 填色 '#ff000080'. 层 其 椭圆 1 2 3 4.
为).
点[0][0] 取 99.
显 像 其 宽. 显 像 其 高.
图 其 每帧 (作 帧: 图 其 贴图 图像:像 横:帧 纵:0. 图 其 贴图 像 0 0. 显 次数[0]. 为).
""", "const canvas_id=events.at(-1).canvas_id;for(let i=0;i<3;i++)runtime.dispatch({canvas_id,event:{type:'frame'}});")
        self.assertFalse([e for e in events if e['type'] == 'error'], events)
        self.assertEqual(''.join(e.get('text', '') for e in events), '20\n30\n1\n1\n1\n')
        scenes = [e for e in events if e['type'] == 'graphics']
        self.assertNotIn('resources', scenes[0])
        for scene in scenes[1:]:
            self.assertEqual(len(scene['resources']), 1)
            self.assertEqual(len(scene['commands']), 2)
            recipe = scene['resources'][0]
            self.assertEqual(recipe['commands'][0]['points'][0], [0, 0])
            self.assertNotIn('transform', recipe['commands'][0])
            self.assertEqual(recipe['commands'][1]['fill'], '#ff000080')
            self.assertNotIn('width', scene['commands'][0])

    def test_input_retains_closure_background_and_empty_frame_remove_it(self):
        events = self.run_js(PREFIX + """
像 取 图 其 缓存 8 8 (作 层: 层 其 背景 '#000000'. 为).
图 其 贴图 像 0 0.
图 其 每帧 (作 帧: 为).
图 其 按键 (作 键: 图 其 填色 '#ffffff'. 为).
图 其 松键 (作 键: 图 其 背景 '#ffffff'. 为).
""", "const canvas_id=events.at(-1).canvas_id;for(const event of [{type:'key_down',key:'x'},{type:'key_up',key:'x'},{type:'frame'}])runtime.dispatch({canvas_id,event});")
        self.assertFalse([e for e in events if e['type'] == 'error'], events)
        scenes = [e for e in events if e['type'] == 'graphics']
        self.assertEqual(scenes[0]['resources'], scenes[1]['resources'])
        self.assertNotIn('resources', scenes[2])
        self.assertNotIn('resources', scenes[3])
        self.assertEqual(scenes[3]['commands'], [])

    def test_event_phase_cannot_be_bypassed_by_replacing_canvas(self):
        for body in ("图 其 缓存 1 1 (作 层: 为).",
                     "新图 取 观 其 画布 5 5. 新图 其 缓存 1 1 (作 层: 为)."):
            for registration, event in (("按键", "{type:'key_down',key:'x'}"),
                                        ("每帧", "{type:'frame'}")):
                with self.subTest(body=body, registration=registration):
                    events = self.run_js(PREFIX + f'图 其 {registration} (作 值: {body} 为).',
                        f"const canvas_id=events.at(-1).canvas_id;runtime.dispatch({{canvas_id,event:{event}}});")
                    self.assertEqual(events[-1]['type'], 'error', events)
                    self.assertIn('初始化', events[-1]['message'])

    def test_compiled_rejects_invalid_api_and_escaped_recorder(self):
        cases = ['图 其 缓存 真 1 (作 层: 为).', '图 其 缓存 1.5 1 (作 层: 为).',
                 '图 其 缓存 0 1 (作 层: 为).', '图 其 缓存 2049 1 (作 层: 为).',
                 '图 其 缓存 1 1 3.', '图 其 缓存 1 1 (作: 为).',
                 '图 其 贴图 空 0 0.', '图 其 缓存 1 1 (作 层: 层 其 保存. 为).',
                 '留 取 [空]. 图 其 缓存 1 1 (作 层: 留[0] 取 层. 为). 留[0] 其 宽.',
                 '像 取 图 其 缓存 1 1 (作 层: 为). 新图 取 观 其 画布 5 5. 新图 其 贴图 像 0 0.']
        for operation in ('图 其 填色 空.', '图 其 关闭.', '观 其 画布 5 5.',
                          '图 其 缓存 1 1 (作 另层: 为).', '层 其 贴图 空 0 0.',
                          '层 其 经过秒.', '层 其 每帧 (作 帧: 为).'):
            cases.append(f'图 其 缓存 1 1 (作 层: {operation} 为).')
        for code in cases:
            with self.subTest(code=code):
                events = self.run_js(PREFIX + code)
                self.assertEqual(events[-1]['type'], 'error', events)

    def test_python_browser_protocol_parity(self):
        from rulang.frontend import parse
        from rulang.graphics_runtime import GraphicsHost
        from rulang.interpreter import Interpreter
        source = PREFIX + """
像 取 图 其 缓存 20 30 (作 层:
 层 其 填色 '#ff000080'. 层 其 保存. 层 其 平移 1 2.
 层 其 裁剪 0 0 10 10. 层 其 扇形 1 2 3 4 0 2.
 层 其 恢复. 层 其 折线 [[0,0],[3,4]].
 层 其 贝塞尔 0 0 1 2 3 4 5 6. 为).
图 其 每帧 (作 帧: 图 其 保存. 图 其 缩放 2 2.
 图 其 贴图 像 帧 0. 图 其 恢复. 为).
"""
        browser = self.run_js(source, "const canvas_id=events.at(-1).canvas_id;for(let i=0;i<3;i++)runtime.dispatch({canvas_id,event:{type:'frame'}});")
        python = []
        interpreter = Interpreter()
        host = GraphicsHost(interpreter, python.append)
        try:
            interpreter.execute(parse(source))
            host.flush()
            for _ in range(3):
                host.handle({'type': 'frame'})
        finally:
            host.close()
        def scenes(events):
            return [{key: value for key, value in event.items() if key != 'canvas_id'}
                    for event in events if event['type'] == 'graphics']
        self.assertEqual(scenes(python), scenes(browser))

    def test_function_return_is_ignored_and_empty_cache_is_drawable(self):
        events = self.run_js(PREFIX + "像 取 图 其 缓存 7 9 (算 层: 得 123. 法). 图 其 贴图 像 0 0. 显 像 其 宽.")
        self.assertFalse([event for event in events if event['type'] == 'error'], events)
        self.assertEqual(''.join(event.get('text', '') for event in events), '7\n')
        scene = [event for event in events if event['type'] == 'graphics'][-1]
        self.assertEqual(scene['resources'][0]['commands'], [])

    def test_runtime_transaction_immutability_lifetime_and_budgets(self):
        runtime = (ROOT / 'rulang/browser_runtime.js').read_text(encoding='utf-8')
        prelude = """
const assert=require('node:assert/strict');
const NativeEncoder=TextEncoder;let fullFrameEncodings=0;
globalThis.TextEncoder=class extends NativeEncoder{encode(value){if(value.includes('"type":"graphics"')&&value.includes('"resources"'))fullFrameEncodings++;return super.encode(value);}};
const dict=()=>Object.create(null),own=(o,k)=>Object.hasOwn(o,k),MISSING=Symbol();
const emitted=[],builtins={values:dict()},__ruHost={emit:e=>emitted.push(e)};
const builtin=(name,fields,kind,key)=>({[key]:kind});
class Instance{constructor(type,fields){this.type=type;this.fields=fields;}}
class Fn{constructor(body){this.body=body;this.params=['target'];}}
const fail=(m,message)=>{throw new Error(message);};
const argsBind=(m,name,args,params)=>Object.fromEntries(params.map((key,i)=>[key,args[i][1]]));
const call=(m,fn,args)=>fn.body(args[0][1]);
"""
        checks = """
const m={},member=(r,n,...args)=>browserMember(m,r,n,args.map(v=>[null,v]),[1,1]);
const canvas=member(builtins.values.__如观,'画布',100,80),c=canvas.graphicsCanvas;
member(canvas,'背景','#010203');member(canvas,'填色','#abcdef');browserFlush();
const before=JSON.stringify(c.commands);let escaped,record;
assert.throws(()=>member(canvas,'缓存',1,1,new Fn(target=>{escaped=target;record=target.graphicsCanvas;member(target,'保存');})),/配对/);
assert.equal(browserCanvas,c);assert.equal(c.resources.size,0);assert.equal(c.resourcePixels,0);
assert.equal(JSON.stringify(c.commands),before);assert.equal(c.fill,'#abcdef');
assert.equal(escaped.graphicsCanvas,null);assert.equal(record.closed,true);assert.deepEqual(record.commands,[]);assert.deepEqual(record.stack,[]);
const img=member(canvas,'缓存',1,1,new Fn(target=>member(target,'背景','#aabbcc')));
assert.equal(m.lastMemberProcedure,false);assert.deepEqual(Object.keys(img.graphicsImage).sort(),['height','id','owner','token','width']);
const recipe=c.resources.get('cache-1');assert.ok(Object.isFrozen(recipe));assert.ok(Object.isFrozen(recipe.commands[0]));
member(canvas,'贴图',img,1,2);member(canvas,'贴图',img,3,4);browserFlush();
const saved=emitted.at(-1);assert.equal(saved.resources.length,1);
browserResetCommands(c);fullFrameEncodings=0;
member(canvas,'贴图',img,0,0);
for(let i=0;i<10;i++)member(canvas,'矩形',i,0,1,1);
assert.equal(fullFrameEncodings,0);browserFlush();assert.equal(fullFrameEncodings,1);
assert.equal(c.referenceIds.size,1);assert.equal(c.referenceCommands,1);
assert.equal(c.referenceBytes,browserEncoder.encode(JSON.stringify(recipe)).length);
member(canvas,'背景','#ffffff');assert.equal(c.referenceIds.size,0);assert.equal(c.referenceBytes,0);assert.equal(c.referenceCommands,0);
member(canvas,'贴图',img,0,0);member(canvas,'贴图',img,1,0);
assert.equal(c.referenceIds.size,1);assert.equal(c.referenceCommands,1);
// Exact incremental candidate bytes must agree with the full event boundary.
const candidate={op:'text',text:'',x:0,y:0,color:'#ffffff',size:16};
const candidateBytes=()=>browserEncoder.encode(JSON.stringify(candidate)).length+1;
const exact=browserEncoder.encode(JSON.stringify(browserScene(c,[...c.commands,candidate]))).length;
candidate.text='字'.repeat(Math.floor((262144-exact)/3))+'x'.repeat((262144-exact)%3);
assert.equal(browserEncoder.encode(JSON.stringify(browserScene(c,[...c.commands,candidate]))).length,262144);
browserCheckCommand(c,candidate,candidateBytes(),m,[1,1]);
candidate.text+='x';assert.throws(()=>browserCheckCommand(c,candidate,candidateBytes(),m,[1,1]),/256 KiB/);
c.commands=Array(2047).fill({op:'image',resource:'cache-1',x:0,y:0});c.bytes=2;
assert.throws(()=>member(canvas,'贴图',img,0,0),/2048/);assert.equal(c.commands.length,2047);
browserResetCommands(c);
// Bound UTF-8 recipe bytes include complete resource/list wrappers.
const text='字'.repeat(4096);
assert.throws(()=>member(canvas,'缓存',1,1,new Fn(target=>{for(let i=0;i<20;i++)member(target,'文字',text,0,0);})),/128 KiB/);
assert.equal(c.resources.size,1);assert.equal(c.resourcePixels,1);
for(let i=0;i<7;i++)member(canvas,'缓存',1,1,new Fn(()=>{}));
assert.throws(()=>member(canvas,'缓存',1,1,new Fn(()=>{})),/8/);
browserClose();assert.equal(c.resources.size,0);assert.equal(saved.resources[0].commands.length,1);
assert.equal(member(img,'宽'),1);
const next=member(builtins.values.__如观,'画布',100,80);
assert.throws(()=>member(next,'贴图',img,0,0),/有效/);
member(next,'缓存',2048,2048,new Fn(()=>{}));
assert.throws(()=>member(next,'缓存',1,1,new Fn(()=>{})),/像素/);
browserClose();const budget=member(builtins.values.__如观,'画布',100,80);
const dense=member(budget,'缓存',1,1,new Fn(target=>{member(target,'填色',null);for(let i=0;i<2047;i++)member(target,'文字','',0,0);}));
member(budget,'贴图',dense,0,0);browserFlush();
assert.equal(emitted.at(-1).resources[0].commands.length,2047);
browserClose();const capacity=member(builtins.values.__如观,'画布',100,80);
assert.throws(()=>member(capacity,'缓存',1,1,new Fn(target=>{member(target,'填色',null);for(let i=0;i<2048;i++)member(target,'文字','',0,0);})),/2047/);
assert.equal(capacity.graphicsCanvas.resources.size,0);
for(let j=0;j<2;j++)member(capacity,'缓存',1,1,new Fn(target=>{member(target,'填色',null);for(let i=0;i<1100;i++)member(target,'文字','',0,0);}));
assert.equal(capacity.graphicsCanvas.resources.size,2);
// Exact complete-event byte boundary, measured with UTF-8 rather than JS length.
const scene=browserScene(capacity.graphicsCanvas,[]);
scene.commands.push({op:'text',x:0,y:0,text:'',color:'',size:16});
const overhead=browserEncoder.encode(JSON.stringify(scene)).length;
scene.commands[0].text='x'.repeat(262144-overhead);
assert.equal(browserEncoder.encode(JSON.stringify(scene)).length,262144);
browserCheckScene(capacity.graphicsCanvas,scene,m,[1,1]);scene.commands[0].text+='x';
assert.throws(()=>browserCheckScene(capacity.graphicsCanvas,scene,m,[1,1]),/256 KiB/);
console.log('cache-ok');
"""
        result = test_browser_js.run_source(prelude + runtime + checks)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'cache-ok\n')
