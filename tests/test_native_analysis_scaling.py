"""Memoization must reduce real work without changing static native semantics."""
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rulang import native_c
from rulang.frontend import RuError, parse
from rulang.modules import load_module_graph
from rulang.native_c import NativeCPlan, NativeCSignature


PREFIX = "密 取 外言 '如:密'.\n"
# Match the loader's canonical module identity on every platform.
PATH = str((Path(tempfile.gettempdir()) / 'native_analysis_scaling.ru').resolve())


class CountingPlan(NativeCPlan):
    def __init__(self, *args, **kwargs):
        self.body_visits = Counter()
        self.statement_visits = 0
        self.largest_return_list = 0
        super().__init__(*args, **kwargs)

    def _block(self, *args, **kwargs):
        result = super()._block(*args, **kwargs)
        self.largest_return_list = max(self.largest_return_list, len(result))
        return result

    def _block_body(self, body, env):
        self.statement_visits += len(body)
        return super()._block_body(body, env)

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
        # Every runtime invocation has fresh locals; its later local bind
        # cannot retroactively change an earlier module read. Captured-cell
        # read-before-write is separately required to retain both types.
        source = ("""
            型 取 密 其 i32.
            算 叶: 旧 取 型. 型 取 密 其 f64. 得 旧. 法
            算 枝: 得 叶. 法
            枝.
            S 取 密 其 签名 (枝) ([]) 'cdecl'.
        """)
        self.assert_equivalent(source, {NativeCSignature('i32', ())})
        # The same source nested in a function captures a live cell; its
        # later write MUST remain visible, unlike a fresh module shadow.
        self.assert_equivalent('算 容: ' + source + ' 得 空. 法 容.',
                               {NativeCSignature('i32', ()), NativeCSignature('f64', ())})


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

    def test_fresh_pair_is_independent_but_rebound_pair_keeps_alias_effect(self):
        source = """
            算 外:
                甲 取 [密 其 i32]. 乙 取 [密 其 f64]. 当前 取 甲.
                算 包: 得 当前 对 0. 法
                算 触碰 值: 未知 值. 得 空. 法
                袋 取 包. 触碰 袋. 触碰 袋. 触碰 袋.
                当前 取 乙. 包. 触碰 袋.
                得 密 其 签名 (密 其 i32) 乙 'cdecl'.
            法 外.
        """
        self.assert_equivalent(source, {NativeCSignature('i32', ('f64',))})
        self.assert_equivalent(source.replace('当前 取 乙. 包.', '当前 取 乙. 袋 取 包.'),
                               error='无法静态确定')


    def test_invalid_array_reinitialization_keeps_new_initializer_aliases(self):
        for effect in ('果 其 增 0.', '果[0] 取 0.', '未知 果.'):
            with self.subTest(effect=effect):
                self.assert_equivalent("""
                    旧阵 取 [密 其 i32]. 新阵 取 [密 其 f64]. 当前 取 旧阵.
                    算 包裹 参数: 果 取 [当前].
                """ + effect + """
                        得 果.
                    法
                    包裹 0. 当前 取 新阵. 包裹 0.
                    签 取 密 其 签名 (密 其 i32) 新阵 'cdecl'.
                """, error='无法静态确定')

    def test_invalid_array_reinitialization_keeps_opaque_callback_effects(self):
        self.assert_equivalent("""
            旧阵 取 [密 其 i32]. 新阵 取 [密 其 f64]. 当前 取 旧阵.
            作 改 盒: 盒[0][0] 取 'bad'. 为
            回们 取 [算 改]. 片 取 回们[:].
            算 包裹 参数: 果 取 [当前]. 调 取 片[0]. 调 果. 得 果. 法
            包裹 0. 当前 取 新阵. 包裹 0.
            签 取 密 其 签名 (密 其 i32) 新阵 'cdecl'.
        """, error='无法静态确定')

    def test_invalid_array_retains_late_opaque_children_through_projections(self):
        for effect in ('未知 壳.', '未知 壳[0].', '未知 (壳 其 位 0).',
                       '未知 壳[:].', '未知 (壳 其 段 0 1).',
                       '壳[0] 其 量.', '壳[0] 其 含 0.'):
            with self.subTest(effect=effect):
                source = """
                    算 外:
                        甲 取 [密 其 i32]. 乙 取 [密 其 f64]. 当前 取 甲.
                        算 袋: 得 当前 对 0. 法
                        袋值 取 袋. 壳 取 [袋值]. 未知 壳.
                        当前 取 乙. 袋.
                """ + effect + """
                        得 密 其 签名 (密 其 i32) 乙 'cdecl'.
                    法 外.
                """
                self.assert_equivalent(source, {NativeCSignature('i32', ('f64',))})
                # This time the new child really enters the already-invalid
                # old owner; every projection/cache path must invalidate beta.
                self.assert_equivalent(source.replace('当前 取 乙. 袋.',
                    '当前 取 乙. 壳[0] 取 袋.'), error='无法静态确定')


    def test_invalid_array_reachability_invalidates_call_and_loop_summaries(self):
        for body in ('未知 值.', '循 2 次 未知 值. 环'):
            with self.subTest(body=body):
                source = """
                    算 外:
                        甲 取 [密 其 i32]. 乙 取 [密 其 f64]. 当前 取 甲.
                        算 袋: 得 当前 对 0. 法
                        算 触碰 值:
                """ + body + """
                            得 空.
                        法
                        袋值 取 袋. 壳 取 [袋值].
                        触碰 壳. 触碰 壳. 触碰 壳.
                        当前 取 乙. 袋. 触碰 壳.
                        得 密 其 签名 (密 其 i32) 乙 'cdecl'.
                    法 外.
                """
                self.assert_equivalent(source, {NativeCSignature('i32', ('f64',))})
                # This time the new child really enters the already-invalid
                # old owner; every projection/cache path must invalidate beta.
                self.assert_equivalent(source.replace('当前 取 乙. 袋.',
                    '当前 取 乙. 壳[0] 取 袋.'), error='无法静态确定')


    def test_retained_callback_cycle_uses_existing_native_recursion_guard(self):
        # The unknown operation may invoke the callback again. Discarding the
        # invalid array's children used to hide this unproved recursive edge.
        self.assert_equivalent("""
            算 外:
                算 内: 未知 包. 得 0. 法
                包 取 [算 内]. 未知 包. 得 0.
            法 外.
            签 取 密 其 签名 (密 其 i32) ([]) 'cdecl'.
        """, error='无法证明此递归路径与原生描述符无关')

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
        source = ("""
            型 取 密 其 i32.
            算 F:
                旧 取 型.
                循 2 次 型 取 密 其 f64. 环
                得 旧.
            法
            F.
            S 取 密 其 签名 (F) ([]) 'cdecl'.
        """)
        self.assert_equivalent(source, {NativeCSignature('i32', ())})
        # The same source nested in a function captures a live cell; its
        # later write MUST remain visible, unlike a fresh module shadow.
        self.assert_equivalent('算 容: ' + source + ' 得 空. 法 容.',
                               {NativeCSignature('i32', ()), NativeCSignature('f64', ())})


    def test_captured_type_write_does_not_prove_first_call_replay(self):
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
            算 外:
            型 取 密 其 i32.
            算 F:
                循 2 次
                    得 型.
                    型 取 密 其 f64.
                环
            法
            F. F. 得 空. 法 外.
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
                self.assertEqual({item.name for item in first.values}, {'i32', 'f64'})
                self.assertEqual({item.name for item in native_c._alternatives(last)}, {'i32', 'f64'})
                self.assertFalse(first_cached)
                self.assertTrue(last_cached)
                values.append(value)
        self.assertEqual(outcome(values[0]), outcome(values[1]))


    def test_different_accumulated_return_cannot_refresh_final_loop_witness(self):
        source = PREFIX + """
            参数 取 [密 其 i32].
            算 F:
                循 2 次
                    得 参数[0].
                    参数 其 增 0.
                环
            法
            F.
        """
        original = native_c._same_returns
        for limit in (0, native_c.MAX_EXPRESSION_SUMMARIES):
            comparisons = []
            def compare(accumulated, final):
                result = original(accumulated, final)
                comparisons.append((tuple(accumulated), tuple(final), result))
                return result
            with self.subTest(expression_limit=limit), \
                    patch.object(native_c, 'MAX_EXPRESSION_SUMMARIES', limit), \
                    patch.object(native_c, '_same_returns', side_effect=compare):
                analyze(source)
                differences = [(earlier, final) for earlier, final, same in comparisons if not same]
                self.assertTrue(differences, 'must exercise unequal loop-return proof')
                self.assertTrue(any(
                    any(isinstance(x, native_c._Type) and x.name == 'i32'
                        for value in earlier for x in native_c._alternatives(value))
                    and all(isinstance(x, native_c._Opaque)
                            for value in final for x in native_c._alternatives(value))
                    for earlier, final in differences))
                with self.assertRaisesRegex(RuError, '无法静态确定'):
                    analyze(source + "S 取 密 其 签名 (F) ([]) 'cdecl'.")

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

    def test_loop_return_widening_preserves_all_nonstring_effects(self):
        returns = ''.join(f"得 '值{index}'.\n" for index in range(129))
        source = PREFIX + '算 F:\n循 1 次\n' + returns + '环\n法\n值 取 F.'
        results = []
        for proof_enabled in (True, False):
            with self.subTest(proof_enabled=proof_enabled), ExitStack() as stack:
                options = {}
                if not proof_enabled:
                    stack.enter_context(patch.object(native_c, '_same_returns', return_value=False))
                    options = {'expression_limit': 0, 'literal_limit': 0, 'legacy_calls': True}
                value = analyze(source, **options)
                self.assertIs(value._module_values[PATH].env.get('值'), native_c.STRING)
                results.append(outcome(value))
        self.assertEqual(results[0], results[1])


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
        # First implicit invocation may allocate its new callsite owner.
        # Warm the same context, then require real cache hits in both modes.
        self.assertIs(value._expr(expr, env), result)
        self.assertIn((id(expr), id(env), False), value._expression_summaries)
        reference = value._expr(expr, env, reference=True)
        self.assertIsInstance(reference, native_c._Function)
        self.assertIs(value._expr(expr, env, reference=True), reference)
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

    def test_nested_loop_returns_remain_bounded_by_charged_visits(self):
        for depth in (4, 8, 12, 16, 20):
            with self.subTest(depth=depth):
                body = '得 1.'
                for index in range(depth):
                    body = '循 2 次 ' + body + f' 局{index} 取 1. 环 '
                source = '算 F: ' + body + ' 法 F.'
                cached = analyze(source)
                uncached = analyze(source, expression_limit=0)
                self.assertEqual(outcome(cached), outcome(uncached))
                self.assertEqual(cached.largest_return_list, uncached.largest_return_list)
                self.assertLessEqual(cached.largest_return_list, depth + 1)
                self.assertLessEqual(cached.largest_return_list, cached._steps)
                self.assertTrue(all(len(entry[1]) <= 1 for key, entry in
                                    cached._expression_summaries.items() if key[0] == 'block'))

    def test_multiple_returns_are_not_merged_or_cached_as_a_block(self):
        value = analyze('算 F: 得 1. 得 1. 法 F.')
        function = next(fn for fn in value._functions if fn.node.data.get('name') == 'F')
        env = next(env for key, env in value._scope_cache.items()
                   if key[0][0] == id(function.node))
        self.assertNotIn(('block', id(function.node.data['body']), id(env)),
                         value._expression_summaries)

    def test_cached_statement_block_retains_active_recursion_footprint(self):
        value = analyze(PREFIX + '算 叶: 得 密 其 i32. 法 算 枝: 得 叶. 法 枝.')
        branch = next(fn for fn in value._functions if fn.node.data.get('name') == '枝')
        leaf = next(fn for fn in value._functions if fn.node.data.get('name') == '叶')
        env = next(env for key, env in value._scope_cache.items()
                   if key[0][0] == id(branch.node))
        body = branch.node.data['body']
        key = ('block', id(body), id(env))
        self.assertIn(id(leaf.node), value._expression_summaries[key][2])
        before = value._block_hits
        value._block(body, env)
        self.assertEqual(value._block_hits, before + 1)
        value._active.add(id(leaf.node))
        with self.assertRaisesRegex(RuError, '递归'):
            value._block(body, env)
        self.assertEqual(value._block_hits, before + 1)

    def test_statement_block_footprint_overflow_is_not_cached_or_truncated(self):
        source = PREFIX + ('算 甲: 得 密 其 i32. 法 算 乙: 得 密 其 f64. 法 '
                           '算 枝: 甲. 得 乙. 法 枝.')
        with patch.object(native_c, 'MAX_SUMMARY_FUNCTIONS', 1):
            value = analyze(source)
        branch = next(fn for fn in value._functions if fn.node.data.get('name') == '枝')
        env = next(env for key, env in value._scope_cache.items()
                   if key[0][0] == id(branch.node))
        self.assertNotIn(('block', id(branch.node.data['body']), id(env)),
                         value._expression_summaries)
        self.assertTrue(all(len(entry[2]) <= 1 for entry in value._expression_summaries.values()))
        self.assertEqual(outcome(value), outcome(analyze(source, expression_limit=0)))

    def test_statement_chunk_boundaries_preserve_first_reads_and_returns(self):
        for width in (0, 1, 2, 3, 4, 5):
            with self.subTest(padding=width):
                padding = '垫 取 0. ' * width
                source = ('型 取 密 其 i32. 算 外: 旧 取 型. ' + padding +
                    "型 取 密 其 f64. 得 旧. 法 外. S 取 密 其 签名 (外) ([]) 'cdecl'.")
                self.assert_equivalent(source, {NativeCSignature('i32', ())})
                # The same source nested in a function captures a live cell; its
                # later write MUST remain visible, unlike a fresh module shadow.
                self.assert_equivalent('算 容: ' + source + ' 得 空. 法 容.',
                                       {NativeCSignature('i32', ()), NativeCSignature('f64', ())})


    def test_statement_chunks_reuse_work_when_function_dependencies_overflow(self):
        source = PREFIX + '甲 取 [密 其 i32]. 乙 取 [密 其 f64]. 算 F: '
        source += '甲[0]. 乙[0]. ' + '1 + 2. ' * 40 + '得 空. 法 ' + 'F(). ' * 8
        with patch.object(native_c, 'MAX_SUMMARY_DEPENDENCIES', 1):
            cached = analyze(source)
            uncached = analyze(source, expression_limit=0)
        self.assertEqual(outcome(cached), outcome(uncached))
        self.assertLess(cached.statement_visits * 2, uncached.statement_visits)
        self.assertLess(cached._steps, uncached._steps)
        self.assertLessEqual(len(cached._expression_summaries), native_c.MAX_EXPRESSION_SUMMARIES)

    def test_statement_chunks_keep_whole_body_function_hoisting(self):
        padding = '垫 取 0. ' * 20
        self.assert_equivalent(
            "算 外: S 取 密 其 签名 (迟) ([]) 'cdecl'. " + padding +
            '算 迟: 得 密 其 i32. 法 得 S. 法 外.',
            {NativeCSignature('i32', ())})

    def test_statement_chunks_keep_first_read_before_later_binding(self):
        padding = '垫 取 0. ' * 20
        source = ('型 取 密 其 i32. 算 外: 旧 取 型. ' + padding +
            "型 取 密 其 f64. 得 旧. 法 外. S 取 密 其 签名 (外) ([]) 'cdecl'.")
        self.assert_equivalent(source, {NativeCSignature('i32', ())})
        # The same source nested in a function captures a live cell; its
        # later write MUST remain visible, unlike a fresh module shadow.
        self.assert_equivalent('算 容: ' + source + ' 得 空. 法 容.',
                               {NativeCSignature('i32', ()), NativeCSignature('f64', ())})


    def test_statement_chunks_invalidate_returned_mutable_alias(self):
        padding = '垫 取 0. ' * 20
        self.assert_equivalent(
            '参数 取 [密 其 i32]. 算 外: ' + padding + '得 参数. 法 外. 外. '
            "参数[0] 取 密 其 f64. S 取 密 其 签名 (密 其 i32) (外) 'cdecl'.",
            error='参数阵')

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
            # Same scalar actuals do not make distinct runtime calls aliases.
            self.assertIsNot(first, again)
            self.assertIsNot(second, again)
            self.assertIsNone(first.items)
            self.assertEqual(second.items, (1, True, '字', None))
            self.assertEqual(again.items, (1, True, '字', None))


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

    def test_first_literal_array_evaluation_counts_every_item_without_size_quota(self):
        # The literal cache removes repeat work, not the measured first visit.
        # Both sides of the retired whole-program boundary must succeed.
        statement = parse('显 [1].')[0]
        array = statement.data['expr']
        item = array.data['items'][0]
        for count in (199999, 200000, 250000):
            with self.subTest(count=count):
                array.data['items'] = [item] * count
                value = CountingPlan({PATH: [statement]})
                self.assertEqual(value._steps, count + 1)
                self.assertEqual(value.body_visits['number'], count)

    def test_repeated_leaf_expressions_have_no_whole_program_quota(self):
        # Repeated visits still count. Normal source growth cannot turn a
        # previously accepted static native plan into an error at 200001.
        statement = parse('显 1.')[0]
        for limit in (0, native_c.MAX_EXPRESSION_SUMMARIES):
            with self.subTest(limit=limit), patch.object(native_c, 'MAX_EXPRESSION_SUMMARIES', limit):
                for count in (200000, 200001, 250000):
                    value = CountingPlan({PATH: [statement] * count})
                    self.assertEqual(value._steps, count)
                    self.assertEqual(value.body_visits['number'], count)
                    self.assertEqual(value.signatures, ())

    def test_independent_modules_do_not_share_an_admission_quota(self):
        statement = parse('显 1.')[0]
        graph = {f'{PATH}.{i}': [statement] * 25000 for i in range(9)}
        reports = []
        value = CountingPlan(graph, diagnostics=reports.append)
        self.assertEqual(value._steps, 225000)
        self.assertTrue(reports[0]['completed'])
        self.assertIsNone(reports[0]['step_limit'])
        self.assertEqual(sum(reports[0]['module_steps'].values()), 225000)


if __name__ == '__main__':
    unittest.main()
