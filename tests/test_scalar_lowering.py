"""Scalar lowering must preserve dynamic effects, errors, and rooted operands."""
import io
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from rulang.frontend import parse
from rulang.interpreter import Interpreter
from rulang.llvm_compiler import LLVMCompiler
from test_bootstrap import TOOLCHAIN, prepared_stages
from test_c_bindings import CC, build, generate
from tools.bootstrap import compile_native


CONDITIONS = """
算 报 值: 显 值. 得 值. 法.
算 错: 卒 'caught'. 得 真. 法.
若 0 且 非 空 则 显 'zero true'. 然.
显 (假 且 错()). 显 (真 或 错()).
显 ((报 0) 且 ((报 假) 或 (报 真))).
显 ((报 空) 或 ((报 7) 且 (报 ''))).
试 若 真 且 (错() 或 报 'wrong') 则 显 'wrong'. 然.
救 因 显 因. 终.
形 点:
 值 为 数.
 算 同 另一: 显 'compare'. 卒 'equality'. 得 假. 法.
象.
左 取 新 点 值:1. 右 取 新 点 值:2.
试 若 (左 == 右) 且 (报 'wrong') 则 显 'wrong'. 然.
救 因 显 因. 终.
序 取 0.
循 6 次
 序 取 序+1.
 若 序 == 2 或 序 == 4 则 续. 然.
 若 序 >= 5 且 序 != 6 则 破. 然.
 显 序.
环.
显 非 (1 < 2 且 3 >= 3). 显 (1 == 真 或 0 != -0).
显 ([] 且 {} 或 空). 显 ((1 对 2) == (1 对 2) 且 'a' < 'b').
"""

NUMBERS = """
算 报 值: 显 值. 得 值. 法.
算 算数 x:
 得 ((x-1)*(x+2)/(x+3)) % 7.
法.
显 算数 13.
显 ((报 4)-(报 1))*((报 2)+(报 3)).
显 -('2.5' 为 数) + +3.5.
显 -7 % 3. 显 7 % -3.
显 9007199254740992+1 == 9007199254740992.
显 5e-324/2 == 0. 显 0-0. 显 -0.
显 'left'+'right'.
值 取 [1]. 值[0] 取 (值[0]+2)*3. 显 值.
算 外:
 项 取 1. 算 改: 项 取 'changed'. 得 2. 法.
 得 ((项+1)*(改())) 对 项.
法.
显 外().
"""

CALL_STORAGE = """
形 盒:
 值 为 阵.
 算 改 列:
  算 看: 得 [其 值,列]. 法.
  其 值[0] 取 列[0].
  列[0] 取 'after'.
  得 算 看.
 法.
象.
共享 取 ['before']. 对象 取 新 盒 值:['old'].
闭包 取 对象 其 改 共享. 显 共享.
对象 取 空. 共享 取 空.
循 12 次 临时 取 ['pressure',[]]. 环.
显 闭包().
"""
CALL_STORAGE_OUTPUT = '[after]\n[[before], [after]]\n'


