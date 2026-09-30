"""0.2 collection, object, module and executable-entry regression tests.

Success and runtime-error cases are exercised by both engines. Module and entry
cases use the public CLI so path resolution and standalone bundling are tested.
"""
import io
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.cli import build
from rulang.compiler import Compiler
from rulang.frontend import RuError, parse, validate
from rulang.interpreter import Interpreter

HAS_CC = any(shutil.which(c) for c in ("clang", "gcc", "cc"))


def interpret(source):
    output = io.StringIO()
    interpreter = Interpreter(io.StringIO(), output)
    interpreter.execute(parse(source))
    return output.getvalue()


OBJECT = """
形 计数:
    值 为 数.
    作 加 步 为 数: 其 值 取 其 值 + 步. 为
    算 读值: 得 其 值. 法
    算 自身: 得 其. 法
象
"""

SUCCESS_CASES = [
    ("original_gender_pair", "男女 取 '男' 对 '女'. 显 男女 其 囫. 显 男女 其 囵.", "男\n女\n"),
    ("keyword_prefix_identifier_function", "算 为乐 事 为 句: 得 事+'快乐'. 法 显 (为乐 '学习').", "学习快乐\n"),
    ("keyword_prefix_identifier_variable", "为乐 取 '普通名称'. 显 为乐.", "普通名称\n"),
    ("students_example", (ROOT/"examples/students.ru").read_text(encoding="utf-8"), "小明同学，18岁，人类\n小青，18岁，人类\n2\n小青\n学习使我快乐\n"),
    ("null_distinct", "显 空. 显 空 == 空. 显 空 == '空'. 显 空 == 0. 显 空 == ''. 显 非 空.", "空\n1\n0\n0\n0\n1\n"),
    ("structured_display_and_cycle", "列 取 [1,空]. 列 其 增 列. 显 列. 显 1 对 2 对 空. 显 空 为 句.", "[1, 空, <循环>]\n(1 对 (2 对 空))\n空\n"),
    ("contains_nested_positional", "算 回 值 为 句: 得 值. 法 显 '甲'@含 回 '甲'.", "1\n"),
    ("contains_nested_named", "算 回 值 为 句: 得 值. 法 显 '甲'@含 回 值:'甲'.", "1\n"),
    ("null_truth", "若 空 则 显 0. 另 显 1. 然 显 空 或 2. 显 空 且 (1/0).", "1\n1\n0\n"),
    ("pair_right_associative", "链 取 1 对 2 对 空. 显 链 其 囫. 显 (链 其 囵) 其 囫. 显 (链 其 囵) 其 囵 == 空.", "1\n2\n1\n"),
    ("pair_precedence", "对值 取 1+2 对 3*4. 显 对值 其 囫. 显 对值 其 囵.", "3\n12\n"),
    ("pair_structural_equality", "显 (1 对 2 对 空) == (1 对 2 对 空). 显 (1 对 空) != (2 对 空).", "1\n1\n"),
    ("pair_identity_leaves", "列 取 [1]. 显 (列 对 空) == (列 对 空). 显 ([1] 对 空) == ([1] 对 空).", "1\n0\n"),
    ("singleton_conversion", "列 取 空 为 阵. 显 列 其 量. 显 列[0] == 空. 显 ('你好' 为 阵) 其 量. 显 (3 为 阵)[0].", "1\n1\n1\n3\n"),
    ("array_empty_and_mixed", "列 取 []. 显 列 其 量. 显 非 列. 列 其 增 1. 列 其 增 '二'. 列 其 增 空. 显 列[0]. 显 列[1]. 显 列[2].", "0\n1\n1\n二\n空\n"),
    ("array_alias_assignment", "甲 取 [1,2]. 乙 取 甲. 乙[0] 取 9. 乙 其 增 3. 显 甲[0]. 显 甲 其 量. 显 甲 == 乙. 显 甲 == [9,2,3].", "9\n3\n1\n0\n"),
    ("array_append_result", "列 取 []. 别名 取 列 其 增 7. 显 别名 == 列. 显 别名[0].", "1\n7\n"),
    ("array_member_named", "列 取 []. 列 其 增 值:7. 显 列 其 位 位:0.", "7\n"),
    ("array_member_index", "列 取 [2,4,6]. 显 列 其 位 1. 列 其 位 1 取 8. 显 列[1].", "4\n8\n"),
    ("array_slice_bounds", "列 取 [0,1,2,3]. 显 列[1:3] 其 量. 显 列[:2][1]. 显 列[2:][0]. 显 列[:] 其 量. 显 列[4:4] 其 量.", "2\n1\n2\n4\n0\n"),
    ("array_member_slice", "列 取 [0,1,2,3]. 显 (列 其 段 1 3)[0]. 显 (列 其 段 终:3 始:1)[1].", "1\n2\n"),
    ("array_slice_shallow", "内 取 [1]. 原 取 [内,2]. 副 取 原[:]. 副[1] 取 8. 副[0][0] 取 9. 显 原[1]. 显 原[0][0]. 显 原 == 副. 显 原[0] == 副[0].", "2\n9\n0\n1\n"),
    ("array_self_cycle", "列 取 []. 列 其 增 列. 别名 取 列[0]. 显 别名 == 列. 显 别名 其 量. 列[0] 取 空. 显 别名[0].", "1\n1\n空\n"),
    ("array_nested_singleton", "甲 取 [1]. 乙 取 甲 为 阵. 显 乙 其 量. 显 乙[0] == 甲.", "1\n1\n"),
    ("utf8_index_length", "文 取 '甲😀é乙'. 显 文 其 量. 显 文[1]. 显 文 其 位 2.", "4\n😀\né\n"),
    ("utf8_slice", "文 取 '甲😀é乙'. 显 文[1:3]. 显 文[:1]. 显 文[3:]. 显 文[4:4]. 显 文 其 段 始:1 终:3.", "😀é\n甲\n乙\n\n😀é\n"),
    ("unicode_codepoints", "文 取 'é👩‍💻'. 显 文 其 量. 显 文[1]. 显 文[2:5].", "5\ń\n👩‍💻\n"),
    ("typed_arrays", "算 首 列 为 句 阵: 得 列[0]. 法 算 量 列 为 阵: 得 列 其 量. 法 显 (首 ['甲','乙']). 显 (量 [1,'二',空]).", "甲\n3\n"),
    ("typed_array_mutation_alias", "作 加 列 为 数 阵: 列 其 增 7. 为 列 取 [1]. 加 列. 显 列[1].", "7\n"),
    ("standard_contains_method_dispatch", "形 A: 算 含 句 为 句: 得 句. 法 象 甲 取 新 A. 显 甲 其 含 '好'. 显 甲 其 含 句:'好'.", "好\n好\n"),
    ("class_alias_rebinding", "形 A: 象 别 取 A. 别 取 1. 显 别.", "1\n"),
    ("object_field_and_methods", OBJECT + "甲 取 新 计数 值:2. 甲 其 加 3. 显 甲 其 读值. 显 (甲 其 自身) == 甲.", "5\n1\n"),
    ("object_aliasing", OBJECT + "甲 取 新 计数 值:1. 乙 取 甲. 乙 其 值 取 4. 显 甲 其 值. 显 甲 == 乙. 显 甲 == (新 计数 值:4).", "4\n1\n0\n"),
    ("object_singleton", OBJECT + "甲 取 新 计数 值:1. 列 取 甲 为 阵. 列[0] 其 值 取 6. 显 甲 其 值. 显 列[0] == 甲.", "6\n1\n"),
    ("object_missing_null", "形 人: 名 为 句. 龄 为 数. 象 甲 取 新 人 名:'甲'. 显 甲 其 龄 == 空. 甲 其 龄 取 3. 甲 其 龄 取 空. 显 甲 其 龄.", "1\n空\n"),
    ("object_cycle", "形 节: 后 为 节. 值 为 数. 象 甲 取 新 节 值:3. 甲 其 后 取 甲. 显 甲 其 后 == 甲. 显 (甲 其 后) 其 值. 甲 其 后 取 空.", "1\n3\n"),
    ("object_inheritance_dispatch", "形 基: 值 为 数. 算 读值: 得 其 值. 法 算 双读: 得 (其 读值)*2. 法 象 形 子 如 基: 名 为 句. 算 读值: 得 其 值+1. 法 象 甲 取 新 子 值:3 名:'子'. 显 甲 其 名. 显 甲 其 读值. 显 甲 其 双读.", "子\n4\n8\n"),
    ("object_subtype_parameter", "形 基: 值 为 数. 象 形 子 如 基: 名 为 句. 象 算 读值 对象 为 基: 得 对象 其 值. 法 显 (读值 (新 子 值:9 名:'子')).", "9\n"),
    ("object_argument_order", "算 报 值 为 数: 显 值. 得 值. 法 形 点: 左 为 数. 右 为 数. 象 点值 取 新 点 右:(报 2) 左:(报 1). 显 点值 其 左. 显 点值 其 右.", "2\n1\n1\n2\n"),
    ("method_named_order", "形 报告: 算 合 左 为 数 右 为 数: 得 左*10+右. 法 象 值 取 新 报告. 显 值 其 合 右:2 左:1.", "12\n"),
    ("linked_list_algorithm", "链 取 1 对 2 对 3 对 空. 和 取 0. 循 若 链 == 空 则 破. 然 和 取 和+链 其 囫. 链 取 链 其 囵. 环 显 和.", "6\n"),
    ("array_sort_algorithm", "列 取 [5,1,4,2,3]. 循 5 次 位 取 0. 循 4 次 若 列[位]>列[位+1] 则 暂 取 列[位]. 列[位] 取 列[位+1]. 列[位+1] 取 暂. 然 位 取 位+1. 环 环 显 列[0]. 显 列[4].", "1\n5\n"),
]

