"""Current time contract, prompt synchronization and a deterministic two-host demo."""
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from rulang.browser_compiler import compile_browser
from rulang.frontend import parse, validate
from rulang.generation import generation_system_prompt
from rulang.graphics_runtime import GraphicsHost
from rulang.interpreter import Interpreter
from rulang.prompts import export_prompt

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / 'rushu/examples/ruguan/elapsed-time.ru'
BOOK_PATH = ROOT / 'rushu/examples/elapsed-time.rushu.json'
NODE = shutil.which('node')

# These are host-monotonic samples, never event payload fields. The large gap
# stands for delayed delivery (for example a hidden tab), not stop/resume.
SCRIPT = [
    (105, {'type': 'mouse_down', 'x': 360, 'y': 420, 'button': 0}),
    (105.25, {'type': 'frame'}),
    (105.75, {'type': 'frame'}),
    (106, {'type': 'key_down', 'key': ' '}),
    (109, {'type': 'key_down', 'key': 'r'}),
    (109.25, {'type': 'frame'}),
    (109.75, {'type': 'frame'}),
    (118, {'type': 'frame'}),
    (120, {'type': 'mouse_down', 'x': 360, 'y': 420, 'button': 0}),
    (120.25, {'type': 'frame'}),
    (128, {'type': 'frame'}),
]


