"""Small domain/alias probes; original compiler tests remain untouched."""
from itertools import product
import random
import tempfile
import unittest
from pathlib import Path
from rulang import native_c as n
from rulang.frontend import parse, RuError
from rulang.modules import load_module_graph
PREFIX = "密 取 外言 '如:密'. "

def plan(s):
    return n.NativeCPlan(load_module_graph(str(Path(tempfile.gettempdir()) / 'native-merge-union.ru'), parse(PREFIX + s)))
P = '算 造 原: 果 取 []. 果 其 增 1. 得 果. 法 '
H = '算 H: X 取 []. 循 13 次 X 取 造 X. 环 得 X. 法 '

class NativeMergeDomainTests(unittest.TestCase):

    def test_more_than_128_nested_arrays_remain_distinct(self):
        p = plan('表 取 [' + ','.join((f'[[{i}]]' for i in range(160))) + ']. 值 取 表[读].')
        env = next(iter(p._module_values.values())).env
        vals = n._alternatives(env.get('值'))
        self.assertEqual(len(vals), 160)
        self.assertTrue(all((isinstance(x, n._Array) for x in vals)))

    def test_large_owner_join_cannot_erase_real_alias_pollution(self):
        arrays = ','.join((f'[{i}]' for i in range(160)))
        with self.assertRaisesRegex(RuError, '无法静态确定'):
            plan("参数 取 [密 其 i32]. S 取 密 其 签名 (密 其 i32) 参数 'cdecl'. 表 取 [" + arrays + ',参数]. 未知 (表[读]).')

    def test_string_and_numeric_histories_widen(self):
        self.assertIs(n._merge(*(f'x{i}' for i in range(160))), n.STRING)
        self.assertIs(n._merge(*range(160)), n.NUMBER)
        owners = [n._Array(()) for _ in range(160)]
        vals = n._alternatives(n._merge(*owners, n._Type('i32'), False, None, n.STRING, n.NUMBER))
        self.assertEqual(len(vals), 165)
        self.assertTrue(all((any((v is o for v in vals)) for o in owners)))

    def test_fresh_loop_nested_reentry_and_129_H(self):
        for tail in ('X 取 []. 循 13 次 X 取 H. 环', ''.join((f'结果{i} 取 H. 无关{i} 取 {i}.' for i in range(129)))):
            p = plan(P + H + tail)
            self.assertTrue(p._analysis_completed)

    def test_closure_feedback_has_finite_lexical_parent(self):
        p = plan('算 造 原: 算 内: 得 原. 法 得 算 内. 法 X 取 空. 循 13 次 X 取 造 X. 环')
        self.assertLess(len(p._envs), 10)

    def test_independent_factory_and_true_reference_alias(self):
        head = '算 造 原: 得 [密 其 i32]. 法 A 取 造 ([]). '
        p = plan(head + "B 取 造 ([]). A 其 增 0. S 取 密 其 签名 (密 其 i32) B 'cdecl'.")
        self.assertEqual(p.signatures, (n.NativeCSignature('i32', ('i32',)),))
        with self.assertRaisesRegex(RuError, '无法静态确定'):
            plan(head + "B 取 A. A 其 增 0. S 取 密 其 签名 (密 其 i32) B 'cdecl'.")

    def test_unknown_string_cannot_supply_abi(self):
        table = '表 取 [' + ','.join((f"'x{i}'" for i in range(160))) + ']. 值 取 表[读]. '
        for suffix in ('T 取 __密 其 类型 值.', 'S 取 密 其 签名 (密 其 i32) ([]) 值.', "S 取 密 其 签名 (密 其 i32) ([值]) 'cdecl'."):
            with self.assertRaisesRegex(RuError, '无法静态确定'):
                plan(table + suffix)

    def test_abi_combinations_are_not_a_business_size_quota(self):
        params = ','.join(['型'] * 8)
        p = plan('型 取 密 其 i32. 型 取 密 其 f64. S 取 密 其 签名 (密 其 i32) ([' + params + "]) 'cdecl'.")
        self.assertEqual(len(p.signatures), 256)
        self.assertEqual(set(p.signatures), {n.NativeCSignature('i32', items) for items in product(('i32', 'f64'), repeat=8)})

    def test_large_callable_union_keeps_effects(self):
        defs = ''.join((f'算 F{i}: 得 {i}. 法 ' for i in range(130)))
        defs += "算 末: 得 密 其 签名 (密 其 f64) ([]) 'cdecl'. 法 "
        p = plan(defs + '表 取 [' + ','.join((f'算 F{i}' for i in range(130))) + ',算 末]. 回 取 表[读]. 回().')
        self.assertEqual(p.signatures, (n.NativeCSignature('f64', ()),))

