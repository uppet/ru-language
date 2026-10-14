"""Keep the compact alpha demo and its notebook aligned with the color contract."""
import json
from pathlib import Path
import unittest

from rulang.frontend import parse, validate

ROOT = Path(__file__).resolve().parents[1]


class GraphicsAlphaDocsTests(unittest.TestCase):
    def test_demo_is_one_self_contained_source_in_both_formats(self):
        source = (ROOT / 'rushu/examples/ruguan/alpha-colors.ru').read_text(encoding='utf-8')
        book = json.loads((ROOT / 'rushu/examples/alpha-colors.rushu.json').read_text(encoding='utf-8'))
        self.assertEqual((book['format'], book['version']), ('rushu-notebook', 1))
        code = [cell for cell in book['cells'] if cell['type'] == 'code']
        self.assertEqual(len(code), 1)
        self.assertEqual(code[0]['source'], source)
        for cell in book['cells']:
            self.assertIsNone(cell['execution_count'])
            self.assertEqual(cell['outputs'], [])
        validate(parse(source))
        self.assertIn("背景 '#00000000'", source)
        self.assertIn('颜色 255 80 80 144', source)
        self.assertIn('颜色 红:55 绿:120 蓝:255 不透明度:144', source)
        self.assertIn("填色 '#22b88790'", source)
        self.assertIn('填色 空', source)
        self.assertIn('描边 空', source)

    def test_color_docs_retain_required_arguments_and_redraw_boundary(self):
        for name in ('rulang/language-spec.md', 'docs/ruguan-guide.md'):
            with self.subTest(document=name):
                text = (ROOT / name).read_text(encoding='utf-8')
                for contract in ('颜色 红 绿 蓝 不透明度', '#RRGGBBAA', '四个参数均必需',
                                 '不钳位、不舍入', '不保留上一帧像素', '透明底上完整重绘'):
                    self.assertIn(contract, text)
                self.assertNotIn('颜色只接受 `#RRGGBB`，', text)
