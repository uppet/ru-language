"""Scoped statements: strict C lowering, flow transfers, and traced captures."""
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rulang.compiler import Compiler
from rulang.frontend import RuError, parse
import test_runtime_pruning as native


CASES = [
    ('empty_and_constant', '段: 落. {} 段: 显 1. 落. {显 2.}', '1\n2\n'),
    ('direct_control_bindings', '''
        值 取 1.
        段:
            若 真 则 值 取 2. 然
            循 2 次 值 取 值+1. 环
            试 值 取 值+1. 救 因 卒 因. 终.
            显 值.
            {值 取 值+10. 显 值.}
            显 值.
        落.
        显 值.
    ''', '5\n15\n5\n1\n'),
    ('escaping_and_shared', '''
        值 取 100. 存 取 [].
        段:
            值 取 10.
            算 加: 值 取 值+1. 得 值. 法
            存 其 增 算 加.
            存 其 增 算: 值 取 值+2. 得 值. 法.
        落.
        显 存[0](). 显 存[1](). 显 存[0](). 显 值.
    ''', '11\n13\n14\n100\n'),
    ('fresh_each_iteration', '''
        存 取 []. 位值 取 [0].
        循 3 次 {
            位值[0] 取 位值[0]+1.
            值 取 位值[0].
            存 其 增 算: 得 值. 法.
        } 环
        显 存[0](). 显 存[1](). 显 存[2]().
    ''', '1\n2\n3\n'),
    ('forward_and_mutual_recursion', '''
        存 取 [].
        段:
            存 其 增 算 偶.
            算 偶 值 为 数: 若 值 == 0 则 得 真. 然 得 奇 值-1. 法
            算 奇 值 为 数: 若 值 == 0 则 得 假. 然 得 偶 值-1. 法
        落.
        显 存[0] 10. 显 存[0] 9.
    ''', '真\n假\n'),
    ('outer_capture_and_block_shadow', '''
        算 制:
            值 取 1. 存 取 [].
            段:
                算 改: 值 取 值+1. 得 值. 法
                显 改.
                值 取 10.
                存 其 增 算 改.
            落.
            显 值.
            得 存[0].
        法
        回 取 制. 显 回(). 显 回().
    ''', '2\n2\n11\n12\n'),
    ('return_nested_rescues', '''
        算 制:
            段:
                值 取 4.
                试 卒 '外'. 救 外因 {
                    试 卒 '内'. 救 内因
                        段: 得 算: 值 取 值+1. 得 (外因+内因) 对 值. 法. 落.
                    终.
                } 终.
            落.
            得 空.
        法
        回 取 制. 显 回(). 显 回().
    ''', '(外内 对 5)\n(外内 对 6)\n'),
    ('finish_escape', '''
        存 取 [].
        作 制:
            {值 取 '保留'. 试 卒 '因'. 救 因 {存 其 增 算: 得 值+因. 法. 完.} 终.}
            显 '不应执行'.
        为
        显 制. 显 存[0]().
    ''', '空\n保留因\n'),
    ('break_cleanup', '''
        存 取 [].
        段:
            外值 取 9.
            循 3 次 {值 取 1. 试 卒 '因'. 救 因
                {存 其 增 算: 得 外值+值. 法. 破.}
            终.} 环
            显 外值.
        落.
        显 存[0]().
    ''', '9\n10\n'),
    ('panic_nested_cleanup', '''
        存 取 [].
        试 {
            值 取 7.
            试 {卒 '内'.} 救 因 显 因. 终.
            {存 其 增 算: 得 值. 法. 卒 '外'.}
        } 救 因 显 因. 终.
        显 存[0]().
    ''', '内\n外\n7\n'),
    ('method_self_capture', '''
        形 盒:
            值 为 数.
            算 制: {增量 取 3. 得 算: 其 值 取 其 值+增量. 得 其 值. 法.} 法
        象
        对象 取 新 盒 值:4. 回 取 对象 其 制. 对象 取 空.
        显 回(). 显 回().
    ''', '7\n10\n'),
]

STRESS = '''
存 取 [].
作 制:
    段:
        值 取 [40]. 值 其 增 值.
        算 回: 值[0] 取 值[0]+1. 得 值[0]. 法
        试 卒 '因'. 救 因 {存 其 增 算 回. 完.} 终.
    落.
为
循 600 次
    制.
    若 存[0]() != 41 则 卒 '捕获损坏'. 然
    存 取 [].
    循 {环值 取 []. 环值 其 增 环值. 破.} 环
    试 {卒 '外'.} 救 因 {局部 取 因.} 终.
环
显 制. 显 存[0](). 存 取 空.
'''


@unittest.skipUnless(native.CC, 'C compiler unavailable')
class ScopedBlocksNativeTests(unittest.TestCase):
    def test_native_flow_and_capture_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, source, expected in CASES:
                with self.subTest(name=name):
                    binary = native.build(native.generate(source), directory, name)
                    result = native.run(binary)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, expected)
                    self.assertIn('RU_GC live=0 ', result.stderr)

    def test_full_and_pruned_runtime_release_cycles(self):
        with tempfile.TemporaryDirectory() as directory:
            for full in (False, True):
                with self.subTest(full=full):
                    generated = native.generate(STRESS, full=full).replace(
                        'ru_shutdown(); return status;',
                        'ru_gc(); fprintf(stderr, "BEFORE_SHUTDOWN live=%zu freed=%zu\\n", '
                        'ru_live, ru_freed); ru_shutdown(); return status;')
                    result = native.run(native.build(generated, directory, 'stress'+str(full)))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, '空\n41\n')
                    match = re.search(r'BEFORE_SHUTDOWN live=(\d+) freed=(\d+)', result.stderr)
                    self.assertIsNotNone(match, result.stderr)
                    self.assertLess(int(match[1]), 100, result.stderr)
                    self.assertGreater(int(match[2]), 6000, result.stderr)
                    self.assertIn('RU_GC live=0 ', result.stderr)

    def test_block_function_names_do_not_leak_into_static_lookup(self):
        source = '段: 算 私有 值 为 数: 得 值. 法 落. 显 私有 1.'
        with self.assertRaisesRegex(RuError, '未定义函数'):
            Compiler(parse(source)).compile()


if __name__ == '__main__':
    unittest.main()
