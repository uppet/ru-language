"""Array stable sorting and shallow one-result-per-element transformation."""
import math
from pathlib import Path
import tempfile
import unittest

from test_practical import CC, NODE, interpreted, execute_target
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter

CASES = [
    ('numbers', "原 取 [3,-1,2,2,0]. 新列 取 原 其 排序. 显 新列. 显 原. 显 新列 == 原.", '[-1, 0, 2, 2, 3]\n[3, -1, 2, 2, 0]\n假\n'),
    ('unicode', "显 ['😀','\\uE000','甲','a','','𐀀'] 其 排序.", '[, a, 甲, \\uE000, 𐀀, 😀]\n'),
    ('fresh', "空列 取 []. 单 取 [1]. 显 (空列 其 排序) == 空列. 显 (单 其 排序) == 单. 显 (空列 其 另成 (算 值: 得 值. 法)) == 空列.", '假\n假\n假\n'),
    ('named_descending', "显 [3,1,2] 其 排序 先于:(算 左 右: 得 左 > 右. 法). 显 [1,2,3] 其 另成 算法:(算 项: 得 项 * 项. 法).", '[3, 2, 1]\n[1, 4, 9]\n'),
    ('all_results', "显 [1,2] 其 另成 (算 项: 得 空. 法). 显 [1,2] 其 另成 (算 项: 得 [项]. 法). 显 [1,2] 其 另成 (算 项: 得 假. 法).", '[空, 空]\n[[1], [2]]\n[假, 假]\n'),
    ('map_snapshot', "原 取 [1,2,3]. 计 取 [0]. 新列 取 原 其 另成 (算 项: 计[0] := 计[0] + 1. 原 其 弹. 得 项. 法). 显 新列. 显 原. 显 计.", '[1, 2, 3]\n[]\n[3]\n'),
    ('sharing_and_cycle', "内 取 [1]. 原 取 [内,内]. 新列 取 原 其 另成 (算 项: 得 项. 法). 内[0] := 9. 显 新列. 显 新列[0] == 内. 显 新列 == 原. 环列 取 []. 环列 其 增 环列. 副 取 环列 其 另成 (算 项: 得 项. 法). 显 副[0] == 环列. 显 副 == 环列.", '[[9], [9]]\n真\n假\n真\n假\n'),
    ('override_mixed', "原 取 [空,假,[1],2,'句']. 新列 取 原 其 排序 (算 左 右: 得 假. 法). 显 新列. 显 新列[2] == 原[2].", '[空, 假, [1], 2, 句]\n真\n'),
    ('stable_custom', "形 盒: 键 为 数. 标签 为 句. 算 先于 另一: 得 其 键 < 另一 其 键. 法 算 同 另一: 卒 '不能调用同'. 法 象 原 取 [(新 盒 键:2 标签:'甲'),(新 盒 键:1 标签:'乙'),(新 盒 键:2 标签:'丙'),(新 盒 键:1 标签:'丁')]. 新列 取 原 其 排序. 显 新列 其 另成 (算 项: 得 项 其 标签. 法). 显 原 其 另成 (算 项: 得 项 其 标签. 法). 新列[0] 其 标签 := '改'. 显 原[1] 其 标签.", '[乙, 丁, 甲, 丙]\n[甲, 乙, 丙, 丁]\n改\n'),
    ('inherited', "形 基: 键 为 数. 算 先于 另一: 得 其 键 < 另一 其 键. 法 象 形 子 如 基: 象 排 取 [(新 子 键:2),(新 子 键:1)] 其 排序. 显 排 其 另成 (算 项: 得 项 其 键. 法).", '[1, 2]\n'),
    ('override_shape', "形 盒: 键 为 数. 算 先于 另一: 卒 '不用默认'. 法 象 排 取 [(新 盒 键:1),(新 盒 键:2)] 其 排序 (算 左 右: 得 左 其 键 > 右 其 键. 法). 显 排 其 另成 (算 项: 得 项 其 键. 法).", '[2, 1]\n'),
    ('panic', "原 取 [2,1]. 试 原 其 排序 (算 左 右: 卒 '排序停'. 法). 救 因 显 因. 终. 显 原. 试 原 其 另成 (算 项: 卒 '另成停'. 法). 救 因 显 因. 终. 显 原.", '排序停\n[2, 1]\n另成停\n[2, 1]\n'),
    ('contest_unchanged', "竞 取 外言 '如:竞'. 显 竞 其 排序 [3,1,2] (算 左 右: 得 左 - 右. 法).", '[1, 2, 3]\n'),
]
# Use a literal private-use character, not a language escape syntax.
CASES[1] = (CASES[1][0], CASES[1][1].replace('\\uE000', '\ue000'), CASES[1][2].replace('\\uE000', '\ue000'))
CASES += [
    ('enumerate_snapshot', "原 取 [10,20,30]. 得列 取 []. 显 原 其 逐位 回调:(作 位 项: 得列 其 增 [位,项]. 原 其 弹. 完. 得列 其 增 '不执行'. 为). 显 得列. 显 原.", '空\n[[0, 10], [1, 20], [2, 30]]\n[]\n'),
    ('enumerate_ignored', "原 取 [1,2,3]. 得列 取 []. 显 原 其 逐位 (算 位 项: 得列 其 增 项. 得 假. 法). 显 得列. 显 [] 其 逐位 (作 位 项: 完. 为).", '空\n[1, 2, 3]\n空\n'),
    ('enumerate_sharing', "内 取 [0]. 原 取 [内,内]. 原 其 逐位 (作 位 项: 项[0] := 项[0] + 1. 为). 显 内. 显 原.", '[2]\n[[2], [2]]\n'),
    ('enumerate_panic', "试 [1] 其 逐位 (作 位 项: 卒 '逐位停'. 为). 救 因 显 因. 终.", '逐位停\n'),
    ('map_enumerate', "表 取 {'甲':1,'乙':2}. 和 取 [0]. 显 表 其 逐目 回调:(算 目 相: 和[0] := 和[0] + 相. 表 其 除 目. 得 假. 法). 显 和. 显 表 其 量.", '空\n[3]\n0\n'),
    ('ordinary_names', "排序 取 1. 先于 取 2. 另成 取 3. 逐位 取 4. 逐目 取 5. 显 排序 + 先于 + 另成 + 逐位 + 逐目.", '15\n'),
    ('map_empty', "显 {} 其 逐目 (作 目 相: 完. 为).", '空\n'),
]
ERRORS = [
    "显 [] 其 逐位.", "显 [] 其 逐位 空.",
    "显 [] 其 逐位 (算 项: 得 空. 法).", "显 [] 其 逐位 (作: 完. 为).",
    "显 {} 其 逐目 空.", "显 {} 其 逐目 (算 项: 得 项. 法).",
    "显 {} 其 列 (作 目 相: 完. 为).",
    "显 [空] 其 排序.", "显 [真] 其 排序.", "显 [[1]] 其 排序.",
    "显 [1,'a'] 其 排序.", "显 [1,真] 其 排序.",
    "显 [] 其 排序 空.", "显 [] 其 排序 (作 左 右: 完. 为).",
    "显 [] 其 排序 (算 项: 得 真. 法).", "显 [] 其 排序 (算 甲 乙 丙: 得 真. 法).",
    "显 [2,1] 其 排序 (算 左 右: 得 1. 法).",
    "显 [2,1] 其 排序 (算 左 右: 得 空. 法).",
    "显 [] 其 另成.", "显 [] 其 另成 空.", "显 [] 其 另成 (作 项: 完. 为).",
    "显 [] 其 另成 (算: 得 空. 法).", "显 [] 其 另成 (算 甲 乙: 得 空. 法).",
    "显 [] 其 排序 比较:(算 左 右: 得 真. 法).",
    "显 [] 其 另成 回调:(算 项: 得 项. 法).",
    "形 盒: 象 显 [(新 盒)] 其 排序.",
    "形 盒: 作 先于 另一: 完. 为 象 显 [(新 盒)] 其 排序.",
    "形 盒: 算 先于: 得 真. 法 象 显 [(新 盒)] 其 排序.",
    "形 盒: 算 先于 另一: 得 0. 法 象 显 [(新 盒),(新 盒)] 其 排序.",
    "形 甲: 算 先于 另一: 得 真. 法 象 形 乙: 算 先于 另一: 得 真. 法 象 显 [(新 甲),(新 乙)] 其 排序.",
    "显 'abc' 其 另成 (算 项: 得 项. 法).", "显 'abc' 其 排序.",
]


