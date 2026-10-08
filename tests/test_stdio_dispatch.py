"""Cross-platform checks for immediate, checked standard-stream writes."""
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rulang import io_runtime


class FakeConsole:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result
        self.error = error

    def write(self, data):
        self.calls.append(data)
        if self.error:
            raise self.error
        return len(data) if self.result is None else self.result


class StdioDispatchTests(unittest.TestCase):
    def test_buffered_and_unbuffered_console_stdout_and_stderr_use_unicode_raw_io(self):
        for target in ('stdout', 'stderr'):
            for buffered in (False, True):
                with self.subTest(target=target, buffered=buffered):
                    raw = FakeConsole()
                    stream = SimpleNamespace(buffer=SimpleNamespace(raw=raw) if buffered else raw,
                                             flush=mock.Mock(), fileno=mock.Mock(return_value=1))
                    with mock.patch.object(io_runtime._io, '_WindowsConsoleIO', FakeConsole, create=True), \
                         mock.patch.object(sys, target, stream), mock.patch.object(io_runtime.os, 'write') as direct:
                        io_runtime._write_stream(stream, '输入第一数：😀')
                    self.assertEqual(raw.calls, ['输入第一数：😀'.encode()])
                    stream.flush.assert_called_once_with()
                    direct.assert_not_called()
                    stream.fileno.assert_not_called()

    def test_console_short_write_and_error_are_not_silently_accepted(self):
        for raw, expected in ((FakeConsole(result=1), OSError),
                              (FakeConsole(error=BrokenPipeError('closed')), BrokenPipeError)):
            stream = SimpleNamespace(buffer=raw, flush=mock.Mock())
            with mock.patch.object(io_runtime._io, '_WindowsConsoleIO', FakeConsole, create=True), \
                 mock.patch.object(sys, 'stdout', stream), self.assertRaises(expected):
                io_runtime._write_stream(stream, '提示')
            self.assertEqual(len(raw.calls), 1)

    def test_redirected_output_keeps_direct_checked_write(self):
        for target in ('stdout', 'stderr'):
            stream = SimpleNamespace(buffer=io.BytesIO(), flush=mock.Mock(), fileno=lambda: 42)
            with mock.patch.object(sys, target, stream), \
                 mock.patch.object(io_runtime.os, 'write', return_value=6) as direct:
                io_runtime._write_stream(stream, '提示')
            direct.assert_called_once_with(42, '提示'.encode())
            self.assertEqual(stream.buffer.getvalue(), b'')

    def test_redirected_short_write_and_failure_remain_immediate(self):
        for result, error, expected in ((1, None, OSError),
                                        (None, BrokenPipeError('closed'), BrokenPipeError)):
            stream = SimpleNamespace(buffer=io.BytesIO(), flush=mock.Mock(), fileno=lambda: 42)
            with mock.patch.object(sys, 'stdout', stream), \
                 mock.patch.object(io_runtime.os, 'write', return_value=result, side_effect=error), \
                 self.assertRaises(expected):
                io_runtime._write_stream(stream, '提示')
            self.assertEqual(stream.buffer.getvalue(), b'')

    def test_injected_text_stream_keeps_ordinary_protocol(self):
        stream = io.StringIO()
        io_runtime._write_stream(stream, '中文😀')
        self.assertEqual(stream.getvalue(), '中文😀')


if __name__ == '__main__':
    unittest.main()
