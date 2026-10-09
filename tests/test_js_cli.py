"""JavaScript CLI and intent-to-Ru-to-JavaScript output safety regressions."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang import __version__
from rulang.cli import build, main, make_parser
from rulang.frontend import RuError, parse
from rulang.generation import GenerationError, generate
from test_generation import DUMMY, MockResponses, TemporaryGeneration, isolated_process_env, response_for

NODE = shutil.which("node")


class JavaScriptBuildCLI(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.source = self.root / "main.ru"
        self.source.write_text("显 '你好😀'.\n", encoding="utf-8")

    def test_c_remains_default_and_generation_ru_remains_default(self):
        parser = make_parser()
        self.assertEqual(parser.parse_args(["build", "x.ru"]).target, "c")
        self.assertEqual(parser.parse_args(["generate", "wish.md"]).target, "ru")

    def test_js_default_output_no_compiler_node_configuration_or_network(self):
        with patch("rulang.cli.subprocess.run", side_effect=AssertionError("execute")), \
             patch("rulang.generation.load_config", side_effect=AssertionError("config")), \
             patch("rulang.generation.request_response", side_effect=AssertionError("network")), \
             patch.dict(os.environ, {"PATH": "", "CC": "/not/a/compiler"}), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["build", str(self.source), "--target", "js"]), 0)
        self.assertTrue(self.source.with_suffix(".js").is_file())
        self.assertIn("未执行", output.getvalue())
        self.assertIn("Node.js", output.getvalue())
        self.assertEqual(list(self.root.glob(".ru-build-*")), [])

    def test_reject_c_only_flags_before_reading_source(self):
        for flags in (["--cc", "clang"], ["--emit-c", "out.c"]):
            with self.subTest(flags=flags), patch("rulang.cli.read_source", side_effect=AssertionError("read")), \
                 contextlib.redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit) as caught:
                main(["build", "missing.ru", "--target", "js", *flags])
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("--target js", error.getvalue())

    def test_build_api_rejects_unknown_target_or_c_only_options(self):
        for options in ({"target": "invalid"}, {"target": "js", "cc": "clang"},
                        {"target": "js", "emit_c": "out.c"}):
            with self.subTest(options=options), self.assertRaises(RuError):
                build(parse("显 1."), self.source, self.root / "out.js", **options)

    def test_source_dependency_and_symlink_collisions_are_rejected(self):
        dependency = self.root / "lib.ru"
        dependency.write_text("值 取 42.", encoding="utf-8")
        text = "模 取 外言 'lib.ru'. 显 模 其 值."
        self.source.write_text(text, encoding="utf-8")
        link = self.root / "source-link.js"
        link.symlink_to(self.source)
        for destination in (self.source, dependency, link):
            with self.subTest(destination=destination), self.assertRaisesRegex(RuError, "不能覆盖"):
                build(parse(text), self.source, destination, target="js")
        self.assertEqual(self.source.read_text(), text)
        self.assertEqual(dependency.read_text(), "值 取 42.")
        self.assertTrue(link.is_symlink())

    def test_failed_compilation_preserves_existing_output(self):
        output = self.root / "out.js"
        output.write_text("previous output", encoding="utf-8")
        with self.assertRaises(RuError):
            build(parse("算 平方 值 为 数: 得 值*值. 法 显 平方 1 2."),
                  self.source, output, target="js")
        self.assertEqual(output.read_text(), "previous output")
        self.assertEqual(list(self.root.glob(".ru-build-*")), [])

    def test_failed_publish_preserves_existing_output_and_removes_temporary(self):
        output = self.root / "out.js"
        output.write_text("previous output", encoding="utf-8")
        with patch("rulang.cli.os.replace", side_effect=OSError("simulated failure")), self.assertRaises(OSError):
            build(parse("显 1."), self.source, output, target="js")
        self.assertEqual(output.read_text(), "previous output")
        self.assertEqual(list(self.root.glob(".ru-build-*")), [])

    def test_successful_build_replaces_output_and_creates_parent(self):
        output = self.root / "new" / "out.js"
        result, backend = build(parse("显 1."), self.source, output, target="js")
        self.assertEqual(result, output)
        first = output.read_text(encoding="utf-8")
        self.assertIn("JavaScript", backend)
        build(parse("显 2."), self.source, output, target="js")
        self.assertNotEqual(output.read_text(encoding="utf-8"), first)

    @unittest.skipUnless(NODE, "Node.js is required to run JavaScript outputs")
    def test_cjs_runs_inside_module_package_after_sources_are_removed(self):
        (self.root / "package.json").write_text(json.dumps({"type": "module"}))
        dependency = self.root / "lib.ru"
        dependency.write_text("值 取 '独立运行😀'.", encoding="utf-8")
        output = self.root / "out.cjs"
        build(parse("模 取 外言 'lib.ru'. 显 模 其 值."), self.source, output, target="js")
        self.source.unlink()
        dependency.unlink()
        result = subprocess.run([NODE, str(output)], cwd=self.root, env=isolated_process_env(PATH=""),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "独立运行😀\n")
        self.assertEqual(result.stderr, "")


class JavaScriptGenerationCLI(TemporaryGeneration):
    def test_one_real_local_request_contains_full_current_spec_and_lowers_ru(self):
        raw = (ROOT / "rulang/language-spec.md").read_bytes()
        with MockResponses(response_for("显 '来自如😀'.")) as server:
            output = generate(self.document, environ=self.local_env(server), target="js")
        self.assertEqual(output, self.root / "wish.generated.js")
        self.assertTrue(output.is_file())
        self.assertFalse((self.root / "wish.generated.ru").exists())
        self.assertEqual(len(server.requests), 1)
        payload = server.requests[0][2]
        system = payload["input"][0]["content"][0]["text"]
        self.assertIn(raw.decode("utf-8"), system)
        self.assertIn("随附规范 SHA-256：" + hashlib.sha256(raw).hexdigest(), system)
        self.assertIn("当前语言版本：" + __version__, system)
        self.assertIn("只输出完整、可检查的 .ru 源码", system)
        self.assertNotEqual(output.read_text(encoding="utf-8"), "显 '来自如😀'.\n")
        if NODE:
            result = subprocess.run([NODE, str(output)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "来自如😀\n")

    def test_cli_js_generation_does_not_execute_division_by_zero(self):
        with MockResponses(response_for("显 1/0.")) as server, \
             patch.dict(os.environ, self.local_env(server), clear=True), \
             patch("rulang.cli.subprocess.run", side_effect=AssertionError("execute")), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["generate", str(self.document), "--target", "js"]), 0)
        self.assertIn("未执行", output.getvalue())
        self.assertTrue((self.root / "wish.generated.js").is_file())
        self.assertEqual(len(server.requests), 1)

    def test_js_cjs_output_and_relative_dependencies(self):
        destination = self.root / "output"
        destination.mkdir()
        dependency = destination / "lib.ru"
        dependency.write_text("显 1/0. 值 取 2.", encoding="utf-8")
        with MockResponses(response_for("模 取 外言 'lib.ru'. 显 模 其 值.")) as server:
            output = generate(self.document, destination / "app.cjs", environ=self.local_env(server), target="js")
        self.assertEqual(output, destination / "app.cjs")
        self.assertTrue(output.is_file())
        self.assertFalse((destination / "app.ru").exists())

    def test_invalid_target_extension_or_existing_output_never_requests(self):
        existing = self.root / "existing.js"
        existing.write_text("keep me")
        link = self.root / "link.js"
        link.symlink_to(existing)
        broken = self.root / "broken.js"
        broken.symlink_to(self.root / "absent.js")
        for destination, target in ((existing, "js"), (link, "js"), (broken, "js"),
                                    (self.document, "js"), (self.root / "new.ru", "js"),
                                    (self.root / "new.mjs", "js"), (self.root / "out.js", "invalid"),
                                    (self.root / "absent" / "new.js", "js")):
            with self.subTest(destination=destination, target=target), \
                 patch("rulang.generation.load_config", side_effect=AssertionError("config")), \
                 self.assertRaises(GenerationError):
                generate(self.document, destination, environ=self.env, target=target)
        self.assertEqual(existing.read_text(), "keep me")
        self.assertTrue(broken.is_symlink())

    def test_invalid_ru_or_direct_javascript_never_saved(self):
        for code in ("console.log('wrong language');", "显 ).", "模 取 外言 'absent.ru'."):
            with self.subTest(code=code), MockResponses(response_for(code)) as server, self.assertRaises(GenerationError):
                generate(self.document, environ=self.local_env(server), target="js")
            self.assertFalse((self.root / "wish.generated.js").exists())
            self.assertEqual(list(self.root.glob(".ru-generate-*")), [])

    def test_publish_race_and_failed_compilation_never_overwrite(self):
        destination = self.root / "out.js"
        original_link = os.link
        def race(source, target):
            destination.write_text("created by someone else")
            return original_link(source, target)
        with MockResponses() as server, patch("rulang.generation.os.link", side_effect=race), self.assertRaises(GenerationError):
            generate(self.document, destination, environ=self.local_env(server), target="js")
        self.assertEqual(destination.read_text(), "created by someone else")
        self.assertEqual(list(self.root.glob(".ru-generate-*")), [])
        destination.unlink()
        with MockResponses() as server, \
             patch("rulang.js_compiler.JSCompiler.compile", side_effect=RuError("private source sentinel")), \
             self.assertRaises(GenerationError) as caught:
            generate(self.document, destination, environ=self.local_env(server), target="js")
        self.assertNotIn("private source sentinel", str(caught.exception))
        self.assertFalse(destination.exists())

    def test_missing_spec_fails_before_request_for_js_target(self):
        with MockResponses() as server, \
             patch("rulang.generation.resources.files", side_effect=FileNotFoundError), \
             self.assertRaises(GenerationError):
            generate(self.document, environ=self.local_env(server), target="js")
        self.assertEqual(server.requests, [])
        self.assertFalse((self.root / "wish.generated.js").exists())

    def test_configured_key_in_bundled_dependency_never_saved(self):
        (self.root / "lib.ru").write_text("值 取 '" + DUMMY + "'.", encoding="utf-8")
        with MockResponses(response_for("模 取 外言 'lib.ru'.")) as server, self.assertRaises(GenerationError) as caught:
            generate(self.document, environ=self.local_env(server), target="js")
        self.assertNotIn(DUMMY, str(caught.exception))
        self.assertFalse((self.root / "wish.generated.js").exists())


if __name__ == "__main__":
    unittest.main()