class ArrayInterfaceTests(unittest.TestCase):
    def test_interpreter_cases(self):
        for name, source, expected in CASES:
            with self.subTest(name=name):
                self.assertEqual(interpreted(source), expected)

    def test_interpreter_errors(self):
        for source in ERRORS:
            with self.subTest(source=source), self.assertRaises(RuError):
                interpreted(source)

    def test_map_old_name_migration(self):
        with self.assertRaisesRegex(RuError, '典的「列」已改名为「逐目」'):
            interpreted("表 取 {}. 表 其 列 (作 目 相: 完. 为).")

    def test_nonfinite_defaults(self):
        owner = Interpreter()
        node = parse('显 1.')[0]
        for value in (math.inf, -math.inf, math.nan):
            with self.subTest(value=value), self.assertRaises(RuError):
                owner.array_transform(node, [value], '排序', [])

    def _cases(self, target):
        with tempfile.TemporaryDirectory() as tmp:
            for full in (False, True):
                for name, source, expected in CASES:
                    with self.subTest(target=target, name=name, full=full):
                        run = execute_target(source, target, Path(tmp), full)
                        self.assertEqual(run.returncode, 0, run.stderr)
                        self.assertEqual(run.stdout, expected)
                        if target == 'c':
                            self.assertIn('live=0', run.stderr)

    def _errors(self, target):
        with tempfile.TemporaryDirectory() as tmp:
            for source in ERRORS:
                with self.subTest(target=target, source=source):
                    try:
                        run = execute_target(source, target, Path(tmp))
                    except RuError:
                        continue
                    self.assertNotEqual(run.returncode, 0)
                    self.assertIn('错误', run.stderr)

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_native_cases(self):
        self._cases('c')

    @unittest.skipUnless(NODE, 'Node unavailable')
    def test_javascript_cases(self):
        self._cases('js')

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_native_errors(self):
        self._errors('c')

    @unittest.skipUnless(NODE, 'Node unavailable')
    def test_javascript_errors(self):
        self._errors('js')
