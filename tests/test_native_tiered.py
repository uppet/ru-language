"""Tiered native plans preserve precise results, diagnostics and cancellation."""
import tempfile
import unittest
import weakref
from pathlib import Path
from unittest.mock import patch

from rulang import native_c as n, native_tiered as t
from rulang.frontend import BudgetExceeded, RuError, parse
from rulang.modules import load_module_graph

PREFIX = "密 取 外言 '如:密'. "
MODULE_PATH = str(Path(tempfile.gettempdir()) / 'native-tiered-test.ru')
CASES = {
    'single': "S 取 密 其 签名 (密 其 i32) ([]) 'cdecl'.",
    'precision_alias': "算 F: 得 [密 其 i32]. 法 算 W: 得 F. 法 A 取 W. B 取 W. A 其 增 0. S 取 密 其 签名 (密 其 无值) B 'cdecl'.",
    'closure_precision': "算 外 T: 算 F: 得 [T]. 法 得 算 F. 法 算 W F: 得 F(). 法 C 取 外 (密 其 i32). D 取 外 (密 其 f64). A 取 W C. B 取 W D. A 其 增 0. S 取 密 其 签名 (密 其 无值) B 'cdecl'.",
    'actual_alias_error': "A 取 [密 其 i32]. B 取 A. B 其 增 0. S 取 密 其 签名 (密 其 无值) A 'cdecl'.",
    'late_product': "算 F T: 得 [T]. 法 算 W T: 得 F T. 法 A 取 W (密 其 i32). S 取 密 其 签名 (密 其 无值) A 'cdecl'. B 取 W (密 其 f64).",
    'wide_product': "算 F T: 得 [" + ','.join(['T'] * 64) + "]. 法 算 W T: 得 F T. 法 A 取 W (密 其 i32). B 取 W (密 其 f64). S 取 密 其 签名 (密 其 无值) A 'cdecl'. R 取 密 其 签名 (密 其 无值) B 'cdecl'.",
}


def graph(source):
    return load_module_graph(MODULE_PATH, parse(PREFIX + source))


def error_details(error):
    return (error.message, error.category, error.line, error.col,
            getattr(error, 'path', None), getattr(error, 'source_name', None),
            getattr(error, 'source_text', None))


def failing_diagnostics(report):
    raise ValueError('diagnostic failure')


class NativeTieredTests(unittest.TestCase):
    def assert_precise_equivalence(self, name):
        modules = graph(CASES[name])
        reports = []
        try:
            plan = t.build_native_c_plan(modules, diagnostics=reports.append)
            outcome = [(item.result, item.params) for item in plan.signatures]
            error = None
        except RuError as caught:
            outcome, error = None, error_details(caught)
        try:
            precise = n.NativeCPlan(modules)
            expected = [(item.result, item.params) for item in precise.signatures]
            expected_error = None
        except RuError as caught:
            expected, expected_error = None, error_details(caught)
        self.assertEqual(outcome, expected)
        self.assertEqual(error, expected_error)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]['steps'], sum(stage['steps'] for stage in reports[0]['stages']))
        self.assertEqual(len(reports[0]['stages']), 1 if name == 'single' else 2)

    def test_single_shape_matches_precise(self):
        self.assert_precise_equivalence('single')

    def test_alias_refinement_matches_precise(self):
        self.assert_precise_equivalence('precision_alias')

    def test_closure_refinement_matches_precise(self):
        self.assert_precise_equivalence('closure_precision')

    def test_actual_alias_error_matches_precise(self):
        self.assert_precise_equivalence('actual_alias_error')

    def test_late_product_matches_precise(self):
        self.assert_precise_equivalence('late_product')

    def test_wide_product_matches_precise(self):
        self.assert_precise_equivalence('wide_product')

    def test_many_arrays_of_one_shape_do_not_refine(self):
        plan = t._CoarsePlan(graph('A 取 0.'))
        arrays = tuple(n._Array((n._Type('i32'),)) for _ in range(150))
        plan._single_shape((n._Type('i32'),), arrays)

    def test_ambiguity_refines_before_product_and_revalidation(self):
        plan = t._CoarsePlan(graph('A 取 0.'))
        ambiguous = n._Array((n._merge(n._Type('i32'), n._Type('f64')), ) * 64)
        with self.assertRaises(t._Refine):
            plan._single_shape((n._Type('i32'),), (ambiguous,))
        with self.assertRaises(t._Refine):
            plan._before_signature_revalidation(ambiguous, 'i32', None)

    def test_resource_and_cancellation_never_start_precise_stage(self):
        failures = (RuError('resource', category='资源错误'),
                    BudgetExceeded('budget', category='原生编译错误'),
                    MemoryError(), KeyboardInterrupt())
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with patch.object(t, '_CoarsePlan', side_effect=failure), \
                        patch.object(t.n, 'NativeCPlan') as precise:
                    with self.assertRaises(type(failure)) as caught:
                        t.build_native_c_plan(graph('A 取 0.'))
                    self.assertIs(caught.exception, failure)
                    precise.assert_not_called()

    def test_failed_cyclic_coarse_heap_is_released_before_precise(self):
        refs = []
        coarse_type, precise_type = t._CoarsePlan, n.NativeCPlan
        test = self

        class ObservedCoarse(coarse_type):
            def __init__(self, *args, **kwargs):
                refs.append(weakref.ref(self))
                super().__init__(*args, **kwargs)

        class ObservedPrecise(precise_type):
            def __init__(self, *args, **kwargs):
                test.assertTrue(refs)
                test.assertIsNone(refs[-1]())
                super().__init__(*args, **kwargs)

        with patch.object(t, '_CoarsePlan', ObservedCoarse), \
                patch.object(t.n, 'NativeCPlan', ObservedPrecise):
            t.build_native_c_plan(graph(CASES['precision_alias']))

    def test_none_receiver_does_not_bypass_product_gate(self):
        plan = t._CoarsePlan(graph('A 取 0.'))
        ambiguous = n._Array((n._merge(n._Type('i32'), n._Type('f64')), ) * 64)
        with self.assertRaises(t._Refine):
            plan._native(n._Operation('签名'),
                         [(None, n._Type('i32')), (None, ambiguous), (None, 'cdecl')],
                         parse('0.')[0])

    def test_diagnostic_failure_propagates_after_success(self):
        with self.assertRaisesRegex(ValueError, 'diagnostic failure'):
            t.build_native_c_plan(graph(CASES['single']), diagnostics=failing_diagnostics)

    def test_diagnostic_failure_does_not_mask_analysis_error(self):
        with self.assertRaises(RuError):
            t.build_native_c_plan(graph(CASES['actual_alias_error']), diagnostics=failing_diagnostics)

    def test_diagnostic_failure_does_not_mask_cancellation(self):
        with patch.object(t, '_CoarsePlan', side_effect=KeyboardInterrupt('cancel')):
            with self.assertRaises(KeyboardInterrupt):
                t.build_native_c_plan(graph(CASES['single']), diagnostics=failing_diagnostics)


if __name__ == '__main__':
    unittest.main()
