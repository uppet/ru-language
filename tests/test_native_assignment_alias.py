"""Native assignment aliases, retained effects, and evaluation order."""
import io
import tempfile
import unittest
from pathlib import Path
from rulang.interpreter import Interpreter
from rulang import native_c as n, native_tiered as t
from rulang.frontend import parse, RuError
from rulang.modules import load_module_graph
P = "密 取 外言 '如:密'. I 取 密 其 i32. F 取 密 其 f64. V 取 密 其 无值. "
PATH = str((Path(tempfile.gettempdir()) / 'native-assignment-alias.ru').resolve())

def plan(source, cls=n.NativeCPlan):
    return cls(load_module_graph(PATH, parse(P + source)))

def target():
    return parse('A[0] 取 B.')[0]

class NativeAssignmentAliasTests(unittest.TestCase):

    def test_new_assignment_alias_invalidates_through_container(self):
        source = "甲 取 [I]. 乙 取 [F]. 袋 取 [甲]. 袋[0] 取 乙. 算 改 包: C 取 包[0]. C[0] 取 0. 得 空. 法 改 袋. S 取 密 其 签名 V 乙 'cdecl'."
        for cls in (n.NativeCPlan, t._CoarsePlan, t.build_native_c_plan):
            with self.subTest(cls=cls.__name__), self.assertRaises((RuError, t._Refine) if cls is t._CoarsePlan else RuError):
                plan(source, cls)

    def test_safe_store_does_not_itself_mutate_rhs(self):
        for cls in (n.NativeCPlan, t._CoarsePlan, t.build_native_c_plan):
            with self.subTest(cls=cls.__name__):
                p = plan("A 取 [0]. B 取 [F]. A[0] 取 B. S 取 密 其 签名 V B 'cdecl'.", cls)
                self.assertEqual(p.signatures, (n.NativeCSignature('无值', ('f64',)),))

    def test_late_cached_read_observes_assigned_edge_change(self):
        source = "算 查 包: 得 包[0]. 法 A 取 [0]. A[0] 取 1. 查 A. 查 A. B 取 [I]. A[0] 取 B. C 取 查 A. C[0] 取 0. S 取 密 其 签名 V B 'cdecl'."
        for cls in (n.NativeCPlan, t._CoarsePlan, t.build_native_c_plan):
            with self.subTest(cls=cls.__name__), self.assertRaises((RuError, t._Refine) if cls is t._CoarsePlan else RuError):
                plan(source, cls)

    def test_array_literal_reentry_retains_assignment_edges(self):
        source = P + 'A 取 [0]. B 取 [I]. A[0] 取 B.'
        nodes = parse(source)
        p = n.NativeCPlan(load_module_graph(PATH, nodes))
        env = p._module_values[PATH].env
        a, b = (env.values['A'], env.values['B'])
        before = p._state()
        self.assertEqual(a.assigned, (b,))
        self.assertIsNotNone(b.items)
        literal = next((x for x in nodes if x.kind == 'bind' and x.data['name'] == 'A')).data['expr']
        self.assertIs(p._expr(literal, env), a)
        self.assertEqual(a.assigned, (b,))
        self.assertIsNone(b.items)
        self.assertNotEqual(before, p._state())

    def test_opaque_map_reentry_does_not_truncate_new_edges(self):
        source = P + "A 取 {'x':0}. B 取 [I]. A['x'] 取 B."
        nodes = parse(source)
        p = n.NativeCPlan(load_module_graph(PATH, nodes))
        env = p._module_values[PATH].env
        a, b = (env.values['A'], env.values['B'])
        self.assertEqual(a.assigned, (b,))
        self.assertIsNotNone(b.items)
        literal = next((x for x in nodes if x.kind == 'bind' and x.data['name'] == 'A')).data['expr']
        self.assertIs(p._expr(literal, env), a)
        self.assertEqual(a.assigned, (b,))
        self.assertIsNotNone(b.items)
        p._invalidate(a, nodes[-1])
        self.assertIsNone(b.items)

    def test_unknown_destination_does_not_hide_rhs(self):
        p = n.NativeCPlan({})
        b = n._Array((n._Type('i32'),))
        node = target()
        p._retain_assignment(n.UNKNOWN, b, node.data['target'], node)
        self.assertIsNone(b.items)

    def test_constructor_stored_then_escaped_still_rejects(self):
        p = n.NativeCPlan({})
        a = n._Array(())
        a.items = None
        node = target()
        op = n._Operation('签名', n.NATIVE)
        p._retain_assignment(a, op, node.data['target'], node)
        self.assertEqual(a.assigned, (op,))
        with self.assertRaisesRegex(RuError, '传给未知调用的原生描述符构造器'):
            p._invalidate(a, node)

    def test_cycles_are_idempotent_and_visible_to_structural_oracle(self):
        p = n.NativeCPlan({})
        env = p._environment()
        a = n._Array(())
        env.put('A', a)
        node = target()
        before = p._state()
        p._retain_assignment(a, a, node.data['target'], node)
        self.assertNotEqual(before, p._state())
        p._invalidate(a, node)
        stable = p._revision
        p._invalidate(a, node)
        self.assertEqual(stable, p._revision)
        self.assertEqual(a.assigned, (a,))

    def test_member_style_index_evaluates_its_arguments(self):
        source = "甲 取 [I]. 乙 取 [F]. 袋 取 [甲]. 算 索 X: X[0] 取 0. 得 0. 法 袋 其 位 (索 乙) 取 甲. S 取 密 其 签名 V 乙 'cdecl'."
        for cls in (n.NativeCPlan, t._CoarsePlan, t.build_native_c_plan):
            with self.subTest(cls=cls.__name__), self.assertRaises((RuError, t._Refine) if cls is t._CoarsePlan else RuError):
                plan(source, cls)

    def test_over_128_assigned_owners_are_all_preserved(self):
        p = n.NativeCPlan({})
        a = n._Array(())
        a.items = None
        owners = [n._Array(()) for _ in range(160)]
        node = target()
        for b in owners:
            p._retain_assignment(a, b, node.data['target'], node)
        self.assertEqual(a.assigned, tuple(owners))
        p._invalidate(a, node)
        self.assertTrue(all((b.items is None for b in owners)))

    def test_receiver_index_rhs_order_matches_runtime(self):
        for style in ('index', 'member'):
            with self.subTest(style=style):
                target_source = '取容[取位]' if style == 'index' else '取容 其 位 (取位)'
                source = "袋 取 [0]. 乙 取 [1]. 算 取容: 显 'R'. 得 袋. 法 算 取位: 显 'I'. 得 0. 法 算 取值: 显 'V'. 得 乙. 法 " + target_source + ' 取 取值.'
                tree = parse(source)
                modules = load_module_graph(PATH, tree)
                output = io.StringIO()
                Interpreter(stdout=output).execute(tree, source_path=PATH, modules=modules)
                trace = []

                class ObservedPlan(n.NativeCPlan):

                    def _invoke(self, function, args, node):
                        if isinstance(function, n._Function) and function.node.data.get('name') in ('取容', '取位', '取值'):
                            trace.append(function.node.data['name'])
                        return super()._invoke(function, args, node)
                ObservedPlan(modules)
                self.assertEqual(trace, ['取容', '取位', '取值'])
                self.assertEqual(output.getvalue().split(), ['R', 'I', 'V'])

    def test_assignment_edge_versions_dependencies_and_reachability(self):
        p = n.NativeCPlan(load_module_graph(PATH, parse('A 取 0.')))
        node = parse('A[0] 取 1.')[0]
        assignment_target = node.data['target']
        a = n._Array(())
        b = n._Array((n._Type('i32'),))
        c = n._Array((n._Type('f64'),))
        p._invalidate(a, node)
        frame = n._SummaryFrame()
        p._summary_frames.append(frame)
        try:
            p._observe_value(a)
            old = a._version
            p._retain_assignment(a, b, assignment_target, node)
            first = a._version
            p._retain_assignment(a, b, assignment_target, node)
            repeat = a._version
            p._retain_assignment(a, c, assignment_target, node)
            second = a._version
            self.assertGreater(first, old)
            self.assertEqual(repeat, first)
            self.assertGreater(second, first)
            self.assertEqual(frame.dependencies[a], old)
        finally:
            p._summary_frames.pop()
        frame = n._SummaryFrame()
        p._summary_frames.append(frame)
        try:
            p._observe_value(a)
            self.assertIn(b, frame.dependencies)
            self.assertIn(c, frame.dependencies)
        finally:
            p._summary_frames.pop()
        env = p._module_values[PATH].env
        env.put('probe', a)
        before = p._state()
        d = n._Array(())
        p._retain_assignment(a, d, assignment_target, node)
        self.assertNotEqual(before, p._state())
        p._invalidate(a, node)
        self.assertIsNone(b.items)
        self.assertIsNone(c.items)
        self.assertIsNone(d.items)
if __name__ == '__main__':
    unittest.main()
