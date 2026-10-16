"""Versioned arc contract and one source, two-host interactive portion chart."""
import contextlib
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from rulang import __version__
from rulang.browser_compiler import compile_browser
from rulang.cli import main
from rulang.frontend import parse, validate
from rulang.generation import generation_system_prompt
from rulang.graphics_runtime import GraphicsHost
from rulang.interpreter import Interpreter
from rulang.prompts import export_prompt

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'rushu/examples/ruguan/pizza-portions.ru'
BOOK = ROOT / 'rushu/examples/pizza-portions.rushu.json'
NODE = shutil.which('node')
INPUTS = [
    {'type': 'key_down', 'key': 'ArrowLeft'},
    {'type': 'key_down', 'key': 'ArrowRight'},
    {'type': 'key_down', 'key': '0'},
    {'type': 'key_down', 'key': 'ArrowLeft'},
    {'type': 'key_down', 'key': '8'},
    {'type': 'key_down', 'key': 'ArrowRight'},
    {'type': 'mouse_down', 'x': 431, 'y': 328, 'button': 0},
    {'type': 'mouse_down', 'x': 557, 'y': 328, 'button': 0},
    {'type': 'mouse_down', 'x': 12, 'y': 12, 'button': 0},
    {'type': 'mouse_down', 'x': 431, 'y': 328, 'button': 2},
]
PORTIONS = [3, 2, 3, 0, 0, 8, 8, 7, 8, 8, 8]


class GraphicsArcExamplesTests(unittest.TestCase):
    def test_notebook_is_clean_and_uses_exactly_the_same_source(self):
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
        for fragment in ("外言 '如:观'", "外言 '如:数学'", '状态 取 [3]', '图 其 弧 ',
                         '图 其 扇形 横:', '图 其 鼠标按下', '图 其 按键', 'ArrowLeft', 'ArrowRight'):
            self.assertIn(fragment, source)
        self.assertNotIn('图 其 每帧', source)

    def test_spec_and_guide_cover_exact_signed_native_geometry_contract(self):
        for filename in ('rulang/language-spec.md', 'docs/ruguan-guide.md'):
            with self.subTest(document=filename):
                text = (ROOT / filename).read_text(encoding='utf-8')
                for fragment in ('弧与扇形（0.19.4／如书 0.8.4）',
                                 '图 其 弧 横 纵 宽 高 始角 转角', '图 其 扇形 横 纵 宽 高 始角 转角',
                                 '返回空，不是新增保留字', '六个参数均必需',
                                 '`横:`、`纵:`、`宽:`、`高:`、`始角:`、`转角:`',
                                 '绝对值不超过 100000 的有限数', '零宽或零高合法',
                                 '转角是带符号的扫过量，不是终止角', '正转角顺时针，负转角逆时针',
                                 '负倍率缩放会把视觉方向一并镜像',
                                 '(cx + rx*cos(θ), cy + ry*sin(θ))', '不是从中心看端点的几何极角',
                                 '`转角 == 0` 不绘制像素', '仍保留并计数为一条绘制命令',
                                 '`abs(转角) >= 2π`', '不对转角取模归零', '没有中心径向辐条',
                                 '只使用当前描边和线宽，忽略填色', '描边包含两条半径边',
                                 'nonzero（非零环绕）', '2048 条／约 256 KiB',
                                 '不提供弦形、二次贝塞尔或路径构造器',
                                 'pizza-portions.ru', 'pizza-portions.rushu.json'):
                    self.assertIn(fragment, text)
                # Previous release headings remain historical and accurate.
                self.assertIn('真实时间（0.19.3／如书 0.8.3）', text)
                self.assertIn('文字对齐（0.19.2／如书 0.8.2）', text)

    def test_four_cli_exports_have_one_complete_spec_and_arc_focus(self):
        raw = (ROOT / 'rulang/language-spec.md').read_bytes()
        spec, digest = raw.decode('utf-8'), hashlib.sha256(raw).hexdigest()
        self.assertTrue(spec.startswith(f'# 如语言规范 {__version__}\n'))
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
                    self.assertIn(f'随附规范版本：{__version__}', prompt)
                    for name in ('弧', '扇形'):
                        self.assertIn('图 其 ' + name + ' 横 纵 宽 高 始角 转角', prompt)
                    if kind == 'ruguan':
                        focus = prompt.partition('<ru-language-spec>')[0]
                        for fragment in ('原生弧／扇形', '带符号转角', '弧只描边',
                                         '零转角保留命令', '无辐条的整椭圆', '非圆椭圆使用参数角',
                                         '不要用折线近似', '二次贝塞尔、路径构造器'):
                            self.assertIn(fragment, focus)

    def run_python(self):
        events, states = [], []
        host = GraphicsHost(Interpreter(stdout=io.StringIO()), events.append)
        try:
            host.interpreter.execute(parse(SOURCE.read_text(encoding='utf-8')))
            host.flush()
            states.append(host.interpreter.global_scope.values['状态'][0])
            for event in INPUTS:
                host.handle(event)
                states.append(host.interpreter.global_scope.values['状态'][0])
            self.assertEqual(host.interpreter.global_scope.values['状态'], [8])
        finally:
            host.close()
        self.assertEqual(states, PORTIONS)
        scenes = [event for event in events if event['type'] == 'graphics']
        # Ignored inputs retain the previous complete scene.
        self.assertEqual(scenes[-3]['commands'], scenes[-2]['commands'])
        self.assertEqual(scenes[-2]['commands'], scenes[-1]['commands'])
        return scenes

    def assert_scenes(self, scenes):
        self.assertEqual(len(scenes), len(PORTIONS))
        for scene, count in zip(scenes, PORTIONS):
            self.assertEqual((scene['width'], scene['height']), (680, 440))
            self.assertFalse(scene['running'])
            self.assertEqual(set(scene['handlers']), {'mouse_down', 'key_down'})
            shapes = [c for c in scene['commands'] if c['op'] in ('arc', 'sector')]
            self.assertEqual([c['op'] for c in shapes], ['sector', 'sector', 'sector', 'arc', 'arc'])
            self.assertAlmostEqual(shapes[2]['sweep'], count * math.tau / 8)
            self.assertAlmostEqual(shapes[4]['sweep'], count * math.tau / 8)
            self.assertAlmostEqual(shapes[0]['sweep'], math.tau)
            self.assertAlmostEqual(shapes[3]['sweep'], math.tau)
            self.assertTrue(all(c['fill'] == '' for c in shapes if c['op'] == 'arc'))
            labels = {(c['x'], c['y']): c['text'] for c in scene['commands'] if c['op'] == 'text'}
            self.assertEqual(labels[376, 185], f'{count} / 8')
            percent = str(count * 12.5).removesuffix('.0')
            self.assertEqual(labels[376, 232], percent + '% 的一整个')

    def test_python_demo_interaction_limits_and_native_commands(self):
        self.assert_scenes(self.run_python())

    @unittest.skipUnless(NODE, 'Node required for browser-js parity')
    def test_same_source_and_inputs_have_matching_two_host_scenes(self):
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
        for scenes in (python, javascript):
            for scene in scenes:
                del scene['canvas_id']
        self.assertEqual(python, javascript)
