"""Adversarial receipts for the isolated interpreter-stack CI runner.

No child process or timeout sleep is performed: every subprocess outcome is
controlled, while the production runner writes real receipts and log files.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('stack_ci_under_test', ROOT/'tools/verify_interpreter_stack.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class InterpreterStackCIContractTests(unittest.TestCase):
    def run_scenario(self, first='success', mutate_receipt=None, drift=False):
        class PlannedCase(unittest.TestCase):
            def __init__(self, name):
                super().__init__()
                self.case_name = name

            def id(self):
                return 'fixture.StackTests.'+self.case_name

            def runTest(self):
                pass

        with tempfile.TemporaryDirectory(prefix='ru-stack-ci-contract-') as directory:
            root = Path(directory)
            out = root/'evidence'
            for name in ('rulang/interpreter.py', 'tools/verify_interpreter_stack.py', 'tests/fixture.py'):
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('# frozen source\n', encoding='utf-8')
            out.mkdir()
            # A stale green receipt must not make startup failure look successful.
            (out/'000.json').write_text(json.dumps({'case': 'fixture.StackTests.a', 'passed': True}), encoding='utf-8')
            calls = []

            def child(command, **kwargs):
                case = command[command.index('--child')+1]
                receipt = Path(command[command.index('--out')+1])
                self.assertFalse(receipt.exists())
                self.assertEqual(command[1:3], ['-X', 'faulthandler'])
                self.assertEqual(kwargs['timeout'], 120)
                self.assertTrue(kwargs['capture_output'])
                self.assertEqual(kwargs['cwd'], root)
                started = json.loads((out/'report.json').read_text(encoding='utf-8'))
                self.assertEqual(started['attempts'][-1]['case'], case)
                self.assertFalse(started['attempts'][-1]['passed'])
                self.assertIsNone(started['attempts'][-1]['returncode'])
                calls.append(case)
                action = first if len(calls) == 1 else 'success'
                if drift and len(calls) == 1:
                    if drift == 'deleted':
                        (root/'rulang/interpreter.py').unlink()
                    else:
                        (root/'rulang/interpreter.py').write_text('# changed during execution\n', encoding='utf-8')
                if action == 'startup':
                    raise OSError('controlled spawn failure')
                if action == 'timeout':
                    raise subprocess.TimeoutExpired(command, 120, output=b'partial stdout\n', stderr=b'partial stderr\n')
                result = {'case': case, 'tests_run': 1, 'failures': 0, 'errors': 0,
                          'skipped': [], 'passed': True}
                if mutate_receipt and len(calls) == 1:
                    result.update(mutate_receipt)
                if action != 'missing':
                    receipt.write_text('{broken' if action == 'malformed' else json.dumps(result), encoding='utf-8')
                return subprocess.CompletedProcess(command, -1073741571 if action == 'nonzero' else 0,
                                                   b'child stdout\n', b'child stderr\n')

            suite = unittest.TestSuite([PlannedCase('b'), PlannedCase('a'), PlannedCase('c')])
            with patch.object(runner.platform, 'platform', return_value='test-platform'), \
                 patch.object(runner, 'ROOT', root), patch.object(runner, 'MODULES', ('fixture',)), \
                 patch.object(runner.unittest.defaultTestLoader, 'loadTestsFromName', return_value=suite), \
                 patch.object(runner.subprocess, 'run', side_effect=child), \
                 patch.object(sys, 'argv', ['verify_interpreter_stack.py', '--out', str(out)]), \
                 patch.object(sys, 'path', list(sys.path)), contextlib.redirect_stdout(io.StringIO()):
                code = runner.main()
            report = json.loads((out/'report.json').read_text(encoding='utf-8'))
            self.assertEqual(calls, ['fixture.StackTests.a', 'fixture.StackTests.b', 'fixture.StackTests.c'])
            self.assertEqual(report['planned'], calls)
            self.assertEqual([a['case'] for a in report['attempts']], calls)
            self.assertEqual(len(report['attempts']), 3)
            self.assertTrue(all(a['passed'] for a in report['attempts'][1:]))
            logs = {}
            for index, attempt in enumerate(report['attempts']):
                for suffix in ('stdout', 'stderr'):
                    data = (out/f'{index:03d}.{suffix}').read_bytes()
                    self.assertEqual(attempt[suffix+'_sha256'], hashlib.sha256(data).hexdigest())
                    logs[index, suffix] = data
            return code, report, logs

    def rejected(self, **kwargs):
        code, report, logs = self.run_scenario(**kwargs)
        self.assertEqual(code, 1)
        self.assertFalse(report['passed'])
        return report, logs

    def test_complete_real_receipt_contract_can_pass(self):
        code, report, _ = self.run_scenario()
        self.assertEqual(code, 0)
        self.assertTrue(report['passed'])
        self.assertEqual(report['inputs'], report['inputs_after'])

    def test_startup_failure_removes_stale_receipt_and_keeps_remaining_plan(self):
        report, logs = self.rejected(first='startup')
        first = report['attempts'][0]
        self.assertIsNone(first['returncode'])
        self.assertFalse(first['timeout'])
        self.assertIn('OSError: controlled spawn failure', first['error'])
        self.assertEqual(logs[0, 'stdout'], b'')
        self.assertEqual(logs[0, 'stderr'], b'')

    def test_timeout_retains_both_partial_logs_and_keeps_remaining_plan(self):
        report, logs = self.rejected(first='timeout')
        self.assertTrue(report['attempts'][0]['timeout'])
        self.assertIsNone(report['attempts'][0]['returncode'])
        self.assertEqual(logs[0, 'stdout'], b'partial stdout\n')
        self.assertEqual(logs[0, 'stderr'], b'partial stderr\n')

    def test_nonzero_exit_with_green_receipt_is_failure_and_hex_is_preserved(self):
        report, _ = self.rejected(first='nonzero')
        first = report['attempts'][0]
        self.assertEqual(first['returncode'], -1073741571)
        self.assertEqual(first['returncode_hex'], '0xc00000fd')
        self.assertTrue(first['result']['passed'])
        self.assertFalse(first['passed'])

    def test_missing_receipt_is_failure_despite_zero_exit(self):
        report, _ = self.rejected(first='missing')
        self.assertEqual(report['attempts'][0]['returncode'], 0)
        self.assertFalse(report['attempts'][0]['passed'])

    def test_green_flag_cannot_hide_skip_errors_or_wrong_test_inventory(self):
        for mutation in ({'skipped': [['case', 'not available']]}, {'tests_run': 0},
                         {'tests_run': 2}, {'tests_run': True}, {'errors': 1},
                         {'failures': 1}, {'errors': False}, {'failures': False},
                         {'skipped': None}, {'case': 'different.case'}, {'passed': 1}):
            with self.subTest(mutation=mutation):
                self.rejected(mutate_receipt=mutation)

    def test_malformed_receipt_retains_logs_and_keeps_remaining_plan(self):
        report, logs = self.rejected(first='malformed')
        self.assertIn('JSONDecodeError', report['attempts'][0]['error'])
        self.assertEqual(logs[0, 'stdout'], b'child stdout\n')
        self.assertEqual(logs[0, 'stderr'], b'child stderr\n')

    def test_deleted_source_writes_final_failed_report(self):
        report, _ = self.rejected(drift='deleted')
        self.assertTrue(all(a['passed'] for a in report['attempts']))
        self.assertIsNone(report['inputs_after'])
        self.assertIn('FileNotFoundError', report['input_error'])

    def test_source_drift_fails_even_when_every_test_passes(self):
        report, _ = self.rejected(drift=True)
        self.assertTrue(all(a['passed'] for a in report['attempts']))
        self.assertNotEqual(report['inputs'], report['inputs_after'])


if __name__ == '__main__':
    unittest.main()
