"""Rebuilt pack runner/schema regression tests; synthetic evidence is never LLVM14/Windows acceptance.

This is a newly written test revision after workspace loss, not a recovery of the
previous pack test bytes or a continuation of its test results.
"""
import copy
from contextlib import contextmanager
import io
import json
from pathlib import Path, PureWindowsPath
import tempfile
import unittest
from unittest.mock import patch

from tools import verify_bootstrap_pack_ci as gate


class PackCiEvidenceTests(unittest.TestCase):
    def test_source_inventory_keys_use_posix_under_windows_model(self):
        original = Path.relative_to
        def windows_relative(path, *others):
            return PureWindowsPath(original(path, *others).as_posix())
        for kind in ('runtime', 'windows'):
            with self.subTest(kind=kind):
                expected = gate.evidence_inputs(kind)
                with patch.object(Path, 'relative_to', windows_relative):
                    actual = gate.evidence_inputs(kind)
                self.assertEqual(actual, expected)
                self.assertIn('.github/workflows/bootstrap-argument-pack.yml', actual)
                self.assertTrue(all('\\' not in key for key in actual))

    def test_actual_required_modules_match_frozen_case_ids(self):
        import importlib.util,sys
        for kind,name in gate.MODULES.items():
            spec=importlib.util.spec_from_file_location(name,gate.ROOT/'tests'/(name+'.py'))
            module=importlib.util.module_from_spec(spec)
            # Restore only the temporary test module, not imports it causes.
            # Rolling back sys.modules leaves stale package attributes which
            # Python 3.10's string-target mock resolver can incorrectly reuse.
            missing=object();previous=sys.modules.get(name,missing)
            sys.modules[name]=module
            try:
                spec.loader.exec_module(module)
                suite=unittest.defaultTestLoader.loadTestsFromModule(module)
                gate.require_cases(list(gate.suite_cases(suite)),kind)
            finally:
                if previous is missing: sys.modules.pop(name,None)
                else: sys.modules[name]=previous

    def test_required_inventory_preserves_cold_import_module_identity(self):
        import subprocess,sys
        # A fresh interpreter makes this independent of the other unit modules'
        # import order.  No actual toolchain is instantiated by the mock check.
        script = '''
import importlib.util, sys
spec=importlib.util.spec_from_file_location('pack_import_regression',sys.argv[1])
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)
import rulang
case=module.PackCiEvidenceTests()
case.assertNotIn('rulang.llvm_toolchain',sys.modules,'fixture is not a cold import')
case.test_actual_required_modules_match_frozen_case_ids()
case.assertIs(rulang.llvm_toolchain,sys.modules.get('rulang.llvm_toolchain'),'inventory erased a dependency but retained its package attribute')
case.test_clang_wrappers_cannot_satisfy_required_identity()
print('cold import identity and constructor interception verified')
'''
        result=subprocess.run([sys.executable,'-B','-c',script,str(Path(__file__).resolve())],
                              cwd=gate.ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(result.stdout,'cold import identity and constructor interception verified\n')
        self.assertEqual(result.stderr,'')

    def test_isolated_branch_and_exact_commit_required(self):
        with patch.dict(gate.os.environ,{'GITHUB_REF':'refs/heads/feature/bootstrap-argument-pack-20261023','GITHUB_SHA':'a'*40}), patch.object(gate.subprocess,'check_output',return_value='a'*40+'\n'):
            self.assertEqual(gate.checkout_identity(),'a'*40)
            with patch.dict(gate.os.environ,{'GITHUB_REF':'refs/heads/main'}),self.assertRaises(RuntimeError):gate.checkout_identity()
            with patch.dict(gate.os.environ,{'GITHUB_SHA':'b'*40}),self.assertRaises(RuntimeError):gate.checkout_identity()

    def good(self, kind='runtime'):
        names = gate.required_cases(kind)
        return {'kind':kind, 'planned':names,
                'records':[{'id':name,'status':'passed'} for name in names],
                'executed':len(names),'skipped':0,'failures':0,'errors':0,'runner_success':True}

    def test_exact_nonempty_required_inventories(self):
        self.assertEqual({key:len(gate.required_cases(key)) for key in gate.REQUIRED},
                         {'runtime':71,'windows':1})
        for kind in gate.REQUIRED:
            names = gate.required_cases(kind)
            gate.require_cases(names, kind)
            for invalid in ([], names[:-1], names+names[:1], names+['extra.case']):
                with self.subTest(kind=kind, invalid=invalid), self.assertRaises(RuntimeError):
                    gate.require_cases(invalid, kind)

    def test_synthetic_pass_only_validates_result_shape(self):
        for kind in gate.REQUIRED: gate.validate_results(self.good(kind), kind)

    def test_counts_flags_and_kind_must_match(self):
        for key, value in [('kind','windows'),('planned',[]),('executed',14),('executed',True),
                           ('skipped',1),('skipped',False),('failures',1),('errors',1),
                           ('runner_success',False),('runner_success',1)]:
            report = self.good(); report[key] = value
            with self.subTest(key=key,value=value), self.assertRaises(RuntimeError):
                gate.validate_results(report,'runtime')
        for key in ('kind','planned','records','executed','skipped','failures','errors','runner_success'):
            report = self.good(); del report[key]
            with self.subTest(missing=key), self.assertRaises(RuntimeError):
                gate.validate_results(report,'runtime')

    def test_every_case_passes_once_no_missing_duplicate_or_xfail(self):
        mutations = [lambda rows: rows.pop(), lambda rows: rows.append(copy.deepcopy(rows[0])),
                     lambda rows: rows[0].update(id='invented.case')]
        mutations += [lambda rows, status=status: rows[0].update(status=status)
                      for status in ('running','skipped','failed','error','expected-failure','unexpected-success')]
        for mutate in mutations:
            report = self.good(); mutate(report['records'])
            with self.assertRaises(RuntimeError): gate.validate_results(report,'runtime')

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
            output = directory/'pack-runtime-tests.json'
            output.write_text('{"complete":true}', encoding='utf-8')
            with patch.object(gate,'checkout_identity',return_value='a'*40), patch.object(gate.native,'stage3',side_effect=RuntimeError('missing new stage3')):
                with self.assertRaisesRegex(RuntimeError,'missing new stage3'):
                    gate.tests(directory,'runtime')
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertIs(report['complete'],False)
            self.assertEqual(report['status'],'failed')
            self.assertIn('missing new stage3',report['error'])

    def test_combined_failure_cannot_leave_old_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp).resolve()
            output = directory/'pack-verification.json';output.write_text('{"complete":true}', encoding='utf-8')
            (directory/'verification.json').write_text('{"synthetic":true}',encoding='utf-8')
            with patch.object(gate,'checkout_identity',return_value='a'*40) as checkout, \
                    patch.object(gate.native,'stage3',side_effect=RuntimeError('missing new stage3')) as stage3:
                with self.assertRaisesRegex(RuntimeError,'^missing new stage3$'):
                    gate.combined(directory)
                checkout.assert_called_once_with()
                stage3.assert_called_once_with(directory)
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
        for name in ('bootstrap/compiler.ru','rulang/llvm_compiler.py'):
            self.assertIn(gate.ROOT/name,paths)

    def test_windows_required_gate_is_not_skip_on_linux(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(gate.sys,'platform','linux'):
            with self.assertRaisesRegex(RuntimeError,'real Windows required'):
                gate.tests(Path(tmp).resolve(),'windows')
            self.assertIs(json.loads((Path(tmp).resolve()/'pack-windows-tests.json').read_text(encoding='utf-8'))['complete'],False)

    def test_clang_wrappers_cannot_satisfy_required_identity(self):
        from types import SimpleNamespace
        tc = SimpleNamespace(version='clang version 14.0.0',triple='x86_64-pc-linux-gnu',
                             clang=['python','fake-clang.py'])
        with patch.object(gate.sys,'platform','linux'), patch('rulang.llvm_toolchain.LLVMToolchain',return_value=tc) as constructor:
            with self.assertRaisesRegex(RuntimeError,'wrappers'): gate.toolchain_identity()
            constructor.assert_called_once_with()

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

    def test_exact_source_inventory_includes_implementations_and_native_fixtures(self):
        runtime = gate.evidence_inputs('runtime')
        windows = gate.evidence_inputs('windows')
        self.assertEqual(len(runtime), 31)
        self.assertEqual(len(windows), 34)
        self.assertEqual(set(runtime), set(gate.INPUT_FILES))
        self.assertEqual(set(windows)-set(runtime), {
            'tests/fixtures/slot_reuse_native/main.ru',
            'tests/fixtures/slot_reuse_native/panic_module.ru',
            'tests/fixtures/native/c_backend_bridge.c'})
        self.assertEqual(gate.unit_inputs(), windows)
        for name in ('bootstrap/compiler.ru','rulang/llvm_compiler.py',
                     'tools/verify_bootstrap_pack_ci.py','tools/bootstrap_pack_artifact.py',
                     'tools/bootstrap_pack_build.py','tools/measure_bootstrap_packs.py'):
            self.assertIn(name, gate.unit_inputs())

    def test_missing_source_inventory_member_is_rejected(self):
        original = Path.is_file
        required = gate.ROOT/'bootstrap/compiler.ru'
        def missing(path):
            return False if path == required else original(path)
        with patch.object(Path,'is_file',missing):
            for method in (lambda: gate.evidence_inputs('runtime'), gate.unit_inputs):
                with self.assertRaisesRegex(RuntimeError,'input missing'):
                    method()

    def test_unit_discovery_matches_exact_fixed_modules_without_execution(self):
        expected=[]
        for name in gate.UNIT_FILES:
            suite=unittest.defaultTestLoader.discover(str(gate.ROOT/'tests'),pattern=name)
            expected.extend(gate.suite_cases(suite))
        self.assertTrue(expected)
        self.assertFalse(any('_FailedTest' in name for name in expected),expected)
        self.assertEqual(len(expected),len(set(expected)))
        self.assertEqual(gate.unit_cases(),sorted(expected))
        self.assertEqual(set(gate.UNIT_FILES),{
            'test_llvm_argument_pack.py','test_bootstrap_pack_ci.py',
            'test_bootstrap_pack_artifact.py','test_bootstrap_pack_build.py',
            'test_bootstrap_pack_measurement.py','test_bootstrap_pack_workflow.py'})

    def test_unit_runner_invalidates_success_and_rejects_changed_execution_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp).resolve()
            report=directory/'pack-unit-tests.json'
            report.write_text('{"complete":true}',encoding='utf-8')
            with patch.object(gate,'unit_inputs',return_value={'synthetic':'hash'}), \
                 patch.object(gate,'unit_cases',return_value=['expected.case']), \
                 patch.object(unittest.defaultTestLoader,'discover',return_value=unittest.TestSuite()), \
                 patch('builtins.print'):
                with self.assertRaisesRegex(RuntimeError,'execution differs from fixed inventory'):
                    gate.units(directory)
            refused=json.loads(report.read_bytes())
            self.assertIs(refused['complete'],False)
            self.assertEqual(refused['log_sha256'],gate.digest(directory/'pack-unit-tests.log'))

    @contextmanager
    def synthetic_units(self):
        # Full real source hashes and real case inventory, but fabricated outcomes.
        # This fixture tests validation shape only and is never persisted as proof.
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp).resolve()
            (directory/'pack-unit-tests.log').write_bytes(b'synthetic-only unit log')
            planned=gate.unit_cases()
            report=dict(complete=True,inputs=gate.unit_inputs(),planned=planned,
                records=[{'id':name,'status':'passed'} for name in planned],
                executed=len(planned),skipped=0,failures=0,errors=0,
                log_sha256=gate.digest(directory/'pack-unit-tests.log'))
            yield directory,report

    def test_units_require_real_case_inventory_not_self_consistent_invention(self):
        with self.synthetic_units() as (directory,report):
            gate.validate_units(report,directory)
            for planned in (['invented.single'], [], report['planned'][:-1],
                            report['planned']+[report['planned'][0]]):
                bad={**report,'planned':planned,'executed':len(planned),
                     'records':[{'id':name,'status':'passed'} for name in planned]}
                with self.subTest(planned_count=len(planned)),self.assertRaisesRegex(RuntimeError,'planned inventory'):
                    gate.validate_units(bad,directory)

    def test_unit_counts_require_integers_not_bools(self):
        with self.synthetic_units() as (directory,report):
            for key in ('executed','skipped','failures','errors'):
                for value in (False, True, 0.0, '0'):
                    with self.subTest(key=key,value=value),self.assertRaisesRegex(RuntimeError,'counts must be integers'):
                        gate.validate_units({**report,key:value},directory)

    def test_unit_implementation_hash_records_and_log_are_bound(self):
        with self.synthetic_units() as (directory,report):
            for path in ('bootstrap/compiler.ru','tools/verify_bootstrap_pack_ci.py'):
                bad=copy.deepcopy(report);bad['inputs'][path]='0'*64
                with self.subTest(path=path),self.assertRaisesRegex(RuntimeError,'stale or incomplete'):
                    gate.validate_units(bad,directory)
            for mutate in (lambda r:r['records'].pop(),
                           lambda r:r['records'][0].update(status='skipped'),
                           lambda r:r.update(executed=r['executed']-1)):
                bad=copy.deepcopy(report);mutate(bad)
                with self.assertRaisesRegex(RuntimeError,'cases absent, failed or skipped'):
                    gate.validate_units(bad,directory)
            (directory/'pack-unit-tests.log').write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError,'log changed'):
                gate.validate_units(report,directory)

    @contextmanager
    def synthetic_combined(self):
        # Mock only execution-dependent identity/proof discovery. All report shape,
        # byte-binding, stale-success and final-recheck logic is the real runner.
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp).resolve();compiler=directory/'stage3'
            compiler.write_bytes(b'synthetic-only-not-executable')
            generation={'synthetic-generation':True}
            (directory/'verification.json').write_text(json.dumps({'bootstrap':generation}),encoding='utf-8')
            (directory/'report.json').write_text(json.dumps(generation),encoding='utf-8')
            (directory/'slot-unit-tests.json').write_text('{"complete":true}',encoding='utf-8')
            inputs={'synthetic-input':'stable'};unit_inputs={'synthetic-unit-input':'stable'}
            tc={'version':'synthetic-only'}
            evidence=directory/('pack-runtime-artifacts-'+'0'*32)
            evidence.mkdir();(evidence/'synthetic-artifact').write_bytes(b'stable')
            report=self.good('runtime')
            report.update(format=1,complete=True,platform='linux',commit='a'*40,compiler=str(compiler),
                compiler_sha256=gate.digest(compiler),bootstrap_report_sha256=gate.digest(directory/'verification.json'),
                inputs=dict(inputs),toolchain=tc,evidence_directory=evidence.name,artifacts=gate.artifact_hashes(evidence))
            (directory/'pack-runtime-tests.json').write_text(json.dumps(report),encoding='utf-8')
            old=dict(scope='real-stage3-frontend',compiler=str(compiler),complete=True,
                compiler_sha256=gate.digest(compiler),skipped=0,failures=0,errors=0,executed=9,planned=9)
            (directory/'native-frontend-tests.json').write_text(json.dumps(old),encoding='utf-8')
            (directory/'slot-runtime-tests.json').write_text('{"synthetic":true}',encoding='utf-8')
            (directory/'pack-unit-tests.log').write_bytes(b'synthetic portable log')
            units=dict(complete=True,inputs=dict(unit_inputs),planned=['synthetic.unit'],
                records=[{'id':'synthetic.unit','status':'passed'}],executed=1,skipped=0,failures=0,errors=0,
                log_sha256=gate.digest(directory/'pack-unit-tests.log'))
            (directory/'pack-unit-tests.json').write_text(json.dumps(units),encoding='utf-8')
            def legacy_combined(path):
                frozen={name:gate.digest(directory/name) for name in
                        ('native-frontend-tests.json','slot-runtime-tests.json')}
                aggregate=dict(complete=True,commit='a'*40,compiler_sha256=gate.digest(compiler),reports=frozen)
                (directory/'slot-verification.json').write_text(json.dumps(aggregate),encoding='utf-8')
                return aggregate
            with patch.object(gate.sys,'platform','linux'), \
                 patch.object(gate.native,'stage3',return_value=compiler), \
                 patch.object(gate,'checkout_identity',return_value='a'*40), \
                 patch.object(gate,'toolchain_identity',return_value=tc), \
                 patch.object(gate,'evidence_inputs',side_effect=lambda kind:dict(inputs)), \
                 patch.object(gate,'unit_inputs',side_effect=lambda:dict(unit_inputs)), \
                 patch.object(gate,'unit_cases',return_value=['synthetic.unit']), \
                 patch.object(gate.slot,'combined',side_effect=legacy_combined):
                yield directory,inputs,unit_inputs

    def assert_pending(self, directory):
        self.assertIs(json.loads((directory/'pack-verification.json').read_text(encoding='utf-8'))['complete'],False)

    def test_synthetic_aggregate_baseline_validates_only_schema(self):
        with self.synthetic_combined() as (directory,inputs,unit_inputs):
            result=gate.combined(directory)
            self.assertIs(result['complete'],True)
            self.assertEqual(result['required_kinds'],['runtime'])
            self.assertEqual(result['unit_log_sha256'],gate.digest(directory/'pack-unit-tests.log'))
            for name,identity in result['reports'].items():
                self.assertEqual(gate.digest(directory/name),identity)

    def test_validated_report_byte_hashes_are_not_rebaselined_after_parse(self):
        for filename in ('pack-runtime-tests.json','native-frontend-tests.json',
                         'slot-runtime-tests.json','pack-unit-tests.json','slot-unit-tests.json','report.json'):
            with self.subTest(filename=filename),self.synthetic_combined() as (directory,inputs,unit_inputs):
                original=Path.read_bytes;changed=[]
                def read_once(path):
                    raw=original(path)
                    if path==directory/filename and not changed:
                        changed.append(True);path.write_bytes(b'{"unvalidated":true}')
                    return raw
                with patch.object(Path,'read_bytes',read_once):
                    with self.assertRaisesRegex(RuntimeError,'referenced report changed'):
                        gate.combined(directory)
                self.assertTrue(changed);self.assert_pending(directory)

    def test_original_aggregate_bytes_must_match_validated_return_value(self):
        with self.synthetic_combined() as (directory,inputs,unit_inputs):
            original=gate.slot.combined.side_effect
            def altered(path):
                validated=original(path)
                (directory/'slot-verification.json').write_bytes(b'{"unvalidated":true}')
                return validated
            with patch.object(gate.slot,'combined',side_effect=altered):
                with self.assertRaisesRegex(RuntimeError,'aggregate bytes changed'):
                    gate.combined(directory)
            self.assert_pending(directory)

    def test_generation_report_must_equal_verified_bootstrap_payload(self):
        with self.synthetic_combined() as (directory,inputs,unit_inputs):
            (directory/'report.json').write_text('{"different":true}',encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError,'generation report differs'):
                gate.combined(directory)
            self.assert_pending(directory)

    def test_verification_bytes_are_rechecked_immediately_after_native_validation(self):
        with self.synthetic_combined() as (directory,inputs,unit_inputs):
            compiler=directory/'stage3'
            def changed(path):
                (directory/'verification.json').write_bytes(b'{"unvalidated":true}')
                return compiler
            with patch.object(gate.native,'stage3',side_effect=changed):
                with self.assertRaisesRegex(RuntimeError,'verified bootstrap bytes changed'):
                    gate.combined(directory)
            self.assert_pending(directory)

    def test_case_inputs_and_artifacts_are_rechecked_after_later_validation(self):
        for which in ('input','artifact'):
            with self.subTest(which=which),self.synthetic_combined() as (directory,inputs,unit_inputs):
                original=gate.validate_units
                def checked_then_changed(*args):
                    original(*args)
                    if which=='input': inputs['synthetic-input']='changed'
                    else: (directory/('pack-runtime-artifacts-'+'0'*32)/'synthetic-artifact').write_bytes(b'changed')
                with patch.object(gate,'validate_units',side_effect=checked_then_changed):
                    with self.assertRaisesRegex(RuntimeError,'sources/artifacts changed'):
                        gate.combined(directory)
                self.assert_pending(directory)

    def test_unit_inputs_and_log_are_rechecked_after_unit_validation(self):
        for which in ('input','log'):
            with self.subTest(which=which),self.synthetic_combined() as (directory,inputs,unit_inputs):
                original=gate.validate_units
                def checked_then_changed(*args):
                    original(*args)
                    if which=='input': unit_inputs['synthetic-unit-input']='changed'
                    else: (directory/'pack-unit-tests.log').write_bytes(b'changed')
                with patch.object(gate,'validate_units',side_effect=checked_then_changed):
                    with self.assertRaisesRegex(RuntimeError,'portable inputs/log changed'):
                        gate.combined(directory)
                self.assert_pending(directory)

    def test_required_artifacts_cannot_escape_owned_directory(self):
        with self.synthetic_combined() as (directory,inputs,unit_inputs):
            path=directory/'pack-runtime-tests.json';report=json.loads(path.read_bytes())
            report['evidence_directory']='../escape'
            path.write_text(json.dumps(report),encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError,'artifact directory identity invalid'):
                gate.combined(directory)
            self.assert_pending(directory)


if __name__ == '__main__': unittest.main()
