"""CI gate unit tests are synthetic; never substitute for its 105 real cases."""
import json
from pathlib import Path
import tempfile
import unittest

from tools import verify_bootstrap_native_ci as gate


class NativeCiEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.compiler = self.directory/('stage3.exe' if gate.sys.platform == 'win32' else 'stage3')
        self.compiler.write_bytes(b'synthetic-test-only')
        from tools.bootstrap_verify import snapshots, input_paths
        planned = gate.planned_cases()
        for path in gate.artifact_paths(self.directory): path.write_bytes(b'synthetic-test-only')
        self.report = {'m4_complete':True, 'platform':gate.sys.platform, 'tests_run':105,
                       'skipped':0, 'failures':0, 'errors':0, 'gates':dict.fromkeys(gate.GATES, True),
                       'planned_cases_by_stage':{str(i):planned for i in (1,2,3)},
                       'stages':{str(i):[{'status':'passed', 'case':name, 'stage':i,
                            'id':'_ru_bootstrap_acceptance.'+cls+'.'+name} for name in planned]
                            for i,cls in ((1,'BootstrapStage1Tests'),(2,'BootstrapStage2Tests'),(3,'BootstrapTests'))},
                       'artifact_sha256':{str(path):gate.digest(path) for path in gate.artifact_paths(self.directory)},
                       'input_sha256':snapshots(input_paths())}

    def write_report(self):
        (self.directory/'verification.json').write_text(json.dumps(self.report), encoding='utf-8')

    def test_complete_synthetic_report_validates_identity_only(self):
        self.write_report()
        self.assertEqual(gate.stage3(self.directory), self.compiler)

    def test_incomplete_skipped_or_empty_generations_fail(self):
        for field, value in [('m4_complete',False), ('tests_run',104), ('skipped',1),
                             ('failures',1), ('errors',1), ('gates',{}), ('input_sha256',{})]:
            with self.subTest(field=field):
                old = self.report[field]
                self.report[field] = value
                self.write_report()
                with self.assertRaises(RuntimeError): gate.stage3(self.directory)
                self.report[field] = old
        self.report['stages']['2'].pop()
        self.write_report()
        with self.assertRaises(RuntimeError): gate.stage3(self.directory)

    def test_mutated_stage3_is_rejected(self):
        self.write_report()
        self.compiler.write_bytes(b'changed')
        with self.assertRaises(RuntimeError): gate.stage3(self.directory)

    def test_mutated_helper_identity_is_rejected(self):
        self.report['input_sha256']['bootstrap/native_emit.ru'] = '0'*64
        self.write_report()
        with self.assertRaises(RuntimeError): gate.stage3(self.directory)

    def test_skipped_stage_case_is_rejected(self):
        self.report['stages']['3'][0]['status'] = 'skipped'
        self.write_report()
        with self.assertRaises(RuntimeError): gate.stage3(self.directory)

    def test_missing_gate_artifact_and_duplicate_cases_fail(self):
        self.report['gates'].pop('source_ir_and_abi_fixed_point')
        self.write_report()
        with self.assertRaises(RuntimeError): gate.stage3(self.directory)
        self.report['gates']['source_ir_and_abi_fixed_point'] = True
        key, value = self.report['artifact_sha256'].popitem()
        self.write_report()
        with self.assertRaises(RuntimeError): gate.stage3(self.directory)
        self.report['artifact_sha256'][key] = value
        self.report['stages']['1'][0] = self.report['stages']['1'][1]
        self.write_report()
        with self.assertRaises(RuntimeError): gate.stage3(self.directory)

    def test_missing_native_runtime_class_cannot_pass_with_portable_gates_only(self):
        for kind, names in gate.REQUIRED_NATIVE_CASES.items():
            gate.require_native_cases(names, kind)
            for invalid in ([], names[:2], names+names[:1]):
                with self.subTest(kind=kind, size=len(invalid)), self.assertRaises(RuntimeError):
                    gate.require_native_cases(invalid, kind)


class NativeSuiteIdentityTests(unittest.TestCase):
    def test_actual_runner_rejects_skips_expected_failures_and_unexpected_successes(self):
        from unittest.mock import patch
        for behavior in ('pass', 'skip', 'xfail', 'xpass', 'failure', 'error'):
            class Synthetic(unittest.TestCase):
                def test_case(self):
                    if behavior == 'skip': self.skipTest('negative control')
                    if behavior in ('xfail', 'failure'): self.fail('negative control')
                    if behavior == 'error': raise RuntimeError('negative control')
            if behavior in ('xfail', 'xpass'):
                Synthetic.test_case = unittest.expectedFailure(Synthetic.test_case)
            with self.subTest(behavior=behavior), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                compiler = directory/'stage3'; compiler.write_bytes(b'synthetic-only')
                suite = unittest.defaultTestLoader.loadTestsFromTestCase(Synthetic)
                names = list(gate.suite_cases(suite))
                with patch.dict(gate.REQUIRED_NATIVE_CASES, {'frontend':names}):
                    if behavior == 'pass':
                        report = gate.run_native_suite(suite, directory, 'frontend', compiler)
                        self.assertEqual(report['planned_ids'], report['executed_ids'])
                    else:
                        with self.assertRaises(RuntimeError):
                            gate.run_native_suite(suite, directory, 'frontend', compiler)
                report = json.loads((directory/'native-frontend-tests.json').read_text())
                self.assertEqual(report['complete'], behavior == 'pass')

    def test_actual_runner_rejects_executed_identity_substitution(self):
        from unittest.mock import patch
        class Synthetic(unittest.TestCase):
            def test_case(self): pass
        class WrongIdentity(gate.IdentityResult):
            def startTest(self, test):
                super().startTest(test)
                self.executed_ids[-1] += '_wrong'
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); compiler = directory/'stage3'
            compiler.write_bytes(b'synthetic-only')
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(Synthetic)
            with patch.dict(gate.REQUIRED_NATIVE_CASES, {'frontend':list(gate.suite_cases(suite))}), patch.object(gate, 'IdentityResult', WrongIdentity):
                with self.assertRaises(RuntimeError):
                    gate.run_native_suite(suite, directory, 'frontend', compiler)

class CurrentEditorOracleTests(unittest.TestCase):
    def test_exact_graph_rejects_missing_duplicate_and_changed_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = []
            for index in range(26):
                path = root/(str(index)+'.ru'); path.write_bytes(str(index).encode())
                rows.append({'scope':'app', 'path':path.name, 'sha256':gate.digest(path)})
            matrix = {'modules':rows}
            dependencies = [{'path':str(root/row['path']), 'sha256':row['sha256']} for row in rows]
            gate.require_current_graph(matrix, root, dependencies)
            for invalid in (dependencies[:-1], dependencies[:-1]+dependencies[:1],
                            [dict(row, sha256='0'*64) for row in dependencies]):
                with self.assertRaises(RuntimeError): gate.require_current_graph(matrix, root, invalid)
            with self.assertRaises(RuntimeError):
                gate.require_current_graph({'modules':rows[:-1]+rows[:1]}, root, dependencies)
            (root/'0.ru').write_bytes(b'changed')
            with self.assertRaises(RuntimeError): gate.require_current_graph(matrix, root, dependencies)
