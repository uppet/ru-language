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
from rulang import __version__
from rulang.compiler import Compiler
from rulang.js_compiler import JSCompiler
from rulang.frontend import parse, validate
from rulang.modules import import_nodes


SPECIFICATION = ROOT / "rulang" / "language-spec.md"


class SpecificationExamples(unittest.TestCase):
    def test_elif_contract_and_example(self):
        specification = SPECIFICATION.read_text(encoding="utf-8")
        self.assertIn("{'另若' 表达式 '则' 程序}", specification)
        self.assertIn("只有 `空` 和 `假` 为假", specification)
        source = (ROOT / "examples" / "elif.ru").read_text(encoding="utf-8")
        program = parse(source)
        validate(program)
        Compiler(program, "elif.ru").compile()
        JSCompiler(program, "elif.ru").compile()

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
        self.assertIn("作为目的名称求名称的当前值", specification)
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
        self.assertIn("`尽取 外言` 是独立导入语句，`尽取` 是一个完整关键字", specification)
        self.assertIn("连续的 `：=`", specification)
        self.assertNotIn("未把花括号当作用域块", specification)
        source = (ROOT / "examples" / "scoped_blocks.ru").read_text(encoding="utf-8")
        program = parse(source)
        validate(program)
        Compiler(program, "scoped_blocks.ru").compile()
        JSCompiler(program, "scoped_blocks.ru").compile()

    def test_map_teaching_terms_match_named_arguments(self):
        for name in ("docs/language-guide.md", "rulang/language-spec.md",
                     "docs/maps-facts-migration.md", "emacs/README.md",
                     "rushu/README.md"):
            with self.subTest(document=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("目（key）", text)
                self.assertIn("相（value）", text)
                self.assertIn("成员命名实参统一使用 `目:`、`相:`", text)
                self.assertIn("`值` 仍是语言的通用概念", text)
        specification = SPECIFICATION.read_text(encoding="utf-8")
        self.assertIn("两个位置实参（目、相）", specification)
        self.assertIn("无法区分缺失与已存空，这是本版明确选择", specification)
        self.assertIn("`其 增 目:… 相:…`", specification)

    def test_documented_numeric_and_fact_contracts(self):
        specification = SPECIFICATION.read_text(encoding="utf-8")
        self.assertIn("| `取整` | `值 为 数` | 向零截断后的数 |", specification)
        self.assertIn("| `绝对` | `值 为 数` | 值的绝对值 |", specification)
        self.assertIn("时成功返回事实假；权限等 stat", specification)
        self.assertIn("| 5 | `为 数`、`为 句`、`为 阵`、`为 事实` |", specification)
        contest = specification.split("### 11.7", 1)[1].split("### 11.8", 1)[0]
        self.assertNotIn("按上述真值规则得到真或假", contest)
        self.assertTrue(all(line.count("|") == 4 for line in contest.splitlines()
                            if line.startswith("|")))

    def test_editor_version_blocks_and_alias_tracker(self):
        self.assertIn("编辑器同步如 " + __version__, (ROOT / "rushu/README.md").read_text(encoding="utf-8"))
        emacs = (ROOT / "emacs/README.md").read_text(encoding="utf-8")
        blocks = next(line for line in emacs.splitlines() if line.startswith("“代码块”包括"))
        self.assertIn("`段: … 落.` / 语句花括号块", blocks)
        specification = SPECIFICATION.read_text(encoding="utf-8")
        self.assertIn("典 / 成、段 / 落及语句花括号块", specification)
        self.assertNotIn("本规范的六类配对", specification)
        tracker = (ROOT / "docs/language-review-tracker.md").read_text(encoding="utf-8")
        local_alias = tracker.split("### RU-027", 1)[1].split("## 维护记录", 1)[0]
        self.assertIn("状态：已解决（RU-001 已覆盖）", local_alias)
        self.assertIn("历史基线", local_alias)
        self.assertNotIn("状态：待确认", local_alias)

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
