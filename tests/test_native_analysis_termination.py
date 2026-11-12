"""Project growth is not a termination test; unresolved ABI flow still is."""
from unittest.mock import patch
import unittest

from rulang import native_c
from rulang.frontend import RuError, parse
from rulang.modules import load_module_graph
from rulang.native_c import NativeCPlan


class FullSweepPlan(NativeCPlan):
    """Independent conservative scheduling oracle: every change wakes everyone."""
    def _changed(self, owner=None):
        super()._changed(owner)
        for key in self._deferred_functions:
            self._queue_deferred(key)


def chain_source(count):
    source = "密 取 外言 '如:密'. 算 外:\n"
    source += ''.join(f'型{i} 取 密 其 i32.\n' for i in range(count + 1))
    source += "签 取 密 其 签名 (密 其 i32) ([]) 'cdecl'.\n"
    source += ''.join(f'算 回{i}: 型{i} 取 型{i+1}. 得 0. 法\n' for i in range(count))
    source += ''.join(f'密 其 回调 签 (算 回{i}) 0.\n' for i in range(count))
    return source + f'型{count} 取 密 其 f64. 得 空. 法 外.'


def graph(source):
    return load_module_graph('/tmp/native-termination.ru', parse(source))


class NativeAnalysisTerminationTests(unittest.TestCase):
    def test_acyclic_callback_chain_longer_than_old_global_round_limit(self):
        value = NativeCPlan(graph(chain_source(129)))
        env = next(env for env in value._envs if '型0' in env.values)
        types = {item.name for item in native_c._alternatives(env.get('型0'))}
        self.assertEqual(types, {'i32', 'f64'})
        self.assertEqual(len(value.signatures), 1)
        self.assertEqual(len(value.callback_signatures), 1)
        self.assertFalse(value._deferred_queue)
        self.assertFalse(value._deferred_pending)

    def test_unvalidated_strong_hoist_rebind_is_rejected_before_inference(self):
        source = '算 G: 算 F: 得 0. 法 F 取 1. 法 循 1 次 G. 环'
        # Deliberately bypass the loader to exercise the planner's own boundary.
        with self.assertRaisesRegex(RuError, '变量名不能与函数名'):
            NativeCPlan({'/tmp/invalid-hoist.ru': parse(source)})

    def test_loop_propagation_length_is_not_a_fixed_iteration_quota(self):
        count = 129
        source = "密 取 外言 '如:密'. "
        source += ''.join(f'型{i} 取 密 其 i32. ' for i in range(count + 1))
        source += f'型{count} 取 密 其 f64. 循 1 次 '
        source += ''.join(f'型{i} 取 型{i+1}. ' for i in range(count))
        source += "环 S 取 密 其 签名 型0 ([]) 'cdecl'."
        value = NativeCPlan(graph(source))
        self.assertEqual({signature.result for signature in value.signatures}, {'i32', 'f64'})

    def test_dependency_scheduler_matches_full_sweep_when_evidence_overflows(self):
        source = chain_source(12)
        expected = FullSweepPlan(graph(source))
        for dependency_limit in (1, 256):
            for expression_limit in (0, 16384):
                with self.subTest(dependency_limit=dependency_limit, expression_limit=expression_limit):
                    with patch.object(native_c, 'MAX_EXPRESSION_DEPENDENCIES', dependency_limit), \
                            patch.object(native_c, 'MAX_SUMMARY_DEPENDENCIES', dependency_limit), \
                            patch.object(native_c, 'MAX_EXPRESSION_SUMMARIES', expression_limit):
                        actual = NativeCPlan(graph(source))
                    self.assertEqual(actual.emit_c(), expected.emit_c())
                    env = next(env for env in actual._envs if '型0' in env.values)
                    self.assertEqual({item.name for item in native_c._alternatives(env.get('型0'))},
                                     {'i32', 'f64'})

    def test_late_unknown_callback_mutation_still_invalidates_signature(self):
        source = """密 取 外言 '如:密'.
        算 外:
            参数 取 [密 其 i32].
            算 后: 未知 参数. 得 0. 法
            签 取 密 其 签名 (密 其 i32) 参数 'cdecl'.
            回签 取 密 其 签名 (密 其 i32) ([]) 'cdecl'.
            密 其 回调 回签 (算 后) 0.
        法 外.
        """
        for plan in (NativeCPlan, FullSweepPlan):
            with self.subTest(plan=plan), self.assertRaisesRegex(RuError, '无法静态确定'):
                plan(graph(source))

    def test_direct_callback_factory_cycle_still_rejects(self):
        source = """密 取 外言 '如:密'.
        签 取 密 其 签名 (密 其 i32) ([]) 'cdecl'.
        算 工厂:
            算 后: 工厂. 得 0. 法
            密 其 回调 签 (算 后) 0.
        法 工厂.
        """
        with self.assertRaisesRegex(RuError, '递归'):
            NativeCPlan(graph(source))

    def test_diagnostic_failure_never_masks_original_failure_or_cancel(self):
        for original in (MemoryError(), RecursionError(), KeyboardInterrupt(),
                         RuError('original ABI rejection', category='原生编译错误')):
            with self.subTest(original=type(original).__name__):
                value = NativeCPlan.__new__(NativeCPlan)
                with patch.object(NativeCPlan, '_analyze', side_effect=original):
                    with self.assertRaises(type(original) if isinstance(original, (KeyboardInterrupt, RuError))
                                          else RuError) as caught:
                        value.__init__(graph('显 1.'), diagnostics=lambda report: (_ for _ in ()).throw(MemoryError()))
                if isinstance(original, RuError):
                    self.assertIs(caught.exception, original)
                with self.assertRaisesRegex(RuError, '禁止生成部分 ABI'):
                    value.emit_c()


if __name__ == '__main__':
    unittest.main()
