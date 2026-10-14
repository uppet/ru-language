"""Versioned open-path contract and one self-contained, two-host line chart."""
import contextlib
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
SOURCE = ROOT / 'rushu/examples/ruguan/weekly-temperature.ru'
BOOK = ROOT / 'rushu/examples/weekly-temperature.rushu.json'
NODE = shutil.which('node')
ORIGINAL = [16, 18, 17, 23, 21, 26, 24]
DAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
KEY = lambda key: {'type': 'key_down', 'key': key}
MOUSE = lambda x, y, button=0: {'type': 'mouse_down', 'x': x, 'y': y, 'button': button}
INPUTS = ([KEY('ArrowUp')] * 8 + [KEY('ArrowDown')] * 21 + [KEY('ArrowUp')]
          + [MOUSE(88, 250), KEY('ArrowLeft'), KEY('ArrowLeft')]
          + [KEY('ArrowRight')] * 7
          + [MOUSE(487, 401), MOUSE(569, 401), KEY('unhandled'),
             MOUSE(12, 12), MOUSE(88, 250, 2), KEY('r')])


def expected_states():
    temperatures = ORIGINAL.copy()
    states = [(3, temperatures.copy())]
    for value in [24, 25, 26, 27, 28, 29, 30, 30] + list(range(29, 9, -1)) + [10, 11]:
        temperatures[3] = value
        states.append((3, temperatures.copy()))
    for selected in [0, 0, 0, 1, 2, 3, 4, 5, 6, 6]:
        states.append((selected, temperatures.copy()))
    temperatures[6] = 23
    states.append((6, temperatures.copy()))
    temperatures[6] = 24
    states.append((6, temperatures.copy()))
    states.extend((6, temperatures.copy()) for _ in range(3))
    states.append((3, ORIGINAL.copy()))
    assert len(states) == len(INPUTS) + 1
    return states


