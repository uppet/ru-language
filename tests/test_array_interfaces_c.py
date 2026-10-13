"""Native array sort/transform ownership, validation and pruning regressions."""
import tempfile
import unittest

from test_runtime_pruning import CC, FIXTURE, build, generate, run


@unittest.skipUnless(CC, 'C compiler unavailable')
class ArrayInterfacesNativeTests(unittest.TestCase):
    def check_program(self, source, expected, *, error=None):
        with tempfile.TemporaryDirectory() as tmp:
            for full in (False, True):
                with self.subTest(full=full):
                    result = run(build(generate(source, full=full), tmp, 'array'))
                    self.assertEqual(result.stdout, expected)
                    if error is None:
                        self.assertEqual(result.returncode, 0, result.stderr)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(error, result.stderr)
                    self.assertIn('RU_GC live=0 ', result.stderr)

    def test_new_shallow_arrays_and_unicode_scalar_order(self):
        self.check_program("""
原 取 [3,1,2]. 显 原 其 排序. 显 原.
空阵 取 []. 显 (空阵 其 排序) == 空阵.
单 取 ['甲']. 显 (单 其 排序) == 单.
显 ['😀','\ue000','a','甲',''] 其 排序.
内 取 [1]. 原阵 取 [内]. 副 取 原阵 其 另成 (算 元: 得 元. 法).
显 副 == 原阵. 显 副[0] == 内.
内 其 增 2. 显 副.
显 [1,2] 其 另成 算法:(算 元: 得 空. 法).
显 [1,2] 其 另成 (算 元: 得 [元]. 法).
""", '[1, 2, 3]\n[3, 1, 2]\n假\n假\n[, a, 甲, \ue000, 😀]\n假\n真\n[[1, 2]]\n[空, 空]\n[[1], [2]]\n')

    def test_sort_snapshot_and_stable_protocol_without_equality(self):
        self.check_program("""
形 项:
  号 为 数. 值 为 数.
  算 同 另一: 卒 '不能用同'. 法
  算 先于 另一:
    循 原 其 量 次 原 其 弹. 环
    得 其 值 < 另一 其 值.
  法
象
原 取 [(新 项 号:1 值:2),(新 项 号:2 值:1),(新 项 号:3 值:2),(新 项 号:4 值:1)].
排 取 原 其 排序. 显 原. 显 排 其 另成 (算 元: 得 元 其 号. 法).
""", '[]\n[2, 4, 1, 3]\n')

    def test_explicit_comparator_override_and_source_mutation(self):
        self.check_program("""
原 取 [[2],[1],[2]].
算 早 左 右: 循 原 其 量 次 原 其 弹. 环 得 左[0] < 右[0]. 法
排 取 原 其 排序 先于:(算 早). 显 原. 显 排.
显 [空,真,1] 其 排序 (算 左 右: 得 假. 法).
""", '[]\n[[1], [2], [2]]\n[空, 真, 1]\n')

    def test_transform_snapshots_before_callback(self):
        self.check_program("""
原 取 [1,2,3].
算 改 元:
  循 原 其 量 次 原 其 弹. 环
  原 其 增 9.
  得 元 * 2.
法
显 原 其 另成 (算 改). 显 原.
""", '[2, 4, 6]\n[9]\n')

    def test_panic_propagation_stops_callbacks(self):
        self.check_program("""
记 取 []. 原 取 [3,2,1].
试 原 其 排序 (算 左 右: 记 其 增 1. 卒 '排序停'. 法).
救 因 显 因. 终.
显 记. 显 原.
试 原 其 另成 (算 元: 记 其 增 元. 卒 '另成停'. 法).
救 因 显 因. 终.
显 记. 显 原.
""", '排序停\n[1]\n[3, 2, 1]\n另成停\n[1, 3]\n[3, 2, 1]\n')

    def test_exact_fact_results_and_callback_validation(self):
        cases = [
            ("[] 其 排序 先于:空.", '接收 2 个参数的算'),
            ("[] 其 排序 (算 一: 得 真. 法).", '接收 2 个参数的算'),
            ("[] 其 排序 (作 左 右: 完. 为).", '接收 2 个参数的算'),
            ("[] 其 另成 (作 元: 完. 为).", '接收 1 个参数的算'),
            ("[] 其 另成 (算 左 右: 得 空. 法).", '接收 1 个参数的算'),
            ("[2,1] 其 排序 (算 左 右: 得 1. 法).", '须返回事实'),
            ("[真] 其 排序.", '不支持事实'),
            ("[空] 其 排序.", '不支持空'),
            ("[[]] 其 排序.", '不支持阵'),
            ("[1,'甲'] 其 排序.", '不支持混合类型'),
            ("形 项: 算 先于 另一: 得 1. 法 象 [(新 项),(新 项)] 其 排序.", '须返回事实'),
            ("形 项: 作 先于 另一: 完. 为 象 [(新 项)] 其 排序.", '接收一个参数的算'),
            ("形 项: 象 [(新 项)] 其 排序.", '接收一个参数的算'),
            ("形 甲: 算 先于 另一: 得 假. 法 象 形 乙: 算 先于 另一: 得 假. 法 象 [(新 甲),(新 乙)] 其 排序.", '同一种形'),
        ]
        for source, error in cases:
            with self.subTest(source=source):
                self.check_program(source, '', error=error)

    def test_each_snapshot_returns_and_migration(self):
        self.check_program("""
原 取 [7,8,9]. 记 取 [].
显 原 其 逐位 回调:(算 位 元:
  记 其 增 [位,元].
  循 原 其 量 次 原 其 弹. 环
  得 '忽略'.
法).
显 记. 显 原.
显 [] 其 逐位 (作 位 元: 卒 '不运行'. 为).
表 取 {'甲':1}. 显 表 其 逐目 回调:(算 目 相: 显 目. 显 相. 表 其 除 目. 得 [相]. 法).
显 表 其 量.
""", '空\n[[0, 7], [1, 8], [2, 9]]\n[]\n空\n甲\n1\n空\n0\n')
        self.check_program("表 取 {}. 表 其 列 (作 目 相: 完. 为).", '',
                           error='典的「列」已改名为「逐目」；请改用「其 逐目」')
        self.check_program("[] 其 逐位 (算 元: 得 元. 法).", '',
                           error='阵的逐位回调须为接受两个参数的算或作')

    def test_unrelated_runtime_keeps_existing_size(self):
        generated = generate(FIXTURE.read_text(encoding='utf-8'), source_name='/p1010.ru')
        for function in ('v_array_sort', 'ru_array_before', 'v_array_transform', 'v_array_each', 'ru_array_algorithm'):
            self.assertNotIn(function, generated)
        self.assertLess(len(generated.encode('utf-8')), 50_000)


if __name__ == '__main__':
    unittest.main()
