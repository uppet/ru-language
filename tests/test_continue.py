"""续 skips only the current invocation's innermost loop iteration."""
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.frontend import Incomplete, RuError, parse, validate
from rulang.interpreter import Interpreter
from rulang.execution_budget import Budget, BudgetPolicy, activate_budget, current_budget
from rulang.frontend import BudgetExceeded

CASES = [
    ('counted', '序 取 0. 循 5 次 序 取 序+1. 若 序 % 2 == 0 则 续. 然 显 序. 环 显 序.', '1\n3\n5\n5\n'),
    ('always_continue', '序 取 0. 循 4 次 序 取 序+1. 续. 显 99. 环 显 序.', '4\n'),
    ('zero', '循 0 次 续. 显 99. 环 显 7.', '7\n'),
    ('infinite', '序 取 0. 循 序 取 序+1. 若 序 < 3 则 续. 然 显 序. 破. 环', '3\n'),
    ('nested', '外数 取 0. 循 2 次 外数 取 外数+1. 内数 取 0. 循 3 次 内数 取 内数+1. 续. 显 99. 环 显 外数 对 内数. 环', '(1 对 3)\n(2 对 3)\n'),
    ('count_once', '次数 取 3. 序 取 0. 循 次数 次 序 取 序+1. 次数 取 0. 续. 环 显 序.', '3\n'),
    ('scope', '外值 取 8. 循 2 次 段: 内值 取 7. 显 内值. 续. 落. 显 99. 环 显 外值.', '7\n7\n8\n'),
    ('try_body', "序 取 0. 循 2 次 试 序 取 序+1. 续. 救 因 显 '不应捕获'. 终. 显 99. 环 试 卒 '后'. 救 因 显 因. 终. 显 序.", '后\n2\n'),
    ('rescue', "循 2 次 试 卒 '甲'. 救 因 显 因. 续. 终. 显 99. 环 试 卒 '后'. 救 因 显 因. 终.", '甲\n甲\n后\n'),
    ('outer_handler', "试 循 2 次 续. 环 卒 '仍可捕获'. 救 因 显 因. 终.", '仍可捕获\n'),
    ('nested_handlers', "循 2 次 试 试 续. 救 内因 显 内因. 终. 救 外因 显 外因. 终. 环 试 卒 '后'. 救 因 显 因. 终.", '后\n'),
    ('closure_escape', "存 取 []. 循 2 次 试 卒 '因'. 救 原因 存 其 增 算: 得 原因. 法. 续. 终. 环 显 存[0](). 显 存[1]().", '因\n因\n'),
    ('function', '算 数: 值 取 0. 循 3 次 值 取 值+1. 续. 环 得 值. 法 显 数.', '3\n'),
    ('procedure_finish', '作 停: 循 3 次 完. 续. 环 显 99. 为 显 停.', '空\n'),
    ('callback_local_loop', '列 取 [1,2]. 列 其 逐位 回调:(作 位, 值: 循 2 次 续. 环 显 值. 为).', '1\n2\n'),
    ('callback_finish', '列 取 [1,2,3]. 列 其 逐位 回调:(作 位, 值: 若 值 == 2 则 完. 然 显 值. 为).', '1\n3\n'),
    ('method', '形 盒: 作 行: 循 2 次 显 1. 续. 环 为 象 物 取 新 盒. 物 其 行.', '1\n1\n'),
    ('identifiers', '继续 取 3. 后续 取 4. 作 续行: 完. 为 显 继续+后续. 显 续行.', '7\n空\n'),
    ('unicode', '循 2 次 续。环。显 1。', '1\n'),
]
INVALID = [
    '续.', '若 真 则 续. 然', '作 错: 续. 为', '算 错: 续. 得 1. 法',
    '循 2 次 回 取 作: 续. 为. 环',
    '循 2 次 回 取 算: 续. 得 1. 法. 环',
    '循 2 次 段: 作 错: 续. 为 落. 环',
    '循 2 次 [1] 其 逐位 回调:(作 位, 值: 续. 为). 环',
    '形 盒: 作 错: 续. 为 象',
    '续 取 1.', '循 2 次 续 1. 环', '循 2 次 续 空. 环',
]

class ContinueTests(unittest.TestCase):
    def test_ast_and_incomplete(self):
        for punctuation in ('.', '。'):
            statement = parse('循 1 次 续'+punctuation+' 环')[0].data['body'][0]
            self.assertEqual((statement.kind, statement.data), ('continue', {}))
        with self.assertRaises(Incomplete): parse('循 1 次 续')

    def test_semantics_and_frame_cleanup(self):
        for name, source, expected in CASES:
            with self.subTest(name=name):
                output = io.StringIO(); vm = Interpreter(stdout=output)
                vm.execute(parse(source))
                self.assertEqual(output.getvalue(), expected)
                self.assertEqual((vm.depth, vm.structure_depth, vm.call_state), (0, 0, [0]))

    def test_invalid_boundary_and_arguments(self):
        for source in INVALID:
            with self.subTest(source=source), self.assertRaises(RuError):
                validate(parse(source))

    def test_loop_escape_diagnostic_location(self):
        with self.assertRaises(RuError) as caught:
            validate(parse('\n  续.'))
        self.assertIn('「续」只能出现在当前函数的循环内', str(caught.exception))
        self.assertEqual((caught.exception.line, caught.exception.col), (2, 3))

    def test_continue_loop_cannot_evade_sticky_budget(self):
        vm = Interpreter(stdout=io.StringIO())
        program = parse("试 循 续. 环 救 因 显 '不应捕获'. 终.")
        budget = Budget(BudgetPolicy(100, 16), clock=lambda: 0.0,
                        memory=lambda: 0, started=0.0, memory_start=0)
        with activate_budget(budget):
            with self.assertRaises(BudgetExceeded) as caught: vm.execute(program)
            self.assertIs(caught.exception, budget.error)
        self.assertGreater(budget.counts['loop'], 0)
        self.assertEqual(vm.stdout.getvalue(), '')
        self.assertEqual((vm.depth, vm.structure_depth, vm.call_state), (0, 0, [0]))
        self.assertIsNone(current_budget())

    def test_experimental_mi_subset_rejects_instead_of_miscompiling(self):
        from rulang.mi_source import SourceLowerer
        function = parse('算 计 次数: 循 次数 次 续. 环 得 1. 法')[0]
        validate([function])
        with self.assertRaisesRegex(RuError, '不支持的语句／效果：continue'):
            SourceLowerer(function, {'params': {'次数': 'u32'}, 'result': 'u32'},
                          '/continue.ru').run()

    def test_repl_reuse_after_continue(self):
        vm = Interpreter(stdout=io.StringIO())
        vm.execute(parse('值 取 0. 循 3 次 值 取 值+1. 续. 环'))
        vm.execute(parse('显 值.'))
        self.assertEqual(vm.stdout.getvalue(), '3\n')

if __name__ == '__main__': unittest.main()
