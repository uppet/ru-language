"""Published code assets use complete-statement punctuation without new syntax."""
import importlib.util
from pathlib import Path
import shutil
import unittest

from rulang.frontend import RuError, parse, style_issues
from rulang.generation import generation_system_prompt

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('style_asset_verifier', ROOT / 'tools/verify_statement_style_assets.py')
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


@unittest.skipUnless(shutil.which('node'), 'Node loads the actual notebook templates')
class StatementStyleAssetsTests(unittest.TestCase):
    def test_complete_published_sources_parse_without_style_warnings(self):
        checked, historical = 0, 0
        for label, source in assets.sources(ROOT):
            with self.subTest(asset=label):
                try:
                    parse(source)
                except RuError:
                    # These two fenced migration counterexamples deliberately use
                    # the removed two-token import spelling; never auto-format them.
                    self.assertTrue(label.startswith('docs/language-review-tracker.md:'))
                    self.assertIn('尽 取 外言', source)
                    historical += 1
                    continue
                self.assertEqual(style_issues(source), [])
                checked += 1
        self.assertGreaterEqual(checked, 222)
        self.assertEqual(historical, 2)

    def test_exported_prompts_teach_statement_and_expression_boundaries(self):
        for target in ('cli', 'rushu', 'ruguan', 'rushu-browser-js', 'ruguan-browser-js'):
            with self.subTest(target=target):
                prompt = generation_system_prompt(target)
                self.assertIn('完整语句统一以句点结束', prompt)
                self.assertIn('括号或阵内的匿名字面量结束词后不得多加点', prompt)
                self.assertIn('形 名:、试:、救 原因:', prompt)


if __name__ == '__main__':
    unittest.main()
