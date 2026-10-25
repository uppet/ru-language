"""Independent stress contracts for the explicit interpreter evaluation stack.

SOURCE tests use the real parser (its 128 nesting limit is unchanged).
AST_ONLY tests deliberately bypass parsing/validation and make no claim that
6400-deep textual syntax is accepted. No recursion/OS-stack limits are changed.
The original tests/test_structure_depth.py remains a separate required suite.
"""
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest

import rulang.interpreter as interpreter_module
from rulang.frontend import Node, Token, RuError, parse
from rulang.interpreter import Interpreter, Scope, RuType, Instance, STRUCTURE_DEPTH_LIMIT


def n(kind, **data):
    return Node(kind, Token('TEST', kind, 17, 9), data)


def number(value=1):
    return n('number', value=float(value))


def recursive_source(calls, expression):
    return ("算 同 值 为 数: 得 值. 法\n"
            "算 阶 值 为 数:\n若 值 <= 0 则 得 1. 另\n得 " + expression +
            ".\n然.\n法.\n显 (阶 " + str(calls) + ").\n")


def mixed_source(calls=80, rounds=8):
    expression = '(阶 (值 - 1))'
    for _ in range(rounds):
        # Binary, index/container, conversion, map/member, and call argument.
        expression = "(同 (({'项': ([((" + expression + ") + 0) 为 数][0])} 其 查 '项')))"
    return recursive_source(calls, expression)


