"""Owned-fixture unit tests of generic C state/ownership on a POSIX test host.

These tests deliberately replace the emitted Windows platform adapter ONLY in
the test artifact. There is no production flag, fallback or supported POSIX
backend. Real Windows ABI, DLL search, LastError and GUI acceptance lives in
test_native_c_backend/test_rujian_c_win32 and must not be inferred from this file.
"""
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from rulang.compiler import Compiler
from rulang.frontend import parse
import test_native_c_backend as acceptance
from test_native_c_backend import bounded_run, ROOT


TEST_PLATFORM = r'''
#include <dlfcn.h>
#include <pthread.h>
static uint32_t ru_native_thread_id;
static pthread_t rn_test_owner;
static int rn_test_ready;
static uint32_t rn_test_error;
static volatile int rn_test_foreign;
static uint32_t rn_platform_thread(void) {
    if (!rn_test_ready) { rn_test_owner = pthread_self(); rn_test_ready = 1; }
    return pthread_equal(rn_test_owner, pthread_self()) ? 1 : 2;
}
static uint32_t rn_platform_error(void) { return rn_test_error; }
static void rn_platform_set_error(uint32_t error) { rn_test_error = error; }
static void rn_platform_thread_error(void) { __sync_lock_test_and_set(&rn_test_foreign, 1); }
static int rn_platform_wrong_thread(int clear) {
    return clear ? __sync_lock_test_and_set(&rn_test_foreign, 0) : __sync_add_and_fetch(&rn_test_foreign, 0);
}
static void *ru_native_load_library(const char *text, const unsigned char *utf16, int system, int line) {
    void *handle; (void)utf16;
    if (system || text[0] != '/') ru_fail(line, "owned POSIX test fixture needs absolute path");
    handle = dlopen(text, RTLD_NOW);
    if (!handle) ru_fail(line, "owned test fixture load failed: %s", dlerror());
    return handle;
}
static void *ru_native_find_symbol(void *handle, const char *name) { return dlsym(handle, name); }
'''


def portable_test_source(source, path, *, full=False):
    generated = Compiler(parse(source), path, allow_native=True, full_runtime=full).compile()
    pattern = r'/\* RU_NATIVE_PLATFORM_BEGIN \*/.*?/\* RU_NATIVE_PLATFORM_END \*/'
    generated, count = re.subn(pattern, lambda _: TEST_PLATFORM, generated, flags=re.S)
    if count != 1:
        raise AssertionError('test-only platform replacement must match exactly once')
    guard = '#error "Ru native C requires Windows x64"'
    if generated.count(guard) != 1:
        raise AssertionError('production ABI guard missing before test-only replacement')
    return generated.replace(guard, '/* POSIX owned-fixture unit test, not Windows ABI evidence. */')


@unittest.skipUnless(os.name == 'posix' and shutil.which('gcc'), 'generic C state tests require POSIX GCC')
class NativeCPortableRuntimeTests(unittest.TestCase):
    # Reuse exact Ru acceptance programs; launch compiled C directly. This is
    # intentionally not the Windows/Python parity oracle or a GUI replacement.
    callbacks = acceptance.NativeCWindowsAcceptanceTests.callbacks
    program = acceptance.NativeCWindowsAcceptanceTests.program

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.fixture = Path(cls.directory.name) / 'owned-native-fixture.so'
        result = bounded_run(['gcc', '-std=c99', '-fPIC', '-shared', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                              str(ROOT / 'tests/fixtures/native/c_backend_bridge.c'), '-o', str(cls.fixture)], timeout=60)
        if result.returncode:
            raise AssertionError(result.stderr)

    def build_executable(self, source, directory, *, full=False):
        directory = Path(directory)
        script, cfile, executable = directory / 'program.ru', directory / 'program.c', directory / 'program'
        script.write_text(source, encoding='utf-8')
        cfile.write_text(portable_test_source(source, str(script), full=full), encoding='utf-8')
        command = ['gcc', '-std=c99', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-pedantic',
                   str(cfile), '-o', str(executable), '-lm', '-ldl', '-pthread']
        # Optional sanitizer run uses the same exact test artifacts. LeakSanitizer
        # can be unavailable in ptrace sandboxes; do not imply a leak check then.
        if os.environ.get('RU_NATIVE_TEST_SANITIZE') == '1':
            command[1:1] = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-g']
        result = bounded_run(command, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '', 'native C produced compiler warnings')
        return executable, script

    def run_executable(self, executable, *, timeout=45, arguments=()):
        env = dict(os.environ, RU_GC_THRESHOLD='1', RU_GC_STATS='1')
        result = bounded_run([str(executable), *arguments], timeout=timeout, env=env)
        if result.returncode == 0:
            self.assertRegex(result.stderr, r'RU_GC live=0 freed=\d+ collections=\d+\n')
            result.stderr = re.sub(r'RU_GC live=0 freed=\d+ collections=\d+\n', '', result.stderr)
        return result

    def assert_native_parity(self, body, expected, *, success=True):
        with tempfile.TemporaryDirectory() as directory:
            executable, _ = self.build_executable(self.program(body), directory)
            result = self.run_executable(executable)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        self.assertEqual(result.stdout, expected, result.stderr)
        self.assertEqual(result.stderr, '')
        return result, result

    test_exact_values_struct_layout_unicode = acceptance.NativeCWindowsAcceptanceTests.test_exact_integer_pointer_bounds_and_struct_layout
    test_mixed_scalar_abi_shape = acceptance.NativeCWindowsAcceptanceTests.test_mixed_gp_xmm_and_stack_arguments_in_both_directions
    test_nested_callback_and_panic = acceptance.NativeCWindowsAcceptanceTests.test_nested_synchronous_callback_and_native_return_after_error
    test_ordinary_error_and_recovery = acceptance.NativeCWindowsAcceptanceTests.test_runtime_error_uses_fallback_and_allows_later_native_call
    test_failure_hook_recursion = acceptance.NativeCWindowsAcceptanceTests.test_failure_hook_recursion_preserves_first_error
    test_tombstone_after_close = acceptance.NativeCWindowsAcceptanceTests.test_closed_callback_tombstone_returns_fallback_without_ru
    test_closed_active_reentry = acceptance.NativeCWindowsAcceptanceTests.test_active_closed_callback_reentry_uses_saved_fallback
    test_owned_nested_copy = acceptance.NativeCWindowsAcceptanceTests.test_owned_pointer_return_and_copied_nested_view_survive_forced_gc
    test_module_init_boundary = acceptance.NativeCWindowsAcceptanceTests.test_first_callback_module_initialization_is_contained_and_retryable

    def test_full_runtime_unicode_and_nested_view_lifetime(self):
        source = """密 取 外言 '如:密'.
文 取 密 其 UTF16 '你好，如 😀'. 显 文 其 解UTF16.
零 取 密 其 UTF16 ''. 显 零 其 解UTF16.
型 取 密 其 结构 [['n',密 其 i64]].
复型 取 密 其 结构 [['inner',型]].
深型 取 密 其 结构 [['middle',复型]].
深 取 深型 其 新建. 中 取 深 其 读 'middle'. 内 取 中 其 读 'inner'.
内 其 写 'n' ((密 其 i64) 其 值 '-9223372036854775808').
显 (内 其 读 'n') 其 句.
文 其 关闭. 零 其 关闭. 深 其 关闭.
"""
        with tempfile.TemporaryDirectory() as directory:
            executable, _ = self.build_executable(source, directory, full=True)
            result = self.run_executable(executable)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, '你好，如 😀\n\n-9223372036854775808\n')
        self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
