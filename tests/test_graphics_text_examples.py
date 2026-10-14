"""Runnable text-anchor documentation and one canonical example in both hosts."""
import hashlib
import json
from pathlib import Path
import unittest

from rulang.frontend import parse, validate
from rulang.generation import generation_system_prompt
from rulang.prompts import export_prompt
import test_graphics_state_parity as graphics_state_parity

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / 'rushu/examples/ruguan/text-alignment.ru'
BOOK_PATH = ROOT / 'rushu/examples/text-alignment.rushu.json'


class GraphicsTextExamplesTests(unittest.TestCase):
    def test_notebook_and_source_are_one_clean_self_contained_example(self):
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
        for fragment in ("横向:'中' 纵向:'中'", "['左', '中', '右']",
                         "['上', '中', '下', '基线']", '图 其 保存.',
                         '图 其 恢复.', '图 其 裁剪', '图 其 旋转', "'#007f82c0'"):
            self.assertIn(fragment, source)

    def test_documents_define_the_same_alignment_and_compatibility_contract(self):
        for path in ('rulang/language-spec.md', 'docs/ruguan-guide.md'):
            with self.subTest(document=path):
                text = (ROOT / path).read_text(encoding='utf-8')
                for fragment in ('文字对齐（0.19.2／如书 0.8.2）',
                                 '图 其 文字对齐 横向 纵向', '两个参数均必需',
                                 '横向:', '纵向:', "'左'", "'中'", "'右'",
                                 "'上'", "'下'", "'基线'", '默认左／上',
                                 'left', 'center', 'right', 'top', 'middle', 'bottom',
                                 'alphabetic', '字体 em 框', '不保证可见字形墨迹包围盒精确居中',
                                 '跨回调保留', '旧书本中缺少对齐字段的静态文字按左／上重放',
                                 '单行', '没有文字测量', '时间接口',
                                 'text-alignment.ru', 'text-alignment.rushu.json'):
                    self.assertIn(fragment, text)
                self.assertNotIn('文字位置是文字框左上角', text)
                self.assertNotIn('文字横纵是文字框左上角', text)

    def test_all_generation_targets_receive_exactly_one_complete_current_spec(self):
        raw = (ROOT / 'rulang/language-spec.md').read_bytes()
        specification = raw.decode('utf-8')
        digest = hashlib.sha256(raw).hexdigest()
        for target in ('cli', 'rushu', 'ruguan', 'rushu-browser-js', 'ruguan-browser-js'):
            with self.subTest(target=target):
                prompt = generation_system_prompt(target)
                self.assertEqual(prompt.count(specification), 1)
                self.assertEqual(prompt.count('<ru-language-spec>'), 1)
                self.assertIn(digest, prompt)
                self.assertIn('文字对齐（0.19.2／如书 0.8.2）', prompt)
                self.assertIn('两个参数均必需', prompt)
                self.assertIn('字体 em 框', prompt)
                if target.startswith('ruguan'):
                    guidance = prompt.partition('<ru-language-spec>')[0]
                    self.assertIn('文字居中优先使用规范中的文字对齐与锚点', guidance)
                    self.assertIn('不靠字符数猜宽度', guidance)
                    self.assertIn('不要虚构文字测量接口', guidance)

    def test_offline_prompt_exports_use_the_same_builder_for_both_backends(self):
        for target in ('rushu', 'ruguan'):
            for backend in ('python', 'browser-js'):
                with self.subTest(target=target, backend=backend):
                    generated_target = target if backend == 'python' else target + '-browser-js'
                    self.assertEqual(export_prompt(target, runtime_target=backend),
                                     generation_system_prompt(generated_target))

    @unittest.skipUnless(graphics_state_parity.NODE, 'Node required for backend parity')
    def test_reference_diagram_emits_the_same_scene_in_both_backends(self):
        source = SOURCE_PATH.read_text(encoding='utf-8')
        scenes = graphics_state_parity.GraphicsStateParityTests.compare(self, source)
        self.assertEqual(len(scenes), 1)
        scene = scenes[0]
        self.assertEqual((scene['width'], scene['height']), (760, 600))
        self.assertFalse(scene['running'])
        self.assertEqual(scene['handlers'], [])
        commands = scene['commands']
        texts = [command for command in commands if command['op'] == 'text']
        horizontal = [command for command in texts if command['text'] == '如观 Ru']
        self.assertEqual([command.get('align', 'left') for command in horizontal], ['left', 'center', 'right'])
        self.assertEqual([command.get('baseline', 'top') for command in horizontal], ['middle'] * 3)
        self.assertEqual([command['x'] for command in horizontal], [240] * 3)
        vertical = [command for command in texts if command['text'] == '如 Ag']
        self.assertEqual([command.get('align', 'left') for command in vertical], ['center'] * 4)
        self.assertEqual([command.get('baseline', 'top') for command in vertical],
                         ['top', 'middle', 'bottom', 'alphabetic'])
        self.assertEqual([command['y'] for command in vertical], [260] * 4)
        transformed = next(command for command in texts if command['text'] == '如观 / centered')
        self.assertEqual((transformed['align'], transformed['baseline']), ('center', 'middle'))
        self.assertEqual(transformed['color'], '#007f82c0')
        self.assertEqual(transformed['size'], 26)
        self.assertIn('transform', transformed)
        self.assertEqual(len(transformed['clips']), 1)
        restored = next(command for command in texts if command['text'] == '恢复后：左上 / restored')
        self.assertEqual((restored.get('align', 'left'), restored.get('baseline', 'top')), ('left', 'top'))
        self.assertEqual((restored['color'], restored['size']), ('#1c3554', 18))
        self.assertNotIn('transform', restored)
        self.assertNotIn('clips', restored)
