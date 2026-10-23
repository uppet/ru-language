"""Portable owned-result pack layout checks; execution/GC gates are separate."""
from pathlib import Path
import re
import unittest

from rulang.frontend import parse
from rulang.llvm_compiler import LLVMCompiler


class PackHarness(LLVMCompiler):
    def __init__(self, prefix=0):
        self.llvm_counter = self.slot_count = self.slot_peak = 0
        self.entry_allocations, self.slot_addresses, self.constants = [], [], []
        self.strings, self.calls, self.evaluated = {}, [], []
        for _ in range(prefix):
            self.slot()

    def expr(self, expression):
        tag, count, result_index = expression
        self.evaluated.append(tag)
        slots = [self.slot() for _ in range(count)]
        return slots[result_index]

    def call_abi(self, operation, *args):
        self.calls.append((operation, args))


def argument(tag, count=1, result_index=0, key=None):
    return key, (tag, count, result_index)


def lower(source):
    compiler = LLVMCompiler(parse(source), '<owned-pack-test>', full_runtime=True)
    return compiler.compile()


class ArgumentPackTests(unittest.TestCase):
    def test_empty_preserves_null_contract(self):
        emitter = PackHarness()
        self.assertEqual(emitter.pack([]), ('0', 'null', 'null'))
        self.assertEqual((emitter.slot_count, emitter.calls, emitter.constants), (0, [], []))

    def test_single_complex_result_need_not_be_last_slot(self):
        for count in (1, 2, 5):
            for result in range(count):
                with self.subTest(count=count, result=result):
                    emitter = PackHarness(prefix=3)
                    argc, keys, values = emitter.pack([argument('one', count, result)])
                    self.assertEqual(argc, '1')
                    self.assertEqual(values, emitter.slot_addresses[3 + result])
                    self.assertEqual(emitter.slot_count, 3 + count)
                    self.assertEqual(emitter.calls, [])

    def test_multiple_one_slot_results_reuse_adjacent_owned_roots(self):
        emitter = PackHarness(prefix=2)
        argc, _, values = emitter.pack([argument('left'), argument('middle'), argument('right')])
        self.assertEqual((argc, values), ('3', emitter.slot_addresses[2]))
        self.assertEqual(emitter.evaluated, ['left', 'middle', 'right'])
        self.assertEqual((emitter.slot_count, emitter.slot_peak, emitter.calls), (5, 5, []))

    def test_any_complex_argument_retains_contiguous_copy_fallback(self):
        for complex_index in range(3):
            with self.subTest(complex_index=complex_index):
                emitter = PackHarness(prefix=2)
                args = [argument(str(i), 3 if i == complex_index else 1) for i in range(3)]
                argc, _, values = emitter.pack(args)
                self.assertEqual(argc, '3')
                self.assertEqual(values, emitter.slot_addresses[7])
                self.assertEqual(emitter.slot_count, 10)
                self.assertEqual([name for name, _ in emitter.calls], ['copy'] * 3)
                self.assertEqual([args[0] for _, args in emitter.calls], emitter.slot_addresses[7:10])
                self.assertTrue(all(out != source for _, (out, source) in emitter.calls))

    def test_named_arguments_keep_source_order_and_key_table(self):
        emitter = PackHarness()
        argc, keys, _ = emitter.pack([argument('second', key='乙'), argument('first', key='甲')])
        self.assertEqual(emitter.evaluated, ['second', 'first'])
        self.assertEqual(argc, '2')
        self.assertIn('[2 x i8*]', keys)
        table = emitter.constants[-1]
        self.assertLess(table.index(emitter.strings['乙']), table.index(emitter.strings['甲']))

    def test_real_scalar_array_has_no_pack_copies(self):
        ir = lower('显 [1,2,3].\n')
        self.assertNotIn('call void @rul_copy(', ir)
        self.assertIn('@rul_frame_new(i32 4)', ir)

    def test_real_complex_multi_array_keeps_fallback(self):
        ir = lower('显 [(1+2),3].\n')
        self.assertEqual(ir.count('call void @rul_copy('), 2)

    def test_real_single_complex_array_has_no_pack_copies(self):
        ir = lower('显 [(1+2)].\n')
        self.assertNotIn('call void @rul_copy(', ir)

    def test_zero_arg_array_is_null_not_physical_slot_zero(self):
        ir = lower('显 [].\n')
        self.assertRegex(ir, r'@rul_array\(i8\* %v\d+, i32 0, i8\* null, i32 1\)')

    def test_result_and_argument_addresses_remain_distinct(self):
        ir = lower('显 [1,2].\n')
        out, first = re.search(r'@rul_array\(i8\* (%v\d+), i32 2, i8\* (%v\d+),', ir).groups()
        self.assertNotEqual(out, first)
        indices = dict(re.findall(r'(%v\d+) = call i8\* @rul_slot\(i8\* %frame, i32 (\d+)\)', ir))
        self.assertEqual((indices[first], indices[out]), ('0', '2'))

    def test_all_fixed_cases_compile_with_unique_ssa_and_exact_physical_bounds(self):
        from bootstrap_pack_cases import CASES
        self.assertEqual(len(CASES), 17)
        for name, source, expected in CASES:
            with self.subTest(name=name):
                ir = lower(source)
                for body in re.findall(r'define void @[^}]+}', ir):
                    names = re.findall(r'^  (%\w+) =', body, re.M)
                    self.assertEqual(len(names), len(set(names)))
                    extent = int(re.search(r'@rul_frame_new\(i32 (\d+)\)', body)[1])
                    indices = [int(x) for x in re.findall(r'@rul_slot\(i8\* %frame, i32 (\d+)\)', body)]
                    self.assertEqual(indices, list(range(extent)))

    def test_pure_ru_guard_and_entire_source_still_parse(self):
        source = (Path(__file__).resolve().parents[1] / 'bootstrap/compiler.ru').read_text(encoding='utf-8')
        self.assertEqual(source.count('    复用 取 (值 其 量) == 1 或 连续.'), 1)
        self.assertIn("若 状['位数'] != 前+1 则 连续 取 假.", source)
        parse(source)


