"""Package identities and side effects match Python, C and JavaScript."""
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from rulang.compiler import Compiler
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter
from rulang.js_compiler import JSCompiler
from rulang.modules import load_module_graph
from rulang.browser_compiler import browser_graph

CC = os.environ.get('CC') or shutil.which('gcc') or shutil.which('cc')
NODE = shutil.which('node')


class PackageBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.app, self.lib = self.root / 'app', self.root / 'lib'
        self.app.mkdir()
        (self.lib / 'src').mkdir(parents=True)
        self.write(self.app / '集录.ru', "{'名':'应用','版':'1.0.0','依赖':{'物理':{'路径':'../lib'},'工程别名':{'路径':'../lib'}}}.")
        self.write(self.lib / '集录.ru', "{'名':'工程','版':'1.0.0','公开':['力学']}.")

    def write(self, path, text):
        path.write_text(text, encoding='utf-8')
        return path

    def assert_backends(self, library, source, expected):
        self.write(self.lib / 'src/力学.ru', library)
        main = self.write(self.app / 'main.ru', source)
        graph = load_module_graph(main)
        self.assertEqual(len(graph), 2)
        # Each fresh run has a fresh cache; repeated aliases within that run
        # must share it. This distinguishes failure rethrow from permanent state.
        for _ in range(2):
            output = io.StringIO()
            Interpreter(stdout=output).execute(graph[graph.root], source_path=main, modules=graph)
            self.assertEqual(output.getvalue(), expected)
        for full in (False, True):
            for backend in ('c', 'js'):
                with self.subTest(backend=backend, full=full):
                    if backend == 'c' and not CC or backend == 'js' and not NODE:
                        continue
                    compiler = (Compiler if backend == 'c' else JSCompiler)(
                        graph[graph.root], str(main), modules=graph, full_runtime=full)
                    generated = compiler.compile()
                    path = self.write(self.root / ('program.' + backend), generated)
                    if backend == 'c':
                        binary = self.root / 'program.exe'
                        built = subprocess.run([CC, '-std=c99', str(path), '-o', str(binary), '-lm'],
                                               capture_output=True, text=True, timeout=60)
                        self.assertEqual(built.returncode, 0, built.stderr)
                        command = [str(binary)]
                    else:
                        command = [NODE, str(path)]
                    for _ in range(2):
                        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout, expected)

    def test_alias_paths_state_type_and_import_all_share_identity(self):
        self.assert_backends('''吾 言 工程 其 力学.
显 '初始化'.
状态 取 [0].
形 点: 值 为 数. 象.
算 接纳 对象 为 点: 得 对象 其 值. 法.
''', '''甲 取 外言 物理 其 力学.
乙 取 外言 '../lib/src/力学.ru'.
尽取 外言 工程别名 其 力学.
甲 其 状态[0] 取 7.
显 乙 其 状态[0].
显 乙 其 接纳 (新 点 值:8).
''', '初始化\n7\n8\n')

    def test_failed_named_and_path_import_share_cached_failure(self):
        self.assert_backends("吾 言 工程 其 力学. 显 '一次'. 卒 '坏'.", '''
试: 外言 物理 其 力学. 救 因: 显 因. 终.
试: 外言 '../lib/src/力学.ru'. 救 因: 显 因. 终.
试: 外言 工程别名 其 力学. 救 因: 显 因. 终.
''', '一次\n坏\n坏\n坏\n')

    def test_unexecuted_named_imports_are_checked(self):
        main = self.write(self.app / 'main.ru', '算 未用: 得 外言 未声明 其 模块. 法.')
        with self.assertRaisesRegex(RuError, '依赖'):
            load_module_graph(main)

    def test_browser_accepts_declaration_but_never_local_packages(self):
        graph = browser_graph("吾 言 页面. 数 取 外言 '如:数学'. 显 数 其 根 4.")
        self.assertEqual(len(graph), 2)
        with self.assertRaisesRegex(RuError, '只允许内置标准外言'):
            browser_graph('外言 工程 其 力学.')

    def test_no_package_legacy_path_scripts_remain_supported(self):
        self.write(self.root / 'plain.ru', '吾 言 普通. 值 取 3.')
        main = self.write(self.root / 'entry.ru', "甲 取 外言 'plain.ru'.")
        self.assertEqual(len(load_module_graph(main)), 2)
