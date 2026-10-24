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
机 其 运行.
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
机 其 运行.
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
机 其 运行.
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
机 其 运行.
"""

TEXTFIELD = """
尽取 外言 '如UI'.

名 取 [''].
改次 取 [0].
机 取 新 应用 宽: 360 高: 640 构: (算:
    得 列 [
        (文入 (名[0]) '姓名' (作 新文 为 句: 名[0] 取 新文. 改次[0] 取 改次[0] + 1. 为)),
        (文 ('次' + (改次[0] 为 句)))
    ].
法).
机 其 运行.
"""

TEXTAREA = """
尽取 外言 '如UI'.

稿 取 [''].
机 取 新 应用 宽: 360 高: 640 构: (算:
    得 列 [
        (多行 (文入 (稿[0]) '备注' (作 新文 为 句: 稿[0] 取 新文. 为)))
    ].
法).
机 其 运行.
"""

TEXT_PAGES = """
尽取 外言 '如UI'.

名 取 [''].
机 取 新 应用 宽: 360 高: 640 构: (算:
    得 列 [
        (文入 (名[0]) '姓名' (作 新文 为 句: 名[0] 取 新文. 为)),
        (钮 '翻页' (作: (机 其 页 (算: 得 列 [(文 ('已存' + 名[0]))]. 法)). 为))
    ].
法).
机 其 运行.
"""

MIXER = (ROOT / 'examples' / 'ruui-mixer.ru').read_text(encoding='utf-8')


def texts(commands):
    return [c.get('text') for c in commands if c.get('op') == 'text']


def rects(commands):
    return [c for c in commands if c.get('op') == 'rect']


def ops(commands, op):
    return [c for c in commands if c.get('op') == op]


def png_bytes(width, height):
    return (b'\x89PNG\r\n\x1a\n' + (13).to_bytes(4, 'big') + b'IHDR'
            + width.to_bytes(4, 'big') + height.to_bytes(4, 'big')
            + b'\x08\x06\x00\x00\x00' + b'\x00\x00\x00\x00')


def jpeg_bytes(width, height):
    return b'\xff\xd8\xff\xc0\x00\x11\x08' + height.to_bytes(2, 'big') + width.to_bytes(2, 'big')


def run_python(source, inputs=(), metrics=None, measurer=None):
    events = []
    host = GraphicsHost(Interpreter(), events.append)
    if metrics is not None:
        host.text_metrics = metrics
    if measurer is not None:
        host.text_measurer = measurer
    try:
        host.interpreter.execute(parse(source))
        host.flush()
        for event in inputs:
            host.handle(event)
        return [e for e in events if e['type'] == 'graphics']
    finally:
        host.close()


def run_javascript(source, inputs=(), metrics=None, measurer_js=None):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'program.mjs').write_text(compile_browser(source), encoding='utf-8')
        options = '{emit:e=>events.push(e)'
        if metrics is not None:
            options += ',textMetrics:' + json.dumps(metrics, ensure_ascii=False)
        if measurer_js is not None:
            options += ',textMeasurer:' + measurer_js
        options += '}'
        (path / 'run.mjs').write_text(
            "import create from './program.mjs';const events=[];"
            f"const runtime=create({options});"
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
    def compare(self, source, inputs=(), metrics=None, measurer=None, measurer_js=None):
        python = run_python(source, inputs, metrics=metrics, measurer=measurer)
        javascript = run_javascript(source, inputs, metrics=metrics, measurer_js=measurer_js)
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
机 其 运行.
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
机 其 运行.
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

    # ---------- 3a：图载／件载／件目（宿主资源协议） ----------

    def load_program(self, directory, filename='a.png'):
        # Ru supports quoted strings; JSON escapes backslashes and quotes without
        # Python repr introducing unsupported \u/\U escapes for Unicode paths.
        directory_literal = json.dumps(str(directory), ensure_ascii=False)
        filename_literal = json.dumps(filename, ensure_ascii=False)
        return f"""
尽取 外言 '如UI'.

