"""String literal histories widen; aliases and ABI proof remain exact."""
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from rulang import native_c as n
from rulang.frontend import parse, RuError
from rulang.modules import load_module_graph

PATH = str(Path('/tmp/native_string_widening.ru').resolve())
PREFIX = "密 取 外言 '如:密'. "
STRINGS = ','.join(f"'item{i}'" for i in range(129))
def plan(source):
    return n.NativeCPlan(load_module_graph(PATH, parse(source)))

class StringWideningTests(unittest.TestCase):
    def test_data_table_and_loop_returns_widen(self):
        sources = ["表 取 [" + STRINGS + "]. 值 取 表[读].",
                   '算 F: 循 1 次 ' + ''.join(f"得 'item{i}'." for i in range(129)) + '环 法 值 取 F.']
        for source in sources:
            for proof in (True, False):
                with self.subTest(source=source[:20], proof=proof), ExitStack() as stack:
                    if not proof:
                        stack.enter_context(patch.object(n, '_same_returns', return_value=False))
                        stack.enter_context(patch.object(n, 'MAX_EXPRESSION_SUMMARIES', 0))
                        stack.enter_context(patch.object(n._SummaryFrame, 'replay_stable', return_value=False))
                    p = plan(PREFIX + source)
                    self.assertIs(p._module_values[PATH].env.get('值'), n.STRING)
    def test_stable_join_keeps_nonstring_identities(self):
        strings = tuple(f'item{i}' for i in range(129))
        array = n._Array(())
        function = plan('算 F: 得 0. 法 F.')._functions[0]
        kept = (n.UNKNOWN, n._Type('i32'), array, n._Opaque((array,)), function,
                n._Operation('签名', n.NATIVE), False, None)
        value = n._merge(*strings, *range(129), *kept)
        expected = n._alternatives(value)
        self.assertEqual(set(expected), {*kept, n.STRING, n.NUMBER})
        for _ in range(140):
            value = n._merge(value, *strings, *range(129))
            self.assertEqual(n._alternatives(value), expected)
        self.assertIs(n._merge(*strings), n.STRING)
        self.assertIs(n._merge('cdecl', n.STRING, 'win64'), n.STRING)
        self.assertIsInstance(n._merge(*strings[:128]), n._Choice)
    def test_context_and_structural_state_distinguish_scalar_tops(self):
        p = plan('值 取 0.')
        self.assertNotEqual(p._context_key(n.STRING), p._context_key(n.NUMBER))
        env = p._module_values[PATH].env
        env.values['probe'] = n.STRING
        before = p._state()
        env.values['probe'] = n.NUMBER
        self.assertNotEqual(before, p._state())

    def test_widened_abi_components_are_unresolved(self):
        table = '表 取 [' + STRINGS + ']. 值 取 表[读]. '
        for expression in ("__密 其 类型 值", "密 其 签名 值 ([]) 'cdecl'",
                "密 其 签名 (密 其 i32) ([值]) 'cdecl'",
                "密 其 签名 (密 其 i32) ([]) 值",
                "密 其 回调 值 (算: 得 0. 法) 0"):
            with self.subTest(expression=expression), self.assertRaisesRegex(RuError, '无法静态确定'):
                plan(PREFIX + table + 'S 取 ' + expression + '.')
    def test_callable_effect_and_mutable_alias_not_erased(self):
        p = plan(PREFIX + f"算 造: 得 密 其 签名 (密 其 f64) ([]) 'cdecl'. 法 表 取 [{STRINGS}, 算 造]. 回 取 表[读]. 回().")
        self.assertEqual(p.signatures, (n.NativeCSignature('f64', ()),))
        with self.assertRaisesRegex(RuError, '无法静态确定'):
            plan(PREFIX + f"参数 取 [密 其 i32]. S 取 密 其 签名 (密 其 i32) 参数 'cdecl'. 表 取 [{STRINGS}, 参数]. 别名 取 表[读]. 未知 别名.")
