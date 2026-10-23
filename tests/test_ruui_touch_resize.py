"""如UI 触屏多点事件与窗口缩放回路：双端行为与校验测试。"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
sys.path.insert(0, str(ROOT))

from rulang.browser_compiler import compile_browser
from rulang.frontend import RuError, parse
from rulang.graphics_runtime import GraphicsHost
from rulang.interpreter import Interpreter

COUNTER = """
尽取 外言 '如UI'.

数 取 [0].
机 取 新 应用 宽: 360 高: 640 构: (算:
    得 列 [
        (文 '触屏'),
        (文 (数[0] 为 句)),
        (钮 '加' (作:
            数[0] 取 数[0] + 1.
            为))
    ].
法).
机 其 运行.
"""

SPLITS = """
尽取 外言 '如UI'.

机 取 新 应用 宽: 360 高: 640 构: (算:
    得 (行 [
        (充 (块 '#ff5a5a' 100)),
        (充 (块 '#40c060' 100))
    ]).
法).
机 其 运行.
"""


def run_python(source, inputs=()):
    events = []
    host = GraphicsHost(Interpreter(), events.append)
    try:
        host.interpreter.execute(parse(source))
        host.flush()
        for event in inputs:
            host.handle(event)
        return [e for e in events if e['type'] == 'graphics']
    finally:
        host.close()


def run_javascript(source, inputs=()):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'program.mjs').write_text(compile_browser(source), encoding='utf-8')
        (path / 'run.mjs').write_text(
            "import create from './program.mjs';const events=[];"
            "const runtime=create({emit:e=>events.push(e)});"
            "const canvas_id=events.find(e=>e.type==='graphics').canvas_id;"
            + "for(const event of " + json.dumps(inputs)
            + ")runtime.dispatch({canvas_id,event});"
            + "console.log(JSON.stringify(events.filter(e=>e.type==='graphics')));",
            encoding='utf-8')
        result = subprocess.run([NODE, str(path / 'run.mjs')], text=True,
                                capture_output=True, timeout=15)
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def texts(commands):
    return [c['text'] for c in commands if c.get('op') == 'text']


def button_pos(events):
    rect = events[-1]['commands']
    hit = [c for c in rect if c.get('op') == 'rect' and c.get('fill') == '#4677ff']
    assert hit, rect
    return hit[0]['x'] + hit[0]['width'] / 2, hit[0]['y'] + hit[0]['height'] / 2


def blocks(commands):
    return [c for c in commands if c.get('op') == 'rect' and c.get('fill') in ('#ff5a5a', '#40c060')]


class RuUITouchTests(unittest.TestCase):
    def touch_tap(self, x, y, pointer=7):
        return [
            {'type': 'touch_start', 'id': pointer, 'x': x, 'y': y},
            {'type': 'touch_end', 'id': pointer, 'x': x, 'y': y},
            {'type': 'frame'},
        ]

    def test_touch_tap_python_increments(self):
        events = run_python(COUNTER)
        x, y = button_pos(events)
        events = run_python(COUNTER, self.touch_tap(x, y))
        self.assertEqual(texts(events[-1]['commands'])[:2], ['触屏', '1'])

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_touch_tap_js_matches_python(self):
        events = run_python(COUNTER)
        x, y = button_pos(events)
        py = run_python(COUNTER, self.touch_tap(x, y))
        js = run_javascript(COUNTER, self.touch_tap(x, y))
        self.assertEqual(texts(js[-1]['commands'])[:2], ['触屏', '1'])
        self.assertEqual(len(py), len(js))

    def test_secondary_pointer_ignored_then_promoted(self):
        # 次指针按下不触发；主指针抬起后次指针提升，但次指针从未转发
        # 过 按下，其 抬起 不补发 松开（不会凭空触发钮）。
        py = run_python(COUNTER)
        x, y = button_pos(py)
        # A 按下（主）→ B 按下（仅记录）→ A 抬起（A 的点按 +1，提升 B）
        # → B 移动（转发）→ B 抬起（值 假，不转发）→ 帧。
        seq = [
            {'type': 'touch_start', 'id': 1, 'x': x, 'y': y},
            {'type': 'touch_start', 'id': 2, 'x': x, 'y': y},
            {'type': 'touch_end', 'id': 1, 'x': x, 'y': y},
            {'type': 'touch_move', 'id': 2, 'x': x, 'y': y},
            {'type': 'touch_end', 'id': 2, 'x': x, 'y': y},
            {'type': 'frame'},
        ]
        events = run_python(COUNTER, seq)
        # 整段只有一次有效点按：计数恰为 1，B 的抬起没再触发。
        self.assertEqual(texts(events[-1]['commands'])[:2], ['触屏', '1'])
        # 对照：A 单独完整点按 → 1。
        seq2 = [
            {'type': 'touch_start', 'id': 1, 'x': x, 'y': y},
            {'type': 'touch_end', 'id': 1, 'x': x, 'y': y},
            {'type': 'frame'},
        ]
        events = run_python(COUNTER, seq2)
        self.assertEqual(texts(events[-1]['commands'])[:2], ['触屏', '1'])


class RuUIResizeTests(unittest.TestCase):
    def test_resize_python_relays_out(self):
        events = run_python(SPLITS)
        first = blocks(events[-1]['commands'])
        self.assertEqual(len(first), 2)
        self.assertEqual(first[0]['width'], 180.0)
        events = run_python(SPLITS, [{'type': 'resize', 'width': 500, 'height': 400}])
        scene = events[-1]
        self.assertEqual(scene['width'], 500)
        self.assertEqual(scene['height'], 400)
        after = blocks(scene['commands'])
        self.assertEqual(len(after), 2)
        self.assertEqual(after[0]['width'], 250.0)

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_resize_js_matches_python(self):
        events = run_python(SPLITS)
        first = blocks(events[-1]['commands'])
        self.assertEqual(first[0]['width'], 180.0)
        resize = [{'type': 'resize', 'width': 500, 'height': 400}]
        py = run_python(SPLITS, resize)
        js = run_javascript(SPLITS, resize)
        self.assertEqual(js[-1]['width'], 500)
        self.assertEqual(blocks(js[-1]['commands'])[0]['width'], 250.0)
        self.assertEqual(len(py), len(js))


class RuUITouchResizeValidationTests(unittest.TestCase):
    def assert_rejected(self, event):
        host = GraphicsHost(Interpreter(), lambda e: None)
        try:
            host.interpreter.execute(parse(COUNTER))
            host.flush()
            with self.assertRaises(RuError):
                host.handle(dict(event))
        finally:
            host.close()

    def test_touch_bad_pointer(self):
        self.assert_rejected({'type': 'touch_start', 'id': -1, 'x': 10, 'y': 10})
        self.assert_rejected({'type': 'touch_start', 'id': 1.5, 'x': 10, 'y': 10})
        self.assert_rejected({'type': 'touch_start', 'id': 100001, 'x': 10, 'y': 10})

    def test_touch_bad_coord(self):
        self.assert_rejected({'type': 'touch_move', 'id': 1, 'x': 'a', 'y': 10})

    def test_touch_unknown_field(self):
        self.assert_rejected({'type': 'touch_start', 'id': 1, 'x': 10, 'y': 10, 'button': 0})

    def test_resize_bad_dims(self):
        self.assert_rejected({'type': 'resize', 'width': 0, 'height': 100})
        self.assert_rejected({'type': 'resize', 'width': 100.5, 'height': 100})
        self.assert_rejected({'type': 'resize', 'width': 100, 'height': 100001})

    def test_resize_unknown_field(self):
        self.assert_rejected({'type': 'resize', 'width': 100, 'height': 100, 'x': 1})

    def test_canvas_resize_member_python(self):
        host = GraphicsHost(Interpreter(), lambda e: None)
        try:
            host.interpreter.execute(parse(
                "观 取 外言 '如:观'. 布 取 (观 其 画布 200 100). 布 其 尺寸 320 240.\n"))
            host.flush()
            self.assertEqual(host.canvas.width, 320.0)
            self.assertEqual(host.canvas.height, 240.0)
            with self.assertRaises(RuError):
                host.interpreter.execute(parse(
                    "观 取 外言 '如:观'. 布 取 (观 其 画布 200 100). 布 其 尺寸 0 240.\n"))
        finally:
            host.close()


if __name__ == '__main__':
    unittest.main()
