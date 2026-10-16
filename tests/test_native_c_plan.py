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