def linear_merge(*values):
    """Historical linear reference; intentionally no optimized keys."""
    UNKNOWN, NUMBER, STRING = (n.UNKNOWN, n.NUMBER, n.STRING)
    SCALAR_LITERAL_PRECISION = n.SCALAR_LITERAL_PRECISION
    _Choice, _alternatives, _same = (n._Choice, n._alternatives, n._same)
    result = []
    numeric = False
    string = False
    for value in values:
        for alternative in _alternatives(value):
            if alternative is NUMBER:
                result = [item for item in result if type(item) not in (int, float)]
                numeric = True
            elif alternative is STRING:
                result = [item for item in result if type(item) is not str]
                string = True
            elif string and type(alternative) is str:
                continue
            elif numeric and type(alternative) in (int, float):
                continue
            if not any((_same(alternative, item) for item in result)):
                result.append(alternative)
            if len(result) > SCALAR_LITERAL_PRECISION:
                nonnumeric = [item for item in result if type(item) not in (int, float)]
                if len(nonnumeric) < len(result):
                    result = nonnumeric + ([] if numeric else [NUMBER])
                    numeric = True
                nonstring = [item for item in result if type(item) is not str]
                if len(nonstring) < len(result):
                    result = nonstring + ([] if string else [STRING])
                    string = True
    if not result:
        return UNKNOWN
    return result[0] if len(result) == 1 else _Choice(tuple(result))


class NativeMergeDifferentialTests(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(48207)
        self.owners = [n._Array(()) for _ in range(180)]
        nodes = [object() for _ in range(4)]
        environments = [object() for _ in range(3)]
        self.functions = [n._Function(nodes[i % 4], environments[i % 3], 'module', bool(i % 2))
                          for i in range(24)]
        first_nan, second_nan = float('nan'), float('nan')
        self.pool = [None, True, False, 0, 1, -0.0, 0.0, 1.0,
                     first_nan, first_nan, second_nan, n.NUMBER, n.STRING, n.UNKNOWN,
                     'a', 'b', *self.owners[:6], *self.functions,
                     n._Type('i32'), n._Type('i32'),
                     n.NativeCSignature('i32', ('i32',)), n.NativeCSignature('i32', ('i32',)),
                     n._Operation('x', n.NATIVE), n._Operation('x', n.NATIVE),
                     n._Opaque(()), [1], [True],
                     n._Choice((n._Choice((True, 1)), n._Choice((1, True))))]
        self.comparisons = 0

    def assert_reference_merge(self, values):
        expected, actual = linear_merge(*values), n._merge(*values)
        with self.subTest(comparison=self.comparisons):
            self.assertTrue(n._same(expected, actual),
                            (values, n._alternatives(expected), n._alternatives(actual)))
        self.comparisons += 1

    def test_seeded_mixed_values_match_linear_reference(self):
        for _ in range(1200):
            values = [self.rng.choice(self.pool) for _ in range(self.rng.randrange(45))]
            if self.rng.randrange(2):
                values = [n._Choice(tuple(values))]
            self.assert_reference_merge(values)
        self.assertEqual(self.comparisons, 1200)

    def test_widening_boundaries_match_linear_reference(self):
        strings = ['s' + str(i) for i in range(140)]
        numbers = list(range(140))
        for size in (127, 128, 129, 140, 180):
            for source in (self.owners[:size], strings[:size], numbers[:size],
                           self.owners[:size] + strings + numbers):
                for _ in range(12):
                    values = list(source) + self.rng.sample(self.pool, 8)
                    self.rng.shuffle(values)
                    self.assert_reference_merge(values)
        self.assertEqual(self.comparisons, 240)

    def test_scalar_top_positions_match_linear_reference(self):
        strings = ['s' + str(i) for i in range(140)]
        for top in (n.NUMBER, n.STRING, n.UNKNOWN):
            for position in range(142):
                self.assert_reference_merge(strings[:position] + [top] + strings[position:] +
                                            [True, False, None, *self.owners[:3]])
        self.assertEqual(self.comparisons, 426)

    def test_function_parent_identity_and_declared_flag_are_preserved(self):
        self.assert_reference_merge(self.functions * 20)

    def test_nested_choices_match_linear_reference(self):
        for _ in range(20):
            self.assert_reference_merge([
                n._Choice((n._Choice(tuple(self.rng.sample(self.pool, 8))),)),
                *self.rng.sample(self.pool, 15)])
        self.assertEqual(self.comparisons, 20)

    def test_extension_equality_fallback_matches_known_values(self):
        class EqualOne:
            def __eq__(self, other):
                return other == 1

        class EqualTop:
            def __eq__(self, other):
                return other is n.NUMBER or other is n.STRING

        self.assert_reference_merge([EqualOne(), 1, True, 2])
        self.assert_reference_merge([1, True, EqualOne(), 2])
        self.assert_reference_merge([EqualTop(), *self.owners, *range(140),
                                     *('s' + str(i) for i in range(140))])
        self.assertEqual(self.comparisons, 3)


if __name__ == '__main__':
    unittest.main()
