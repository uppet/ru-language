"""Required continue gate must reject missing, failed, or skipped LLVM tests."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify_continue_llvm', ROOT/'tools/verify_continue_llvm.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

class ContinueGateTests(unittest.TestCase):
    def result(self, **changes):
        result = dict(testsRun=len(gate.selected_suite()[1]), skipped=[], expectedFailures=[], unexpectedSuccesses=[],
                      wasSuccessful=lambda: True)
        result.update(changes)
        return SimpleNamespace(**result)

    def run_gate(self, result):
        with patch.object(gate, 'LLVMToolchain'), patch.object(gate.unittest.TextTestRunner, 'run', return_value=result):
            return gate.main()

    def test_complete_success(self):
        self.assertEqual(self.run_gate(self.result()), 0)

    def test_rejects_incomplete_failed_or_skipped(self):
        for change in ({'testsRun':0}, {'testsRun':5}, {'skipped':['missing']},
                       {'expectedFailures':['bad']}, {'unexpectedSuccesses':['bad']},
                       {'wasSuccessful':lambda:False}):
            with self.subTest(change=change):
                self.assertEqual(self.run_gate(self.result(**change)), 1)

    def test_missing_toolchain_is_error(self):
        with patch.object(gate, 'LLVMToolchain', side_effect=RuntimeError('missing')):
            with self.assertRaisesRegex(RuntimeError, 'missing'): gate.main()

    def test_missing_selection_is_error(self):
        with patch.object(gate, 'LLVMToolchain'), patch.object(gate.unittest.defaultTestLoader, 'loadTestsFromTestCase', return_value=unittest.TestSuite()):
            with self.assertRaisesRegex(RuntimeError, 'incomplete'): gate.main()

native_spec = importlib.util.spec_from_file_location('verify_continue_native_kernel', ROOT/'tools/verify_continue_native_kernel.py')
native_gate = importlib.util.module_from_spec(native_spec)
native_spec.loader.exec_module(native_gate)

class NativeContinueGateTests(unittest.TestCase):
    def run_gate(self, outcome='pass'):
        class Fixture(unittest.TestCase):
            def test_continue_cannot_evade_native_graphics_budget(self): pass
            def test_continue_counted_nested_scope_rescue_and_finish(self):
                if outcome == 'skip': self.skipTest('not executed')
                if outcome == 'fail': self.fail('wrong result')
            def test_continue_rejects_callable_boundaries_before_side_effects(self): pass
        with patch.object(native_gate, 'LLVMToolchain'), patch.object(native_gate, 'NativeKernelTests', Fixture):
            return native_gate.main()

    def test_actual_selected_execution_succeeds(self):
        self.assertEqual(self.run_gate(), 0)

    def test_skip_and_failure_are_not_acceptance(self):
        for outcome in ('skip', 'fail'):
            with self.subTest(outcome=outcome): self.assertEqual(self.run_gate(outcome), 1)

    def test_missing_required_case_is_error(self):
        with patch.object(native_gate, 'LLVMToolchain'), patch.object(native_gate.unittest.defaultTestLoader, 'loadTestsFromTestCase', return_value=unittest.TestSuite()):
            with self.assertRaisesRegex(RuntimeError, 'incomplete'): native_gate.main()
