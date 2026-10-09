"""Facts, hash maps, and callback safety across all three backends."""
import io
import os
from unittest.mock import patch
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest

from test_javascript import NODE, compiled, node_run
from rulang.cli import build
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter
from rulang.modules import load_module_graph


class MapsFactsContract:
    def run_source(self, source):
        with tempfile.TemporaryDirectory() as folder:
            path, _ = compiled(source, folder)
            return node_run(path)

    def output(self, source, expected):
        status, out, error = self.run_source(source)
        self.assertEqual((status, out, error), (0, expected, ''))

    def error(self, source, expected):
        status, _, error = self.run_source(source)
        self.assertNotEqual(status, 0)
        self.assertRegex(error, expected)

    def test_truth_and_type_separation(self):
        self.output("显 真. 显 假. 显 真 == 1. 显 假 == 0. 显 0 为 事实. 显 -0 为 事实. 显 '' 为 事实. 显 [] 为 事实. 显 典: 成 为 事实. 显 空 为 事实. 显 非 0. 显 0 且 ''.",
                    '真\n假\n假\n假\n真\n真\n真\n真\n真\n假\n假\n真\n')
        self.error('显 真 + 1.', '算术|数字')
        self.error('显 真 为 数.', '转')

    def test_map_primitive_keys_alias_and_missing(self):
        self.output("物 取 典: 真 对 'fact'. 1 对 'number'. 0 对 1. -0 对 2. 成. 别 取 物. 显 别 其 量. 显 别 其 查 真. 显 别 其 查 1. 显 别 其 查 0. 显 别 其 查 '缺'. 显 别 其 除 真. 显 物 其 除 真. 显 别 == 物.",
                    '3\nfact\nnumber\n2\n空\n真\n假\n真\n')

    def test_order_and_duplicate_value_evaluation(self):
        self.output("算 报 值: 显 值. 得 值. 法 物 取 典: (报 'a') 对 (报 1). (报 'a') 对 (报 2). 成. 显 物 其 查 'a'.", 'a\n1\na\n2\n2\n')

    def test_same_shape_custom_equality_collision(self):
        self.output("形 键形: 值 为 数. 算 同 另一: 得 其 值 == 另一 其 值. 法 算 印: 得 0. 法 象 甲 取 新 键形 值:1. 乙 取 新 键形 值:1. 丙 取 新 键形 值:2. 显 甲 == 乙. 显 甲 != 乙. 物 取 典: 甲 对 9. 丙 对 7. 成. 显 物 其 查 乙. 显 物 其 查 丙. 物 其 增 乙 8. 显 物 其 查 甲.", '真\n假\n9\n7\n8\n')

    def test_snapshot_captures_values_and_finish_only_callback(self):
        self.output("算 试列: 总 取 0. 物 取 典: 'a' 对 1. 'b' 对 2. 成. 物 其 列 回调:(作 键 值: 总 取 总+值. 物 其 除 'b'. 物 其 增 'c' 3. 完. 为). 得 总. 法 显 试列.", '3\n')

    def test_snapshot_function_closure_and_panic(self):
        self.output("算 求: 总 取 0. 物 取 典: 'a' 对 1. 'b' 对 2. 成. 物 其 列 算 键 值: 总 取 总+值. 得 99. 法. 得 总. 法 显 求. 试 物 取 典: 1 对 2. 成. 物 其 列 作 键 值: 卒 '停止'. 为. 救 原因 显 原因. 终.", '3\n停止\n')

    def test_cycle_display(self):
        self.output("物 取 典: 成. 物 其 增 'self' 物. 显 物.", '{self: <循环>}\n')

    def test_unsupported_keys(self):
        for key in ('空', '[]', '典: 成', '1 对 2', '算: 得 1. 法'):
            with self.subTest(key=key):
                self.error('物 取 典: ('+key+') 对 1. 成.', '典.*键')

    def test_custom_key_protocol_rejections(self):
        for methods, expected in (
            ('', '同'),
            ('算 同 另一: 得 真. 法', '印'),
            ('作 同 另一: 完. 为 算 印: 得 0. 法', '同'),
            ('算 同 另一: 得 真. 法 算 印: 得 真. 法', '安全整数'),
            ('算 同 另一: 得 真. 法 算 印: 得 0.5. 法', '安全整数'),
            ('算 同 另一: 得 真. 法 算 印: 得 9007199254740992. 法', '安全整数'),
        ):
            with self.subTest(methods=methods):
                self.error('形 键形: '+methods+' 象 物 取 典: (新 键形) 对 1. 成.', expected)
        self.error('形 键形: 算 同 另一: 得 1. 法 象 甲 取 新 键形. 显 甲 == 甲.', '事实')

    def test_hash_callback_mutation_guard(self):
        self.error("物 取 典: 成. 形 键形: 算 同 另一: 得 真. 法 算 印: 物 其 增 'x' 1. 得 0. 法 象 物 其 增 (新 键形) 8.", '修改')

    def test_equality_callback_mutation_guard(self):
        self.error("物 取 典: 成. 形 键形: 算 同 另一: 物 其 增 'x' 1. 得 真. 法 算 印: 得 0. 法 象 物 其 增 (新 键形) 8. 显 物 其 查 (新 键形).", '修改')

    def test_numeric_hash_stress_and_deletions(self):
        self.output("物 取 典: 成. 位 取 0. 循 3000 次 物 其 增 位 位*2. 位 取 位+1. 环 位 取 0. 总 取 0. 循 3000 次 总 取 总+(物 其 查 位). 若 位%2 == 0 则 物 其 除 位. 然 位 取 位+1. 环 显 总. 显 物 其 量. 显 物 其 查 2999. 显 物 其 查 0.", '8997000\n1500\n5998\n空\n')

    def test_custom_collision_stress(self):
        self.output("形 键形: 值 为 数. 算 同 另一 为 键形: 得 其 值 == 另一 其 值. 法 算 印: 得 7. 法 象 物 取 典: 成. 位 取 0. 循 80 次 物 其 增 (新 键形 值:位) 位. 位 取 位+1. 环 位 取 0. 总 取 0. 循 80 次 总 取 总+(物 其 查 (新 键形 值:位)). 物 其 除 (新 键形 值:位). 位 取 位+1. 环 显 总. 显 物 其 量.", '3160\n0\n')

    def test_same_concrete_shape_and_inheritance(self):
        self.output("形 基: 算 同 另一: 得 真. 法 算 印: 得 0. 法 象 形 子 如 基: 象 甲 取 新 基. 乙 取 新 子. 显 甲 == 乙. 显 乙 == 甲. 物 取 典: 甲 对 1. 乙 对 2. 成. 显 物 其 量. 显 物 其 查 (新 子).", '假\n假\n2\n2\n')

    def test_identity_without_custom_equality(self):
        self.output('形 盒: 象 甲 取 新 盒. 显 甲 == 甲. 显 甲 == (新 盒). 显 (甲 对 空) == (甲 对 空).', '真\n假\n真\n')

    def test_hash_boundaries(self):
        self.output('形 键形: 值 为 数. 算 同 另一: 得 其 值 == 另一 其 值. 法 算 印: 得 其 值. 法 象 物 取 典: (新 键形 值:9007199254740991) 对 1. (新 键形 值:(-9007199254740991)) 对 2. 成. 显 物 其 查 (新 键形 值:9007199254740991). 显 物 其 查 (新 键形 值:(-9007199254740991)).', '1\n2\n')

    def test_fields_typed_arrays_and_conversions(self):
        self.output("形 盒: 表 为 典. 标 为 事实. 象 物 取 典: 'a' 对 []. 成. 盒值 取 新 盒 表:物 标:真. (盒值 其 表 其 查 'a') 其 增 7. 显 物 其 查 'a'. 算 回 表 为 典 列 为 事实 阵: 得 表. 法 显 (回 物, [真,假]) == 物. 显 (物 为 阵)[0] == 物. 显 真 为 句.", '[7]\n真\n真\n真\n')

    def test_missing_and_null_and_false_values(self):
        self.output("物 取 典: '空' 对 空. '假' 对 假. 成. 显 物 其 查 '空'. 显 物 其 查 '缺'. 显 物 其 查 '假'. 显 物 其 除 '空'. 显 物 其 除 '缺'.", '空\n空\n假\n真\n假\n')

    def test_snapshot_is_shallow_and_recursive_enumeration(self):
        self.output("算 求: 总 取 0. 列值 取 [1]. 物 取 典: 1 对 列值. 2 对 列值. 成. 物 其 列 作 键 值: 值[0] 取 值[0]+1. 总 取 总+值[0]. 物 其 列 作 内键 内值: 总 取 总+1. 为. 为. 得 总. 法 显 求.", '9\n')

    def test_short_circuit_and_predicates_are_facts(self):
        self.output("显 假 且 (1/0). 显 真 或 (1/0). 显 空 且 (1/0). 显 [] 或 (1/0). 算 回 值 为 事实: 得 值. 法 显 回 (1 < 2). 显 回 ('abc' 其 含 'b'). 显 回 (1 != 2).", '假\n真\n假\n真\n真\n真\n真\n')

    def test_fact_rejected_in_numeric_roles(self):
        for source in ('显 [1][假].', '循 真 次 显 1. 环', '显 真 < 1.', '显 -真.', '算 回 值 为 数: 得 值. 法 回 真.'):
            with self.subTest(source=source):
                status, _, _ = self.run_source(source)
                self.assertNotEqual(status, 0)

    def test_key_callbacks_propagate_panic(self):
        self.output("形 键形: 算 同 另一: 卒 '同比较'. 法 算 印: 得 0. 法 象 物 取 典: (新 键形) 对 1. 成. 试 物 其 查 (新 键形). 救 原因 显 原因. 终. 形 坏键: 算 同 另一: 得 真. 法 算 印: 卒 '印计算'. 法 象 试 物 其 增 (新 坏键) 2. 救 原因 显 原因. 终.", '同比较\n印计算\n')

    def test_invalid_key_evaluates_value_before_rejection(self):
        status, out, error = self.run_source("算 值: 显 '值已求'. 得 1. 法 物 取 典: 空 对 值. 成.")
        self.assertNotEqual(status, 0)
        self.assertEqual(out, '值已求\n')

    def test_map_argument_and_callback_validation(self):
        for source in ("物 取 典: 成. 物 其 查.", "物 取 典: 成. 物 其 增 错:1 值:2.", "物 取 典: 成. 物 其 列 1.", "物 取 典: 成. 物 其 列 算 键: 得 键. 法.", "物 取 典: 成. 物 其 查 1 2."):
            with self.subTest(source=source):
                status, _, _ = self.run_source(source)
                self.assertNotEqual(status, 0)

    def test_module_maps_and_closure_runtime_retention(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder/'library.ru').write_text("算 制: 表 取 典: 'a' 对 真. 成. 得 算: 得 表. 法. 法", encoding='utf-8')
            source = "库 取 外言 './library.ru'. 回调 取 库 其 制. 表 取 回调(). 显 表 其 查 'a'. 显 回调() == 表."
            main = folder/'main.ru'
            main.write_text(source, encoding='utf-8')
            graph = load_module_graph(str(main), parse(source))
            if self.backend == 'python':
                output = io.StringIO()
                Interpreter(io.StringIO(), output).execute(graph[graph.root], source_path=graph.root, modules=graph)
                actual = (0, output.getvalue(), '')
            elif self.backend == 'c':
                binary, _ = build(graph[graph.root], graph.root, folder/'case', modules=graph)
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
                actual = (result.returncode, result.stdout, result.stderr)
            else:
                path, _ = compiled(source, folder, source_path=main, graph=graph)
                actual = node_run(path)
            self.assertEqual(actual, (0, '真\n真\n', ''))

    def test_example(self):
        source = (Path(__file__).resolve().parents[1]/'examples/maps_facts.ru').read_text(encoding='utf-8')
        self.output(source, '真\n假\n真\n假\n92\n空\n3\n275\n真\n假\n七号\n')

    def test_pair_custom_equality_callback_order(self):
        self.output("形 键形: 值 为 数. 算 同 另一: 显 其 值. 得 真. 法 象 甲 取 (新 键形 值:1) 对 (新 键形 值:2). 乙 取 (新 键形 值:1) 对 (新 键形 值:2). 显 甲 == 乙.", '1\n2\n真\n')

    def test_literal_key_value_hash_equality_side_effect_order(self):
        self.output("形 键形: 算 同 另一: 显 '同'. 得 真. 法 算 印: 显 '印'. 得 0. 法 象 算 键: 显 '键'. 得 新 键形. 法 算 值: 显 '值'. 得 1. 法 物 取 典: 键 对 值. 键 对 值. 成.", '键\n值\n印\n键\n值\n印\n同\n')

    def test_recursive_custom_comparison_is_bounded(self):
        status, _, error = self.run_source('形 键形: 算 同 另一: 得 其 == 另一. 法 象 显 (新 键形) == (新 键形).')
        self.assertNotEqual(status, 0)
        self.assertRegex(error, '128|层数|递归')
        self.assertNotRegex(error, 'Segmentation|RangeError|RecursionError')

    def test_gc_map_array_closure_cycles_survive_panic(self):
        source = """算 制:
            表 取 典: 成.
            列值 取 [表].
            回调 取 算: 得 表 其 查 '值'. 法.
            表 其 增 '列' 列值.
            表 其 增 '回' 回调.
            表 其 增 '值' 7.
            试 卒 '保留'. 救 原因 得 表. 终.
        法
        表 取 制.
        循 80 次 废 取 制. 环
        显 (表 其 查 '回')().
        显 (表 其 查 '列')[0] == 表.
        算 遍历:
            总 取 0.
            物 取 典: 1 对 [10]. 2 对 [20]. 成.
            物 其 列 作 键 值:
                物 其 除 1. 物 其 除 2.
                循 10 次 废 取 制. 环
                总 取 总+值[0].
            为.
            得 总.
        法
        显 遍历.
        试 表 其 列 作 键 值: 废 取 制. 卒 '跳出'. 为. 救 原因 显 原因. 终.
        显 (表 其 查 '回')()."""
        with patch.dict(os.environ, {'RU_GC_THRESHOLD':'1'}):
            self.output(source, '7\n真\n30\n跳出\n7\n')

    def test_gc_key_callback_growth_mutation_guard(self):
        source = """物 取 典: 成.
        形 键形:
            算 同 另一:
                位 取 0.
                循 100 次 物 其 增 位, [位]. 位 取 位+1. 环
                得 真.
            法
            算 印: 得 0. 法
        象
        物 其 增 (新 键形) 1.
        显 物 其 查 (新 键形)."""
        with patch.dict(os.environ, {'RU_GC_THRESHOLD':'1'}):
            self.error(source, '修改')

    def test_key_callback_can_mutate_other_map(self):
        self.output("别 取 典: 成. 形 键形: 算 同 另一: 别 其 增 '同' 真. 得 真. 法 算 印: 别 其 增 '印' 真. 得 0. 法 象 物 取 典: (新 键形) 对 7. 成. 显 物 其 查 (新 键形). 显 别 其 量.", '7\n2\n')

    def test_map_rejects_sequence_operations(self):
        for operation in ('显 物[0].', '显 物[:].', '显 物[0:1].', '物[0] 取 7.', '显 物 其 位 0.', '显 物 其 段 0 1.', '物 其 位 0 取 7.'):
            for literal in ('典: 成', '典: 1 对 2. 成'):
                with self.subTest(operation=operation, literal=literal):
                    status, _, error = self.run_source('物 取 '+literal+'. '+operation)
                    self.assertEqual(status, 1, error)

    def test_pair_identity_shortcut_and_instance_self_dispatch(self):
        self.output("形 键形: 算 同 另一: 显 '调用'. 得 假. 法 象 甲 取 新 键形. 对值 取 甲 对 空. 显 对值 == 对值. 显 甲 == 甲.", '真\n调用\n假\n')


class InterpreterMapsFactsTests(MapsFactsContract, unittest.TestCase):
    backend = 'python'
    def run_source(self, source):
        out = io.StringIO()
        try:
            Interpreter(io.StringIO(), out).execute(parse(source))
            return 0, out.getvalue(), ''
        except RuError as error:
            return 1, out.getvalue(), str(error)


@unittest.skipUnless(NODE, 'Node.js required')
class JavaScriptMapsFactsTests(MapsFactsContract, unittest.TestCase):
    backend = 'js'


@unittest.skipUnless(any(shutil.which(c) for c in ('cc', 'gcc', 'clang')), 'C compiler required')
class NativeMapsFactsTests(MapsFactsContract, unittest.TestCase):
    backend = 'c'
    def run_source(self, source):
        with tempfile.TemporaryDirectory() as folder:
            try:
                binary, _ = build(parse(source), 'maps-facts.ru', Path(folder)/'case')
            except RuError as error:
                return 1, '', str(error)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
            return result.returncode, result.stdout, result.stderr


if __name__ == '__main__':
    unittest.main()
