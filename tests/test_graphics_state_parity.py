"""End-to-end Python/browser-js command contract for drawing state."""
import json
import math
import time
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from rulang.browser_compiler import compile_browser
from rulang.frontend import parse
from rulang.graphics_runtime import GraphicsHost
from rulang.interpreter import Interpreter

NODE = shutil.which('node')
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(NODE, 'Node required for backend parity')
class GraphicsStateParityTests(unittest.TestCase):
    def compare(self, source, inputs=()):
        events = []
        host = GraphicsHost(Interpreter(), events.append)
        try:
            host.interpreter.execute(parse(source))
            host.flush()
            for event in inputs:
                host.handle(event)
            python = [e for e in events if e['type'] == 'graphics']
        finally:
            host.close()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'program.mjs').write_text(compile_browser(source), encoding='utf-8')
            (path / 'run.mjs').write_text(
                "import create from './program.mjs';const events=[];"
                "const runtime=create({emit:e=>events.push(e)});"
                "const canvas_id=events.find(e=>e.type==='graphics').canvas_id;"
                "for(const event of " + json.dumps(inputs) + ")runtime.dispatch({canvas_id,event});"
                "console.log(JSON.stringify(events.filter(e=>e.type==='graphics')));", encoding='utf-8')
            result = subprocess.run([NODE, str(path / 'run.mjs')], text=True,
                                    capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        javascript = json.loads(result.stdout)
        for emitted in (python, javascript):
            for event in emitted:
                del event['canvas_id']
        def compare_value(left, right):
            if isinstance(left, (int, float)) and not isinstance(left, bool):
                self.assertIsInstance(right, (int, float))
                self.assertNotIsInstance(right, bool)
                self.assertTrue(math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12),
                                (left, right))
            elif isinstance(left, dict):
                self.assertEqual(left.keys(), right.keys())
                for key in left:
                    compare_value(left[key], right[key])
            elif isinstance(left, list):
                self.assertEqual(len(left), len(right))
                for a, b in zip(left, right):
                    compare_value(a, b)
            else:
                self.assertEqual(left, right)
        compare_value(python, javascript)
        return python

    def test_all_primitives_nested_state_and_background(self):
        scenes = self.compare("""观 取 外言 '如:观'. 图 取 观 其 画布 320 240.
图 其 保存. 图 其 平移 70 40. 图 其 缩放 2 3.
图 其 裁剪 0 0 70 50. 图 其 保存.
图 其 变换 1 0 0 1 5 7. 图 其 裁剪 0 0 40 30.
图 其 填色 '#ffaa00'. 图 其 描边 空.
图 其 背景 '#ffffff'. 图 其 三角形 0 0 20 0 10 20.
图 其 多边形 [[0,0],[30,0],[30,20],[0,20]].
图 其 矩形 1 2 3 4. 图 其 椭圆 1 2 3 4.
图 其 文字 '变换' 1 2. 图 其 描边 '#000000'. 图 其 线 1 2 3 4.
图 其 恢复. 图 其 矩形 0 0 10 10.
图 其 取消裁剪. 图 其 重置变换. 图 其 矩形 0 0 10 10.
图 其 恢复. 图 其 矩形 0 0 10 10.
""")
        commands = scenes[0]['commands']
        self.assertNotIn('transform', commands[0])
        self.assertEqual(commands[1]['transform'], [2, 0, 0, 3, 80, 61])
        self.assertEqual(len(commands[1]['clips']), 2)
        self.assertNotIn('transform', commands[-1])
        self.assertNotIn('clips', commands[-1])

    def test_callback_resets_geometry_but_preserves_style_and_mouse_coordinates(self):
        scenes = self.compare("""观 取 外言 '如:观'. 图 取 观 其 画布 200 160.
图 其 平移 20 30. 图 其 裁剪 0 0 20 20. 图 其 填色 '#aabbcc'.
图 其 矩形 0 0 20 20.
图 其 每帧 (作 帧:
 图 其 平移 5 6. 图 其 矩形 0 0 10 10.
为).
图 其 鼠标移动 (作 横 纵:
 图 其 矩形 横 纵 10 10.
为).
""", [{'type': 'frame'}, {'type': 'frame'}, {'type': 'mouse_move', 'x': 31, 'y': 42}])
        self.assertEqual(scenes[1]['commands'], scenes[2]['commands'])
        self.assertNotIn('clips', scenes[1]['commands'][0])
        last = scenes[-1]['commands'][0]
        self.assertEqual((last['x'], last['y']), (31, 42))
        self.assertNotIn('transform', last)
        self.assertEqual(last['fill'], '#aabbcc')

    def test_zero_rotation_and_negative_scale(self):
        self.compare("""观 取 外言 '如:观'. 图 取 观 其 画布 100 100.
图 其 旋转 0. 图 其 缩放 (-1) 0.
图 其 多边形 [[0,0],[10,0],[0,10]].
""")

    def test_documented_example_source_and_backends(self):
        source = (ROOT / 'rushu/examples/ruguan/transform-shapes.ru').read_text(encoding='utf-8')
        book = json.loads((ROOT / 'rushu/examples/transform-shapes.rushu.json').read_text(encoding='utf-8'))
        self.assertIn(source, [cell.get('source') for cell in book['cells']])
        self.compare(source, [{'type': 'frame'}, {'type': 'frame'}])


class GraphicsSpawnTransportTests(unittest.TestCase):
    def test_new_example_runs_through_real_spawned_transport(self):
        from rushu.kernel import Session
        def ready(session):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                result = session.poll()
                self.assertFalse([e for e in result['events'] if e['type'] == 'error'], result)
                if result['state'] == 'idle' and not result['graphics_busy']:
                    return result
                time.sleep(.01)
            self.fail('new graphics example did not become ready')
        session = Session()
        try:
            source = (ROOT / 'rushu/examples/ruguan/transform-shapes.ru').read_text(encoding='utf-8')
            session.execute(source, 'shapes')
            result = ready(session)
            self.assertIsNotNone(result['graphics'], result)
            canvas_id = result['graphics']['canvas_id']
            for _ in range(3):
                time.sleep(.06)
                session.dispatch_graphics(canvas_id, 'shapes', 1, 1, {'type': 'frame'})
                result = ready(session)
                self.assertIsNotNone(result['graphics'], result)
                scene = next(e for e in reversed(result['events']) if e['type'] == 'graphics')
                self.assertTrue(any(c['op'] == 'polygon' for c in scene['commands']))
                self.assertTrue(any(c.get('clips') for c in scene['commands']))
            session.dispatch_graphics(canvas_id, 'shapes', 1, 1, {'type': 'close'})
            self.assertIsNone(ready(session)['graphics'])
            session.execute('显 42.', 'after-shapes')
            result = ready(session)
            self.assertTrue(any(e.get('text') == '42\n' for e in result['events']))
        finally:
            session.close()
