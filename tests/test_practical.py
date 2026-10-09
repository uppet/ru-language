"""Practical libraries: exact text/numeric contracts, identity, modules, all targets."""
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
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter, Module
from rulang.js_compiler import JSCompiler
from rulang.modules import load_module_graph

CC = (shutil.which(os.environ['CC']) if os.environ.get('CC') else
      next((shutil.which(c) for c in ('gcc', 'clang', 'cc') if shutil.which(c)), None))
NODE = shutil.which('node')
PRELUDE = "文 取 外言 '如:文本'. 数学 取 外言 '如:数学'. 随 取 外言 '如:随机'.\n"
CASES = [
    ('split', "显 文 其 拆分 ',甲,,乙,' ','. 显 (文 其 拆分 '' ',') 其 量. 显 文 其 拆分 'aaa' 'aa'. 显 文 其 拆分 '甲😀乙😀' '😀'.", '[, 甲, , 乙, ]\n1\n[, a]\n[甲, 乙, ]\n'),
    ('replace', "显 文 其 替换 'aaa' 'aa' 'b'. 显 文 其 替换 文:'ababa' 旧:'a' 新文:'aa'. 显 文 其 替换 '甲😀😀乙' '😀' ''.", 'ba\naabaabaa\n甲乙\n'),
    ('trim', "显 文 其 去空白 ' \\t甲 乙\\r\\n'. 显 (文 其 去空白 '　甲 ') 其 量. 显 (文 其 去空白 '') 其 量.", '甲 乙\n3\n0\n'),
    ('fixed', "显 文 其 定点 3.5 2. 显 文 其 定点 1.25 1. 显 文 其 定点 (-1.25) 1. 显 文 其 定点 2.675 2. 显 文 其 定点 (-0) 2. 显 文 其 定点 (-0.001) 2. 显 文 其 定点 9.99 1. 显 文 其 定点 1e21 0. 显 文 其 定点 5e-324 15.", '3.50\n1.3\n-1.3\n2.67\n-0.00\n-0.00\n10.0\n1000000000000000000000\n0.000000000000000\n'),
    ('math', "显 数学 其 取整 (-1.8). 显 数学 其 小 3 1. 显 数学 其 大 3 1. 显 数学 其 绝对 (-3). 显 数学 其 整除 (-7) 3. 显 数学 其 平方根 9. 显 数学 其 幂 2 10. 显 数学 其 幂 0 0. 显 数学 其 幂 (-2) 3. 显 数学 其 向下取整 (-1.2). 显 数学 其 向上取整 (-1.2). 显 数学 其 四舍五入 (-1.5). 显 数学 其 四舍五入 0.49999999999999994. 显 数学 其 四舍五入 4503599627370495.5.", '-1\n1\n3\n3\n-2\n3\n1024\n1\n-8\n-2\n-1\n-2\n0\n4.5035996273705e+15\n'),
    ('negative_zero', "显 数学 其 平方根 (-0). 显 数学 其 向下取整 (-0). 显 数学 其 向上取整 (-0.2). 显 数学 其 四舍五入 (-0.2). 显 数学 其 幂 (-0) 3.", '-0\n-0\n-0\n-0\n-0\n'),
    ('array', "列 取 [空,1,2,3]. 别 取 列. 显 列 其 删 位:1. 显 别. 显 列 其 弹. 显 列 其 查 值:空. 显 列 其 查 9. 显 列 其 删 0. 显 列.", '1\n[空, 2, 3]\n3\n0\n空\n空\n[2]\n'),
    ('equality', "内 取 [1]. 列 取 [假,0,内,1,1]. 显 列 其 查 0. 显 列 其 查 内. 显 列 其 查 [1]. 显 列 其 查 1. 典表 取 {'a':3}. 显 典表 其 查 键:'a'.", '1\n2\n空\n3\n3\n'),
    ('snapshot', "形 盒: 值 为 数. 算 同 另一: 循 原 其 量 次 原 其 弹. 环 得 其 值 == 另一 其 值. 法 象 原 取 [(新 盒 值:1),(新 盒 值:2)]. 显 原 其 查 (新 盒 值:2). 显 原 其 量.", '1\n0\n'),
    ('cyclic', "列 取 []. 列 其 增 列. 显 列 其 查 列. 显 (列 其 弹) == 列. 显 列.", '0\n真\n[]\n'),
    ('panic', "形 盒: 算 同 另一: 卒 '比较停'. 法 象 列 取 [(新 盒)]. 试 列 其 查 (新 盒). 救 原因 显 原因. 终. 显 列 其 量.", '比较停\n1\n'),
    ('pcg_golden', "源 取 随 其 造源 42. 循 6 次 显 源 其 整数 0 4294967295. 环", '2707161783\n2068313097\n3122475824\n2211639955\n3215226955\n3421331566\n'),
    ('rng_identity', "甲 取 随 其 造源 42. 乙 取 随 其 造源 42. 别 取 甲. 显 甲 == 乙. 显 甲 == 别. 显 甲 其 整数 7 7. 显 甲 其 整数 (-0) 0. 显 (甲 其 整数 0 4294967295) == (乙 其 整数 0 4294967295). 显 别 其 整数 0 4294967295.", '假\n真\n7\n0\n真\n2068313097\n'),
    ('shuffle', "源 取 随 其 造源 42. 空列 取 []. 显 (源 其 洗牌 空列) == 空列. 内 取 [1]. 单 取 [内]. 副 取 源 其 洗牌 单. 显 副 == 单. 显 副[0] == 内. 显 源 其 整数 0 4294967295. 原 取 [1,2,3,4,5]. 排 取 源 其 洗牌 原. 显 原. 显 排 == 原. 显 排 其 量.", '假\n假\n真\n2707161783\n[1, 2, 3, 4, 5]\n假\n5\n'),
    ('references', "格式 取 算 文 其 定点. 显 格式 1.25 1. 开始 取 算 随 其 造源. 源 取 开始 42. 开方 取 算 数学 其 平方根. 显 开方 4. 显 源 其 整数 下:0 上:4294967295.", '1.3\n2\n2707161783\n'),
]
ERRORS = [
    "文 其 拆分 'abc' ''.", "文 其 替换 'abc' '' 'x'.", "文 其 去空白 1.",
    "文 其 定点 1 (-1).", "文 其 定点 1 16.", "文 其 定点 1 1.5.", "文 其 定点 真 1.",
    "数学 其 平方根 (-1).", "数学 其 幂 (-2) 0.5.", "数学 其 幂 0 (-1).", "数学 其 幂 1e308 2.",
    "([1]) 其 删 (-1).", "([1]) 其 删 1.", "([1]) 其 删 0.5.", "([1]) 其 删 真.", "([]) 其 弹.",
    "([]) 其 查.", "([1]) 其 弹 0.", "算 ([1]) 其 查.",
    "随 其 造源 (-1).", "随 其 造源 4294967296.", "随 其 造源 0.5.",
    "源 取 随 其 造源 1. 源 其 整数 0 4294967296.",
    "源 取 随 其 造源 1. 源 其 整数 2 1.",
    "源 取 随 其 造源 1. 源 其 整数 0 0.5.",
    "源 取 随 其 造源 1. 源 其 整数 9007199254740992 9007199254740992.",
    "源 取 随 其 造源 1. 源 其 洗牌 'abc'.",
    "形 盒: 算 同 另一: 得 1. 法 象 列 取 [(新 盒)]. 列 其 查 (新 盒).",
]


