"""如UI third-party widget library: Python/JS parity and interaction tests."""
import json
import math
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
        (文 '计数器'),
        (文 (数[0] 为 句)),
        (钮 '加一' (作: 数[0] 取 数[0] + 1. 为))
    ].
法).
机 其 跑.
"""

QUIZ = """
尽取 外言 '如UI'.

选值 取 [0].
馈 取 [''].
机 取 新 应用 宽: 360 高: 640 构: (算:
    得 列 [
        (文 '如言首个公开版本年？'),
        (选 ['2019', '2022', '2025'] 0 (作 位 为 数:
            选值[0] 取 位.
            馈[0] 取 ''.
            为)),
        (钮 '提交' (作:
            若 选值[0] == 2 则
                馈[0] 取 '答对了'.
            另
                馈[0] 取 '再想想'.
            然
            为)),
        (文 (馈[0]))
    ].
法).
机 其 跑.
"""

SCROLL_TAP = """
尽取 外言 '如UI'.

中 取 ['无'].
机 取 新 应用 宽: 360 高: 640 构: (算:
    得 列 [
        (滚 96 ([
            (钮 '甲' (作: 中[0] 取 '甲'. 为)),
            (钮 '乙' (作: 中[0] 取 '乙'. 为)),
            (钮 '丙' (作: 中[0] 取 '丙'. 为)),
            (钮 '丁' (作: 中[0] 取 '丁'. 为)),
            (钮 '戊' (作: 中[0] 取 '戊'. 为))
        ])),
        (文 (中[0]))
    ].
法).
机 其 跑.
"""

SLIDER = """
尽取 外言 '如UI'.

