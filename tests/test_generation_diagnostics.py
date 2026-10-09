"""CLI generation diagnostics stay local, truthful, and separate from source."""
import contextlib
import io
from pathlib import Path
import re
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rulang.cli import _GenerationProgress, main
from rulang.generation import GenerationError


STAGES = (
    "读取意图文档", "检查生成配置", "发送生成请求", "等待提供方响应",
    "收到提供方响应", "检查生成源码", "生成源码检查完成", "发布生成文件",
)


class GenerationDiagnosticsTests(unittest.TestCase):
    def invoke(self, arguments, generation):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("rulang.cli.generate", side_effect=generation) as call, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main(["generate", "intent.md", *arguments])
        return status, stdout.getvalue(), stderr.getvalue(), call

    def test_verbose_is_opt_in_and_default_timeout_is_preserved(self):
        with patch("rulang.cli.threading.Thread") as thread:
            status, stdout, stderr, call = self.invoke([], lambda *args, **kwargs: Path("out.ru"))
        self.assertEqual(status, 0)
        self.assertIn("out.ru", stdout)
        self.assertEqual(stderr, "")
        call.assert_called_once_with("intent.md", None, 1800.0, target="ru", stdout=False, progress=None)
        thread.assert_not_called()

    def test_verbose_emits_only_actual_stage_callbacks_in_order(self):
        reporters = []

        def generation(*args, progress, **kwargs):
            reporters.append(progress.__self__)
            for stage in STAGES:
                progress(stage)
            return Path("out.ru")

        status, stdout, stderr, call = self.invoke(["--verbose"], generation)
        self.assertEqual(status, 0)
        self.assertIn("out.ru", stdout)
        self.assertEqual([re.sub(r"^\[生成 [0-9]+\.[0-9]s\] ", "", line)
                          for line in stderr.splitlines()], list(STAGES))
        self.assertNotIn("%", stderr)
        self.assertEqual(call.call_count, 1)
        self.assertFalse(reporters[0].thread.is_alive())

    def test_stdout_ru_and_js_contain_only_complete_source(self):
        for target, source in (("ru", "显 '已检查'.\n"),
                               ("js", '"use strict";\nconsole.log("已检查");\n')):
            with self.subTest(target=target):
                def generation(*args, progress, **kwargs):
                    for stage in STAGES[:-1]:
                        progress(stage)
                    return source

                status, stdout, stderr, call = self.invoke(
                    ["--verbose", "--stdout", "--target", target, "--timeout", "3600"], generation)
                self.assertEqual(status, 0)
                self.assertEqual(stdout, source)
                self.assertIn("生成源码检查完成", stderr)
                self.assertIn("未执行", stderr)
                self.assertNotIn("发布生成文件", stderr)
                self.assertEqual(call.call_args.args[2], 3600)
                self.assertEqual(call.call_args.kwargs["target"], target)
                self.assertTrue(call.call_args.kwargs["stdout"])

    def test_non_verbose_stdout_keeps_existing_review_notice(self):
        status, stdout, stderr, call = self.invoke(
            ["--stdout"], lambda *args, **kwargs: "显 '已检查'.\n")
        self.assertEqual(status, 0)
        self.assertEqual(stdout, "显 '已检查'.\n")
        self.assertEqual(stderr, "已生成并检查；未执行，请先审阅源码。\n")
        self.assertIsNone(call.call_args.kwargs["progress"])

    def test_wait_updates_include_elapsed_time_without_another_request(self):
        heartbeat = threading.Event()
        reporters = []

        class Capture(io.StringIO):
            def write(self, text):
                result = super().write(text)
                if "已等待" in text:
                    heartbeat.set()
                return result

        def generation(*args, progress, **kwargs):
            reporter = progress.__self__
            reporters.append(reporter)
            progress("发送生成请求")
            progress("等待提供方响应")
            self.assertTrue(heartbeat.wait(2), "No wait heartbeat was emitted")
            progress("收到提供方响应")
            return "显 '已检查'.\n"

        stdout, stderr = io.StringIO(), Capture()
        with patch.object(_GenerationProgress, "INTERVAL", 0.01), \
                patch("rulang.cli.generate", side_effect=generation) as call, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(main(["generate", "intent.md", "--stdout", "--verbose"]), 0)
        self.assertEqual(stdout.getvalue(), "显 '已检查'.\n")
        self.assertRegex(stderr.getvalue(), r"\[生成 [0-9]+\.[0-9]s\] 等待提供方响应（已等待 [0-9]+\.[0-9]s）")
        self.assertEqual(call.call_count, 1)
        self.assertTrue(reporters[0].thread.daemon)
        self.assertFalse(reporters[0].thread.is_alive())
        self.assertTrue(reporters[0].stopped.is_set())
        self.assertNotIn("已等待", stderr.getvalue().split("收到提供方响应", 1)[1])

    def test_stage_elapsed_time_uses_monotonic_clock(self):
        stderr = io.StringIO()
        with patch("rulang.cli.time.monotonic", side_effect=(100.0, 103.5)), \
                contextlib.redirect_stderr(stderr):
            with _GenerationProgress(True) as reporter:
                reporter.stage("读取意图文档")
        self.assertEqual(stderr.getvalue(), "[生成 3.5s] 读取意图文档\n")

    def test_untrusted_progress_text_is_never_printed(self):
        unsafe = (
            "Authorization: Bearer FAKE_SECRET", "https://example.test/?key=FAKE_SECRET",
            "request body: PRIVATE_INTENT", "response body: PRIVATE_RESPONSE",
            "等待提供方响应\nFAKE_SECRET", {"api-key": "FAKE_SECRET"}, None,
        )

        def generation(*args, progress, **kwargs):
            for stage in unsafe:
                progress(stage)
            progress("检查生成源码")
            return "显 '安全'.\n"

        status, stdout, stderr, _call = self.invoke(["--stdout", "--verbose"], generation)
        self.assertEqual(status, 0)
        self.assertEqual(stdout, "显 '安全'.\n")
        self.assertIn("检查生成源码", stderr)
        for value in ("FAKE_SECRET", "PRIVATE_INTENT", "PRIVATE_RESPONSE", "Authorization", "https://"):
            self.assertNotIn(value, stdout + stderr)

    def test_safe_generation_errors_go_to_stderr_and_stop_reporter(self):
        messages = (
            "TLS 证书验证失败；未自动重试",
            "Responses 请求失败（HTTP 401）；未自动重试",
            "Responses 请求超时；服务端可能已经计费",
            "Responses 网络连接失败；未自动重试",
            "Responses 响应中断；服务端可能已经计费",
        )
        for message in messages:
            with self.subTest(message=message):
                reporters = []

                def generation(*args, progress, **kwargs):
                    reporters.append(progress.__self__)
                    progress("等待提供方响应")
                    raise GenerationError(message)

                status, stdout, stderr, call = self.invoke(["--stdout", "--verbose"], generation)
                self.assertEqual(status, 1)
                self.assertEqual(stdout, "")
                self.assertIn(message, stderr)
                self.assertNotIn("生成源码检查完成", stderr)
                self.assertNotIn("Traceback", stderr)
                self.assertEqual(call.call_count, 1)
                self.assertFalse(reporters[0].thread.is_alive())

    def test_keyboard_interrupt_stops_reporter_before_returning(self):
        reporters = []

        def generation(*args, progress, **kwargs):
            reporters.append(progress.__self__)
            progress("等待提供方响应")
            raise KeyboardInterrupt

        status, stdout, stderr, call = self.invoke(["--stdout", "--verbose"], generation)
        self.assertEqual(status, 130)
        self.assertEqual(stdout, "")
        self.assertIn("已取消", stderr)
        self.assertEqual(call.call_count, 1)
        self.assertFalse(reporters[0].thread.is_alive())

    def test_unexpected_exception_still_stops_reporter(self):
        reporters = []

        def generation(*args, progress, **kwargs):
            reporters.append(progress.__self__)
            raise RuntimeError("local test failure")

        with self.assertRaisesRegex(RuntimeError, "local test failure"):
            self.invoke(["--stdout", "--verbose"], generation)
        self.assertFalse(reporters[0].thread.is_alive())

    def test_closed_diagnostic_stream_does_not_escape_reporter(self):
        stream = io.StringIO()
        stream.close()
        with contextlib.redirect_stderr(stream):
            with _GenerationProgress(True) as reporter:
                reporter.stage("等待提供方响应")
                reporter.stage("收到提供方响应")
        self.assertTrue(reporter.stopped.is_set())
        self.assertFalse(reporter.thread.is_alive())

    def test_generate_help_explains_verbose_stderr_and_wait_updates(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as caught:
            main(["generate", "--help"])
        self.assertEqual(caught.exception.code, 0)
        text = stdout.getvalue()
        for expected in ("--verbose", "标准错误", "10", "进度百分比", "--stdout", "1800"):
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