果 取 [''].
机 取 新 应用 宽: 360 高: 640 件目: {directory_literal} 构: (算:
    得 列 [
        (图载 {filename_literal} 120 (作 宽 为 数 高 为 数 错 为 句:
            果[0] 取 (宽 为 句) + 'x' + (高 为 句) + ':' + 错.
            为)),
        (文 (果 其 位 0))
    ].
法).
机 其 运行.
"""

    def test_resource_paths_keep_windows_separators_quotes_and_unicode(self):
        from rulang.frontend import lex
        directory = "C:\\Users\\甲 O'Brien\\项目"
        filename = 'a"b.png'
        values = [token.value for token in lex(self.load_program(directory, filename))]
        self.assertIn(directory, values)
        self.assertIn(filename, values)
        parse(self.load_program(directory, filename))

    def test_resource_protocol_joins_windows_base_with_forward_slash(self):
        # The UI protocol joins base/source, independent of the host OS.
        directory = "C:\\Users\\甲 O'Brien\\项目"
        events = run_python(self.load_program(directory))
        requested = [c for event in events
                     for c in ops(event['commands'], 'image_request')]
        self.assertEqual([(c['id'], c['source']) for c in requested],
                         [(1, directory + '/a.png')])

    def test_image_head_size_recognises_png_and_jpeg(self):
        from rulang.graphics_runtime import _image_head_size
        self.assertEqual(_image_head_size(png_bytes(4, 3)), (4, 3))
        self.assertEqual(_image_head_size(jpeg_bytes(640, 480)), (640, 480))
        with self.assertRaisesRegex(RuError, '不识别的图像格式'):
            _image_head_size(b'not an image at all')
        with self.assertRaisesRegex(RuError, '图像尺寸无效'):
            _image_head_size(png_bytes(0, 3))

    def test_image_load_python_host_auto_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'a.png').write_bytes(png_bytes(4, 3))
            events = run_python(self.load_program(directory))
        # 首帧装帧不绘，宿主读头成功后第二帧等比绘制 160x120 居中。
        self.assertEqual(len(events), 2)
        drawn = ops(events[-1]['commands'], 'draw_image')
        self.assertEqual(len(drawn), 1)
        self.assertTrue(math.isclose(drawn[0]['x'], 100.0), drawn[0])
        self.assertTrue(math.isclose(drawn[0]['width'], 160.0), drawn[0])
        self.assertIn('4x3:', texts(events[-1]['commands']))

    def test_image_load_failure_fires_callback_once(self):
        with tempfile.TemporaryDirectory() as directory:
            events = run_python(self.load_program(directory, 'missing.png'))
        self.assertEqual(len(events), 2)
        self.assertIn('0x0:读不到文件', texts(events[-1]['commands']))
        self.assertEqual(ops(events[-1]['commands'], 'draw_image'), [])

    def test_image_load_parity_injected(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'a.png').write_bytes(png_bytes(4, 3))
            # Python 宿主自动装载；JS 由注入事件驱动：双路须殊途同归。
            events = self.compare(
                self.load_program(directory),
                [{'type': 'image_ready', 'id': 1, 'width': 4, 'height': 3},
                 {'type': 'image_ready', 'id': 1, 'width': 4, 'height': 3}])
        self.assertEqual(len(events), 2)
        drawn = ops(events[-1]['commands'], 'draw_image')
        self.assertEqual(len(drawn), 1)
        self.assertIn('4x3:', texts(events[-1]['commands']))

    def test_image_load_parity_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            events = self.compare(
                self.load_program(directory, 'missing.png'),
                [{'type': 'image_failed', 'id': 1, 'error': '读不到文件'}])
        self.assertEqual(len(events), 2)
        self.assertIn('0x0:读不到文件', texts(events[-1]['commands']))

    def test_image_page_switch_releases_and_reloads(self):
        source = """
尽取 外言 '如UI'.

