"""Ru-declared Win32 integration: real HWNDs, real BUTTON clicks, bounded subprocesses.

Non-Windows hosts still parse the bundled source. A skipped Windows test is not
native execution evidence. No Python GUI implementation or replacement mocks.
"""
import ctypes
import os
from pathlib import Path
import platform
import queue
import threading
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.frontend import parse, validate

BUNDLE = ROOT / 'rulang' / 'thirdparty' / '如见'
EXAMPLES = ROOT / 'examples' / 'native'
WINDOWS_X64 = (sys.platform == 'win32' and ctypes.sizeof(ctypes.c_void_p) == 8
               and platform.machine().lower() in ('amd64', 'x86_64'))


def cli_run(source, *, timeout=45):
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
    try:
        return subprocess.run([sys.executable, str(ROOT / 'ru'), 'run', '--allow-native', str(source)],
                              cwd=str(ROOT), text=True, encoding='utf-8',
                              capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as error:
        raise AssertionError(
            f'Ru native subprocess exceeded {timeout}s; '
            f'stdout={error.stdout!r}; stderr={error.stderr!r}') from error


class RuJianSourceTests(unittest.TestCase):
    def test_bundle_and_separate_native_examples_parse_and_validate(self):
        paths = sorted(BUNDLE.glob('*.ru')) + sorted(EXAMPLES.glob('rujian*.ru'))
        self.assertGreaterEqual(len(paths), 4)
        for path in paths:
            with self.subTest(path=path.name):
                validate(parse(path.read_text(encoding='utf-8')))

    def test_bundle_is_ru_and_uses_generic_native_import(self):
        self.assertFalse(list(BUNDLE.rglob('*.py')))
        low = (BUNDLE / 'win32.ru').read_text(encoding='utf-8')
        high = (BUNDLE / '如见.ru').read_text(encoding='utf-8')
        self.assertIn("外言 '如:密'", low)
        self.assertIn("外言 '如:密'", high)
        self.assertIn("'GetMessageW'", low)
        self.assertIn("'CreateWindowExW'", low)
        self.assertIn('失败时', high)
        self.assertNotIn("外言 '如:见'", high)
        for path in EXAMPLES.glob('rujian*.ru'):
            self.assertIn("外言 '如见'", path.read_text(encoding='utf-8'))


@unittest.skipUnless(WINDOWS_X64, 'requires a Windows x64 Python process and usable desktop')
class RuJianWindowsTests(unittest.TestCase):
    def run_source(self, text, expected=None, *, success=True):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'rujian_test.ru'
            source.write_text(text, encoding='utf-8')
            result = cli_run(source)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + '\n' + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + '\n' + result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertNotIn('Exception ignored on calling ctypes callback', result.stderr)
        if expected is not None:
            self.assertEqual(result.stdout, expected, result.stderr)
        return result

    def prelude(self):
        name = 'RuJian.Test.' + uuid.uuid4().hex
        return f"""
见 取 外言 '如见'.
密 取 外言 '如:密'.
W 取 见 其 Win32.
算 确认 成果:
    若 (成果 其 回调错误) != 空 则 卒 (成果 其 回调错误). 然
    得 成果 其 值.
法
作 断言 条件 为 事实, 说明 为 句:
    若 非 条件 则 卒 说明. 然
为
类名 取 '{name}'.
"""

    def test_windows_x64_struct_sizes_alignments_and_every_offset(self):
        source = self.prelude() + '''
显 (W 其 WNDCLASSEXW) 其 大小.
显 (W 其 WNDCLASSEXW) 其 对齐.
'''
        for field in ('cbSize', 'style', 'lpfnWndProc', 'cbClsExtra', 'cbWndExtra', 'hInstance',
                      'hIcon', 'hCursor', 'hbrBackground', 'lpszMenuName', 'lpszClassName', 'hIconSm'):
            source += f"显 (W 其 WNDCLASSEXW) 其 偏移 '{field}'.\n"
        source += '显 (W 其 POINT) 其 大小. 显 (W 其 POINT) 其 对齐.\n'
        for field in ('x', 'y'):
            source += f"显 (W 其 POINT) 其 偏移 '{field}'.\n"
        source += '显 (W 其 MSG) 其 大小. 显 (W 其 MSG) 其 对齐.\n'
        for field in ('hwnd', 'message', 'wParam', 'lParam', 'time', 'pt', 'lPrivate'):
            source += f"显 (W 其 MSG) 其 偏移 '{field}'.\n"
        expected = [80, 8, 0, 4, 8, 16, 20, 24, 32, 40, 48, 56, 64, 72,
                    8, 4, 0, 4, 48, 8, 0, 8, 16, 24, 32, 36, 44]
        self.run_source(source, ''.join(f'{value}\n' for value in expected))

    def test_real_hidden_window_button_and_message_loop_example(self):
        result = cli_run(EXAMPLES / 'rujian_hidden.ru')
        self.assertEqual(result.returncode, 0, result.stdout + '\n' + result.stderr)
        self.assertEqual(result.stdout, '如见隐藏窗口：点击、Unicode 标题、消息循环与清理通过\n')
        self.assertEqual(result.stderr, '')

    def test_click_routing_unicode_repeated_cycles_and_unregister(self):
        self.run_source(self.prelude() + '''
循 3 次
    窗 取 见 其 窗口 类名 '开始' 320 180.
    主柄 取 窗 其 句柄.
    点击数 取 [0].
    钮 取 窗 其 按钮 '按钮' 10 10 110 35 123 (算:
        点击数[0] 取 点击数[0]+1.
        窗 其 标题 ('中文 🌸 ' + (点击数[0] 为 句)).
        得 空.
    法).
    另钮 取 窗 其 按钮 '另一个' 10 60 110 35 124 (算: 得 空. 法).
    断言 ((确认 ((W 其 IsWindow) 其 调用 [主柄])) 其 数 == 1) '主 HWND 无效'.
    断言 ((确认 ((W 其 IsWindow) 其 调用 [钮])) 其 数 == 1) 'BUTTON HWND 无效'.
    # 假菜单、错误 ID、错误通知码、另一个真实控件，均不得误调目标处理器。
    确认 ((W 其 SendMessageW) 其 调用 [主柄,W 其 WM_COMMAND,123,0]).
    确认 ((W 其 SendMessageW) 其 调用 [主柄,W 其 WM_COMMAND,125,((密 其 intptr) 其 重释 钮)]).
    确认 ((W 其 SendMessageW) 其 调用 [主柄,W 其 WM_COMMAND,65659,((密 其 intptr) 其 重释 钮)]).
    确认 ((W 其 SendMessageW) 其 调用 [主柄,W 其 WM_COMMAND,123,((密 其 intptr) 其 重释 另钮)]).
    断言 (点击数[0] == 0) '错误通知触发点击'.
    循 3 次
        确认 ((W 其 SendMessageW) 其 调用 [钮,W 其 BM_CLICK,0,0]).
    环
    断言 (点击数[0] == 3) '真实 BUTTON 点击数错误'.
    断言 ((窗 其 取标题) == '中文 🌸 3') 'UTF16 标题错误'.
    确认 ((W 其 PostMessageW) 其 调用 [主柄,W 其 WM_CLOSE,0,0]).
    断言 ((窗 其 循环) == 0) '消息循环退出错误'.
    断言 ((确认 ((W 其 IsWindow) 其 调用 [主柄])) 其 为空) '主窗口未销毁'.
    断言 ((确认 ((W 其 IsWindow) 其 调用 [钮])) 其 为空) '子窗口未销毁'.
    窗 其 释放.
环
显 'cycles-ok'.
''', 'cycles-ok\n')

    def test_getmessage_minus_one_is_not_quit(self):
        self.run_source(self.prelude() + '''
# Use an owned, destroyed HWND, the invalid-parameter example documented by
# GetMessageW. A guessed numeric handle such as 1 is not an invalidity proof.
# https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-getmessagew
消息体 取 (W 其 MSG) 其 新建.
窗 取 见 其 窗口 类名 '无效过滤器生命周期' 300 160.
旧柄 取 窗 其 句柄.
断言 ((确认 ((W 其 IsWindow) 其 调用 [旧柄])) 其 数 == 1) '测试窗口未创建'.
窗 其 关闭.
断言 ((窗 其 循环) == 0) '销毁后的 WM_QUIT 未正常消耗'.
断言 (非 (旧柄 其 为空)) '保存的 HWND 变成了 NULL 过滤器'.
断言 ((确认 ((W 其 IsWindow) 其 调用 [旧柄])) 其 为空) '测试 HWND 尚未失效'.
断言 ((确认 ((W 其 PeekMessageW) 其 调用 [消息体,空,W 其 WM_QUIT,W 其 WM_QUIT,0])) 其 为空) '测试队列残留 WM_QUIT'.
显 'invalid-filter-ready'.
成果 取 (W 其 GetMessageW) 其 调用 [消息体,旧柄,0,0].
断言 (((成果 其 值) 其 数) == -1) 'GetMessageW 未保留有符号错误'.
断言 ((成果 其 错误码) != 0) 'GetMessageW 丢失错误码'.
消息体 其 关闭.
显 'minus-one-ok'.
''', 'invalid-filter-ready\nminus-one-ok\n')

    def test_callback_panic_and_runtime_error_are_contained_then_cleaned(self):
        for body, diagnostic in (("卒 '点击故障'.", '点击故障'), ('得 1/0.', None)):
            with self.subTest(body=body):
                source = self.prelude() + '''
窗 取 见 其 窗口 类名 '回调故障' 300 160.
主柄 取 窗 其 句柄.
钮 取 窗 其 按钮 '故障' 10 10 90 30 1 (算:
''' + body + '''
法).
成果 取 (W 其 SendMessageW) 其 调用 [钮,W 其 BM_CLICK,0,0].
断言 ((成果 其 回调错误) != 空) '回调异常未进入成果'.
窗 其 释放.
断言 ((((W 其 IsWindow) 其 调用 [主柄]) 其 值) 其 为空) '回调失败后未清理'.
显 'contained-and-cleaned'.
卒 (成果 其 回调错误).
'''
                result = self.run_source(source, 'contained-and-cleaned\n', success=False)
                if diagnostic:
                    self.assertIn(diagnostic, result.stderr)

    def test_queued_callback_failure_unblocks_and_cleans_message_loop(self):
        self.run_source(self.prelude() + '''
窗 取 见 其 窗口 类名 '队列故障' 300 160.
主柄 取 窗 其 句柄.
钮 取 窗 其 按钮 '故障' 10 10 90 30 1 (算: 卒 '队列点击故障'. 法).
确认 ((W 其 PostMessageW) 其 调用 [钮,W 其 BM_CLICK,0,0]).
故障们 取 [].
试
    窗 其 循环.
救 原因
    故障们 其 增 原因.
终
断言 ((故障们 其 量) == 1) '循环未报告一次回调失败'.
断言 (故障们[0] 其 含 '队列点击故障') '循环丢失主错误'.
断言 ((((W 其 IsWindow) 其 调用 [主柄]) 其 值) 其 为空) '循环失败后未清理'.
显 'loop-fault-ok'.
''', 'loop-fault-ok\n')

    def test_direct_release_and_callback_failure_do_not_leave_stale_quit(self):
        self.run_source(self.prelude() + '''
窗 取 见 其 窗口 类名 '第一个' 300 160.
窗 其 释放.
窗 取 见 其 窗口 类名 '故障窗口' 300 160.
钮 取 窗 其 按钮 '故障' 10 10 90 30 1 (算: 卒 '重试前故障'. 法).
故障成果 取 (W 其 SendMessageW) 其 调用 [钮,W 其 BM_CLICK,0,0].
断言 ((故障成果 其 回调错误) != 空) '未记录原生回调失败'.
窗 其 释放.
窗 取 见 其 窗口 类名 '重新创建' 300 160.
主柄 取 窗 其 句柄.
点击数 取 [0].
钮 取 窗 其 按钮 '再次点击' 10 10 90 30 1 (算:
    点击数[0] 取 点击数[0]+1.
    窗 其 关闭.
    得 空.
法).
确认 ((W 其 PostMessageW) 其 调用 [钮,W 其 BM_CLICK,0,0]).
断言 ((窗 其 循环) == 0) '重新创建后退出码错误'.
断言 (点击数[0] == 1) '消息循环提前消费了上一窗口的 WM_QUIT'.
断言 ((((W 其 IsWindow) 其 调用 [主柄]) 其 值) 其 为空) '新窗口未销毁'.
显 'retry-ok'.
''', 'retry-ok\n')

    def test_release_inside_click_finishes_and_next_loop_is_clean(self):
        for queued in (False, True):
            with self.subTest(queued=queued):
                trigger = ("确认 ((W 其 PostMessageW) 其 调用 [钮,W 其 BM_CLICK,0,0]). 断言 ((窗 其 循环) == 0) '释放后循环退出错误'." if queued else "确认 ((W 其 SendMessageW) 其 调用 [钮,W 其 BM_CLICK,0,0]).")
                self.run_source(self.prelude() + """
窗 取 见 其 窗口 类名 '处理器内释放' 300 160.
钮 取 窗 其 按钮 '释放' 10 10 90 30 1 (算:
    窗 其 释放.
    得 空.
法).
""" + trigger + """
窗二 取 见 其 窗口 类名 '下一生命周期' 300 160.
次数 取 [0].
钮二 取 窗二 其 按钮 '关闭' 10 10 90 30 1 (算:
    次数[0] 取 次数[0]+1.
    窗二 其 关闭.
    得 空.
法).
确认 ((W 其 PostMessageW) 其 调用 [钮二,W 其 BM_CLICK,0,0]).
断言 ((窗二 其 循环) == 0) '下一循环继承了错误退出码'.
断言 (次数[0] == 1) '下一循环提前消费了过期退出消息'.
显 'reentrant-release-ok'.
""", 'reentrant-release-ok\n')

    def test_release_then_create_inside_callback_rejects_and_next_loop_recovers(self):
        self.run_source(self.prelude() + """
窗 取 见 其 窗口 类名 '不允许回调中重建' 300 160.
钮 取 窗 其 按钮 '重建' 10 10 90 30 1 (算:
    窗 其 释放.
    见 其 窗口 类名 '尚未离开旧回调' 300 160.
    得 空.
法).
确认 ((W 其 PostMessageW) 其 调用 [钮,W 其 BM_CLICK,0,0]).
故障们 取 [].
试
    窗 其 循环.
救 原因
    故障们 其 增 原因.
终
断言 ((故障们 其 量) == 1) '未拒绝回调内重建'.
断言 (故障们[0] 其 含 '不能在原生回调中创建新的主窗口') '重建诊断不明确'.
断言 (非 (密 其 回调中)) '回调活动状态没有恢复'.
窗二 取 见 其 窗口 类名 '旧回调返回后重建' 300 160.
次数 取 [0].
钮二 取 窗二 其 按钮 '关闭' 10 10 90 30 1 (算:
    次数[0] 取 次数[0]+1.
    窗二 其 关闭.
    得 空.
法).
确认 ((W 其 PostMessageW) 其 调用 [钮二,W 其 BM_CLICK,0,0]).
断言 ((窗二 其 循环) == 0 且 次数[0] == 1) '重建后有过期退出消息'.
显 'callback-create-guard-ok'.
""", 'callback-create-guard-ok\n')

    def test_nested_message_loop_in_callback_is_rejected(self):
        self.run_source(self.prelude() + """
窗 取 见 其 窗口 类名 '禁止嵌套循环' 300 160.
钮 取 窗 其 按钮 '循环' 10 10 90 30 1 (算: 得 窗 其 循环. 法).
确认 ((W 其 PostMessageW) 其 调用 [钮,W 其 BM_CLICK,0,0]).
故障们 取 [].
试
    窗 其 循环.
救 原因
    故障们 其 增 原因.
终
断言 ((故障们 其 量) == 1) '未拒绝嵌套消息循环'.
断言 (故障们[0] 其 含 '不能在原生回调中启动消息循环') '嵌套循环诊断不明确'.
断言 (非 (密 其 回调中)) '回调活动状态没有恢复'.
窗二 取 见 其 窗口 类名 '嵌套拒绝后重建' 300 160.
窗二 其 关闭.
断言 ((窗二 其 循环) == 0) '嵌套拒绝后未清理'.
显 'nested-loop-guard-ok'.
""", 'nested-loop-guard-ok\n')

    def test_sent_message_inside_getmessage_release_and_failures_do_not_hang(self):
        endings = (('得 空.', None), ("卒 'sent panic'.", 'sent panic'),
                   ('得 1/0.', '原生回调失败'),
                   ("见 其 窗口 类名 '不许立即重建' 300 160. 得 空.", '不能在原生回调中创建新的主窗口'))
        for ending, diagnostic in endings:
            with self.subTest(ending=ending):
                source_text = self.prelude() + """
窗 取 见 其 窗口 类名 'GetMessage 同步回入释放' 300 160.
钮 取 窗 其 按钮 '释放' 10 10 90 30 1 (算:
    窗 其 释放.
""" + ending + """
法).
显 钮 其 句.
故障们 取 [].
试
    断言 ((窗 其 循环) == 0) 'GetMessage 同步释放未正常退出'.
救 原因
    故障们 其 增 原因.
终
"""
                if diagnostic is None:
                    source_text += "断言 ((故障们 其 量) == 0) '正常释放意外失败'.\n"
                else:
                    source_text += "断言 ((故障们 其 量) == 1) '未报告一次同步回调错误'. 断言 (故障们[0] 其 含 '" + diagnostic + "') '同步回调错误诊断丢失'.\n"
                source_text += """
断言 (非 (密 其 回调中)) '回调活动状态没有恢复'.
窗二 取 见 其 窗口 类名 '下一生命周期' 300 160.
次数 取 [0].
钮二 取 窗二 其 按钮 '关闭' 10 10 90 30 1 (算:
    次数[0] 取 次数[0]+1.
    窗二 其 关闭.
    得 空.
法).
确认 ((W 其 PostMessageW) 其 调用 [钮二,W 其 BM_CLICK,0,0]).
断言 ((窗二 其 循环) == 0 且 次数[0] == 1) '下一生命周期退出消息错误'.
显 'sent-release-ok'.
"""
                self._send_click_while_getmessage_waits(source_text)

    def _send_click_while_getmessage_waits(self, source_text):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'sent-release.ru'
            source.write_text(source_text, encoding='utf-8')
            env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
            child = subprocess.Popen([sys.executable, str(ROOT / 'ru'), 'run', '--allow-native', str(source)], cwd=ROOT, text=True, encoding='utf-8', stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            try:
                lines = queue.Queue()
                reader = threading.Thread(target=lambda: lines.put(child.stdout.readline()), daemon=True)
                reader.start()
                handle_line = lines.get(timeout=15).strip()
                self.assertTrue(handle_line.isdecimal(), handle_line)
                user32 = ctypes.WinDLL('user32.dll', use_last_error=True, winmode=0x800)
                send = user32.SendMessageTimeoutW
                send.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_size_t, ctypes.c_ssize_t, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_size_t)]
                send.restype = ctypes.c_ssize_t
                result = ctypes.c_size_t()
                # Cross-process synchronous BM_CLICK is dispatched by the
                # child's waiting GetMessage, rather than DispatchMessage.
                sent = send(int(handle_line), 245, 0, 0, 2, 5000, ctypes.byref(result))
                self.assertNotEqual(sent, 0, 'SendMessageTimeoutW failed: ' + str(ctypes.get_last_error()))
                output, error = child.communicate(timeout=15)
                self.assertEqual(child.returncode, 0, output + error)
                self.assertEqual(output, 'sent-release-ok\n', error)
                self.assertEqual(error, '')
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)

    def test_failed_registration_then_success_and_low_level_create_error(self):
        self.run_source(self.prelude() + '''
坏类名 取 ''.
循 300 次 坏类名 取 坏类名+'长'. 环
故障们 取 [].
试
    见 其 窗口 坏类名 '不可注册' 300 160.
救 原因
    故障们 其 增 原因.
终
断言 ((故障们 其 量) == 1) '超长类名注册未失败'.
窗 取 见 其 窗口 类名 '注册失败后恢复' 300 160.
窗 其 关闭.
断言 ((窗 其 循环) == 0) '注册失败后新窗口无法运行'.
名 取 密 其 UTF16 'RuJian.Class.Does.Not.Exist'.
文 取 密 其 UTF16 '不可创建'.
成果 取 (W 其 CreateWindowExW) 其 调用 [0,名,文,0,0,0,100,100,空,空,空,空].
名 其 关闭.
文 其 关闭.
断言 ((成果 其 值) 其 为空) '未知窗口类创建未失败'.
断言 ((成果 其 错误码) != 0) '创建错误丢失 Win32 错误码'.
显 'failure-recovery-ok'.
''', 'failure-recovery-ok\n')

    def test_duplicate_class_does_not_destroy_original_owner(self):
        self.run_source(self.prelude() + '''
窗 取 见 其 窗口 类名 '原窗口' 300 160.
故障们 取 [].
试
    见 其 窗口 类名 '不该创建' 300 160.
救 原因
    故障们 其 增 原因.
终
断言 ((故障们 其 量) == 1) '未拒绝重复窗口类'.
断言 ((窗 其 取标题) == '原窗口') '重复创建损坏原窗口'.
窗 其 关闭.
断言 ((窗 其 循环) == 0) '关闭后未接收 WM_QUIT'.
显 'duplicate-ok'.
''', 'duplicate-ok\n')


if __name__ == '__main__':
    unittest.main()
