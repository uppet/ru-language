import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.cli import build, read_source
from rulang.compiler import Compiler
from rulang.frontend import Incomplete, RuError, parse, validate
from rulang.interpreter import Interpreter


def interpret(source, stdin=""):
    output = io.StringIO()
    interpreter = Interpreter(io.StringIO(stdin), output)
    interpreter.execute(parse(source))
    return output.getvalue()


SUCCESS_CASES = [
    ("hello", "显 ‘你好，世界’.", "", "你好，世界\n"),
    ("ascii_quotes", '''显 "hello". 显 'world'.''', "", "hello\nworld\n"),
    ("curly_double_quotes", "显 “你好”.", "", "你好\n"),
    ("fullwidth_punctuation", "显（2+3）。", "", "5\n"),
    ("precedence", "显 1 + 2 * 3. 显 (1 + 2) * 3. 显 -7 % 3.", "", "7\n9\n-1\n"),
    ("numeric_formats", "显 .5 + 1e2 + 2.5E-1.", "", "100.75\n"),
    ("conversion", "显 (' -12.5e1 ' 为 数) + 5. 显 42 为 句. 显 '1.' 为 数.", "", "-120\n42\n1\n"),
    ("conversion_precedence", "显 1 + 2 为 句. 显 ('x' + 'y') 为 句.", "", "3\nxy\n"),
    ("reassignment", "值 取 3. 值 取 值+4. 显 值.", "", "7\n"),
    ("dynamic_binding", "值 取 3. 值 取 '三'. 显 值.", "", "三\n"),
    ("comments", "# 注释\n显 2. // 末尾注释\n", "", "2\n"),
    ("escapes", r'''显 '第一\n第二\t行\\'.''', "", "第一\n第二\t行\\\n"),
    ("if_else", "若 0 则 显 '坏'. 另 显 '好'. 然 若 '' 则 显 1. 然", "", "好\n"),
    ("comparisons", "显 1 < 2. 显 1 <= 1. 显 '乙' > '甲'. 显 1 == '1'. 显 1 != '1'.", "", "1\n1\n0\n0\n1\n"),
    ("contains", "信 取 '你好，再见'. 显 信@含 '再见'. 显 信 其 含 '你好'. 显 非 (信@含 '再见').", "", "1\n1\n0\n"),
    ("short_circuit", "显 0 且 (1 / 0). 显 1 或 未定义. 显 非 0. 显 2 且 '好'.", "", "0\n1\n1\n1\n"),
    ("counted_loop", "和 取 0. 循 5 次 和 取 和 + 1. 环 显 和. 循 0 次 显 '坏'. 环", "", "5\n"),
    ("count_expression", "和 取 0. 次数 取 3. 循 次数 + 1 次 和 取 和 + 1. 环 显 和.", "", "4\n"),
    ("unbounded_break", "值 取 0. 循 值 取 值+1. 若 值 == 3 则 破. 然 环 显 值.", "", "3\n"),
    ("nested_break", "值 取 0. 循 3 次 循 值 取 值+1. 破. 环 环 显 值.", "", "3\n"),
    ("square", "算 平方 根 为 数： 得 根 * 根. 法 显 (平方 根: 9).", "", "81\n"),
    ("procedure", "作 祭拜: 循 3 次 显 '叩'. 环 为 . 祭拜.", "", "叩\n叩\n叩\n"),
    ("function_io", "算 报数 值 为 数: 显 值. 得 值+1. 法 显 (报数 值: 2).", "", "2\n3\n"),
    ("recursive", "算 阶乘 值 为 数: 若 值<=1 则 得 1. 另 得 值*(阶乘 值: 值-1). 然 法 显 (阶乘 值: 6).", "", "720\n"),
    ("forward_function", "显 (值). 算 值: 得 8. 法", "", "8\n"),
    ("lexical_scope", "值 取 1. 作 改: 值 取 2. 显 值. 为 改. 显 值.", "", "2\n1\n"),
    ("global_read", "值 取 '世界'. 算 问候: 得 '你好'+值. 法 显 问候.", "", "你好世界\n"),
    ("named_order", "算 回 值 为 句: 显 值. 得 值. 法 算 合 左 为 句 右 为 句: 得 左+右. 法 显 (合 右: (回 值: '右') 左: (回 值: '左')).", "", "右\n左\n左右\n"),
    ("named_variable_arguments", "算 合 甲 为 句 乙 为 句: 得 甲+乙. 法 串 取 '甲'. 显 (合 甲: 串 乙: '乙').", "", "甲乙\n"),
    ("named_expression_arguments", "算 和 甲 为 数 乙 为 数: 得 甲+乙. 法 值 取 2. 显 (和 甲: 值+值 乙: 值*3).", "", "10\n"),
    ("input_add", "左 取 (读 提示:'甲：') 为 数. 右 取 (读 提示:'乙：') 为 数. 显 左+右.", "2\n3\n", "甲：乙：5\n"),
    ("input_crlf", "显 读. 显 读.", "一\r\n二\r\n", "一\n二\n"),
    ("input_no_newline", "显 读.", "尾行", "尾行\n"),
    ("input_empty_line", "显 '前'+(读)+'后'.", "\n", "前后\n"),
    ("input_loop", "循 信 取 读. 若 信 其 含 '再见' 则 破. 另 显 信. 然 环", "你好\n再见\n", "你好\n"),
    ("owned_return", "算 合 甲 为 句 乙 为 句: 暂 取 甲+乙. 得 暂. 法 显 '前'+(合 甲:'甲' 乙:'乙')+'后'.", "", "前甲乙后\n"),
    ("string_reassignment", "值 取 ''. 循 100 次 值 取 值+'好'. 环 显 值@含 '好好'.", "", "1\n"),
]