果 取 [''].
二页 取 (算:
    得 列 [(图载 'c.png' 120 (作 宽 为 数 高 为 数 错 为 句:
        果[0] 取 (宽 为 句) + 'x' + (高 为 句). 为)),
        (文 (果 其 位 0))
    ].
法).
机 取 新 应用 宽: 360 高: 640 件目: {d} 构: (算:
    得 列 [
        (图载 'a.png' 120 (作 宽 为 数 高 为 数 错 为 句: 果[0] 取 (宽 为 句). 为)),
        (钮 '换' (作: 机 其 页 二页. 为))
    ].
法).
机 其 运行.
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'a.png').write_bytes(png_bytes(4, 3))
            (path / 'c.png').write_bytes(png_bytes(5, 2))
            host_events = []
            host = GraphicsHost(Interpreter(), host_events.append)
            try:
                host.interpreter.execute(parse(source.format(d=json.dumps(directory, ensure_ascii=False))))
                host.flush()
                button = self.find_rect(host_events[0]['commands'], '#4677ff')
                x, y = self.center(button)
                for event in self.tap(x, y):
                    host.handle(event)
            finally:
                host.close()
            events = [e for e in host_events if e['type'] == 'graphics']
            released = [c for e in events for c in ops(e['commands'], 'image_release')]
            self.assertEqual([c['id'] for c in released], [1])
            requested = [c for e in events for c in ops(e['commands'], 'image_request')]
            self.assertEqual([(c['id'], c['source']) for c in requested],
                             [(1, directory + '/a.png'), (2, directory + '/c.png')])
            self.assertIn('5x2', texts(events[-1]['commands']))
            switched = [e for e in events if ops(e['commands'], 'image_release')]
            self.assertTrue(switched)
            self.assertEqual(ops(switched[-1]['commands'], 'image_release')[0]['id'], 1)

    def test_file_load_parity_text_and_base64(self):
        source = """
尽取 外言 '如UI'.

果 取 [''].
机 取 新 应用 宽: 360 高: 640 件目: {d} 构: (算:
    得 列 [(文 果[0])].
法).
机 其 运行.
机 其 件载 'note.txt' (作 字 为 句 错 为 句: 果[0] 取 字 + '/' + 错. 为) '文' 假.
机 其 件载 'data.bin' (作 字 为 句 错 为 句: 果[0] 取 果[0] + '|' + 字. 为) 'base64' 假.
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'note.txt').write_text('你好', encoding='utf-8')
            (path / 'data.bin').write_bytes(bytes([0, 255]))
            events = self.compare(
                source.format(d=json.dumps(directory, ensure_ascii=False)),
                [{'type': 'file_ready', 'id': 1, 'text': '你好'},
                 {'type': 'file_ready', 'id': 2, 'text': 'AP8='}])
        self.assertIn('你好/|AP8=', texts(events[-1]['commands']))

    def test_source_resolution_rejects_bad_paths(self):
        base = """
尽取 外言 '如UI'.
机 取 新 应用 宽: 360 高: 640 {extra} 构: (算: 得 列 [(文 'x')]. 法).
机 其 运行.
机 其 件载 '{src}' (作 字 为 句 错 为 句: 为) '文' 假.
"""
        cases = [
            ('', '../x', '源 越出件目'),
            ('', 'a/../../x', '源 越出件目'),
            ("件目: '/tmp'", '../x', '源 越出件目'),
            ('', '/tmp/x', '源 不可为绝对路径'),
            ('', '', '源 不可为空串'),
        ]
        for extra, src, message in cases:
            with self.assertRaises(RuError) as caught:
                run_python(base.format(extra=extra, src=src))
            self.assertIn(message, str(caught.exception))

    def test_file_mode_and_text_quota_enforced(self):
        source = """
尽取 外言 '如UI'.
机 取 新 应用 宽: 360 高: 640 构: (算: 得 列 [(文 'x')]. 法).
机 其 运行.
机 其 件载 'a' (作 字 为 句 错 为 句: 为) 'binary' 假.
"""
        with self.assertRaisesRegex(RuError, '只支持 文 或 base64'):
            run_python(source)

    def test_load_handle_cap_enforced(self):
        lines = '\n'.join(
            "机 其 件载 '第{0}件.txt' (作 字 为 句 错 为 句: 为) '文' 假.".format(i)
            for i in range(65))
        source = """
