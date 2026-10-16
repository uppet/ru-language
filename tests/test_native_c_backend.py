"""Acceptance of the standalone C native backend, never a Python executable shim.

Portable tests check capability and static ABI boundaries. Windows tests compile
the owned DLL and real Ru executables with warnings as errors, then launch those
executables directly from an empty directory with Python removed from PATH.
The interpreter is only a separate parity oracle. A platform skip is not native
execution evidence; compiler/runtime failures on a supported host must fail.
"""
import ctypes
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.cli import compiler_command
from rulang.compiler import Compiler
from rulang.frontend import RuError, parse

WINDOWS_X64 = (sys.platform == 'win32' and ctypes.sizeof(ctypes.c_void_p) == 8
               and platform.machine().lower() in ('amd64', 'x86_64'))
PREFIX = "密 取 外言 '如:密'.\n"
ASSERT = """
作 断言 条件 为 事实, 说明 为 句:
    若 非 条件 则 卒 说明. 然
为
算 确认 成果:
    若 (成果 其 回调错误) != 空 则 卒 (成果 其 回调错误). 然
    得 成果 其 值.
法
"""


def bounded_run(command, *, timeout=45, **kwargs):
    try:
        return subprocess.run(command, capture_output=True, text=True,
                              encoding='utf-8', timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired as error:
        raise AssertionError(
            f'Child exceeded {timeout}s: {command!r}; '
            f'stdout={error.stdout!r}; stderr={error.stderr!r}') from error


def cli(*arguments, timeout=45):
    return bounded_run([sys.executable, str(ROOT / 'ru'), *map(str, arguments)],
                       cwd=ROOT, timeout=timeout,
                       env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1'))


def native_environment():
    """No Python search path, virtualenv, or compiler directory at execution."""
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith('PYTHON')
           and key.upper() not in ('PATH', 'VIRTUAL_ENV', 'CONDA_PREFIX', 'RU_GC_STATS')}
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    env['PATH'] = os.pathsep.join((str(windows / 'System32'), str(windows)))
    env['RU_GC_THRESHOLD'] = '1'
    return env


def ru_string(value):
    return "'" + str(value).replace('\\', '\\\\').replace("'", "\\'") + "'"


def binding(variable, symbol, result, parameters):
    args = ','.join('密 其 ' + item for item in parameters)
    return (f"{variable} 取 库 其 绑定 '{symbol}' "
            f"(密 其 签名 (密 其 {result}) ([{args}]) 'cdecl').\n")


class NativeCStaticAcceptanceTests(unittest.TestCase):
    def emit(self, source, *, full=False):
        return Compiler(parse(source), str(ROOT / 'native-acceptance.ru'),
                        allow_native=True, full_runtime=full).compile()

    def test_default_denial_covers_hidden_dormant_and_transitive_use(self):
        sources = [PREFIX, "若 不实 则 外言 '如:密'. 然", '别名 取 __密.']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'dependency.ru').write_text(PREFIX, encoding='utf-8')
            sources.append("外言 './dependency.ru'.")
            for index, source in enumerate(sources):
                with self.subTest(source=source):
                    script = root / f'denied{index}.ru'
                    script.write_text("显 'must-not-execute'. " + source, encoding='utf-8')
                    executable = root / 'preserved.exe'
                    executable.write_bytes(b'existing-output')
                    for command in ('check', 'build'):
                        arguments = [command, str(script)]
                        if command == 'build':
                            arguments += ['-o', str(executable)]
                        result = cli(*arguments)
                        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertNotIn('must-not-execute', result.stdout)
                        self.assertRegex(result.stderr, '原生|如:密')
                    self.assertEqual(executable.read_bytes(), b'existing-output')

    def test_opted_in_check_is_static_even_for_nonexistent_library(self):
        source = PREFIX + """
库 取 密 其 系统库 'Ru.Acceptance.Does.Not.Exist.dll'.
调 取 库 其 绑定 'missing' (密 其 签名 (密 其 i64) ([密 其 f32]) 'win64').
显 'must-not-execute'.
卒 'must-not-execute'.
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'static-only.ru'
            path.write_text(source, encoding='utf-8')
            result = cli('check', '--target', 'c', '--allow-native', path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('must-not-execute', result.stdout)
        self.assertNotIn('Traceback', result.stderr)

    def test_emission_is_standalone_typed_c_without_python_runtime(self):
        source = self.emit(PREFIX + """
