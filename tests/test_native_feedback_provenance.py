"""Finite allocation preserves the former feedback optimization's safety duties.

No certificate counters are required: the new heap domain handles data mutation
conservatively rather than admitting only certified scalar-array loops.
"""
import unittest
import tempfile
from pathlib import Path
from rulang import native_c as n
from rulang.native_tiered import build_native_c_plan
from rulang.frontend import parse, RuError
from rulang.modules import load_module_graph

MODULE_PATH = str((Path(tempfile.gettempdir()) / 'feedback-regression.ru').resolve())
P = "密 取 外言 '如:密'. "
F = "算 造 原: 果 取 []. 果 其 增 1. 得 果. 法 "

def analyze(source, engine=n.NativeCPlan):
    return engine(load_module_graph(MODULE_PATH, parse(P + source)))

class FeedbackProvenanceTests(unittest.TestCase):
    def test_scalar_loop_has_stable_allocation_domain(self):
        for engine in (n.NativeCPlan, build_native_c_plan):
            sizes = []
            for count in (13, 13000):
                with self.subTest(engine=engine.__name__, count=count):
                    plan = analyze(F + f'X 取 []. 循 {count} 次 X 取 造 X. 环', engine)
                    self.assertEqual(plan.signatures, ())
                    sizes.append((len(plan._array_cache), len(plan._scope_cache), plan._steps))
            self.assertEqual(sizes[0], sizes[1])

    def test_large_scalar_inputs_keep_initial_element_charges(self):
        for engine in (n.NativeCPlan, build_native_c_plan):
            for count in (129, 257, 1000):
                with self.subTest(engine=engine.__name__, count=count):
                    plan = analyze(F + 'X 取 [' + ','.join("'a'" for _ in range(count)) +
                                   ']. 循 13 次 X 取 造 X. 环', engine)
                    self.assertEqual(plan.signatures, ())
                    self.assertGreater(plan._steps, count)

    def test_external_writes_preserve_real_descriptor_alias_effects(self):
        for engine in (n.NativeCPlan, build_native_c_plan):
            for write in ('原 其 增 果.', '原[0] 取 果.', '原 其 删 0.', '原 其 增 1.'):
                with self.subTest(engine=engine.__name__, write=write):
                    function = '算 造 原: 果 取 []. 果 其 增 1. ' + write + ' 得 果. 法 '
                    # Ordinary data mutation is no longer rejected just because
                    # a scalar-feedback certificate cannot prove it pure.
                    value = analyze(function + 'X 取 []. X 其 增 0. 循 13 次 X 取 造 X. 环', engine)
                    self.assertEqual(value.signatures, ())
                    # The same write corrupts a real signature array alias.
                    with self.assertRaisesRegex(RuError, '无法静态确定'):
                        analyze(function + "A 取 [密 其 i32]. X 取 A. 循 13 次 X 取 造 X. 环 "
                                "S 取 密 其 签名 (密 其 无值) A 'cdecl'.", engine)

    def test_finite_reentry_preserves_typed_factory_independence(self):
        source = F + "算 H: X 取 []. X 取 造 X. 得 X. 法 算 参数 原: 得 [密 其 i32]. 法 " \
            "甲 取 H. 无关 取 0. 乙 取 H. A 取 参数 甲. B 取 参数 乙. A 其 增 0. " \
            "S 取 密 其 签名 (密 其 无值) B 'cdecl'."
        for engine in (n.NativeCPlan, build_native_c_plan):
            with self.subTest(engine=engine.__name__):
                self.assertEqual(analyze(source, engine).signatures,
                                 (n.NativeCSignature('无值', ('i32',)),))

    def test_owner_invalidation_is_in_structural_state_and_idempotent(self):
        plan = analyze('A 取 [密 其 i32]. Y 取 [A].')
        owner = plan._module_values[MODULE_PATH].env.values['Y']
        child = owner.items[0]
        node = parse('0.')[0]
        before = plan._state(); revision = plan._revision
        plan._invalidate(owner, node)
        self.assertIsNone(owner.items)
        self.assertIsNone(child.items)
        self.assertNotEqual(plan._state(), before)
        self.assertGreater(plan._revision, revision)
        after = plan._state(); revision = plan._revision
        plan._invalidate(owner, node)
        self.assertEqual(plan._state(), after)
        self.assertEqual(plan._revision, revision)

    def test_literal_reentry_never_restores_invalidated_contents(self):
        nodes = parse(P + 'X 取 1. Y 取 [X].')
        plan = n.NativeCPlan(load_module_graph(MODULE_PATH, nodes))
        env = plan._module_values[MODULE_PATH].env; owner = env.values['Y']
        expr = nodes[-1].data['expr']
        env.put('X', n._Type('i32'))
        self.assertIs(plan._expr(expr, env), owner)
        plan._invalidate(owner, nodes[-1])
        self.assertIsNone(owner.items)
        env.put('X', 2)
        self.assertIs(plan._expr(expr, env), owner)
        self.assertIsNone(owner.items)
        # New mutable aliases discovered after invalidation must still be kept
        # and invalidated, not hidden by an old scalar-only classification.
        child = n._Array((n._Type('f64'),))
        env.put('X', child)
        version = owner._version
        self.assertIs(plan._expr(expr, env), owner)
        self.assertGreater(owner._version, version)
        self.assertIsNone(child.items)
        self.assertIn(child, n._alternatives(owner.reachable[0]))
        before = owner._version
        plan._invalidate(owner, nodes[-1])
        plan._invalidate(owner, nodes[-1])
        self.assertEqual(owner._version, before)

if __name__ == '__main__':
    unittest.main()