尽取 外言 '如UI'.
机 取 新 应用 宽: 360 高: 640 构: (算: 得 列 [(文 'x')]. 法).
机 其 运行.
{lines}
"""
        with self.assertRaisesRegex(RuError, '如观文件装载最多 64 项'):
            run_python(source.format(lines=lines))

    def test_host_event_validation_and_quiety(self):
        events = []
        host = GraphicsHost(Interpreter(), events.append, auto_load=False)
        try:
            host.interpreter.execute(parse(self.load_program('/nonexistent')))
            host.flush()
            graphics = [e for e in events if e['type'] == 'graphics']
            self.assertEqual(len(graphics), 1)
            # auto_load=False：请求只入队不装载，无后续帧。
            host.flush()
            self.assertEqual(len([e for e in events if e['type'] == 'graphics']), 1)
            # 未绑定的装载就绪事件静默忽略。
            host.handle({'type': 'image_ready', 'id': 1, 'width': 4, 'height': 3})
            self.assertEqual(len([e for e in events if e['type'] == 'graphics']), 1)
            bad = [
                {'type': 'image_ready', 'id': -1, 'width': 4, 'height': 3},
                {'type': 'image_ready', 'id': 1, 'width': 0, 'height': 3},
                {'type': 'image_failed', 'id': 1, 'error': ''},
                {'type': 'file_ready', 'id': 1, 'text': 'x' * 9000000},
                {'type': 'image_ready', 'id': 1, 'width': 4, 'height': 3, 'extra': 1},
            ]
            for event in bad:
                with self.assertRaises(RuError):
                    host.handle(event)
        finally:
            host.close()

    def test_host_image_quota_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            big = path / 'big.png'
            with big.open('wb') as handle:
                handle.truncate(64 * 1024 * 1024 + 1)
            events = run_python(self.load_program(directory, 'big.png'))
        self.assertIn('0x0:图像超过配额', texts(events[-1]['commands']))

    def field(self, commands):
        return self.find_rect(commands, '#d8dee9')

    @staticmethod
    def all_ops(events, op):
        return [c for e in events if e['type'] == 'graphics'
                for c in ops(e['commands'], op)]

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_textfield_focus_types_and_blur_parity(self):
        events = self.compare(TEXTFIELD)
        self.assertEqual(texts(events[-1]['commands'])[0], '姓名')
        field = self.field(events[-1]['commands'])
        x, y = self.center(field)
        focus_tap = self.tap(x, y)
        events = self.compare(TEXTFIELD, focus_tap)
        self.assertEqual(texts(events[-1]['commands'])[0], '次0')
        focus = self.all_ops(events, 'text_focus')[0]
        self.assertEqual(focus['text'], '')
        self.assertEqual(focus['cursor'], 0)
        typing = focus_tap + [{'type': 'text_char', 'text': '小'},
                              {'type': 'text_char', 'text': '红'}, {'type': 'frame'}]
        events = self.compare(TEXTFIELD, typing)
        self.assertEqual(texts(events[-1]['commands'])[:2], ['小红', '次2'])
        updates = self.all_ops(events, 'text_update')
        self.assertEqual(updates[-1]['cursor'], 2)
        blur_tap = typing + self.tap(4, 600)
        events = self.compare(TEXTFIELD, blur_tap)
        self.assertTrue(self.all_ops(events, 'text_blur'))
        self.assertEqual(texts(events[-1]['commands'])[:2], ['小红', '次2'])

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_textfield_edit_keys_parity(self):
        events = self.compare(TEXTFIELD)
        field = self.field(events[-1]['commands'])
        x, y = self.center(field)
        sequence = self.tap(x, y) + [
            {'type': 'text_paste', 'text': '甲乙丙'},
            {'type': 'text_key', 'key': '左'},
            {'type': 'text_key', 'key': '退格'},
            {'type': 'text_key', 'key': '家'},
            {'type': 'text_key', 'key': '终'},
            {'type': 'text_key', 'key': '删除'},
            {'type': 'frame'},
        ]
        events = self.compare(TEXTFIELD, sequence)
        # 粘贴后光标居尾；退格删乙；家／终跳行首／尾；尾处删除无操作。
        self.assertEqual(texts(events[-1]['commands'])[:2], ['甲丙', '次2'])

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_textfield_enter_commits_single_line_and_ignores_rest(self):
        events = self.compare(TEXTFIELD)
        field = self.field(events[-1]['commands'])
        x, y = self.center(field)
        sequence = self.tap(x, y) + [
            {'type': 'text_char', 'text': '甲'},
            {'type': 'text_key', 'key': '回车'},
            {'type': 'text_char', 'text': '乙'},
            {'type': 'frame'},
        ]
        events = self.compare(TEXTFIELD, sequence)
        # 单行回车＝提交并失焦；后续无焦点输入被忽略（重发旧场景）。
        self.assertEqual(texts(events[-1]['commands'])[:2], ['甲', '次1'])

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_textfield_single_line_paste_strips_newlines(self):
        events = self.compare(TEXTFIELD)
        field = self.field(events[-1]['commands'])
        x, y = self.center(field)
        sequence = self.tap(x, y) + [{'type': 'text_paste', 'text': '甲\n乙'},
                                     {'type': 'frame'}]
        events = self.compare(TEXTFIELD, sequence)
        self.assertEqual(texts(events[-1]['commands'])[0], '甲乙')

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_textarea_multiline_enter_newline_and_line_keys(self):
        events = self.compare(TEXTAREA)
        field = self.field(events[-1]['commands'])
        x, y = self.center(field)
        sequence = self.tap(x, y) + [
            {'type': 'text_char', 'text': '甲'},
            {'type': 'text_key', 'key': '回车'},
            {'type': 'text_char', 'text': '乙'},
            {'type': 'text_key', 'key': '上'},
            {'type': 'text_key', 'key': '家'},
            {'type': 'text_char', 'text': '丙'},
            {'type': 'frame'},
        ]
        events = self.compare(TEXTAREA, sequence)
        # 上：列位保持归首行；家：行首；丙插行首。
        self.assertEqual(texts(events[-1]['commands'])[0], '丙甲\n乙')

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_textfield_ime_composition_commit_once(self):
        events = self.compare(TEXTFIELD)
        field = self.field(events[-1]['commands'])
        x, y = self.center(field)
        sequence = self.tap(x, y) + [
            {'type': 'text_comp_start'},
            {'type': 'text_char', 'text': 'n'},
            {'type': 'text_comp_update', 'text': 'n', 'cursor': 1},
            {'type': 'text_comp_update', 'text': 'ni', 'cursor': 2},
            {'type': 'text_key', 'key': '左'},
            {'type': 'text_comp_end', 'text': '你'},
            {'type': 'frame'},
        ]
        events = self.compare(TEXTFIELD, sequence)
        # 组合草稿与组合期按键全部忽略；定字上屏只 遇改 一次。
        self.assertEqual(texts(events[-1]['commands'])[:2], ['你', '次1'])

    def test_textfield_host_validation_python(self):
        events = run_python(TEXTFIELD)
        field = self.field(events[-1]['commands'])
        x, y = self.center(field)
        focus_tap = self.tap(x, y)
        run_python(TEXTFIELD, focus_tap + [{'type': 'text_key', 'key': '回车'}])
        bad = [
            {'type': 'text_key', 'key': '乱键'},
            {'type': 'text_key', 'key': 'Enter'},
            {'type': 'text_char', 'text': '甲乙'},
            {'type': 'text_char', 'text': ''},
            {'type': 'text_paste', 'text': ''},
            {'type': 'text_paste', 'text': 'x' * 4097},
            {'type': 'text_comp_update', 'text': 'x' * 257, 'cursor': 1},
            {'type': 'text_comp_update', 'text': 'a', 'cursor': -1},
            {'type': 'text_comp_end', 'text': 'x' * 257},
            {'type': 'text_key', 'key': '回车', 'extra': 1},
        ]
        for event in bad:
            with self.assertRaises(RuError):
                run_python(TEXTFIELD, focus_tap + [event])

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_textfield_blur_when_page_drops_field(self):
        events = self.compare(TEXT_PAGES)
        field = self.field(events[-1]['commands'])
        x, y = self.center(field)
        button = self.find_rect(events[-1]['commands'], '#4677ff')
        bx, by = self.center(button)
        sequence = self.tap(x, y) + [{'type': 'text_char', 'text': '甲'}] + self.tap(bx, by)
        events = self.compare(TEXT_PAGES, sequence)
        # 点击按钮先失焦提交（text_blur），再翻页；新页读到已提交的串。
        self.assertTrue(self.all_ops(events, 'text_blur'))
        self.assertIn('已存甲', texts(events[-1]['commands']))


MEASURE_SNIPPET = """
观 取 外言 '如:观'.
机 取 (观 其 画布 360 640).
机 其 背景 '#102030'.
机 其 填色 '#ffffff'.
机 其 矩形 10 10 (机 其 测文 'a一') 4.
机 其 填色 '#ff0000'.
度 取 (机 其 字度).
机 其 矩形 20 20 4 ((度 其 查 '半') * 16).
机 其 填色 '#00ff00'.
机 其 矩形 30 30 4 ((度 其 查 '行') * 16).
机 其 填色 '#0000ff'.
机 其 矩形 40 40 ((机 其 测文 '甲乙') - (机 其 测文 '甲')) 4.
"""


class RuUITextMeasureTests(unittest.TestCase):

    def setUp(self):
        self.case = RuUIParityTests()

    def widths(self, events):
        commands = events[-1]['commands']
        return {
            'text': self.case.find_rect(commands, '#ffffff'),
            'half': self.case.find_rect(commands, '#ff0000'),
            'line': self.case.find_rect(commands, '#00ff00'),
            'full': self.case.find_rect(commands, '#0000ff'),
        }

    @staticmethod
    def size(widths, key):
        rect = widths[key]
        return rect['width'] if key in ('text', 'full') else rect['height']

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_measure_text_default_metrics_parity(self):
        # 不注入：双端回退算法与库早期近似逐位一致（全 1.0、半 0.56、行 1.5）。
        events = self.case.compare(MEASURE_SNIPPET)
        widths = self.widths(events)
        self.assertAlmostEqual(self.size(widths, 'text'), 1.56 * 16, delta=1e-9)
        self.assertAlmostEqual(self.size(widths, 'half'), 0.56 * 16, delta=1e-9)
        self.assertAlmostEqual(self.size(widths, 'line'), 1.5 * 16, delta=1e-9)
        self.assertAlmostEqual(self.size(widths, 'full'), 1.0 * 16, delta=1e-9)

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_measure_text_injected_metrics_drive_layout(self):
        injected = {'全': 1.1, '半': 0.5, '行': 1.4}
        events = self.case.compare(MEASURE_SNIPPET, metrics=injected)
        widths = self.widths(events)
        self.assertAlmostEqual(self.size(widths, 'text'), 1.6 * 16, delta=1e-9)
        self.assertAlmostEqual(self.size(widths, 'half'), 0.5 * 16, delta=1e-9)
        self.assertAlmostEqual(self.size(widths, 'line'), 1.4 * 16, delta=1e-9)
        self.assertAlmostEqual(self.size(widths, 'full'), 1.1 * 16, delta=1e-9)

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_textfield_caret_follows_injected_metrics(self):
        # 值区起始 x＝9.6（页内边距后实测常量）；注入半角 0.5：打完 'a'
        # 光标 x＝9.6＋0.5×16＝17.6；缺省回退 0.56 时为 18.56，两档必须不同。
        events = self.case.compare(TEXTFIELD)
        field = self.case.field(events[-1]['commands'])
        x, y = self.case.center(field)
        sequence = self.case.tap(x, y) + [{'type': 'text_char', 'text': 'a'},
                                          {'type': 'frame'}]
        carets = []
        for metrics in (None, {'全': 1.1, '半': 0.5, '行': 1.4}):
            events = self.case.compare(TEXTFIELD, sequence, metrics=metrics)
            matches = [c for c in ops(events[-1]['commands'], 'rect') if c['width'] == 2]
            self.assertTrue(matches, events[-1]['commands'])
            carets.append(matches[-1]['x'])
        self.assertAlmostEqual(carets[0], 9.6 + 0.56 * 16, delta=1e-9)
        self.assertAlmostEqual(carets[1], 9.6 + 0.5 * 16, delta=1e-9)
        self.assertNotAlmostEqual(carets[0], carets[1], delta=1e-6)

    def test_measure_text_measurer_hook_parity(self):
        # 宿主实测钩优先于回退：'a一' → 2×2+1 ＝ 5（双端同一确定性钩）。
        measurer = lambda text, size: len(text) * 2 + 1
        measurer_js = '(text,size)=>Array.from(text).length*2+1'
        events = self.case.compare(MEASURE_SNIPPET, measurer=measurer, measurer_js=measurer_js)
        self.assertEqual(self.size(self.widths(events), 'text'), 5)

    def test_measure_text_invalid_injection_rejected(self):
        bad_metrics = {'全': 1, '半': -1, '行': 1.5}
        with self.assertRaises(RuError) as caught:
            run_python(MEASURE_SNIPPET, metrics=bad_metrics)
        self.assertIn('字度', str(caught.exception))
        if NODE:
            with self.assertRaises(AssertionError):
                run_javascript(MEASURE_SNIPPET, metrics=bad_metrics)

    def test_measure_text_invalid_measurer_result_rejected(self):
        with self.assertRaises(RuError) as caught:
            run_python(MEASURE_SNIPPET, measurer=lambda text, size: float('nan'))
        self.assertIn('无效宽度', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