签 取 密 其 签名 (密 其 f64) ([密 其 i64,密 其 f32,密 其 指针]) 'win64'.
回 取 密 其 回调 签 (算 甲 乙 丙: 得 1.25. 法) 0.
回 其 关闭.
""")
        self.assertIn('ru_native_generated_call', source)
        self.assertIn('ru_native_callback_dispatch', source)
        self.assertIn('int64_t', source)
        self.assertIn('float', source)
        for forbidden in ('Python.h', 'Py_Initialize', 'ctypes', 'python.exe'):
            self.assertNotIn(forbidden, source)
        self.assertNotIn('#include "native_', source, 'emitted C must embed its native support')

    def test_finite_aliases_and_bundled_rujian_emit_on_any_host(self):
        source = self.emit("""
尽取 外言 '如:密'.
算 造 型:
    别名 取 型.
    得 签名 别名 ([别名,f64]) 'cdecl'.
法
甲 取 造 i64.
乙 取 造 u64.
见 取 外言 '如见'.
""")
        self.assertIn('ru_native_generated_call', source)
        self.assertIn('ru_native_generated_callback', source)

    def test_dynamic_signatures_fail_before_build_or_execution(self):
        cases = (
            "签 取 密 其 签名 (密 其 i32) (读) 'cdecl'.",
            "签 取 密 其 签名 (密 其 i32) ([]) (读).",
            "签 取 密 其 签名 (读) ([]) 'cdecl'.",
            "参数们 取 [密 其 i32]. 参数们 其 增 (密 其 f64). 签 取 密 其 签名 (密 其 i32) 参数们 'cdecl'.",
        )
        for source in cases:
            with self.subTest(source=source), self.assertRaisesRegex(RuError, '无法静态确定'):
                self.emit(PREFIX + source)

    def test_plain_programs_do_not_acquire_native_runtime(self):
        for full in (False, True):
            with self.subTest(full=full):
                generated = self.emit("显 'ordinary'.", full=full)
                self.assertNotIn('ru_native_callback_dispatch', generated)
                self.assertNotIn('RuNativeRaw', generated)
                self.assertNotIn('ru_native_load_library', generated)


class NativeExecutableMixin:
    """Shared build/launch helper; deliberately not a unittest TestCase."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        selected = os.environ.get('CC')
        command = compiler_command(selected) if selected else []
        if not command:
            found = next((shutil.which(name) for name in ('clang', 'gcc', 'cc')
                          if shutil.which(name)), None)
            if found:
                command = [found]
        if not command or not (shutil.which(command[0]) or Path(command[0]).is_file()):
            raise unittest.SkipTest('a local Clang/GCC C compiler is required')
        cls.compiler = command

    def build_executable(self, source, directory):
        directory = Path(directory)
        script = directory / 'program.ru'
        executable = directory / 'program.exe'
        emitted = directory / 'program.c'
        script.write_text(source, encoding='utf-8')
        command = [*self.compiler, '-Werror', '-pedantic']
        selected = subprocess.list2cmdline(command) if os.name == 'nt' else shlex.join(command)
        result = cli('build', '--allow-native', '--cc', selected,
                     '--emit-c', emitted, script, '-o', executable, timeout=150)
        self.assertEqual(result.returncode, 0, result.stdout + '\n' + result.stderr)
        self.assertTrue(emitted.is_file(), result.stdout)
        self.assertEqual(executable.read_bytes()[:2], b'MZ', 'the build must produce a Windows PE executable')
        return executable, script

    def run_executable(self, executable, *, arguments=(), timeout=45):
        with tempfile.TemporaryDirectory() as empty_working_directory:
            # No shell and no Python launcher: this exact executable is the child.
            return bounded_run([str(executable), *arguments], cwd=empty_working_directory,
                               env=native_environment(), timeout=timeout)


