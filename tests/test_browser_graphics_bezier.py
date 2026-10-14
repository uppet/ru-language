"""Browser cubic commands, strict coordinates and Python parity."""
from pathlib import Path
import subprocess
import unittest

import test_browser_js
import test_graphics_state_parity

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "观 取 外言 '如:观'. 图 取 观 其 画布 180 120. "


@unittest.skipUnless(test_browser_js.NODE, 'Node required for browser bezier tests')
class BrowserGraphicsBezierTests(unittest.TestCase):
    run_js = test_browser_js.BrowserCompilerTests.run_js
    compare = test_graphics_state_parity.GraphicsStateParityTests.compare

    def test_exact_named_coordinates_extremes_and_degeneracy_match_python(self):
        scenes = self.compare(PREFIX + """
图 其 填色 '#FF000080'. 图 其 描边 '#ABCDEF80'. 图 其 线宽 3.
图 其 贝塞尔 1 2 3 4 5 6 7 8.
图 其 贝塞尔 终纵:8 控二横:5 起横:1 控一纵:4 终横:7 起纵:2 控二纵:6 控一横:3.
图 其 贝塞尔 (-100000) 100000 100000 (-100000) (-100000) 100000 100000 (-100000).
图 其 贝塞尔 0.1 (-0.1) 0.25 (-0.25) 0.5 (-0.5) 0 0.
图 其 贝塞尔 0 0 10 0 (-10) 0 0 0.
图 其 描边 空. 图 其 贝塞尔 0 0 0 0 0 0 0 0.
图 其 矩形 0 0 1 1.
""")
        commands = scenes[0]['commands']
        self.assertEqual(commands[0], commands[1])
        self.assertTrue(all(c['fill'] == '' for c in commands[:-1]))
        self.assertEqual(commands[0]['stroke'], '#abcdef80')
        self.assertEqual(commands[-2]['stroke'], '')
        self.assertEqual(commands[-1]['fill'], '#ff000080')

    def test_snapshots_callback_reset_and_invisible_input_match_python(self):
        scenes = self.compare(PREFIX + """
图 其 描边 '#ff000080'. 图 其 保存. 图 其 平移 10 20. 图 其 裁剪 0 0 50 60.
图 其 变换 1 2 3 4 5 6. 图 其 缩放 (-1) 0. 控 取 30.
图 其 贝塞尔 0 0 控 20 40 20 50 0. 控 取 99.
图 其 恢复. 图 其 贝塞尔 0 0 控 20 40 20 50 0. 图 其 描边 '#ffffff'.
图 其 每帧 (作 帧: 图 其 贝塞尔 0 0 帧 1 10 1 20 0. 图 其 平移 1 2. 为).
图 其 按键 (作 键: 图 其 描边 空. 图 其 贝塞尔 0 0 0 0 0 0 0 0. 为).
""", [{'type': 'frame'}, {'type': 'frame'}, {'type': 'key_down', 'key': 'x'}])
        initial = scenes[0]['commands']
        self.assertEqual(initial[0]['cx1'], 30)
        self.assertEqual(initial[0]['transform'], [-1, -2, 0, 0, 15, 26])
        self.assertEqual(initial[0]['clips'][0]['transform'], [1, 0, 0, 1, 10, 20])
        self.assertEqual(initial[1]['cx1'], 99)
        self.assertNotIn('transform', initial[1])
        for frame in scenes[1:]:
            self.assertEqual(len(frame['commands']), 1)
            self.assertNotIn('transform', frame['commands'][0])
            self.assertNotIn('clips', frame['commands'][0])
        self.assertEqual(scenes[-1]['commands'][0]['stroke'], '')

    def test_return_empty_and_names_are_not_keywords(self):
        events = self.run_js(PREFIX + '贝塞尔 取 3. 起横 取 4. 控一横 取 5. 控二纵 取 6. 终纵 取 7. '
                             '显 贝塞尔 + 起横 + 控一横 + 控二纵 + 终纵. 显 (图 其 贝塞尔 0 0 1 1 2 2 3 3).')
        self.assertFalse([e for e in events if e['type'] == 'error'], events)
        self.assertEqual(''.join(e.get('text', '') for e in events), '25\n空\n')

    def test_compiled_invalid_coordinate_arity_names_and_location(self):
        cases = ['', '0 0 1 1 2 2 3', '0 0 1 1 2 2 3 3 4',
                 '起横:0 起纵:0 控一横:1 控一纵:1 控二横:2 控二纵:2 终横:3',
                 '起横:0 起纵:0 控一横:1 控一纵:1 控二横:2 控二纵:2 终横:3 终纵:3 起横:4',
                 '起横:0 起纵:0 控一横:1 控一纵:1 控二横:2 控二纵:2 终横:3 半径:3']
        for index in range(8):
            for bad in ('真', '空', "'1'", '100001', '(-100001)', '([])'):
                args = ['1'] * 8
                args[index] = bad
                cases.append(' '.join(args))
        for args in cases:
            with self.subTest(args=args):
                events = self.run_js(PREFIX + '\n图 其 贝塞尔 ' + args + '.')
                self.assertEqual(events[-1]['type'], 'error', events)
                self.assertEqual(events[-1]['diagnostic']['line'], 2)
        mixed = test_browser_js.request(PREFIX + '\n图 其 贝塞尔 0 起纵:0 控一横:1 控一纵:1 控二横:2 控二纵:2 终横:3 终纵:3.')
        self.assertIn('不能混用', mixed['error'])
        self.assertEqual(mixed['diagnostic']['line'], 2)

    def test_actual_member_nonfinite_atomicity_and_exact_budgets(self):
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
call(canvas,'平移',1,2);call(canvas,'裁剪',0,0,20,30);
call(canvas,'贝塞尔',0,0,10,20,30,20,40,0);
const before=JSON.stringify(c);
for(let i=0;i<8;i++)for(const bad of [null,true,false,undefined,NaN,Infinity,-Infinity,[],{},'1',100001,-100001]){
 const args=Array(8).fill(1);args[i]=bad;
 assert.throws(()=>call(canvas,'贝塞尔',...args));assert.equal(JSON.stringify(c),before);
}
const n=c.bytes;c.commands=Array(2048).fill(c.commands[0]);
assert.throws(()=>call(canvas,'贝塞尔',...Array(8).fill(0)),/2048/);assert.equal(c.commands.length,2048);assert.equal(c.bytes,n);
c.commands=[];c.bytes=2;call(canvas,'描边',null);call(canvas,'贝塞尔',...Array(8).fill(0));
assert.equal(c.commands[0].fill,'');assert.equal(c.commands[0].stroke,'');
const size=c.bytes-2;c.commands=[];c.bytes=261120-size;
call(canvas,'贝塞尔',...Array(8).fill(0));assert.equal(c.bytes,261120);assert.equal(c.commands.length,1);
c.commands=[];c.bytes=261121-size;
assert.throws(()=>call(canvas,'贝塞尔',...Array(8).fill(0)),/256 KiB/);assert.equal(c.commands.length,0);assert.equal(c.bytes,261121-size);
console.log('atomic');
"""
        result = subprocess.run([test_browser_js.NODE, '-e', prelude + runtime + checks], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'atomic\n')