class GraphicsPolylineExamplesTests(unittest.TestCase):
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
        for fragment in ("外言 '如:观'", "外言 '如:数学'", '图 其 折线 点阵.',
                         '图 其 折线 点阵:点阵.', '点阵[位][1] 取',
                         '图 其 鼠标按下', '图 其 按键', 'ArrowLeft', 'ArrowRight',
                         'ArrowUp', 'ArrowDown', '若 气温[位] < 10', '若 气温[位] > 30'):
            self.assertIn(fragment, source)
        self.assertNotIn('图 其 每帧', source)

    def test_spec_and_guide_define_one_precise_open_path_contract(self):
        for filename in ('rulang/language-spec.md', 'docs/ruguan-guide.md'):
            with self.subTest(document=filename):
                text = (ROOT / filename).read_text(encoding='utf-8')
                for fragment in ('折线（0.19.5／如书 0.8.5）', '图 其 折线 点阵',
                                 '返回空，不是新增保留字', '唯一的 `点阵` 参数必需',
                                 '命名调用 `图 其 折线 点阵:', '2～256 个点',
                                 '每个点也必须是阵且恰有两个坐标',
                                 '绝对值不超过 100000 的有限数', '拒绝事实、空、句与其他类型',
                                 '所有点相同均合法', '不自行补画圆点',
                                 '一次 `moveTo`', '逐点 `lineTo`', '只调用一次 `stroke`',
                                 '不会自动首尾闭合', '不调用 `closePath` 或 `fill`',
                                 '末点与首点相同', '忽略填色且不修改当前填色',
                                 '不能逐段绘制', '半透明折点重复叠色', '使用既有 `多边形`',
                                 '深复制外层点阵及各点坐标', '变换、裁剪、描边和线宽',
                                 '`描边 空` 或零长度折线仍保留并计数为一条绘制命令',
                                 '2048 条／约 256 KiB', '贝塞尔曲线、路径构造器或文字测量',
                                 'weekly-temperature.ru', 'weekly-temperature.rushu.json'):
                    self.assertIn(fragment, text)
                for milestone in ('弧与扇形（0.19.4／如书 0.8.4）',
                                  '真实时间（0.19.3／如书 0.8.3）',
                                  '文字对齐（0.19.2／如书 0.8.2）'):
                    self.assertIn(milestone, text)
                self.assertNotIn('不提供弦形、折线', text)

    def test_four_offline_cli_exports_embed_exact_current_spec_and_signature(self):
        raw = (ROOT / 'rulang/language-spec.md').read_bytes()
        spec, digest = raw.decode('utf-8'), hashlib.sha256(raw).hexdigest()
        self.assertTrue(spec.startswith('# 如语言规范 0.19.5\n'))
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
                    self.assertIn('随附规范版本：0.19.5', prompt)
                    for fragment in ('图 其 折线 点阵', '唯一的 `点阵` 参数必需',
                                     '2～256 个点', '深复制外层点阵及各点坐标',
                                     '只调用一次 `stroke`', '2048 条／约 256 KiB'):
                        self.assertIn(fragment, prompt)
                    if kind == 'ruguan':
                        focus = prompt.partition('<ru-language-spec>')[0]
                        for fragment in ('数据曲线与路线使用原生折线', '位置或点阵:调用',
                                         '开放路径只描边一次', '不逐段模拟半透明折点',
                                         '折线深复制顶点和绘制状态', '空描边或零长度仍计入原有预算'):
                            self.assertIn(fragment, focus)

    def run_python(self):
        events, states = [], []
        host = GraphicsHost(Interpreter(stdout=io.StringIO()), events.append)
        def remember():
            scope = host.interpreter.global_scope.values
            states.append((scope['选中'][0], scope['气温'].copy()))
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
        original_points = [[88 + 90 * i, 150 + (30 - t) * 8] for i, t in enumerate(ORIGINAL)]
        for scene, (selected, temperatures) in zip(scenes, expected_states()):
            self.assertEqual((scene['width'], scene['height']), (720, 480))
            self.assertFalse(scene['running'])
            self.assertEqual(set(scene['handlers']), {'mouse_down', 'key_down'})
            paths = [command for command in scene['commands'] if command['op'] == 'polyline']
            self.assertEqual(len(paths), 2)
            # The same outer array and all inner vertices were reused for the
            # second path; the first command must keep its original coordinates.
            self.assertEqual(paths[0]['points'], original_points)
            self.assertEqual(paths[1]['points'], [[88 + 90 * i, 150 + (30 - t) * 8]
                                                  for i, t in enumerate(temperatures)])
            self.assertEqual([command['stroke'] for command in paths], ['#a9b7af', '#148678b8'])
            self.assertEqual([command['stroke_width'] for command in paths], [3, 5])
            self.assertEqual([command['fill'] for command in paths], ['', ''])
            self.assertLess(len(scene['commands']), 100)
            self.assertLess(len(json.dumps(scene).encode('utf-8')), 256 * 1024)
            labels = {(c['x'], c['y']): c['text'] for c in scene['commands'] if c['op'] == 'text'}
            self.assertEqual(labels[42, 400], DAYS[selected])
            self.assertEqual(labels[112, 400], str(temperatures[selected]) + ' ℃')
        self.assertNotEqual(scenes[1]['commands'], scenes[0]['commands'])
        self.assertEqual(scenes[-1]['commands'], scenes[0]['commands'])
        # Unknown keys, clicks outside the controls, and non-primary buttons do
        # not draw and preserve the previous complete scene.
        self.assertEqual(scenes[-5]['commands'], scenes[-4]['commands'])
        self.assertEqual(scenes[-4]['commands'], scenes[-3]['commands'])
        self.assertEqual(scenes[-3]['commands'], scenes[-2]['commands'])

    def test_python_chart_interaction_bounds_and_vertex_deep_copy(self):
        self.assert_scenes(self.run_python())

    @unittest.skipUnless(NODE, 'Node required for browser-js parity')
    def test_exact_two_host_scenes_with_edits_reset_and_deep_copied_vertices(self):
        python = self.run_python()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'program.mjs').write_text(compile_browser(SOURCE.read_text(encoding='utf-8')), encoding='utf-8')
            (path / 'run.mjs').write_text(
                "import create from './program.mjs';const events=[];"
                "const runtime=create({emit:e=>events.push(e)});"
                "const canvas_id=events.find(e=>e.type==='graphics').canvas_id;"
                "for(const event of " + json.dumps(INPUTS) + ")runtime.dispatch({canvas_id,event});"
                "console.log(JSON.stringify(events));", encoding='utf-8')
            result = subprocess.run([NODE, str(path / 'run.mjs')], text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        events = json.loads(result.stdout)
        self.assertFalse([event for event in events if event['type'] == 'error'], events)
        javascript = [event for event in events if event['type'] == 'graphics']
        self.assert_scenes(javascript)
        self.assert_scenes(python)
        for scenes in (python, javascript):
            for scene in scenes:
                del scene['canvas_id']
        self.assertEqual(python, javascript)