值 取 [30].
机 取 新 应用 宽: 360 高: 640 构: (算:
    得 列 [
        (文 (值[0] 为 句)),
        (滑 30 0 100 (作 新值 为 数: 值[0] 取 新值. 为))
    ].
法).
机 其 跑.
"""

MIXER = (ROOT / 'examples' / 'ruui-mixer.ru').read_text(encoding='utf-8')


def texts(commands):
    return [c.get('text') for c in commands if c.get('op') == 'text']


def rects(commands):
    return [c for c in commands if c.get('op') == 'rect']


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


def compare_value(test, left, right):
    if isinstance(left, (int, float)) and not isinstance(left, bool):
        test.assertIsInstance(right, (int, float))
        test.assertNotIsInstance(right, bool)
        test.assertTrue(math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12), (left, right))
    elif isinstance(left, dict):
        test.assertEqual(left.keys(), right.keys(), (left, right))
        for key in left:
            compare_value(test, left[key], right[key])
    elif isinstance(left, list):
        test.assertEqual(len(left), len(right))
        for a, b in zip(left, right):
            compare_value(test, a, b)
    else:
        test.assertEqual(left, right)


class RuUIParityTests(unittest.TestCase):
    def compare(self, source, inputs=()):
        python = run_python(source, inputs)
        javascript = run_javascript(source, inputs)
        self.assertEqual(len(python), len(javascript), (len(python), len(javascript)))
        for p, j in zip(python, javascript):
            p = {k: v for k, v in p.items() if k != 'canvas_id'}
            j = {k: v for k, v in j.items() if k != 'canvas_id'}
            compare_value(self, p, j)
        return python

    def find_rect(self, commands, fill):
        matches = [c for c in commands if c.get('op') == 'rect' and c.get('fill') == fill]
        self.assertTrue(matches, (fill, commands))
        return matches[0]

    def find_text(self, commands, value):
        matches = [c for c in commands if c.get('op') == 'text' and c.get('text') == value]
        self.assertTrue(matches, (value, commands))
        return matches[0]

    def center(self, command):
        return (command['x'] + command['width'] / 2, command['y'] + command['height'] / 2)

    def tap(self, x, y):
        return [
            {'type': 'mouse_down', 'x': x, 'y': y, 'button': 0},
            {'type': 'mouse_up', 'x': x, 'y': y, 'button': 0},
            {'type': 'frame'},
        ]

    def test_counter_python_headless_tap_increments(self):
        events = run_python(COUNTER)
        self.assertEqual(len(events), 1)
        self.assertEqual(texts(events[-1]['commands'])[:2], ['计数器', '0'])
        button = self.find_rect(events[-1]['commands'], '#4677ff')
        x, y = self.center(button)
        events = run_python(COUNTER, self.tap(x, y))
        self.assertEqual(texts(events[-1]['commands'])[:2], ['计数器', '1'])
        events = run_python(COUNTER, self.tap(x, y) + self.tap(x, y))
        self.assertEqual(texts(events[-1]['commands'])[:2], ['计数器', '2'])

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_counter_js_matches_python_and_taps(self):
        events = self.compare(COUNTER)
        self.assertEqual(texts(events[-1]['commands'])[:2], ['计数器', '0'])
        button = self.find_rect(events[-1]['commands'], '#4677ff')
        x, y = self.center(button)
        events = self.compare(COUNTER, self.tap(x, y))
        self.assertEqual(texts(events[-1]['commands'])[:2], ['计数器', '1'])

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_quiz_select_and_submit_feedback(self):
        events = self.compare(QUIZ)
        self.assertIn('如言首个公开版本年？', texts(events[-1]['commands']))
        option = self.find_text(events[-1]['commands'], '2025')
        x, y = option['x'], option['y']
        events = self.compare(QUIZ, self.tap(x, y))
        submit = self.find_rect(events[-1]['commands'], '#4677ff')
        sx, sy = self.center(submit)
        events = self.compare(QUIZ, self.tap(x, y) + self.tap(sx, sy))
        self.assertIn('答对了', texts(events[-1]['commands']))
        wrong = self.find_text(events[-1]['commands'], '2019')
        events = self.compare(QUIZ, self.tap(wrong['x'], wrong['y']) + self.tap(sx, sy))
        self.assertIn('再想想', texts(events[-1]['commands']))

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_scroll_clips_hits_and_drag_reveals(self):
        events = self.compare(SCROLL_TAP)
        first = self.find_rect(events[-1]['commands'], '#4677ff')
        x, y = self.center(first)
        events = self.compare(SCROLL_TAP, self.tap(x, y))
        self.assertIn('甲', texts(events[-1]['commands']))
        # 第五项在 96 高的视口外，点击不应命中。
        fifth = self.find_text(events[-1]['commands'], '戊')
        events = self.compare(SCROLL_TAP, self.tap(fifth['x'], fifth['y']))
        self.assertIn('无', texts(events[-1]['commands']))
        # 拖拽 60 向上后，第五项进入视口并可点。
        drag = [
            {'type': 'mouse_down', 'x': x, 'y': y, 'button': 0},
            {'type': 'mouse_move', 'x': x, 'y': y - 60, 'button': 0},
            {'type': 'mouse_up', 'x': x, 'y': y - 60, 'button': 0},
            {'type': 'frame'},
        ]
        events = self.compare(SCROLL_TAP, drag + self.tap(fifth['x'], fifth['y'] - 60))
        self.assertIn('戊', texts(events[-1]['commands']))

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_slider_drag_updates_value(self):
        events = self.compare(SLIDER)
        self.assertIn('30', texts(events[-1]['commands']))
        knob = [c for c in events[-1]['commands'] if c.get('op') == 'ellipse']
        self.assertTrue(knob, events[-1]['commands'])
        kx, ky = knob[0]['x'] + 8, knob[0]['y'] + 8
        drag = [
            {'type': 'mouse_down', 'x': kx, 'y': ky, 'button': 0},
            {'type': 'mouse_move', 'x': kx + 1000, 'y': ky, 'button': 0},
            {'type': 'mouse_up', 'x': kx + 1000, 'y': ky, 'button': 0},
            {'type': 'frame'},
        ]
        events = self.compare(SLIDER, drag)
        self.assertIn('100', texts(events[-1]['commands']))

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_slider_drag_clamps_to_min(self):
        events = self.compare(SLIDER)
        knob = [c for c in events[-1]['commands'] if c.get('op') == 'ellipse']
        kx, ky = knob[0]['x'] + 8, knob[0]['y'] + 8
        drag = [
            {'type': 'mouse_down', 'x': kx, 'y': ky, 'button': 0},
            {'type': 'mouse_move', 'x': kx - 1000, 'y': ky, 'button': 0},
            {'type': 'mouse_up', 'x': kx - 1000, 'y': ky, 'button': 0},
            {'type': 'frame'},
        ]
        events = self.compare(SLIDER, drag)
        self.assertEqual(texts(events[-1]['commands'])[0], '0')

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_scroll_drag_clamps_and_second_drag_resumes(self):
        events = self.compare(SCROLL_TAP)
        first = self.find_rect(events[-1]['commands'], '#4677ff')
        x, y = self.center(first)
        fifth = self.find_text(events[-1]['commands'], '戊')
        # 内容剩余 120：向上猛拖 300，位移钳在 120，戊进入视口可点。
        drag_up = [
            {'type': 'mouse_down', 'x': x, 'y': y, 'button': 0},
            {'type': 'mouse_move', 'x': x, 'y': y - 300, 'button': 0},
            {'type': 'mouse_up', 'x': x, 'y': y - 300, 'button': 0},
            {'type': 'frame'},
        ]
        events = self.compare(SCROLL_TAP, drag_up + self.tap(fifth['x'], fifth['y'] - 120))
        self.assertEqual(texts(events[-1]['commands'])[-1], '戊')
        # 松手后再向下拖 500：从 120 回 0，原位只点得到乙。
        drag_down = [
            {'type': 'mouse_down', 'x': x, 'y': y, 'button': 0},
            {'type': 'mouse_move', 'x': x, 'y': y + 500, 'button': 0},
            {'type': 'mouse_up', 'x': x, 'y': y + 500, 'button': 0},
            {'type': 'frame'},
        ]
        events = self.compare(SCROLL_TAP, drag_up + drag_down + self.tap(fifth['x'], fifth['y'] - 120))
        self.assertEqual(texts(events[-1]['commands'])[-1], '乙')

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_mixer_example_layout_and_equal_width(self):
        events = self.compare(MIXER)
        self.assertIn('调色盘', texts(events[-1]['commands']))
        bars = [c for c in events[-1]['commands']
                if c.get('op') == 'rect' and c.get('fill') in ('#ff5a5a', '#40c060', '#3f8cff')]
        self.assertEqual(len(bars), 3, bars)
        for bar in bars:
            self.assertTrue(math.isclose(bar['width'], 120.0, abs_tol=1e-9), bars)
        heights = {bar['fill']: bar['height'] for bar in bars}
        self.assertEqual(heights, {'#ff5a5a': 40.0, '#40c060': 140.0, '#3f8cff': 90.0})
        buttons = [c for c in events[-1]['commands']
                   if c.get('op') == 'rect' and c.get('fill') == '#4677ff']
        self.assertEqual(len(buttons), 2, buttons)
        for button in buttons:
            self.assertTrue(math.isclose(button['width'], 180.0, abs_tol=1e-9), buttons)

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_mixer_interactions_preset_and_theme(self):
        events = self.compare(MIXER)
        knob = [c for c in events[-1]['commands'] if c.get('op') == 'ellipse']
        kx, ky = knob[0]['x'] + 8, knob[0]['y'] + 8
        drag_right = [
            {'type': 'mouse_down', 'x': kx, 'y': ky, 'button': 0},
            {'type': 'mouse_move', 'x': kx + 1000, 'y': ky, 'button': 0},
            {'type': 'mouse_up', 'x': kx + 1000, 'y': ky, 'button': 0},
            {'type': 'frame'},
        ]
        events = self.compare(MIXER, drag_right)
        bar = [c for c in events[-1]['commands'] if c.get('op') == 'rect' and c.get('fill') == '#ff5a5a'][0]
        self.assertTrue(math.isclose(bar['height'], 255.0, rel_tol=1e-12, abs_tol=1e-12), bar)
        # 选预设 深海：三柱变为 10/40/120。
        sea = self.find_text(events[-1]['commands'], '深海')
        events = self.compare(MIXER, drag_right + self.tap(sea['x'], sea['y']))
        heights = {c['fill']: c['height'] for c in events[-1]['commands']
                   if c.get('op') == 'rect' and c.get('fill') in ('#ff5a5a', '#40c060', '#3f8cff')}
        self.assertEqual(heights, {'#ff5a5a': 10.0, '#40c060': 40.0, '#3f8cff': 120.0})
        # 主题切换：背景变暗、按钮换标签，两后端一致。
        toggle = self.find_text(events[-1]['commands'], '切到暗色')
        events = self.compare(MIXER, drag_right + self.tap(sea['x'], sea['y']) + self.tap(toggle['x'], toggle['y']))
        background = [c for c in events[-1]['commands'] if c.get('op') == 'background']
        self.assertEqual(background[0]['color'], '#16181d')
        self.assertIn('切回亮色', texts(events[-1]['commands']))

    def test_toast_and_page_switch(self):
        toast = """
