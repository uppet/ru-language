"""Error-only hints preserve evaluation, typed identity, and valid programs."""
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from rulang.compiler import Compiler
from rulang.frontend import RuError
from rulang.interpreter import Interpreter
from rulang.js_compiler import JSCompiler
from rulang.modules import load_module_graph

NODE = shutil.which('node') or shutil.which('nodejs')
CC = (shutil.which(os.environ['CC']) if os.environ.get('CC') else
      next((shutil.which(c) for c in ('clang', 'gcc', 'cc') if shutil.which(c)), None))
SECRET = 'private-payload-never-print'


class ActionableDiagnostics(unittest.TestCase):
    def check(self, source, expected, *, other=None, output=None):
        with tempfile.TemporaryDirectory() as folder:
            # Match the module loader's canonical path, including Windows 8.3 aliases.
            root = (Path(folder) / 'main.ru').resolve()
            root.write_text(source, encoding='utf-8')
            if other:
                (Path(folder) / 'other.ru').write_text(other, encoding='utf-8')
            graph = load_module_graph(root)
            stdout = io.StringIO()
            engine = Interpreter(io.StringIO(), stdout)
            if expected:
                with self.assertRaises(RuError) as error:
                    engine.execute(graph[graph.root], source_path=graph.root, modules=graph)
                self.assertIn(expected, error.exception.message)
                self.assertNotIn(SECRET, error.exception.message)
                self.assertEqual(error.exception.line, 2)
                self.assertEqual(error.exception.source_name, str(root))
            else:
                engine.execute(graph[graph.root], source_path=graph.root, modules=graph)
                self.assertEqual(stdout.getvalue(), output)
            for full in (False, True):
                for backend, available in ((Compiler, CC), (JSCompiler, NODE)):
                    if not available:
                        continue
                    with self.subTest(full=full, backend=backend.__name__):
                        generated = backend(graph[graph.root], graph.root, modules=graph,
                                            full_runtime=full).compile()
                        if backend is Compiler:
                            binary = Path(folder) / ('native.exe' if os.name == 'nt' else 'native')
                            cfile = Path(folder) / 'native.c'
                            cfile.write_text(generated, encoding='utf-8')
                            built = subprocess.run([CC, '-std=c99', '-O1', '-Wall', '-Wextra',
                                '-Werror', '-Wno-unused-function', '-pedantic', str(cfile),
                                '-lm', '-o', str(binary)], capture_output=True, text=True, timeout=60)
                            self.assertEqual(built.returncode, 0, built.stderr)
                            command = [str(binary)]
                        else:
                            path = Path(folder) / 'program.js'
                            path.write_text(generated, encoding='utf-8')
                            command = [NODE, str(path)]
                        result = subprocess.run(command, capture_output=True, text=True,
                            timeout=20, env={**os.environ, 'RU_GC_THRESHOLD':'1', 'RU_GC_STATS':'1'})
                        self.assertEqual(result.returncode, 1 if expected else 0, result.stderr)
                        self.assertNotIn(SECRET, result.stderr)
                        if backend is Compiler:
                            self.assertIn('RU_GC live=0 ', result.stderr)
                        if expected:
                            self.assertIn(expected, result.stderr)
                            self.assertIn(str(root)+':2:', result.stderr)
                        else:
                            self.assertEqual(result.stdout, output)
                            self.assertNotIn('若要', result.stderr)

    def test_nested_array_argument(self):
        self.check('算 接收 参数 为 数 阵 阵: 得 0. 法\n接收 ([[1],[2,\''+SECRET+'\']]).',
                   '元素[1][1]须为数，实际收到句')

    def test_nested_array_field(self):
        self.check('形 盒: 列 为 数 阵 阵. 象\n新 盒 列:[[1],真].',
                   '元素[1]须为数 阵，实际收到事实')

    def test_array_field_assignment(self):
        self.check('形 盒: 列 为 数 阵. 象 值 取 新 盒.\n值 其 列 取 [1,假].',
                   '元素[1]须为数，实际收到事实')

    def test_same_name_different_identity(self):
        self.check("异 取 外言 'other.ru'. 形 点: 象 算 接收 参数 为 点 阵: 得 0. 法\n接收 ([(异 其 造)]).",
                   '元素[0]须为点，实际收到点；同名但不同形身份：期望形与实际形来自不同声明',
                   other='形 点: 象 算 造: 得 新 点. 法')

    def test_index_spacing(self):
        self.check('列 取 [7].\n显 列 [0].', '若要索引，请让方括号紧邻接收者，如 列[0]')

    def test_comparison_hint(self):
        self.check('前 取 1.\n显 前 < 2 < 3.', '若要连续比较，请拆成两个比较并用「且」连接')

    def test_cycles_have_finite_annotation_depth(self):
        self.check('列 取 []. 列 其 增 列. 算 接收 参数 为 数 阵 阵: 得 0. 法\n接收 列.',
                   '元素[0][0]须为数，实际收到阵')

    def test_valid_calls_comparisons_and_inheritance_unchanged(self):
        self.check('''形 点: 象 形 子点 如 点: 象
算 接收 参数 为 点 阵: 得 参数 其 量. 法
算 回 列 为 数 阵: 得 列[0]. 法
显 回 ([7]). 显 回 [8].
列 取 [9]. 显 列[0].
显 接收 ([新 子点]). 显 1 < 2 且 2 < 3.
显 (1 < 2) == 真. 显 1 < 2 == 真.
''', None, output='7\n8\n9\n1\n真\n真\n真\n')


if __name__ == '__main__':
    unittest.main()