RUNTIME_ERRORS = [
    ("undefined_help_identifier", "显 助人."),
    ("undefined_joy_identifier", "显 为乐."),
    ("null_arithmetic", "显 空+1."),
    ("null_number", "显 空 为 数."),
    ("index_negative", "显 [1][-1]."),
    ("index_fractional", "显 [1][0.5]."),
    ("index_string", "显 [1]['0']."),
    ("index_at_length", "显 [1][1]."),
    ("index_empty", "显 [][0]."),
    ("index_huge", "显 [1][1e100]."),
    ("index_non_collection", "显 1[0]."),
    ("string_index_past", "显 '😀'[1]."),
    ("slice_negative", "显 [1,2][-1:1]."),
    ("slice_reversed", "显 [1,2][2:1]."),
    ("slice_past_end", "显 [1,2][0:3]."),
    ("slice_fractional", "显 '甲乙'[0:1.5]."),
    ("string_immutable", "文 取 '甲乙'. 文[0] 取 '丙'."),
    ("append_string", "文 取 '甲'. 文 其 增 '乙'."),
    ("pair_field_wrong_type", "值 取 1. 显 值 其 囫."),
    ("pair_immutable", "值 取 1 对 2. 值 其 囫 取 3."),
    ("array_parameter_element_type", "算 首 列 为 数 阵: 得 列[0]. 法 显 (首 [1,'二'])."),
    ("array_parameter_scalar", "算 首 列 为 数 阵: 得 列[0]. 法 显 (首 1)."),
    ("object_wrong_field_type", "形 人: 龄 为 数. 象 甲 取 新 人 龄:1. 甲 其 龄 取 '老'."),
    ("object_unknown_field", "形 人: 龄 为 数. 象 甲 取 新 人 龄:1. 显 甲 其 未知."),
    ("object_unknown_write", "形 人: 龄 为 数. 象 甲 取 新 人 龄:1. 甲 其 未知 取 3."),
    ("constructor_wrong_type", "形 人: 龄 为 数. 象 甲 取 新 人 龄:'老'."),
    ("method_wrong_type", OBJECT + "甲 取 新 计数 值:1. 甲 其 加 '二'."),
    ("object_unrelated_parameter", "形 甲: 值 为 数. 象 形 乙: 值 为 数. 象 算 读值 对象 为 甲: 得 对象 其 值. 法 显 (读值 (新 乙 值:1))."),
]

