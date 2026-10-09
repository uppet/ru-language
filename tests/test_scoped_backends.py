"""Lexical statement blocks: Python/standalone JavaScript execution parity."""
import gc
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import weakref

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter
from rulang.js_compiler import JSCompiler

NODE = shutil.which('node') or shutil.which('nodejs')


CASES = [
    ('immediate_and_empty', '显 1. {} 段: 落. { 显 2. } 显 3.', '1\n2\n3\n'),
    ('keyword_and_fullwidth', '值 取 1. 段： 值 取 2。 ｛ 值 取 3。 显 值。 ｝ 显 值。 落。 显 值。', '3\n2\n1\n'),
    ('local_bindings', '值 取 1. { 显 值. 值 取 值+1. 显 值. 值 取 值+1. 显 值. } 显 值.', '1\n2\n3\n1\n'),
    ('function_local_shadow', '算 制 起: { 起 取 起+1. 显 起. } 得 起. 法 显 (制 4).', '5\n4\n'),
    ('flow_bindings_local', "值 取 10. { 若 真 则 值 取 1. 然 循 2 次 值 取 值+1. 环 试 值 取 值+1. 救 原因 显 '不应'. 终. 显 值. } 显 值.", '4\n10\n'),
    ('nested_blocks', '值 取 1. { 值 取 2. { 显 值. 值 取 3. 显 值. } 显 值. } 显 值.', '2\n3\n2\n1\n'),
    ('fresh_loop_entries', '列 取 []. 计 取 0. 循 3 次 计 取 计+1. { 值 取 计. 列 其 增 算: 值 取 值+10. 得 值. 法. } 环 显 列[0](). 显 列[1](). 显 列[0](). 显 列[2]().', '11\n12\n21\n13\n'),
    ('fresh_named_declarations', '列 取 []. 计 取 0. 循 2 次 计 取 计+1. { 值 取 计. 算 看: 得 值. 法 列 其 增 算 看. } 环 显 列[0](). 显 列[1](). 显 列[0] == 列[1].', '1\n2\n假\n'),
    ('hoisted_named_function', '{ 显 后. 算 后: 得 7. 法 }', '7\n'),
    ('shared_block_capture', '列 取 []. { 值 取 2. 算 看: 得 值. 法 作 改 新值: 值 取 新值. 为 列 其 增 算 看. 列 其 增 作 改. } 列[1] 9. 显 列[0]().', '9\n'),
    ('capture_outer_function', '算 制: 值 取 1. 列 取 []. { 列 其 增 算: 值 取 值+1. 得 值. 法. } 得 [列[0], 算: 得 值. 法]. 法 组 取 制. 显 组[0](). 显 组[1]().', '2\n2\n'),
    ('capture_nearest_block', '列 取 []. { 值 取 1. { 值 取 4. 列 其 增 算: 值 取 值+1. 得 值. 法. } 显 值. } 显 列[0]().', '1\n5\n'),
    ('capture_module_never_rebinds', '值 取 1. 列 取 []. { 列 其 增 算: 值 取 值+1. 得 值. 法. } 显 列[0](). 显 值.', '2\n1\n'),
    ('return_through_block', '算 取值: { { 得 7. } 显 99. } 得 0. 法 显 取值.', '7\n'),
    ('return_escaping_closure', '算 制: { 值 取 3. 得 算: 值 取 值+1. 得 值. 法. } 法 回调 取 制. 显 回调(). 显 回调().', '4\n5\n'),
    ('finish_through_block', '作 报: { 显 1. { 完. } 显 99. } 显 99. 为 报. 显 2.', '1\n2\n'),
    ('break_through_blocks', '值 取 1. 循 3 次 { 值 取 2. { 破. } 显 99. } 显 99. 环 显 值.', '1\n'),
    ('break_inner_loop_restores_block', '{ 值 取 2. 循 3 次 { 值 取 9. 破. } 环 显 值. }', '2\n'),
    ('panic_escape_capture', "列 取 []. 试 { 值 取 4. 列 其 增 算: 值 取 值+1. 得 值. 法. 卒 '因'. } 救 原因 显 原因. 终. 显 列[0]().", '因\n5\n'),
    ('return_through_try', "算 回: 试 { 得 8. } 救 原因 显 '不应'. 终. 得 0. 法 显 回.", '8\n'),
    ('break_through_try', "循 2 次 试 { 破. } 救 原因 显 '不应'. 终. 显 99. 环 显 1.", '1\n'),
    ('finish_through_rescue', "作 报: 试 卒 '因'. 救 原因 { 完. } 显 99. 终. 显 99. 为 报. 显 1.", '1\n'),
    ('rescue_uses_own_scope', "值 取 1. { 值 取 2. 试 卒 '因'. 救 原因 值 取 9. { 显 值. } 终. 显 值. } 显 值.", '9\n2\n1\n'),
    ('maps_remain_expressions', "图 取 {'数': 2}. { 图['数']. 显 {'数': 3}['数']. } 显 图['数']. 显 {}.", '3\n2\n{}\n'),
    ('shared_mutation', '列 取 [1]. { 列[0] 取 4. 列 其 增 5. } 显 列.', '[4, 5]\n'),
]


