"""Host-backed animation mathematics, all targets and dependency pruning."""
import math
from pathlib import Path
import tempfile
import unittest

from test_practical import CC, NODE, execute_target, interpreted
from rulang.compiler import Compiler
from rulang.frontend import RuError, parse
from rulang.modules import load_module_graph
from rulang.stdlib_pruning import _trusted_declarations

PRELUDE = "数学 取 外言 '如:数学'.\n"
PROGRAM = PRELUDE + '''
显 数学 其 圆周率.
显 数学 其 正弦 弧度:0.
显 数学 其 余弦 弧度:0.
显 数学 其 正弦 (数学 其 圆周率 / 2).
显 数学 其 余弦 数学 其 圆周率.
显 数学 其 角度转弧度 角度:180.
显 数学 其 弧度转角度 弧度:数学 其 圆周率.
显 数学 其 方向角 横:0 纵:1.
显 数学 其 方向角 1 (-1).
显 数学 其 方向角 (-1) (-1).
显 数学 其 方向角 (-1) 1.
显 数学 其 正弦 1e308.
显 数学 其 余弦 (-1e308).
显 数学 其 角度转弧度 1e308.
正弦引用 取 算 数学 其 正弦. 显 正弦引用 0.
方向引用 取 算 数学 其 方向角. 显 方向引用 0 1.
尽 取 外言 '如:数学'. 显 圆周率. 显 余弦 0.
'''
EXPECTED = [math.pi, 0, 1, 1, -1, math.pi, 180, math.pi/2,
            3*math.pi/4, -3*math.pi/4, -math.pi/4,
            math.sin(1e308), math.cos(-1e308), 1e308*(math.pi/180), 0, 0, math.pi, 1]
ZERO_PROGRAM = PRELUDE + '''
显 数学 其 正弦 (-0). 显 数学 其 余弦 (-0).
显 数学 其 角度转弧度 (-0). 显 数学 其 弧度转角度 (-0).
显 数学 其 方向角 (-0) 1. 显 数学 其 方向角 0 0.
显 数学 其 方向角 (-0) 0.
显 数学 其 方向角 0 (-0). 显 数学 其 方向角 (-0) (-0).
'''
ZERO_EXPECTED = '-0\n1\n-0\n-0\n-0\n0\n-0\n3.14159265358979\n-3.14159265358979\n'
ERRORS = ["数学 其 正弦 真.", "数学 其 余弦 '零'.", "数学 其 角度转弧度 空.",
          "数学 其 弧度转角度 1e308.", "数学 其 方向角 0 真.",
          "数学 其 正弦 角度:90.", "数学 其 方向角 1.", "数学 其 圆周率 1."]

class TrigonometryTests(unittest.TestCase):
    def assert_numbers(self, output):
        actual = list(map(float, output.splitlines()))
        self.assertEqual(len(actual), len(EXPECTED))
        for value, expected in zip(actual, EXPECTED):
            self.assertTrue(math.isclose(value, expected, rel_tol=1e-13, abs_tol=1e-14), (value, expected))

    def test_interpreter(self):
        self.assert_numbers(interpreted(PROGRAM))
        self.assertEqual(interpreted(ZERO_PROGRAM), ZERO_EXPECTED)
        for source in ERRORS:
            with self.subTest(source=source), self.assertRaises(RuError):
                interpreted(PRELUDE + source)

    def targets(self, target):
        with tempfile.TemporaryDirectory() as tmp:
            for full in (False, True):
                for source in (PROGRAM, ZERO_PROGRAM):
                    with self.subTest(target=target, full=full, zero=source==ZERO_PROGRAM):
                        result = execute_target(source, target, Path(tmp), full)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        if source == PROGRAM:
                            self.assert_numbers(result.stdout)
                        else:
                            self.assertEqual(result.stdout, ZERO_EXPECTED)
                for source in ERRORS:
                    with self.subTest(target=target, full=full, error=source):
                        try:
                            result = execute_target(PRELUDE+source, target, Path(tmp), full)
                        except RuError:
                            continue
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('错误', result.stderr)

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_c(self):
        self.targets('c')

    @unittest.skipUnless(NODE, 'Node unavailable')
    def test_js(self):
        self.targets('js')

    def test_pruning(self):
        def generate(source):
            graph = load_module_graph('/tmp/math-pruning.ru', parse(source))
            return Compiler(graph[graph.root], graph.root, modules=graph).compile()
        for source in ["显 '你好'.", PRELUDE+"显 数学 其 平方根 4.", PRELUDE+"显 数学 其 圆周率."]:
            generated = generate(source)
            for symbol in ['ru_practical_sin(', 'ru_practical_cos(', 'ru_practical_atan2(',
                           'ru_practical_radians(', 'ru_practical_degrees(']:
                self.assertNotIn(symbol, generated)
        generated = generate(PRELUDE+"显 数学 其 正弦 1.")
        self.assertIn('ru_practical_sin(', generated)
        self.assertNotIn('ru_practical_cos(', generated)
        self.assertNotIn('ru_practical_atan2(', generated)
        self.assertNotIn('ru_practical_pow(', generated)
        # A shipped file match alone must not make side-effecting initialization safe.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'library.ru'
            for source, trusted in [('常量 取 3.14.', True), ("常量 取 '文'.", False),
                                    ('常量 取 1 + 2.', False), ('显 1.', False)]:
                path.write_text(source)
                self.assertEqual(_trusted_declarations(parse(source), path), trusted)

if __name__ == '__main__':
    unittest.main()
