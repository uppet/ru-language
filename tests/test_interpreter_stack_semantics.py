"""Observable semantic fences for the explicit interpreter evaluation stack.

These shallow programs intentionally pass the pre-stack interpreter too. Deep
capacity tests live separately: no assertions here depend on continuation internals.
"""
import io
from pathlib import Path
import tempfile
import unittest

from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter, Panic


class InterpreterStackSemanticsTests(unittest.TestCase):
    def make(self):
        output = io.StringIO()
        return Interpreter(stdout=output), output

    def idle(self, vm):
        self.assertEqual(vm.structure_depth, 0)
        self.assertEqual(vm.depth, 0)
        self.assertEqual(vm.call_state, [0])

    def output(self, source, expected):
        vm, stream = self.make()
        vm.execute(parse(source))
        self.assertEqual(stream.getvalue(), expected)
        self.idle(vm)
        return vm

    def test_left_to_right_binary_arguments_array_and_named_arguments(self):
        self.output("""
记 取 [].
算 标 值: 记 其 增 值. 得 值. 法
算 合 左 右: 得 左*10+右. 法
显 (标 1)+(标 2).
显 合 (标 3) (标 4).
显 [(标 5),(标 6)].
显 合 右:(标 7) 左:(标 8).
显 记.
""", '3\n34\n[5, 6]\n87\n[1, 2, 3, 4, 5, 6, 7, 8]\n')

    def test_map_key_value_and_slice_bounds_evaluate_left_to_right(self):
        self.output("""
痕 取 []. 算 标 值: 痕 其 增 值. 得 值. 法
表 取 {(标 '甲'):(标 1),(标 '乙'):(标 2)}.
算 对象: 痕 其 增 '接收'. 得 [10,20,30]. 法
显 (对象)[(标 1):(标 3)]. 显 痕.
""", '[20, 30]\n[甲, 1, 乙, 2, 接收, 1, 3]\n')

    def test_constructor_named_fields_use_source_order(self):
        self.output("""
形 盒: 左 为 数. 右 为 数. 象
痕 取 []. 算 标 值: 痕 其 增 值. 得 值. 法
物 取 新 盒 右:(标 2) 左:(标 1).
显 物 其 左. 显 物 其 右. 显 痕.
""", '1\n2\n[2, 1]\n')

    def test_constructor_type_failure_stops_remaining_field_expressions(self):
        vm, stream = self.make()
        vm.execute(parse("形 盒: 左 为 数. 右 为 数. 象 痕 取 []. 算 标 值: 痕 其 增 值. 得 值. 法"))
        with self.assertRaisesRegex(RuError, '须为数'):
            vm.execute(parse("新 盒 左:(标 '错') 右:(标 2)."))
        self.idle(vm)
        vm.execute(parse('显 痕.'))
        self.assertEqual(stream.getvalue(), '[错]\n')
        self.idle(vm)

    def test_short_circuit_does_not_evaluate_skipped_operand(self):
        self.output("""
记 取 []. 算 标 值: 记 其 增 值. 得 真. 法
显 假 且 (标 1). 显 真 或 (标 2).
显 真 且 (标 3). 显 假 或 (标 4). 显 记.
""", '假\n真\n真\n真\n[3, 4]\n')

    def test_callee_captured_before_argument_rebinds_closure(self):
        self.output("""
算 测:
    回 取 算 值: 得 '旧'+值. 法.
    算 换: 回 取 算 值: 得 '新'+值. 法. 得 '!'. 法
    显 回 (换).
    显 回 '?'.
    得 真.
法
测.
""", '旧!\n新?\n')

    def test_indexed_callee_captured_before_argument_replaces_slot(self):
        self.output("""
组 取 [算 值: 得 值+1. 法].
算 换: 组[0] 取 算 值: 得 值+100. 法. 得 7. 法
显 组[0] (换). 显 组[0] 7.
""", '8\n107\n')

    def test_invalid_assignment_checks_index_before_rhs_side_effect(self):
        for target in ('列[5]', '列 其 位 5', '列[-1]'):
            with self.subTest(target=target):
                vm, stream = self.make()
                vm.execute(parse("列 取 [1]. 痕 取 []. 算 右: 痕 其 增 9. 得 2. 法"))
                with self.assertRaises(RuError):
                    vm.execute(parse(target+' 取 右.'))
                self.idle(vm)
                vm.execute(parse('显 痕. 显 列.'))
                self.assertEqual(stream.getvalue(), '[]\n[1]\n')
                self.idle(vm)

    def test_assignment_receiver_index_then_rhs_exactly_once(self):
        self.output("""
痕 取 []. 列 取 [0].
算 对象: 痕 其 增 '接收'. 得 列. 法
算 位置: 痕 其 增 '位'. 得 0. 法
算 右: 痕 其 增 '右'. 得 8. 法
(对象)[位置] 取 右. 显 痕. 显 列.
""", '[接收, 位, 右]\n[8]\n')

    def test_return_finish_break_cross_scopes_and_try_without_rescue(self):
        self.output("""
算 回: 试 { 循 2 次 { 得 8. } 环 } 救 原因 显 '错救'. 终. 得 0. 法
作 止: 试 { 循 2 次 { 完. } 环 } 救 原因 显 '错救'. 终. 显 99. 为
显 回. 止.
循 2 次 试 { 破. } 救 原因 显 '错救'. 终. 显 99. 环
显 '完成'.
""", '8\n完成\n')

    def test_rescue_repanic_reaches_outer_handler_not_same_handler(self):
        self.output("""
痕 取 [].
试
    试 { 卒 '初'. } 救 原因 痕 其 增 原因. 卒 原因+'再'. 终.
救 原因 痕 其 增 原因. 终.
显 痕.
作 止: 试 卒 '停'. 救 原因 { 完. } 显 99. 终. 为
止. 显 '恢复'.
""", '[初, 初再]\n恢复\n')

    def test_fatal_runtime_error_is_not_panic_and_counters_recover(self):
        vm, stream = self.make()
        vm.execute(parse('算 坏: 得 [1][2]. 法'))
        with self.assertRaises(RuError) as caught:
            vm.execute(parse("试 坏. 救 原因 显 '不可捕获'. 终."))
        self.assertNotIsInstance(caught.exception, Panic)
        self.idle(vm)
        vm.execute(parse("显 '可继续'."))
        self.assertEqual(stream.getvalue(), '可继续\n')
        self.idle(vm)

    def test_unhandled_panic_unwinds_and_same_interpreter_reusable(self):
        vm, stream = self.make()
        with self.assertRaises(Panic) as caught:
            vm.execute(parse("算 坏: { 卒 '根因'. } 法 坏."))
        self.assertEqual(caught.exception.reason, '根因')
        self.idle(vm)
        vm.execute(parse('算 好: 得 42. 法 显 好.'))
        self.assertEqual(stream.getvalue(), '42\n')
        self.idle(vm)

    def test_imported_closure_owner_and_source_error_restoration(self):
        with tempfile.TemporaryDirectory(prefix='ru-stack-owner-') as directory:
            root = Path(directory)
            module = root/'library.ru'
            module.write_text("算 制 起: 得 算 步: 起 取 起+步. 得 起. 法. 法\n算 坏: 得 [1][2]. 法\n", encoding='utf-8')
            entry = root/'main.ru'
            vm, stream = self.make()
            vm.execute(parse("库 取 外言 'library.ru'. 回 取 库 其 制 10. 显 回 2. 显 回 3."), source_path=entry)
            self.assertEqual(stream.getvalue(), '12\n15\n')
            with self.assertRaises(RuError) as caught:
                vm.execute(parse('库 其 坏.'))
            self.assertEqual(caught.exception.source_name, str(module.resolve()))
            self.assertEqual(caught.exception.line, 2)
            self.idle(vm)
            for imported in vm.module_cache.values():
                self.idle(imported.interpreter)
            vm.execute(parse('显 回 4.'))
            self.assertEqual(stream.getvalue(), '12\n15\n19\n')
            self.idle(vm)

    def test_map_hash_and_equality_mutation_guards_survive_callback_return(self):
        cases = [
            "物 取 {}. 形 键形: 算 同 另一: 得 真. 法 算 印: 物 其 增 'x' 1. 得 0. 法 象 物 其 增 (新 键形) 8.",
            "物 取 {}. 形 键形: 算 同 另一: 物 其 增 'x' 1. 得 真. 法 算 印: 得 0. 法 象 物 其 增 (新 键形) 8. 物 其 查 (新 键形).",
        ]
        for source in cases:
            with self.subTest(source=source):
                vm, stream = self.make()
                with self.assertRaisesRegex(RuError, '修改'):
                    vm.execute(parse(source))
                self.idle(vm)
                vm.execute(parse("显 物 其 查 'x'."))
                self.assertEqual(stream.getvalue(), '1\n')
                self.idle(vm)

    def test_sort_callback_panic_and_then_success_without_stale_frames(self):
        self.output("""
原 取 [3,1,2].
试 原 其 排序 (算 左 右: 卒 '比较停'. 法). 救 因 显 因. 终.
显 原. 显 原 其 排序 (算 左 右: 得 左 < 右. 法).
显 原 其 另成 (算 项: 得 项*2. 法).
""", '比较停\n[3, 1, 2]\n[1, 2, 3]\n[6, 2, 4]\n')

    def test_snapshot_callback_finish_does_not_abort_iteration(self):
        self.output("""
原 取 [10,20,30]. 痕 取 [].
原 其 逐位 (作 位 项: { 痕 其 增 [位,项]. 原 其 弹. 完. } 显 99. 为).
显 痕. 显 原.
""", '[[0, 10], [1, 20], [2, 30]]\n[]\n')


if __name__ == '__main__':
    unittest.main()
