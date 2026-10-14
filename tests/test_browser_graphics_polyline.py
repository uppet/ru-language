"""Browser polyline command parity, dense point validation and atomic limits."""
from pathlib import Path
import subprocess
import unittest

import test_browser_js
import test_graphics_state_parity

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "观 取 外言 '如:观'. 图 取 观 其 画布 180 120. "


@unittest.skipUnless(test_browser_js.NODE, 'Node required for browser polyline tests')
class BrowserGraphicsPolylineTests(unittest.TestCase):
    run_js = test_browser_js.BrowserCompilerTests.run_js
    compare = test_graphics_state_parity.GraphicsStateParityTests.compare

    def test_named_points_deep_copy_alpha_and_degenerate_parity(self):
        scenes = self.compare(PREFIX + """
图 其 填色 '#FF000080'. 图 其 描边 '#ABCDEF80'. 图 其 线宽 3.
点 取 [[1,2],[3,4],[5,6]]. 图 其 折线 点阵:点.
点[0][0] 取 99. 点[1] 取 [7,8]. 点 其 增 [9,10].
图 其 折线 点. 图 其 折线 [[-100000,100000],[100000,-100000]].
图 其 描边 空. 图 其 折线 [[0,0],[0,0],[0,0]].
""")
        commands = scenes[0]['commands']
        self.assertEqual(commands[0]['points'], [[1, 2], [3, 4], [5, 6]])
        self.assertEqual(commands[1]['points'], [[99, 2], [7, 8], [5, 6], [9, 10]])
        self.assertTrue(all(c['fill'] == '' for c in commands))
        self.assertEqual(commands[0]['stroke'], '#abcdef80')
        self.assertEqual(commands[-1]['stroke'], '')

    def test_full_vertex_limit_and_state_snapshots_match_python(self):
        points = ','.join(f'[{i},{i % 2}]' for i in range(256))
        scenes = self.compare(PREFIX + f"""
点 取 [{points}]. 图 其 折线 点.
图 其 描边 '#ff000080'. 图 其 保存. 图 其 平移 10 20. 图 其 裁剪 0 0 50 60.
图 其 变换 1 2 3 4 5 6. 图 其 缩放 (-1) 0. 图 其 折线 [[0,0],[2,3],[4,0]].
图 其 恢复. 图 其 折线 [[0,0],[1,1]]. 图 其 描边 '#ffffff'.
图 其 每帧 (作 帧: 图 其 折线 [[0,0],[帧,1]]. 图 其 平移 1 2. 为).
图 其 按键 (作 键: 图 其 描边 空. 图 其 折线 [[0,0],[0,0]]. 为).
""", [{'type': 'frame'}, {'type': 'frame'}, {'type': 'key_down', 'key': 'x'}])
        initial = scenes[0]['commands']
        self.assertEqual(len(initial[0]['points']), 256)
        self.assertEqual(initial[1]['transform'], [-1, -2, 0, 0, 15, 26])
        self.assertEqual(initial[1]['clips'][0]['transform'], [1, 0, 0, 1, 10, 20])
        self.assertNotIn('transform', initial[2])
        for frame in scenes[1:]:
            self.assertEqual(len(frame['commands']), 1)
            self.assertNotIn('transform', frame['commands'][0])
            self.assertNotIn('clips', frame['commands'][0])
        self.assertEqual(scenes[-1]['commands'][0]['stroke'], '')

    def test_return_empty_and_names_remain_ordinary(self):
        events = self.run_js(PREFIX + '折线 取 3. 点阵 取 4. 显 折线 + 点阵. 显 (图 其 折线 [[0,0],[1,1]]).')
        self.assertFalse([e for e in events if e['type'] == 'error'], events)
        self.assertEqual(''.join(e.get('text', '') for e in events), '7\n空\n')

    def test_compiled_invalid_points_arity_names_and_diagnostics(self):
        cases = ['图 其 折线.', '点 取 [[0,0],[1,1]]. 图 其 折线 点 点.',
                 '图 其 折线 点:[[0,0],[1,1]].', '图 其 折线 点阵:[[0,0],[1,1]] 点阵:[[0,0],[1,1]].',
                 '观 其 折线 [[0,0],[1,1]].']
        for points in ('空', '真', "'points'", '([])', '[[0,0]]', '[0,1]', '[[0],[1,1]]',
                       '[[0,0,0],[1,1]]', '[[0,0],[真,1]]', "[[0,0],['1',1]]", '[[0,0],[100001,1]]',
                       '[' + ','.join('[0,0]' for _ in range(257)) + ']'):
            cases.append('图 其 折线 ' + points + '.')
        for call in cases:
            with self.subTest(call=call):
                events = self.run_js(PREFIX + '\n' + call)
                self.assertEqual(events[-1]['type'], 'error', events)
                self.assertEqual(events[-1]['diagnostic']['line'], 2)
        mixed = test_browser_js.request(PREFIX + '图 其 折线 [[0,0],[1,1]] 点阵:[[0,0],[1,1]].')
        self.assertIn('不能混用', mixed['error'])

    def test_actual_members_reject_sparse_nonfinite_arrays_atomically(self):
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
const points=[[0,0],[10,20],[20,0]];call(canvas,'折线',points);
points[0][0]=99;points[1]=[30,40];points.push([50,60]);
assert.deepEqual(c.commands[0].points,[[0,0],[10,20],[20,0]]);
const before=JSON.stringify(c);
const hole=[, [1,1],[2,2]],inherited=Object.setPrototypeOf([,[1,1],[2,2]],[[0,0]]);
const inner=Object.setPrototypeOf([,0],[0]);
for(const name of ['折线','多边形']){
 const invalid=[null,true,false,'points',{},new Float64Array(6),[],[[0,0]],Array(257).fill([0,0]),
  hole,inherited,[[0,0],inner,[2,2]],[[0,0],new Array(2),[2,2]],[[0,0],new Float64Array([1,1]),[2,2]],
  [[0,0],[1],[2,2]],[[0,0],[1,1,1],[2,2]],[[0,0],null,[2,2]]];
 for(const bad of [null,true,false,NaN,Infinity,-Infinity,[],{},'1',100001,-100001])invalid.push([[0,0],[bad,1],[2,2]],[[0,0],[1,bad],[2,2]]);
 for(const bad of invalid){assert.throws(()=>call(canvas,name,bad));assert.equal(JSON.stringify(c),before);}
}
const n=c.bytes;c.commands=Array(2048).fill(c.commands[0]);
assert.throws(()=>call(canvas,'折线',[[0,0],[0,0]]),/2048/);assert.equal(c.commands.length,2048);assert.equal(c.bytes,n);
c.commands=[];c.bytes=261119;
assert.throws(()=>call(canvas,'折线',[[0,0],[0,0]]),/256 KiB/);assert.equal(c.commands.length,0);assert.equal(c.bytes,261119);
c.bytes=2;call(canvas,'描边',null);call(canvas,'折线',[[0,0],[0,0]]);
assert.equal(c.commands.length,1);assert.equal(c.commands[0].fill,'');assert.equal(c.commands[0].stroke,'');assert.ok(c.bytes>2);
console.log('atomic');
"""
        result = subprocess.run([test_browser_js.NODE, '-e', prelude + runtime + checks], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'atomic\n')