def interpreted(source, echo=False):
    output = io.StringIO()
    runtime = Interpreter(io.StringIO(), output)
    runtime.execute(parse(source), echo=echo)
    return output.getvalue(), runtime


class ScopedInterpreterTests(unittest.TestCase):
    def test_scoped_execution(self):
        for name, source, expected in CASES:
            with self.subTest(name=name):
                self.assertEqual(interpreted(source)[0], expected)

    def test_block_names_do_not_escape(self):
        for source in ('{ 临时 取 1. } 显 临时.',
                       '{ 算 临时: 得 1. 法 } 显 临时.'):
            with self.subTest(source=source), self.assertRaises(RuError):
                interpreted(source)

    def test_repl_echo_preserved_without_exposing_bindings(self):
        output, runtime = interpreted('{ 1. 值 取 2. 值. }', echo=True)
        self.assertEqual(output, '1\n2\n')
        self.assertNotIn('值', runtime.global_scope.values)

    def test_escaped_block_environment_is_collected(self):
        _, runtime = interpreted('列 取 []. { 值 取 3. 列 其 增 算: 值 取 值+1. 得 值. 法. }')
        scope = runtime.global_scope.values['列'][0].environment
        self.assertEqual(scope.kind, 'block')
        reference = weakref.ref(scope)
        del scope
        gc.collect()
        self.assertIsNotNone(reference())
        runtime.global_scope.values['列'].clear()
        gc.collect()
        self.assertIsNone(reference())


@unittest.skipUnless(NODE, 'Node.js unavailable')
class ScopedJavaScriptTests(unittest.TestCase):
    def test_scoped_execution_full_and_pruned(self):
        with tempfile.TemporaryDirectory(prefix='ru-scoped-js-') as folder:
            output = Path(folder) / 'program.js'
            for full in (False, True):
                for name, source, expected in CASES:
                    with self.subTest(name=name, full_runtime=full):
                        output.write_text(JSCompiler(parse(source), '<作用域测试>', full_runtime=full).compile(), encoding='utf-8')
                        result = subprocess.run([NODE, str(output)], capture_output=True,
                                                text=True, encoding='utf-8', timeout=20)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout, expected)
                        self.assertEqual(result.stderr, '')

    def test_block_calls_do_not_leak_into_enclosing_compilation(self):
        for source in ('{ 算 临时 值: 得 值. 法 } 显 (临时 2).',
                       '{ 临时 取 算 值: 得 值. 法. } 显 (临时 2).'):
            with self.subTest(source=source), self.assertRaises(RuError):
                JSCompiler(parse(source)).compile()


if __name__ == '__main__':
    unittest.main()
