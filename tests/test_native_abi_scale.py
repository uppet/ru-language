"""ABI plans scale with finite signatures, not arbitrary compiler quotas."""
import unittest
import tempfile
from pathlib import Path
from itertools import product
from unittest.mock import patch
from rulang import native_c as n
from rulang.frontend import parse, RuError
from rulang.modules import load_module_graph
NODE = parse('显 0.')[0]
T = n._Choice((n._Type('i32'), n._Type('f64')))

def register(plan, array, result=None):
    return plan._native(n._Operation('签名'), [(None, result or n._Type('无值')), (None, array), (None, 'cdecl')], NODE)

def graph(src):
    return load_module_graph(str(Path(tempfile.gettempdir()) / 'native-abi-scale.ru'), parse("密 取 外言 '如:密'. " + src))

class NativeABIScaleTests(unittest.TestCase):

    def test_2048_exact_signatures_and_stable_index(self):

        class Plan(n.NativeCPlan):

            def _analyze(self):
                a = n._Array((T,) * 11)
                first = register(self, a)
                second = register(self, a)
                self.assertions = (len(n._alternatives(first)), len(n._alternatives(second)))
                super()._analyze()
        p = Plan({})
        self.assertEqual(p.assertions, (2048, 2048))
        self.assertEqual(len(p.signatures), 2048)
        self.assertEqual(set(p.signatures), {n.NativeCSignature('无值', x) for x in product(('i32', 'f64'), repeat=11)})
        self.assertEqual(len(p._signature_index), 2048)
        self.assertTrue(all((p._signature_index[s] == i for i, s in enumerate(p.signatures))))
        c = p.emit_c()
        self.assertIn('case 2047:', c)
        self.assertNotIn('ru_native_callback_2047_', c)

    def test_source_256_cartesian(self):
        p = n.NativeCPlan(graph('T 取 密 其 i32. T 取 密 其 f64. S 取 密 其 签名 (密 其 无值) ([' + ','.join(('T' for _ in range(8))) + "]) 'cdecl'."))
        self.assertEqual(len(p.signatures), 256)

    def test_late_unknown_before_any_product(self):

        class Plan(n.NativeCPlan):

            def _analyze(self):
                register(self, n._Array((T,) * 50 + (n.UNKNOWN,)))
        with patch.object(n, 'product', side_effect=AssertionError('enumerated before validation')):
            with self.assertRaisesRegex(RuError, '参数类型'):
                Plan({})

    def test_later_array_alternative_unknown_before_product(self):

        class Plan(n.NativeCPlan):

            def _analyze(self):
                register(self, n._Choice((n._Array((T,) * 50), n._Array((n.UNKNOWN,)))))
        with patch.object(n, 'product', side_effect=AssertionError('enumerated before validation')):
            with self.assertRaisesRegex(RuError, '参数类型'):
                Plan({})

    def test_late_mutation_rechecked_without_enumeration(self):

        class Plan(n.NativeCPlan):

            def _analyze(self):
                a = n._Array((n._Type('i32'),))
                register(self, a)
                a.items = (T,) * 50 + (n.UNKNOWN,)
                with patch.object(n, 'product', side_effect=AssertionError('late enumeration')):
                    super()._analyze()
        with self.assertRaisesRegex(RuError, '后续作用影响'):
            Plan({})

    def test_late_known_type_change_rejected(self):

        class Plan(n.NativeCPlan):

            def _analyze(self):
                a = n._Array((n._Type('i32'),))
                register(self, a)
                a.items = (n._Type('f64'),)
                super()._analyze()
        with self.assertRaisesRegex(RuError, '后续作用改变'):
            Plan({})

    def test_runtime_callback_slots_distinct_from_signature_count(self):

        class Plan(n.NativeCPlan):

            def _analyze(self):
                choices = register(self, n._Array((T,) * 11))
                self._native(n._Operation('回调'), [(None, n._alternatives(choices)[-1]), (None, n.UNKNOWN), (None, 0)], NODE)
                super()._analyze()
        p = Plan({})
        self.assertEqual(n.MAX_CALLBACKS, 1024)
        self.assertEqual(len(p.callback_signatures), 1)
        c = p.emit_c()
        self.assertIn('ru_native_callback_2047_1023', c)
        self.assertNotIn('ru_native_callback_2047_1024', c)

    def test_runtime_64_argument_contract_unchanged(self):

        class Plan(n.NativeCPlan):

            def _analyze(self):
                register(self, n._Array((n._Type('i32'),) * 65))
        with self.assertRaisesRegex(RuError, '64'):
            Plan({})

    def test_resource_and_cancel_never_emit_partial_plan(self):
        for error in (MemoryError(), KeyboardInterrupt()):

            class Plan(n.NativeCPlan):

                def _analyze(self):
                    register(self, n._Array(()))
                    raise error
            p = Plan.__new__(Plan)
            with self.assertRaises(RuError if isinstance(error, MemoryError) else KeyboardInterrupt):
                p.__init__({})
            with self.assertRaisesRegex(RuError, '禁止生成部分'):
                p.emit_c()
            if isinstance(error, MemoryError):
                self.assertEqual(p.signatures, ())
                self.assertEqual(p._signature_index, {})

    def test_emit_resource_failure_preserves_completed_analysis(self):
        p = n.NativeCPlan(graph("S 取 密 其 签名 (密 其 无值) ([]) 'cdecl'."))
        signatures = p.signatures
        for error in (MemoryError(), RecursionError(), KeyboardInterrupt()):

            class FailingTypes(dict):

                def __getitem__(self, key):
                    raise error
            with patch.object(n, 'C_TYPES', FailingTypes()):
                with self.assertRaises(RuError if not isinstance(error, KeyboardInterrupt) else KeyboardInterrupt) as caught:
                    p.emit_c()
            self.assertTrue(p._analysis_completed)
            self.assertIs(p.signatures, signatures)
            if not isinstance(error, KeyboardInterrupt):
                self.assertEqual(caught.exception.category, '资源错误')
        self.assertIn('ru_native_call_0', p.emit_c())

    def test_real_c_int_representability_guard(self):

        class Huge:

            def __len__(self):
                return 2147483649
        p = n.NativeCPlan({})
        p.signatures = Huge()
        with self.assertRaisesRegex(RuError, 'signed int') as c:
            p.emit_c()
        self.assertEqual(c.exception.category, '资源错误')
if __name__ == '__main__':
    unittest.main()
