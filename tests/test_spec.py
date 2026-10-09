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
    def test_optional_parameter_contract_and_example(self):
        specification = SPECIFICATION.read_text(encoding="utf-8")
        self.assertIn("参数       = 名称 ['为' 类型] ;", specification)
        self.assertIn("所有用户参数仍必需", specification)
        self.assertIn("无类型与任何显式类型均不兼容", specification)
        self.assertNotIn("每个参数都必须有类型", specification)
        source = (ROOT / "examples" / "optional_parameters.ru").read_text(encoding="utf-8")
        program = parse(source)
        validate(program)
        Compiler(program, "optional_parameters.ru").compile()
        JSCompiler(program, "optional_parameters.ru").compile()

    def test_symbol_map_contract_and_example(self):
        specification = SPECIFICATION.read_text(encoding="utf-8")
        self.assertIn("'{' [表达式 ':' 表达式", specification)
        self.assertIn("`｛` → `{`", specification)
        self.assertIn("允许尾逗号", specification)
        self.assertIn("名称键求名称的当前值", specification)
        self.assertIn("表达式位置的花括号构造典", specification)
        self.assertIn("裸 `{}` 是空块", specification)
        self.assertIn("`{(f 1): (g 2), 'x': 3}`", specification)
        self.assertIn("调用内 `参数名:表达式` 的冒号仍是命名实参", specification)
        self.assertNotIn("位运算、字典、异步", specification)
        source = (ROOT / "examples" / "map_symbol_literals.ru").read_text(encoding="utf-8")
        program = parse(source)
        validate(program)
        Compiler(program, "map_symbol_literals.ru").compile()
        JSCompiler(program, "map_symbol_literals.ru").compile()

    def test_scoped_block_assignment_contract_and_example(self):
        specification = SPECIFICATION.read_text(encoding="utf-8")
        self.assertIn("作用域块   = '段' ':' 程序 '落' '.' | '{' 程序 '}' ['.'] ;", specification)
        self.assertIn("赋值符     = '取' | ':=' ;", specification)
        self.assertIn("`段` 与 `落` 也是上下文词，没有加入保留字集合", specification)
        self.assertIn("每次实际进入块都创建新的词法子环境", specification)
        self.assertIn("直接绑定只属于该环境", specification)
        self.assertIn("块不引入新的函数、过程或循环边界", specification)
        self.assertIn("`尽 取 外言` 是导入语句，仍须使用 `取`", specification)
        self.assertIn("连续的 `：=`", specification)
        self.assertNotIn("未把花括号当作用域块", specification)
        source = (ROOT / "examples" / "scoped_blocks.ru").read_text(encoding="utf-8")
        program = parse(source)
        validate(program)
        Compiler(program, "scoped_blocks.ru").compile()
        JSCompiler(program, "scoped_blocks.ru").compile()

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
