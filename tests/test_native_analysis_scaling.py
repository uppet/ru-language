"""Memoization must reduce real work without changing static native semantics."""
from collections import Counter
from contextlib import ExitStack
import unittest
from unittest.mock import patch

from rulang import native_c
from rulang.frontend import RuError, parse
from rulang.modules import load_module_graph
from rulang.native_c import NativeCPlan, NativeCSignature


PREFIX = "密 取 外言 '如:密'.\n"
PATH = '/tmp/native_analysis_scaling.ru'


class CountingPlan(NativeCPlan):
    def __init__(self, *args, **kwargs):
        self.body_visits = Counter()
        super().__init__(*args, **kwargs)

    def _expr_body(self, node, env, reference=False):
        self.body_visits[node.kind] += 1
        return super()._expr_body(node, env, reference)


def analyze(source, *, expression_limit=None, dependency_limit=None,
            literal_limit=None, legacy_calls=False):
    with ExitStack() as stack:
        if expression_limit is not None:
            stack.enter_context(patch.object(native_c, 'MAX_EXPRESSION_SUMMARIES', expression_limit))
        if dependency_limit is not None:
            stack.enter_context(patch.object(native_c, 'MAX_EXPRESSION_DEPENDENCIES', dependency_limit))
        if literal_limit is not None:
            stack.enter_context(patch.object(native_c, 'MAX_LITERAL_ARRAYS', literal_limit))
        if legacy_calls:
            # The prior strategy cached a body only after an evaluation with
            # no revision change. Disable both optimizations for that oracle.
            stack.enter_context(patch.object(native_c._SummaryFrame, 'replay_stable', return_value=False))
        return CountingPlan(load_module_graph(PATH, parse(source)))


def outcome(value):
    return value.signatures, value.callback_signatures, value.emit_c()


def failure(error):
    return (error.category, error.message, error.source_name,
            error.line, error.col, error.source_text)


