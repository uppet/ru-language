"""M4 acceptance: fresh generations, identical regressions and frozen evidence."""
import importlib.util
import json
from pathlib import Path
import sys
import time
import unittest

from rulang.llvm_toolchain import LLVMToolchain
from tools.bootstrap import ROOT, bootstrap, digest
from tools.bootstrap_compare import compare_native


def snapshots(paths):
    return {path.relative_to(ROOT).as_posix(): digest(path.read_bytes()) for path in sorted(set(paths))}


def input_paths():
    paths = [path for path in (ROOT/'rulang').rglob('*') if path.suffix in ('.py', '.h', '.ru')]
    paths += list((ROOT/'bootstrap').rglob('*.ru'))+list((ROOT/'bootstrap/validation').glob('*.json'))
    paths += list((ROOT/'tools').glob('bootstrap*.py'))
    paths += [ROOT/'tests/test_bootstrap.py']
    return paths


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = {}

    def startTest(self, test):
        super().startTest(test)
        self.records[test.id()] = {'id': test.id(), 'stage': test.stage_number,
                                   'case': test._testMethodName, 'status': 'running',
                                   'started': time.monotonic()}

    def stopTest(self, test):
        record = self.records[test.id()]
        record['seconds'] = time.monotonic()-record.pop('started')
        super().stopTest(test)

    def status(self, test, status):
        self.records[test.id()]['status'] = status

    def addSuccess(self, test):
        self.status(test, 'passed')
        super().addSuccess(test)

    def addFailure(self, test, error):
        self.status(test, 'failed')
        super().addFailure(test, error)

    def addError(self, test, error):
        if test.id() in self.records:
            self.status(test, 'error')
        super().addError(test, error)

    def addSkip(self, test, reason):
        if test.id() in self.records:
            self.status(test, 'skipped')
        super().addSkip(test, reason)

    def addSubTest(self, test, subtest, error):
        if error:
            self.status(test, 'failed')
        super().addSubTest(test, subtest, error)


def regression_gates(expected, records):
    stages = {str(index): [row for row in records if row['stage'] == index] for index in (1, 2, 3)}
    return {'same_nonempty_suite_for_each_stage': bool(expected['1']) and expected['1'] == expected['2'] == expected['3'],
            'every_planned_case_ran': all(sorted(row['case'] for row in stages[index]) == expected[index] for index in expected),
            'every_case_passed_without_skips': bool(records) and all(row['status'] == 'passed' for row in records)}


def verify(directory, selected=None):
    directory = Path(directory).resolve()
    # A failed new run must never leave an old "complete" acceptance report.
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory/'verification.json'
    destination.write_text(json.dumps({'m4_complete': False, 'status': 'running'})+'\n', encoding='utf-8')
    paths = input_paths()
    frozen = snapshots(paths)
    cycle = bootstrap(directory, selected)
    toolchain = LLVMToolchain(selected)
    suffix = '.exe' if sys.platform == 'win32' else ''
    binaries = [directory/('stage'+str(index)+suffix) for index in (1, 2, 3)]
    artifacts = binaries+[directory/('stage'+str(i)+'.ll') for i in (2, 3)]
    artifacts += [Path(str(binaries[i])+ending) for i in (1, 2) for ending in ('.frontend.ll', '.metadata.c')]
    artifact_hashes = {str(path): digest(path.read_bytes()) for path in artifacts}
    comparison = compare_native(binaries[1].read_bytes(), binaries[2].read_bytes())

    name = '_ru_bootstrap_acceptance'
    spec = importlib.util.spec_from_file_location(name, ROOT/'tests/test_bootstrap.py')
    cases = importlib.util.module_from_spec(spec)
    sys.modules[name] = cases
    spec.loader.exec_module(cases)
    cases.TOOLCHAIN, cases._STAGES = toolchain, (directory, cycle)
    classes = (cases.BootstrapStage1Tests, cases.BootstrapStage2Tests, cases.BootstrapTests)
    expected = {str(cls.stage_number): unittest.defaultTestLoader.getTestCaseNames(cls) for cls in classes}
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in classes)
    result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
    records = list(result.records.values())
    stages = {str(index): [row for row in records if row['stage'] == index] for index in (1, 2, 3)}
    frozen_after = snapshots(input_paths())
    artifacts_after = {str(path): digest(path.read_bytes()) for path in artifacts}
    gates = {'source_ir_and_abi_fixed_point': cycle['fixed_point'],
             'native_binary_fixed_point': comparison['normalized_equal'],
             **regression_gates(expected, records),
             'test_runner_success_without_skips': result.wasSuccessful() and not result.skipped,
             'inputs_unchanged': frozen == frozen_after,
             'artifacts_unchanged_during_tests': artifact_hashes == artifacts_after}
    report = {'format': 1, 'milestone': 'M4', 'platform': sys.platform,
              'scope': 'Declared native bootstrap frontend profile; not full Python frontend/package parity',
              'm4_complete': all(gates.values()), 'gates': gates, 'bootstrap': cycle,
              'native_comparison': comparison, 'planned_cases_by_stage': expected,
              'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
              'skipped': len(result.skipped), 'stages': stages, 'input_sha256': frozen,
              'artifact_sha256': artifact_hashes}
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(('M4 verification passed: ' if report['m4_complete'] else 'M4 verification FAILED: ')+str(destination), flush=True)
    return report
