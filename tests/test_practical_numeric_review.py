"""Independent exact-value and PCG-oracle review for the practical library.

The decimal oracle uses Decimal's exact float conversion and ROUND_HALF_UP,
not the runtime's integer-ratio algorithm. PCG words come from the published
42/54 reference demo: https://www.pcg-random.org/using-pcg-c-basic.html
"""
from decimal import Decimal, ROUND_HALF_UP, localcontext
import io
import math
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.frontend import Node, RuError, Token, parse
from rulang.interpreter import Interpreter
from rulang.modules import load_module_graph
from rulang.practical_runtime import _Random, fixed_text, practical_member

NODE = shutil.which('node') or shutil.which('nodejs')
CC = shutil.which(os.environ.get('CC', 'cc'))
PRELUDE = "文 取 外言 '如:文本'. 数学 取 外言 '如:数学'. 随 取 外言 '如:随机'.\n"
RAW = [2707161783, 2068313097, 3122475824, 2211639955, 3215226955, 3421331566]


def decimal_oracle(value, places):
    with localcontext() as context:
        context.prec = 1200
        exact = Decimal.from_float(value)
        return format(exact.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP), 'f')


def edge_values():
    values = [0.0, -0.0, 5e-324, -5e-324, sys.float_info.min,
              sys.float_info.max, -sys.float_info.max,
              1000000000000000128.0, 4503599627370495.5,
              4503599627370496.0, 9007199254740991.0]
    for value in [0.5, 1.25, 2.5, 0.15, 0.35, 1.005, 2.675, 2.685, 9.995, 9.999]:
        for adjacent in [math.nextafter(value, -math.inf), value, math.nextafter(value, math.inf)]:
            values.extend([adjacent, -adjacent])
    return values


def generated_fixed_case():
    statements, answers = [], []
    for value in edge_values():
        literal = f'({repr(value)})'
        for places in [0, 1, 2, 15]:
            statements.append(f'显 (文 其 定点 {literal} {places}).')
            answers.append(decimal_oracle(value, places))
    return PRELUDE + '\n'.join(statements), '\n'.join(answers) + '\n'


RANDOM_SOURCE = PRELUDE + """
源 取 随 其 造源 种子:42.
循 6 次 显 源 其 整数 下:0 上:4294967295. 环
拒 取 随 其 造源 42.
循 6 次 显 拒 其 整数 0 2147483648. 环
显 拒 其 整数 0 4294967295.
洗 取 随 其 造源 42.
原 取 [0,1,2,3,4,5,6,7,8,9].
显 洗 其 洗牌 列:原. 显 原. 显 洗 其 整数 0 4294967295.
上源 取 随 其 造源 42. 下源 取 随 其 造源 42.
显 文 其 定点 (上源 其 整数 9007194959773696 9007199254740991) 0.
显 文 其 定点 (下源 其 整数 (-9007199254740991) (-9007194959773696)) 0.
无耗 取 随 其 造源 42.
显 文 其 定点 (无耗 其 整数 (-0) (-0)) 2.
空阵 取 []. 单阵 取 [[]].
空副 取 无耗 其 洗牌 空阵. 单副 取 无耗 其 洗牌 单阵.
显 空副 == 空阵. 显 单副 == 单阵. 显 单副[0] == 单阵[0].
显 无耗 其 整数 0 4294967295.
别名 取 无耗. 独立 取 随 其 造源 42.
显 别名 其 整数 0 4294967295. 显 独立 其 整数 0 4294967295.
显 无耗 其 整数 0 4294967295.
"""
RANDOM_EXPECTED = '\n'.join(map(str, RAW + [559678134, 974992175, 64156306,
    1067743306, 1273847917, 1069982636, 2167406445])) + "\n" + """[8, 2, 6, 4, 5, 1, 7, 0, 9, 3]
[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
4181216144
9007197666935479
-9007196547579208
0.00
假
假
真
2707161783
2068313097
2707161783
3122475824
"""

MATH_SOURCE = PRELUDE + """
显 数学 其 平方根 (-0). 显 数学 其 向下取整 (-0).
显 数学 其 向上取整 (-0). 显 数学 其 四舍五入 (-0).
显 数学 其 向上取整 (-0.5). 显 数学 其 四舍五入 (-0.49999999999999994).
显 数学 其 四舍五入 0.49999999999999994.
显 数学 其 四舍五入 0.5. 显 数学 其 四舍五入 (-0.5).
显 文 其 定点 (数学 其 四舍五入 4503599627370495.5) 0.
显 文 其 定点 (数学 其 四舍五入 4503599627370496) 0.
显 数学 其 幂 0 0. 显 数学 其 幂 (-0) 0.
显 数学 其 幂 (-0) 3. 显 数学 其 幂 (-0) 2.
显 数学 其 幂 (-0) 0.5. 显 数学 其 幂 (-2) 3.
显 数学 其 幂 (-2) (-3). 显 数学 其 幂 2 (-1075).
显 数学 其 幂 (-2) (-1075).
引用 取 算 数学 其 四舍五入. 显 引用 值:(-1.5).
列 取 [假,0,真,1,空]. 显 列 其 查 0. 显 列 其 查 假.
显 列 其 查 1. 显 列 其 查 真. 显 列 其 查 空.
显 数学 其 绝对 (-0). 显 数学 其 取整 (-0.5).
显 数学 其 小 0 (-0). 显 数学 其 大 (-0) 0.
显 数学 其 整除 (-7) 3.
"""
MATH_EXPECTED = """-0
-0
-0
-0
-0
-0
0
1
-1
4503599627370496
4503599627370496
1
1
-0
0
0
-8
-0.125
0
-0
-2
1
0
3
2
4
-0
-0
-0
0
-2
"""