class NativeAnalysisScalingTests(unittest.TestCase):
    def assert_equivalent(self, source, expected=None, error=None):
        outcomes = []
        for mode, options in (
                ('memoized', {}),
                ('without_expression_caches', {'expression_limit': 0, 'literal_limit': 0}),
                ('legacy_body_summaries', {'expression_limit': 0, 'literal_limit': 0,
                                           'legacy_calls': True})):
            with self.subTest(mode=mode):
                try:
                    value = analyze(PREFIX + source, **options)
                except RuError as caught:
                    outcomes.append(('error', failure(caught)))
                    self.assertIsNotNone(error, caught.message)
                    self.assertIn(error, caught.message)
                    self.assertEqual(caught.category, '原生编译错误')
                else:
                    outcomes.append(('success', outcome(value)))
                    self.assertIsNone(error)
                    self.assertEqual(set(value.signatures), expected)
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[0], outcomes[2])

    def test_aliases_named_arguments_and_callback_output_match_uncached_analysis(self):
        self.assert_equivalent("""
            别名 取 密. 型 取 别名 其 i32. 参数 取 [型, 别名 其 f64].
            算 造 类型 参数们:
                得 别名 其 签名 约定:'cdecl' 参数:参数们 返回:类型.
            法
            F 取 算 造. G 取 F.
            循 3 次
                S 取 G 型 参数.
                局部 取 ((1 + 2) * (3 + 4)).
            环
            算 回 甲 乙: 得 0. 法
            C 取 密 其 回调 S (算 回) 0.
        """, {NativeCSignature('i32', ('i32', 'f64'))})

    def test_late_missing_binding_and_local_shadow_match_uncached_analysis(self):
        self.assert_equivalent("""
            型 取 密 其 i32.
            算 外:
                算 首: 得 型. 法
                首. 首.
                型 取 密 其 f64.
                得 密 其 签名 (首) ([]) 'cdecl'.
            法
            外.
            循 2 次
                段:
                    S 取 密 其 签名 型 ([]) 'cdecl'.
                    型 取 密 其 f64.
                落.
                型 取 密 其 u8.
            环
        """, {NativeCSignature(name, ()) for name in ('i32', 'f64', 'u8')})

    def test_first_call_nested_private_read_before_bind_is_not_replayed(self):
        # The leaf's first return contains only the global type. Its own bind
        # changes a future fresh invocation's conservative local/ancestor join.
        # That read-before-write evidence must survive propagation to the root.
        self.assert_equivalent("""
            型 取 密 其 i32.
            算 叶: 旧 取 型. 型 取 密 其 f64. 得 旧. 法
            算 枝: 得 叶. 法
            枝.
            S 取 密 其 签名 (枝) ([]) 'cdecl'.
        """, {NativeCSignature('i32', ()), NativeCSignature('f64', ())})

    def test_capture_read_before_write_and_unknown_escape_match_uncached_analysis(self):
        self.assert_equivalent("""
            算 外:
                型 取 密 其 i32.
                算 读后改: 旧 取 型. 型 取 密 其 f64. 得 旧. 法
                算 改: 型 取 密 其 u8. 得 空. 法
                读后改. 读后改. 读后改.
                未知 (算 改).
                得 密 其 签名 (读后改) ([]) 'cdecl'.
            法 外.
        """, {NativeCSignature(name, ()) for name in ('i32', 'f64', 'u8')})

    def test_callback_late_capture_changes_match_uncached_analysis(self):
        self.assert_equivalent("""
            算 外:
                型 取 密 其 i32.
                算 回 值: S 取 密 其 签名 型 ([]) 'cdecl'. 得 0. 法
                循 3 次 回 (1 + 2). 环
                签 取 密 其 签名 (密 其 i32) ([密 其 i32]) 'cdecl'.
                C 取 密 其 回调 签 (算 回) 0.
                型 取 密 其 f64. 得 C.
            法 外.
        """, {NativeCSignature('i32', ()), NativeCSignature('f64', ()),
              NativeCSignature('i32', ('i32',))})

    def test_array_alias_mutations_preserve_errors_and_locations(self):
        for mutation in ('别名[0] 取 密 其 f64.', '别名 其 增 (密 其 f64).'):
            with self.subTest(mutation=mutation):
                self.assert_equivalent("""
                    参数 取 [密 其 i32]. 包 取 [参数]. 别名 取 包[0].
                    算 首: 得 包[0][0]. 法
                    循 3 次 首(). 环
                """ + mutation + "S 取 密 其 签名 (首) ([]) 'cdecl'.",
                    error='无法静态确定')

    def test_opaque_alias_growing_reachability_preserves_error(self):
        self.assert_equivalent("""
            算 外:
                甲 取 [密 其 i32]. 乙 取 [密 其 f64]. 当前 取 甲.
                算 包: 得 当前 对 0. 法
                算 触碰 值: 未知 值. 得 空. 法
                袋 取 包. 触碰 袋. 触碰 袋. 触碰 袋.
                当前 取 乙. 包. 触碰 袋.
                得 密 其 签名 (密 其 i32) 乙 'cdecl'.
            法 外.
        """, error='无法静态确定')

    def test_recursion_acceptance_and_rejection_match_uncached_analysis(self):
        self.assert_equivalent("""
            S 取 密 其 签名 (密 其 i32) ([]) 'cdecl'.
            算 阶乘 数量:
                若 数量 <= 1 则 得 1. 然
                得 数量 * (阶乘 (数量 - 1)).
            法
            循 3 次 阶乘 (3 + 3). 环
        """, {NativeCSignature('i32', ())})
        self.assert_equivalent("""
            算 递归 型:
                S 取 密 其 签名 型 ([]) 'cdecl'.
                得 递归 型.
            法
            递归 (密 其 i32).
        """, error='无法证明此递归路径')

    def test_first_call_safe_local_initialization_reuses_function_summary(self):
        source = '算 加一 值: 局部 取 值 + 1. 得 局部. 法 加一 7. 加一 7.'
        value = analyze(source, expression_limit=0)
        legacy = analyze(source, expression_limit=0, legacy_calls=True)
        self.assertEqual(outcome(value), outcome(legacy))
        self.assertEqual(value._function_evaluations, 1)
        self.assertEqual(legacy._function_evaluations, 2)
        self.assertEqual(value._summary_hits, 1)

    def test_stable_loop_refines_only_its_transient_private_reads(self):
        source = '型 取 1. 算 F: 循 2 次 旧 取 型. 型 取 2. 环 得 旧. 法 F. F.'
        value = analyze(source, expression_limit=0, literal_limit=0)
        legacy = analyze(source, expression_limit=0, literal_limit=0, legacy_calls=True)
        self.assertEqual(outcome(value), outcome(legacy))
        self.assertEqual(value._function_evaluations, 1)
        self.assertEqual(legacy._function_evaluations, 2)
        self.assertEqual(value._summary_hits, 1)

    def test_loop_refinement_does_not_erase_a_read_before_the_loop(self):
        self.assert_equivalent("""
            型 取 密 其 i32.
            算 F:
                旧 取 型.
                循 2 次 型 取 密 其 f64. 环
                得 旧.
            法
            F.
            S 取 密 其 签名 (F) ([]) 'cdecl'.
        """, {NativeCSignature('i32', ()), NativeCSignature('f64', ())})

    def test_loop_with_different_early_return_does_not_prove_first_call_replay(self):
        class RecordingReturns(CountingPlan):
            def __init__(self, *args, **kwargs):
                self.root_calls = []
                super().__init__(*args, **kwargs)

            def _invoke(self, function, args, node):
                result = super()._invoke(function, args, node)
                if isinstance(function, native_c._Function) and function.node.data.get('name') == 'F':
                    key = (self._context_key(function), ())
                    self.root_calls.append((result, key in self._call_summaries))
                return result

        source = PREFIX + """
            型 取 密 其 i32.
            算 造 值: 得 [1]. 法
            算 F:
                循 2 次
                    得 造 型.
                    型 取 密 其 f64.
                环
            法
            F. F.
        """
        values = []
        for limit in (0, native_c.MAX_EXPRESSION_SUMMARIES):
            with self.subTest(expression_limit=limit), patch.object(native_c, 'MAX_EXPRESSION_SUMMARIES', limit):
                value = RecordingReturns(load_module_graph(PATH, parse(source)))
                self.assertEqual(len(value.root_calls), 2)
                first, first_cached = value.root_calls[0]
                last, last_cached = value.root_calls[1]
                self.assertIsInstance(first, native_c._Choice)
                self.assertEqual(len(first.values), 2)
                self.assertTrue(all(isinstance(item, native_c._Array) for item in first.values))
                self.assertIsInstance(last, native_c._Array)
                self.assertFalse(first_cached)
                self.assertTrue(last_cached)
                values.append(value)
        self.assertEqual(outcome(values[0]), outcome(values[1]))

    def test_loop_return_alias_mutation_preserves_error_and_location(self):
        self.assert_equivalent("""
            参数 取 [密 其 i32].
            算 F:
                循 2 次
                    得 参数[0].
                    参数 其 增 (密 其 f64).
                环
            法
            F.
            S 取 密 其 签名 (F) ([]) 'cdecl'.
        """, error='无法静态确定')

    def test_loop_return_proof_does_not_preempt_a_later_native_error(self):
        returns = ''.join(f"得 '值{index}'.\n" for index in range(129))
        invalid_type = "S 取 __密 其 类型 '不支持'."
        source = PREFIX + '算 F:\n循 1 次\n' + returns + '环\n' + invalid_type + '\n法\nF.'
        errors = []
        for proof_enabled in (True, False):
            with self.subTest(proof_enabled=proof_enabled), ExitStack() as stack:
                options = {}
                if not proof_enabled:
                    stack.enter_context(patch.object(native_c, '_same_returns', return_value=False))
                    options = {'expression_limit': 0, 'literal_limit': 0, 'legacy_calls': True}
                with self.assertRaisesRegex(RuError, '无法静态确定原生类型') as caught:
                    analyze(source, **options)
                error = caught.exception
                self.assertEqual(error.source_name, PATH)
                self.assertEqual(error.line, source.splitlines().index(invalid_type) + 1)
                self.assertEqual(error.col, invalid_type.index('其') + 1)
                errors.append(failure(error))
        self.assertEqual(errors[0], errors[1])

    def test_loop_return_proof_preserves_normal_final_return_alternative_limit(self):
        returns = ''.join(f"得 '值{index}'.\n" for index in range(129))
        source = PREFIX + '算 F:\n循 1 次\n' + returns + '环\n法\nF.'
        errors = []
        for proof_enabled in (True, False):
            with self.subTest(proof_enabled=proof_enabled), ExitStack() as stack:
                options = {}
                if not proof_enabled:
                    stack.enter_context(patch.object(native_c, '_same_returns', return_value=False))
                    options = {'expression_limit': 0, 'literal_limit': 0, 'legacy_calls': True}
                with self.assertRaisesRegex(RuError, '候选值超过 128 上限') as caught:
                    analyze(source, **options)
                self.assertEqual(caught.exception.category, '原生编译错误')
                # The ordinary return-join error has no attached source text;
                # preserve all of its existing metadata, not just its message.
                errors.append(vars(caught.exception))
        self.assertEqual(errors[0], errors[1])

    def test_compound_expression_hits_survive_unrelated_binding_writes(self):
        value = CountingPlan({PATH: []})
        env = value._module_values[PATH].env
        env.put('参数', native_c._Array((native_c._Type('i32'), native_c._Type('f64'))))
        env.put('位置', 0)
        expr = parse('显 参数[位置].')[0].data['expr']
        self.assertEqual(value._expr(expr, env), native_c._Type('i32'))
        visits = sum(value.body_visits.values())
        env.put('无关', 1)
        self.assertEqual(value._expr(expr, env), native_c._Type('i32'))
        self.assertEqual(sum(value.body_visits.values()), visits)
        self.assertGreater(value._expression_hits, 0)
        env.put('位置', 1)
        self.assertEqual(value._expr(expr, env), native_c._Type('f64'))
        self.assertGreater(sum(value.body_visits.values()), visits)

    def test_absent_local_binding_is_an_expression_dependency(self):
        value = CountingPlan({PATH: []})
        outer = value._module_values[PATH].env
        outer.put('位置', 0)
        outer.put('参数', native_c._Array(tuple(native_c._Type(t) for t in ('i32', 'f64', 'u8'))))
        local = value._environment(outer, 'block')
        expr = parse('显 参数[位置].')[0].data['expr']
        self.assertEqual(value._expr(expr, local), native_c._Type('i32'))
        self.assertEqual(value._expr(expr, local), native_c._Type('i32'))
        self.assertGreater(value._expression_hits, 0)
        local.put('位置', 1)
        self.assertEqual(set(native_c._alternatives(value._expr(expr, local))),
                         {native_c._Type('i32'), native_c._Type('f64')})
        outer.put('位置', 2)
        self.assertEqual(set(native_c._alternatives(value._expr(expr, local))),
                         {native_c._Type('f64'), native_c._Type('u8')})

    def test_cached_expression_keeps_transitive_recursion_footprint(self):
        value = analyze(PREFIX + """
            算 叶 甲 乙: 得 密 其 i32. 法
            算 枝 甲 乙: 得 叶 甲 乙. 法
            循 3 次 枝 (1 + 2) (3 + 4). 环
        """)
        env = value._module_values[PATH].env
        loop = next(node for node in value.modules[PATH] if node.kind == 'loop')
        expr = loop.data['body'][0].data['expr']
        value._expr(expr, env)
        self.assertIn((id(expr), id(env), False), value._expression_summaries)
        leaf = next(fn for fn in value._functions if fn.node.data.get('name') == '叶')
        value._active.add(id(leaf.node))
        try:
            with self.assertRaisesRegex(RuError, '无法证明此递归路径'):
                value._expr(expr, env)
        finally:
            value._active.remove(id(leaf.node))

    def test_expression_reference_mode_is_not_an_implicit_call_cache_hit(self):
        value = analyze('算 F: 得 [1, 2]. 法')
        env = value._module_values[PATH].env
        env.put('M', native_c._Module(env))
        expr = parse('显 M 其 F.')[0].data['expr']
        result = value._expr(expr, env)
        self.assertIsInstance(result, native_c._Array)
        self.assertIn((id(expr), id(env), False), value._expression_summaries)
        reference = value._expr(expr, env, reference=True)
        self.assertIsInstance(reference, native_c._Function)
        self.assertIn((id(expr), id(env), True), value._expression_summaries)
        visits = sum(value.body_visits.values())
        self.assertIs(value._expr(expr, env), result)
        self.assertIs(value._expr(expr, env, reference=True), reference)
        self.assertEqual(sum(value.body_visits.values()), visits)

    def test_expression_recursion_footprint_overflow_is_not_truncated(self):
        source = PREFIX + """
            算 叶 值: 得 密 其 i32. 法
            算 枝 值: 得 叶 值. 法
            算 树 值: 得 枝 值. 法
            循 3 次 树 (1 + 2). 环
            S 取 密 其 签名 (树 0) ([]) 'cdecl'.
        """
        expected = analyze(source, expression_limit=0, literal_limit=0, legacy_calls=True)
        with patch.object(native_c, 'MAX_SUMMARY_FUNCTIONS', 2):
            bounded = analyze(source)
        self.assertEqual(outcome(bounded), outcome(expected))
        self.assertTrue(all(len(entry[2]) <= 2
                            for entry in bounded._expression_summaries.values()))
        root = next(fn for fn in bounded._functions if fn.node.data.get('name') == '树')
        self.assertTrue(all(id(root.node) not in entry[2]
                            for entry in bounded._expression_summaries.values()))

    @staticmethod
    def scale_source(width=64):
        # Descriptor propagation forces several fixed-point passes. Independent
        # compound scalar expressions should not be revisited just because
        # other bindings in the same scope are still being joined.
        source = PREFIX + "甲 取 7. 乙 取 11. 型0 取 密 其 i32.\n"
        source += ''.join(f'型{i} 取 密 其 f64.\n' for i in range(1, 10))
        source += '循 20 次\n'
        for index in range(width):
            source += f'局{index} 取 ((甲 + {index}) * (乙 + 2)) + ((甲 - 3) / (乙 + 4)).\n'
        source += "S 取 密 其 签名 型9 ([]) 'cdecl'.\n"
        source += ''.join(f'型{i} 取 型{i - 1}.\n' for i in reversed(range(1, 10)))
        return source + '环'

    def test_synthetic_scale_reduces_actual_expression_visits(self):
        source = self.scale_source()
        cached = analyze(source)
        uncached = analyze(source, expression_limit=0)
        self.assertEqual(outcome(cached), outcome(uncached))
        self.assertEqual(set(cached.signatures),
                         {NativeCSignature('i32', ()), NativeCSignature('f64', ())})
        self.assertGreater(cached._expression_hits, 0)
        self.assertEqual(uncached._expression_hits, 0)
        self.assertFalse(uncached._expression_summaries)
        self.assertLess(sum(cached.body_visits.values()) * 2, sum(uncached.body_visits.values()))
        self.assertLess(cached.body_visits['binary'], uncached.body_visits['binary'])
        self.assertLess(cached._steps, uncached._steps)

    def test_expression_cache_eviction_is_bounded_and_semantics_preserving(self):
        source = self.scale_source(width=12)
        expected = analyze(source, expression_limit=0)
        unlimited = analyze(source)
        for limit in (1, 3, 8):
            with self.subTest(limit=limit):
                bounded = analyze(source, expression_limit=limit)
                self.assertLessEqual(len(bounded._expression_summaries), limit)
                self.assertGreater(len(unlimited._expression_summaries), limit)
                self.assertEqual(outcome(bounded), outcome(expected))
                self.assertGreater(sum(bounded.body_visits.values()), sum(unlimited.body_visits.values()))

    def test_expression_dependency_overflow_falls_back_without_truncation(self):
        source = self.scale_source(width=8)
        expected = analyze(source, expression_limit=0)
        for limit in (0, 1, 2):
            with self.subTest(limit=limit):
                bounded = analyze(source, dependency_limit=limit)
                self.assertEqual(outcome(bounded), outcome(expected))
                self.assertTrue(all(len(entry[0]) <= limit
                                    for entry in bounded._expression_summaries.values()))
        mutation = PREFIX + """
            参数 取 [密 其 i32]. 包 取 [参数].
            算 首: 得 包[0][0]. 法
            循 3 次 首(). 环
            参数[0] 取 密 其 f64.
            S 取 密 其 签名 (首) ([]) 'cdecl'.
        """
        errors = []
        for options in ({'expression_limit': 0}, {'dependency_limit': 1}):
            with self.assertRaises(RuError) as caught:
                analyze(mutation, **options)
            errors.append(failure(caught.exception))
        self.assertEqual(errors[0], errors[1])

    def test_literal_array_contexts_keep_distinct_mutable_owners(self):
        source = PREFIX + """
            S 取 密 其 签名 (密 其 i32) ([]) 'cdecl'.
            算 造 标记: 得 [1, 真, '字', 空]. 法
            甲 取 造 0. 乙 取 造 1.
            未知 甲.
            丙 取 造 0.
        """
        cached = analyze(source)
        uncached = analyze(source, expression_limit=0, literal_limit=0, legacy_calls=True)
        self.assertEqual(outcome(cached), outcome(uncached))
        self.assertGreater(cached._literal_array_hits, 0)
        self.assertFalse(uncached._literal_array_items)
        self.assertEqual(uncached._literal_array_hits, 0)
        self.assertLess(cached.body_visits['string'], uncached.body_visits['string'])
        for value in (cached, uncached):
            bindings = value._module_values[PATH].env.values
            first, second, again = (bindings[name] for name in ('甲', '乙', '丙'))
            self.assertIsInstance(first, native_c._Array)
            self.assertIsInstance(second, native_c._Array)
            self.assertIsNot(first, second)
            self.assertIs(first, again)
            self.assertIsNone(first.items)
            self.assertEqual(second.items, (1, True, '字', None))

    def test_nested_literal_arrays_do_not_share_inner_mutable_owners(self):
        source = """
            算 造 标记: 得 [[1, 2]]. 法
            甲 取 造 0. 乙 取 造 1.
            未知 (甲[0]).
        """
        cached = analyze(source)
        uncached = analyze(source, expression_limit=0, literal_limit=0, legacy_calls=True)
        self.assertEqual(outcome(cached), outcome(uncached))
        self.assertGreater(cached._literal_array_hits, 0)
        for value in (cached, uncached):
            bindings = value._module_values[PATH].env.values
            first, second = bindings['甲'], bindings['乙']
            self.assertIsNot(first, second)
            self.assertIsNot(first.items[0], second.items[0])
            self.assertIsNone(first.items[0].items)
            self.assertEqual(second.items[0].items, (1, 2))
            function = next(fn for fn in value._functions if fn.node.data.get('name') == '造')
            outer_array = function.node.data['body'][0].data['expr']
            self.assertNotIn(id(outer_array), value._literal_array_items)

    def test_nonliteral_array_items_are_evaluated_for_each_context(self):
        source = """
            算 参数列 型: 得 [型]. 法
            甲 取 参数列 (密 其 i32). 乙 取 参数列 (密 其 f64).
            S 取 密 其 签名 (密 其 无值) 甲 'cdecl'.
            T 取 密 其 签名 (密 其 无值) 乙 'cdecl'.
        """
        self.assert_equivalent(source, {NativeCSignature('无值', ('i32',)),
                                        NativeCSignature('无值', ('f64',))})
        value = analyze(PREFIX + source)
        function = next(fn for fn in value._functions if fn.node.data.get('name') == '参数列')
        array = function.node.data['body'][0].data['expr']
        self.assertNotIn(id(array), value._literal_array_items)

    def test_literal_array_cache_eviction_is_bounded(self):
        source = PREFIX + "S 取 密 其 签名 (密 其 i32) ([]) 'cdecl'.\n"
        for index in range(8):
            source += f'算 造{index} 标记: 得 [{index}, 真]. 法\n'
        for context in range(3):
            source += ''.join(f'造{index} {context}.\n' for index in range(8))
        expected = analyze(source, expression_limit=0, literal_limit=0)
        cached = analyze(source)
        self.assertGreater(cached._literal_array_hits, 0)
        for limit in (1, 3):
            with self.subTest(limit=limit):
                bounded = analyze(source, literal_limit=limit)
                self.assertLessEqual(len(bounded._literal_array_items), limit)
                self.assertGreater(len(cached._literal_array_items), limit)
                self.assertEqual(outcome(bounded), outcome(expected))
                self.assertGreater(bounded.body_visits['fact'], cached.body_visits['fact'])

    def test_first_literal_array_evaluation_charges_every_item(self):
        # A literal-content cache may only remove repeat work, not exempt a
        # first, oversized data table from the normal expression budget.
        statement = parse('显 [1].')[0]
        array = statement.data['expr']
        item = array.data['items'][0]
        array.data['items'] = [item] * 199999
        valid = CountingPlan({PATH: [statement]})
        self.assertEqual(valid._steps, 200000)
        self.assertEqual(valid.body_visits['number'], 199999)
        array.data['items'] = [item] * 200000
        invalid = CountingPlan.__new__(CountingPlan)
        with self.assertRaisesRegex(RuError, '超过复杂度上限'):
            invalid.__init__({PATH: [statement]})
        self.assertEqual(invalid._steps, 200001)
        self.assertEqual(invalid.body_visits['number'], 199999)
        self.assertFalse(invalid._literal_array_items)

    def test_repeated_leaf_expressions_preserve_exact_200000_step_guard(self):
        # Reuse one AST node deliberately: memoization cannot turn the work
        # limit into a count of distinct syntax nodes or unique cache entries.
        statement = parse('显 1.')[0]
        errors = []
        self.assertEqual(native_c.MAX_ANALYSIS_STEPS, 200000)
        for limit in (0, native_c.MAX_EXPRESSION_SUMMARIES):
            with self.subTest(limit=limit), patch.object(native_c, 'MAX_EXPRESSION_SUMMARIES', limit):
                valid = CountingPlan({PATH: [statement] * 200000})
                self.assertEqual(valid._steps, 200000)
                self.assertEqual(valid.body_visits['number'], 200000)
                invalid = CountingPlan.__new__(CountingPlan)
                with self.assertRaisesRegex(RuError, '超过复杂度上限') as caught:
                    invalid.__init__({PATH: [statement] * 200001})
                self.assertEqual(invalid._steps, 200001)
                self.assertEqual(invalid.body_visits['number'], 200000)
                errors.append(failure(caught.exception))
        self.assertEqual(errors[0], errors[1])


if __name__ == '__main__':
    unittest.main()