class ScalarIRTests(unittest.TestCase):
    def test_root_map_keeps_high_bit_without_binary64_rounding(self):
        source = '算 边界: 得 ['+','.join(str(i) for i in range(63))+']. 法.'
        ir = LLVMCompiler(parse(source)).compile()
        self.assertIn('call void @rul_local_frame_roots(i8* %frame, i32 0, i32 2147483648)', ir)
        ir = LLVMCompiler(parse(source.replace('得 [', '显 [').replace(']. 法.', ']. 得 0. 法.'))).compile()
        self.assertIn('call void @rul_local_clear_mask(i8* %frame, i32 64, i32 0, i32 2147483648)', ir)
        ir = LLVMCompiler(parse("值 取 ['heap']. 值 取 7. 显 值.")).compile()
        self.assertIn('call void @rul_local_clear_mask(i8* %frame, i32 1, i32 0, i32 0)', ir)
        self.assertIn('call void @rul_local_frame_drop(i8* %frame)', ir)
        self.assertNotIn('@rul_local_drop(', ir)


    def test_numeric_expression_uses_ssa_and_only_boxes_final_result(self):
        compiler = LLVMCompiler(parse('算 看 x: 得 (x-1)*(x+2). 法.'))
        ir = compiler.compile()
        self.assertIn('i8* noalias writeonly %out)', ir)
        for operation in ('fsub', 'fadd', 'fmul'):
            self.assertIn(' = '+operation+' double ', ir)
        self.assertEqual(ir.count('call void @rul_init_number('), 1)
        self.assertNotIn('call void @rul_init_mul(', ir)
        runtime = compiler.runtime_c()
        self.assertIn('if(fn->direct)', runtime)
        self.assertNotIn('_bridge(', runtime)

    def test_conditions_have_no_fact_result_slots(self):
        source = "算 看 a b: 若 (a < b 且 非 假) 或 a == b 则 得 1. 然. 得 0. 法."
        ir = LLVMCompiler(parse(source)).compile()
        self.assertIn(' = phi i1 ', ir)
        self.assertIn('call i32 @rul_test_lt(', ir)
        self.assertNotIn('call void @rul_init_fact(', ir)
        self.assertNotIn('call void @rul_fact(', ir)


class ScalarExecutionContract:
    backend = 'c'

    def execute(self, source):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            if self.backend == 'c':
                binary = build(generate(source), root, 'scalar')
            elif self.backend == 'llvm':
                compiler = LLVMCompiler(parse(source), '/scalar.ru')
                binary, _ = TOOLCHAIN.compile(compiler.compile(TOOLCHAIN.triple, TOOLCHAIN.data_layout),
                                               compiler.runtime_c(), root)
            else:
                selected = os.environ.get('RU_SCALAR_TEST_COMPILER')
                if selected:
                    native = Path(selected).resolve()
                else:
                    directory, _ = prepared_stages()
                    native = directory/('stage3.exe' if os.name == 'nt' else 'stage3')
                entry = root/'scalar.ru'
                entry.write_text(source, encoding='utf-8')
                binary = root/'program.exe'
                with patch('rulang.frontend.parse', side_effect=AssertionError('host parser')), \
                     patch.object(LLVMCompiler, 'compile', side_effect=AssertionError('host lowering')):
                    compile_native(native, entry, binary, TOOLCHAIN)
            return subprocess.run([str(binary)], capture_output=True, text=True, encoding='utf-8',
                                  timeout=30, env={**os.environ, 'RU_GC_THRESHOLD':'1', 'RU_GC_STATS':'1'})

    def test_short_circuit_truth_panic_equality_and_loop_cleanup(self):
        output = io.StringIO()
        Interpreter(stdout=output).execute(parse(CONDITIONS))
        result = self.execute(CONDITIONS)
        self.assertEqual((result.returncode, result.stdout), (0, output.getvalue()), result.stderr)
        self.assertRegex(result.stderr, r'^RU_GC live=0 freed=\d+ collections=\d+\s*$')

    def test_call_storage_allows_heap_mutation_and_escaping_closures(self):
        result = self.execute(CALL_STORAGE)
        self.assertEqual((result.returncode, result.stdout), (0, CALL_STORAGE_OUTPUT), result.stderr)
        self.assertRegex(result.stderr, r'^RU_GC live=0 freed=\d+ collections=\d+\s*$')

    def test_consumed_operands_keep_results_and_aliases_rooted(self):
        source = """
算 刷:
 循 12 次 临时 取 ['garbage', [1,2,3]]. 环.
 得 'later'.
法.
算 生: 得 [['kept'], ['other']]. 法.
显 [(生()[0])[0], 刷()].
显 [生()[0:1], 刷()].
显 [('甲'+'乙') 对 ('丙'+'丁'), 刷()].
显 [('12'+'3') 为 数, 刷()].
算 外:
 共同 取 [['old']].
 算 改: 共同[0] 取 ['new']. 得 刷(). 法.
 得 [共同[0], 改(), 共同[0]].
法.
显 外().
若 生()[0] 且 (刷() == 'later') 则 显 'truth'. 然.
"""
        output = io.StringIO()
        Interpreter(stdout=output).execute(parse(source))
        result = self.execute(source)
        self.assertEqual((result.returncode, result.stdout), (0, output.getvalue()), result.stderr)
        self.assertRegex(result.stderr, r'^RU_GC live=0 freed=\d+ collections=\d+\s*$')

    def test_comparison_diagnostic_is_preserved(self):
        result = self.execute("若 1 < 真 则 显 'wrong'. 然.")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('比较需要相同的数字或字符串类型', result.stderr)

    def test_control_character_literals_survive_native_source_processing(self):
        result = self.execute("显 '\\n'. 显 '\x1c\x1d\x1e\u0085\u2028\u2029'.")
        self.assertEqual((result.returncode, result.stdout), (0, '\n\n\x1c\x1d\x1e\u0085\u2028\u2029\n'), result.stderr)

    def test_numeric_intermediates_rounding_order_and_mutation(self):
        output = io.StringIO()
        Interpreter(stdout=output).execute(parse(NUMBERS))
        result = self.execute(NUMBERS)
        self.assertEqual((result.returncode, result.stdout), (0, output.getvalue()), result.stderr)
        self.assertRegex(result.stderr, r'^RU_GC live=0 freed=\d+ collections=\d+\s*$')

    def test_numeric_checks_keep_original_failure_order(self):
        cases = [
            ("('bad' - (报 2))", '2\n', '算术运算符 - 需要两个数字'),
            ("((报 1e308)*(报 2))*(报 0)", '1e+308\n2\n', '运算结果不是有限数字'),
            ("(报 1)/(报 (-0))", '1\n-0\n', '除数不能为零'),
            ("(报 1)%(报 0)", '1\n0\n', '除数不能为零'),
            ("-(报 'bad')", 'bad\n', '运算符 - 需要数字'),
        ]
        for expression, expected, error in cases:
            with self.subTest(expression=expression):
                result = self.execute('算 报 值: 显 值. 得 值. 法. 显 '+expression+'.')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, expected)
                self.assertIn(error, result.stderr)