class IndependentNumericOracleTests(unittest.TestCase):
    def setUp(self):
        self.owner = Interpreter(io.StringIO(), io.StringIO())
        self.node = Node('number', Token('NUMBER', '0', 1, 1), {})
        self.helper = self.owner.global_scope.find('__实用')[0]

    def invoke(self, name, *values, receiver=None):
        handled, value = practical_member(self.owner, self.node,
            self.helper if receiver is None else receiver, name,
            [(None, item) for item in values])
        self.assertTrue(handled)
        return value

    def test_official_pcg_reference_words(self):
        source = _Random(42)
        self.assertEqual([source.next() for _ in RAW], RAW)

    def test_rejection_consumes_the_rejected_word(self):
        source = _Random(42)
        self.assertEqual([source.bounded(2147483649) for _ in range(6)],
            [559678134, 974992175, 64156306, 1067743306, 1273847917, 1069982636])
        self.assertEqual(source.next(), 2167406445)

    def test_threshold_boundary_and_full_width(self):
        class Prescribed(_Random):
            def __init__(self, values):
                self.values, self.draws = iter(values), 0
            def next(self):
                self.draws += 1
                return next(self.values)
        source = Prescribed([2147483646, 2147483647])
        self.assertEqual(source.bounded(2147483649), 2147483647)
        self.assertEqual(source.draws, 2)
        source = Prescribed([4294967295])
        self.assertEqual(source.bounded(1), 0)
        self.assertEqual(source.draws, 0)
        self.assertEqual(source.bounded(4294967296), 4294967295)
        self.assertEqual(source.draws, 1)

    def test_fixed_decimal_binary64_edges(self):
        for value in edge_values():
            for places in range(16):
                with self.subTest(value=value.hex(), places=places):
                    self.assertEqual(fixed_text(value, places), decimal_oracle(value, places))

    def test_fixed_independent_random_bit_patterns(self):
        source = random.Random(121209)
        for _ in range(400):
            value = struct.unpack('>d', source.getrandbits(64).to_bytes(8, 'big'))[0]
            if not math.isfinite(value):
                continue
            for places in [0, 1, 2, 7, 15]:
                with self.subTest(value=value.hex(), places=places):
                    self.assertEqual(fixed_text(value, places), decimal_oracle(value, places))

    def test_math_signed_zero_and_extreme_finite_values(self):
        for name in ['平方根', '向下取整', '向上取整', '四舍五入']:
            result = self.invoke(name, -0.0)
            self.assertEqual(result, 0)
            self.assertEqual(math.copysign(1, result), -1)
        for name in ['向下取整', '向上取整', '四舍五入']:
            for value in [sys.float_info.max, -sys.float_info.max]:
                self.assertEqual(self.invoke(name, value), value)
        self.assertEqual(self.invoke('四舍五入', math.nextafter(0.5, 0)), 0)
        self.assertEqual(self.invoke('四舍五入', 4503599627370495.5), 4503599627370496)

    def test_non_numbers_and_nonfinite_numbers_are_rejected(self):
        for value in [False, True, 1, '1', None, [], math.inf, -math.inf, math.nan]:
            for name in ['平方根', '向下取整', '向上取整', '四舍五入']:
                with self.subTest(name=name, value=value), self.assertRaises(RuError):
                    self.invoke(name, value)
            with self.subTest(name='定点', value=value), self.assertRaises(RuError):
                self.invoke('定点', value, 2.0)

    def test_fixed_places_and_random_seed_validation(self):
        for places in [-1.0, 16.0, 0.5, False, True, '2', math.inf, math.nan]:
            with self.subTest(places=places), self.assertRaises(RuError):
                self.invoke('定点', 1.0, places)
        self.assertEqual(self.invoke('定点', -0.0, -0.0), '-0')
        for seed in [-1.0, 4294967296.0, 0.5, False, True, '2', math.inf, math.nan]:
            with self.subTest(seed=seed), self.assertRaises(RuError):
                self.invoke('造源', seed)
        zero, negative_zero = self.invoke('造源', 0.0), self.invoke('造源', -0.0)
        self.assertIsNot(zero, negative_zero)
        self.assertEqual(zero.practical_state.state, negative_zero.practical_state.state)
        self.invoke('造源', 4294967295.0)

    def test_pow_real_domain_and_overflow(self):
        for base, exponent in [(-2.0, 0.5), (0.0, -1.0), (-0.0, -1.0),
                               (2.0, 1024.0), (False, 2.0), (2.0, False)]:
            with self.subTest(base=base, exponent=exponent), self.assertRaises(RuError):
                self.invoke('幂', base, exponent)
        self.assertEqual(self.invoke('幂', 0.0, 0.0), 1)
        self.assertEqual(self.invoke('幂', -1.0, 9007199254740991.0), -1)
        self.assertEqual(self.invoke('幂', -1.0, 9007199254740992.0), 1)

    def test_random_invalid_calls_do_not_advance_state(self):
        source = self.invoke('造源', 42.0)
        before = source.practical_state.state
        bad = [(False, 1.0), (0.0, False), (0.5, 1.0), (0.0, 0.5),
               (1.0, 0.0), (0.0, 4294967296.0),
               (-9007199254740992.0, -9007199254740992.0),
               (9007199254740992.0, 9007199254740992.0)]
        for low, high in bad:
            with self.subTest(low=low, high=high), self.assertRaises(RuError):
                self.invoke('整数', low, high, receiver=source)
            self.assertEqual(source.practical_state.state, before)
        with self.assertRaises(RuError):
            self.invoke('洗牌', 'wrong', receiver=source)
        self.assertEqual(source.practical_state.state, before)

    def test_random_singletons_normalize_negative_zero_without_a_draw(self):
        source = self.invoke('造源', 42.0)
        before = source.practical_state.state
        result = self.invoke('整数', -0.0, -0.0, receiver=source)
        self.assertEqual(math.copysign(1, result), 1)
        for original in [[], [[]]]:
            copy = self.invoke('洗牌', original, receiver=source)
            self.assertIsNot(copy, original)
            if original:
                self.assertIs(copy[0], original[0])
        self.assertEqual(source.practical_state.state, before)