def interpreted(source):
    graph = load_module_graph('/tmp/practical-test.ru', parse(source))
    output = io.StringIO()
    Interpreter(io.StringIO(''), output).execute(graph[graph.root], source_path=graph.root, modules=graph)
    return output.getvalue()


def execute_target(source, target, directory, full=False):
    source_path = directory / 'main.ru'
    source_path.write_text(source, encoding='utf-8')
    graph = load_module_graph(source_path, parse(source))
    if target == 'c':
        output, binary = directory / 'main.c', directory / ('main.exe' if os.name == 'nt' else 'main')
        output.write_text(Compiler(graph[graph.root], graph.root, modules=graph, full_runtime=full).compile(), encoding='utf-8')
        build = subprocess.run([CC, '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-pedantic', str(output), '-o', str(binary), '-lm'], capture_output=True, text=True, encoding='utf-8')
        if build.returncode:
            raise AssertionError(build.stderr)
        command = [str(binary)]
    else:
        output = directory / 'main.js'
        output.write_text(JSCompiler(graph[graph.root], graph.root, modules=graph, full_runtime=full).compile(), encoding='utf-8')
        command = [NODE, str(output)]
    return subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=30,
                          env={**os.environ, 'RU_GC_THRESHOLD':'1', 'RU_GC_STATS':'1'})


