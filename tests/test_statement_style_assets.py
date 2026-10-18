"""Published code assets use complete-statement punctuation without new syntax."""
import importlib.util
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import unittest

from rulang.frontend import RuError, parse, style_issues
from rulang.generation import generation_system_prompt

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('style_asset_verifier', ROOT / 'tools/verify_statement_style_assets.py')
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


class StatementStyleAssetLabelTests(unittest.TestCase):
    def test_posix_and_windows_labels_share_repository_identity(self):
        for path_type, root in ((PurePosixPath, '/checkout'),
                                (PureWindowsPath, r'C:\checkout'),
                                (PureWindowsPath, r'\\server\share\checkout')):
            for relative in ('examples/hello.ru', 'rushu/examples/example.rushu.json',
                             'docs/language-review-tracker.md', 'rulang/stdlib/密.ru'):
                with self.subTest(root=root, relative=relative):
                    base = path_type(root)
                    self.assertEqual(assets.asset_label(base / relative, base), relative)

    def test_historical_exception_matches_only_its_exact_document(self):
        prefix = 'docs/language-review-tracker.md:'
        for path_type, root in ((PurePosixPath, '/checkout'),
                                (PureWindowsPath, r'C:\checkout')):
            base = path_type(root)
            for relative, expected in (
                    ('docs/language-review-tracker.md', True),
                    ('docs/language-review-tracker.md.copy', False),
                    ('docs/nested/language-review-tracker.md', False),
                    ('other/language-review-tracker.md', False)):
                with self.subTest(root=root, relative=relative):
                    label = assets.asset_label(base / relative, base) + ':fence:4'
                    self.assertEqual(label.startswith(prefix), expected)

    def test_asset_outside_checkout_is_not_relabelled_as_inside(self):
        for path, root in (
                (PurePosixPath('/other/source.ru'), PurePosixPath('/checkout')),
                (PureWindowsPath(r'C:\other\source.ru'), PureWindowsPath(r'C:\checkout')),
                (PureWindowsPath(r'D:\checkout\source.ru'), PureWindowsPath(r'C:\checkout'))):
            with self.subTest(path=path), self.assertRaises(ValueError):
                assets.asset_label(path, root)


@unittest.skipUnless(shutil.which('node'), 'Node loads the actual notebook templates')
class StatementStyleAssetsTests(unittest.TestCase):
    def test_complete_published_sources_parse_without_style_warnings(self):
        checked, historical = 0, 0
        for label, source in assets.sources(ROOT):
            with self.subTest(asset=label):
                self.assertNotIn('\\', label)
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
