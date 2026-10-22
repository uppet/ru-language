"""Guards and honest diagnostics for deep program structure.

The parser caps combined source nesting at 128 (frontend). Call depth is
capped at 128 (invoke). Neither covers the multiplicative axis: deep calls
whose per-call expressions are themselves deep (the ``unary.ru`` shape:
128 calls x ~63 structure levels reaches past 8000 interpreter frames
while parsing stays under 30 and calls stay under 129). Interpreter-level
structure guard covers exactly that gap; these tests pin its behavior and
keep the legitimate deep-recursion repro class green.
"""

import unittest

from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter, STRUCTURE_DEPTH_LIMIT


def run(source):
    program = parse(source)
    from io import StringIO
    out = StringIO()
    interpreter = Interpreter(stdout=out)
    interpreter.execute(program)
    return out.getvalue()


def unary_chain(calls, width):
    """Recursion like the reviewer's unary.ru: each call wraps the next in
    a paren group preceded by ``width`` unary negations."""
    return (
        f"算 阶 值 为 数:\n"
        f" 若 值 <= 0 则\n"
        f"  得 1.\n"
        f" 另\n"
        f" 得 {'- ' * width}({' ' * 0}阶 值: 值 - 1).\n"
        f" 然.\n"
        f"法.\n"
        f"结果 取 阶 值:{calls}.\n"
        f"显 结果.\n"
    )


class StructureDepthTests(unittest.TestCase):
    def test_legit_deep_unary_chain_still_runs(self):
        # 80 calls x 80 unaries = 6400 interpreter frames: the reviewer's
        # repro class must keep working (guard sits at 8000).
        self.assertEqual(run(unary_chain(80, 80)), "1\n")

    def test_guard_fires_with_runtime_category_and_position(self):
        # 63 unaries per call x ~127 reachable calls exceeds 8000 total
        # structure before the 128 call limit: the interpreter guard must
        # fire first, as a runtime error at a real source position.
        with self.assertRaises(RuError) as caught:
            run(unary_chain(127, 63))
        error = caught.exception
        self.assertEqual(error.category, "运行错误")
        self.assertIn(str(STRUCTURE_DEPTH_LIMIT), error.message)
        self.assertIn("拆分为较小的步骤", error.message)
        self.assertGreater(error.line, 1)  # position points inside the body

    def test_call_depth_error_still_runtime(self):
        with self.assertRaises(RuError) as caught:
            run(unary_chain(200, 1))
        error = caught.exception
        self.assertEqual(error.category, "运行错误")
        self.assertIn("128", error.message)

    def test_parser_depth_limit_unchanged(self):
        # Pure source nesting still fails at parse time with the parser's
        # own message; the interpreter guard is not involved.
        with self.assertRaises(RuError) as caught:
            parse("结果 取 " + "(" * 200 + "1" + ")" * 200 + ".\n")
        self.assertIn("源码嵌套过深", caught.exception.message)

    def test_shallow_program_unaffected(self):
        self.assertEqual(run("显 1 + 2 * 3.\n"), "7\n")


if __name__ == "__main__":
    unittest.main()