@unittest.skipUnless(CC, 'C compiler required')
class ScalarCExecutionTests(ScalarExecutionContract, unittest.TestCase):
    backend = 'c'


@unittest.skipUnless(TOOLCHAIN, 'LLVM14 required')
class ScalarLLVMExecutionTests(ScalarExecutionContract, unittest.TestCase):
    backend = 'llvm'

    def test_unwritten_local_payload_cleanup_and_reuse(self):
        compiler = LLVMCompiler(parse(''), '/unwritten-local.ru')
        ir = compiler.compile(TOOLCHAIN.triple, TOOLCHAIN.data_layout)
        anchor = 'entry:\n  %status = call i32 @rul_main'
        self.assertEqual(ir.count(anchor), 1)
        # Poison both raw buffers before registration. Untaken paths may leave
        # their payload unwritten; cleanup must inspect only initialized roots.
        probe = '''  %probe_bytes = call i64 @rul_local_frame_size(i32 2)
  %probe_frame = alloca i8, i64 %probe_bytes, align 16
  call void @rul_local_frame_init(i8* %probe_frame, i32 2)
  %probe_value_bytes = call i64 @rul_args_size(i32 1)
  %probe_a_storage = alloca i8, i64 %probe_value_bytes, align 16
  %probe_b_storage = alloca i8, i64 %probe_value_bytes, align 16
  call void @llvm.memset.p0i8.i64(i8* %probe_a_storage, i8 -91, i64 %probe_value_bytes, i1 false)
  call void @llvm.memset.p0i8.i64(i8* %probe_b_storage, i8 -91, i64 %probe_value_bytes, i1 false)
  %probe_a = call i8* @rul_local_slot(i8* %probe_frame, i32 0, i8* %probe_a_storage)
  %probe_b = call i8* @rul_local_slot(i8* %probe_frame, i32 1, i8* %probe_b_storage)
  call void @rul_local_clear_count(i8* %probe_frame, i32 2)
  call void @rul_init_array(i8* %probe_a, i32 0, i8* null, i32 1)
  call void @rul_local_clear_count(i8* %probe_frame, i32 2)
  call void @rul_init_number(i8* %probe_a, double 7.0)
  call void @rul_init_copy(i8* %probe_b, i8* %probe_a)
  call void @rul_print(i8* %probe_b, i32 1)
  call void @rul_local_clear_count(i8* %probe_frame, i32 2)
  call void @rul_init_array(i8* %probe_a, i32 0, i8* null, i32 1)
  call void @rul_print(i8* %probe_a, i32 1)
  call void @rul_local_frame_drop(i8* %probe_frame)
'''
        program = ir.replace(anchor, 'entry:\n' + probe + '  %status = call i32 @rul_main')
        program += '\ndeclare void @llvm.memset.p0i8.i64(i8*, i8, i64, i1)\n'
        with tempfile.TemporaryDirectory() as folder:
            binary, _ = TOOLCHAIN.compile(program, compiler.runtime_c(), Path(folder))
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30,
                                    env={**os.environ, 'RU_GC_THRESHOLD':'1', 'RU_GC_STATS':'1'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '7\n[]\n')
            self.assertRegex(result.stderr, r'^RU_GC live=0 freed=\d+ collections=\d+\s*$')

    def test_single_root_cleanup_respects_prefix_and_high_bit(self):
        compiler = LLVMCompiler(parse(''), '/cleanup-single-root.ru')
        ir = compiler.compile(TOOLCHAIN.triple, TOOLCHAIN.data_layout)
        anchor = 'entry:\n  %status = call i32 @rul_main'
        self.assertEqual(ir.count(anchor), 1)
        # Out-of-prefix bits must not read the as-yet uninitialized field
        # table. Only slots 0 and 63 are registered in this synthetic frame.
        probe = '''  %probe_bytes = call i64 @rul_local_frame_size(i32 64)
  %probe_frame = alloca i8, i64 %probe_bytes, align 16
  call void @rul_local_frame_init(i8* %probe_frame, i32 64)
  call void @rul_local_clear_mask(i8* %probe_frame, i32 0, i32 1, i32 0)
  call void @rul_local_clear_mask(i8* %probe_frame, i32 63, i32 0, i32 2147483648)
  %probe_value_bytes = call i64 @rul_args_size(i32 1)
  %probe_low_storage = alloca i8, i64 %probe_value_bytes, align 16
  %probe_high_storage = alloca i8, i64 %probe_value_bytes, align 16
  %probe_low = call i8* @rul_local_slot(i8* %probe_frame, i32 0, i8* %probe_low_storage)
  %probe_high = call i8* @rul_local_slot(i8* %probe_frame, i32 63, i8* %probe_high_storage)
  call void @rul_init_array(i8* %probe_high, i32 0, i8* null, i32 1)
  call void @rul_local_clear_mask(i8* %probe_frame, i32 63, i32 0, i32 2147483648)
  call void @rul_init_array(i8* %probe_low, i32 0, i8* null, i32 1)
  call void @rul_print(i8* %probe_high, i32 1)
  call void @rul_local_clear_mask(i8* %probe_frame, i32 64, i32 0, i32 2147483648)
  call void @rul_local_clear_mask(i8* %probe_frame, i32 64, i32 0, i32 2147483648)
  call void @rul_init_array(i8* %probe_high, i32 0, i8* null, i32 1)
  call void @rul_print(i8* %probe_high, i32 1)
  call void @rul_local_clear_mask(i8* %probe_frame, i32 64, i32 0, i32 2147483648)
  call void @rul_local_clear_mask(i8* %probe_frame, i32 1, i32 1, i32 0)
'''
        program = ir.replace(anchor, 'entry:\n' + probe + '  %status = call i32 @rul_main')
        with tempfile.TemporaryDirectory() as folder:
            binary, _ = TOOLCHAIN.compile(program, compiler.runtime_c(), Path(folder))
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30,
                                    env={**os.environ, 'RU_GC_THRESHOLD':'1', 'RU_GC_STATS':'1'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '[]\n[]\n')
            self.assertRegex(result.stderr, r'^RU_GC live=0 freed=\d+ collections=\d+\s*$')

    def test_cleanup_helpers_check_bounds_before_scanning(self):
        compiler = LLVMCompiler(parse(''), '/cleanup-bounds.ru')
        ir = compiler.compile(TOOLCHAIN.triple, TOOLCHAIN.data_layout)
        anchor = 'entry:\n  %status = call i32 @rul_main'
        self.assertEqual(ir.count(anchor), 1)
        setup = ('  %bounds_bytes = call i64 @rul_local_frame_size(i32 1)\n'
                 '  %bounds_frame = alloca i8, i64 %bounds_bytes, align 16\n'
                 '  call void @rul_local_frame_init(i8* %bounds_frame, i32 1)\n'
                 '  call void @rul_local_frame_roots(i8* %bounds_frame, i32 0, i32 0)\n')
        for helper in ('local_clear_count', 'local_clear_mask'):
            for count in (-1, 0, 2):
                args = f'i8* %bounds_frame, i32 {count}'
                if helper == 'local_clear_mask':
                    args += ', i32 0, i32 0'
                probe = setup + f'  call void @rul_{helper}({args})\n'
                program = ir.replace(anchor, 'entry:\n' + probe + '  %status = call i32 @rul_main')
                with self.subTest(helper=helper, count=count), tempfile.TemporaryDirectory() as folder:
                    binary, _ = TOOLCHAIN.compile(program, compiler.runtime_c(), Path(folder))
                    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30,
                                            env={**os.environ, 'RU_GC_THRESHOLD':'1', 'RU_GC_STATS':'1'})
                    self.assertEqual(result.stdout, '')
                    if count == 0:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn('RU_GC live=0 ', result.stderr)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('LLVM 临时值清理越界', result.stderr)

    def test_omitting_real_roots_is_rejected_by_gc_evidence(self):
        # Reusing the slots exposes a missed normal clear even though final
        # cleanup still scans the complete union mask: the overwritten root
        # cannot be recovered at function exit.
        source = "算 生: 得 [1,[]]. 法. 循 5 次 值 取 生(). 值 取 7. 环. 显 'done'."
        compiler = LLVMCompiler(parse(source), '/roots-negative.ru')
        ir = compiler.compile(TOOLCHAIN.triple, TOOLCHAIN.data_layout)
        broken = re.sub(r'(call void @rul_(?:local_)?frame_roots\(i8\* %frame), i32 \d+, i32 \d+\)',
                        r'\1, i32 0, i32 0)', ir)
        normal_missing = re.sub(
            r'(call void @rul_local_clear_mask\(i8\* %frame, i32 \d+), i32 \d+, i32 \d+\)',
            r'\1, i32 0, i32 0)', ir)
        broken = re.sub(
            r'(call void @rul_local_clear_mask\(i8\* %frame, i32 \d+), i32 \d+, i32 \d+\)',
            r'\1, i32 0, i32 0)', broken)
        self.assertNotEqual(ir, broken)
        self.assertNotEqual(ir, normal_missing)
        for label, program, should_release in (
                ('correct', ir, True), ('missing-roots', broken, False),
                ('missing-normal-roots', normal_missing, False)):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as folder:
                binary, _ = TOOLCHAIN.compile(program, compiler.runtime_c(), Path(folder))
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30,
                                        env={**os.environ, 'RU_GC_THRESHOLD':'1', 'RU_GC_STATS':'1'})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual('RU_GC live=0 ' in result.stderr, should_release, result.stderr)


@unittest.skipUnless(TOOLCHAIN, 'LLVM14 required')
class ScalarBootstrapExecutionTests(ScalarExecutionContract, unittest.TestCase):
    backend = 'bootstrap'
