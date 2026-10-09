"""Explicit recoverable panic parity and native unwind ownership regression tests."""
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.compiler import Compiler
from rulang.frontend import Incomplete, RuError, parse, validate
from rulang.interpreter import Interpreter, Panic
from rulang.modules import load_module_graph

CC = (shutil.which(os.environ['CC']) if os.environ.get('CC') else
      next((shutil.which(c) for c in ('clang', 'gcc', 'cc') if shutil.which(c)), None))

CASES = [
    ('normal', "试 显 '正常'. 救 原因 显 '不应执行'. 终. 显 '之后'.", '正常\n之后\n'),
    ('reason_and_resume', "试 卒 '失败😀'. 显 '不应执行'. 救 原因 显 原因. 终. 显 '继续'.", '失败😀\n继续\n'),
    ('body_binding_survives', "甲 取 1. 试 甲 取 2. 乙 取 '存在'. 卒 '坏'. 救 原因 显 甲. 终. 显 甲. 显 乙.", '2\n2\n存在\n'),
    ('handler_scope', "原因 取 '外'. 值 取 '旧'. 列 取 [1]. 试 卒 '内'. 救 原因 值 取 '新'. 列[0] 取 2. 显 原因. 显 值. 终. 显 原因. 显 值. 显 列[0].", '内\n新\n外\n旧\n2\n'),
    ('nested', "试 试 卒 '内'. 救 内因 显 内因. 卒 内因+'外'. 终. 显 '坏'. 救 外因 显 外因. 终. 显 '后'.", '内\n内外\n后\n'),
    ('function_call', "算 坏 值 为 句: 卒 值. 法 试 显 '左'+(坏 '原因')+'右'. 救 原因 显 原因. 终.", '原因\n'),
    ('nearest_dynamic', "作 坏: 卒 '坏'. 为 作 内: 试 坏. 救 原因 显 '近'+原因. 终. 为 试 内. 显 '完'. 救 原因 显 '远'. 终.", '近坏\n完\n'),
    ('return_try', "算 回: 试 得 '返回'. 救 原因 得 '坏'. 终. 法 显 回. 试 卒 '后'. 救 原因 显 原因. 终.", '返回\n后\n'),
    ('return_rescue', "算 回: 试 卒 '返回'. 救 原因 得 原因. 终. 法 显 回.", '返回\n'),
    ('break_try', "循 试 破. 救 原因 显 '坏'. 终. 环 试 卒 '后'. 救 原因 显 原因. 终.", '后\n'),
    ('break_rescue', "循 试 卒 '断'. 救 原因 显 原因. 破. 终. 环 显 '后'.", '断\n后\n'),
    ('loop_in_rescue', "试 卒 '原'. 救 原因 循 3 次 显 原因. 破. 环 显 原因. 终.", '原\n原\n'),
    ('nested_rescue_return', "算 回: 试 卒 '外'. 救 外因 试 卒 '内'. 救 内因 得 外因+内因. 终. 终. 法 显 回.", '外内\n'),
    ('nested_rescue_break', "循 试 卒 '外'. 救 外因 试 卒 '内'. 救 内因 显 外因+内因. 破. 终. 终. 环 显 '完'.", '外内\n完\n'),
    ('rescue_outer', "试 试 卒 '一'. 救 原因 试 卒 原因+'二'. 救 次因 卒 次因+'三'. 终. 终. 救 原因 显 原因. 终.", '一二三\n'),
    ('method', "形 甲: 算 坏 值 为 句: 卒 值. 法 象 试 显 (新 甲) 其 坏 '方法'. 救 原因 显 原因. 终.", '方法\n'),
    ('standard_method', "形 甲: 算 含 句 为 句: 卒 句. 法 象 试 显 (新 甲) 其 含 '标准'. 救 原因 显 原因. 终.", '标准\n'),
    ('short_circuit', "算 坏: 卒 '坏'. 法 试 显 假 且 坏. 显 真 或 坏. 显 真 且 坏. 救 原因 显 原因. 终.", '假\n真\n坏\n'),
    ('argument_order', "算 报 值 为 句: 显 值. 得 值. 法 算 坏: 卒 '卒'. 法 算 合 甲 为 句 乙 为 句 丙 为 句: 得 甲+乙+丙. 法 试 显 (合 (报 '先') 坏 (报 '不应')). 救 原因 显 原因. 终.", '先\n卒\n'),
    ('assignment_partial', "算 坏: 卒 '坏'. 法 列 取 ['旧']. 试 列[0] 取 坏. 救 原因 显 原因. 终. 显 列[0].", '坏\n旧\n'),
    ('contextual_end', "终 取 '可作名称'. 显 终. 显 '甲乙丙' 其 段 始:1 终:2. 试 卒 '救'. 救 原因 显 原因. 终.", '可作名称\n乙\n救\n'),
    ('optional_colons', "试: 卒 '好'. 救 原因: 显 原因. 终.", '好\n'),
]