ERROR_CASES = [
    ("invalid_number", "显 '不是数字' 为 数.", ""),
    ("empty_number", "显 '' 为 数.", ""),
    ("hex_number", "显 '0x10' 为 数.", ""),
    ("nan_number", "显 'nan' 为 数.", ""),
    ("infinite_number", "显 '1e999' 为 数.", ""),
    ("divide_zero", "显 1/0.", ""),
    ("remainder_zero", "显 1%0.", ""),
    ("overflow", "显 1e308*1e308.", ""),
    ("unknown_variable", "显 不存在.", ""),
    ("type_mismatch", "显 1+'x'.", ""),
    ("contains_type", "显 1@含 '1'.", ""),
    ("fractional_count", "循 1.5 次 显 1. 环", ""),
    ("negative_count", "循 -1 次 显 1. 环", ""),
    ("string_count", "循 '3' 次 显 1. 环", ""),
    ("typed_parameter", "算 平方 根 为 数: 得 根*根. 法 显 (平方 根:'3').", ""),
    ("missing_return", "算 空: 显 '开始'. 法 空.", ""),
    ("read_eof", "循环值 取 0. 循 循环值 取 读. 环", ""),
    ("read_bad_prompt", "显 (读 提示:3).", ""),
    ("read_nul", "显 读.", "a\x00b\n"),
    ("recursion_depth", "算 深: 得 深. 法 显 深.", ""),
]


