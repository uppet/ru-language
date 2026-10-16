"""Native documentation snippets parse without executing imports or DLLs."""
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.frontend import parse, validate
from rulang.modules import load_module_graph


class NativeDocumentationTests(unittest.TestCase):
    def test_guide_examples_parse_and_resolve_without_native_execution(self):
        guide = (ROOT / "docs/native-library.md").read_text(encoding="utf-8")
        sources = re.findall(r"^```ru[ \t]*\n(.*?)^```[ \t]*$", guide,
                             re.MULTILINE | re.DOTALL)
        self.assertGreaterEqual(len(sources), 5)
        with tempfile.TemporaryDirectory() as directory, \
             patch("rulang.interpreter.Interpreter.execute",
                   side_effect=AssertionError("documentation checks must not execute")):
            for index, source in enumerate(sources, 1):
                with self.subTest(example=index):
                    program = parse(source)
                    validate(program)
                    path = Path(directory) / f"example-{index}.ru"
                    path.write_text(source, encoding="utf-8")
                    graph = load_module_graph(path, program)
                    self.assertTrue(any(Path(module).name == "密.ru" for module in graph))

    def test_guide_spec_and_entry_points_agree_on_native_boundary(self):
        for relative in ("docs/native-library.md", "rulang/language-spec.md", "docs/command-line.md"):
            with self.subTest(document=relative):
                content = (ROOT / relative).read_text(encoding="utf-8")
                for term in ("如:密", "如见", "Windows x64", "--allow-native",
                             "check --target python", "三方", "不是沙箱"):
                    self.assertIn(term, content)
        guide = (ROOT / "docs/native-library.md").read_text(encoding="utf-8")
        for term in ("16 MiB", "1024", "1～128", "64 个参数", "界内第一个 NUL",
                     "关闭父内存", "PostQuitMessage", "位段 起 宽"):
            self.assertIn(term, guide)


if __name__ == "__main__":
    unittest.main()
