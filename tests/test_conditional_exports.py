"""RU-028: import-all callable values include possible module-scope bindings."""
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.compiler import Compiler
from rulang.frontend import RuError
from rulang.interpreter import Interpreter
from rulang.js_compiler import JSCompiler
from rulang.modules import load_module_graph

CC = shutil.which(os.environ.get('CC', 'cc'))
NODE = shutil.which('node') or shutil.which('nodejs')


class ConditionalExportTests(unittest.TestCase):
    def check_engines(self, library, main, expected='', error=None, middle=None):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'lib.ru').write_text(library, encoding='utf-8')
            if middle is not None:
                (root / 'middle.ru').write_text(middle, encoding='utf-8')
            source = root / 'main.ru'
            source.write_text(main, encoding='utf-8')
            graph = load_module_graph(source)
            output = io.StringIO()
            engine = Interpreter(stdout=output)
            if error:
                with self.assertRaisesRegex(RuError, error):
                    engine.execute(graph[graph.root], source_path=graph.root, modules=graph)
            else:
                engine.execute(graph[graph.root], source_path=graph.root, modules=graph)
            self.assertEqual(output.getvalue(), expected)
            for backend, available in ((Compiler, CC), (JSCompiler, NODE)):
                if not available:
                    continue
                for full in (False, True):
                    with self.subTest(backend=backend.__name__, full=full):
                        # Runtime failures must still compile: possible exports
                        # do not imply that a branch created a value.
                        generated = backend(graph[graph.root], str(source), modules=graph,
                                            full_runtime=full).compile()
                        if backend is Compiler:
                            target = root / 'program.c'
                            target.write_text(generated, encoding='utf-8')
                            binary = root / ('program.exe' if os.name == 'nt' else 'program')
                            built = subprocess.run([CC, '-std=c99', '-O0', str(target), '-lm',
                                                    '-o', str(binary)], capture_output=True,
                                                   text=True, timeout=60)
                            self.assertEqual(built.returncode, 0, built.stderr)
                            command = [str(binary)]
                        else:
                            target = root / 'program.js'
                            target.write_text(generated, encoding='utf-8')
                            command = [NODE, str(target)]
                        result = subprocess.run(command, capture_output=True, text=True,
                                                encoding='utf-8', timeout=10)
                        self.assertEqual(result.stdout, expected)
                        if error:
                            self.assertNotEqual(result.returncode, 0)
                            self.assertRegex(result.stderr, error)
                        else:
                            self.assertEqual(result.returncode, 0, result.stderr)

    def test_if_loop_and_try_bindings_are_callable(self):
        for body in ('若 真 则 {binding} 然',
                     '循 1 次 若 真 则 {binding} 然 环',
                     "试 {binding} 救 因 卒 因. 终."):
            with self.subTest(body=body):
                self.check_engines(body.format(binding='回 取 算 值: 得 值+1. 法.'),
                                   "尽 取 外言 'lib.ru'. 显 回 2. 显 回 值:4.", '3\n5\n')

    def test_transitive_export_closure_and_procedure(self):
        self.check_engines(
            "种 取 4. 若 真 则 回 取 算 值: 得 种+值. 法. "
            "报 取 作 值: 显 值. 为. 然",
            "尽 取 外言 'middle.ru'. 显 回 2. 报 值:7.", '6\n7\n',
            middle="尽 取 外言 'lib.ru'.")

    def test_untaken_branch_still_fails_at_runtime(self):
        self.check_engines('若 假 则 回 取 算 值: 得 值. 法. 然',
                           "尽 取 外言 'lib.ru'. 显 回 2.", error='未定义.*回')

    def test_conditional_conflict_remains_runtime_only(self):
        for fact, expected_error in (('假', None), ('真', '名称冲突')):
            with self.subTest(fact=fact):
                self.check_engines(f'若 {fact} 则 回 取 算 值: 得 值. 法. 然',
                                   "回 取 9. 尽 取 外言 'lib.ru'. 显 回.",
                                   '' if expected_error else '9\n', error=expected_error)

    def test_noncallable_value_is_not_promoted_to_function(self):
        self.check_engines('若 真 则 回 取 3. 然',
                           "尽 取 外言 'lib.ru'. 显 回 2.", error='不是(算|函数)')

    def test_plain_value_and_existing_call_forms(self):
        self.check_engines('若 真 则 值 取 3. 回 取 算 数值: 得 数值+1. 法. 然',
                           "模 取 外言 'lib.ru'. 尽 取 外言 'lib.ru'. "
                           '显 值. 显 模 其 回 2. 显 (回) 3.', '3\n3\n4\n')

    def test_private_scopes_and_unknown_names_still_rejected(self):
        for library in ('段: 回 取 算 值: 得 值. 法. 落.',
                        "试 卒 1. 救 因 回 取 算 值: 得 值. 法. 终.",
                        '算 工厂: 回 取 算 值: 得 值. 法. 得 回. 法',
                        '值 取 1.'):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root / 'lib.ru').write_text(library, encoding='utf-8')
                source = root / 'main.ru'
                source.write_text("尽 取 外言 'lib.ru'. 显 回 2.", encoding='utf-8')
                graph = load_module_graph(source)
                for backend in (Compiler, JSCompiler):
                    with self.subTest(library=library, backend=backend.__name__):
                        with self.assertRaisesRegex(RuError, '未定义函数：回'):
                            backend(graph[graph.root], str(source), modules=graph).compile()


if __name__ == '__main__':
    unittest.main()
