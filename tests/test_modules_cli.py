"""Module loading, CLI argument forwarding and build-path safety regressions."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.cli import build, make_parser
from rulang.frontend import RuError, parse
from rulang.modules import load_module_graph


class ModuleLoaderTests(unittest.TestCase):
    def test_importer_relative_and_canonical_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lib").mkdir()
            main = root / "main.ru"
            main.write_text("甲 取 外言 'lib/a.ru'. 乙 取 外言 'lib/../lib/a.ru'.", encoding="utf-8")
            (root / "lib/a.ru").write_text("乙 取 外言 'b.ru'.", encoding="utf-8")
            (root / "lib/b.ru").write_text("值 取 42.", encoding="utf-8")
            graph = load_module_graph(main)
            self.assertEqual(len(graph), 3)
            imports = [n.data["expr"].data["resolved"] for n in graph[graph.root]]
            self.assertEqual(imports[0], imports[1])
            self.assertEqual(graph[str(root / "lib/a.ru")][0].data["expr"].data["resolved"], str(root / "lib/b.ru"))

    def test_import_errors_report_origin_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.ru").write_text("甲 取 外言 'a.ru'.", encoding="utf-8")
            (root / "a.ru").write_text("# 注释\n甲 取 外言 'missing.ru'.", encoding="utf-8")
            with self.assertRaises(RuError) as context:
                load_module_graph(root / "main.ru")
            self.assertEqual(context.exception.source_name, str(root / "a.ru"))
            self.assertEqual(context.exception.line, 2)
            self.assertIn("无法读取外言", context.exception.message)

    def test_import_syntax_error_reports_imported_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.ru").write_text("甲 取 外言 'bad.ru'.", encoding="utf-8")
            (root / "bad.ru").write_text("# 注释\n显 ).", encoding="utf-8")
            result = subprocess.run([sys.executable, ROOT / "ru", "check", root / "main.ru"],
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn(str(root / "bad.ru") + ":2:", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_import_compile_error_reports_imported_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.ru").write_text("模 取 外言 'lib.ru'.", encoding="utf-8")
            (root / "lib.ru").write_text("# 注释\n算 平方 根 为 数: 得 根*根. 法\n显 平方 1 2.", encoding="utf-8")
            result = subprocess.run([sys.executable, ROOT / "ru", "check", root / "main.ru"],
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn(str(root / "lib.ru") + ":3:", result.stderr)
            self.assertIn("显 平方 1 2.", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_cycles_even_when_import_is_in_function(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main = root / "main.ru"
            main.write_text("算 尚未调用: 模 取 外言 'a.ru'. 得 1. 法", encoding="utf-8")
            (root / "a.ru").write_text("模 取 外言 'main.ru'.", encoding="utf-8")
            with self.assertRaises(RuError) as context:
                load_module_graph(main)
            self.assertIn("循环外言", context.exception.message)

    def test_loading_never_executes_module(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "main.ru"
            path.write_text("显 1/0.", encoding="utf-8")
            self.assertEqual(len(load_module_graph(path)), 1)

    def test_build_cannot_overwrite_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main, dependency = root / "main.ru", root / "dependency.ru"
            main.write_text("模 取 外言 'dependency.ru'.", encoding="utf-8")
            dependency.write_text("值 取 42.", encoding="utf-8")
            program = parse(main.read_text(encoding="utf-8"))
            for output, emit_c in ((dependency, None), (root / "binary", dependency)):
                with self.subTest(output=output, emit_c=emit_c):
                    with self.assertRaises(RuError):
                        build(program, main, output, emit_c=emit_c)
            self.assertEqual(dependency.read_text(encoding="utf-8"), "值 取 42.")

    def test_run_options_after_source_are_program_arguments(self):
        args = make_parser().parse_args(["run", "main.ru", "--flag", "中文", "--"])
        self.assertEqual(args.args, ["--flag", "中文", "--"])
        args = make_parser().parse_args(["run", "main.ru", "--", "--", "中文"])
        self.assertEqual(args.args, ["--", "中文"])

    def test_local_imports_only(self):
        with tempfile.TemporaryDirectory() as directory:
            for requested in ("", "https://example.com/a.ru"):
                with self.subTest(path=requested):
                    with self.assertRaises(RuError) as context:
                        load_module_graph(Path(directory) / "main.ru", parse(f"模 取 外言 '{requested}'."))
                    self.assertIn("本地文件路径", context.exception.message)


if __name__ == "__main__":
    unittest.main()
