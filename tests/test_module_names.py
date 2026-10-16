"""Canonical standard-module names, migration diagnostics and I/O boundaries."""
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rulang.browser_compiler import ALLOWED_MODULES, browser_graph
from rulang.compiler import Compiler
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter
from rulang.js_compiler import JSCompiler
from rulang.modules import STANDARD_MODULES, load_module_graph, resolve_import

ROOT = Path(__file__).resolve().parents[1]
RENAMED = {'如观': '如:观', '如竞': '如:竞', '如:竞赛': '如:竞'}


class ModuleNameTests(unittest.TestCase):
    def test_canonical_names_are_the_only_standard_names(self):
        expected = {'如:观', '如:竞', '如:文本', '如:数学', '如:随机', '如:密'}
        self.assertEqual(set(STANDARD_MODULES), expected)
        self.assertEqual(ALLOWED_MODULES, expected - {'如:密'})
        for name, filename in STANDARD_MODULES.items():
            self.assertEqual(resolve_import(name, '/tmp/main.ru'),
                             str((ROOT / 'rulang' / 'stdlib' / filename).resolve()))
        graph = browser_graph("观 取 外言 '如:观'. 竞 取 外言 '如:竞'. 显 (竞 其 小 2 3).")
        self.assertEqual(len(graph), 3)

    def test_old_names_fail_before_file_read_in_every_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            main = Path(directory) / 'main.ru'
            for old, new in RENAMED.items():
                if os.name != 'nt' or ':' not in old:
                    (Path(directory) / old).write_text("卒 'must not execute'.", encoding='utf-8')
                code = f"若 不实 则\n 外言 '{old}'.\n然"
                expected = f"标准外言「{old}」已改名为「{new}」；请改用 外言 '{new}'"
                loaders = (
                    lambda: load_module_graph(main, parse(code)),
                    lambda: Compiler(parse(code), str(main)),
                    lambda: JSCompiler(parse(code), str(main)),
                    lambda: browser_graph(code),
                )
                for loader in loaders:
                    with self.subTest(old=old, loader=loader), patch.object(
                            Path, 'read_text', side_effect=AssertionError('must not read')):
                        with self.assertRaises(RuError) as caught:
                            loader()
                        self.assertEqual(caught.exception.message, expected)
                        self.assertEqual(caught.exception.category, '模块错误')
                        self.assertEqual(caught.exception.line, 2)

    def test_old_names_cli_diagnoses_all_backends(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'main.ru'
            for old, new in RENAMED.items():
                source.write_text(f"外言 '{old}'.", encoding='utf-8')
                for command in [('check',), ('run',), ('build', '--target', 'c'),
                                ('build', '--target', 'js')]:
                    with self.subTest(old=old, command=command):
                        result = subprocess.run(
                            [sys.executable, str(ROOT / 'ru'), command[0], str(source), *command[1:]],
                            capture_output=True, text=True, timeout=20)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(f"已改名为「{new}」", result.stderr)

    def test_explicit_relative_old_names_remain_local_only(self):
        with tempfile.TemporaryDirectory() as directory:
            main = Path(directory) / 'main.ru'
            for old in ('如观', '如竞'):
                local = Path(directory) / old
                local.write_text('算 值: 得 7. 法', encoding='utf-8')
                code = f"库 取 外言 './{old}'. 显 库 其 值."
                self.assertEqual(resolve_import('./' + old, str(main)), str(local.resolve()))
                graph = load_module_graph(main, parse(code))
                for compiler in (Compiler, JSCompiler):
                    self.assertTrue(compiler(graph[graph.root], str(main), modules=graph).compile())
                with patch.object(Path, 'read_text', side_effect=AssertionError('must not read')):
                    with self.assertRaisesRegex(RuError, '不读取本地文件'):
                        browser_graph(code)

    def test_interpreter_rejects_retired_names_even_after_canonical_import(self):
        interpreter = Interpreter(stdout=io.StringIO())
        interpreter.execute(parse("竞 取 外言 '如:竞'. 观 取 外言 '如:观'."))
        for old, new in RENAMED.items():
            with self.subTest(old=old), patch.object(
                    Path, 'read_text', side_effect=AssertionError('must not read')):
                with self.assertRaisesRegex(RuError, f'已改名为「{new}」'):
                    interpreter.execute(parse(f"外言 '{old}'."))

    def test_bare_product_names_remain_ordinary_identifiers(self):
        # Module spellings do not reserve new language identifiers.
        output = io.StringIO()
        Interpreter(stdout=output).execute(parse('如观 取 7. 如竞 取 8. 显 如观. 显 如竞.'))
        self.assertEqual(output.getvalue(), '7\n8\n')


if __name__ == '__main__':
    unittest.main()
