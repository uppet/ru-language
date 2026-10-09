import io
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
from rulang.cli import build, read_source, repl
from rulang.compiler import Compiler
from rulang.frontend import Incomplete, RuError, parse, validate
from rulang.interpreter import Interpreter


def interpret(source, stdin=""):
    output = io.StringIO()
    interpreter = Interpreter(io.StringIO(stdin), output)
    interpreter.execute(parse(source))
    return output.getvalue()


POSITIONAL_REQUEST = """算 平方 根 为 数：
    得 根 * 根.
法

显 (平方 9.9).
"""


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
    ("if_else", "若 假 则 显 '坏'. 另 显 '好'. 然 若 空 则 显 1. 然", "", "好\n"),
    ("comparisons", "显 1 < 2. 显 1 <= 1. 显 '乙' > '甲'. 显 1 == '1'. 显 1 != '1'.", "", "真\n真\n假\n假\n真\n"),
    ("contains", "信 取 '你好，再见'. 显 信@含 '再见'. 显 信 其 含 '你好'. 显 非 (信@含 '再见').", "", "真\n真\n假\n"),
    ("short_circuit", "显 假 且 (1 / 0). 显 真 或 未定义. 显 非 假. 显 2 且 '好'.", "", "假\n真\n真\n真\n"),
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
    ("string_reassignment", "值 取 ''. 循 100 次 值 取 值+'好'. 环 显 值@含 '好好'.", "", "真\n"),
    ("positional_exact_request", POSITIONAL_REQUEST, "", "98.01\n"),
    ("positional_unwrapped", "算 平方 根 为 数: 得 根*根. 法 显 平方 3.", "", "9\n"),
    ("positional_variable", "算 平方 根 为 数: 得 根*根. 法 值 取 4. 显 (平方 值).", "", "16\n"),
    ("positional_greedy", "算 平方 根 为 数: 得 根*根. 法 显 (平方 2+1). 显 (平方 2)+1.", "", "9\n5\n"),
    ("positional_order", "算 差 左 为 数 右 为 数: 得 左-右. 法 左值 取 8. 右值 取 3. 显 (差 左值 右值).", "", "5\n"),
    ("positional_expressions", "算 合 左 为 数 右 为 数: 得 左*10+右. 法 值 取 2. 显 (合 值+1 值*4).", "", "38\n"),
    ("positional_fullwidth_comma", "算 差 左 为 数，右 为 数：得 左-右. 法 显（差 8，3）。", "", "5\n"),
    ("positional_negative", "算 差 左 为 数 右 为 数: 得 左-右. 法 显 (差 (-2) (-3)). 显 (差 2, -3). 显 (差 2, +3).", "", "1\n5\n-1\n"),
    ("positional_signs_stay_binary", "算 固定: 得 9. 法 值 取 7. 显 固定-2. 显 固定+2. 显 值 - 2. 显 值 + 2.", "", "7\n11\n5\n9\n"),
    ("positional_unary_not", "算 回 值: 得 值. 法 显 (回 非 假). 显 (回 (-3)).", "", "真\n-3\n"),
    ("positional_string_operators", "算 合 左 为 句 右 为 句: 得 左+右. 法 显 (合 '+' '-'). 显 (合 '为' '非').", "", "+-\n为非\n"),
    ("positional_colon_literal", "算 合 甲 为 句 乙 为 句: 得 甲+乙. 法 串 取 '前'. 显 (合 串 ':').", "", "前:\n"),
    ("positional_keyword_literal", "作 报 值 为 句: 显 值. 为 报 '取'.", "", "取\n"),
    ("positional_nested", "算 平方 根 为 数: 得 根*根. 法 算 差 左 为 数 右 为 数: 得 左-右. 法 显 (差 (平方 3) (平方 根:2)). 显 (差 左:(平方 4) 右:(平方 3)).", "", "5\n7\n"),
    ("positional_evaluation_order", "算 回 值 为 句: 显 值. 得 值. 法 算 合 左 为 句 右 为 句: 得 左+右. 法 显 (合 (回 '左') (回 '右')).", "", "左\n右\n左右\n"),
    ("positional_recursive", "算 阶乘 值 为 数: 若 值<=1 则 得 1. 另 得 值*(阶乘 值-1). 然 法 显 (阶乘 6).", "", "720\n"),
    ("positional_forward", "显 (平方 4). 算 平方 根 为 数: 得 根*根. 法", "", "16\n"),
    ("positional_zero_arg_as_value", "算 常量: 得 5. 法 算 差 左 为 数 右 为 数: 得 左-右. 法 显 (差 常量 2).", "", "3\n"),
    ("positional_procedure", "作 报 值 为 句: 显 值. 为 报 '好'.", "", "好\n"),
    ("positional_member", "算 回 值 为 事实: 得 值. 法 信 取 '你好'. 显 (回 (信@含 '你')). 显 (回 (信 其 含 '好')).", "", "真\n真\n"),
    ("positional_member_result", "算 回 值 为 句: 得 值. 法 信 取 '你好'. 显 (回 信)@含 '你'. 显 信@含 (回 '好').", "", "真\n真\n"),
    ("positional_conversion", "算 平方 根 为 数: 得 根*根. 法 显 (平方 '3' 为 数). 显 (平方 4) 为 句.", "", "9\n16\n"),
    ("positional_input", "显 (读 '输入：').", "你好\n", "输入：你好\n"),
    ("positional_count", "算 回 值 为 数: 得 值. 法 循 回 2 次 显 '好'. 环", "", "好\n好\n"),
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
    ("missing_return", "算 未返: 显 '开始'. 法 未返.", ""),
    ("read_eof", "循环值 取 0. 循 循环值 取 读. 环", ""),
    ("read_bad_prompt", "显 (读 提示:3).", ""),
    ("read_nul", "显 读.", "a\x00b\n"),
    ("recursion_depth", "算 深: 得 深. 法 显 深.", ""),
    ("positional_typed_parameter", "算 平方 根 为 数: 得 根*根. 法 显 (平方 '3').", ""),
    ("positional_second_type", "算 合 左 为 句 右 为 数: 得 左. 法 显 (合 '好' '3').", ""),
    ("positional_read_bad_prompt", "显 (读 3).", ""),
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
                 "作 错: 得 1. 为", "算 外: 若 1 则 作 内: 显 1. 为 然 得 1. 法",
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

    def test_positional_call_diagnostics(self):
        definition = "算 差 左 为 数 右 为 数: 得 左-右. 法\n"
        cases = [
            (definition + "显 (差 1).", "需要 2 个位置实参（左、右），收到 1 个"),
            (definition + "显 (差 1 2 3).", "需要 2 个位置实参（左、右），收到 3 个"),
            (definition + "显 差.", "缺少「左、右」"),
            (definition + "显 (差 1 -2).", "收到 1 个"),
            (definition + "显 (差 左:1 错:2).", "未知「错」"),
            ("算 无参: 得 1. 法\n显 (无参 2).", "需要 0 个位置实参"),
            ("显 (不存在 1).", "未定义函数：不存在"),
            ("显 (读 '一' '二').", "需要 1 个位置实参（提示），收到 2 个"),
        ]
        for source, message in cases:
            for operation in (interpret, lambda s: Compiler(parse(s)).compile()):
                with self.subTest(source=source, operation=operation):
                    with self.assertRaises(RuError) as context:
                        operation(source)
                    self.assertIn(message, context.exception.message)
                    self.assertEqual(context.exception.line, source.count("\n") + 1)
                    self.assertGreater(context.exception.col, 1)

    def test_call_style_mixing_diagnostics(self):
        for source in ("合 1 乙:2.", "合 甲:1 2.", "合 1, 乙:2.", "合 甲:1, -2."):
            with self.subTest(source=source):
                with self.assertRaises(RuError) as context:
                    parse(source)
                self.assertIn("不能混用位置实参与命名实参", context.exception.message)

    def test_positional_runtime_type_diagnostic(self):
        source = "算 平方 根 为 数: 得 根*根. 法\n显 (平方 '3')."
        with self.assertRaises(RuError) as context:
            interpret(source)
        self.assertEqual((context.exception.line, context.exception.col), (2, 4))
        self.assertIn("实参「根」须为数", context.exception.message)
        self.assertIn("实际收到句", context.exception.message)
        self.assertNotIn("请显式使用", context.exception.message)

    @unittest.skipUnless(any(shutil.which(c) for c in ("clang", "gcc", "cc")), "C compiler unavailable")
    def test_positional_request_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            path, binary, cfile = Path(temp)/"square.ru", Path(temp)/"square", Path(temp)/"square.c"
            path.write_text(POSITIONAL_REQUEST, encoding="utf-8")
            for command in ("check", "run", "build"):
                argv = [sys.executable, str(ROOT/"ru"), command, str(path)]
                if command == "build":
                    argv += ["-o", str(binary), "--emit-c", str(cfile)]
                result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                if command == "run":
                    self.assertEqual(result.stdout, "98.01\n")
            self.assertIn(f"Generated by ru {__version__}", cfile.read_text(encoding="utf-8"))
            path.unlink()
            cfile.unlink()
            result = subprocess.run([binary], capture_output=True, text=True, cwd=temp, env={"PATH": ""}, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "98.01\n")

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

    def test_repl_banner_version(self):
        stdin, stdout = io.StringIO(":quit\n"), io.StringIO()
        with patch.object(stdin, "isatty", return_value=True), \
                patch("sys.stdin", stdin), patch("sys.stdout", stdout):
            self.assertEqual(repl(), 0)
        self.assertTrue(stdout.getvalue().startswith(f"如 {__version__} ·"))
        self.assertIn("元初实现", stdout.getvalue())
        self.assertIn(":退 / :quit 退出", stdout.getvalue())

    def test_repl_exit_aliases(self):
        for command in (":退", ":quit", ":q", ":exit"):
            for interactive in (False, True):
                with self.subTest(command=command, interactive=interactive):
                    stdin = io.StringIO(f"显 '之前'.\n  {command}  \n显 '之后'.\n")
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with patch.object(stdin, "isatty", return_value=interactive), \
                            patch("sys.stdin", stdin), patch("sys.stdout", stdout), \
                            patch("sys.stderr", stderr):
                        self.assertEqual(repl(), 0)
                    self.assertIn("之前\n", stdout.getvalue())
                    self.assertNotIn("之后", stdout.getvalue())
                    self.assertEqual(stderr.getvalue(), "")
                    if not interactive:
                        self.assertEqual(stdout.getvalue(), "之前\n")

    def test_repl_chinese_exit_help_and_command_boundary(self):
        commands = ":help\n:退.\n显 ':退'.\n显 '继续'.\n:退\n显 '之后'.\n"
        result = subprocess.run([sys.executable, str(ROOT/"ru"), "repl"],
                                input=commands, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertIn(":退 / :quit / :q / :exit 退出", result.stdout)
        self.assertTrue(result.stdout.endswith(":退\n继续\n"))
        self.assertIn("未知命令", result.stderr)
        self.assertNotIn("之后", result.stdout)

    def test_repl_exit_text_inside_multiline_input(self):
        commands = "显 ‘第一行\n:退\n最后一行’.\n:退\n显 '之后'.\n"
        result = subprocess.run([sys.executable, str(ROOT/"ru"), "repl"],
                                input=commands, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "第一行\n:退\n最后一行\n")
        self.assertEqual(result.stderr, "")

    def test_repl_persistence_and_multiline(self):
        commands = "值 取 3.\n值+4.\n算 平方 根 为 数:\n得 根*根.\n法\n平方 根:值.\n循 2 次\n值 取 值+1.\n环\n值.\n:quit\n"
        result = subprocess.run([sys.executable, str(ROOT/"ru"), "repl"], input=commands, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "7\n9\n5\n")

    def test_repl_error_recovery(self):
        result = subprocess.run([sys.executable, str(ROOT/"ru"), "repl"], input="值 取 8.\n显 1/0.\n值.\n:quit\n", capture_output=True, text=True, timeout=5)
        self.assertEqual(result.stdout, "8\n")
        self.assertIn("除数不能为零", result.stderr)

    def test_repl_positional_and_redefinition(self):
        commands = ("算 平方 根 为 数:\n得 根*根.\n法\n平方 9.9.\n平方 根:3.\n"
                    "平方 '错'.\n平方 4.\n算 平方 左 为 数 右 为 数:\n得 左*右.\n法\n"
                    "平方 2.\n平方 2 3.\n:quit\n")
        result = subprocess.run([sys.executable, str(ROOT/"ru"), "repl"], input=commands, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "98.01\n9\n16\n6\n")
        self.assertIn("实参「根」须为数", result.stderr)
        self.assertIn("需要 2 个位置实参", result.stderr)

    def test_repl_incomplete_eof(self):
        result = subprocess.run([sys.executable, str(ROOT/"ru"), "repl"], input="若 1 则\n", capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn("期待「然」", result.stderr)

    def test_generation_guard(self):
        # Tests never inherit a developer's LLM credentials or user config.
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "empty.json"
            config.write_text("{}", encoding="utf-8")
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith("RU_LLM_")}
            env["RU_LANG_CONFIG"] = str(config)
            for command in ("run", "check", "build", "generate"):
                result = subprocess.run(
                    [sys.executable, str(ROOT/"ru"), command, str(ROOT/"examples/wish.md")],
                    capture_output=True, text=True, timeout=5, env=env)
                self.assertEqual(result.returncode, 1)
                self.assertIn("生成功能未配置" if command == "generate" else "ru generate", result.stderr)

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
