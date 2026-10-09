"""Explicit CLI execution uses only fixed, locally controlled generated fixtures.

Provider calls are mocked or go to a loopback fixture server with the documented
public dummy token. These tests never load user configuration or model output.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rulang.cli import main, make_parser
from test_generation import (
    DUMMY, MockResponses, TemporaryGeneration, isolated_process_env, response_for,
)

NODE = shutil.which("node")


class GenerationRunTests(TemporaryGeneration):
    def setUp(self):
        super().setUp()
        self.config.write_text(json.dumps({
            "api-key": DUMMY, "base-url": "https://example.test/v1", "model": "mock-model",
        }), encoding="utf-8")
        self.fixture = "显 '安全的本地样例'.\n"

    def invoke(self, arguments=(), source=None, input_text=""):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, self.env, clear=True), \
                patch("rulang.generation.request_response", return_value=source or self.fixture) as provider, \
                patch("sys.stdin", io.StringIO(input_text)), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main(["generate", str(self.document), *arguments])
        return status, stdout.getvalue(), stderr.getvalue(), provider

    def test_default_stays_non_executing_for_both_targets(self):
        self.assertFalse(make_parser().parse_args(["generate", "wish.md"]).run)
        for target in ("ru", "js"):
            with self.subTest(target=target), \
                    patch("rulang.cli.Interpreter", side_effect=AssertionError("execute Ru")), \
                    patch("rulang.cli.subprocess.run", side_effect=AssertionError("execute Node")), \
                    patch("rulang.cli.shutil.which", side_effect=AssertionError("look up Node")):
                status, stdout, stderr, provider = self.invoke(["--target", target])
            self.assertEqual(status, 0, stderr)
            self.assertIn("未执行", stdout)
            self.assertEqual(stderr, "")
            self.assertTrue(self.document.with_suffix(".generated." + target).is_file())
            provider.assert_called_once()

    def test_run_and_stdout_conflict_before_config_network_or_node_lookup(self):
        for arguments in (("--run", "--stdout"), ("--stdout", "--run"),
                          ("--target", "js", "--run", "--stdout")):
            with self.subTest(arguments=arguments), \
                    patch("rulang.cli.generate", side_effect=AssertionError("generate")) as generation, \
                    patch("rulang.generation.load_config", side_effect=AssertionError("read config")), \
                    patch("rulang.generation.request_response", side_effect=AssertionError("network")), \
                    patch("rulang.cli.shutil.which", side_effect=AssertionError("Node lookup")), \
                    contextlib.redirect_stderr(io.StringIO()) as stderr, \
                    self.assertRaises(SystemExit) as caught:
                main(["generate", "missing.md", *arguments])
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("--run", stderr.getvalue())
            self.assertIn("--stdout", stderr.getvalue())
            generation.assert_not_called()

    def test_default_ru_output_is_published_then_run_once(self):
        output = self.document.with_suffix(".generated.ru")
        from rulang.interpreter import Interpreter
        execute = Interpreter.execute

        def verify_published(interpreter, *args, **kwargs):
            self.assertEqual(output.read_text(encoding="utf-8"), self.fixture)
            return execute(interpreter, *args, **kwargs)

        with patch.object(Interpreter, "execute", verify_published):
            status, stdout, stderr, provider = self.invoke(["--run"])
        self.assertEqual(status, 0, stderr)
        self.assertEqual(stdout, "安全的本地样例\n")
        self.assertIn(str(output), stderr)
        self.assertIn("正在运行", stderr)
        self.assertNotIn("未执行", stderr)
        self.assertEqual(output.read_text(encoding="utf-8"), self.fixture)
        provider.assert_called_once()

    def test_explicit_output_entry_stdin_stdout_and_exit_status_match_run(self):
        output = self.root / "chosen.ru"
        source = "显 '顶层'. 算 元初 外参 为 句 阵: 显 外参 其 量. 显 读. 得 7. 法\n"
        status, stdout, stderr, provider = self.invoke(
            ["--run", "-o", str(output)], source, "输入😀\n")
        self.assertEqual((status, stdout), (7, "顶层\n0\n输入😀\n"), stderr)
        self.assertEqual(output.read_text(encoding="utf-8"), source)
        provider.assert_called_once()
        ordinary_stdout, ordinary_stderr = io.StringIO(), io.StringIO()
        with patch("sys.stdin", io.StringIO("输入😀\n")), \
                contextlib.redirect_stdout(ordinary_stdout), contextlib.redirect_stderr(ordinary_stderr), \
                patch("rulang.generation.load_config", side_effect=AssertionError("configuration")):
            ordinary_status = main(["run", str(output)])
        self.assertEqual((status, stdout), (ordinary_status, ordinary_stdout.getvalue()))
        self.assertEqual(ordinary_stderr.getvalue(), "")

    def test_output_directory_controls_local_import_resolution(self):
        folder = self.root / "generated"
        folder.mkdir()
        (folder / "lib.ru").write_text("值 取 '依赖样例'.\n", encoding="utf-8")
        output = folder / "program.ru"
        source = "库 取 外言 'lib.ru'. 显 库 其 值.\n"
        status, stdout, stderr, provider = self.invoke(["--run", "-o", str(output)], source)
        self.assertEqual((status, stdout), (0, "依赖样例\n"), stderr)
        self.assertTrue(output.is_file())
        provider.assert_called_once()

    def test_ru_runtime_error_keeps_published_source_and_diagnostic_location(self):
        output = self.root / "failed.ru"
        source = "显 '运行前'.\n卒 '安全样例错误'.\n"
        status, stdout, stderr, provider = self.invoke(["--run", "-o", str(output)], source)
        self.assertEqual(status, 1)
        self.assertEqual(stdout, "运行前\n")
        self.assertIn(str(output), stderr)
        self.assertIn("安全样例错误", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertEqual(output.read_text(encoding="utf-8"), source)
        provider.assert_called_once()

    def test_invalid_entry_exit_is_a_runtime_error_and_keeps_source(self):
        source = "算 元初 外参 为 句 阵: 得 256. 法\n"
        status, stdout, stderr, provider = self.invoke(["--run"], source)
        self.assertEqual((status, stdout), (1, ""))
        self.assertIn("0 至 255", stderr)
        self.assertEqual(self.document.with_suffix(".generated.ru").read_text(encoding="utf-8"), source)
        provider.assert_called_once()

    def test_validation_failure_never_runs_or_publishes(self):
        with patch("rulang.cli.Interpreter", side_effect=AssertionError("execute")) as interpreter:
            status, stdout, stderr, provider = self.invoke(["--run"], "not valid generated source")
        self.assertEqual((status, stdout), (1, ""))
        self.assertIn("未通过", stderr)
        self.assertFalse(self.document.with_suffix(".generated.ru").exists())
        interpreter.assert_not_called()
        provider.assert_called_once()

    def test_publication_failure_never_runs(self):
        with patch("rulang.generation.os.link", side_effect=OSError("fixture publication failure")), \
                patch("rulang.cli.Interpreter", side_effect=AssertionError("execute")) as interpreter:
            status, stdout, stderr, provider = self.invoke(["--run"])
        self.assertEqual((status, stdout), (1, ""))
        self.assertIn("保存生成文件失败", stderr)
        self.assertFalse(self.document.with_suffix(".generated.ru").exists())
        interpreter.assert_not_called()
        provider.assert_called_once()

    def test_existing_output_is_neither_overwritten_nor_run(self):
        output = self.root / "previous.ru"
        output.write_text("显 '先前文件'.\n", encoding="utf-8")
        with patch("rulang.cli.Interpreter", side_effect=AssertionError("execute")):
            status, stdout, stderr, provider = self.invoke(["--run", "-o", str(output)])
        self.assertEqual((status, stdout), (1, ""))
        self.assertIn("输出路径已存在", stderr)
        self.assertEqual(output.read_text(encoding="utf-8"), "显 '先前文件'.\n")
        provider.assert_not_called()

    def test_keyboard_interrupt_preserves_published_output(self):
        with patch("rulang.cli.Interpreter") as interpreter:
            interpreter.return_value.execute.side_effect = KeyboardInterrupt
            status, stdout, stderr, provider = self.invoke(["--run"])
        self.assertEqual((status, stdout), (130, ""))
        self.assertIn("已取消", stderr)
        self.assertTrue(self.document.with_suffix(".generated.ru").is_file())
        provider.assert_called_once()

    def test_verbose_generation_stops_before_runtime_and_stdout_is_clean(self):
        from rulang.interpreter import Interpreter
        execute = Interpreter.execute

        def verify_stopped(interpreter, *args, **kwargs):
            self.assertFalse(any(thread.name == "ru-generate-progress" for thread in threading.enumerate()))
            return execute(interpreter, *args, **kwargs)

        with patch.object(Interpreter, "execute", verify_stopped):
            status, stdout, stderr, provider = self.invoke(["--run", "--verbose", "--timeout", "3600"])
        self.assertEqual((status, stdout), (0, "安全的本地样例\n"), stderr)
        self.assertIn("发布生成文件", stderr)
        self.assertIn("正在运行", stderr)
        self.assertLess(stderr.index("发布生成文件"), stderr.index("正在运行"))
        self.assertEqual(provider.call_args.args[2], 3600)
        provider.assert_called_once()

    def test_js_uses_resolved_node_exact_published_path_and_inherited_streams(self):
        output = self.root / "spaces and 中文.cjs"
        node = str(self.root / "node executable")
        with patch("rulang.cli.shutil.which", return_value=node) as lookup, \
                patch("rulang.cli.Interpreter", side_effect=AssertionError("Ru fallback")), \
                patch("rulang.cli.subprocess.run") as launch:
            launch.return_value.returncode = 17
            status, stdout, stderr, provider = self.invoke(
                ["--run", "--target", "js", "-o", str(output)])
        self.assertEqual((status, stdout), (17, ""))
        self.assertTrue(output.is_file())
        self.assertIn("Node.js", stderr)
        self.assertFalse(self.document.with_suffix(".generated.ru").exists())
        lookup.assert_called_once_with("node")
        # No shell, pipes, captured input/output, generation timeout, or extra argv.
        launch.assert_called_once_with([node, str(output)])
        provider.assert_called_once()

    def test_missing_node_stops_before_config_network_or_artifact_creation(self):
        with patch("rulang.cli.shutil.which", return_value=None) as lookup, \
                patch("rulang.generation.load_config", side_effect=AssertionError("read config")), \
                patch("rulang.cli.generate", side_effect=AssertionError("generate")) as generation, \
                patch("rulang.cli.Interpreter", side_effect=AssertionError("Ru fallback")), \
                patch("rulang.cli.subprocess.run", side_effect=AssertionError("execute")):
            status, stdout, stderr, provider = self.invoke(["--run", "--target", "js"])
        self.assertEqual((status, stdout), (1, ""))
        self.assertIn("未找到 Node.js", stderr)
        self.assertIn("未发送生成请求", stderr)
        self.assertFalse(self.document.with_suffix(".generated.js").exists())
        lookup.assert_called_once_with("node")
        generation.assert_not_called()
        provider.assert_not_called()

    def test_node_launch_error_keeps_javascript_and_never_falls_back_to_ru(self):
        for error in (FileNotFoundError("node removed"), PermissionError("node denied")):
            output = self.root / (type(error).__name__ + ".js")
            with self.subTest(error=type(error).__name__), \
                    patch("rulang.cli.shutil.which", return_value="/fixture/node"), \
                    patch("rulang.cli.subprocess.run", side_effect=error) as launch, \
                    patch("rulang.cli.Interpreter", side_effect=AssertionError("Ru fallback")):
                status, stdout, stderr, provider = self.invoke(
                    ["--run", "--target", "js", "-o", str(output)])
            self.assertEqual((status, stdout), (1, ""))
            self.assertIn("无法启动 Node.js", stderr)
            self.assertIn("生成文件已保留", stderr)
            self.assertNotIn("Traceback", stderr)
            self.assertTrue(output.is_file())
            launch.assert_called_once()
            provider.assert_called_once()

    def test_ru_cli_subprocess_inherits_input_and_returns_entry_status(self):
        source = "显 '顶层'. 算 元初 外参 为 句 阵: 显 读. 得 7. 法\n"
        with MockResponses(response_for(source)) as server:
            result = subprocess.run(
                [sys.executable, str(ROOT / "ru"), "generate", str(self.document), "--run"],
                input="输入😀\n", capture_output=True, text=True, encoding="utf-8", timeout=10,
                env=isolated_process_env(**self.local_env(server)))
            self.assertEqual(len(server.requests), 1)
        self.assertEqual((result.returncode, result.stdout), (7, "顶层\n输入😀\n"), result.stderr)
        self.assertEqual(self.document.with_suffix(".generated.ru").read_text(encoding="utf-8"), source)

    @unittest.skipUnless(NODE, "Node.js is needed for actual JavaScript execution")
    def test_js_cli_subprocess_inherits_input_output_and_entry_exit_status(self):
        source = "显 'JS 顶层'. 算 元初 外参 为 句 阵: 显 外参 其 量. 显 读. 得 9. 法\n"
        output = self.root / "published.cjs"
        with MockResponses(response_for(source)) as server:
            result = subprocess.run(
                [sys.executable, str(ROOT / "ru"), "generate", str(self.document), "--run",
                 "--target", "js", "-o", str(output)],
                input="Node 输入😀\n", capture_output=True, text=True, encoding="utf-8", timeout=10,
                env=isolated_process_env(PATH=str(Path(NODE).parent), **self.local_env(server)))
            self.assertEqual(len(server.requests), 1)
        self.assertEqual((result.returncode, result.stdout), (9, "JS 顶层\n0\nNode 输入😀\n"), result.stderr)
        self.assertIn("Node.js", result.stderr)
        self.assertTrue(output.is_file())
        self.assertFalse(self.document.with_suffix(".generated.ru").exists())

    @unittest.skipUnless(NODE, "Node.js is needed for actual JavaScript execution")
    def test_js_runtime_failure_preserves_artifact_and_reports_child_error(self):
        source = "显 'JS 运行前'. 卒 'JS 安全样例错误'.\n"
        output = self.root / "runtime-failure.js"
        with MockResponses(response_for(source)) as server:
            result = subprocess.run(
                [sys.executable, str(ROOT / "ru"), "generate", str(self.document), "--run",
                 "--target", "js", "-o", str(output)],
                capture_output=True, text=True, encoding="utf-8", timeout=10,
                env=isolated_process_env(PATH=str(Path(NODE).parent), **self.local_env(server)))
            self.assertEqual(len(server.requests), 1)
        self.assertEqual((result.returncode, result.stdout), (1, "JS 运行前\n"), result.stderr)
        self.assertIn("JS 安全样例错误", result.stderr)
        self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
