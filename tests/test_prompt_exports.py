"""Offline prompt export and non-destructive publication contracts."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.cli import main
from rulang.frontend import RuError
from rulang.generation import GenerationConfig, generation_system_prompt, request_response
from rulang.prompts import export_prompt


class PromptExportTests(unittest.TestCase):
    def test_notebook_request_and_export_match_exactly(self):
        response = io.BytesIO(json.dumps({"status": "completed", "output_text": "显 '好'."}).encode())
        response.status = 200
        with patch("rulang.generation.urlrequest.build_opener") as build:
            build.return_value.open.return_value = response
            request_response(GenerationConfig("test-export-dummy", "https://example.invalid/v1", "test"),
                             "画图", runtime_target="rushu")
            request = build.return_value.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["input"][0]["content"][0]["text"], export_prompt("rushu"))

    def test_complete_specification_once_and_current_hash(self):
        raw = (ROOT / "rulang/language-spec.md").read_bytes()
        for target in ("rushu", "ruguan"):
            with self.subTest(target=target):
                text = export_prompt(target)
                self.assertEqual(text.count(raw.decode()), 1)
                self.assertEqual(text.count("<ru-language-spec>"), 1)
                self.assertIn(hashlib.sha256(raw).hexdigest(), text)
                self.assertIn("如书 Python 代码格", text)
                self.assertIn("正弦 弧度", text)
                self.assertIn("造源", text)
        self.assertNotEqual(export_prompt("rushu"), export_prompt("ruguan"))
        self.assertIn("本次任务聚焦如观", export_prompt("ruguan"))

    def test_export_never_loads_config_or_network(self):
        with patch("rulang.generation.load_config", side_effect=AssertionError("config read")), \
             patch("rulang.generation.urlrequest.build_opener", side_effect=AssertionError("network")), \
             patch("rulang.generation.request_response", side_effect=AssertionError("provider")):
            for target in ("rushu", "ruguan"):
                self.assertEqual(export_prompt(target), generation_system_prompt(target))

    def test_cli_stdout_is_exact_and_stderr_empty(self):
        for command in ("rushu-prompt", "ruguan-prompt"):
            for args in ([], ["-o", "-"]):
                with self.subTest(command=command, args=args):
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        self.assertEqual(main([command, *args]), 0)
                    self.assertEqual(stdout.getvalue(), export_prompt(command[:-7]))
                    self.assertEqual(stderr.getvalue(), "")

    def test_subprocess_utf8_ignores_locale_and_bad_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".ru-lang.json").write_text("bad config", encoding="utf-8")
            env = {**os.environ, "HOME": directory, "USERPROFILE": directory,
                   "RU_LLM_API_KEY_FILE": str(Path(directory, "absent-secret")),
                   "PYTHONIOENCODING": "ascii", "PYTHONUTF8": "0", "LC_ALL": "C"}
            result = subprocess.run([sys.executable, str(ROOT / "ru"), "rushu-prompt"],
                                    cwd=directory, env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, export_prompt("rushu").encode("utf-8"))
            self.assertEqual(result.stderr, b"")

    def test_file_output_is_exact_and_cli_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            for target in ("rushu", "ruguan"):
                output = Path(directory, target + " 提示.txt")
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(main([target + "-prompt", "--output", str(output)]), 0)
                self.assertEqual(output.read_bytes(), export_prompt(target).encode())
                self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")
                self.assertEqual(list(Path(directory).glob(".ru-prompt-*")), [])

    def test_existing_file_needs_force(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "prompt.txt")
            output.write_text("original")
            with self.assertRaises(RuError):
                export_prompt("rushu", output)
            self.assertEqual(output.read_text(), "original")
            self.assertEqual(export_prompt("ruguan", output, force=True), output)
            self.assertEqual(output.read_text(), export_prompt("ruguan"))

    def test_force_accepts_new_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "prompt")
            export_prompt("rushu", output, force=True)
            self.assertEqual(output.read_text(), export_prompt("rushu"))

    def test_force_rejects_stdout(self):
        for output in (None, "-"):
            with self.assertRaises(RuError):
                export_prompt("rushu", output, force=True)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(["rushu-prompt", "--force"])
        self.assertEqual(error.exception.code, 2)

    def test_invalid_target(self):
        with self.assertRaises(RuError):
            export_prompt("invalid")

    def test_specification_and_hardlink_protected(self):
        specification = ROOT / "rulang/language-spec.md"
        before = specification.read_bytes()
        with self.assertRaises(RuError):
            export_prompt("rushu", specification, force=True)
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            alias = Path(directory, "alias.txt")
            os.link(specification, alias)
            with self.assertRaises(RuError):
                export_prompt("ruguan", alias, force=True)
            self.assertEqual(alias.read_bytes(), before)
        self.assertEqual(specification.read_bytes(), before)

    def test_symlink_directory_and_fifo_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "original"
            target.write_text("original")
            paths = [root / "link", root / "broken", root / "folder"]
            try:
                paths[0].symlink_to(target)
                paths[1].symlink_to(root / "absent")
            except (OSError, NotImplementedError):
                paths = [paths[-1]]
            paths[-1].mkdir()
            if hasattr(os, "mkfifo"):
                fifo = root / "fifo"
                os.mkfifo(fifo)
                paths.append(fifo)
            for path in paths:
                for force in (False, True):
                    with self.subTest(path=path, force=force), self.assertRaises(RuError):
                        export_prompt("rushu", path, force=force)
            self.assertEqual(target.read_text(), "original")

    def test_fsync_and_replace_failure_preserve_original_and_cleanup(self):
        for operation in ("fsync", "replace"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                output = Path(directory, "prompt.txt")
                output.write_text("original")
                with patch("rulang.prompts.os." + operation, side_effect=OSError("private detail")), self.assertRaises(RuError) as error:
                    export_prompt("rushu", output, force=True)
                self.assertNotIn("private detail", str(error.exception))
                self.assertEqual(output.read_text(), "original")
                self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_no_force_race_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "prompt.txt")
            link = os.link
            def race(source, destination):
                output.write_text("concurrent writer")
                return link(source, destination)
            with patch("rulang.prompts.os.link", side_effect=race), self.assertRaises(RuError):
                export_prompt("rushu", output)
            self.assertEqual(output.read_text(), "concurrent writer")
            self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_force_rechecks_destination_after_temporary_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "prompt.txt"
            original = root / "original.txt"
            original.write_text("keep")
            def replace_with_link(_descriptor):
                try:
                    output.symlink_to(original)
                except (OSError, NotImplementedError):
                    self.skipTest("symlink creation unavailable")
            with patch("rulang.prompts.os.fsync", side_effect=replace_with_link), self.assertRaises(RuError):
                export_prompt("rushu", output, force=True)
            self.assertTrue(output.is_symlink())
            self.assertEqual(original.read_text(), "keep")
            self.assertEqual(list(root.glob(".ru-prompt-*")), [])

    def test_missing_directory_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(main(["ruguan-prompt", "-o", str(Path(directory, "absent/prompt.txt"))]), 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("提示导出错误", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_invalid_specification_never_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "prompt.txt")
            output.write_text("original")
            with patch("rulang.generation.resources.files") as resources:
                resources.return_value.joinpath.return_value.open.return_value = io.BytesIO(b"bad spec")
                with self.assertRaises(RuError):
                    export_prompt("rushu", output, force=True)
            self.assertEqual(output.read_text(), "original")
            self.assertEqual(list(Path(directory).iterdir()), [output])


if __name__ == "__main__":
    unittest.main()