class IndependentNumericBackendTests(unittest.TestCase):
    def cases(self):
        return [('pcg_and_limits', RANDOM_SOURCE, RANDOM_EXPECTED),
                ('math_and_types', MATH_SOURCE, MATH_EXPECTED),
                ('exact_fixed', *generated_fixed_case())]

    def test_interpreter_oracles(self):
        for name, source, expected in self.cases():
            with self.subTest(name=name):
                graph = load_module_graph('/tmp/numeric-review.ru', parse(source))
                output = io.StringIO()
                Interpreter(io.StringIO(), output).execute(graph[graph.root], source_path=graph.root, modules=graph)
                self.assertEqual(output.getvalue(), expected)

    @unittest.skipUnless(NODE, 'Node.js unavailable')
    def test_javascript_default_and_full(self):
        from rulang.js_compiler import JSCompiler
        with tempfile.TemporaryDirectory() as folder:
            for name, source, expected in self.cases():
                graph = load_module_graph(str(Path(folder) / (name + '.ru')), parse(source))
                for full in [False, True]:
                    with self.subTest(name=name, full=full):
                        output = Path(folder) / (name + '.js')
                        output.write_text(JSCompiler(graph[graph.root], graph.root, modules=graph,
                            full_runtime=full).compile(), encoding='utf-8')
                        run = subprocess.run([NODE, str(output)], capture_output=True, text=True, encoding='utf-8', timeout=30)
                        self.assertEqual(run.returncode, 0, run.stderr)
                        self.assertEqual(run.stdout, expected)

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_native_default_and_full_forced_gc(self):
        from rulang.compiler import Compiler
        with tempfile.TemporaryDirectory() as folder:
            for name, source, expected in self.cases():
                graph = load_module_graph(str(Path(folder) / (name + '.ru')), parse(source))
                for full in [False, True]:
                    with self.subTest(name=name, full=full):
                        output, binary = Path(folder) / (name + '.c'), Path(folder) / (name + ('.exe' if os.name == 'nt' else '.out'))
                        output.write_text(Compiler(graph[graph.root], graph.root, modules=graph,
                            full_runtime=full).compile(), encoding='utf-8')
                        built = subprocess.run([CC, '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-Wno-unused-function', '-pedantic', str(output), '-lm', '-o', str(binary)],
                            capture_output=True, text=True, encoding='utf-8', timeout=60)
                        self.assertEqual(built.returncode, 0, built.stderr)
                        run = subprocess.run([str(binary)], capture_output=True, text=True, encoding='utf-8', timeout=30,
                            env={**os.environ, 'RU_GC_THRESHOLD': '1', 'RU_GC_STATS': '1'})
                        self.assertEqual(run.returncode, 0, run.stderr)
                        self.assertEqual(run.stdout, expected)
                        self.assertIn('RU_GC live=0 ', run.stderr)


if __name__ == '__main__':
    unittest.main()
