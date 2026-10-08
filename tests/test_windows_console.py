"""Real Windows-console regressions; redirected pipes cannot expose this bug.

Each probe starts a fresh, hidden console, uses CP936 only in that console,
and sends its observations back in a temporary JSON file. The test runner's
console, code pages, standard streams, and environment are never changed.
Run with: python -m unittest discover -s tests -p test_windows_console.py -v
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROMPT = "输入第一数："
MOJIBAKE = "杈撳叆绗\ue0ff竴鏁帮細"
BMP_TEXT = "中文 / café / Ελληνικά"
UNICODE_TEXT = BMP_TEXT + " / 😀𐐷𠀀"


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class COORD(ctypes.Structure):
        _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

    class SMALL_RECT(ctypes.Structure):
        _fields_ = [(name, wintypes.SHORT)
                    for name in ("Left", "Top", "Right", "Bottom")]

    class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
        _fields_ = [("dwSize", COORD), ("dwCursorPosition", COORD),
                    ("wAttributes", wintypes.WORD), ("srWindow", SMALL_RECT),
                    ("dwMaximumWindowSize", COORD)]

    class KEY_CHAR(ctypes.Union):
        _fields_ = [("UnicodeChar", wintypes.WCHAR), ("AsciiChar", wintypes.CHAR)]

    class KEY_EVENT_RECORD(ctypes.Structure):
        _fields_ = [("bKeyDown", wintypes.BOOL), ("wRepeatCount", wintypes.WORD),
                    ("wVirtualKeyCode", wintypes.WORD),
                    ("wVirtualScanCode", wintypes.WORD), ("uChar", KEY_CHAR),
                    ("dwControlKeyState", wintypes.DWORD)]

    class INPUT_EVENT(ctypes.Union):
        # KEY_EVENT_RECORD and MOUSE_EVENT_RECORD are the largest union members.
        _fields_ = [("KeyEvent", KEY_EVENT_RECORD), ("padding", ctypes.c_byte * 16)]

    class INPUT_RECORD(ctypes.Structure):
        _fields_ = [("EventType", wintypes.WORD), ("Event", INPUT_EVENT)]

    class _Console:
        """Win32 access confined to the CREATE_NEW_CONSOLE probe process."""

        def __init__(self):
            self.api = ctypes.WinDLL("kernel32", use_last_error=True)
            signatures = {
                "GetStdHandle": ([wintypes.DWORD], wintypes.HANDLE),
                "GetConsoleCP": ([], wintypes.UINT),
                "GetConsoleOutputCP": ([], wintypes.UINT),
                "SetConsoleCP": ([wintypes.UINT], wintypes.BOOL),
                "SetConsoleOutputCP": ([wintypes.UINT], wintypes.BOOL),
                "GetConsoleMode": ([wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
                "SetConsoleMode": ([wintypes.HANDLE, wintypes.DWORD], wintypes.BOOL),
                "GetConsoleScreenBufferInfo": ([wintypes.HANDLE, ctypes.POINTER(CONSOLE_SCREEN_BUFFER_INFO)], wintypes.BOOL),
                "SetConsoleCursorPosition": ([wintypes.HANDLE, COORD], wintypes.BOOL),
                "FillConsoleOutputCharacterW": ([wintypes.HANDLE, wintypes.WCHAR, wintypes.DWORD, COORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
                "ReadConsoleOutputCharacterW": ([wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, COORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
                "FlushConsoleInputBuffer": ([wintypes.HANDLE], wintypes.BOOL),
                "WriteConsoleInputW": ([wintypes.HANDLE, ctypes.POINTER(INPUT_RECORD), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            }
            for name, (args, result) in signatures.items():
                function = getattr(self.api, name)
                function.argtypes, function.restype = args, result
            self.input = self.api.GetStdHandle(-10)
            self.output = self.api.GetStdHandle(-11)
            self.original_pages = self.code_pages()
            self.original_input_mode = self.mode(self.input)
            self.original_output_mode = self.mode(self.output)

        @staticmethod
        def check(success):
            if not success:
                raise ctypes.WinError(ctypes.get_last_error())

        def mode(self, handle):
            mode = wintypes.DWORD()
            self.check(self.api.GetConsoleMode(handle, ctypes.byref(mode)))
            return mode.value

        def code_pages(self):
            return [self.api.GetConsoleCP(), self.api.GetConsoleOutputCP()]

        def configure(self):
            self.check(self.api.SetConsoleCP(936))
            self.check(self.api.SetConsoleOutputCP(936))
            # Cooked input, without echo; keyboard events are real console input.
            self.check(self.api.SetConsoleMode(self.input, 0x0001 | 0x0002))
            self.check(self.api.SetConsoleMode(self.output, 0x0001 | 0x0002))

        def restore(self):
            self.check(self.api.SetConsoleMode(self.input, self.original_input_mode))
            self.check(self.api.SetConsoleMode(self.output, self.original_output_mode))
            self.check(self.api.SetConsoleCP(self.original_pages[0]))
            self.check(self.api.SetConsoleOutputCP(self.original_pages[1]))

        def clear(self):
            sys.stdout.flush()
            sys.stderr.flush()
            info = CONSOLE_SCREEN_BUFFER_INFO()
            self.check(self.api.GetConsoleScreenBufferInfo(self.output, ctypes.byref(info)))
            if info.dwSize.X < 60 or info.dwSize.Y < 4:
                raise AssertionError("Probe console screen buffer is unexpectedly small")
            self.width = info.dwSize.X
            written = wintypes.DWORD()
            self.check(self.api.FillConsoleOutputCharacterW(
                self.output, " ", self.width * 4, COORD(0, 0), ctypes.byref(written)))
            self.check(self.api.SetConsoleCursorPosition(self.output, COORD(0, 0)))

        def read(self, rows=1):
            # Read the wide-character screen contents, not a redirected byte pipe.
            lines = []
            for row in range(rows):
                buffer = ctypes.create_unicode_buffer(self.width + 1)
                count = wintypes.DWORD()
                self.check(self.api.ReadConsoleOutputCharacterW(
                    self.output, buffer, self.width, COORD(0, row), ctypes.byref(count)))
                text = buffer[:count.value]
                # ctypes can expose a UTF-16 surrogate pair as two characters.
                lines.append(text.encode("utf-16-le", "surrogatepass")
                             .decode("utf-16-le").rstrip(" "))
            return "\n".join(lines)

        def queue_input(self, text):
            assert ctypes.sizeof(KEY_EVENT_RECORD) == 16
            assert ctypes.sizeof(INPUT_RECORD) == 20
            self.check(self.api.FlushConsoleInputBuffer(self.input))
            utf16 = text.encode("utf-16-le")
            records = (INPUT_RECORD * len(utf16))()
            for index in range(0, len(utf16), 2):
                character = chr(int.from_bytes(utf16[index:index + 2], "little"))
                for offset, pressed in enumerate((True, False)):
                    record = records[index + offset]
                    record.EventType = 0x0001  # KEY_EVENT
                    key = record.Event.KeyEvent
                    key.bKeyDown, key.wRepeatCount = pressed, 1
                    key.uChar.UnicodeChar = character
                    if character == "\r":
                        key.wVirtualKeyCode, key.wVirtualScanCode = 0x0D, 0x1C
            written = wintypes.DWORD()
            self.check(self.api.WriteConsoleInputW(
                self.input, records, len(records), ctypes.byref(written)))
            if written.value != len(records):
                raise AssertionError("Could not queue all console keyboard events")


def _console_probe(kind, unbuffered):
    import _io

    sys.path.insert(0, str(ROOT))
    from rulang.io_runtime import _write_stream, read_stream_line

    console = _Console()
    result = {"streams": {}, "observations": {}, "python_controls": {}}
    try:
        console.configure()
        for name in ("stdin", "stdout", "stderr"):
            stream = getattr(sys, name)
            raw = getattr(stream.buffer, "raw", stream.buffer)
            if not isinstance(raw, _io._WindowsConsoleIO):
                raise AssertionError(f"{name} must use a real _WindowsConsoleIO, got {type(raw)!r}")
            result["streams"][name] = type(stream.buffer).__name__
        if kind in ("output", "legacy"):
            for name in ("stdout", "stderr"):
                stream = getattr(sys, name)
                for content in ((PROMPT, BMP_TEXT, UNICODE_TEXT) if kind == "output" else (PROMPT,)):
                    console.clear()
                    if kind == "legacy":
                        # This is the pre-fix operation, deliberately bypassing
                        # Python's Unicode console layer under a non-UTF-8 page.
                        os.write(stream.fileno(), content.encode("utf-8"))
                    else:
                        # Check that preceding buffered text is flushed in order.
                        stream.write("prefix:")
                        _write_stream(stream, content)
                    result["observations"][name + ":" + content] = console.read()
                    if kind == "output":
                        # Some console hosts' screen-reading APIs cannot return
                        # astral characters faithfully. Compare with a separate
                        # standard Python Unicode write on the same console;
                        # BMP text and the reported prompt still require literal
                        # equality, independently of this control.
                        console.clear()
                        stream.write("prefix:" + content)
                        stream.flush()
                        result["python_controls"][name + ":" + content] = console.read()
        elif kind == "cli":
            console.clear()
            console.queue_input("2\r3\r")
            command = [sys.executable, "-E"] + (["-u"] if unbuffered else [])
            completed = subprocess.run(
                command + ["-m", "rulang", "run", str(ROOT / "examples" / "add.ru")],
                cwd=ROOT, timeout=20)
            result["returncode"] = completed.returncode
            # Cooked console Enter advances the cursor even with echo disabled.
            result["observations"]["add.ru"] = console.read(rows=3)
        elif kind == "input":
            console.queue_input(UNICODE_TEXT + "\r")
            result["observations"]["stdin"] = read_stream_line(sys.stdin)
        else:
            raise AssertionError(f"Unknown console probe: {kind}")
        result["code_pages_after_operation"] = console.code_pages()
    finally:
        console.restore()
    result["original_code_pages"] = console.original_pages
    result["restored_code_pages"] = console.code_pages()
    return result


@unittest.skipUnless(os.name == "nt", "requires the Windows console APIs")
class WindowsConsoleTests(unittest.TestCase):
    def probe(self, kind, unbuffered):
        with tempfile.TemporaryDirectory(prefix="ru-console-test-") as directory:
            output = Path(directory) / "result.json"
            command = [sys.executable, "-E"] + (["-u"] if unbuffered else [])
            command += [str(Path(__file__).resolve()), "--console-probe", kind,
                        str(output), str(int(unbuffered))]
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
            # No PIPE handles: CPython must construct real WindowsConsoleIO
            # streams at startup. CREATE_NEW_CONSOLE isolates all Win32 changes.
            completed = subprocess.run(
                command, cwd=ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE,
                startupinfo=startup, timeout=45)
            self.assertTrue(output.is_file(), f"Console probe produced no report (exit {completed.returncode})")
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(completed.returncode, 0, result.get("error", result))
            self.assertNotIn("error", result)
            self.assertEqual(result["code_pages_after_operation"], [936, 936])
            self.assertEqual(result["restored_code_pages"], result["original_code_pages"])
            for name in ("stdout", "stderr"):
                self.assertEqual(result["streams"][name],
                                 "_WindowsConsoleIO" if unbuffered else "BufferedWriter")
            return result

    def test_stdout_and_stderr_match_python_unicode_console_output(self):
        for unbuffered in (False, True):
            with self.subTest(unbuffered=unbuffered):
                result = self.probe("output", unbuffered)
                for name in ("stdout", "stderr"):
                    for content in (PROMPT, BMP_TEXT):
                        self.assertEqual(result["observations"][name + ":" + content],
                                         "prefix:" + content)
                    for content in (PROMPT, BMP_TEXT, UNICODE_TEXT):
                        self.assertEqual(result["observations"][name + ":" + content],
                                         result["python_controls"][name + ":" + content])

    def test_old_raw_descriptor_write_reproduces_reported_mojibake(self):
        self.assertEqual(PROMPT.encode("utf-8").decode("gb18030"), MOJIBAKE)
        for unbuffered in (False, True):
            with self.subTest(unbuffered=unbuffered):
                result = self.probe("legacy", unbuffered)
                for name in ("stdout", "stderr"):
                    self.assertEqual(result["observations"][name + ":" + PROMPT], MOJIBAKE)

    def test_add_example_prompts_and_result_in_real_console(self):
        for unbuffered in (False, True):
            with self.subTest(unbuffered=unbuffered):
                result = self.probe("cli", unbuffered)
                self.assertEqual(result["returncode"], 0)
                self.assertEqual(result["observations"]["add.ru"], "输入第一数：\n输入第二数：\n5")

    def test_console_input_preserves_unicode_and_astral_characters(self):
        for unbuffered in (False, True):
            with self.subTest(unbuffered=unbuffered):
                result = self.probe("input", unbuffered)
                self.assertEqual(result["observations"]["stdin"], UNICODE_TEXT + "\r\n")


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--console-probe":
        try:
            report = _console_probe(sys.argv[2], bool(int(sys.argv[4])))
            status = 0
        except BaseException:
            report = {"error": traceback.format_exc()}
            status = 1
        Path(sys.argv[3]).write_text(json.dumps(report, ensure_ascii=True), encoding="utf-8")
        raise SystemExit(status)
    unittest.main()
