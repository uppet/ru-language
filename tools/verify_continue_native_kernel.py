#!/usr/bin/env python3
"""Run native notebook regressions once, requiring actual continue coverage."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tests'), str(ROOT)]
from rulang.llvm_toolchain import LLVMToolchain
from test_rushu_native import NativeKernelTests

REQUIRED = {
    'test_continue_cannot_evade_native_graphics_budget',
    'test_continue_counted_nested_scope_rescue_and_finish',
    'test_continue_rejects_callable_boundaries_before_side_effects',
}

def main():
    LLVMToolchain()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(NativeKernelTests)
    planned = [test.id() for test in suite]
    names = {test._testMethodName for test in suite}
    if not REQUIRED <= names or len(planned) != len(set(planned)):
        raise RuntimeError('native notebook continue contract selection incomplete')
    executed = []
    class Result(unittest.TextTestResult):
        def startTest(self, test):
            executed.append(test.id())
            super().startTest(test)
    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    return 0 if (result.wasSuccessful() and executed == planned
                 and result.testsRun == len(planned) and not result.skipped
                 and not result.expectedFailures and not result.unexpectedSuccesses) else 1

if __name__ == '__main__': raise SystemExit(main())
