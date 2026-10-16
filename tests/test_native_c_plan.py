"""Static ABI discovery and exact typed C thunks; no DLL loading is required."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from rulang.frontend import RuError, parse
from rulang.modules import load_module_graph
from rulang.native_c import MAX_CALLBACKS, NativeCPlan, NativeCSignature, PRIMITIVE_IDS
from rulang import native_c


PREFIX = "密 取 外言 '如:密'. "


def plan(source, path='/tmp/native_c_plan.ru'):
    return NativeCPlan(load_module_graph(path, parse(source)))


class NativeCAnalysisTests(unittest.TestCase):
    def test_primitive_ids_match_runtime_contract(self):
        self.assertEqual(list(PRIMITIVE_IDS.values()), list(range(14)))
        self.assertEqual(PRIMITIVE_IDS['无值'], 0)
        self.assertEqual(PRIMITIVE_IDS['指针'], 13)

    def test_aliases_named_arguments_and_conventions_share_shape(self):
        value = plan(PREFIX + """
            别名 取 密.
            类型 取 别名 其 i32.
            参数列 取 [别名 其 f32, 别名 其 f64, 别名 其 指针].
            S 取 别名 其 签名 约定:'cdecl' 参数:参数列 返回:类型.
            T 取 密 其 签名 类型 参数列 'win64'.
        """)
        self.assertEqual(value.signatures, (NativeCSignature('i32', ('f32', 'f64', '指针')),))

    def test_import_all_and_function_wrapper_local_aliases(self):
        value = plan("""
            尽取 外言 '如:密'.
            算 造 类型:
                局部 取 类型.
                参数们 取 [局部, f64].
                得 签名 返回:局部 参数:参数们 约定:'win64'.
            法
            甲 取 造 i32.
            乙 取 造 u64.
        """)
        self.assertEqual(set(value.signatures), {
            NativeCSignature('i32', ('i32', 'f64')),
            NativeCSignature('u64', ('u64', 'f64'))})

    def test_nested_closure_and_callable_alias(self):
        value = plan(PREFIX + """
            算 造 型:
                算 内造:
                    得 密 其 签名 型 ([型]) 'cdecl'.
                法
                引用 取 算 内造.
                得 引用().
            法
            S 取 造 (密 其 i16).
        """)
        self.assertEqual(value.signatures, (NativeCSignature('i16', ('i16',)),))

    def test_callable_reference_alias_is_not_implicitly_invoked(self):
        value = plan(PREFIX + """
            算 造 型: 得 密 其 签名 型 ([]) 'cdecl'. 法
            F 取 算 造.
            G 取 F.
            S 取 G (密 其 i32).
        """)
        self.assertEqual(value.signatures, (NativeCSignature('i32', ()),))

    def test_finite_conditional_type_and_signature_choices(self):
        value = plan(PREFIX + """
            型 取 密 其 i32.
            若 读 则 型 取 密 其 f64. 然
            S 取 密 其 签名 型 ([型]) 'win64'.
        """)
        self.assertEqual(set(value.signatures), {
            NativeCSignature(r, (p,)) for r in ('i32', 'f64') for p in ('i32', 'f64')})

    def test_local_import_and_dormant_function_are_analyzed(self):
        value = plan("""
            算 未用 值:
                密 取 外言 '如:密'.
                得 密 其 签名 (密 其 u8) ([]) 'cdecl'.
            法
        """)
        self.assertEqual(value.signatures, (NativeCSignature('u8', ()),))

    def test_transitive_alias_import_all(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'dep.ru').write_text(PREFIX + "I 取 密 其 intptr. S 取 密 其 签名 I ([I]) 'cdecl'.", encoding='utf-8')
            value = plan("尽取 外言 './dep.ru'. 另名 取 S.", str(root / 'main.ru'))
            self.assertEqual(value.signatures, (NativeCSignature('intptr', ('intptr',)),))

    def test_callback_only_shapes_receive_slots(self):
        value = plan(PREFIX + """
            S 取 密 其 签名 (密 其 f64) ([密 其 f32]) 'win64'.
            T 取 密 其 签名 (密 其 i32) ([]) 'cdecl'.
            F 取 算 值: 得 值. 法.
            C 取 密 其 回调 格式:S 算值:F 失败值:0.
        """)
        self.assertEqual(value.callback_signatures, {NativeCSignature('f64', ('f32',))})
        source = value.emit_c()
        self.assertEqual(source.count('static double ru_native_callback_0_'), MAX_CALLBACKS)
        self.assertNotIn('ru_native_callback_1_', source)
        self.assertIn('typedef double (*RuNativeCall_0)(float);', source)
        self.assertIn('slot >= 1024', source)

    def test_native_operation_reference(self):
        value = plan(PREFIX + """
            签名算 取 算 密 其 签名.
            S 取 签名算 (密 其 u32) ([密 其 i8]) 'win64'.
        """)
        self.assertEqual(value.signatures, (NativeCSignature('u32', ('i8',)),))

    def test_rejects_dynamic_signature_components(self):
        sources = [
            "S 取 密 其 签名 (密 其 i32) (读) 'win64'.",
            "S 取 密 其 签名 (密 其 i32) ([]) (读).",
            "算 造 型: 得 密 其 签名 型 ([]) 'cdecl'. 法 S 取 造 (读).",
            "算 造 参数: 得 密 其 签名 (密 其 i32) 参数 'cdecl'. 法",
            "S 取 密 其 签名 (密 其 i32) ([读]) 'win64'.",
            "算 回调造 S: 得 密 其 回调 S (算: 得 0. 法) 0. 法",
        ]
        for source in sources:
            with self.subTest(source=source), self.assertRaisesRegex(RuError, '无法静态确定'):
                plan(PREFIX + source)

    def test_error_location_points_to_user_call_not_stdlib_forwarder(self):
        source_path = str(Path('/tmp/user_abi.ru').resolve())
        with self.assertRaises(RuError) as caught:
            plan(PREFIX + "\nS 取 密 其 签名 (密 其 i32) (读) 'cdecl'.", source_path)
        self.assertEqual(caught.exception.source_name, source_path)
        self.assertEqual(caught.exception.line, 2)

    def test_dynamic_selection_from_finite_type_array(self):
        value = plan(PREFIX + """
            类型们 取 [密 其 i32,密 其 f32].
            型 取 类型们[读].
            S 取 密 其 签名 型 ([]) 'cdecl'.
        """)
        self.assertEqual(set(value.signatures), {
            NativeCSignature('i32', ()), NativeCSignature('f32', ())})

    def test_large_numeric_table_widens_without_changing_native_shapes(self):
        numbers = ','.join(str(value) for value in range(1024))
        source = PREFIX + f"""
            表 取 [{numbers}].
            算 查询 位: 得 表[位]. 法
            序 取 查询 (读 为 数).
            类型们 取 [密 其 i32, 密 其 f64].
            型 取 类型们[序].
            S 取 密 其 签名 型 ([]) 'cdecl'.
        """
        expected = {NativeCSignature('i32', ()), NativeCSignature('f64', ())}
        for cache in (True, False):
            with self.subTest(cache=cache):
                if cache:
                    value = plan(source)
                else:
                    with patch('rulang.native_c.MAX_SUMMARY_DEPENDENCIES', 0):
                        value = plan(source)
                self.assertEqual(set(value.signatures), expected)
                self.assertLess(value._steps, 5000)

    def test_numeric_widening_is_stable_and_preserves_nonnumeric_values(self):
        integers = tuple(range(129))
        floats = tuple(value + 0.5 for value in range(129))
        self.assertIs(native_c._merge(*integers), native_c.NUMBER)
        self.assertIs(native_c._merge(*floats), native_c.NUMBER)
        self.assertIsInstance(native_c._merge(*range(128)), native_c._Choice)
        marker = native_c._Type('i32')
        value = native_c._merge(native_c.UNKNOWN, *integers, marker, False, None, 'cdecl')
        expected = native_c._alternatives(value)
        self.assertEqual(set(expected), {native_c.UNKNOWN, native_c.NUMBER, marker, False, None, 'cdecl'})
        for _ in range(140):
            value = native_c._merge(value, *floats, *integers)
            self.assertEqual(native_c._alternatives(value), expected)
        self.assertEqual(set(native_c._alternatives(native_c._merge(*integers, value))), set(expected))
        for fact, number in ((False, 0), (True, 1), (False, 0.0), (True, 1.0)):
            for pair in ((fact, number), (number, fact)):
                with self.subTest(pair=pair):
                    merged = native_c._alternatives(native_c._merge(*pair, *integers))
                    self.assertEqual(len(merged), 2)
                    self.assertTrue(any(item is fact for item in merged))
                    self.assertTrue(any(item is native_c.NUMBER for item in merged))

    def test_widened_numbers_cannot_supply_abi_components(self):
        table = '表 取 [' + ','.join(map(str, range(129))) + ']. 值 取 表[读]. '
        for expression in (
                "__密 其 类型 值",
                "密 其 签名 值 ([]) 'cdecl'",
                "密 其 签名 (密 其 i32) ([值]) 'cdecl'",
                "密 其 签名 (密 其 i32) ([]) 值",
                "密 其 回调 值 (算: 得 0. 法) 0"):
            with self.subTest(expression=expression), self.assertRaises(RuError):
                plan(PREFIX + table + 'S 取 ' + expression + '.')

    def test_fact_numeric_identity_survives_choices_contexts_and_state(self):
        for fact, number in ((False, 0), (True, 1)):
            self.assertFalse(native_c._same(native_c._Choice((fact, 'x')),
                                           native_c._Choice((number, 'x'))))
            self.assertFalse(native_c._same(
                native_c._Choice((native_c._Choice((fact, 'x')), None)),
                native_c._Choice((native_c._Choice((number, 'x')), None))))
        value = plan(PREFIX + """
            算 原样 值: 得 值. 法
            甲 取 原样 真. 乙 取 原样 1.
            丙 取 原样 假. 丁 取 原样 0.
            戊 取 原样 真. 己 取 原样 1.
        """)
        env = value._module_values[str(Path('/tmp/native_c_plan.ru').resolve())].env
        for name in ('甲', '丙', '戊'):
            self.assertIs(type(env.get(name)), bool)
        for name in ('乙', '丁', '己'):
            self.assertIs(type(env.get(name)), float)
        for fact, number in ((False, 0), (True, 1)):
            env.values['probe'] = fact
            before = value._state()
            env.values['probe'] = number
            self.assertNotEqual(value._state(), before)
            array = native_c._Array((native_c._Choice((fact, 'x')),))
            env.values['probe'] = array
            before = value._state()
            array.items = (native_c._Choice((number, 'x')),)
            self.assertNotEqual(value._state(), before)

    def test_numeric_widening_keeps_callable_effects_and_array_aliases(self):
        numbers = ','.join(map(str, range(129)))
        value = plan(PREFIX + f"""
            算 造: 得 密 其 签名 (密 其 f64) ([]) 'cdecl'. 法
            表 取 [{numbers}, 算 造].
            回 取 表[读]. 回().
        """)
        self.assertEqual(value.signatures, (NativeCSignature('f64', ()),))
        with self.assertRaisesRegex(RuError, '无法静态确定'):
            plan(PREFIX + f"""
                参数 取 [密 其 i32].
                S 取 密 其 签名 (密 其 i32) 参数 'cdecl'.
                表 取 [{numbers}, 参数].
                别名 取 表[读]. 未知 别名.
            """)

    def test_numeric_widening_does_not_raise_nonnumeric_candidate_limit(self):
        for values in (
                ','.join(f"'item{value}'" for value in range(129)),
                ','.join(f'[{value},{value + 1}]' for value in range(129))):
            with self.subTest(values=values[:40]), self.assertRaisesRegex(RuError, '128 上限'):
                plan(PREFIX + '表 取 [' + values + ']. 显 表[读].')

    def test_dynamic_array_mutation_cannot_smuggle_signature(self):
        for mutation in ("参数们 其 增 (密 其 f32).", "参数们[0] 取 密 其 f64."):
            with self.subTest(mutation=mutation), self.assertRaisesRegex(RuError, '无法静态确定'):
                plan(PREFIX + "参数们 取 [密 其 i32]. " + mutation +
                     "S 取 密 其 签名 (密 其 i32) 参数们 'cdecl'.")

    def test_rejects_struct_void_and_variadic_shapes(self):
        for source, message in [
            ("S 取 密 其 签名 (密 其 i32) ([密 其 无值]) 'win64'.", '按值'),
            ("T 取 密 其 结构 [['x',密 其 i32]]. S 取 密 其 签名 T ([]) 'cdecl'.", '按值'),
            ("S 取 密 其 签名 (密 其 i32) ([]) 'varargs'.", '不支持变参'),
        ]:
            with self.subTest(source=source), self.assertRaisesRegex(RuError, message):
                plan(PREFIX + source)

    def test_64_parameters_allowed_65_rejected(self):
        def source(count):
            return PREFIX + "S 取 密 其 签名 (密 其 无值) ([" + ','.join(['密 其 u8'] * count) + "]) 'cdecl'."
        self.assertEqual(len(plan(source(64)).signatures[0].params), 64)
        with self.assertRaisesRegex(RuError, '64'):
            plan(source(65))

    def test_rujian_is_ordinary_source_and_never_loads_dlls(self):
        with patch('ctypes.CDLL', side_effect=AssertionError('must not load a DLL')):
            value = plan("见 取 外言 '如见'.")
        self.assertEqual(len(value.signatures), 15)
        self.assertEqual(value.callback_signatures, {
            NativeCSignature('intptr', ('指针', 'u32', 'uintptr', 'intptr'))})

    def test_loop_carried_type_reaches_fixed_point(self):
        value = plan(PREFIX + """
            型 取 密 其 i32.
            循 2 次
                S 取 密 其 签名 型 ([]) 'cdecl'.
                型 取 密 其 f64.
            环
        """)
        self.assertEqual(set(value.signatures), {
            NativeCSignature('i32', ()), NativeCSignature('f64', ())})

    def test_loop_fixed_point_propagates_multiple_iterations(self):
        value = plan(PREFIX + """
            甲 取 密 其 i8. 乙 取 密 其 i16. 丙 取 密 其 f64.
            循 10 次
                S 取 密 其 签名 甲 ([]) 'cdecl'.
                甲 取 乙. 乙 取 丙.
            环
        """)
        self.assertEqual(set(value.signatures), {
            NativeCSignature(name, ()) for name in ('i8', 'i16', 'f64')})

    def test_captured_type_rebinding_is_not_a_new_local(self):
        value = plan(PREFIX + """
            算 外造:
                型 取 密 其 i32.
                算 改: 型 取 密 其 f64. 得 空. 法
                改.
                得 密 其 签名 型 ([]) 'cdecl'.
            法
            S 取 外造.
        """)
        self.assertIn(NativeCSignature('f64', ()), value.signatures)

    def test_branch_capture_effects_merge_into_parent(self):
        value = plan(PREFIX + """
            算 外造:
                型 取 密 其 i32.
                算 改: 型 取 密 其 f64. 得 空. 法
                若 读 则 改. 然
                得 密 其 签名 型 ([]) 'cdecl'.
            法
            S 取 外造.
        """)
        self.assertEqual(set(value.signatures), {
            NativeCSignature('i32', ()), NativeCSignature('f64', ())})

    def test_scope_shadow_does_not_mutate_outer_descriptor(self):
        value = plan(PREFIX + """
            型 取 密 其 i32.
            { 型 取 密 其 f64. }
            S 取 密 其 签名 型 ([]) 'cdecl'.
        """)
        self.assertEqual(value.signatures, (NativeCSignature('i32', ()),))

    def test_rescue_observes_body_descriptor_effects(self):
        value = plan(PREFIX + """
            型 取 密 其 i32.
            试 型 取 密 其 f64. 卒 'x'.
            救 原因 S 取 密 其 签名 型 ([]) 'cdecl'. 终
        """)
        self.assertIn(NativeCSignature('f64', ()), value.signatures)

    def test_rescue_binding_shadows_outer_descriptor(self):
        value = plan(PREFIX + """
            型 取 密 其 i32.
            试 卒 'x'. 救 原因 型 取 密 其 f64. 终
            S 取 密 其 签名 型 ([]) 'cdecl'.
        """)
        self.assertEqual(value.signatures, (NativeCSignature('i32', ()),))

    def test_unknown_method_invalidates_nested_mutable_aliases(self):
        for argument, setup in [('参数们', ''), ('外层', '外层 取 [参数们].')]:
            with self.subTest(argument=argument), self.assertRaisesRegex(RuError, '无法静态确定'):
                plan(PREFIX + """
                    形 工具: 算 改 值: 得 空. 法 象
                    对象 取 新 工具.
                    参数们 取 [密 其 i32].
                """ + setup + "对象 其 改 " + argument + ". " +
                     "S 取 密 其 签名 (密 其 i32) 参数们 'cdecl'.")

    def test_unknown_choice_keeps_reachable_mutable_aliases(self):
        with self.assertRaisesRegex(RuError, '无法静态确定'):
            plan(PREFIX + """
                形 工具: 算 改 值: 得 空. 法 象
                对象 取 新 工具.
                参数们 取 [密 其 i32]. 别名 取 参数们.
                若 读 则 别名 取 读. 然
                对象 其 改 别名.
                S 取 密 其 签名 (密 其 i32) 参数们 'cdecl'.
            """)

    def test_previously_called_constructor_cannot_escape_unknown_dispatch(self):
        with self.assertRaisesRegex(RuError, '无法静态确定'):
            plan(PREFIX + """
                算 造 型: 得 密 其 签名 型 ([]) 'cdecl'. 法
                F 取 算 造.
                S 取 F (密 其 i32).
                盒 取 典: 'f' 对 F. 成.
                G 取 盒 其 查 'f'.
                T 取 G (密 其 f64).
            """)

    def test_sliced_callable_escape_cannot_hide_dynamic_constructor(self):
        with self.assertRaisesRegex(RuError, '无法静态确定'):
            plan(PREFIX + """
                算 造 型: 得 密 其 签名 型 ([]) 'cdecl'. 法
                F 取 算 造. S 取 F (密 其 i32).
                列 取 [F]. 切片 取 列[0:1].
                G 取 切片[0]. T 取 G (密 其 f64).
            """)

    def test_loop_array_mutation_is_rejected_at_compile_time(self):
        with self.assertRaisesRegex(RuError, '无法静态确定'):
            plan(PREFIX + """
                参数们 取 [密 其 i32].
                循 2 次
                    S 取 密 其 签名 (密 其 i32) 参数们 'cdecl'.
                    参数们[0] 取 密 其 f64.
                环
            """)

    def test_descriptor_or_non_scalar_recursive_paths_are_rejected(self):
        for body in [
            "S 取 密 其 签名 型 ([]) 'cdecl'. 若 数量 > 0 则 造 (密 其 f64) 0. 然 得 S.",
            "若 数量 > 0 则 造 型 0. 然 得 型.",
        ]:
            with self.subTest(body=body), self.assertRaisesRegex(RuError, '无法证明此递归路径与原生描述符无关'):
                plan(PREFIX + "算 造 型 数量: " + body + " 法 S 取 造 (密 其 i32) 1.")

    def test_pure_factorial_with_static_native_signatures_is_supported(self):
        value = plan(PREFIX + """
            S 取 密 其 签名 (密 其 i32) ([]) 'cdecl'.
            算 阶乘 数量:
                若 数量 <= 1 则 得 1. 然
                得 数量 * (阶乘 (数量 - 1)).
            法
            显 阶乘 6.
        """)
        self.assertEqual(value.signatures, (NativeCSignature('i32', ()),))

    def test_pure_string_recursion_with_static_native_signatures_is_supported(self):
        value = plan(PREFIX + """
            S 取 密 其 签名 (密 其 i32) ([]) 'cdecl'.
            算 重复 文 为 句, 数量 为 数:
                若 数量 <= 0 则 得 ''. 然
                若 数量 <= 1 则 得 文. 然
                得 文 + (重复 文 (数量 - 1)).
            法
            显 重复 'x' 3.
        """)
        self.assertEqual(value.signatures, (NativeCSignature('i32', ()),))

    def test_pure_factorial_from_native_button_callback_is_supported(self):
        value = plan(PREFIX + """
            算 阶乘 数量:
                若 数量 <= 1 则 得 1. 然
                得 数量 * (阶乘 (数量 - 1)).
            法
            算 点击 值: 得 阶乘 6. 法
            S 取 密 其 签名 (密 其 i32) ([密 其 i32]) 'cdecl'.
            C 取 密 其 回调 S (算 点击) 0.
        """)
        self.assertEqual(value.callback_signatures, {NativeCSignature('i32', ('i32',))})

    def test_recursive_member_access_and_capture_writes_are_rejected(self):
        sources = [
            "算 F n: 若 n > 0 则 F (n-1). 然 得 密 其 i32. 法 F 1.",
            "算 外: 型 取 密 其 i32. 算 F n: 型 取 1. 若 n > 0 则 F (n-1). 然 得 1. 法 F 1. 得 1. 法 外.",
            "算 F n: 列 取 [n]. 若 n > 0 则 F (n-1). 然 得 1. 法 F 1.",
        ]
        for source in sources:
            with self.subTest(source=source), self.assertRaisesRegex(RuError, '无法证明此递归路径'):
                plan(PREFIX + source)

    def test_recursive_future_local_cannot_hide_global_descriptor_read(self):
        with self.assertRaisesRegex(RuError, '无法证明此递归路径'):
            plan(PREFIX + """
                乙 取 密 其 i32.
                算 F 数量:
                    甲 取 乙. 乙 取 甲.
                    若 数量 > 0 则 F (数量 - 1). 然
                    得 甲.
                法
                F 1.
            """)

    def test_pure_scalar_recursion_allows_definitely_initialized_locals(self):
        value = plan(PREFIX + """
            S 取 密 其 签名 (密 其 i32) ([]) 'cdecl'.
            算 阶乘 数量:
                若 数量 <= 1 则 得 1. 然
                前项 取 数量 - 1.
                得 数量 * (阶乘 前项).
            法
            显 阶乘 6.
        """)
        self.assertEqual(value.signatures, (NativeCSignature('i32', ()),))

    def test_recursive_parameter_swap_cannot_return_mutable_alias(self):
        with self.assertRaisesRegex(RuError, '无法证明此递归路径'):
            plan(PREFIX + """
                参数们 取 [密 其 i32].
                算 交换 甲 乙 数量:
                    若 数量 <= 0 则 得 甲. 然
                    得 交换 乙 甲 0.
                法
                别名 取 交换 0 参数们 1.
                别名 其 增 (密 其 f64).
                S 取 密 其 签名 (密 其 i32) 参数们 'cdecl'.
            """)

    def test_untyped_recursive_equality_is_not_assumed_pure(self):
        with self.assertRaisesRegex(RuError, '无法证明此递归路径'):
            plan(PREFIX + """
                算 F 值 数量:
                    若 值 == 值 则 若 数量 > 0 则 F 值 0. 然 然
                    得 1.
                法
                F 1 1.
            """)

    def test_late_discovered_equality_effect_revalidates_signature_arrays(self):
        with self.assertRaisesRegex(RuError, '无法静态确定'):
            plan(PREFIX + """
                参数们 取 [密 其 i32].
                形 工具:
                    算 同 对方:
                        参数们 其 增 (密 其 f64).
                        得 真.
                    法
                象
                甲 取 新 工具.
                显 甲 == 甲.
                签 取 密 其 签名 (密 其 i32) 参数们 'cdecl'.
            """)

    def test_array_alias_projection_paths_reject_mutation(self):
        projections = [
            "包 取 [参数们]. 别名 取 包 其 位 0.",
            "包 取 参数们 对 0. 别名 取 包 其 囫.",
            "包 取 [参数们]. 若 读 则 包 取 [参数们]. 然 别名 取 包[0].",
            "包 取 参数们 为 阵. 别名 取 包[0].",
            "包 取 [参数们]. 段 取 包 其 段 0 1. 别名 取 段[0].",
        ]
        for projection in projections:
            with self.subTest(projection=projection), self.assertRaisesRegex(RuError, '无法静态确定'):
                plan(PREFIX + "参数们 取 [密 其 i32]. " + projection +
                     " 别名 其 增 (密 其 f64). S 取 密 其 签名 (密 其 i32) 参数们 'cdecl'.")

    def test_callback_captured_type_is_reanalyzed_after_later_rebind(self):
        value = plan(PREFIX + """
            算 外造:
                型 取 密 其 i32.
                算 回 值:
                    S 取 密 其 签名 型 ([]) 'cdecl'.
                    得 0.
                法
                签 取 密 其 签名 (密 其 i32) ([密 其 i32]) 'cdecl'.
                回调 取 密 其 回调 签 (算 回) 0.
                型 取 密 其 f64.
                得 回调.
            法
            回调 取 外造.
        """)
        self.assertIn(NativeCSignature('f64', ()), value.signatures)

    def test_repeated_helper_fanout_and_loops_have_bounded_static_work(self):
        # A generic fixed-ABI graph: repeated scalar helpers have no reason to
        # rediscover the same bodies exponentially. This is independently
        # generated test data, not an application source fixture.
        source = PREFIX + """
            签甲 取 密 其 签名 (密 其 i32) ([密 其 i32]) 'cdecl'.
            签乙 取 密 其 签名 (密 其 无值) ([密 其 指针, 密 其 f64]) 'win64'.
            算 层0 值: 得 值 + 1. 法
        """
        for level in range(1, 9):
            source += f'算 层{level} 值: 循 3 次\n'
            for branch in range(4):
                source += f'局{branch} 取 层{level - 1} 值.\n'
            source += '环 得 局0. 法\n'
        source += '循 10 次 层8 7. 层8 7. 环'
        first, second = plan(source), plan(source)
        self.assertEqual(first.signatures, (
            NativeCSignature('i32', ('i32',)),
            NativeCSignature('无值', ('指针', 'f64'))))
        self.assertEqual(first.signatures, second.signatures)
        self.assertEqual(first._steps, second._steps)
        self.assertEqual(first._function_evaluations, second._function_evaluations)
        self.assertGreater(first._summary_hits, 0)
        self.assertLess(first._steps, 5000)
        self.assertLess(first._function_evaluations, 500)
        generated = first.emit_c()
        self.assertIn('if (result == 5 && argc == 1 && params != NULL && params[0] == 5) return 0;', generated)
        self.assertIn('if (result == 0 && argc == 2 && params != NULL && params[0] == 13 && params[1] == 12) return 1;', generated)

    def test_cached_capture_read_is_invalidated_by_rebinding(self):
        value = plan(PREFIX + """
            算 外:
                型 取 密 其 i32.
                算 取型: 得 型. 法
                算 改型: 型 取 密 其 f64. 得 空. 法
                取型. 取型. 取型.
                改型.
                得 密 其 签名 (取型) ([]) 'cdecl'.
            法
            外.
        """)
        self.assertEqual(set(value.signatures), {
            NativeCSignature('i32', ()), NativeCSignature('f64', ())})
        self.assertGreater(value._summary_hits, 0)

    def test_unrelated_local_writes_do_not_restart_shared_helper_graph(self):
        # Each caller creates its own local cells/arrays, but all callers use
        # the same helper contexts. A global invalidation stamp repeats the
        # whole graph after every unrelated write and exceeds the normal cap.
        source = PREFIX + """
            S 取 密 其 签名 (密 其 i32) ([密 其 f64]) 'cdecl'.
            算 层0 值: 得 值 + 1. 法
        """
        for level in range(1, 40):
            source += f'算 层{level} 值: ' + f'层{level - 1} 值. ' * 7
            source += f'得 层{level - 1} 值. 法\n'
        for caller in range(100):
            source += f'算 调用{caller}: '
            for branch in range(4):
                source += f'局{branch} 取 [{branch}]. 层39 7. '
            source += '得 0. 法\n'
        source += '算 入口: ' + ' '.join(f'调用{i}.' for i in range(100)) + ' 得 0. 法 入口.'
        first, second = plan(source), plan(source)
        self.assertEqual(first.signatures, (NativeCSignature('i32', ('f64',)),))
        self.assertEqual(first.signatures, second.signatures)
        self.assertEqual(first._steps, second._steps)
        self.assertEqual(first._function_evaluations, second._function_evaluations)
        self.assertLess(first._steps, 30000)
        self.assertLess(first._function_evaluations, 1000)

    def test_dependency_overflow_propagates_through_cached_children(self):
        source = PREFIX + """
            S 取 密 其 签名 (密 其 i32) ([]) 'cdecl'.
            算 叶 值: 得 值 + 1. 法
            算 枝 值: 得 叶 值. 法
            算 树 值: 得 枝 值. 法
            树 7. 树 7. 树 7. 树 7.
        """
        expected = plan(source).signatures
        with patch('rulang.native_c.MAX_SUMMARY_DEPENDENCIES', 3):
            value = plan(source)
        self.assertEqual(value.signatures, expected)
        self.assertTrue(all(len(summary[0]) <= 3 for summary in value._call_summaries.values()))
        branch = next(fn for fn in value._functions if fn.node.data.get('name') == '枝')
        root = next(fn for fn in value._functions if fn.node.data.get('name') == '树')
        cached_nodes = {key[0][1] for key in value._call_summaries}
        self.assertIn(id(branch.node), cached_nodes)
        # Own scope + module + branch scope + leaf scope cannot fit. The leaf
        # dependency must propagate even when the branch itself was a hit.
        self.assertNotIn(id(root.node), cached_nodes)

    def test_cached_transitive_footprint_cannot_bypass_active_recursion(self):
        value = plan(PREFIX + """
            算 叶: 得 密 其 i32. 法
            算 枝: 得 叶. 法
            算 树: 得 枝. 法
            树. 树. 树. 树.
        """)
        leaf = next(fn for fn in value._functions if fn.node.data.get('name') == '叶')
        root = next(fn for fn in value._functions if fn.node.data.get('name') == '树')
        self.assertIn(id(root.node), {key[0][1] for key in value._call_summaries})
        value._active.add(id(leaf.node))
        try:
            with self.assertRaisesRegex(RuError, '无法证明此递归路径'):
                value._invoke(root, [], root.node)
        finally:
            value._active.remove(id(leaf.node))

    def test_dependency_cache_matches_analysis_without_summary_hits(self):
        class WithoutSummaryHits(NativeCPlan):
            def _invoke(self, function, args, node):
                self._call_summaries.clear()
                return super()._invoke(function, args, node)

        cases = {
            'missing_parent_binding': ("""
                算 外:
                    算 取型: 得 型. 法
                    取型. 取型. 取型.
                    型 取 密 其 i32.
                    得 密 其 签名 (取型) ([]) 'cdecl'.
                法 外.
            """, {NativeCSignature('i32', ())}),
            'nested_cached_capture': ("""
                算 外:
                    型 取 密 其 i32.
                    算 叶: 得 型. 法
                    算 枝: 得 叶. 法
                    枝. 枝. 枝.
                    型 取 密 其 f64.
                    得 密 其 签名 (枝) ([]) 'cdecl'.
                法 外.
            """, {NativeCSignature('i32', ()), NativeCSignature('f64', ())}),
            'nested_cached_array': ("""
                参数们 取 [密 其 i32].
                算 叶: 得 参数们[0]. 法
                算 枝: 得 叶. 法
                枝. 枝. 枝. 参数们 其 增 (密 其 f64).
                S 取 密 其 签名 (枝) ([]) 'cdecl'.
            """, None),
            'returned_closure_array': ("""
                算 造:
                    参数们 取 [密 其 i32].
                    算 首: 得 参数们[0]. 法
                    得 [算 首, 参数们].
                法
                包 取 造. F 取 包[0]. 参数们 取 包[1].
                算 用: 得 F(). 法
                用. 用. 用. 参数们 其 增 (密 其 f64).
                S 取 密 其 签名 (用) ([]) 'cdecl'.
            """, None),
            'opaque_alias_gains_child': ("""
                算 外:
                    甲 取 [密 其 i32]. 乙 取 [密 其 f64]. 当前 取 甲.
                    算 包: 得 当前 对 0. 法
                    算 触碰 值: 未知 值. 得 空. 法
                    袋 取 包. 触碰 袋. 触碰 袋. 触碰 袋.
                    当前 取 乙. 包. 触碰 袋.
                    得 密 其 签名 (密 其 i32) 乙 'cdecl'.
                法 外.
            """, None),
            'late_callback_capture': ("""
                算 外:
                    型 取 密 其 i32.
                    算 回 值: S 取 密 其 签名 型 ([]) 'cdecl'. 得 0. 法
                    回 0. 回 0. 回 0.
                    签 取 密 其 签名 (密 其 i32) ([密 其 i32]) 'cdecl'.
                    回调 取 密 其 回调 签 (算 回) 0.
                    型 取 密 其 f64. 得 回调.
                法 外.
            """, {NativeCSignature('i32', ()), NativeCSignature('f64', ()),
                  NativeCSignature('i32', ('i32',))}),
            'read_before_write': ("""
                算 外:
                    型 取 密 其 i32.
                    算 读后改: 旧 取 型. 型 取 密 其 f64. 得 旧. 法
                    读后改. 得 密 其 签名 (读后改) ([]) 'cdecl'.
                法 外.
            """, {NativeCSignature('i32', ()), NativeCSignature('f64', ())}),
            'unknown_callable_escape': ("""
                算 外:
                    型 取 密 其 i32.
                    算 取型: 得 型. 法
                    算 改型: 型 取 密 其 f64. 得 空. 法
                    F 取 算 改型. 取型. 取型. 取型. 未知 F.
                    得 密 其 签名 (取型) ([]) 'cdecl'.
                法 外.
            """, {NativeCSignature('i32', ()), NativeCSignature('f64', ())}),
        }
        for name, (source, expected) in cases.items():
            with self.subTest(case=name):
                outcomes = []
                for plan_type in (NativeCPlan, WithoutSummaryHits):
                    graph = load_module_graph('/tmp/native_dependency_' + name + '.ru', parse(PREFIX + source))
                    try:
                        value = plan_type(graph)
                    except RuError as error:
                        self.assertIsNone(expected, error.message)
                        self.assertEqual(error.category, '原生编译错误')
                        self.assertIn('无法静态确定', error.message)
                        outcomes.append((error.category, error.message))
                    else:
                        self.assertIsNotNone(expected)
                        self.assertEqual(set(value.signatures), expected)
                        outcomes.append((value.signatures, value.callback_signatures))
                self.assertEqual(outcomes[0], outcomes[1])

    def test_reused_local_cannot_hide_a_later_capture_target(self):
        cases = {
            'write': """
                算 外:
                    算 改:
                        型 取 密 其 f64.
                        得 空.
                    法
                    改. 改. 改.
                    型 取 密 其 i32.
                    改.
                    得 密 其 签名 型 ([]) 'cdecl'.
                法 外.
            """,
            'read_before_write': """
                型 取 密 其 i32.
                算 外:
                    算 改:
                        旧 取 型.
                        型 取 密 其 f64.
                        得 旧.
                    法
                    改. 改. 改.
                    型 取 密 其 u8.
                    得 密 其 签名 (改) ([]) 'cdecl'.
                法 外.
            """,
            'warmed_transitive_caller': """
                算 外:
                    算 改:
                        型 取 密 其 f64.
                        得 空.
                    法
                    算 枝: 得 改. 法
                    枝. 枝. 枝.
                    型 取 密 其 i32.
                    枝.
                    得 密 其 签名 型 ([]) 'cdecl'.
                法 外.
            """,
        }
        for name, body in cases.items():
            source = PREFIX + body
            with self.subTest(case=name), self.assertRaisesRegex(
                    RuError, '随调用改变的捕获绑定「型」') as caught:
                plan(source)
            self.assertEqual(caught.exception.category, '原生编译错误')
            self.assertEqual(caught.exception.source_name, str(Path('/tmp/native_c_plan.ru').resolve()))
            self.assertEqual(caught.exception.line, next(
                index for index, line in enumerate(source.splitlines(), 1)
                if '型 取 密 其 f64.' in line))
            self.assertIn('首次调用前初始化外层同名变量', caught.exception.message)

    def test_stable_capture_and_guaranteed_local_shadows_remain_supported(self):
        cases = [
            ("""
                算 外:
                    型 取 密 其 i32.
                    算 改: 型 取 密 其 f64. 得 空. 法
                    改. 改. 改.
                    得 密 其 签名 型 ([]) 'cdecl'.
                法 外.
            """, {NativeCSignature('i32', ()), NativeCSignature('f64', ())}),
            ("""
                算 外:
                    算 用 型: 得 型. 法
                    用 (密 其 i32). 用 (密 其 i32). 用 (密 其 i32).
                    型 取 密 其 f64.
                    得 密 其 签名 (用 (密 其 i32)) ([]) 'cdecl'.
                法 外.
            """, {NativeCSignature('i32', ())}),
            ("""
                算 外:
                    算 用:
                        算 型: 得 密 其 f64. 法
                        得 型.
                    法
                    用. 用. 用.
                    型 取 密 其 i32.
                    得 密 其 签名 (用) ([]) 'cdecl'.
                法 外.
            """, {NativeCSignature('f64', ())}),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(set(plan(PREFIX + source).signatures), expected)

    def test_reused_scopes_retain_possible_ancestor_reads(self):
        class WithoutSummaryHits(NativeCPlan):
            def _invoke(self, function, args, node):
                self._call_summaries.clear()
                return super()._invoke(function, args, node)

        cases = {
            'block': """
                型 取 密 其 i32.
                循 2 次
                    段:
                        S 取 密 其 签名 型 ([]) 'cdecl'.
                        型 取 密 其 f64.
                    落.
                    型 取 密 其 u8.
                环
            """,
            'delayed_first_read': """
                算 外:
                    型 取 密 其 i32.
                    算 忽略 回: 得 密 其 i32. 法
                    算 调用 回: 得 回(). 法
                    F 取 算 忽略.
                    循 2 次
                        段:
                            算 G: 得 型. 法
                            S 取 密 其 签名 (F (算 G)) ([]) 'cdecl'.
                            型 取 密 其 f64.
                        落.
                        F 取 算 调用. 型 取 密 其 u8.
                    环
                    得 空.
                法 外.
            """,
            'function_module_read': """
                型 取 密 其 i32.
                算 F:
                    S 取 密 其 签名 型 ([]) 'cdecl'.
                    型 取 密 其 f64. 得 空.
                法
                F. 型 取 密 其 u8. F.
            """,
            'conditional_local': """
                型 取 密 其 i32.
                算 F 条件:
                    若 条件 则 型 取 密 其 f64. 然
                    得 密 其 签名 型 ([]) 'cdecl'.
                法
                F 真. 型 取 密 其 u8. F 假.
            """,
            'zero_iteration_local': """
                型 取 密 其 i32.
                算 F:
                    循 0 次 型 取 密 其 f64. 环
                    得 密 其 签名 型 ([]) 'cdecl'.
                法
                F. 型 取 密 其 u8. F.
            """,
            'rescue': """
                型 取 密 其 i32.
                循 2 次
                    试 卒 'x'.
                    救 原因
                        S 取 密 其 签名 型 ([]) 'cdecl'.
                        型 取 密 其 f64.
                    终
                    型 取 密 其 u8.
                环
            """,
        }
        expected = {NativeCSignature(name, ()) for name in ('i32', 'f64', 'u8')}
        for name, source in cases.items():
            with self.subTest(case=name):
                outcomes = []
                for plan_type in (NativeCPlan, WithoutSummaryHits):
                    graph = load_module_graph('/tmp/native_scope_' + name + '.ru', parse(PREFIX + source))
                    value = plan_type(graph)
                    self.assertEqual(set(value.signatures), expected)
                    outcomes.append((value.signatures, value.callback_signatures))
                self.assertEqual(outcomes[0], outcomes[1])

    def test_late_ancestor_read_keeps_mutable_array_alias(self):
        with self.assertRaisesRegex(RuError, '无法静态确定'):
            plan(PREFIX + """
                参数们 取 [密 其 i32].
                算 忽略 回: 得 []. 法
                算 调用 回: 得 回(). 法
                F 取 算 忽略.
                循 2 次
                    段:
                        算 G: 得 参数们. 法
                        S 取 密 其 签名 (密 其 i32) (F (算 G)) 'cdecl'.
                        参数们 取 [密 其 f64].
                    落.
                    F 取 算 调用. 参数们 其 增 (密 其 u8).
                环
            """)

    def test_scope_entry_shadows_and_bind_first_blocks_remain_supported(self):
        value = plan(PREFIX + """
            型 取 密 其 i32.
            原因 取 [密 其 i32].
            循 2 次
                段:
                    型 取 密 其 f64.
                    S 取 密 其 签名 型 ([]) 'cdecl'.
                落.
                段:
                    算 型: 得 密 其 u8. 法
                    S 取 密 其 签名 (型) ([]) 'cdecl'.
                落.
                试 卒 'x'. 救 原因 未知 原因. 终
            环
            T 取 密 其 签名 (密 其 i32) 原因 'cdecl'.
        """)
        self.assertEqual(set(value.signatures), {
            NativeCSignature('i32', ()), NativeCSignature('f64', ()),
            NativeCSignature('u8', ()), NativeCSignature('i32', ('i32',))})

    def test_reused_local_preserves_implicit_native_root_binding(self):
        # The planner only creates abstract library values here; no DLL loads.
        value = plan("""
            型 取 __密 其 类型 'i32'.
            算 F:
                S 取 __密 其 签名 型 ([]) 'cdecl'.
                __密 取 __密 其 系统库 'unused.dll'.
                得 空.
            法
            F. 型 取 __密 其 类型 'u8'. F.
        """)
        self.assertEqual(set(value.signatures), {
            NativeCSignature('i32', ()), NativeCSignature('u8', ())})

    def test_implicit_calls_in_ancestor_choices_keep_declared_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'dep.ru').write_text(PREFIX + """
                参数们 取 [密 其 i32].
                算 调整:
                    得 密 其 签名 (参数们[0]) ([]) 'cdecl'.
                法
            """, encoding='utf-8')
            # Imported declarations can share a name with an ordinary local.
            # On the later fresh call, its zero-arg invocation must still run.
            with self.assertRaisesRegex(RuError, '无法静态确定'):
                plan("""
                    尽取 外言 './dep.ru'.
                    算 F: 调整. 调整 取 0. 得 空. 法
                    F. 参数们[0] 取 密 其 f64. F.
                """, str(root / 'main.ru'))
            (root / 'wrapper.ru').write_text("""
                尽取 外言 './dep.ru'.
                调整. 调整 取 0.
            """, encoding='utf-8')
            prefix = """
                M 取 外言 './wrapper.ru'.
                参数们 取 M 其 参数们.
                参数们[0] 取 __密 其 类型 'f64'.
            """
            with self.assertRaisesRegex(RuError, '无法静态确定'):
                plan(prefix + 'M 其 调整.', str(root / 'main.ru'))
            # Taking a reference must not implicitly call either candidate.
            value = plan(prefix + 'F 取 算 M 其 调整.', str(root / 'main.ru'))
            self.assertEqual(value.signatures, (NativeCSignature('i32', ()),))

    def test_changing_body_is_not_cached_at_its_exit_revision(self):
        value = plan(PREFIX + """
            算 外:
                型 取 密 其 i32.
                算 读后改:
                    旧 取 型.
                    型 取 密 其 f64.
                    得 旧.
                法
                读后改.
                得 密 其 签名 (读后改) ([]) 'cdecl'.
            法
            外.
        """)
        self.assertEqual(set(value.signatures), {
            NativeCSignature('i32', ()), NativeCSignature('f64', ())})

    def test_cached_array_projection_is_invalidated_by_alias_mutation(self):
        for mutation in ("别名 其 增 (密 其 f64).", "别名[0] 取 密 其 f64."):
            with self.subTest(mutation=mutation), self.assertRaisesRegex(RuError, '无法静态确定'):
                plan(PREFIX + """
                    算 首 参数: 得 参数[0]. 法
                    参数们 取 [密 其 i32]. 别名 取 参数们.
                    首 参数们. 首 参数们. 首 参数们.
                """ + mutation + "S 取 密 其 签名 (首 参数们) ([]) 'cdecl'.")

    def test_cached_callback_is_revisited_after_late_capture_change(self):
        value = plan(PREFIX + """
            算 外:
                型 取 密 其 i32.
                算 回 值:
                    S 取 密 其 签名 型 ([]) 'cdecl'.
                    得 0.
                法
                回 0. 回 0. 回 0.
                签 取 密 其 签名 (密 其 i32) ([密 其 i32]) 'cdecl'.
                回调 取 密 其 回调 签 (算 回) 0.
                型 取 密 其 f64.
                得 回调.
            法
            外.
        """)
        self.assertIn(NativeCSignature('f64', ()), value.signatures)
        self.assertEqual(value.callback_signatures, {NativeCSignature('i32', ('i32',))})
        self.assertGreater(value._summary_hits, 0)

    def test_cached_array_return_does_not_hide_late_method_effects(self):
        with self.assertRaisesRegex(RuError, '无法静态确定'):
            plan(PREFIX + """
                参数们 取 [密 其 i32].
                算 参数列: 得 参数们. 法
                参数列. 参数列. 参数列.
                形 工具:
                    算 同 对方: 参数们 其 增 (密 其 f64). 得 真. 法
                象
                签 取 密 其 签名 (密 其 i32) (参数列) 'cdecl'.
            """)

    def test_unknown_callable_escape_invalidates_cached_capture_read(self):
        value = plan(PREFIX + """
            算 外:
                型 取 密 其 i32.
                算 取型: 得 型. 法
                算 改型: 型 取 密 其 f64. 得 空. 法
                F 取 算 改型.
                取型. 取型. 取型.
                未知 F.
                得 密 其 签名 (取型) ([]) 'cdecl'.
            法
            外.
        """)
        self.assertIn(NativeCSignature('f64', ()), value.signatures)
        self.assertGreater(value._summary_hits, 0)

    def test_unknown_escape_rechecks_cached_signature_constructor(self):
        with self.assertRaisesRegex(RuError, '无法静态确定'):
            plan(PREFIX + """
                算 造 型: 得 密 其 签名 型 ([]) 'cdecl'. 法
                F 取 算 造.
                F (密 其 i32). F (密 其 i32). F (密 其 i32).
                未知 F.
            """)

    def test_call_summary_eviction_is_bounded_and_semantics_preserving(self):
        source = PREFIX + """
            算 取型 型: 得 型. 法
            取型 (密 其 i32). 取型 (密 其 i32).
            取型 (密 其 f64). 取型 (密 其 f64).
            取型 (密 其 u8). 取型 (密 其 u8).
            S 取 密 其 签名 (取型 (密 其 i32)) ([]) 'cdecl'.
            T 取 密 其 签名 (取型 (密 其 f64)) ([]) 'cdecl'.
        """
        expected = plan(source).signatures
        with patch('rulang.native_c.MAX_CALL_SUMMARIES', 2):
            value = plan(source)
        self.assertLessEqual(len(value._call_summaries), 2)
        self.assertEqual(value.signatures, expected)

    def test_large_summary_footprints_are_not_cached_or_truncated(self):
        source = PREFIX + """
            S 取 密 其 签名 (密 其 i32) ([]) 'cdecl'.
            算 叶 值: 得 值 + 1. 法
            算 枝 值: 得 叶 值. 法
            算 树 值: 得 枝 值. 法
            树 7. 树 7. 树 7. 树 7.
        """
        expected = plan(source).signatures
        with patch('rulang.native_c.MAX_SUMMARY_FUNCTIONS', 2):
            value = plan(source)
        self.assertEqual(value.signatures, expected)
        self.assertGreater(value._summary_hits, 0)
        self.assertTrue(all(len(summary[2]) <= 2 for summary in value._call_summaries.values()))
        root = next(fn for fn in value._functions if fn.node.data.get('name') == '树')
        branch = next(fn for fn in value._functions if fn.node.data.get('name') == '枝')
        cached_nodes = {key[0][1] for key in value._call_summaries}
        self.assertIn(id(branch.node), cached_nodes)
        # The cached branch's leaf dependency must propagate into the parent;
        # truncating it would incorrectly allow the three-function root entry.
        self.assertNotIn(id(root.node), cached_nodes)

    def test_generated_platform_guard_excludes_arm64ec(self):
        source = plan(PREFIX).emit_c()
        self.assertIn('defined(_M_ARM64)', source)
        self.assertIn('defined(_M_ARM64EC)', source)

    def test_unrelated_same_named_members_do_not_need_native_resolution(self):
        value = plan("""
            形 工具:
                算 签名 返回 参数 约定: 得 返回. 法
            象
            T 取 新 工具.
            显 T 其 签名 1 2 3.
        """)
        self.assertFalse(value.signatures)


@unittest.skipUnless(shutil.which('cc'), 'a C compiler is required')
class NativeCThunkTests(unittest.TestCase):
    def test_exact_mixed_calls_and_callback_tables_compile_and_run(self):
        # A host C smoke test checks emitted prototypes and bit preservation.
        # It is not a substitute for the Windows x64 integration suite.
        value = plan(PREFIX + """
            S 取 密 其 签名 (密 其 f64) ([密 其 i8,密 其 u64,密 其 f32,密 其 f64,密 其 指针]) 'cdecl'.
            T 取 密 其 签名 (密 其 无值) ([]) 'win64'.
            F 取 算 甲 乙 丙 丁 戊: 得 0. 法.
            C 取 密 其 回调 S F 0.
        """)
        before = r'''
#define _WIN32 1
#include <stdint.h>
#include <stddef.h>
#include <assert.h>
typedef union RuNativeRaw { int64_t i; uint64_t u; float f32; double f64; void *p; } RuNativeRaw;
static int marker;
static double mixed(int8_t a, uint64_t b, float c, double d, void *p) {
    assert(a == -17 && b == UINT64_MAX && c == 1.25f && d == 2.5 && p == &marker);
    return 3.75;
}
static void empty(void) { marker = 9; }
static RuNativeRaw ru_native_callback_dispatch(unsigned slot, int signature, const RuNativeRaw *args) {
    RuNativeRaw result = {0};
    assert(slot == 1023 && signature == 0);
    result.f64 = mixed((int8_t)args[0].i, args[1].u, args[2].f32, args[3].f64, args[4].p);
    return result;
}
'''
        after = r'''
int main(void) {
    RuNativeRaw args[5] = {{0}}, result;
    int params[] = {1, 8, 11, 12, 13};
    union { void *p; double (*f)(int8_t,uint64_t,float,double,void *); } target;
    union { void *p; void (*f)(void); } target_void;
    args[0].i = -17; args[1].u = UINT64_MAX; args[2].f32 = 1.25f; args[3].f64 = 2.5; args[4].p = &marker;
    assert(ru_native_generated_signature(12,5,params,0) == 0);
    assert(ru_native_generated_signature(12,5,params,1) == 0);
    assert(ru_native_generated_signature(12,5,params,2) == -1);
    assert(ru_native_generated_signature(12,5,NULL,0) == -1);
    target.f = mixed;
    result = ru_native_generated_call(0,target.p,args);
    assert(result.f64 == 3.75);
    target.p = ru_native_generated_callback(0,1023);
    assert(target.f(-17,UINT64_MAX,1.25f,2.5,&marker) == 3.75);
    assert(ru_native_generated_callback(0,1024) == NULL);
    assert(ru_native_generated_callback(1,0) == NULL);
    target_void.f = empty;
    result = ru_native_generated_call(1,target_void.p,NULL);
    assert(marker == 9 && result.u == 0);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source, executable = Path(directory) / 'test.c', Path(directory) / 'test'
            source.write_text(before + value.emit_c() + after, encoding='utf-8')
            subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-Wstrict-prototypes',
                            '-pedantic', str(source), '-o', str(executable)], check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
