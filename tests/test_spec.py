"""Keep executable-syntax examples in the bundled language specification honest.

The specification uses ``ru`` fences for complete syntax examples and ``text``
or ``ebnf`` for fragments, counterexamples and grammar notation. These checks
never execute the examples or load their external modules.
"""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.compiler import Compiler
from rulang.js_compiler import JSCompiler
from rulang.frontend import parse, validate
from rulang.modules import import_nodes


SPECIFICATION = ROOT / "rulang" / "language-spec.md"


class SpecificationExamples(unittest.TestCase):
    def test_complete_examples_parse_and_compile_without_execution(self):
        specification = SPECIFICATION.read_text(encoding="utf-8")
        examples = re.findall(r"^```ru[ \t]*\n(.*?)^```[ \t]*$",
                              specification, re.MULTILINE | re.DOTALL)
        self.assertTrue(examples, "The learner specification needs complete examples")
        for index, source in enumerate(examples, 1):
            with self.subTest(example=index):
                program = parse(source)
                validate(program)
                if not any(import_nodes(program)):
                    # Backend generation is a structural check, not native compilation or
                    # execution. Import examples require their documented files
                    # and are intentionally not read by this standalone test.
                    Compiler(program, f"<语言规范示例 {index}>").compile()
                    JSCompiler(program, f"<语言规范示例 {index}>").compile()


if __name__ == "__main__":
    unittest.main()
