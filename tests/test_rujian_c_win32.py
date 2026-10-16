"""The real Win32 lifecycle suite, executed as Python-free compiled Ru programs.

The source oracle is intentionally shared with test_rujian_win32. Every child
launch path is replaced here: neither normal programs, the bundled example, nor
the sent-message case invokes the interpreter. Python is only the test driver;
its sole GUI operation sends BM_CLICK to the real HWND printed by the C child.
"""
import ctypes
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import unittest

import test_native_c_backend as native_c
import test_rujian_win32 as source_cases


@unittest.skipUnless(native_c.WINDOWS_X64, 'requires Windows x64 and a usable desktop')
class RuJianCompiledWindowsTests(native_c.NativeExecutableMixin,
                                 source_cases.RuJianWindowsTests):
    def run_source(self, text, expected=None, *, success=True):
        with tempfile.TemporaryDirectory() as directory:
            executable, _ = self.build_executable(text, directory)
            result = self.run_executable(executable)
        self.assertEqual(result.returncode == 0, success,
                         result.stdout + '\n' + result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertNotIn('Exception ignored on calling ctypes callback', result.stderr)
        if expected is not None:
            self.assertEqual(result.stdout, expected, result.stderr)
        if success:
            self.assertEqual(result.stderr, '')
        return result

    def test_real_hidden_window_button_and_message_loop_example(self):
        source = (source_cases.EXAMPLES / 'rujian_hidden.ru').read_text(encoding='utf-8')
        self.run_source(source, '如见隐藏窗口：点击、Unicode 标题、消息循环与清理通过\n')

    def _send_click_while_getmessage_waits(self, source_text):
        with tempfile.TemporaryDirectory() as directory:
            executable, _ = self.build_executable(source_text, directory)
            working = Path(directory) / 'empty-working-directory'
            working.mkdir()
            child = subprocess.Popen(
                [str(executable)], cwd=working, env=native_c.native_environment(),
                text=True, encoding='utf-8', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                lines = queue.Queue()
                reader = threading.Thread(target=lambda: lines.put(child.stdout.readline()),
                                          daemon=True)
                reader.start()
                try:
                    handle_line = lines.get(timeout=15).strip()
                except queue.Empty as error:
                    raise AssertionError('compiled child did not publish its BUTTON HWND within 15s') from error
                self.assertTrue(handle_line.isdecimal(), handle_line)
                user32 = ctypes.WinDLL('user32.dll', use_last_error=True, winmode=0x800)
                send = user32.SendMessageTimeoutW
                send.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_size_t,
                                 ctypes.c_ssize_t, ctypes.c_uint32, ctypes.c_uint32,
                                 ctypes.POINTER(ctypes.c_size_t)]
                send.restype = ctypes.c_ssize_t
                native_result = ctypes.c_size_t()
                # Only a Win32 test-driver hook. The compiled child's waiting
                # GetMessage dispatches this synchronous cross-process BM_CLICK.
                sent = send(int(handle_line), 245, 0, 0, 2, 5000,
                            ctypes.byref(native_result))
                self.assertNotEqual(sent, 0, 'SendMessageTimeoutW failed: '
                                    + str(ctypes.get_last_error()))
                try:
                    output, error = child.communicate(timeout=15)
                except subprocess.TimeoutExpired as exception:
                    raise AssertionError('compiled GetMessage callback did not return within 15s') from exception
                self.assertEqual(child.returncode, 0, output + error)
                self.assertEqual(output, 'sent-release-ok\n', error)
                self.assertEqual(error, '')
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
