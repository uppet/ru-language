#!/usr/bin/env python3
"""Fail closed when required 续 LLVM execution contracts cannot actually run."""
from pathlib import Path
import os
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT)]
from rulang.llvm_toolchain import LLVMToolchain
from test_continue_compilers import ContinueLLVMTests, ContinueNativeCTests, ContinueNativeLLVMTests

EXPECTED = {
    'test_counted_continue_advances_and_count_evaluated_once',
    'test_infinite_and_innermost_counted_loop',
    'test_scope_cleanup_and_escaping_closure',
    'test_continue_from_try_and_rescue_leaves_correct_handler',
    'test_zero_count_and_finish_are_distinct',
    'test_callback_owns_loop_and_cannot_continue_caller',
}

def selected_suite():
    classes = [ContinueLLVMTests]
    if os.name == 'nt':
        classes += [ContinueNativeCTests, ContinueNativeLLVMTests]
    suite = unittest.TestSuite()
    expected = {'test_continue_compilers.ContinueLLVMTests.' + name for name in EXPECTED}
    for cls in classes:
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
        if cls is not ContinueLLVMTests:
            expected.add('test_continue_compilers.' + cls.__name__ +
                         '.test_native_callback_continue_preserves_frame_and_outer_loop')
    return suite, expected

def main():
    LLVMToolchain()  # Missing/mismatched tools must fail, never make the job green by skipping.
    suite, expected = selected_suite()
    names = {test.id() for test in suite}
    if names != expected or suite.countTestCases() != len(expected):
        raise RuntimeError('续 LLVM contract selection changed or is incomplete')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if (result.wasSuccessful() and result.testsRun == len(expected)
                 and not result.skipped and not result.expectedFailures
                 and not result.unexpectedSuccesses) else 1

if __name__ == '__main__':
    raise SystemExit(main())
