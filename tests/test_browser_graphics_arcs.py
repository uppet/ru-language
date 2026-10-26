"""Browser/Python arc command parity, validation and atomic resource failures."""
from pathlib import Path
import subprocess
import unittest

import test_browser_js
import test_graphics_state_parity

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "观 取 外言 '如:观'. 图 取 观 其 画布 160 120. "


@unittest.skipUnless(test_browser_js.NODE, 'Node required for browser arcs')
class BrowserGraphicsArcTests(unittest.TestCase):
    run_js = test_browser_js.BrowserCompilerTests.run_js
    compare = test_graphics_state_parity.GraphicsStateParityTests.compare

    def test_exact_signatures_raw_angles_empty_styles_and_python_parity(self):
        frames = self.compare(PREFIX + """
图 其 填色 '#ABCDEF80'. 图 其 描边 '#12345678'. 图 其 线宽 3.
图 其 弧 1 2 30 40 5.8 1.
图 其 扇形 转角: (-2) 高: 40 始角: (-1) 宽: 30 纵: 2 横: 1.
图 其 弧 (-100000) 100000 0 0 100000 0.
图 其 扇形 0 0 100000 0 (-100000) (-100000).
图 其 弧 0 0 0 100000 (-100000) 100000.
图 其 弧 0 0 20 30 0 6.283185307179586.
图 其 扇形 0 0 20 30 0 (-6.283185307179586).
图 其 填色 空. 图 其 描边 空. 图 其 弧 0 0 0 0 0 0. 图 其 扇形 0 0 0 0 0 0.
""")
        commands = frames[0]['commands']
        self.assertEqual([c['op'] for c in commands[:2]], ['arc', 'sector'])
        self.assertEqual(commands[0]['fill'], '')
        self.assertEqual(commands[1]['fill'], '#abcdef80')
        self.assertEqual(commands[2]['start'], 100000)
        self.assertEqual(commands[2]['sweep'], 0)
        self.assertEqual(commands[-1]['stroke'], '')

    def test_signed_geometry_snapshots_reset_and_zero_input_scene_parity(self):
        frames = self.compare(PREFIX + """
图 其 填色 '#ff000080'. 图 其 保存. 图 其 平移 10 20.
图 其 裁剪 0 0 20 30. 图 其 变换 1 2 3 4 5 6. 图 其 缩放 (-1) 0.
图 其 扇形 0 0 10 10 0 1. 图 其 弧 0 0 10 10 0 (-1). 图 其 恢复.
图 其 扇形 0 0 10 10 0 1. 图 其 填色 '#FFFFFF'.
图 其 每帧 (作 帧: 图 其 扇形 0 0 20 30 0 1. 图 其 平移 1 2. 为).
图 其 按键 (作 键: 图 其 弧 0 0 10 10 0 0. 为).
""", [{'type': 'frame'}, {'type': 'frame'}, {'type': 'key_down', 'key': 'x'}])
        initial = frames[0]['commands']
        self.assertEqual(initial[0]['transform'], [-1, -2, 0, 0, 15, 26])
        self.assertEqual(initial[0]['clips'][0]['transform'], [1, 0, 0, 1, 10, 20])
        self.assertEqual(initial[0]['fill'], '#ff000080')
        self.assertNotIn('transform', initial[2])
        self.assertEqual(frames[1]['commands'], frames[2]['commands'])
        self.assertNotIn('transform', frames[1]['commands'][0])
        self.assertEqual(len(frames[-1]['commands']), 1)
        self.assertEqual(frames[-1]['commands'][0]['op'], 'arc')

    def test_return_empty_and_ordinary_identifiers(self):
        events = self.run_js(PREFIX + '弧 取 3. 扇形 取 4. 始角 取 5. 转角 取 6. '
                             '显 弧 + 扇形 + 始角 + 转角. 显 (图 其 弧 0 0 2 2 0 1). 显 (图 其 扇形 0 0 2 2 0 1).')
        self.assertFalse([e for e in events if e['type'] == 'error'], events)
        self.assertEqual(''.join(e.get('text', '') for e in events), '18\n空\n空\n')

    def test_compiled_bad_arity_names_types_and_diagnostics(self):
        cases = ['', '0 0 1 1 0', '0 0 1 1 0 1 2', '0 0 (-1) 1 0 1', '0 0 1 (-1) 0 1',
                 '横:0 纵:0 宽:1 高:1 始角:0 终角:1', '横:0 纵:0 宽:1 高:1 始角:0',
                 '横:0 纵:0 宽:1 高:1 始角:0 转角:1 横:0']
        for name in ('弧', '扇形'):
            mixed = test_browser_js.request(PREFIX + '\n图 其 ' + name + ' 0 纵:0 宽:1 高:1 始角:0 转角:1.')
            self.assertIn('不能混用', mixed['error'])
            self.assertEqual(mixed['diagnostic']['line'], 2)
            for args in cases:
                with self.subTest(name=name, args=args):
                    events = self.run_js(PREFIX + '\n图 其 ' + name + ' ' + args + '.')
                    self.assertEqual(events[-1]['type'], 'error', events)
                    self.assertIn('diagnostic', events[-1])
            for index in range(6):
                for bad in ('真', '空', "'1'", '100001'):
                    args = ['1'] * 6
                    args[index] = bad
                    with self.subTest(name=name, index=index, bad=bad):
                        events = self.run_js(PREFIX + '\n图 其 ' + name + ' ' + ' '.join(args) + '.')
                        self.assertEqual(events[-1]['type'], 'error', events)
                        self.assertEqual(events[-1]['diagnostic']['line'], 2)

    def test_actual_member_atomic_nonfinite_failures_and_budgets(self):
        runtime = (ROOT / 'rulang/browser_runtime.js').read_text(encoding='utf-8')
        prelude = """
const assert=require('node:assert/strict');
const dict=()=>Object.create(null),own=(o,k)=>Object.hasOwn(o,k),MISSING=Symbol();
const builtins={values:dict()},__ruHost={emit:()=>{}};
const builtin=(name,fields,kind,key)=>({[key]:kind});
class Instance{constructor(type,fields){this.type=type;this.fields=fields;}} class Fn{}
const fail=(m,message)=>{throw new Error(message);};
const argsBind=(m,name,args,params)=>Object.fromEntries(params.map((key,i)=>[key,args[i][1]]));
"""
        checks = """
const m={},call=(receiver,name,...args)=>browserMember(m,receiver,name,args.map(x=>[null,x]),[1,1]);
const canvas=call(builtins.values.__如观,'画布',100,80),c=canvas.graphicsCanvas;
call(canvas,'平移',1,2);call(canvas,'裁剪',0,0,20,30);call(canvas,'扇形',0,0,20,30,0,1);
const before=JSON.stringify(c);const originalBytes=c.bytes;
for(const name of ['弧','扇形'])for(const bad of [null,true,false,NaN,Infinity,-Infinity,[],{},'1',100001,-100001]){
 for(let i=0;i<6;i++){const args=[1,1,1,1,1,1];args[i]=bad;
  assert.throws(()=>call(canvas,name,...args),/有限数/);assert.equal(JSON.stringify(c),before);
 }
}
// Inject boundary state to isolate count and byte accounting without altering constants.
c.commands=Array(2048).fill(c.commands[0]);c.bytes=originalBytes;
assert.throws(()=>call(canvas,'弧',0,0,0,0,0,0),/2048/);assert.equal(c.commands.length,2048);assert.equal(c.bytes,originalBytes);
c.commands=[];c.bytes=261119;
assert.throws(()=>call(canvas,'扇形',0,0,0,0,0,0),/256 KiB/);assert.equal(c.commands.length,0);assert.equal(c.bytes,261119);
c.bytes=2;call(canvas,'描边',null);call(canvas,'弧',0,0,0,0,0,0);
assert.equal(c.commands.length,1);assert.equal(c.commands[0].sweep,0);assert.equal(c.commands[0].fill,'');assert.ok(c.bytes>2);
console.log('atomic');
"""
        result = test_browser_js.run_source(prelude + runtime + checks)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'atomic\n')