STRUCTURAL_ERRORS = [
    "列 取 [1]. 列[:] 取 [].",
    "显 [1,2.",
    "显 1 对 .",
    "其 值 取 1.",
    "形 人: 龄 为 数.",
    "形 人: 龄 为 数. 龄 为 数. 象",
    "形 人: 算 问: 得 1. 法 算 问: 得 2. 法 象",
    "形 人 如 不存在: 象",
    "形 甲 如 乙: 象 形 乙 如 甲: 象",
    "形 基: 算 读值 值 为 数: 得 值. 法 象 形 子 如 基: 算 读值 值 为 句: 得 值. 法 象",
    "形 基: 算 读值 值 为 数: 得 值. 法 象 形 子 如 基: 算 读值 别名 为 数: 得 别名. 法 象",
    "形 基: 算 读值: 得 1. 法 象 形 子 如 基: 作 读值: 显 1. 为 象",
]


class ExtensionValueTests(unittest.TestCase):
    def test_interpreter_success(self):
        for name, source, expected in SUCCESS_CASES:
            with self.subTest(case=name):
                self.assertEqual(interpret(source), expected)

    @unittest.skipUnless(HAS_CC, "C compiler unavailable")
    def test_native_success(self):
        with tempfile.TemporaryDirectory() as temp:
            for name, source, expected in SUCCESS_CASES:
                with self.subTest(case=name):
                    binary, _ = build(parse(source), name+".ru", Path(temp)/name)
                    result = subprocess.run([binary], capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, expected)

    def test_interpreter_runtime_errors(self):
        for name, source in RUNTIME_ERRORS:
            with self.subTest(case=name):
                with self.assertRaises(RuError) as context:
                    interpret(source)
                self.assertEqual(context.exception.category, "运行错误")

    @unittest.skipUnless(HAS_CC, "C compiler unavailable")
    def test_native_runtime_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            for name, source in RUNTIME_ERRORS:
                with self.subTest(case=name):
                    binary, _ = build(parse(source), name+".ru", Path(temp)/name)
                    result = subprocess.run([binary], capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("运行错误", result.stderr)
                    self.assertIn(name+".ru:", result.stderr)

    def test_structural_errors(self):
        for source in STRUCTURAL_ERRORS:
            for operation in (interpret, lambda s: Compiler(parse(s)).compile()):
                with self.subTest(source=source, operation=operation):
                    with self.assertRaises(RuError):
                        operation(source)

    def test_assignment_checks_target_before_rhs(self):
        prefix = "算 副作用: 显 '不应执行'. 得 2. 法 "
        for suffix in ("列 取 [1]. 列[2] 取 副作用.",
                       "列 取 [1]. 列[-1] 取 副作用.",
                       "列 取 1. 列[0] 取 副作用.",
                       "列 取 '甲'. 列[0] 取 副作用.",
                       "算 生 列 为 阵: 列 其 增 8. 得 9. 法 列 取 []. 列[0] 取 (生 列)."):
            with self.subTest(source=suffix):
                output = io.StringIO()
                with self.assertRaises(RuError):
                    Interpreter(io.StringIO(), output).execute(parse(prefix+suffix))
                self.assertEqual(output.getvalue(), "")
                if HAS_CC:
                    with tempfile.TemporaryDirectory() as temp:
                        binary, _ = build(parse(prefix+suffix), "target_order.ru", Path(temp)/"target-order")
                        result = subprocess.run([binary], capture_output=True, text=True, timeout=10)
                        self.assertEqual(result.returncode, 1, result.stderr)
                        self.assertEqual(result.stdout, "")

    @unittest.skipUnless(HAS_CC, "C compiler unavailable")
    def test_native_tracing_gc_cycles_and_live_aliases(self):
        source = """
形 节:
    后 为 节.
    值 为 数.
    列 为 阵.
象
算 创建 值 为 数:
    甲 取 新 节 值:值 列:[].
    甲 其 后 取 甲.
    甲 其 列 其 增 甲.
    环对 取 甲 对 甲 其 列.
    甲 其 列 其 增 环对.
    甲 其 列 其 增 ('甲'+'乙').
    得 甲.
法
保留 取 创建 41.
别名 取 保留 其 列.
循 2000 次 临时 取 创建 1. 环
显 别名[0] 其 值.
显 保留 其 后 == 保留.
显 别名 其 量.
显 (别名[1] 其 囫) == 保留.
"""
        expected = "41\n1\n3\n1\n"
        self.assertEqual(interpret(source), expected)
        with tempfile.TemporaryDirectory() as temp:
            binary, _ = build(parse(source), "gc_cycles.ru", Path(temp)/"gc-cycles")
            environment = dict(os.environ, RU_GC_THRESHOLD="1", RU_GC_STATS="1")
            result = subprocess.run([binary], env=environment, capture_output=True,
                                    text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, expected)
            stats = re.search(r"RU_GC live=(\d+) freed=(\d+) collections=(\d+)", result.stderr)
            self.assertIsNotNone(stats, result.stderr)
            live, freed, collections = map(int, stats.groups())
            self.assertEqual(live, 0, result.stderr)
            self.assertGreater(freed, 5000, result.stderr)
            self.assertGreater(collections, 1000, result.stderr)

    def test_repl_collections_and_no_automatic_entry(self):
        commands = ("列 取 [1].\n列 其 增 2.\n显 列 其 量.\n"
                    "算 元初 参数 为 句 阵:\n显 '不应自动调用'.\n得 0.\n法\n"
                    "显 列[1].\n:quit\n")
        result = subprocess.run([sys.executable, str(ROOT/"ru"), "repl"], input=commands,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("不应自动调用", result.stdout)
        self.assertTrue(result.stdout.endswith("2\n2\n"), result.stdout)


class ExtensionCLITests(unittest.TestCase):
    def cli(self, command, source, *extra, cwd=None):
        return subprocess.run([sys.executable, str(ROOT/"ru"), command, str(source), *extra],
                              cwd=cwd, capture_output=True, text=True, timeout=30)

    def write_tree(self, root, files):
        for name, source in files.items():
            path = Path(root)/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        return Path(root)/"main.ru"

    def both(self, files, expected, args=(), exitcode=0, standalone=False):
        with tempfile.TemporaryDirectory() as temp:
            main = self.write_tree(temp, files)
            checked = self.cli("check", main, cwd="/")
            self.assertEqual(checked.returncode, 0, checked.stderr)
            result = self.cli("run", main, "--", *args, cwd="/")
            self.assertEqual(result.returncode, exitcode, result.stderr)
            self.assertEqual(result.stdout, expected)
            if HAS_CC:
                binary, cfile = Path(temp)/"standalone", Path(temp)/"standalone.c"
                result = self.cli("build", main, "-o", str(binary), "--emit-c", str(cfile), cwd="/")
                self.assertEqual(result.returncode, 0, result.stderr)
                if standalone:
                    for path in Path(temp).rglob("*.ru"):
                        path.unlink()
                    cfile.unlink()
                result = subprocess.run([binary, *args], cwd="/", env={"PATH": ""},
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, exitcode, result.stderr)
                self.assertEqual(result.stdout, expected)

    def test_entry_argv_exit_and_top_level(self):
        self.both({"main.ru": "显 '顶层'. 算 元初 外参 为 句 阵: 显 外参 其 量. 显 外参[0]. 显 外参[1]. 得 7. 法"},
                  "顶层\n2\n甲😀\n--flag\n", args=("甲😀", "--flag"), exitcode=7, standalone=True)

    def test_shared_pair_dag_equality(self):
        self.both({"main.ru": "左 取 0 对 空. 右 取 0 对 空. 循 30 次 左 取 左 对 左. 右 取 右 对 右. 环 显 左 == 右."}, "1\n")

    def test_entry_empty_argv(self):
        self.both({"main.ru": "算 元初 参数 为 句 阵: 显 参数 其 量. 得 0. 法"}, "0\n")

    def test_modules_cached_and_relative_to_importer(self):
        self.both({"main.ru": "甲 取 外言 'sub/a.ru'. 乙 取 外言 'sub/a.ru'. 显 甲 == 乙. 显 甲 其 加 3. 显 乙 其 数列[0].",
                   "sub/a.ru": "显 '初始化'. 数列 取 [10]. 算 加 值 为 数: 数列[0] 取 数列[0]+值. 得 数列[0]. 法"},
                  "初始化\n1\n13\n13\n", standalone=True)

    def test_module_paths_normalized_cache(self):
        self.both({"main.ru": "甲 取 外言 'sub/a.ru'. 乙 取 外言 'sub/../sub/a.ru'. 显 甲 == 乙.",
                   "sub/a.ru": "显 '只一次'."}, "只一次\n1\n")

    def test_module_lexical_global_scope(self):
        self.both({"main.ru": "值 取 100. 模 取 外言 'lib.ru'. 显 模 其 加 3. 显 值.",
                   "lib.ru": "值 取 10. 算 加 数值 为 数: 得 值+数值. 法"}, "13\n100\n")

    def test_import_all_function_type_and_shared_array(self):
        self.both({"main.ru": "尽 取 外言 'lib.ru'. 显 (平方 4). 甲 取 新 人 名:'甲'. 显 甲 其 名. 列 其 增 2. 模 取 外言 'lib.ru'. 显 模 其 列 其 量.",
                   "lib.ru": "列 取 [1]. 算 平方 根 为 数: 得 根*根. 法 形 人: 名 为 句. 象"}, "16\n甲\n2\n")

    def test_cross_module_inheritance_and_dispatch(self):
        self.both({"main.ru": "尽 取 外言 'base.ru'. 形 子 如 父: 算 读取: 得 其 值*2. 法 象 对象 取 新 子 值:3. 显 对象 其 读取. 显 对象 其 双读.",
                   "base.ru": "显 '初始化'. 形 父: 值 为 数. 算 读取: 得 其 值. 法 算 双读: 得 (其 读取)*2. 法 象"},
                  "初始化\n6\n12\n", standalone=True)

    def test_imported_scalar_can_be_rebound_locally(self):
        self.both({"main.ru": "尽 取 外言 'lib.ru'. 值 取 2. 显 值. 模 取 外言 'lib.ru'. 显 模 其 值.",
                   "lib.ru": "值 取 1."}, "2\n1\n")

    def test_imported_entry_not_called(self):
        self.both({"main.ru": "模 取 外言 'lib.ru'. 显 '主文件'. 算 元初 参数 为 句 阵: 显 '主入口'. 得 0. 法",
                   "lib.ru": "显 '库顶层'. 算 元初 参数 为 句 阵: 显 '库入口错误'. 得 9. 法"}, "库顶层\n主文件\n主入口\n")
        self.both({"main.ru": "尽 取 外言 'lib.ru'. 显 '主文件'.",
                   "lib.ru": "算 元初 参数 为 句 阵: 显 '库入口错误'. 得 9. 法"}, "主文件\n")

    def test_diamond_import_initialized_once(self):
        self.both({"main.ru": "甲 取 外言 'a.ru'. 乙 取 外言 'b.ru'. 显 (甲 其 共) == (乙 其 共).",
                   "a.ru": "共 取 外言 'common.ru'.",
                   "b.ru": "共 取 外言 'common.ru'.",
                   "common.ru": "显 '共用初始化'. 列 取 []."}, "共用初始化\n1\n")

    def test_module_cycle_missing_and_import_collisions(self):
        cases = [
            ({"main.ru": "模 取 外言 'missing.ru'."}, "missing.ru"),
            ({"main.ru": "模 取 外言 'a.ru'.", "a.ru": "模 取 外言 'main.ru'."}, "循环"),
            ({"main.ru": "值 取 1. 尽 取 外言 'a.ru'.", "a.ru": "值 取 2."}, "冲突"),
            ({"main.ru": "尽 取 外言 'a.ru'. 尽 取 外言 'b.ru'.", "a.ru": "值 取 1.", "b.ru": "值 取 2."}, "冲突"),
        ]
        for files, diagnostic in cases:
            with self.subTest(files=files), tempfile.TemporaryDirectory() as temp:
                main = self.write_tree(temp, files)
                for command in ("check", "run", "build"):
                    result = self.cli(command, main)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn(diagnostic, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_import_runtime_order_and_branch_collisions(self):
        cases = [
            ("若 1 则 值 取 2. 然 尽 取 外言 'lib.ru'.", "值 取 1.", "冲突"),
            ("值 取 1. 尽 取 外言 'lib.ru'.", "若 1 则 值 取 2. 然", "冲突"),
            ("形 子 如 基: 象 尽 取 外言 'lib.ru'.", "形 基: 象", "基"),
            ("对象 取 新 基. 尽 取 外言 'lib.ru'.", "形 基: 象", "基"),
        ]
        for source, library, diagnostic in cases:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as temp:
                main = self.write_tree(temp, {"main.ru": source, "lib.ru": library})
                checked = self.cli("check", main)
                self.assertEqual(checked.returncode, 0, checked.stderr)
                result = self.cli("run", main)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(diagnostic, result.stderr)
                self.assertEqual(result.stdout, "")
                if HAS_CC:
                    binary = Path(temp)/"import-order"
                    result = self.cli("build", main, "-o", str(binary))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    result = subprocess.run([binary], capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn(diagnostic, result.stderr)
                    self.assertEqual(result.stdout, "")

    def test_imported_function_and_class_cannot_be_overwritten(self):
        for name, definition in (("函", "算 函: 得 1. 法"), ("人", "形 人: 象")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                main = self.write_tree(temp, {"main.ru": f"尽 取 外言 'lib.ru'. {name} 取 2.",
                                              "lib.ru": definition})
                for command in ("check", "run", "build"):
                    result = self.cli(command, main)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("重名", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_invalid_entry_signatures(self):
        for definition in ("算 元初: 得 0. 法", "算 元初 参数 为 数: 得 0. 法",
                           "算 元初 参数 为 阵: 得 0. 法", "作 元初 参数 为 句 阵: 显 1. 为",
                           "算 元初 甲 为 句 阵 乙 为 数: 得 0. 法"):
            with self.subTest(definition=definition), tempfile.TemporaryDirectory() as temp:
                main = self.write_tree(temp, {"main.ru": definition})
                for command in ("check", "run", "build"):
                    result = self.cli(command, main)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("元初", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_invalid_entry_return_values(self):
        for value in ("-1", "256", "0.5", "'0'", "空"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp:
                main = self.write_tree(temp, {"main.ru": f"算 元初 参数 为 句 阵: 得 {value}. 法"})
                result = self.cli("run", main)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("元初", result.stderr)
                if HAS_CC:
                    binary = Path(temp)/"bad-entry"
                    result = self.cli("build", main, "-o", str(binary))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    result = subprocess.run([binary], capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("元初", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
