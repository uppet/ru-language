"""Synthetic runner/schema tests, never real stage3/LLVM14 acceptance evidence."""
import copy
from contextlib import contextmanager
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import verify_bootstrap_dense_ci as gate


class DenseCiEvidenceTests(unittest.TestCase):
    def good(self, kind='frontend'):
        names = gate.required_cases(kind)
        return {'kind':kind, 'planned':names,
                'records':[{'id':name,'status':'passed'} for name in names],
                'executed':len(names),'skipped':0,'failures':0,'errors':0,'runner_success':True}

    def test_exact_nonempty_required_inventories(self):
        self.assertEqual({key:len(gate.required_cases(key)) for key in gate.REQUIRED},
                         {'frontend':15,'runtime':6,'windows':2})
        for kind in gate.REQUIRED:
            names = gate.required_cases(kind)
            gate.require_cases(names, kind)
            for invalid in ([], names[:-1], names+names[:1], names+['extra.case']):
                with self.subTest(kind=kind, invalid=invalid), self.assertRaises(RuntimeError):
                    gate.require_cases(invalid, kind)

    def test_synthetic_pass_only_validates_result_shape(self):
        for kind in gate.REQUIRED: gate.validate_results(self.good(kind), kind)

    def test_counts_flags_and_kind_must_match(self):
        for key, value in [('kind','runtime'),('planned',[]),('executed',14),('executed',True),
                           ('skipped',1),('skipped',False),('failures',1),('errors',1),
                           ('runner_success',False),('runner_success',1)]:
            report = self.good(); report[key] = value
            with self.subTest(key=key,value=value), self.assertRaises(RuntimeError):
                gate.validate_results(report,'frontend')
        for key in ('kind','planned','records','executed','skipped','failures','errors','runner_success'):
            report = self.good(); del report[key]
            with self.subTest(missing=key), self.assertRaises(RuntimeError):
                gate.validate_results(report,'frontend')

    def test_every_case_passes_once_no_missing_duplicate_or_xfail(self):
        mutations = [lambda rows: rows.pop(), lambda rows: rows.append(copy.deepcopy(rows[0])),
                     lambda rows: rows[0].update(id='invented.case')]
        mutations += [lambda rows, status=status: rows[0].update(status=status)
                      for status in ('running','skipped','failed','error','expected-failure','unexpected-success')]
        for mutate in mutations:
            report = self.good(); mutate(report['records'])
            with self.assertRaises(RuntimeError): gate.validate_results(report,'frontend')

    def run_cases(self, cls):
        return unittest.TextTestRunner(stream=io.StringIO(),resultclass=gate.EvidenceResult).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(cls))

    def test_subtest_failure_cannot_later_be_recorded_passed(self):
        class Cases(unittest.TestCase):
            def test_example(self):
                with self.subTest(value=1): self.assertEqual(1,2)
                with self.subTest(value=2): self.assertEqual(2,2)
        result = self.run_cases(Cases)
        self.assertEqual(result.testsRun,1)
        self.assertEqual([row['status'] for row in result.records],['failed-subtest'])
        self.assertFalse(result.wasSuccessful())

    def test_skip_expected_failure_and_unexpected_success_are_not_passes(self):
        class Cases(unittest.TestCase):
            @unittest.skip('synthetic skip')
            def test_skip(self): pass
            @unittest.expectedFailure
            def test_xfail(self): self.fail('synthetic expected failure')
            @unittest.expectedFailure
            def test_xpass(self): pass
        result = self.run_cases(Cases)
        self.assertEqual(sorted(row['status'] for row in result.records),
                         ['expected-failure','skipped','unexpected-success'])

    def test_setup_class_failure_cannot_disappear(self):
        class Cases(unittest.TestCase):
            @classmethod
            def setUpClass(cls): raise RuntimeError('required tool missing')
            def test_case(self): pass
        result = self.run_cases(Cases)
        self.assertEqual(result.testsRun,0)
        self.assertEqual(len(result.errors),1)
        self.assertEqual(result.records[0]['status'],'error')

    def test_single_success_record(self):
        class Cases(unittest.TestCase):
            def test_case(self): pass
        result = self.run_cases(Cases)
        self.assertEqual(result.testsRun,1)
        self.assertEqual(result.records,[{'id':Cases('test_case').id(),'status':'passed'}])

    def test_failed_preflight_invalidates_old_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp).resolve()
            output = directory/'dense-frontend-tests.json'
            output.write_text('{"complete":true}', encoding='utf-8')
            with patch.object(gate.native,'stage3',side_effect=RuntimeError('missing new stage3')):
                with self.assertRaisesRegex(RuntimeError,'missing new stage3'):
                    gate.tests(directory,'frontend')
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertIs(report['complete'],False)
            self.assertEqual(report['status'],'failed')
            self.assertIn('missing new stage3',report['error'])

    def test_combined_failure_cannot_leave_old_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp).resolve()
            output = directory/'dense-verification.json';output.write_text('{"complete":true}', encoding='utf-8')
            with patch.object(gate.native,'stage3',side_effect=RuntimeError('missing')):
                with self.assertRaises(RuntimeError): gate.combined(directory)
            self.assertIs(json.loads(output.read_text(encoding='utf-8'))['complete'],False)

    def test_real_artifact_inventory_must_be_nonempty_and_changes_are_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp).resolve()
            with self.assertRaises(RuntimeError): gate.artifact_hashes(directory)
            output = directory/'program';output.write_bytes(b'not-real-execution-evidence')
            before = gate.artifact_hashes(directory)
            output.write_bytes(b'changed')
            self.assertNotEqual(before,gate.artifact_hashes(directory))
            output.unlink()
            with self.assertRaises(RuntimeError): gate.artifact_hashes(directory)

    def test_m4_source_inventory_already_covers_new_production_files(self):
        from tools.bootstrap_verify import input_paths
        paths = set(input_paths())
        for name in ('bootstrap/dense_emit.ru','bootstrap/dense_plan.ru','bootstrap/dense_bridge.ru',
                     'rulang/bootstrap_dense_runtime.h','tools/bootstrap_dense_protocol.py'):
            self.assertIn(gate.ROOT/name,paths)

    def test_windows_required_gate_is_not_skip_on_linux(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(gate.sys,'platform','linux'):
            with self.assertRaisesRegex(RuntimeError,'real Windows required'):
                gate.tests(Path(tmp).resolve(),'windows')
            self.assertIs(json.loads((Path(tmp).resolve()/'dense-windows-tests.json').read_text(encoding='utf-8'))['complete'],False)

    def test_clang_wrappers_cannot_satisfy_required_identity(self):
        from types import SimpleNamespace
        tc = SimpleNamespace(version='clang version 14.0.0',triple='x86_64-pc-linux-gnu',
                             clang=['python','fake-clang.py'])
        with patch.object(gate.sys,'platform','linux'), patch('rulang.llvm_toolchain.LLVMToolchain',return_value=tc):
            with self.assertRaisesRegex(RuntimeError,'wrappers'): gate.toolchain_identity()

    def test_identity_captures_clang_argv_resolved_path_and_link_flags(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp).resolve()/'synthetic-not-executed';binary.write_bytes(b'synthetic')
            tc = SimpleNamespace(version='clang version 14.0.0',triple='x86_64-pc-linux-gnu',
                                 clang=[str(binary)],link_flags=['-lm'],data_layout='synthetic',
                                 tools={name:str(binary) for name in ('llvm-as','llvm-link','opt','llvm-dis','llc')})
            with patch.object(gate.sys,'platform','linux'), patch('rulang.llvm_toolchain.LLVMToolchain',return_value=tc):
                before = gate.toolchain_identity()
                self.assertEqual(before['clang_argv'],[str(binary)])
                self.assertEqual(before['resolved_clang'],str(binary.resolve()))
                self.assertEqual(before['link_flags'],['-lm'])
                tc.link_flags.append('-other')
                self.assertNotEqual(before,gate.toolchain_identity())

    def test_legacy_ffi_scope_and_compiler_identity_remain_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            compiler = Path(tmp).resolve()/'stage3';compiler.write_bytes(b'synthetic-not-executed')
            report = dict(scope='real-stage3-frontend',compiler=str(compiler),complete=True,
                          compiler_sha256=gate.digest(compiler),skipped=0,failures=0,errors=0,
                          executed=9,planned=9)
            gate.validate_legacy(report,compiler,'frontend')
            for key,value in [('scope','synthetic'),('compiler','other-stage3'),('skipped',1),
                              ('compiler_sha256','0'*64),('executed',8),('complete',False)]:
                bad = {**report,key:value}
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    gate.validate_legacy(bad,compiler,'frontend')

    @contextmanager
    def synthetic_combined(self):
        # Deliberately mocked schema fixture, deleted immediately; no execution.
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp).resolve(); compiler = directory/'stage3'
            compiler.write_bytes(b'synthetic-only-not-executable')
            (directory/'verification.json').write_text('{}', encoding='utf-8')
            inputs = {'synthetic-input':'stable'}; tc = {'version':'synthetic-only'}
            for index,kind in enumerate(('frontend','runtime')):
                evidence = directory/('dense-'+kind+'-artifacts-'+str(index)*32)
                evidence.mkdir();(evidence/'synthetic-artifact').write_bytes(b'stable')
                report = self.good(kind)
                report.update(format=1,complete=True,platform='linux',compiler=str(compiler),
                    compiler_sha256=gate.digest(compiler),
                    bootstrap_report_sha256=gate.digest(directory/'verification.json'),
                    inputs=dict(inputs),toolchain=tc,evidence_directory=evidence.name,
                    artifacts=gate.artifact_hashes(evidence))
                (directory/('dense-'+kind+'-tests.json')).write_text(json.dumps(report), encoding='utf-8')
            old = dict(scope='real-stage3-frontend',compiler=str(compiler),complete=True,
                       compiler_sha256=gate.digest(compiler),skipped=0,failures=0,errors=0,
                       executed=9,planned=9)
            (directory/'native-frontend-tests.json').write_text(json.dumps(old), encoding='utf-8')
            with patch.object(gate.sys,'platform','linux'), \
                 patch.object(gate.native,'stage3',return_value=compiler), \
                 patch.object(gate,'toolchain_identity',return_value=tc), \
                 patch.object(gate,'evidence_inputs',side_effect=lambda kind:dict(inputs)):
                yield directory, inputs

    def test_synthetic_aggregate_baseline_validates_only_schema(self):
        with self.synthetic_combined() as (directory,inputs):
            self.assertIs(gate.combined(directory)['complete'],True)

    def test_report_hash_is_bound_to_parsed_bytes_dense_and_legacy(self):
        for filename in ('dense-frontend-tests.json','native-frontend-tests.json'):
            with self.subTest(filename=filename), self.synthetic_combined() as (directory,inputs):
                original = Path.read_bytes; changed = []
                def read_once(path):
                    raw = original(path)
                    if path == directory/filename and not changed:
                        changed.append(True)
                        path.write_bytes(b'{"unvalidated":true}')
                    return raw
                with patch.object(Path,'read_bytes',read_once):
                    with self.assertRaisesRegex(RuntimeError,'reports changed'):
                        gate.combined(directory)
                self.assertIs(json.loads((directory/'dense-verification.json').read_text(encoding='utf-8'))['complete'],False)

    def test_earlier_case_inputs_and_artifacts_are_rechecked_at_end(self):
        for which in ('input','artifact'):
            with self.subTest(which=which), self.synthetic_combined() as (directory,inputs):
                original = gate.validate_legacy
                def validate_then_mutate(*args):
                    original(*args)
                    if which == 'input': inputs['synthetic-input'] = 'changed'
                    else:
                        artifact = directory/('dense-frontend-artifacts-'+'0'*32)/'synthetic-artifact'
                        artifact.write_bytes(b'changed')
                with patch.object(gate,'validate_legacy',side_effect=validate_then_mutate):
                    with self.assertRaisesRegex(RuntimeError,'inputs/application artifacts changed'):
                        gate.combined(directory)
                self.assertIs(json.loads((directory/'dense-verification.json').read_text(encoding='utf-8'))['complete'],False)


if __name__ == '__main__': unittest.main()