STRESS = '''
形 环结: 后 为 环结. 象
算 深 数值 为 数:
    列 取 ['分配', 数值]. 列 其 增 列.
    节 取 新 环结. 节 其 后 取 节.
    若 数值 == 0 则 卒 '底'. 然
    得 ['左', (深 数值-1), '右'].
法
算 返 数值 为 数:
    试 显 深 数值. 救 原因
        循 3 次 试 卒 原因+'内'. 救 内因 破. 终. 环
        得 原因+'返'.
    终.
法
循 300 次
    试 显 ['临时', (深 20), '未求值']. 救 原因
        若 原因 != '底' 则 卒 '错误'. 然
    终.
    答 取 返 10.
环
显 答.
'''


def interpreted(source):
    out = io.StringIO()
    interpreter = Interpreter(io.StringIO(), out)
    interpreter.execute(parse(source))
    return out.getvalue()


def native(source, folder, stem='case', flags=(), modules=None, source_path=None):
    path = Path(folder).resolve() / (stem + '.c')
    binary = Path(folder).resolve() / stem
    program = modules[str(Path(source_path).resolve())] if modules is not None else parse(source)
    path.write_text(Compiler(program, str(source_path or '<测试>'), modules=modules).compile(), encoding='utf-8')
    result = subprocess.run([CC, '-std=c99', '-O2', '-g', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-pedantic', *flags, str(path), '-lm', '-o', str(binary)], capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return subprocess.run([str(binary)], capture_output=True, text=True, timeout=40,
                          env={**os.environ, 'RU_GC_THRESHOLD': '1', 'RU_GC_STATS': '1',
                               'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1'})


class PanicTests(unittest.TestCase):
    def test_interpreter_cases(self):
        for name, source, expected in CASES:
            with self.subTest(name=name):
                self.assertEqual(interpreted(source), expected)

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_native_cases(self):
        with tempfile.TemporaryDirectory() as folder:
            for name, source, expected in CASES:
                with self.subTest(name=name):
                    result = native(source, folder, name)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, expected)
                    self.assertRegex(result.stderr, r'RU_GC live=0 ')

    def test_structure(self):
        for source in ('试 显 1. 终.', '救 原因 显 原因.', '试 救 终.',
                       '试 算 内: 得 1. 法 救 原因 终.',
                       '试 破. 救 原因 终.', '试 救 原因 得 1. 终.'):
            with self.subTest(source=source), self.assertRaises(RuError):
                validate(parse(source))
        for source in ('试', '试 卒 \'坏\'.', '试 救', '试 救 原因', '卒'):
            with self.subTest(source=source), self.assertRaises(Incomplete):
                parse(source)

    def test_nonpanic_errors_are_not_rescued(self):
        sources = ["试 显 1/0. 救 原因 显 '不应'. 终.",
                   "试 卒 3. 救 原因 显 '不应'. 终.",
                   "试 显 [1][2]. 救 原因 显 '不应'. 终.",
                   "试 卒 '坏'. 救 原因 临时 取 原因. 终. 显 临时."]
        for source in sources:
            with self.subTest(source=source), self.assertRaises(RuError) as raised:
                interpreted(source)
            self.assertNotIsInstance(raised.exception, Panic)
        if CC:
            with tempfile.TemporaryDirectory() as folder:
                for index, source in enumerate(sources):
                    with self.subTest(native=index):
                        result = native(source, folder, 'error' + str(index))
                        self.assertNotEqual(result.returncode, 0)
                        self.assertNotIn('不应', result.stdout)
                        self.assertIn('运行错误', result.stderr)

    def test_uncaught_and_repl(self):
        with self.assertRaises(Panic) as raised:
            interpreted("显 '先'.\n卒 '原因😀'.")
        self.assertEqual((raised.exception.line, raised.exception.col), (2, 1))
        self.assertEqual(raised.exception.reason, '原因😀')
        result = subprocess.run([sys.executable, '-m', 'rulang', 'repl'],
                                input="卒 '失败'.\n显 '继续'.\n:quit\n", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '继续\n')
        self.assertIn('未救之卒：失败', result.stderr)
        if CC:
            with tempfile.TemporaryDirectory() as folder:
                result = native("显 '先'.\n卒 '原因😀'.", folder)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('<测试>:2:1: 未救之卒：原因😀', result.stderr)
                self.assertIn('RU_GC live=0 ', result.stderr)

    def test_module_calls_and_cached_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve() / 'root.ru'
            child = Path(folder).resolve() / 'child.ru'
            child.write_text("作 坏: 卒 '跨模块'. 为", encoding='utf-8')
            source = "模 取 外言 'child.ru'. 试 模 其 坏. 救 原因 显 原因. 终."
            root.write_text(source, encoding='utf-8')
            graph = load_module_graph(root)
            out = io.StringIO()
            Interpreter(stdout=out).execute(graph[str(root)], source_path=root, modules=graph)
            self.assertEqual(out.getvalue(), '跨模块\n')
            if CC:
                result = native(source, folder, modules=graph, source_path=root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '跨模块\n')
            child.write_text("显 '初始化'. 卒 '初始化失败'.", encoding='utf-8')
            source = "循 3 次 试 模 取 外言 'child.ru'. 救 原因 显 原因. 终. 环"
            root.write_text(source, encoding='utf-8')
            graph = load_module_graph(root)
            out = io.StringIO()
            Interpreter(stdout=out).execute(graph[str(root)], source_path=root, modules=graph)
            self.assertEqual(out.getvalue(), '初始化\n' + '初始化失败\n' * 3)
            if CC:
                result = native(source, folder, 'cached_failure', modules=graph, source_path=root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, out.getvalue())
                self.assertIn('RU_GC live=0 ', result.stderr)

    def test_failed_module_preserves_escaped_objects(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve() / 'root.ru'
            store = Path(folder).resolve() / 'store.ru'
            bad = Path(folder).resolve() / 'bad.ru'
            middle = Path(folder).resolve() / 'middle.ru'
            store.write_text("对象们 取 [].", encoding='utf-8')
            bad.write_text("存 取 外言 'store.ru'. 文本 取 '仍存'.\n"
                "形 物: 算 取文: 得 文本. 法 象\n"
                "存 其 对象们 其 增 (新 物).\n卒 '初始化失败'.", encoding='utf-8')
            middle.write_text("显 '中间只执行一次'. 模 取 外言 'bad.ru'.", encoding='utf-8')
            source = ("循 50 次 试 模 取 外言 'middle.ru'. 救 原因 显 原因. 终. 环 "
                      "存 取 外言 'store.ru'. 显 存 其 对象们 其 量. "
                      "显 (存 其 对象们)[0] 其 取文.")
            root.write_text(source, encoding='utf-8')
            graph = load_module_graph(root)
            expected = '中间只执行一次\n' + '初始化失败\n' * 50 + '1\n仍存\n'
            out = io.StringIO()
            interpreter = Interpreter(stdout=out)
            interpreter.execute(graph[str(root)], source_path=root, modules=graph)
            self.assertEqual(out.getvalue(), expected)
            # Reimports through a failed dependency preserve the original
            # source location and materialize fresh exceptions each time.
            for name in (str(bad), str(middle)):
                cached = interpreter.module_cache[name]
                self.assertFalse(isinstance(cached, BaseException))
                with self.assertRaises(Panic) as raised:
                    cached.rethrow()
                self.assertEqual((raised.exception.source_name, raised.exception.line), (str(bad), 4))
            if CC:
                result = native(source, folder, 'escaped', modules=graph, source_path=root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)
                self.assertIn('RU_GC live=0 ', result.stderr)
                uncaught = "试 模 取 外言 'middle.ru'. 救 原因 终. 模 取 外言 'middle.ru'."
                root.write_text(uncaught, encoding='utf-8')
                graph = load_module_graph(root)
                result = native(uncaught, folder, 'cached_origin', modules=graph, source_path=root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f'{bad}:4:1: 未救之卒：初始化失败', result.stderr)
                self.assertIn('RU_GC live=0 ', result.stderr)

    def test_module_origin_and_reserved_handler(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve() / 'root.ru'
            child = Path(folder).resolve() / 'child.ru'
            child.write_text("作 坏:\n  卒 '模块原点'.\n为", encoding='utf-8')
            source = "模 取 外言 'child.ru'. 模 其 坏."
            root.write_text(source, encoding='utf-8')
            graph = load_module_graph(root)
            with self.assertRaises(Panic) as raised:
                Interpreter().execute(graph[str(root)], source_path=root, modules=graph)
            error = raised.exception
            self.assertEqual((error.source_name, error.line, error.col), (str(child), 2, 3))
            if CC:
                result = native(source, folder, 'origin', modules=graph, source_path=root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f'{child}:2:3: 未救之卒：模块原点', result.stderr)
                self.assertIn('RU_GC live=0 ', result.stderr)
            source = "尽 取 外言 'child.ru'. 试 卒 '坏'. 救 坏 显 坏. 终."
            root.write_text(source, encoding='utf-8')
            graph = load_module_graph(root)
            with self.assertRaises(RuError) as raised:
                Interpreter().execute(graph[str(root)], source_path=root, modules=graph)
            self.assertNotIsInstance(raised.exception, Panic)
            if CC:
                result = native(source, folder, 'reserved', modules=graph, source_path=root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('运行错误', result.stderr)

    def test_entry_panic(self):
        source = "算 元初 外参 为 句 阵: 卒 '入口失败'. 法"
        interpreter = Interpreter()
        interpreter.execute(parse(source))
        with self.assertRaises(Panic):
            interpreter.execute_entry([])
        self.assertEqual(interpreter.call_state[0], 0)
        self.assertEqual(interpreter.depth, 0)
        if CC:
            with tempfile.TemporaryDirectory() as folder:
                result = native(source, folder)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('未救之卒：入口失败', result.stderr)
                self.assertIn('RU_GC live=0 ', result.stderr)

    @unittest.skipUnless(CC and os.name != 'nt', 'POSIX pipe test')
    def test_legacy_print_failure_is_fatal(self):
        class BrokenOutput(io.StringIO):
            def flush(self):
                raise BrokenPipeError('closed pipe')
        with self.assertRaises(RuError) as raised:
            Interpreter(stdout=BrokenOutput()).execute(parse("试 显 'x'. 救 原因 显 '不可救'. 终."))
        self.assertNotIsInstance(raised.exception, Panic)
        self.assertIn('输出失败', raised.exception.message)
        with tempfile.TemporaryDirectory() as folder:
            result = native("试 显 'x'. 救 原因 显 '不可救'. 终.", folder, 'broken')
            self.assertEqual(result.returncode, 0, result.stderr)
            read_fd, write_fd = os.pipe()
            os.close(read_fd)
            with os.fdopen(write_fd, 'wb') as output:
                result = subprocess.run([str(Path(folder).resolve() / 'broken')], stdout=output,
                                        stderr=subprocess.PIPE, text=True, timeout=10)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('运行错误：输出失败', result.stderr)
            source = Path(folder).resolve() / 'broken.ru'
            source.write_text("试 显 'x'. 救 原因 显 '不可救'. 终.", encoding='utf-8')
            read_fd, write_fd = os.pipe()
            os.close(read_fd)
            with os.fdopen(write_fd, 'wb') as output:
                result = subprocess.run([sys.executable, str(ROOT / 'ru'), 'run', str(source)],
                                        stdout=output, stderr=subprocess.PIPE, text=True, timeout=10)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('运行错误：输出失败', result.stderr)
            self.assertNotIn('Exception ignored', result.stderr)

    def test_interpreter_recursion_unwinds(self):
        self.assertEqual(interpreted(STRESS), '底返\n')

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_native_sanitizer_stress(self):
        with tempfile.TemporaryDirectory() as folder:
            flags = ('-fsanitize=address,undefined', '-fno-omit-frame-pointer')
            probe = Path(folder).resolve() / 'sanitizer-probe.c'
            probe.write_text('int main(void) { return 0; }\n', encoding='utf-8')
            supported = subprocess.run(
                [CC, *flags, str(probe), '-o', str(probe.with_suffix('.exe'))],
                capture_output=True, text=True, timeout=30)
            if supported.returncode:
                self.skipTest('Selected C compiler cannot link ASan/UBSan: ' + supported.stderr)
            result = native(STRESS, folder, flags=flags)
            # Some managed executors run under ptrace, where LeakSanitizer
            # itself cannot start. Keep ASan/UBSan enabled and separately check
            # the runtime's exact zero-root/live-heap accounting there.
            if 'LeakSanitizer does not work under ptrace' in result.stderr:
                result = subprocess.run([str(Path(folder).resolve() / 'case')], capture_output=True,
                    text=True, timeout=40, env={**os.environ, 'RU_GC_THRESHOLD': '1',
                    'RU_GC_STATS': '1', 'ASAN_OPTIONS': 'detect_leaks=0:halt_on_error=1'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '底返\n')
            self.assertIn('RU_GC live=0 ', result.stderr)
            self.assertNotIn('Sanitizer', result.stderr)
            self.assertGreater(int(re.search(r'freed=(\d+)', result.stderr).group(1)), 30000)


if __name__ == '__main__':
    unittest.main()
