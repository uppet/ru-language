"""Input growth is not a quota; all mutable identities and ABI shapes survive."""
import tempfile
from pathlib import Path
import unittest
from rulang import native_c as n
from rulang.native_tiered import build_native_c_plan
from rulang.frontend import parse
from rulang.modules import load_module_graph

class NativeFiniteDomainTests(unittest.TestCase):
    def test_more_than_128_mutable_owners_are_never_truncated(self):
        owners = [n._Array(()) for _ in range(1025)]
        merged = n._reachable_values(*owners)
        self.assertEqual(n._alternatives(merged), tuple(owners))
        self.assertEqual(len({id(x) for x in n._alternatives(merged)}), 1025)
        self.assertEqual(n._alternatives(n._merge(merged, *owners)), tuple(owners))

    def test_more_than_1024_distinct_signature_shapes_are_supported(self):
        source = "密 取 外言 '如:密'. "
        for value in range(1025):
            cells = ','.join('密 其 ' + ('i32' if value & (1 << bit) else 'u8')
                             for bit in range(11))
            source += f"签{value} 取 密 其 签名 (密 其 无值) ([{cells}]) 'cdecl'.\n"
        path = str((Path(tempfile.gettempdir()) / 'native-finite-shapes.ru').resolve())
        value = build_native_c_plan(load_module_graph(path, parse(source)))
        expected = {n.NativeCSignature('无值', tuple('i32' if bits & (1 << bit) else 'u8'
                                                   for bit in range(11))) for bits in range(1025)}
        self.assertEqual(set(value.signatures), expected)
        self.assertEqual(len(value.signatures), 1025)

    def test_nested_reentry_and_many_fresh_calls_reach_finite_heap(self):
        prefix = ('算 造 原: 果 取 []. 果 其 增 1. 得 果. 法 '
                  '算 H: X 取 []. 循 13 次 X 取 造 X. 环 得 X. 法 ')
        sources = (prefix + 'X 取 []. 循 13 次 X 取 H. 环',
                   prefix + ''.join(f'结果{i} 取 H. 无关{i} 取 {i}.\n' for i in range(129)))
        path = str((Path(tempfile.gettempdir()) / 'native-finite-reentry.ru').resolve())
        for source in sources:
            for engine in (n.NativeCPlan, build_native_c_plan):
                with self.subTest(source=source[-40:], engine=engine.__name__):
                    value = engine(load_module_graph(path, parse(source)))
                    self.assertEqual(value.signatures, ())
                    self.assertFalse(value._deferred_queue)
                    self.assertFalse(value._deferred_pending)