class PhysicalSlotParserTests(unittest.TestCase):
    @staticmethod
    def check(ir):
        from test_bootstrap_pack_runtime import physical_slots
        return physical_slots(ir)

    @staticmethod
    def function(name='example', extent=0, indices=()):
        rows = ['define void @'+name+'() {', 'entry:',
                '  %frame = call i8* @rul_frame_new(i32 '+str(extent)+')']
        rows += ['  %v'+str(i)+' = call i8* @rul_slot(i8* %frame, i32 '+str(index)+')'
                 for i,index in enumerate(indices)]
        return '\n'.join(rows+['  ret void', '}', ''])

    def test_real_generated_function_text_in_global_strings_is_not_a_function(self):
        generated = lower("显 'define void @fake'.\n显 '}'.\n")
        ir = generated
        # Python escapes every string byte.  Use the equivalent literal ASCII
        # spelling emitted by pure Ru, preserving functions and decoded bytes.
        for text in ('define void @fake','}'):
            escaped = 'c"'+''.join('\\%02X' % byte for byte in text.encode())+'\\00"'
            self.assertEqual(ir.count(escaped),1)
            ir = ir.replace(escaped,'c"'+text+'\\00"')
        self.assertRegex(ir, re.compile(r'^@\w+ = .*c"define void @fake', re.M))
        headers = re.findall(r'^define void @', ir, re.M)
        self.assertTrue(headers)
        self.assertGreater(len(re.findall(r'define void @[^}]+}', ir)),len(headers))
        rows = self.check(ir)
        self.assertEqual(rows,self.check(generated))
        self.assertEqual(len(rows),len(headers))
        self.assertTrue(all(row['addresses']==row['frame_slots'] for row in rows))

    def test_string_only_input_cannot_count_as_actual_generated_functions(self):
        ir = '@text = private constant [16 x i8] c"define void @x}\\00"\n'
        with self.assertRaisesRegex(AssertionError,'actual generated functions required'):
            self.check(ir)

    def test_zero_extent_is_valid_and_every_real_function_is_checked(self):
        self.assertEqual(self.check(self.function()),[{'frame_slots':0,'addresses':0}])
        self.assertEqual(self.check(self.function()+self.function('second',2,(0,1))),
                         [{'frame_slots':0,'addresses':0},{'frame_slots':2,'addresses':2}])

    def test_missing_duplicate_and_empty_function_frames_are_rejected(self):
        frame = '  %frame = call i8* @rul_frame_new(i32 0)\n'
        good = self.function()
        cases = {
            'missing':good.replace(frame,''),
            'duplicate':good.replace(frame,frame+'  %other = call i8* @rul_frame_new(i32 0)\n'),
            'empty':'define void @empty() {\n}\n',
            'second_missing':good+self.function('unframed').replace(frame,''),
        }
        for name,ir in cases.items():
            with self.subTest(name=name),self.assertRaisesRegex(AssertionError,'exactly one frame'):
                self.check(ir)

    def test_missing_or_malformed_boundaries_cannot_hide_or_merge_functions(self):
        good = self.function()
        unclosed = good.rsplit('}',1)[0]
        cases = {
            'missing_close':unclosed,
            'next_void':unclosed+self.function('second'),
            'next_main':unclosed+'define i32 @main() {\n  ret i32 0\n}\n',
            'later_unclosed':good+self.function('second').rsplit('}',1)[0],
            'inline_close':good.replace('  ret void\n}', '  ret void }'),
            'missing_open':good.replace('() {','()'),
        }
        for name,ir in cases.items():
            with self.subTest(name=name),self.assertRaisesRegex(AssertionError,'function boundary'):
                self.check(ir)

    def test_duplicate_ssa_is_still_rejected(self):
        good = self.function(extent=1,indices=(0,))
        slot = '  %v0 = call i8* @rul_slot(i8* %frame, i32 0)\n'
        with self.assertRaisesRegex(AssertionError,'duplicate SSA definition'):
            self.check(good.replace(slot,slot+slot))

    def test_missing_duplicate_out_of_bounds_and_reordered_slots_are_rejected(self):
        for name,indices in [('missing',(0,)),('duplicate',(0,0)),
                             ('out_of_bounds',(0,2)),('reordered',(1,0))]:
            with self.subTest(name=name),self.assertRaisesRegex(AssertionError,'inventory/highwater mismatch'):
                self.check(self.function(extent=2,indices=indices))
        with self.assertRaisesRegex(AssertionError,'inventory/highwater mismatch'):
            self.check(self.function(extent=0,indices=(0,)))


if __name__ == '__main__':
    unittest.main()
