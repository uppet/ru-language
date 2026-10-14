"""Versioned cubic contract and one self-contained, two-host control-point demo."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from rulang.browser_compiler import compile_browser
from rulang.cli import main
from rulang.frontend import parse, validate
from rulang.generation import generation_system_prompt
from rulang.graphics_runtime import GraphicsHost
from rulang.interpreter import Interpreter
from rulang.prompts import export_prompt

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'rushu/examples/ruguan/curved-bridge.ru'
BOOK = ROOT / 'rushu/examples/curved-bridge.rushu.json'
NODE = shutil.which('node')
KEY = lambda key: {'type': 'key_down', 'key': key}
MOUSE = lambda x, y, button=0: {'type': 'mouse_down', 'x': x, 'y': y, 'button': button}
INPUTS = [KEY('ArrowRight'), KEY('ArrowUp'), KEY('2'), KEY('ArrowLeft'), KEY('ArrowDown'),
          MOUSE(300, 240), MOUSE(420, 402), MOUSE(80, 120), KEY('ArrowLeft'), KEY('ArrowUp'),
          MOUSE(640, 330), KEY('ArrowRight'), KEY('ArrowDown'), MOUSE(300, 200, 2),
          MOUSE(12, 12), KEY('unhandled'), MOUSE(626, 402), MOUSE(518, 402),
          KEY('ArrowRight'), KEY('1'), KEY('r')]
SIGNATURE = '图 其 贝塞尔 起横 起纵 控一横 控一纵 控二横 控二纵 终横 终纵'


def expected_states():
    selected, controls = 0, [[180, 30], [420, 30]]
    states = [(selected, copy.deepcopy(controls))]
    for event in INPUTS:
        key = event.get('key')
        if key == 'r' or (event.get('type') == 'mouse_down' and event['x'] == 626):
            selected, controls = 0, [[180, 30], [420, 30]]
        elif key in ('1', '2'):
            selected = int(key) - 1
        elif key in ('ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'):
            dx, dy = {'ArrowLeft': (-10, 0), 'ArrowRight': (10, 0),
                      'ArrowUp': (0, -10), 'ArrowDown': (0, 10)}[key]
            controls[selected][0] = min(580, max(20, controls[selected][0] + dx))
            controls[selected][1] = min(210, max(0, controls[selected][1] + dy))
        elif event['type'] == 'mouse_down' and event['button'] == 0:
            x, y = event['x'], event['y']
            if 80 <= x <= 640 and 120 <= y <= 330:
                controls[selected] = [x - 60, y - 120]
            elif (x, y) == (420, 402):
                selected = 0
            elif (x, y) == (518, 402):
                selected = 1
        states.append((selected, copy.deepcopy(controls)))
    return states


class GraphicsBezierExamplesTests(unittest.TestCase):
    def test_notebook_is_clean_and_contains_the_exact_source(self):
        source = SOURCE.read_text(encoding='utf-8')
        book = json.loads(BOOK.read_text(encoding='utf-8'))
        self.assertEqual((book['format'], book['version']), ('rushu-notebook', 1))
        code = [cell for cell in book['cells'] if cell['type'] == 'code']
        self.assertEqual(len(code), 1)
        self.assertEqual(code[0]['source'].encode('utf-8'), SOURCE.read_bytes())
        for cell in book['cells']:
            self.assertIsNone(cell['execution_count'])
            self.assertEqual(cell['outputs'], [])
        validate(parse(source))
        for fragment in ("外言 '如:观'", '图 其 贝塞尔 40 190', '图 其 折线 ',
                         '图 其 保存', '图 其 裁剪', '图 其 平移', '图 其 恢复',
                         '图 其 鼠标按下', '图 其 按键', 'ArrowLeft', 'ArrowRight',
                         'ArrowUp', 'ArrowDown', "键 == '1'", "键 == '2'", "键 == 'r'"):
            self.assertIn(fragment, source)
        self.assertNotIn('图 其 每帧', source)

    def test_spec_and_guide_define_one_precise_cubic_contract(self):
        for filename in ('rulang/language-spec.md', 'docs/ruguan-guide.md'):
            with self.subTest(document=filename):
                text = (ROOT / filename).read_text(encoding='utf-8')
                for fragment in ('贝塞尔（0.19.6／如书 0.8.6）', SIGNATURE,
                                 '返回空，不是新增保留字', '八个参数均必需',
                                 '`起横:`、`起纵:`、`控一横:`、`控一纵:`、`控二横:`、`控二纵:`、`终横:`、`终纵:`',
                                 '单段三次贝塞尔曲线', '曲线经过起点与终点', '不是必须经过的点',
                                 '绝对值不超过 100000 的有限数', '拒绝事实、空、句与其他类型',
                                 '点重合、共线、起终点相同与全部重合均合法', '不自行补画圆点',
                                 '一次 `moveTo`', '一次 `bezierCurveTo`', '只调用一次 `stroke`',
                                 '不调用 `closePath` 或 `fill`', '忽略填色且不修改当前填色',
                                 '深复制嵌套状态', '透明颜色、描边、线宽、矩阵和裁剪',
                                 '`描边 空` 或退化曲线仍保留并计数为一条绘制命令',
                                 '2048 条／约 256 KiB', "op:'bezier'", '`transform`／`clips`',
                                 '二次贝塞尔、弦形、路径构造器、曲线查询或文字测量',
                                 'curved-bridge.ru', 'curved-bridge.rushu.json'):
                    self.assertIn(fragment, text)
                for milestone in ('折线（0.19.5／如书 0.8.5）', '弧与扇形（0.19.4／如书 0.8.4）',
                                  '真实时间（0.19.3／如书 0.8.3）', '文字对齐（0.19.2／如书 0.8.2）'):
                    self.assertIn(milestone, text)
                for stale in ('不提供贝塞尔曲线', '不提供弦形、贝塞尔曲线'):
                    self.assertNotIn(stale, text)

    def test_four_offline_cli_exports_embed_exact_current_spec_and_signature(self):
        raw = (ROOT / 'rulang/language-spec.md').read_bytes()
        spec, digest = raw.decode('utf-8'), hashlib.sha256(raw).hexdigest()
        self.assertTrue(spec.startswith('# 如语言规范 0.19.7\n'))
        for kind in ('rushu', 'ruguan'):
            for backend in ('python', 'browser-js'):
                with self.subTest(kind=kind, backend=backend):
                    output, error = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                        self.assertEqual(main([kind + '-prompt', '--target', backend]), 0)
                    prompt = output.getvalue()
                    target = kind if backend == 'python' else kind + '-browser-js'
                    self.assertEqual(prompt, generation_system_prompt(target))
                    self.assertEqual(prompt, export_prompt(kind, runtime_target=backend))
                    self.assertEqual(error.getvalue(), '')
                    self.assertEqual(prompt.count(spec), 1)
                    self.assertEqual(prompt.count('<ru-language-spec>'), 1)
                    self.assertIn(digest, prompt)
                    self.assertIn('随附规范版本：0.19.7', prompt)
                    for fragment in (SIGNATURE, '八个参数均必需', '单段三次贝塞尔曲线',
                                     '只调用一次 `stroke`', '深复制嵌套状态', '2048 条／约 256 KiB'):
                        self.assertIn(fragment, prompt)
                    if kind == 'ruguan':
                        focus = prompt.partition('<ru-language-spec>')[0]
                        for fragment in ('原生三次贝塞尔', '八参全必需', '控制点不必经过',
                                         'moveTo 加 bezierCurveTo', '只描边一次，不填充、不闭合',
                                         '矩阵、裁剪、透明样式', '退化或无描边也保留命令',
                                         '不拆成短线', '不虚构二次贝塞尔'):
                            self.assertIn(fragment, focus)

    def run_python(self):
        events, states = [], []
        host = GraphicsHost(Interpreter(stdout=io.StringIO()), events.append)
        def remember():
            scope = host.interpreter.global_scope.values
            states.append((scope['选中'][0], copy.deepcopy(scope['控制'])))
        try:
            host.interpreter.execute(parse(SOURCE.read_text(encoding='utf-8')))
            host.flush()
            remember()
            for event in INPUTS:
                host.handle(event)
                remember()
        finally:
            host.close()
        self.assertFalse([event for event in events if event['type'] == 'error'], events)
        self.assertEqual(states, expected_states())
        return [event for event in events if event['type'] == 'graphics']

    def assert_scenes(self, scenes):
        self.assertEqual(len(scenes), len(INPUTS) + 1)
        for scene, (selected, controls) in zip(scenes, expected_states()):
            self.assertEqual((scene['width'], scene['height']), (720, 480))
            self.assertFalse(scene['running'])
            self.assertEqual(set(scene['handlers']), {'mouse_down', 'key_down'})
            paths = [c for c in scene['commands'] if c['op'] == 'bezier']
            self.assertEqual(len(paths), 1)
            curve = paths[0]
            self.assertEqual([curve[k] for k in ('x1', 'y1', 'cx1', 'cy1', 'cx2', 'cy2', 'x2', 'y2')],
                             [40, 190, *controls[0], *controls[1], 560, 190])
            self.assertEqual((curve['fill'], curve['stroke'], curve['stroke_width']), ('', '#148678b8', 6))
            self.assertEqual(curve['transform'], [1, 0, 0, 1, 60, 120])
            self.assertEqual(curve['clips'], [{'x': 70, 'y': 116, 'width': 580, 'height': 234,
                                               'transform': [1, 0, 0, 1, 0, 0]}])
            control_frame = [c for c in scene['commands'] if c['op'] == 'polyline']
            self.assertEqual(len(control_frame), 1)
            self.assertEqual(control_frame[0]['points'], [[40, 190], *controls, [560, 190]])
            self.assertEqual(control_frame[0]['stroke'], '#bac8bf')
            buttons = [c for c in scene['commands'] if c['op'] == 'rect' and c['fill'] == '#e5a853']
            self.assertEqual([c['x'] for c in buttons], [374 + 98 * selected])
            for command in buttons:
                self.assertNotIn('transform', command)
                self.assertNotIn('clips', command)
            self.assertLess(len(scene['commands']), 60)
            self.assertLess(len(json.dumps(scene).encode('utf-8')), 256 * 1024)
        self.assertNotEqual(scenes[1]['commands'], scenes[0]['commands'])
        self.assertEqual(scenes[-1]['commands'], scenes[0]['commands'])
        # Limits, ignored input and later edits never rewrite an older scene.
        for previous, current in ((8, 9), (9, 10), (11, 12), (12, 13), (13, 14), (14, 15), (15, 16)):
            self.assertEqual(scenes[previous]['commands'], scenes[current]['commands'])

    def test_python_interaction_bounds_reset_and_deep_snapshots(self):
        self.assert_scenes(self.run_python())

    def run_javascript(self, source, inputs=()):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'program.mjs').write_text(compile_browser(source), encoding='utf-8')
            (path / 'run.mjs').write_text(
                "import create from './program.mjs';const events=[];"
                "const runtime=create({emit:e=>events.push(e)});"
                "const canvas_id=events.find(e=>e.type==='graphics').canvas_id;"
                "for(const event of " + json.dumps(inputs) + ")runtime.dispatch({canvas_id,event});"
                "console.log(JSON.stringify(events));", encoding='utf-8')
            result = subprocess.run([NODE, str(path / 'run.mjs')], text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        events = json.loads(result.stdout)
        self.assertFalse([event for event in events if event['type'] == 'error'], events)
        return events

    @unittest.skipUnless(NODE, 'Node required for browser-js parity')
    def test_exact_two_host_scenes_with_interaction_reset_and_deep_snapshots(self):
        python = self.run_python()
        events = self.run_javascript(SOURCE.read_text(encoding='utf-8'), INPUTS)
        javascript = [event for event in events if event['type'] == 'graphics']
        self.assert_scenes(javascript)
        self.assert_scenes(python)
        for scenes in (python, javascript):
            for scene in scenes:
                del scene['canvas_id']
        self.assertEqual(python, javascript)

    @unittest.skipUnless(NODE, 'Node required for browser-js parity')
    def test_both_call_styles_return_empty_and_freeze_nested_state(self):
        source = """观 取 外言 '如:观'. 图 取 观 其 画布 180 120.
