"""Module loading, CLI argument forwarding and build-path safety regressions."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.cli import build, make_parser
from rulang.frontend import RuError, parse
from rulang.modules import load_module_graph

HAS_CC = any(shutil.which(cc) for cc in ("clang", "gcc", "cc"))


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


class ImportedParameterTests(unittest.TestCase):
    def cli(self, command, source, *args):
        return subprocess.run([sys.executable, ROOT / "ru", command, source, *args],
                              text=True, capture_output=True, timeout=30)

    def test_imported_declarations_protect_function_and_method_parameters(self):
        declarations = ("算 导入名: 得 1. 法", "形 导入名: 象")
        consumers = (
            "算 检查 导入名 为 数: 得 导入名. 法\n显 检查 2.",
            "形 工具: 算 检查 导入名 为 数: 得 导入名. 法 象\n显 (新 工具) 其 检查 2.",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main, binary = root / "main.ru", root / "program"
            (root / "relay.ru").write_text("尽 取 外言 'lib.ru'.", encoding="utf-8")
            for declaration in declarations:
                (root / "lib.ru").write_text(declaration, encoding="utf-8")
                for imported in ("lib.ru", "relay.ru"):
                    for consumer in consumers:
                        main.write_text(f"尽 取 外言 '{imported}'.\n" + consumer, encoding="utf-8")
                        for command in ("run", "check", "build"):
                            with self.subTest(declaration=declaration, imported=imported,
                                              consumer=consumer, command=command):
                                args = ("-o", str(binary)) if command == "build" else ()
                                result = self.cli(command, main, *args)
                                self.assertEqual(result.returncode, 1, result.stderr)
                                self.assertIn("参数名不能与函数名、形名或内置名称重名", result.stderr)
                                self.assertIn(str(main) + ":2:", result.stderr)
                                self.assertEqual(result.stdout, "")
                                self.assertNotIn("Traceback", result.stderr)
                                self.assertFalse(binary.exists())

    def test_imported_value_bindings_remain_shadowable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main = root / "main.ru"
            (root / "lib.ru").write_text(
                "普通值 取 1. 形 导入形: 象 实例别名 取 新 导入形.", encoding="utf-8")
            main.write_text(
                "尽 取 外言 'lib.ru'.\n"
                "算 检查 普通值 为 数 实例别名 为 数: 得 普通值+实例别名. 法\n"
                "形 工具: 算 检查 普通值 为 数 实例别名 为 数: 得 普通值+实例别名. 法 象\n"
                "显 检查 2 3. 显 (新 工具) 其 检查 4 5.", encoding="utf-8")
            self.assert_success(main, "5\n9\n")

    def test_imported_functions_and_methods_use_their_owner_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main = root / "main.ru"
            (root / "lib.ru").write_text(
                "算 检查 主函数 为 数: 得 主函数. 法\n"
                "形 工具: 算 检查 主形 为 数: 得 主形. 法 象", encoding="utf-8")
            main.write_text(
                "算 主函数: 得 1. 法 形 主形: 象\n"
                "尽 取 外言 'lib.ru'. 显 检查 2. 显 (新 工具) 其 检查 3.", encoding="utf-8")
            self.assert_success(main, "2\n3\n")

    def assert_success(self, main, expected):
        result = self.cli("run", main)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected)
        result = self.cli("check", main)
        self.assertEqual(result.returncode, 0, result.stderr)
        if HAS_CC:
            binary = main.parent / "program"
            result = self.cli("build", main, "-o", str(binary))
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([binary], text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, expected)

    def test_collision_diagnostics_name_the_declaration_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main, library = root / "main.ru", root / "lib.ru"
            (root / "base.ru").write_text("算 导入名: 得 1. 法", encoding="utf-8")
            main.write_text("模 取 外言 'lib.ru'.\n显 模 其 检查 2.", encoding="utf-8")
            library.write_text(
                "尽 取 外言 'base.ru'.\n算 检查 导入名 为 数: 得 导入名. 法", encoding="utf-8")
            for command in ("run", "check"):
                with self.subTest(command=command):
                    result = self.cli(command, main)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn(str(library) + ":2:", result.stderr)
                    self.assertIn("参数名不能与函数名、形名或内置名称重名", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_interpreter_checks_only_when_called_after_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main = root / "main.ru"
            (root / "lib.ru").write_text("算 导入名: 得 1. 法", encoding="utf-8")
            source = ("算 检查 导入名 为 数: 得 导入名. 法\n"
                      "显 检查 2.\n尽 取 外言 'lib.ru'.\n")
            main.write_text(source, encoding="utf-8")
            result = self.cli("run", main)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "2\n")
            main.write_text(source + "显 检查 3.", encoding="utf-8")
            result = self.cli("run", main)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, "2\n")
            self.assertIn("参数名不能与函数名、形名或内置名称重名", result.stderr)


if __name__ == "__main__":
    unittest.main()