class InterpreterStackDepthTests(unittest.TestCase):
    def runtime(self):
        output = io.StringIO()
        return Interpreter(stdout=output), output

    def assert_restored(self, runtime):
        self.assertEqual(runtime.structure_depth, 0)
        self.assertEqual(runtime.depth, 0)
        self.assertEqual(runtime.call_state[0], 0)

    def run_source(self, source):
        runtime, output = self.runtime()
        runtime.execute(parse(source))
        self.assert_restored(runtime)
        return output.getvalue()

    def test_source_mixed_expression_recursion_real_parser(self):
        self.assertEqual(self.run_source(mixed_source()), '1\n')

    def test_source_6400_unaries_inside_mixed_operations(self):
        leaf = '- ' * 80 + '(阶 (值 - 1))'
        expression = "(同 (({'项': ([((" + leaf + ") + 0) 为 数][0])} 其 查 '项')))"
        self.assertEqual(self.run_source(recursive_source(80, expression)), '1\n')

    def test_source_scope_try_if_recursion_return_unwinds(self):
        body = '得 (阶 (值 - 1)).'
        for _ in range(20):
            body = "{ 试 若 真 则 " + body + " 然 救 原因 卒 原因. 终 }"
        source = ('算 阶 值 为 数: 若 值 <= 0 则 得 1. 然 ' + body +
                  ' 法 显 (阶 80).')
        self.assertEqual(self.run_source(source), '1\n')

    def test_source_call_128_boundary_and_failure_restore(self):
        runtime, output = self.runtime()
        runtime.execute(parse(recursive_source(127, '(阶 (值 - 1))')))
        self.assertEqual(output.getvalue(), '1\n')
        self.assert_restored(runtime)
        with self.assertRaises(RuError) as caught:
            runtime.execute(parse('显 (阶 128).'))
        self.assertIn('128', caught.exception.message)
        self.assertEqual(caught.exception.category, '运行错误')
        self.assert_restored(runtime)
        runtime.execute(parse('显 7.'))
        self.assertTrue(output.getvalue().endswith('7\n'))

    def test_source_8000_guard_is_fatal_not_rescued_and_restores(self):
        runtime, output = self.runtime()
        source = recursive_source(127, '- ' * 63 + '(阶 (值 - 1))')
        source = source.replace('显 (阶 127).', "试 显 (阶 127). 救 原因 显 'WRONGLY RESCUED'. 终")
        with self.assertRaises(RuError) as caught:
            runtime.execute(parse(source))
        self.assertIn('8000', caught.exception.message)
        self.assertEqual(caught.exception.category, '运行错误')
        self.assertGreater(caught.exception.line, 1)
        self.assertNotIn('WRONGLY RESCUED', output.getvalue())
        self.assert_restored(runtime)
        runtime.execute(parse('显 7.'))
        self.assertEqual(output.getvalue(), '7\n')

    def test_source_panic_and_fatal_failure_restore_after_deep_calls(self):
        for leaf, rescued in [("卒 'deep panic'.", True), ("得 1 / 0.", False)]:
            with self.subTest(leaf=leaf):
                runtime, output = self.runtime()
                expression = '- ' * 70 + '(阶 (值 - 1))'
                source = recursive_source(80, expression).replace('得 1.', leaf)
                source = source.replace('显 (阶 80).', "试 显 (阶 80). 救 原因 显 原因. 终")
                if rescued:
                    runtime.execute(parse(source))
                    self.assertEqual(output.getvalue(), 'deep panic\n')
                else:
                    with self.assertRaises(RuError) as caught:
                        runtime.execute(parse(source))
                    self.assertIn('除数不能为零', caught.exception.message)
                self.assert_restored(runtime)
                runtime.execute(parse('显 7.'))
                self.assertTrue(output.getvalue().endswith('7\n'))

    def run_source_child(self, source, expected):
        # Implicit callbacks cross synchronous host boundaries. A fresh process
        # gives Windows native-stack failures an honest nonzero test result.
        script = ("import io,sys; from rulang.frontend import parse; "
                  "from rulang.interpreter import Interpreter; out=io.StringIO(); "
                  "r=Interpreter(stdout=out); r.execute(parse(sys.stdin.read())); "
                  "assert (r.structure_depth,r.depth,r.call_state[0])==(0,0,0); "
                  "sys.stdout.write(out.getvalue())")
        result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', script],
            input=source, text=True, encoding='utf-8', capture_output=True,
            cwd=Path(interpreter_module.__file__).resolve().parents[1], timeout=120,
            env={**os.environ, 'PYTHONUTF8':'1', 'PYTHONDONTWRITEBYTECODE':'1'})
        self.assertEqual(result.returncode, 0, result.stderr[-12000:])
        self.assertEqual(result.stdout, expected)

    def test_source_map_index_hash_and_equality_linear_callback_depth(self):
        for callback in ('印', '同'):
            with self.subTest(callback=callback):
                # Only ONE callback recurses. Seventy-five nested lookups, not
                # two recursive paths/exponential branching. No map mutation.
                expression = '- ' * 80 + '(物[(新 键形)])'
                recursive = ("若 层[0] > 0 则 层[0] 取 层[0]-1. 得 " +
                             (expression + ' * 0.' if callback == '印' else
                              '(' + expression + ' == 1).') + ' 然 ')
                hash_body = recursive + '得 0.' if callback == '印' else '得 0.'
                equal_body = recursive + '得 真.' if callback == '同' else '得 真.'
                source = ("层 取 [0]. 形 键形: 算 印: " + hash_body +
                          " 法 算 同 另一: " + equal_body + " 法 象 "
                          "物 取 典: (新 键形) 对 1. 成. 层[0] 取 75. "
                          "显 物[(新 键形)]. 显 层[0].")
                self.run_source_child(source, '1\n0\n')

    def test_source_contest_sort_linear_synchronous_callback_depth(self):
        # Exactly two elements => one comparison per sort. Comparator recurses
        # through a single nested sort, then returns0; no 2**depth explosion. The library wrapper plus
        # comparator consume two Ru calls per level: 61*2 remains below128.
        expression = '- ' * 96 + '((竞 其 排序 [2,1] (算 比))[0])'
        source = ("竞 取 外言 '如:竞'. 层 取 [60]. "
                  "算 比 左 为 数 右 为 数: 若 层[0] > 0 则 "
                  "层[0] 取 层[0]-1. 得 (" + expression + ") * 0. 然 得 0. 法 "
                  "显 (竞 其 排序 [2,1] (算 比)). 显 层[0].")
        self.run_source_child(source, '[2, 1]\n0\n')

    def test_source_1600_sequential_inheritance_declarations(self):
        # Sequential shallow declarations, NOT 1600 nested parser constructs.
        declarations = ['形 T0: 象']
        declarations += ['形 T'+str(i)+' 如 T'+str(i-1)+': 象' for i in range(1,1600)]
        source = '\n'.join(declarations) + '\n物 取 新 T1599. 显 7.'
        self.run_source_child(source, '7\n')

    def test_ast_only_6400_mixed_expression_nodes(self):
        runtime, _ = self.runtime()
        expression = number()
        # Exactly 6399 wrapper nodes plus the scalar leaf = 6400.
        for i in range(2133):
            expression = n('binary', op='+', left=expression, right=number(0))
            expression = n('array', items=[expression])
            expression = n('index', receiver=expression, index=number(0))
        self.assertEqual(runtime.expr(expression, runtime.global_scope), 1.0)
        self.assert_restored(runtime)

    def test_ast_only_8000_expression_boundary_and_error_position(self):
        runtime, _ = self.runtime()
        expression = number()
        for _ in range(STRUCTURE_DEPTH_LIMIT - 1):
            expression = n('unary', op='+', expr=expression)
        self.assertEqual(runtime.expr(expression, runtime.global_scope), 1.0)
        with self.assertRaises(RuError) as caught:
            runtime.expr(n('unary', op='+', expr=expression), runtime.global_scope)
        self.assertIn('8000', caught.exception.message)
        self.assertEqual((caught.exception.line, caught.exception.col), (17, 9))
        self.assert_restored(runtime)
        self.assertEqual(runtime.expr(number(7), runtime.global_scope), 7.0)

    def test_ast_only_deep_scope_try_if_blocks(self):
        runtime, output = self.runtime()
        body = [n('print', expr=number(7))]
        for i in range(6399):
            if i % 3 == 0:
                body = [n('scope', body=body)]
            elif i % 3 == 1:
                body = [n('if', condition=n('fact', value=True), yes=body, no=[])]
            else:
                body = [n('try', body=body, reason='原因', rescue=[n('print', expr=number(99))])]
        runtime.block(body, runtime.global_scope)
        self.assertEqual(output.getvalue(), '7\n')
        self.assert_restored(runtime)

    def test_source_instance_method_argument_deep_recursion(self):
        prefix = ('形 基: 算 接 值 为 数: 得 值. 法 象 '
                  '形 子 如 基: 象 盒 取 新 子.\n')
        expression = '(盒 其 接 (' + '- ' * 80 + '(阶 (值 - 1))))'
        self.assertEqual(self.run_source(prefix + recursive_source(80, expression)), '1\n')

    def test_ast_only_deep_override_parameter_identity_comparison(self):
        runtime, _ = self.runtime()
        annotation = '数' + ' 阵' * 6400
        def method(typ):
            return n('function', name='接', params=[('值', typ)], procedure=False,
                     body=[n('return', expr=number())])
        parent = RuType(runtime, n('type', name='TP', parent=None, fields=[], methods=[method(annotation)]))
        child = RuType(runtime, n('type', name='TC', parent='TP', fields=[], methods=[method(annotation)]))
        runtime.types.update(TP=parent, TC=child)
        runtime.resolve_type(child)
        self.assertEqual(child.state, 2)
        bad = RuType(runtime, n('type', name='TB', parent='TP', fields=[],
                               methods=[method('句' + ' 阵' * 6400)]))
        runtime.types['TB'] = bad
        with self.assertRaises(RuError) as caught:
            runtime.resolve_type(bad)
        self.assertIn('覆写方法', caught.exception.message)
        self.assertEqual((caught.exception.line, caught.exception.col), (17, 9))
        self.assertEqual(bad.state, 0)
        self.assertEqual(parent.state, 2)
        self.assert_restored(runtime)

    def test_ast_only_deep_type_identity_and_value_matching(self):
        runtime, _ = self.runtime()
        annotation = '数' + ' 阵' * 6400
        identity = runtime.type_identity(annotation, number())
        value, bad = 1.0, 'not a number'
        current = identity
        for _ in range(6400):
            self.assertIsInstance(current, tuple)
            self.assertEqual(current[0], 'array')
            current = current[1]
            value, bad = [value], [bad]
        self.assertEqual(current, '数')
        self.assertTrue(runtime.type_matches(value, identity))
        self.assertFalse(runtime.type_matches(bad, identity))
        self.assertTrue(runtime.type_matches(value, annotation))
        self.assertFalse(runtime.type_matches(bad, annotation))
        self.assert_restored(runtime)

    def test_ast_only_deep_inheritance_resolves_and_matches(self):
        runtime, _ = self.runtime()
        for i in range(1600):
            name = 'T' + str(i)
            runtime.types[name] = RuType(runtime, n('type', name=name,
                parent='T' + str(i-1) if i else None, fields=[], methods=[]))
        leaf = runtime.types['T1599']
        runtime.resolve_type(leaf)
        self.assertTrue(runtime.type_matches(Instance(leaf, {}), runtime.types['T0']))
        self.assertTrue(all(t.state == 2 for t in runtime.types.values()))
        self.assert_restored(runtime)

    def test_ast_only_inheritance_cycle_error_restores_resolution_states(self):
        runtime, _ = self.runtime()
        for name, parent in [('TA', 'TB'), ('TB', 'TC'), ('TC', 'TA')]:
            runtime.types[name] = RuType(runtime, n('type', name=name, parent=parent, fields=[], methods=[]))
        with self.assertRaises(RuError) as caught:
            runtime.resolve_type(runtime.types['TA'])
        self.assertEqual(caught.exception.category, '运行错误')
        self.assertEqual((caught.exception.line, caught.exception.col), (17, 9))
        self.assertTrue(all(t.state == 0 for t in runtime.types.values()))
        runtime.types['TC'].node.data['parent'] = None
        runtime.resolve_type(runtime.types['TA'])
        self.assertTrue(all(t.state == 2 for t in runtime.types.values()))
        self.assert_restored(runtime)


if __name__ == '__main__':
    unittest.main()
