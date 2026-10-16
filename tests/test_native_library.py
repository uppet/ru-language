"""Native bridge boundaries and a locally compiled, repository-owned C fixture.

Portable ABI tests inject the supported-host predicate, never enabling native
execution for actual Linux/ARM users. Windows CLI integration remains separate.
"""
import ctypes as C
from dataclasses import FrozenInstanceError
import gc
import functools
import time
from types import SimpleNamespace
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import weakref

from rulang import native_runtime as N
from rulang.browser_compiler import browser_graph
from rulang.cli import make_parser
from rulang.compiler import Compiler
from rulang.frontend import parse, RuError
from rulang.interpreter import Interpreter
from rulang.js_compiler import JSCompiler
from rulang.modules import ModuleGraph, load_module_graph, resolve_import

ROOT = Path(__file__).resolve().parents[1]
IMPORT = "密 取 外言 '如:密'. "


class NativePermissionsTests(unittest.TestCase):
    def test_default_denies_direct_hidden_dormant_and_import_before_output(self):
        for code in ("显 'side effect'. 外言 '如:密'.", "显 'side effect'. 若 不实 则 外言 '如:密'. 然", "显 'side effect'. 别名 取 __密. 别名 其 类型 'u64'."):
            with self.subTest(code=code):
                output = io.StringIO()
                with self.assertRaisesRegex(RuError, '原生能力默认关闭'):
                    Interpreter(stdout=output).execute(parse(code))
                self.assertEqual(output.getvalue(), '')

    def test_transitive_local_alias_denied_before_side_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'main.ru'
            dep = Path(directory) / 'dep.ru'
            dep.write_text("外言 '如:密'.", encoding='utf-8')
            output = io.StringIO()
            with self.assertRaisesRegex(RuError, '原生能力默认关闭'):
                Interpreter(stdout=output).execute(parse("显 'bad'. 外言 './dep.ru'."), source_path=root)
            self.assertEqual(output.getvalue(), '')

    def test_unsupported_platform_has_clear_error(self):
        with patch.object(N, '_supported', return_value=False):
            with self.assertRaisesRegex(RuError, 'Windows x64'):
                Interpreter(allow_native=True).execute(parse(IMPORT))

    def test_frozen_capability_and_rushu_default(self):
        context = Interpreter()._native_context
        with self.assertRaises(FrozenInstanceError):
            context.capability.allowed = True
        with self.assertRaises(AttributeError):
            context.capability = N.NativeCapability(True)
        from rushu.kernel import Session
        kernel = Session()
        self.addCleanup(kernel.close)
        kernel.execute("显 'must not execute'. 外言 '如:密'.", 'native-deny')
        after, events, deadline = 0, [], time.monotonic() + 15
        while time.monotonic() < deadline:
            result = kernel.poll(after)
            events.extend(result['events'])
            after = result['cursor']
            if result['state'] == 'idle' and events:
                break
            time.sleep(0.02)
        self.assertTrue(any('原生能力默认关闭' in event.get('message', '') for event in events), events)
        self.assertFalse(any(event.get('type') == 'output' for event in events))

    def test_compilers_reject_dormant_import_and_hidden_alias(self):
        for code in (IMPORT, "若 不实 则 原生 取 __密. 然"):
            for compiler in (Compiler, JSCompiler):
                with self.subTest(compiler=compiler, code=code):
                    with self.assertRaisesRegex(RuError, '不支持'):
                        compiler(parse(code), str(ROOT / 'unused.ru')).compile()
            with self.assertRaises(RuError):
                browser_graph(code)

    def test_cli_option_does_not_read_program_args_as_capability(self):
        args = make_parser().parse_args(['run', '--allow-native', 'test.ru'])
        self.assertTrue(args.allow_native)
        args = make_parser().parse_args(['run', 'test.ru', '--allow-native'])
        self.assertFalse(args.allow_native)
        self.assertEqual(args.args, ['--allow-native'])
        args = make_parser().parse_args(['generate', 'intent.txt', '--run'])
        self.assertFalse(hasattr(args, 'allow_native'))

    def test_python_check_never_loads_or_executes_dll(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'check.ru'
            path.write_text(IMPORT + "库 取 密 其 系统库 'does-not-exist.dll'. 卒 'must not execute'.", encoding='utf-8')
            result = subprocess.run([sys.executable, str(ROOT / 'ru'), 'check', '--target', 'python', str(path)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('未执行代码或加载 DLL', result.stdout)
            result = subprocess.run([sys.executable, str(ROOT / 'ru'), 'check', str(path)], capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)

    def test_context_retains_thread_object_identity_not_reusable_ident(self):
        with patch.object(N, '_supported', return_value=True):
            context = N.NativeContext(N.NativeCapability(True))
            self.assertIs(context.thread, threading.current_thread())
            with patch.object(threading, 'current_thread', return_value=object()):
                with self.assertRaisesRegex(N.NativeFault, '所属解释器线程'):
                    context.check()

    def test_imported_context_is_identical(self):
        with patch.object(N, '_supported', return_value=True):
            owner = Interpreter(allow_native=True)
            owner.execute(parse(IMPORT))
            module = owner.global_scope.values['密']
            self.assertIs(module.interpreter._native_context, owner._native_context)
            denied = Interpreter()
            with self.assertRaisesRegex(RuError, '默认关闭'):
                denied.execute(parse(IMPORT), module_cache=owner.module_cache)

    def test_enabled_contexts_cannot_share_cache_or_native_arguments(self):
        with patch.object(N, '_supported', return_value=True):
            first, second = Interpreter(allow_native=True), Interpreter(allow_native=True)
            first.execute(parse(IMPORT + "原值 取 (密 其 u64) 其 值 7."))
            with self.assertRaisesRegex(RuError, '能力上下文'):
                second.execute(parse(IMPORT), module_cache=first.module_cache)
            second = Interpreter(allow_native=True)
            second.execute(parse(IMPORT))
            second.global_scope.values['外来'] = first.global_scope.values['原值']
            with self.assertRaisesRegex(RuError, '跨解释器'):
                second.execute(parse('显 外来 其 句.'))
            with self.assertRaisesRegex(RuError, '跨解释器'):
                second.execute(parse('(密 其 u64) 其 值 外来.'))

    def test_supplied_graph_cannot_hide_native_root_preflight(self):
        graph = ModuleGraph(str(ROOT / 'native-root.ru'))
        graph[str(ROOT / 'benign-module.ru')] = parse('值 取 1.')
        output = io.StringIO()
        with self.assertRaisesRegex(RuError, '原生能力默认关闭'):
            Interpreter(stdout=output).execute(parse("显 'SIDE EFFECT'. __密 其 类型 'u8'."), modules=graph)
        self.assertEqual(output.getvalue(), '')
        for compiler in (Compiler, JSCompiler):
            with self.subTest(compiler=compiler):
                with self.assertRaisesRegex(RuError, '不支持'):
                    compiler(parse('别名 取 __密.'), str(ROOT / 'native-root.ru'), modules=graph).compile()

    def test_exported_functions_and_methods_cannot_cross_enabled_context(self):
        with patch.object(N, '_supported', return_value=True):
            enabled = Interpreter(allow_native=True)
            enabled.execute(parse(IMPORT + "算 值算: 得 ((密 其 u64) 其 值 42) 其 数. 法 形 主体: 算 值法: 得 42. 法 象 实例 取 新 主体."))
            for allow in (False, True):
                consumer = Interpreter(allow_native=allow, stdout=io.StringIO())
                consumer.global_scope.values['外算'] = enabled.function_values['值算']
                consumer.global_scope.values['外形'] = enabled.global_scope.values['实例']
                for source in ('显 外算().', '显 外形 其 值法.'):
                    with self.subTest(allow=allow, source=source):
                        with self.assertRaisesRegex(RuError, '跨原生能力上下文'):
                            consumer.execute(parse(source))
                self.assertEqual(consumer.stdout.getvalue(), '')
            ordinary = Interpreter()
            ordinary.execute(parse('算 值算: 得 42. 法'))
            consumer = Interpreter(stdout=io.StringIO())
            consumer.global_scope.values['外算'] = ordinary.function_values['值算']
            consumer.execute(parse('显 外算().'))
            self.assertEqual(consumer.stdout.getvalue(), '42\n')

    def test_bundled_package_can_be_copied_without_repository_root(self):
        with tempfile.TemporaryDirectory() as directory:
            shutil.copytree(ROOT / 'rulang', Path(directory) / 'rulang', ignore=shutil.ignore_patterns('__pycache__'))
            result = subprocess.run([sys.executable, '-c', "from rulang.modules import load_module_graph; from rulang.frontend import parse; g=load_module_graph('test.ru',parse(\"外言 '如见'.\")); print(len(g))"], cwd=directory, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertGreaterEqual(int(result.stdout), 3)


class NativeValueTests(unittest.TestCase):
    def setUp(self):
        self.supported = patch.object(N, '_supported', return_value=True)
        self.supported.start()
        self.addCleanup(self.supported.stop)
        self.output = io.StringIO()
        self.owner = Interpreter(allow_native=True, stdout=self.output)
        self.owner.execute(parse(IMPORT))

    def run_ru(self, source):
        self.owner.execute(parse(source))
        return self.output.getvalue()

    def test_exact_integer_and_pointer_roundtrip(self):
        output = self.run_ru("大值 取 (密 其 u64) 其 值 '18446744073709551615'. 显 大值 其 句. 有号 取 (密 其 intptr) 其 重释 大值. 显 有号 其 句. 指 取 (密 其 指针) 其 重释 有号. 显 指 其 句. 显 指 其 位段 0 16.")
        self.assertEqual(output, '18446744073709551615\n-1\n18446744073709551615\n65535\n')
        with self.assertRaisesRegex(RuError, '安全整数'):
            self.run_ru('显 大值 其 数.')

    def test_overflow_fraction_nan_and_implicit_pointer_rejected(self):
        for descriptor, value in [('i8', 128.0), ('u8', -1.0), ('u64', '18446744073709551616'), ('i64', '-9223372036854775809'), ('u64', 9007199254740992.0), ('i32', 1.5), ('f32', 1e300), ('f64', float('nan'))]:
            with self.subTest(descriptor=descriptor, value=value):
                with self.assertRaises(N.NativeFault):
                    N._convert(N.PRIMITIVES[descriptor], value)
        with self.assertRaisesRegex(N.NativeFault, '指针参数'):
            N._marshal(N.PRIMITIVES['指针'], 123.0)
        with self.assertRaisesRegex(N.NativeFault, '等宽'):
            N._convert(N.PRIMITIVES['i32'], N.NativeScalar(N.PRIMITIVES['u64'], 1), True)

    def test_struct_layout_zero_fields_and_owned_views(self):
        self.assertEqual(self.run_ru("点型 取 密 其 结构 ([['x',密 其 i32],['y',密 其 i32]]). 记录型 取 密 其 结构 ([['small',密 其 u8],['large',密 其 u64],['point',点型]]). 显 记录型 其 大小. 显 记录型 其 对齐. 显 记录型 其 偏移 'large'. 记录 取 记录型 其 新建. 显 (记录 其 读 'large') 其 句. 点 取 记录 其 读 'point'. 点 其 写 'x' 23. 显 ((记录 其 读 'point') 其 读 'x') 其 数. 记录 其 关闭."), '24\n8\n8\n0\n23\n')
        with self.assertRaisesRegex(RuError, '缓冲已关闭'):
            self.run_ru("点 其 读 'x'.")

    def test_utf_and_buffer_closed_pointer(self):
        self.assertEqual(self.run_ru("文甲 取 密 其 UTF8 '你好😀'. 文乙 取 密 其 UTF16 '你好😀'. 显 文甲 其 解UTF8. 显 文乙 其 解UTF16. 指甲 取 文甲 其 地址. 文甲 其 关闭."), '你好😀\n你好😀\n')
        with self.assertRaisesRegex(RuError, '关闭'):
            self.run_ru('显 指甲 其 句.')
        with self.assertRaisesRegex(RuError, 'NUL'):
            self.owner.global_scope.values["零文"] = "a\0b"
            self.run_ru("密 其 UTF16 零文.")
        with self.assertRaisesRegex(RuError, '未知原生成员'):
            self.run_ru("指 取 (密 其 指针) 其 值 '4096'. 指 其 读.")

    def test_nested_struct_pointer_anchors_survive_view_gc_and_copy(self):
        self.run_ru("内型 取 密 其 结构 ([['p',密 其 指针]]). 外型 取 密 其 结构 ([['inner',内型]]). 外 取 外型 其 新建. 视图 取 外 其 读 'inner'. 文 取 密 其 UTF8 'anchor'. 视图 其 写 'p' 文. 副 取 外型 其 新建. 副 其 写 'inner' 视图.")
        memory = N._unwrap(self.owner.global_scope.values['文'])
        reference = weakref.ref(memory)
        del memory
        self.owner.global_scope.values.pop('文')
        self.owner.global_scope.values.pop('视图')
        gc.collect()
        self.assertIsNotNone(reference())
        self.run_ru("视图二 取 外 其 读 'inner'. 视图二 其 写 'p' 空. 外 其 关闭.")
        gc.collect()
        self.assertIsNotNone(reference(), 'copied nested pointer must retain original buffer')
        self.run_ru('副 其 关闭.')
        gc.collect()
        self.assertIsNone(reference())

    def test_nonfinite_native_results_never_enter_ru_numbers(self):
        with self.assertRaisesRegex(N.NativeFault, '有限数'):
            N.NativeScalar(N.PRIMITIVES['f64'], float('inf'))

    def test_float_conversion_checks_lifetime_and_pointer_provenance(self):
        self.run_ru("文 取 密 其 UTF8 'alive'. 指 取 文 其 地址. 指宽 取 (密 其 uintptr) 其 重释 指.")
        for value in ('指', '指宽'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(RuError, '不能转换为浮点'):
                    self.run_ru('(密 其 f64) 其 值 ' + value + '.')
        self.run_ru('文 其 关闭.')
        for descriptor in ('f32', 'f64', 'u64'):
            with self.subTest(descriptor=descriptor):
                with self.assertRaisesRegex(RuError, '已关闭'):
                    self.run_ru('(密 其 ' + descriptor + ') 其 值 指.')

    def test_loader_policy_rejects_before_load(self):
        with patch.object(C, 'WinDLL', create=True) as load:
            for path in ('../evil.dll', '/tmp/evil.dll', 'a\\b.dll', 'evil', 'a.dll:stream'):
                with self.assertRaises(RuError):
                    self.run_ru(f"密 其 系统库 '{path.replace(chr(92), chr(92)*2)}'.")
            load.assert_not_called()
            self.run_ru("密 其 系统库 'kernel32.dll'.")
            self.assertEqual(load.call_args.kwargs['winmode'], 0x800)
        with tempfile.TemporaryDirectory() as directory, patch.object(C, 'WinDLL', create=True) as load:
            path = Path(directory) / 'fixture.dll'
            path.touch()
            self.owner.global_scope.values['路径'] = str(path)
            self.run_ru('密 其 动态库 路径.')
            self.assertEqual(load.call_args.kwargs['winmode'], 0x900)


class NativeFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.child = bool(os.environ.get('RU_TEST_NATIVE_FIXTURE'))
        if cls.child:
            cls.path = Path(os.environ['RU_TEST_NATIVE_FIXTURE'])
            cls.directory = SimpleNamespace(name=str(cls.path.parent))
            cls.library = N.NativeLibrary(C.CDLL(str(cls.path), use_last_error=True))
            return
        compiler = shutil.which(os.environ.get('CC', 'gcc'))
        if compiler is None:
            raise unittest.SkipTest('fixture needs official local C compiler')
        cls.directory = tempfile.TemporaryDirectory()
        cls.path = Path(cls.directory.name) / ('bridge.dll' if os.name == 'nt' else 'bridge.so')
        command = [compiler, '-shared', '-O2', str(ROOT / 'tests/fixtures/native/bridge.c'), '-o', str(cls.path)]
        if os.name != 'nt':
            command.insert(1, '-fPIC')
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError('fixture compile failed: ' + result.stderr)
        cls.library = None if os.name == 'nt' else N.NativeLibrary(C.CDLL(str(cls.path), use_last_error=True))

    @classmethod
    def tearDownClass(cls):
        if not cls.child:
            cls.directory.cleanup()

    def setUp(self):
        if os.name == 'nt' and not self.child:
            return
        self.supported = patch.object(N, '_supported', return_value=True)
        self.supported.start()
        self.addCleanup(self.supported.stop)
        self.owner = Interpreter(allow_native=True, stdout=io.StringIO())
        self.context = self.owner._native_context
        self.owner.execute(parse(IMPORT))
        self.owner.global_scope.values['测试库'] = N._wrap(self.library, self.context)

    def execute(self, code):
        self.owner.execute(parse(code))
        return self.owner.stdout.getvalue()

    def test_real_c_exact_integer_struct_pointer_utf16(self):
        result = self.execute("回声 取 测试库 其 绑定 'echo_u64' (密 其 签名 (密 其 u64) ([(密 其 u64)]) 'cdecl'). 显 ((回声 其 调用 ([((密 其 u64) 其 值 '18446744073709551615')])) 其 值) 其 句. 型 取 密 其 结构 ([['tiny',密 其 u8],['wide',密 其 u64],['tail',密 其 i32]]). 物 取 型 其 新建. 填 取 测试库 其 绑定 'mixed_fill' (密 其 签名 (密 其 无值) ([(密 其 指针)]) 'cdecl'). 填 其 调用 ([物]). 显 (物 其 读 'wide') 其 句. 显 (物 其 读 'tail') 其 数. 回指 取 测试库 其 绑定 'echo_pointer' (密 其 签名 (密 其 指针) ([(密 其 指针)]) 'cdecl'). 指 取 (密 其 指针) 其 值 '18446744073709551615'. 显 ((回指 其 调用 ([指])) 其 值) 其 句. 文 取 密 其 缓冲 8. 填文 取 测试库 其 绑定 'fill_utf16' (密 其 签名 (密 其 无值) ([(密 其 指针)]) 'cdecl'). 填文 其 调用 ([文]). 显 文 其 解UTF16.")
        self.assertEqual(result, '18446744073709551615\n18446744073709551615\n-19\n18446744073709551615\n你😀\n')

    def test_real_c_callback_reentry_error_outcome_and_close(self):
        self.execute("签 取 密 其 签名 (密 其 i64) ([(密 其 u64)]) 'cdecl'. 原生调 取 测试库 其 绑定 'invoke_callback' (密 其 签名 (密 其 i64) ([(密 其 指针),(密 其 u64)]) 'cdecl'). 回声 取 测试库 其 绑定 'echo_i64' (密 其 签名 (密 其 i64) ([(密 其 i64)]) 'cdecl'). 回 取 密 其 回调 签 (算 值: 得 (回声 其 调用 ([值])) 其 值. 法) (-9). 果 取 原生调 其 调用 ([回,42]). 显 (果 其 值) 其 数. 显 果 其 回调错误.")
        self.assertEqual(self.owner.stdout.getvalue(), '42\n空\n')
        self.execute("坏回 取 密 其 回调 签 (算 值: 卒 'callback boom'. 法) (-9). 坏果 取 原生调 其 调用 ([坏回,1]). 显 (坏果 其 值) 其 数. 显 坏果 其 回调错误. 坏回 其 关闭.")
        self.assertIn('-9\n原生回调失败：', self.owner.stdout.getvalue())
        self.assertIn('callback boom', self.owner.stdout.getvalue())
        with self.assertRaisesRegex(RuError, '已关闭'):
            self.execute('原生调 其 调用 ([坏回,1]).')

    def test_failure_hook_recursion_is_bounded_and_first_error_survives(self):
        self.execute("签 取 密 其 签名 (密 其 i64) ([(密 其 u64)]) 'cdecl'. 原生调 取 测试库 其 绑定 'invoke_callback' (密 其 签名 (密 其 i64) ([(密 其 指针),(密 其 u64)]) 'cdecl'). 计数 取 [0]. 回 取 密 其 回调 签 (算 值: 计数[0] 取 计数[0]+1. 卒 ('first-' + (计数[0] 为 句)). 法) (-3). 回 其 失败时 原生调 ([回,1]). 果 取 原生调 其 调用 ([回,1]). 显 计数[0]. 显 (果 其 值) 其 数. 显 果 其 回调错误. 回 其 关闭.")
        output = self.owner.stdout.getvalue()
        self.assertTrue(output.startswith('2\n-3\n'), output)
        self.assertIn('first-1', output)
        self.assertNotIn('first-2', output)

    def test_separate_bindings_do_not_mutate_prior_signatures(self):
        self.execute("甲 取 测试库 其 绑定 'echo_u64' (密 其 签名 (密 其 u64) ([(密 其 u64)]) 'cdecl'). 乙 取 测试库 其 绑定 'echo_u64' (密 其 签名 (密 其 i64) ([(密 其 i64)]) 'cdecl'). 大值 取 (密 其 u64) 其 值 '18446744073709551615'. 显 ((甲 其 调用 [大值]) 其 值) 其 句. 显 ((乙 其 调用 [(-1)]) 其 值) 其 句.")
        self.assertEqual(self.owner.stdout.getvalue(), '18446744073709551615\n-1\n')

    def test_owned_pointer_callback_results_are_pinned_until_close(self):
        self.execute("签 取 密 其 签名 (密 其 指针) ([]) 'cdecl'. 原生调 取 测试库 其 绑定 'invoke_pointer_callback' (密 其 签名 (密 其 指针) ([(密 其 指针)]) 'cdecl'). 回 取 密 其 回调 签 (算: 得 密 其 UTF8 'temporary'. 法) 空. 果 取 原生调 其 调用 [回].")
        callback = N._unwrap(self.owner.global_scope.values['回'])
        self.assertEqual(len(callback.return_owners), 1)
        memory = next(iter(callback.return_owners.values()))
        reference = weakref.ref(memory)
        del memory
        gc.collect()
        self.assertIsNotNone(reference())
        with patch.object(N, 'MAX_CALLBACK_RETURN_OWNERS', 1):
            self.execute('坏果 取 原生调 其 调用 [回]. 显 坏果 其 回调错误.')
            self.assertIn('返回的拥有型指针资源', self.owner.stdout.getvalue())
        callback.close()
        gc.collect()
        self.assertIsNone(reference())

    def test_active_callback_can_close_and_return_scalar_but_not_owned_pointer(self):
        self.execute("签 取 密 其 签名 (密 其 i64) ([(密 其 u64)]) 'cdecl'. 原生调 取 测试库 其 绑定 'invoke_callback' (密 其 签名 (密 其 i64) ([(密 其 指针),(密 其 u64)]) 'cdecl'). 回 取 密 其 回调 签 (算 值: 回 其 关闭. 得 9. 法) (-3). 果 取 原生调 其 调用 [回,1]. 显 (果 其 值) 其 数. 显 果 其 回调错误.")
        self.assertEqual(self.owner.stdout.getvalue(), '9\n空\n')
        self.execute("指签 取 密 其 签名 (密 其 指针) ([]) 'cdecl'. 指调 取 测试库 其 绑定 'invoke_pointer_callback' (密 其 签名 (密 其 指针) ([(密 其 指针)]) 'cdecl'). 指回 取 密 其 回调 指签 (算: 指回 其 关闭. 得 密 其 UTF8 'unsafe'. 法) 空. 指果 取 指调 其 调用 [指回]. 显 (指果 其 值) 其 为空. 显 指果 其 回调错误.")
        self.assertIn('真\n原生回调失败：关闭中的回调不能返回拥有型指针', self.owner.stdout.getvalue())

    def test_callback_activity_survives_close_and_unwinds_on_each_exit(self):
        self.execute("签 取 密 其 签名 (密 其 i64) ([(密 其 u64)]) 'cdecl'. 原生调 取 测试库 其 绑定 'invoke_callback' (密 其 签名 (密 其 i64) ([(密 其 指针),(密 其 u64)]) 'cdecl').")
        for ending in ('得 9.', "卒 'activity panic'.", '得 1/0.'):
            with self.subTest(ending=ending):
                self.owner.stdout.seek(0)
                self.owner.stdout.truncate(0)
                self.execute("显 密 其 回调中. 回 取 密 其 回调 签 (算 值: 显 密 其 回调中. 回 其 关闭. 显 密 其 回调中. " + ending + " 法) (-3). 果 取 原生调 其 调用 [回,1]. 显 密 其 回调中.")
                self.assertEqual(self.owner.stdout.getvalue(), '假\n真\n真\n假\n')
                self.assertEqual(self.context.callback_depth, 0)
                self.assertEqual(N._unwrap(self.owner.global_scope.values['回']).active, 0)
                outcome = N._unwrap(self.owner.global_scope.values['果'])
                self.assertEqual(outcome.callback_error is None, ending == '得 9.')

    def test_callback_activity_unwinds_even_when_last_error_cleanup_fails(self):
        self.execute("签 取 密 其 签名 (密 其 i64) ([(密 其 u64)]) 'cdecl'. 回 取 密 其 回调 签 (算 值: 得 9. 法) (-3).")
        callback = N._unwrap(self.owner.global_scope.values['回'])
        self.context.depth = 1
        try:
            with patch.object(C, 'get_last_error', return_value=0, create=True), patch.object(C, 'set_last_error', side_effect=MemoryError('cleanup'), create=True):
                self.assertEqual(callback.trampoline(1), -3)
        finally:
            self.context.depth = 0
        self.assertEqual(self.context.callback_depth, 0)
        self.assertEqual(callback.active, 0)
        self.assertTrue(self.context.containment_failure)
        callback.close()

    def test_callback_return_rejects_foreign_context_before_c_marshalling(self):
        other = Interpreter(allow_native=True)
        other.execute(parse(IMPORT + "值 取 (密 其 i64) 其 值 7."))
        self.owner.global_scope.values['外来'] = other.global_scope.values['值']
        self.execute("签 取 密 其 签名 (密 其 i64) ([(密 其 u64)]) 'cdecl'. 原生调 取 测试库 其 绑定 'invoke_callback' (密 其 签名 (密 其 i64) ([(密 其 指针),(密 其 u64)]) 'cdecl'). 回 取 密 其 回调 签 (算 值: 得 外来. 法) (-3). 果 取 原生调 其 调用 [回,1]. 显 (果 其 值) 其 数. 显 果 其 回调错误. 回 其 关闭.")
        output = self.owner.stdout.getvalue()
        self.assertTrue(output.startswith('-3\n'), output)
        self.assertIn('跨解释器能力上下文', output)

    def test_error_reporting_failure_cannot_escape_ctypes_trampoline(self):
        self.execute("签 取 密 其 签名 (密 其 i64) ([(密 其 u64)]) 'cdecl'. 原生调 取 测试库 其 绑定 'invoke_callback' (密 其 签名 (密 其 i64) ([(密 其 指针),(密 其 u64)]) 'cdecl'). 回 取 密 其 回调 签 (算 值: 卒 'original'. 法) (-2).")
        errors = io.StringIO()
        with patch.object(self.context, 'error', side_effect=MemoryError('injected reporting failure')), patch.object(sys, 'stderr', errors):
            self.execute('果 取 原生调 其 调用 [回,1]. 显 (果 其 值) 其 数. 显 果 其 回调错误.')
        self.assertEqual(errors.getvalue(), '')
        self.assertEqual(self.context.callback_depth, 0)
        self.assertEqual(self.owner.stdout.getvalue(), '-2\n原生回调失败：错误报告或收束异常\n')
        self.execute('回 其 关闭.')

    def test_foreign_thread_skips_ru_and_failure_hook(self):
        self.execute("签 取 密 其 签名 (密 其 i64) ([(密 其 u64)]) 'cdecl'. 回 取 密 其 回调 签 (算 值: 显 'must not run'. 得 5. 法) (-7).")
        callback = N._unwrap(self.owner.global_scope.values['回'])
        result = []
        thread = threading.Thread(target=lambda: result.append(callback.trampoline(1)))
        thread.start(); thread.join(5)
        self.assertEqual(result, [-7])
        self.assertEqual(self.owner.stdout.getvalue(), '')
        self.assertIn('同步回调', self.context.errors[0])
        callback.close()

    def test_close_detaches_owner_and_process_tombstone_is_bounded(self):
        self.execute("签 取 密 其 签名 (密 其 i64) ([(密 其 u64)]) 'cdecl'. 回 取 密 其 回调 签 (算 值: 得 7. 法) (-2).")
        callback = N._unwrap(self.owner.global_scope.values['回'])
        trampoline = callback.trampoline
        callback.close()
        self.assertIsNone(callback.owner)
        self.assertIsNone(callback.function)
        self.assertIsNone(callback.failure_hook)
        self.assertNotIn(callback, self.context.callbacks)
        self.assertEqual(trampoline(1), -2)
        with patch.object(N, 'MAX_CALLBACKS', len(N._CALLBACK_TOMBSTONES)):
            with self.assertRaisesRegex(RuError, '上限'):
                self.execute('密 其 回调 签 (算 值: 得 7. 法) (-2).')

    def test_expired_context_does_not_stay_alive_through_global_trampoline(self):
        self.execute("签 取 密 其 签名 (密 其 i64) ([(密 其 u64)]) 'cdecl'. 回 取 密 其 回调 签 (算 值: 得 7. 法) (-2).")
        callback = N._unwrap(self.owner.global_scope.values['回'])
        trampoline = callback.trampoline
        owner = weakref.ref(self.owner)
        del callback
        self.owner = self.context = None
        gc.collect()
        self.assertIsNone(owner())
        self.assertEqual(trampoline(1), -2)

    @unittest.skipUnless(N._supported(), 'real Windows x64 CLI only')
    def test_windows_cli_loads_own_absolute_fixture_and_captures_last_error(self):
        path = str(self.path).replace('\\', '\\\\')
        source = IMPORT + f"库 取 密 其 动态库 '{path}'. 调 取 库 其 绑定 'last_error_value' (密 其 签名 (密 其 i32) ([]) 'cdecl'). 果 取 调 其 调用 ([]). 显 (果 其 值) 其 数. 显 果 其 错误码."
        script = Path(self.directory.name) / 'run.ru'
        script.write_text(source, encoding='utf-8')
        result = subprocess.run([sys.executable, str(ROOT / 'ru'), 'run', '--allow-native', str(script)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '-1\n1234\n')


def _windows_fixture_subprocess(method):
    @functools.wraps(method)
    def test(self):
        if os.name != 'nt' or self.child:
            return method(self)
        environment = dict(os.environ, RU_TEST_NATIVE_FIXTURE=str(self.path), PYTHONIOENCODING='utf-8')
        result = subprocess.run([sys.executable, '-m', 'unittest', 'test_native_library.NativeFixtureTests.' + method.__name__, '-v'], cwd=ROOT / 'tests', env=dict(environment, PYTHONPATH=str(ROOT)), capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    return test


# Windows keeps DLLs loaded until process exit. Execute each actual native
# fixture case in a bounded child; parent can then delete the fixture normally.
for _name, _method in list(vars(NativeFixtureTests).items()):
    if _name.startswith('test_'):
        setattr(NativeFixtureTests, _name, _windows_fixture_subprocess(_method))


if __name__ == '__main__':
    unittest.main()