@unittest.skipUnless(WINDOWS_X64, 'requires real Windows x64 execution')
class NativeCWindowsAcceptanceTests(NativeExecutableMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fixture_directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixture_directory.cleanup)
        cls.fixture = Path(cls.fixture_directory.name) / 'c_backend_bridge.dll'
        command = [*cls.compiler, '-std=c99', '-shared', '-O2', '-Wall', '-Wextra',
                   '-Werror', '-pedantic', str(ROOT / 'tests/fixtures/native/c_backend_bridge.c'),
                   '-o', str(cls.fixture)]
        result = bounded_run(command, timeout=90)
        if result.returncode:
            raise AssertionError('owned C fixture failed to compile:\n' + result.stderr)

    def program(self, body):
        return PREFIX + ASSERT + '库 取 密 其 动态库 ' + ru_string(self.fixture) + '.\n' + body

    def assert_native_parity(self, body, expected, *, success=True):
        with tempfile.TemporaryDirectory() as directory:
            executable, script = self.build_executable(self.program(body), directory)
            native = self.run_executable(executable)
            interpreted = cli('run', '--allow-native', script)
        for name, result in (('C executable', native), ('Python oracle', interpreted)):
            with self.subTest(backend=name):
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
                self.assertEqual(result.stdout, expected, result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertNotIn('Exception ignored on calling ctypes callback', result.stderr)
                if success:
                    self.assertEqual(result.stderr, '')
        return native, interpreted

    def test_exact_integer_pointer_bounds_and_struct_layout(self):
        body = binding('无号', 'echo_u64', 'u64', ['u64'])
        body += binding('有号', 'echo_i64', 'i64', ['i64'])
        body += binding('回指', 'echo_pointer', '指针', ['指针'])
        body += binding('大小', 'mixed_size', 'u32', [])
        body += binding('宽偏', 'mixed_wide_offset', 'u32', [])
        body += binding('尾偏', 'mixed_tail_offset', 'u32', [])
        body += binding('填', 'mixed_fill', '无值', ['指针'])
        body += binding('填文', 'fill_utf16', '无值', ['指针'])
        body += """
显 (确认 (无号 其 调用 [((密 其 u64) 其 值 '18446744073709551615')])) 其 句.
显 (确认 (有号 其 调用 [((密 其 i64) 其 值 '-9223372036854775808')])) 其 句.
指 取 (密 其 指针) 其 值 '18446744073709551615'.
显 (确认 (回指 其 调用 [指])) 其 句.
显 ((密 其 intptr) 其 重释 指) 其 句.
型 取 密 其 结构 [['tiny',密 其 u8],['wide',密 其 u64],['tail',密 其 i32]].
断言 ((型 其 大小) == (确认 (大小 其 调用 [])) 其 数) '结构大小'.
断言 ((型 其 偏移 'wide') == (确认 (宽偏 其 调用 [])) 其 数) 'wide 偏移'.
断言 ((型 其 偏移 'tail') == (确认 (尾偏 其 调用 [])) 其 数) 'tail 偏移'.
物 取 型 其 新建.
确认 (填 其 调用 [物]).
显 (物 其 读 'wide') 其 句.
显 (物 其 读 'tail') 其 数.
文 取 密 其 缓冲 8.
确认 (填文 其 调用 [文]).
显 文 其 解UTF16.
物 其 关闭. 文 其 关闭.
"""
        self.assert_native_parity(body, '18446744073709551615\n-9223372036854775808\n18446744073709551615\n-1\n18446744073709551615\n-19\n你😀\n')

    def test_numeric_and_owner_errors_exit_before_entering_native_code(self):
        # Ordinary runtime errors are fatal, not caught by 试/救. Compile once
        # and select each failing case in its own bounded child process.
        cases = (
            ("(密 其 u64) 其 值 '18446744073709551616'.", '范围|溢出'),
            ("(密 其 i64) 其 值 '-9223372036854775809'.", '范围|溢出'),
            ("(密 其 u8) 其 值 (-1).", '范围|溢出'),
            ("(密 其 i32) 其 值 1.5.", '整数'),
            ("探针 其 调用 [1].", '指针'),
            ("指 取 (密 其 指针) 其 值 '18446744073709551615'. 指 其 数.", '安全整数'),
            ("文 取 密 其 缓冲 8. 文 其 关闭. 探针 其 调用 [文].", '关闭'),
        )
        body = binding('探针', 'reject_probe', '无值', ['指针'])
        body += '算 元初 参数 为 句 阵:\n'
        for index, (expression, _) in enumerate(cases):
            body += f"若 参数[0] == '{index}' 则 {expression} 然\n"
        body += "探针 其 调用 [空]. 得 0. 法\n"
        with tempfile.TemporaryDirectory() as directory:
            executable, script = self.build_executable(self.program(body), directory)
            for index, (_, diagnostic) in enumerate(cases):
                for backend in ('C executable', 'Python oracle'):
                    with self.subTest(case=index, backend=backend):
                        result = (self.run_executable(executable, arguments=[str(index)])
                                  if backend == 'C executable'
                                  else cli('run', '--allow-native', script, str(index)))
                        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertEqual(result.stdout, '', 'invalid input reached the native fixture')
                        self.assertRegex(result.stderr, r'program\.ru:\d+(?::\d+)?: error:')
                        self.assertRegex(result.stderr, diagnostic)
                        self.assertNotIn('Traceback', result.stderr)

    def test_mixed_gp_xmm_and_stack_arguments_in_both_directions(self):
        parameters = ['i64', 'f64', 'u64', 'f32', 'i32', 'f64', 'u64', 'f32']
        body = binding('混调', 'mixed_registers', 'f64', parameters)
        body += binding('叫混回', 'invoke_mixed', 'f64', ['指针'])
        body += binding('单回声', 'echo_f32', 'f32', ['f32'])
        body += binding('叫单回', 'invoke_f32', 'f32', ['指针'])
        body += "签 取 密 其 签名 (密 其 f64) ([" + ','.join('密 其 ' + p for p in parameters) + "]) 'cdecl'.\n"
        body += """
回 取 密 其 回调 签 (算 甲 乙 丙 丁 戊 己 庚 辛:
    得 确认 (混调 其 调用 [甲,乙,丙,丁,戊,己,庚,辛]).
法) (-999).
显 (确认 (混调 其 调用 [((密 其 i64) 其 值 '-9223372036854775808'),1.25,((密 其 u64) 其 值 '18446744073709551615'),2.5,-17,4.75,((密 其 u64) 其 值 '9007199254740993'),8.5])) 其 数.
显 (确认 (叫混回 其 调用 [回])) 其 数.
显 (确认 (单回声 其 调用 [1.25])) 其 数.
单签 取 密 其 签名 (密 其 f32) ([密 其 f32]) 'cdecl'.
单回 取 密 其 回调 单签 (算 值: 得 值. 法) (-999).
显 (确认 (叫单回 其 调用 [单回])) 其 数.
回 其 关闭. 单回 其 关闭.
"""
        self.assert_native_parity(body, '17\n17\n1.25\n2.5\n')

    def callbacks(self):
        return (binding('原生调', 'invoke_callback', 'i64', ['指针', 'u64'])
                + binding('回声', 'echo_i64', 'i64', ['i64'])
                + binding('返回数', 'callback_returns', 'i32', [])
                + "签 取 密 其 签名 (密 其 i64) ([密 其 u64]) 'cdecl'.\n")

    def test_nested_synchronous_callback_and_native_return_after_error(self):
        body = self.callbacks() + """
算 阶乘 数字 为 数:
    若 数字 <= 1 则 得 1.
    另 得 数字 * (阶乘 数字-1). 然
法
内回 取 密 其 回调 签 (算 值: 得 确认 (回声 其 调用 [值]). 法) (-8).
外回 取 密 其 回调 签 (算 值: 得 确认 (原生调 其 调用 [内回,值]). 法) (-9).
显 (确认 (原生调 其 调用 [外回,42])) 其 数.
显 (确认 (返回数 其 调用 [])) 其 数.
坏回 取 密 其 回调 签 (算 值: 卒 'contained-panic'. 法) (-7).
果 取 原生调 其 调用 [坏回,1].
显 (果 其 值) 其 数.
断言 ((果 其 回调错误) 其 含 'contained-panic') '丢失回调错误'.
显 (确认 (返回数 其 调用 [])) 其 数.
断言 (非 (密 其 回调中)) '回调活动未恢复'.
递归回 取 密 其 回调 签 (算 值: 得 阶乘 (值 其 数). 法) (-12).
显 (确认 (原生调 其 调用 [递归回,5])) 其 数.
显 (确认 (返回数 其 调用 [])) 其 数.
内回 其 关闭. 外回 其 关闭. 坏回 其 关闭. 递归回 其 关闭.
显 'contained'.
"""
        self.assert_native_parity(body, '42\n2\n-7\n3\n120\n4\ncontained\n')

    def test_runtime_error_uses_fallback_and_allows_later_native_call(self):
        body = self.callbacks() + binding('坏浮', 'nonfinite_f64', 'f64', []) + """
算 数算 参数 为 数: 得 参数. 法
回 取 密 其 回调 签 (算 值: 得 1/0. 法) (-13).
果 取 原生调 其 调用 [回,1].
显 (果 其 值) 其 数.
断言 ((果 其 回调错误) != 空) '运行错误逃出回调'.
显 (确认 (返回数 其 调用 [])) 其 数.
长文 取 ''.
循 1500 次 长文 取 长文 + '中文😀'. 环
长回 取 密 其 回调 签 (算 值: 卒 长文. 法) (-17).
长果 取 原生调 其 调用 [长回,1].
显 (长果 其 值) 其 数.
断言 ((长果 其 回调错误) 其 含 '中文😀') '长 UTF8 错误未安全保留'.
显 (确认 (返回数 其 调用 [])) 其 数.
显 (确认 (回声 其 调用 [19])) 其 数.
回 其 关闭. 长回 其 关闭.
"""
        errors = (
            (-21, "得 数算 '类型错误'."),
            (-22, '得 值 其 不存在的成员.'),
            (-23, '得 (密 其 u8) 其 值 256.'),
            (-24, '得 (密 其 f32) 其 值 1e39.'),
            (-25, '得 确认 (坏浮 其 调用 []).'),
        )
        for fallback, statement in errors:
            body += f"""
错误回 取 密 其 回调 签 (算 值: {statement} 法) ({fallback}).
错误果 取 原生调 其 调用 [错误回,1].
显 (错误果 其 值) 其 数.
断言 ((错误果 其 回调错误) != 空) '普通错误未被回调边界包含'.
断言 (非 (密 其 回调中)) '普通错误后回调深度没有恢复'.
显 (确认 (回声 其 调用 [19])) 其 数.
错误回 其 关闭.
"""
        body += '显 (确认 (返回数 其 调用 [])) 其 数.\n'
        expected = '-13\n1\n-17\n2\n19\n'
        expected += ''.join(f'{fallback}\n19\n' for fallback, _ in errors) + '7\n'
        self.assert_native_parity(body, expected)

    def test_failure_hook_recursion_preserves_first_error(self):
        body = self.callbacks() + """
次数 取 [0].
回 取 密 其 回调 签 (算 值:
    次数[0] 取 次数[0]+1.
    卒 ('first-' + (次数[0] 为 句)).
法) (-3).
回 其 失败时 原生调 ([回,1]).
果 取 原生调 其 调用 [回,1].
显 次数[0]. 显 (果 其 值) 其 数.
断言 ((果 其 回调错误) 其 含 'first-1') '首错误丢失'.
断言 (非 ((果 其 回调错误) 其 含 'first-2')) '次错误覆盖首错误'.
显 (确认 (返回数 其 调用 [])) 其 数.
回 其 关闭.
"""
        self.assert_native_parity(body, '2\n-3\n2\n')

    def test_foreign_thread_rejects_ru_body_and_failure_hook(self):
        body = self.callbacks()
        body += binding('异调', 'invoke_foreign_thread', 'i64', ['指针', 'u64'])
        body += binding('记错', 'mark_failure', '无值', ['i32'])
        body += binding('错数', 'failure_count', 'i32', [])
        body += """
次数 取 [0].
回 取 密 其 回调 签 (算 值: 次数[0] 取 次数[0]+1. 得 5. 法) (-7).
回 其 失败时 记错 ([1]).
果 取 异调 其 调用 [回,1].
显 (果 其 值) 其 数. 显 次数[0].
显 (确认 (错数 其 调用 [])) 其 数.
断言 ((果 其 回调错误) 其 含 '同步回调') '异线程回调没有明确错误'.
断言 (非 (密 其 回调中)) '异线程破坏回调深度'.
回 其 关闭.
"""
        self.assert_native_parity(body, '-7\n0\n0\n')

    def test_last_error_snapshot_survives_nested_native_call(self):
        body = self.callbacks()
        body += binding('设错', 'last_error_value', 'i32', [])
        body += binding('外错', 'callback_last_error', 'u32', ['指针'])
        body += """
直接 取 设错 其 调用 [].
显 (直接 其 值) 其 数. 显 直接 其 错误码.
回 取 密 其 回调 签 (算 值:
    内果 取 设错 其 调用 [].
    断言 ((内果 其 错误码) == 4321) '内错误码丢失'.
    得 9.
法) (-7).
果 取 外错 其 调用 [回].
显 (果 其 值) 其 数. 显 果 其 错误码.
断言 ((果 其 回调错误) == 空) '错误码恢复引发错误'.
回 其 关闭.
"""
        self.assert_native_parity(body, '-1\n4321\n1234\n1234\n')

    def test_closed_callback_tombstone_returns_fallback_without_ru(self):
        body = self.callbacks()
        body += binding('存回', 'save_callback', '无值', ['指针'])
        body += binding('叫旧回', 'invoke_saved', 'i64', ['u64'])
        body += """
次数 取 [0].
回 取 密 其 回调 签 (算 值: 次数[0] 取 次数[0]+1. 得 7. 法) (-21).
确认 (存回 其 调用 [回]).
回 其 关闭.
果 取 叫旧回 其 调用 [1].
显 (果 其 值) 其 数. 显 次数[0].
断言 ((果 其 回调错误) != 空) '关闭回调没有错误成果'.
回 取 空.
循 20 次 临时 取 [1,2,3,'collect']. 环
后果 取 叫旧回 其 调用 [2].
显 (后果 其 值) 其 数.
显 (确认 (返回数 其 调用 [])) 其 数.
"""
        self.assert_native_parity(body, '-21\n0\n-21\n2\n')

    def test_active_closed_callback_reentry_uses_saved_fallback(self):
        body = self.callbacks()
        body += binding('存回', 'save_callback', '无值', ['指针'])
        body += binding('叫旧回', 'invoke_saved', 'i64', ['u64'])
        body += """
次数 取 [0].
回 取 密 其 回调 签 (算 值:
    次数[0] 取 次数[0]+1.
    回 其 关闭.
    内果 取 叫旧回 其 调用 [2].
    断言 (((内果 其 值) 其 数) == -31) '关闭中回调没有用失败值'.
    断言 (次数[0] == 1) '关闭中回调再次进入如代码'.
    断言 (密 其 回调中) '活动回调过早归零'.
    得 11.
法) (-31).
确认 (存回 其 调用 [回]).
果 取 原生调 其 调用 [回,1].
显 (果 其 值) 其 数. 显 次数[0].
断言 ((果 其 回调错误) != 空) '关闭中再次回入未报告'.
断言 (非 (密 其 回调中)) '活动回调未归零'.
显 (确认 (返回数 其 调用 [])) 其 数.
"""
        self.assert_native_parity(body, '11\n1\n2\n')

    def test_owned_pointer_return_and_copied_nested_view_survive_forced_gc(self):
        body = binding('存指', 'capture_pointer', '无值', ['指针'])
        body += binding('验指', 'saved_text_matches', 'i32', [])
        body += binding('验内', 'nested_text_matches', 'i32', ['指针'])
        body += """
签 取 密 其 签名 (密 其 指针) ([]) 'cdecl'.
回 取 密 其 回调 签 (算: 得 密 其 UTF8 'retained-owner'. 法) 空.
确认 (存指 其 调用 [回]).
内型 取 密 其 结构 [['text',密 其 指针]].
外型 取 密 其 结构 [['inner',内型]].
外 取 外型 其 新建. 视图 取 外 其 读 'inner'.
文 取 密 其 UTF8 'nested-owner'.
视图 其 写 'text' 文.
副 取 外型 其 新建. 副 其 写 'inner' 视图.
文 取 空. 视图 取 空. 外 其 关闭. 外 取 空.
循 40 次 临时 取 ['collect',1,2,3]. 环
显 (确认 (验指 其 调用 [])) 其 数.
显 (确认 (验内 其 调用 [副])) 其 数.
重用文 取 密 其 UTF8 'retained-owner'.
重用指 取 重用文 其 地址.
重释回 取 密 其 回调 签 (算:
    得 (密 其 指针) 其 重释 重用指.
法) 空.
循 140 次 确认 (存指 其 调用 [重释回]). 环
重用文 取 空. 重用指 取 空.
循 20 次 临时 取 ['collect',4,5,6]. 环
显 (确认 (验指 其 调用 [])) 其 数.
副 其 关闭. 回 其 关闭. 重释回 其 关闭.
"""
        self.assert_native_parity(body, '1\n1\n1\n')

    def test_first_callback_module_initialization_is_contained_and_retryable(self):
        # C has an explicit first-initialization boundary. Once imported before
        # a native call, the same module is available normally in callbacks.
        body = self.callbacks() + """
回 取 密 其 回调 签 (算 参数:
    延迟 取 外言 './late.ru'.
    得 延迟 其 值.
法) (-7).
果 取 原生调 其 调用 [回,1].
断言 (((果 其 值) 其 数) == -7) '首次初始化失败值错误'.
断言 ((果 其 回调错误) 其 含 '不能首次初始化外言') '缺少首次初始化诊断'.
显 'first-contained'.
已导入 取 外言 './late.ru'.
显 (确认 (原生调 其 调用 [回,1])) 其 数.
显 (确认 (返回数 其 调用 [])) 其 数.
回 其 关闭.
"""
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'late.ru').write_text("显 'late-ready'. 值 取 73.", encoding='utf-8')
            executable, _ = self.build_executable(self.program(body), directory)
            result = self.run_executable(executable)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, 'first-contained\nlate-ready\n73\n2\n', result.stderr)
        self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