尽取 外言 '如UI'.

页号 取 [0].
机 取 新 应用 宽: 360 高: 640 构: (算:
    若 页号[0] == 0 则
        得 列 [
            (文 '首页'),
            (钮 '下一页' (作:
                页号[0] 取 1.
                (机 其 页) 机 其 构.
                为)),
            (钮 '打招呼' (作: 机 其 提示 '你好'. 为))
        ].
    另
        得 列 [
            (文 '第二页'),
            (钮 '回去' (作:
                页号[0] 取 0.
                (机 其 页) 机 其 构.
                为))
        ].
    然
法).
机 其 跑.
"""
        events = run_python(toast)
        self.assertIn('首页', texts(events[-1]['commands']))
        nxt = [c for c in events[-1]['commands'] if c.get('op') == 'text' and c.get('text') == '下一页'][0]
        events = run_python(toast, self.tap(nxt['x'], nxt['y']))
        self.assertIn('第二页', texts(events[-1]['commands']))
        events = run_python(toast, self.tap(nxt['x'], nxt['y']) + self.tap(nxt['x'], nxt['y']))
        self.assertIn('首页', texts(events[-1]['commands']))

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_toast_renders_on_both_backends(self):
        source = """
尽取 外言 '如UI'.
机 取 新 应用 宽: 360 高: 640 构: (算:
    得 列 [
        (文 '底'),
        (钮 '招呼' (作: 机 其 提示 '世界'. 为))
    ].
法).
机 其 跑.
"""
        events = self.compare(source)
        btn = self.find_rect(events[-1]['commands'], '#4677ff')
        x, y = self.center(btn)
        events = self.compare(source, self.tap(x, y))
        self.assertIn('世界', texts(events[-1]['commands']))
        self.assertNotIn('世界', texts(events[0]['commands']))

    def test_invalid_event_rejected_python(self):
        events = []
        host = GraphicsHost(Interpreter(), events.append)
        try:
            host.interpreter.execute(parse(COUNTER))
            host.flush()
            with self.assertRaises(RuError):
                host.handle({'type': 'mouse_down', 'x': 'a', 'y': 1, 'button': 0})
        finally:
            host.close()


if __name__ == '__main__':
    unittest.main()