class PracticalLibraryTests(unittest.TestCase):
    def test_interpreter_cases(self):
        for name, source, expected in CASES:
            with self.subTest(name=name):
                self.assertEqual(interpreted(PRELUDE + source), expected)

    def test_interpreter_errors(self):
        for source in ERRORS:
            with self.subTest(source=source):
                with self.assertRaises(RuError):
                    interpreted(PRELUDE + source)

    def _target_cases(self, target):
        # Distinct explicit scopes let one build exercise all independent cases.
        source = PRELUDE + ''.join('\n段:\n'+body+'\n落.\n' for _, body, _ in CASES if '形 ' not in body)
        expected = ''.join(expected for _, body, expected in CASES if '形 ' not in body)
        programs = [('combined', source, expected)] + [(name, PRELUDE+body, expected) for name, body, expected in CASES if '形 ' in body]
        with tempfile.TemporaryDirectory() as tmp:
            for full in (False, True):
                for name, source, expected in programs:
                    with self.subTest(target=target, full=full, name=name):
                        run = execute_target(source, target, Path(tmp), full)
                        self.assertEqual(run.returncode, 0, run.stderr)
                        self.assertEqual(run.stdout, expected)
                        if target == 'c':
                            self.assertIn('live=0', run.stderr)

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_native_cases(self):
        self._target_cases('c')

    @unittest.skipUnless(NODE, 'Node unavailable')
    def test_javascript_cases(self):
        self._target_cases('js')

    def _target_errors(self, target):
        with tempfile.TemporaryDirectory() as tmp:
            for source in ERRORS:
                with self.subTest(target=target, source=source):
                    try:
                        run = execute_target(PRELUDE+source, target, Path(tmp))
                    except RuError:
                        continue
                    self.assertNotEqual(run.returncode, 0)
                    self.assertIn('错误', run.stderr)

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_native_errors(self):
        self._target_errors('c')

    @unittest.skipUnless(NODE, 'Node unavailable')
    def test_javascript_errors(self):
        self._target_errors('js')

    def test_exports_and_protection(self):
        for module, expected in [('文本', {'拆分','替换','去空白','定点'}), ('数学', {'取整','小','大','绝对','整除','平方根','幂','向下取整','向上取整','四舍五入'}), ('随机', {'造源'})]:
            graph = load_module_graph(ROOT/'rulang'/'stdlib'/(module+'.ru'))
            runtime = Interpreter(io.StringIO(''),io.StringIO())
            runtime.execute(graph[graph.root], source_path=graph.root, modules=graph)
            self.assertEqual(set(Module(runtime).exports()), expected)
        with self.assertRaises(RuError):
            interpreted('__实用 取 1.')
        with self.assertRaises(RuError):
            interpreted("尽 取 外言 '如:数学'. 尽 取 外言 '如:竞赛'.")

if __name__ == '__main__':
    unittest.main()