图 其 填色 '#ffcc0080'. 图 其 描边 '#148678b8'. 图 其 线宽 6.
点 取 [10,90,30,10,120,10,160,90]. 图 其 保存.
图 其 平移 4 5. 图 其 裁剪 0 0 170 110. 图 其 缩放 (-1) 1.
显 (图 其 贝塞尔 点[0] 点[1] 点[2] 点[3] 点[4] 点[5] 点[6] 点[7]).
点[2] 取 50. 图 其 平移 8 9. 图 其 取消裁剪. 图 其 恢复.
显 (图 其 贝塞尔 起横:点[0] 起纵:点[1] 控一横:点[2] 控一纵:点[3] 控二横:点[4] 控二纵:点[5] 终横:点[6] 终纵:点[7]).
图 其 描边 空. 图 其 椭圆 0 0 4 4.
"""
        output, python = io.StringIO(), []
        host = GraphicsHost(Interpreter(stdout=output), python.append)
        try:
            host.interpreter.execute(parse(source))
            host.flush()
        finally:
            host.close()
        self.assertEqual(output.getvalue(), '空\n空\n')
        javascript = self.run_javascript(source)
        self.assertEqual(''.join(event.get('text', '') for event in javascript), '空\n空\n')
        scenes = []
        for events in (python, javascript):
            scene = [e for e in events if e['type'] == 'graphics'][0]
            first, second, dot = scene['commands']
            self.assertEqual(first['cx1'], 30)
            self.assertEqual(first['transform'], [-1, 0, 0, 1, 4, 5])
            self.assertEqual(first['clips'][0]['transform'], [1, 0, 0, 1, 4, 5])
            self.assertEqual(first['stroke'], '#148678b8')
            self.assertEqual(first['fill'], '')
            self.assertEqual(second['cx1'], 50)
            self.assertNotIn('transform', second)
            self.assertNotIn('clips', second)
            self.assertEqual(dot['fill'], '#ffcc0080')
            self.assertEqual(dot['stroke'], '')
            scene.pop('canvas_id')
            scenes.append(scene)
        self.assertEqual(*scenes)