class LanguageTests(unittest.TestCase):
    def test_interpreter_success_cases(self):
        for name, source, stdin, expected in SUCCESS_CASES:
            with self.subTest(case=name):
                self.assertEqual(interpret(source, stdin), expected)

    def test_interpreter_errors(self):
        for name, source, stdin in ERROR_CASES:
            with self.subTest(case=name):
                with self.assertRaises(RuError):
                    interpret(source, stdin)

    @unittest.skipUnless(any(shutil.which(c) for c in ("clang", "gcc", "cc")), "C compiler unavailable")
    def test_native_success_cases(self):
        with tempfile.TemporaryDirectory() as temp:
            for name, source, stdin, expected in SUCCESS_CASES:
                with self.subTest(case=name):
                    binary, _ = build(parse(source), name+".ru", Path(temp)/name)
                    result = subprocess.run([binary], input=stdin, capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, expected)

    @unittest.skipUnless(any(shutil.which(c) for c in ("clang", "gcc", "cc")), "C compiler unavailable")
    def test_native_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            for name, source, stdin in ERROR_CASES:
                with self.subTest(case=name):
                    binary, _ = build(parse(source), name+".ru", Path(temp)/name)
                    result = subprocess.run([binary], input=stdin, capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("运行错误", result.stderr)
                    self.assertIn(name+".ru:", result.stderr)

    def test_structural_errors(self):
        cases = ["显 1", "若 1 则 显 1.", "显 ‘未结束", "破.", "得 1.",
                 "作 错: 得 1. 为", "算 外: 作 内: 显 1. 为 得 1. 法",
                 "算 同 值 为 数 值 为 数: 得 1. 法", "算 读: 得 1. 法",
                 "算 函: 得 1. 法 函 取 1.", "作 错: 破. 为",
                 "显 1e999.", "显 'x' @ 不支持 'a'.", "显 'bad\\z'."]
        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(RuError):
                    validate(parse(source))

    def test_named_call_errors(self):
        for source in ["未定义 值:1.", "算 平方 根 为 数: 得 根. 法 平方.",
                       "算 平方 根 为 数: 得 根. 法 平方 根:1 根:2.", "读 错:1."]:
            with self.subTest(source=source):
                with self.assertRaises(RuError):
                    Compiler(parse(source)).compile()
                with self.assertRaises(RuError):
                    interpret(source)

    def test_line_column_diagnostic(self):
        with self.assertRaises(RuError) as context:
            parse("显 1.\n显 ).")
        self.assertEqual((context.exception.line, context.exception.col), (2, 3))

    def test_incomplete(self):
        for source in ("显 1", "算 平方 根 为 数:\n得 根*根.", "循\n显 1."):
            with self.assertRaises(Incomplete):
                parse(source)

    def test_deep_nesting_has_clean_diagnostic(self):
        source = "显 " + "(" * 1100 + "1" + ")" * 1100 + "."
        with self.assertRaises(RuError) as context:
            parse(source)
        self.assertIn("嵌套过深", context.exception.message)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"deep.ru"
            path.write_text(source, encoding="utf-8")
            for command in ("run", "check", "build"):
                result = subprocess.run([sys.executable, str(ROOT/"ru"), command, str(path)], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 1)
                self.assertIn("嵌套过深", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_repl_persistence_and_multiline(self):
        commands = "值 取 3.\n值+4.\n算 平方 根 为 数:\n得 根*根.\n法\n平方 根:值.\n循 2 次\n值 取 值+1.\n环\n值.\n:quit\n"
        result = subprocess.run([sys.executable, str(ROOT/"ru"), "repl"], input=commands, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "7\n9\n5\n")

    def test_repl_error_recovery(self):
        result = subprocess.run([sys.executable, str(ROOT/"ru"), "repl"], input="值 取 8.\n显 1/0.\n值.\n:quit\n", capture_output=True, text=True, timeout=5)
        self.assertEqual(result.stdout, "8\n")
        self.assertIn("除数不能为零", result.stderr)

    def test_repl_incomplete_eof(self):
        result = subprocess.run([sys.executable, str(ROOT/"ru"), "repl"], input="若 1 则\n", capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn("期待「然」", result.stderr)

    def test_generation_guard(self):
        for command in ("run", "check", "build", "generate"):
            result = subprocess.run([sys.executable, str(ROOT/"ru"), command, str(ROOT/"examples/wish.md")], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 1)
            self.assertIn("生成功能未配置", result.stderr)

    @unittest.skipUnless(any(shutil.which(c) for c in ("clang", "gcc", "cc")), "C compiler unavailable")
    def test_native_without_source_or_python(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)/"gone.ru"
            source.write_text("显 '独立运行'.", encoding="utf-8")
            binary, _ = build(parse(source.read_text(encoding="utf-8")), source, Path(temp)/"standalone")
            source.unlink()
            result = subprocess.run([binary], capture_output=True, text=True, cwd=temp, env={"PATH": ""}, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "独立运行\n")
            if sys.platform.startswith("linux"):
                self.assertEqual(binary.read_bytes()[:4], b"\x7fELF")

    def test_examples(self):
        for path in (ROOT/"examples").glob("*.ru"):
            with self.subTest(example=path.name):
                Compiler(parse(path.read_text(encoding="utf-8")), str(path)).compile()


if __name__ == "__main__":
    unittest.main(verbosity=2)