class GraphicsTimeExamplesTests(unittest.TestCase):
    def test_notebook_source_is_clean_self_contained_and_synchronized(self):
        source = SOURCE_PATH.read_text(encoding='utf-8')
        book = json.loads(BOOK_PATH.read_text(encoding='utf-8'))
        self.assertEqual((book['format'], book['version']), ('rushu-notebook', 1))
        code = [cell for cell in book['cells'] if cell['type'] == 'code']
        self.assertEqual(len(code), 1)
        self.assertEqual(code[0]['source'], source)
        for cell in book['cells']:
            self.assertIsNone(cell['execution_count'])
            self.assertEqual(cell['outputs'], [])
        validate(parse(source))
        for fragment in ("状态 取 ['待发', 0, 0, 0, 0]", '图 其 经过秒', '图 其 间隔秒',
                         '图 其 每帧 (作 帧:', '图 其 停.', '图 其 继续.',
                         "状态[0] 取 '暂停'", "状态[0] 取 '抵达'",
                         '状态[1] + (图 其 经过秒) - 状态[2]',
                         '若 步 > 0.05 则 步 取 0.05. 然', '图 其 保存.', '图 其 恢复.'):
            self.assertIn(fragment, source)
        self.assertNotRegex(source, r'帧\s*[/％%]')
        self.assertNotIn('经过秒()', source)
        self.assertNotIn('间隔秒()', source)

    def test_spec_and_guide_define_raw_callback_time_and_lifecycle(self):
        for name in ('rulang/language-spec.md', 'docs/ruguan-guide.md'):
            with self.subTest(document=name):
                text = (ROOT / name).read_text(encoding='utf-8')
                for fragment in ('真实时间（0.19.3／如书 0.8.3）', '图 其 经过秒', '图 其 间隔秒',
                                 '只读、零参、返回数', '创建画布时两者均为 0', '单调时钟',
                                 '冻结的同一快照', '自本画布创建起', '首帧为 0',
                                 '第一帧也为 0', '输入回调的 `间隔秒` 为 0',
                                 '不改写上一帧基准', '已经运行时重复 `继续`',
                                 '重新注册 `每帧`', '既不钳位也不补帧',
                                 '只接收一个从 1 开始的帧序号', '不保证不同平台一致',
                                 '客户端传来的时间值不能覆盖宿主采样',
                                 '忙循环不能等待时间变化', '不延长回调预算',
                                 '自己的积分步长', '0.05 秒', '经过秒 - 开始秒',
                                 '不恢复时间基准或回调', 'elapsed-time.ru',
                                 'elapsed-time.rushu.json'):
                    self.assertIn(fragment, text)
                for obsolete in ('或时间接口', '文字测量与时间接口仍未提供',
                                 '应等待后续明确的计时接口'):
                    self.assertNotIn(obsolete, text)
                # Earlier milestones retain their historical scopes.
                self.assertIn('文字对齐（0.19.2／如书 0.8.2）', text)
                self.assertIn('透明度与颜色（0.19.1／如书 0.8.1）', text)
                self.assertIn('文字测量仍未提供', text)

    def test_all_prompts_embed_exactly_one_complete_current_spec(self):
        raw = (ROOT / 'rulang/language-spec.md').read_bytes()
        spec = raw.decode('utf-8')
        digest = hashlib.sha256(raw).hexdigest()
        self.assertTrue(spec.startswith('# 如语言规范 0.19.3\n'))
        for target in ('cli', 'rushu', 'ruguan', 'rushu-browser-js', 'ruguan-browser-js'):
            with self.subTest(target=target):
                prompt = generation_system_prompt(target)
                self.assertEqual(prompt.count(spec), 1)
                self.assertEqual(prompt.count('<ru-language-spec>'), 1)
                self.assertIn(digest, prompt)
                self.assertIn('随附规范版本：0.19.3', prompt)
                if target.startswith('ruguan'):
                    guidance = prompt.partition('<ru-language-spec>')[0]
                    for fragment in ('经过秒／间隔秒', '不把帧数除目标帧率当真实时间',
                                     '每帧回调仍只有帧序号一参'):
                        self.assertIn(fragment, guidance)
                    self.assertIn('跨帧状态写入共享形或阵', guidance)
                    self.assertIn('原始间隔秒仍保留真实间隔', guidance)
                    self.assertIn('不要虚构文字测量接口', guidance)
        for target in ('rushu', 'ruguan'):
            for backend in ('python', 'browser-js'):
                generated_target = target if backend == 'python' else target + '-browser-js'
                self.assertEqual(export_prompt(target, runtime_target=backend),
                                 generation_system_prompt(generated_target))

    def run_python_demo(self):
        now, samples, events, states = [100], [], [], []
        def clock():
            samples.append(now[0])
            return now[0]
        host = GraphicsHost(Interpreter(stdout=io.StringIO()), events.append, now_seconds=clock)
        try:
            host.interpreter.execute(parse(SOURCE_PATH.read_text(encoding='utf-8')))
            host.flush()
            states.append(list(host.interpreter.global_scope.values['状态']))
            for instant, event in SCRIPT:
                now[0] = instant
                host.handle(event)
                states.append(list(host.interpreter.global_scope.values['状态']))
            self.assertEqual(samples, [100] + [instant for instant, _ in SCRIPT])
        finally:
            host.close()
        return [event for event in events if event['type'] == 'graphics'], states

    def assert_demo_scenes(self, scenes):
        self.assertEqual(len(scenes), len(SCRIPT) + 1)
        self.assertEqual([scene['running'] for scene in scenes],
                         [False, True, True, True, False, True, True, True, False, True, True, False])
        modes = ['待发', '航行', '航行', '航行', '暂停', '航行', '航行', '航行', '抵达', '航行', '航行', '抵达']
        elapsed = ['0', '5', '5.25', '5.75', '6', '9', '9.25', '9.75', '18', '20', '20.25', '28']
        delta = ['0', '0', '0', '0.5', '0', '0', '0', '0.5', '8.25', '0', '0', '7.75']
        percent = ['0', '0', '3', '9', '12', '12', '15', '21', '100', '0', '3', '100']
        for index, scene in enumerate(scenes):
            self.assertEqual((scene['width'], scene['height'], scene['fps']), (720, 500, 20))
            self.assertEqual(set(scene['handlers']), {'frame', 'mouse_down', 'key_down'})
            labels = {(c['x'], c['y']): c['text'] for c in scene['commands'] if c['op'] == 'text'}
            self.assertEqual(labels[96, 420], modes[index])
            self.assertEqual(labels[46, 142], elapsed[index])
            self.assertEqual(labels[270, 142], delta[index])
            self.assertEqual(labels[494, 142], percent[index])
        self.assertEqual(next(c for c in scenes[8]['commands'] if c.get('text') == '再次出发')['x'], 360)

    def test_demo_pause_resume_delayed_delivery_and_restart_in_python(self):
        scenes, states = self.run_python_demo()
        self.assert_demo_scenes(scenes)
        # The elapsed clock keeps its creation origin; only application state
        # offsets the three-second pause. No outer scalar rebinding is needed.
        self.assertEqual(states[4], ['暂停', 5, 6, .125, .1])
        self.assertEqual(states[5], ['航行', 8, 6, .125, .1])
        self.assertAlmostEqual(states[8][4], .3)  # Large raw gap, one capped integration step.
        self.assertEqual(states[9], ['航行', 20, 0, 0, 0])
        self.assertEqual(states[-1][0], '抵达')
        self.assertEqual(states[-1][3], 1)

    @unittest.skipUnless(NODE, 'Node required for backend parity')
    def test_demo_scenes_match_with_the_same_injected_host_clock(self):
        python, _ = self.run_python_demo()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            source = SOURCE_PATH.read_text(encoding='utf-8')
            (path / 'program.mjs').write_text(compile_browser(source), encoding='utf-8')
            (path / 'run.mjs').write_text(
                "import create from './program.mjs';let now=100;const events=[],samples=[];"
                "const runtime=create({emit:e=>events.push(e),nowSeconds:()=>{samples.push(now);return now;}});"
                "const canvas_id=events.find(e=>e.type==='graphics').canvas_id;"
                "for(const [instant,event] of " + json.dumps(SCRIPT) + ")"
                "{now=instant;runtime.dispatch({canvas_id,event});}"
                "console.log(JSON.stringify({samples,scenes:events.filter(e=>e.type==='graphics')}));",
                encoding='utf-8')
            result = subprocess.run([NODE, str(path / 'run.mjs')], text=True,
                                    capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['samples'], [100] + [instant for instant, _ in SCRIPT])
        javascript = output['scenes']
        self.assert_demo_scenes(javascript)
        for emitted in (python, javascript):
            for event in emitted:
                del event['canvas_id']
        def compare(left, right):
            if isinstance(left, (int, float)) and not isinstance(left, bool):
                self.assertIsInstance(right, (int, float))
                self.assertNotIsInstance(right, bool)
                self.assertTrue(math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12), (left, right))
            elif isinstance(left, dict):
                self.assertEqual(left.keys(), right.keys())
                for key in left:
                    compare(left[key], right[key])
            elif isinstance(left, list):
                self.assertEqual(len(left), len(right))
                for a, b in zip(left, right):
                    compare(a, b)
            else:
                self.assertEqual(left, right)
        compare(python, javascript)
