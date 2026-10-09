"""Explicit artifact replacement is atomic and never mutates protected sources.

Every provider/config call is mocked with a public dummy credential. These
tests never read a user's configuration, contact a provider, or run model code.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.frontend import RuError
from rulang.generation import GenerationConfig, GenerationError, LOCAL_TEST_API_KEY, generate


class ForceGenerationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.document = self.root / "wish.md"
        self.document.write_text("显示一个问候。\n如是我言\n", encoding="utf-8")
        self.original_document = self.document.read_bytes()
        self.output = self.root / "out.ru"
        self.original_output = "显 '保留旧产物'.\n".encode("utf-8")
        self.output.write_bytes(self.original_output)
        self.source = "显 '新产物'. 显 1/0."
        config = patch("rulang.generation.load_config", return_value=GenerationConfig(LOCAL_TEST_API_KEY))
        request = patch("rulang.generation.request_response", return_value=self.source)
        self.config = config.start()
        self.request = request.start()
        self.addCleanup(config.stop)
        self.addCleanup(request.stop)

    def assert_no_temporary(self):
        self.assertEqual(list(self.root.glob(".ru-generate-*")), [])

    def assert_preserved(self):
        self.assertEqual(self.output.read_bytes(), self.original_output)
        self.assertEqual(self.document.read_bytes(), self.original_document)
        self.assert_no_temporary()

    def require_symlink(self, path, target):
        try:
            path.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are unavailable")

    def require_hardlink(self, path, target):
        try:
            os.link(target, path)
        except (OSError, NotImplementedError):
            self.skipTest("hard links are unavailable")

    def test_force_replaces_ru_js_and_cjs_only_after_fsync(self):
        for target, extension in (("ru", ".ru"), ("js", ".js"), ("js", ".cjs")):
            with self.subTest(target=target, extension=extension):
                output = self.root / ("artifact" + extension)
                output.write_bytes(self.original_output)
                original_fsync, original_replace = os.fsync, os.replace
                stages = []

                def fsync(fd):
                    self.assertEqual(output.read_bytes(), self.original_output)
                    original_fsync(fd)
                    stages.append("fsync")

                def replace(temporary, destination):
                    self.assertEqual(stages, ["fsync"])
                    self.assertEqual(output.read_bytes(), self.original_output)
                    artifact = Path(temporary).read_text(encoding="utf-8")
                    if target == "ru":
                        self.assertEqual(artifact, self.source + "\n")
                    else:
                        self.assertIn("use strict", artifact)
                    self.assertEqual(Path(destination), output)
                    stages.append("replace")
                    original_replace(temporary, destination)

                with patch("rulang.generation.os.fsync", side_effect=fsync), \
                        patch("rulang.generation.os.replace", side_effect=replace), \
                        patch("rulang.generation.os.link", side_effect=AssertionError("exclusive path")):
                    self.assertEqual(generate(self.document, output, target=target, force=True), output)
                self.assertEqual(stages, ["fsync", "replace"])
                self.assertNotEqual(output.read_bytes(), self.original_output)
                self.assertEqual(self.document.read_bytes(), self.original_document)
                self.assert_no_temporary()
        self.assertEqual(self.request.call_count, 3)

    def test_force_default_output_and_absent_output(self):
        for target in ("ru", "js"):
            with self.subTest(target=target):
                output = self.document.with_suffix(".generated." + target)
                self.assertEqual(generate(self.document, target=target, force=True), output)
                output.write_bytes(self.original_output)
                self.assertEqual(generate(self.document, target=target, force=True), output)
                self.assertNotEqual(output.read_bytes(), self.original_output)
                self.assert_no_temporary()

    def test_stdout_force_rejected_before_document_config_or_request(self):
        with patch("rulang.generation._read_bounded", side_effect=AssertionError("document read")):
            with self.assertRaisesRegex(GenerationError, "--stdout.*--force"):
                generate(self.root / "missing.md", stdout=True, force=True)
        self.config.assert_not_called()
        self.request.assert_not_called()
        self.assert_preserved()

    def test_existing_output_without_force_still_rejected_before_config(self):
        with self.assertRaises(GenerationError):
            generate(self.document, self.output)
        self.config.assert_not_called()
        self.request.assert_not_called()
        self.assert_preserved()

    def test_no_force_keeps_exclusive_publication_and_race_protection(self):
        output = self.root / "new.ru"
        original_link = os.link

        def race(temporary, destination):
            output.write_bytes(self.original_output)
            return original_link(temporary, destination)

        with patch("rulang.generation.os.replace", side_effect=AssertionError("replacement")), \
                patch("rulang.generation.os.link", side_effect=race):
            with self.assertRaises(GenerationError):
                generate(self.document, output)
        self.assertEqual(output.read_bytes(), self.original_output)
        self.assert_no_temporary()

    def test_force_request_failure_preserves_original(self):
        self.request.side_effect = GenerationError("mock transport failure")
        with self.assertRaises(GenerationError):
            generate(self.document, self.output, force=True)
        self.request.assert_called_once()
        self.assert_preserved()

    def test_force_invalid_source_and_dependencies_preserve_original(self):
        for source in ("显 ).", "破.", "# comment only", "解释\n```ru\n显 1.\n```",
                       "模 取 外言 'missing.ru'.", "显 '" + LOCAL_TEST_API_KEY + "'."):
            with self.subTest(source=source):
                self.request.return_value = source
                with self.assertRaises(GenerationError):
                    generate(self.document, self.output, force=True)
                self.assert_preserved()

    def test_force_compile_failures_preserve_original(self):
        for compiler in ("rulang.generation.Compiler.compile", "rulang.js_compiler.JSCompiler.compile"):
            with self.subTest(compiler=compiler):
                output = self.root / "out.js"
                output.write_bytes(self.original_output)
                with patch(compiler, side_effect=RuError("mock compilation failure")):
                    with self.assertRaises(GenerationError):
                        generate(self.document, output, target="js", force=True)
                self.assertEqual(output.read_bytes(), self.original_output)
                self.assert_preserved()

    def test_force_temp_write_fsync_and_publication_failures_preserve_original(self):
        operations = ("tempfile.mkstemp", "os.fdopen", "os.fsync", "os.replace")
        for operation in operations:
            with self.subTest(operation=operation):
                with patch("rulang.generation." + operation, side_effect=OSError("mock save failure")):
                    with self.assertRaises(GenerationError):
                        generate(self.document, self.output, force=True)
                self.assert_preserved()

    def test_failed_fdopen_closes_temporary_descriptor(self):
        original_mkstemp = tempfile.mkstemp
        descriptors = []

        def mkstemp(*args, **kwargs):
            fd, path = original_mkstemp(*args, **kwargs)
            descriptors.append(fd)
            return fd, path

        with patch("rulang.generation.tempfile.mkstemp", side_effect=mkstemp), \
                patch("rulang.generation.os.fdopen", side_effect=OSError("mock open failure")):
            with self.assertRaises(GenerationError):
                generate(self.document, self.output, force=True)
        self.assertEqual(len(descriptors), 1)
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])
        self.assert_preserved()

    def test_force_partial_temporary_write_preserves_original(self):
        original_fdopen = os.fdopen

        class FailingWrite:
            def __init__(self, *args, **kwargs):
                self.stream = original_fdopen(*args, **kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()

            def write(self, artifact):
                self.stream.write(artifact[:2])
                self.stream.flush()
                raise OSError("mock partial write failure")

        with patch("rulang.generation.os.fdopen", side_effect=FailingWrite):
            with self.assertRaises(GenerationError):
                generate(self.document, self.output, force=True)
        self.assert_preserved()

    def test_force_cancellation_during_request_or_publication_preserves_original(self):
        for operation in ("request_response", "os.fsync", "os.replace"):
            with self.subTest(operation=operation):
                with patch("rulang.generation." + operation, side_effect=KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        generate(self.document, self.output, force=True)
                self.assert_preserved()

    def test_force_same_document_or_document_hardlink_rejected_before_config(self):
        document = self.root / "intent.ru"
        document.write_bytes(self.original_document)
        alias = self.root / "intent-alias.ru"
        self.require_hardlink(alias, document)
        for output in (document, alias):
            with self.subTest(output=output), self.assertRaises(GenerationError):
                generate(document, output, force=True)
        self.config.assert_not_called()
        self.request.assert_not_called()
        self.assertEqual(document.read_bytes(), self.original_document)
        self.assertEqual(alias.read_bytes(), self.original_document)
        self.assert_preserved()

    def test_force_symlink_and_dangling_symlink_rejected_before_config(self):
        present = self.root / "link.ru"
        dangling = self.root / "dangling.ru"
        missing = self.root / "missing.ru"
        self.require_symlink(present, self.output)
        self.require_symlink(dangling, missing)
        for output in (present, dangling):
            with self.subTest(output=output), self.assertRaisesRegex(GenerationError, "符号链接"):
                generate(self.document, output, force=True)
            self.assertTrue(output.is_symlink())
        self.config.assert_not_called()
        self.request.assert_not_called()
        self.assertFalse(missing.exists())
        self.assert_preserved()

    def test_force_directory_and_special_file_rejected_before_config(self):
        directory = self.root / "directory.ru"
        directory.mkdir()
        outputs = [directory]
        if hasattr(os, "mkfifo"):
            fifo = self.root / "pipe.ru"
            os.mkfifo(fifo)
            outputs.append(fifo)
        for output in outputs:
            with self.subTest(output=output), self.assertRaises(GenerationError):
                generate(self.document, output, force=True)
        self.config.assert_not_called()
        self.request.assert_not_called()
        self.assert_preserved()

    def test_force_still_checks_extension_and_parent_before_config(self):
        for output in (self.root / "out.md", self.root / "absent" / "out.ru"):
            with self.subTest(output=output), self.assertRaises(GenerationError):
                generate(self.document, output, force=True)
        self.config.assert_not_called()
        self.request.assert_not_called()
        self.assert_preserved()

    def test_force_direct_self_import_cannot_overwrite_dependency(self):
        self.request.return_value = "模 取 外言 'out.ru'. 显 1."
        with self.assertRaises(GenerationError):
            generate(self.document, self.output, force=True)
        self.assert_preserved()

    def test_force_imported_dependency_hardlink_ru_and_js_is_protected(self):
        dependency = self.root / "lib.ru"
        dependency.write_text("值 取 2.", encoding="utf-8")
        original = dependency.read_bytes()
        self.request.return_value = "模 取 外言 'lib.ru'. 显 模 其 值."
        for target in ("ru", "js"):
            output = self.root / ("alias." + target)
            self.require_hardlink(output, dependency)
            with self.subTest(target=target), self.assertRaisesRegex(GenerationError, "依赖.*硬链接"):
                generate(self.document, output, target=target, force=True)
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(dependency.read_bytes(), original)
            self.assert_no_temporary()

    def test_force_transitive_dependency_hardlink_is_protected(self):
        leaf = self.root / "leaf.ru"
        leaf.write_text("值 取 2.", encoding="utf-8")
        (self.root / "middle.ru").write_text("模 取 外言 'leaf.ru'. 值 取 模 其 值.", encoding="utf-8")
        alias = self.root / "leaf-alias.ru"
        self.require_hardlink(alias, leaf)
        self.request.return_value = "模 取 外言 'middle.ru'. 显 模 其 值."
        with self.assertRaisesRegex(GenerationError, "依赖.*硬链接"):
            generate(self.document, alias, force=True)
        self.assertEqual(alias.read_text(encoding="utf-8"), "值 取 2.")
        self.assert_no_temporary()

    def test_force_normal_imports_are_validated_without_execution(self):
        dependency = self.root / "lib.ru"
        dependency.write_text("显 1/0. 值 取 2.", encoding="utf-8")
        original = dependency.read_bytes()
        self.request.return_value = "模 取 外言 'lib.ru'. 显 模 其 值."
        self.assertEqual(generate(self.document, self.output, force=True), self.output)
        self.assertEqual(dependency.read_bytes(), original)
        self.assert_no_temporary()

    def test_force_rechecks_late_symlink_after_fsync(self):
        link = self.root / "link-check.ru"
        self.require_symlink(link, self.document)
        link.unlink()
        original_fsync = os.fsync

        def fsync(fd):
            original_fsync(fd)
            self.output.unlink()
            self.output.symlink_to(self.document)

        with patch("rulang.generation.os.fsync", side_effect=fsync), \
                patch("rulang.generation.os.replace", side_effect=AssertionError("unsafe publication")):
            with self.assertRaisesRegex(GenerationError, "符号链接"):
                generate(self.document, self.output, force=True)
        self.assertTrue(self.output.is_symlink())
        self.assertEqual(self.document.read_bytes(), self.original_document)
        self.assert_no_temporary()

    def test_force_rechecks_late_input_hardlink_after_fsync(self):
        alias = self.root / "hardlink-check.ru"
        self.require_hardlink(alias, self.document)
        alias.unlink()
        original_fsync = os.fsync

        def fsync(fd):
            original_fsync(fd)
            self.output.unlink()
            os.link(self.document, self.output)

        with patch("rulang.generation.os.fsync", side_effect=fsync), \
                patch("rulang.generation.os.replace", side_effect=AssertionError("unsafe publication")):
            with self.assertRaisesRegex(GenerationError, "硬链接"):
                generate(self.document, self.output, force=True)
        self.assertEqual(self.output.read_bytes(), self.original_document)
        self.assertEqual(self.document.read_bytes(), self.original_document)
        self.assert_no_temporary()

    def test_force_remembers_input_inode_if_document_path_changes_during_request(self):
        alias = self.root / "original-document.ru"
        self.require_hardlink(alias, self.document)

        def request(*args, **kwargs):
            self.document.unlink()
            self.document.write_text("新的意图文档。\n如是我言\n", encoding="utf-8")
            self.output.unlink()
            os.link(alias, self.output)
            return self.source

        self.request.side_effect = request
        with self.assertRaisesRegex(GenerationError, "硬链接"):
            generate(self.document, self.output, force=True)
        self.assertEqual(self.output.read_bytes(), self.original_document)
        self.assertEqual(alias.read_bytes(), self.original_document)
        self.assert_no_temporary()

    def test_force_remembers_dependency_inode_if_path_changes_after_check(self):
        dependency = self.root / "lib.ru"
        dependency.write_text("值 取 2.", encoding="utf-8")
        original = dependency.read_bytes()
        alias = self.root / "original-dependency.ru"
        self.require_hardlink(alias, dependency)
        self.request.return_value = "模 取 外言 'lib.ru'. 显 模 其 值."
        original_fsync = os.fsync

        def fsync(fd):
            original_fsync(fd)
            dependency.unlink()
            dependency.write_text("值 取 3.", encoding="utf-8")
            self.output.unlink()
            os.link(alias, self.output)

        with patch("rulang.generation.os.fsync", side_effect=fsync):
            with self.assertRaisesRegex(GenerationError, "依赖.*硬链接"):
                generate(self.document, self.output, force=True)
        self.assertEqual(self.output.read_bytes(), original)
        self.assertEqual(alias.read_bytes(), original)
        self.assertEqual(dependency.read_text(encoding="utf-8"), "值 取 3.")
        self.assert_no_temporary()


if __name__ == "__main__":
    unittest.main()
