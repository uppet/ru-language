"""C scalar lowering preserves effects, errors and root ownership."""
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from rulang.frontend import parse
from rulang.interpreter import Interpreter
from test_c_bindings import CC, build, generate


CONDITIONS = """
算 报 值: 显 值. 得 值. 法.
算 错: 卒 'caught'. 得 真. 法.
若 0 且 非 空 则 显 'zero true'. 然.
显 (假 且 错()). 显 (真 或 错()).
显 ((报 0) 且 ((报 假) 或 (报 真))).
显 ((报 空) 或 ((报 7) 且 (报 ''))).
试 若 真 且 (错() 或 报 'wrong') 则 显 'wrong'. 然.
救 因 显 因. 终.
形 点:
 值 为 数.
 算 同 另一: 显 'compare'. 卒 'equality'. 得 假. 法.
象.
左 取 新 点 值:1. 右 取 新 点 值:2.
试 若 (左 == 右) 且 (报 'wrong') 则 显 'wrong'. 然.
救 因 显 因. 终.
序 取 0.
循 6 次
 序 取 序+1.
 若 序 == 2 或 序 == 4 则 续. 然.
 若 序 >= 5 且 序 != 6 则 破. 然.
 显 序.
环.
显 非 (1 < 2 且 3 >= 3). 显 (1 == 真 或 0 != -0).
显 ([] 且 {} 或 空). 显 ((1 对 2) == (1 对 2) 且 'a' < 'b').
"""


NUMBERS = """
算 报 值: 显 值. 得 值. 法.
算 算数 x:
 得 ((x-1)*(x+2)/(x+3)) % 7.
法.
显 算数 13.
显 ((报 4)-(报 1))*((报 2)+(报 3)).
显 -('2.5' 为 数) + +3.5.
显 -7 % 3. 显 7 % -3.
显 9007199254740992+1 == 9007199254740992.
显 5e-324/2 == 0. 显 0-0. 显 -0.
显 'left'+'right'.
值 取 [1]. 值[0] 取 (值[0]+2)*3. 显 值.
算 外:
 项 取 1. 算 改: 项 取 'changed'. 得 2. 法.
 得 ((项+1)*(改())) 对 项.
法.
显 外().
"""


CALL_STORAGE = """
形 盒:
 值 为 阵.
 算 改 列:
  算 看: 得 [其 值,列]. 法.
  其 值[0] 取 列[0].
  列[0] 取 'after'.
  得 算 看.
 法.
象.
共享 取 ['before']. 对象 取 新 盒 值:['old'].
闭包 取 对象 其 改 共享. 显 共享.
对象 取 空. 共享 取 空.
循 12 次 临时 取 ['pressure',[]]. 环.
显 闭包().
"""


CALL_STORAGE_OUTPUT = '[after]\n[[before], [after]]\n'


class ScalarExecutionContract:
    backend = 'c'

    def execute(self, source):
        with tempfile.TemporaryDirectory() as temporary:
            binary = build(generate(source), Path(temporary), 'scalar')
            return subprocess.run([str(binary)], capture_output=True, text=True, encoding='utf-8',
                                  timeout=30, env={**os.environ, 'RU_GC_THRESHOLD':'1', 'RU_GC_STATS':'1'})

    def test_short_circuit_truth_panic_equality_and_loop_cleanup(self):
        output = io.StringIO()
        Interpreter(stdout=output).execute(parse(CONDITIONS))
        result = self.execute(CONDITIONS)
        self.assertEqual((result.returncode, result.stdout), (0, output.getvalue()), result.stderr)
        self.assertRegex(result.stderr, r'^RU_GC live=0 freed=\d+ collections=\d+\s*$')

    def test_call_storage_allows_heap_mutation_and_escaping_closures(self):
        result = self.execute(CALL_STORAGE)
        self.assertEqual((result.returncode, result.stdout), (0, CALL_STORAGE_OUTPUT), result.stderr)
        self.assertRegex(result.stderr, r'^RU_GC live=0 freed=\d+ collections=\d+\s*$')

    def test_consumed_operands_keep_results_and_aliases_rooted(self):
        source = """
算 刷:
 循 12 次 临时 取 ['garbage', [1,2,3]]. 环.
 得 'later'.
法.
算 生: 得 [['kept'], ['other']]. 法.
显 [(生()[0])[0], 刷()].
显 [生()[0:1], 刷()].
显 [('甲'+'乙') 对 ('丙'+'丁'), 刷()].
显 [('12'+'3') 为 数, 刷()].
算 外:
 共同 取 [['old']].
 算 改: 共同[0] 取 ['new']. 得 刷(). 法.
 得 [共同[0], 改(), 共同[0]].
法.
显 外().
若 生()[0] 且 (刷() == 'later') 则 显 'truth'. 然.
"""
        output = io.StringIO()
        Interpreter(stdout=output).execute(parse(source))
        result = self.execute(source)
        self.assertEqual((result.returncode, result.stdout), (0, output.getvalue()), result.stderr)
        self.assertRegex(result.stderr, r'^RU_GC live=0 freed=\d+ collections=\d+\s*$')

    def test_comparison_diagnostic_is_preserved(self):
        result = self.execute("若 1 < 真 则 显 'wrong'. 然.")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('比较需要相同的数字或字符串类型', result.stderr)

    def test_control_character_literals_survive_native_source_processing(self):
        result = self.execute("显 '\\n'. 显 '\x1c\x1d\x1e\u0085\u2028\u2029'.")
        self.assertEqual((result.returncode, result.stdout), (0, '\n\n\x1c\x1d\x1e\u0085\u2028\u2029\n'), result.stderr)

    def test_numeric_intermediates_rounding_order_and_mutation(self):
        output = io.StringIO()
        Interpreter(stdout=output).execute(parse(NUMBERS))
        result = self.execute(NUMBERS)
        self.assertEqual((result.returncode, result.stdout), (0, output.getvalue()), result.stderr)
        self.assertRegex(result.stderr, r'^RU_GC live=0 freed=\d+ collections=\d+\s*$')

    def test_numeric_checks_keep_original_failure_order(self):
        cases = [
            ("('bad' - (报 2))", '2\n', '算术运算符 - 需要两个数字'),
            ("((报 1e308)*(报 2))*(报 0)", '1e+308\n2\n', '运算结果不是有限数字'),
            ("(报 1)/(报 (-0))", '1\n-0\n', '除数不能为零'),
            ("(报 1)%(报 0)", '1\n0\n', '除数不能为零'),
            ("-(报 'bad')", 'bad\n', '运算符 - 需要数字'),
        ]
        for expression, expected, error in cases:
            with self.subTest(expression=expression):
                result = self.execute('算 报 值: 显 值. 得 值. 法. 显 '+expression+'.')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, expected)
                self.assertIn(error, result.stderr)


@unittest.skipUnless(CC, 'C compiler required')
class ScalarCExecutionTests(ScalarExecutionContract, unittest.TestCase):
    backend = 'c'

