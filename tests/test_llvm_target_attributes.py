"""Clang target compatibility across the direct IR/runtime boundary."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from rulang.frontend import RuError
from rulang.llvm_toolchain import LLVMToolchain


class TargetAttributeTests(unittest.TestCase):
    def setUp(self):
        self.toolchain = LLVMToolchain.__new__(LLVMToolchain)
        self.toolchain.triple = 'x86_64-pc-linux-gnu'
        self.toolchain.function_target = {
            'target-cpu':'x86-64', 'target-features':'+sse,+sse2', 'tune-cpu':'generic'}

    def test_definitions_only_and_idempotent(self):
        ir = '@text = private constant [16 x i8] c"define void @x}\\00"\n'
        ir += 'declare void @external()\ndefine void @example() {\n ret void\n}\n'
        updated = self.toolchain.target_program(ir)
        self.assertEqual(updated.splitlines()[:2], ir.splitlines()[:2])
        self.assertEqual(updated.count('"target-features"='), 1)
        self.assertEqual(self.toolchain.target_program(updated), updated)
        self.assertNotIn('fast-math', updated)
        self.assertNotIn('no-trapping-math', updated)
        self.assertNotIn('uwtable', updated)

    def test_windows_adds_unwind_tables_to_every_definition(self):
        self.toolchain.triple = 'x86_64-pc-windows-msvc19.20.0'
        ir = 'declare void @external()\ndefine void @one() {\n ret void\n}\n'
        ir += 'define void @two() #0 {\n ret void\n}\nattributes #0 = { nounwind }\n'
        updated = self.toolchain.target_program(ir)
        self.assertEqual(updated.count(' uwtable'), 2)
        self.assertEqual(updated.splitlines()[0], ir.splitlines()[0])
        self.assertEqual(updated.count('"target-features"='), 2)
        self.assertEqual(self.toolchain.target_program(updated), updated)
        self.assertNotIn('fast-math', updated)
        self.assertNotIn('no-trapping-math', updated)

    def test_windows_preserves_direct_and_group_unwind_attributes(self):
        self.toolchain.triple = 'x86_64-pc-windows-msvc'
        for direct, group in [(' uwtable', ''), (' #0', 'attributes #0 = { uwtable }\n')]:
            with self.subTest(direct=direct):
                ir = 'define void @example()'+direct+' {\n ret void\n}\n'+group
                updated = self.toolchain.target_program(ir)
                self.assertEqual(updated.count('uwtable'), 1)
                self.assertEqual(self.toolchain.target_program(updated), updated)

    def test_windows_unwind_detection_ignores_names_and_string_attributes(self):
        self.toolchain.triple = 'x86_64-pc-windows-msvc'
        ir = 'define void @uwtable() "note"=" uwtable " #0 {\n ret void\n}\n'
        ir += 'attributes #0 = { "uwtable"=" uwtable " }\n'
        updated = self.toolchain.target_program(ir)
        self.assertIn(' uwtable {', updated)
        self.assertEqual(self.toolchain.target_program(updated), updated)

    def test_windows_keeps_target_conflict_check(self):
        self.toolchain.triple = 'x86_64-pc-windows-msvc'
        for suffix in [' uwtable "target-cpu"="haswell"', ' #0']:
            with self.subTest(suffix=suffix), self.assertRaisesRegex(RuError, '目标属性冲突'):
                self.toolchain.target_program('define void @example()'+suffix+
                    ' {\n ret void\n}\nattributes #0 = { uwtable "target-cpu"="haswell" }\n')

    def test_linux_preserves_unwind_policy(self):
        ir = 'define void @one() {\n ret void\n}\ndefine void @two() uwtable {\n ret void\n}\n'
        updated = self.toolchain.target_program(ir)
        self.assertEqual(updated.count('uwtable'), 1)
        self.assertNotIn('uwtable', updated.splitlines()[0])

    def test_existing_groups_must_match_selected_runtime(self):
        ir = 'define void @example() #0 {\n ret void\n}\n'
        ir += 'attributes #0 = { "target-cpu"="x86-64" }\n'
        updated = self.toolchain.target_program(ir)
        self.assertEqual(updated.count('"target-cpu"='), 1)
        with self.assertRaisesRegex(RuError, '目标属性冲突'):
            self.toolchain.target_program(ir.replace('x86-64', 'haswell'))

    def test_unrecognized_definition_header_is_rejected(self):
        with self.assertRaises(RuError):
            self.toolchain.target_program('define void @example()\n{\n ret void\n}\n')

    def test_real_runtime_helper_can_inline_into_direct_ir(self):
        try:
            tc = LLVMToolchain()
        except RuError:
            self.skipTest('LLVM14 required')
        ir = ('declare i32 @helper()\ndefine i32 @main() {\n'
              ' %v = call i32 @helper()\n ret i32 %v\n}\n')
        # The volatile load prevents constant-return propagation from passing
        # this check while a mismatched target still blocks actual inlining.
        runtime = 'volatile int input = 7; int helper(void) { return input; }\n'
        with tempfile.TemporaryDirectory() as temporary:
            binary, standalone = tc.compile(ir, runtime, temporary)
            optimized = standalone.read_text(encoding='utf-8')
            self.assertNotRegex(optimized, r'\bcall\b[^\n]*@helper\(')
            self.assertIn('load volatile i32', optimized)
            self.assertEqual(subprocess.run([str(binary)], timeout=10).returncode, 7)
