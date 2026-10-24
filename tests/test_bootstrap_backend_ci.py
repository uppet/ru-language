"""Portable negative controls, not a substitute for required real LLVM14 gates."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import verify_bootstrap_backend_ci as runner


def write(path, value):
    path.write_text(json.dumps(value)+'\n',encoding='utf-8')


def valid_result(kind):
    ids=runner.required_cases(kind)
    return {'kind':kind,'planned':ids,'records':[{'id':x,'status':'passed'} for x in ids],
            'executed':len(ids),'skipped':0,'failures':0,'errors':0,'runner_success':True}


class BackendGateTests(unittest.TestCase):
    def test_exact31_and1_required(self):
        self.assertEqual(len(runner.required_cases('runtime')),31)
        self.assertEqual(len(runner.required_cases('windows')),1)
        for kind in ('runtime','windows'):runner.validate_results(valid_result(kind),kind)

    def test_missing_duplicate_extra_skip_failure_bool_count_rejected(self):
        for kind in ('runtime','windows'):
            good=valid_result(kind)
            mutations=[lambda d:d['records'].pop(),lambda d:d['records'].append(d['records'][0]),
                       lambda d:d['records'].append({'id':'extra','status':'passed'}),
                       lambda d:d.update(skipped=1),lambda d:d.update(failures=1),lambda d:d.update(errors=1),
                       lambda d:d.update(executed=True),lambda d:d.update(runner_success=False),
                       lambda d:d['records'][0].update(status='skipped')]
            for change in mutations:
                bad=deepcopy(good);change(bad)
                with self.subTest(kind=kind,change=change),self.assertRaises(RuntimeError):runner.validate_results(bad,kind)

    def test_subtest_failure_cannot_be_overwritten(self):
        class Bad(unittest.TestCase):
            def runTest(self):
                with self.subTest(one=1):self.fail('sentinel')
        result=unittest.TextTestRunner(stream=io.StringIO(),resultclass=runner.EvidenceResult).run(unittest.TestSuite([Bad()]))
        self.assertEqual(result.records[0]['status'],'failed-subtest')
        result.addSuccess(Bad())
        self.assertEqual(result.records[0]['status'],'failed-subtest')

    def test_read_report_hashes_original_bytes(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'r.json';raw=b'{ "x" : 1 }\n';p.write_bytes(raw)
            value,digest=runner.read_report(p)
            self.assertEqual(value,{'x':1});self.assertEqual(digest,hashlib.sha256(raw).hexdigest())

    def test_artifact_missing_empty_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)
            with self.assertRaises(RuntimeError):runner.artifact_hashes(p/'missing')
            with self.assertRaises(RuntimeError):runner.artifact_hashes(p)
            (p/'a').write_bytes(b'x');self.assertEqual(runner.artifact_hashes(p),{'a':runner.digest(p/'a')})
            with patch.object(Path,'is_symlink',return_value=True),self.assertRaises(RuntimeError):runner.artifact_hashes(p)

    def bootstrap_fixture(self, directory):
        paths=runner.artifact_paths(directory)
        for p in paths:p.write_bytes(b'\x7fELFfixture' if p.name in ('stage1','stage2','stage3','stage1.exe','stage2.exe','stage3.exe') else b'fixed')
        names=[f'test_{i:02}' for i in range(35)]
        from tools.bootstrap_compare import compare_native
        report={'format':1,'milestone':'M4','platform':runner.sys.platform,'m4_complete':True,'tests_run':105,
                'skipped':0,'failures':0,'errors':0,'gates':{x:True for x in runner.GATES},
                'planned_cases_by_stage':{str(i):names for i in (1,2,3)},
                'stages':{},'artifact_sha256':{str(p):runner.digest(p) for p in paths},'input_sha256':{'a':'b'}}
        for index,cls in [(1,'BootstrapStage1Tests'),(2,'BootstrapStage2Tests'),(3,'BootstrapTests')]:
            report['stages'][str(index)]=[{'id':'_ru_bootstrap_acceptance.'+cls+'.'+x,'case':x,'stage':index,'status':'passed'} for x in names]
        report['native_comparison']=compare_native(paths[1].read_bytes(),paths[2].read_bytes())
        report['bootstrap']={'fixed_point':True,'source_sha256':runner.digest(runner.ROOT/'bootstrap/compiler.ru'),
                             'triple':'test','llvm':'clang version 14.0.0','stages':[]}
        for p in paths[1:3]:report['bootstrap']['stages'].append({'binary_sha256':runner.digest(p),'source_ir_sha256':runner.digest(str(p)+'.frontend.ll'),'metadata_sha256':runner.digest(str(p)+'.metadata.c')})
        write(directory/'verification.json',report)
        return report,names

    def check_bootstrap(self,directory,names):
        with patch.object(runner,'planned_cases',return_value=names),patch('tools.bootstrap_verify.input_paths',return_value=[]),patch('tools.bootstrap_verify.snapshots',return_value={'a':'b'}):
            return runner.bootstrap_snapshot(directory)

    def test_bootstrap105_and_nine_actual_artifacts(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t).resolve();report,names=self.bootstrap_fixture(p)
            got=self.check_bootstrap(p,names);self.assertEqual(got['artifacts'],report['artifact_sha256'])

    def test_bootstrap_wrong_cases_inputs_artifacts_and_gates_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t).resolve();good,names=self.bootstrap_fixture(p)
            for change in [lambda d:d.update(tests_run=104),lambda d:d.update(skipped=1),lambda d:d.update(format=2),
                           lambda d:d['gates'].pop(next(iter(d['gates']))),lambda d:d['stages']['3'][0].update(status='skipped'),
                           lambda d:d['input_sha256'].update(a='wrong'),lambda d:d['artifact_sha256'].pop(next(iter(d['artifact_sha256']))),
                           lambda d:d['native_comparison'].update(normalized_equal=False),lambda d:d['bootstrap']['stages'][0].update(binary_sha256='wrong')]:
                bad=deepcopy(good);change(bad);write(p/'verification.json',bad)
                with self.subTest(change=change),self.assertRaises(RuntimeError):self.check_bootstrap(p,names)

    def test_bootstrap_source_and_binary_fixedpoint_recomputed(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t).resolve();good,names=self.bootstrap_fixture(p)
            file=runner.artifact_paths(p)[2];file.write_bytes(b'\x7fELFdifferent')
            good['artifact_sha256'][str(file)]=runner.digest(file);write(p/'verification.json',good)
            with self.assertRaises(RuntimeError):self.check_bootstrap(p,names)

    def combined_fixture(self,p):
        snap={'identity':'fixed'};checkout={'commit':'a'*40,'tree':'b'*40};inputs={'test':'hash'};tool={'llvm':'14'}
        for kind in ['runtime']+(['windows'] if runner.sys.platform=='win32' else []):
            folder=p/('backend-'+kind+'-artifacts-fixture');folder.mkdir();(folder/'runtime.log').write_bytes(b'PASS')
            report=valid_result(kind);report.update(complete=True,status='passed',preflight={'fixed':'preflight'},platform=runner.sys.platform,
                  checkout=checkout,bootstrap=snap,inputs=inputs,toolchain=tool,evidence_directory=folder.name,
                  artifacts=runner.artifact_hashes(folder));write(p/('backend-'+kind+'-tests.json'),report)
        return snap,checkout,inputs,tool

    def combined(self,p,values):
        snap,checkout,inputs,tool=values
        with patch.object(runner,'preflight_snapshot',return_value={'fixed':'preflight'}),patch.object(runner,'bootstrap_snapshot',return_value=snap),patch.object(runner,'checkout_identity',return_value=checkout),patch.object(runner,'evidence_inputs',return_value=inputs),patch.object(runner,'toolchain_identity',return_value=tool):runner.combined(p)

    def test_combined_requires_complete_raw_bound_reports(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);v=self.combined_fixture(p);self.combined(p,v)
            self.assertTrue(json.loads((p/'backend-acceptance.json').read_text())['complete'])
            f=p/'backend-runtime-tests.json';j=json.loads(f.read_text());j['inputs']={'other':'x'};write(f,j)
            with self.assertRaises(RuntimeError):self.combined(p,v)
            self.assertFalse(json.loads((p/'backend-acceptance.json').read_text())['complete'])

    def test_parse_then_replace_report_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);v=self.combined_fixture(p);original=runner.read_report
            def read(path):
                value=original(path);Path(path).write_bytes(b'{"unvalidated":true}');return value
            with patch.object(runner,'read_report',side_effect=read),self.assertRaises(RuntimeError):self.combined(p,v)

    def test_late_artifact_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);v=self.combined_fixture(p);original=runner.artifact_hashes;calls=[]
            def read(path):
                value=original(path);calls.append(path)
                if len(calls)==1:(path/'runtime.log').write_bytes(b'changed')
                return value
            with patch.object(runner,'artifact_hashes',side_effect=read),self.assertRaises(RuntimeError):self.combined(p,v)

    def test_later_kind_cannot_hide_prior_artifact_change(self):
        with tempfile.TemporaryDirectory() as t,patch.object(runner.sys,'platform','win32'):
            p=Path(t);v=self.combined_fixture(p);original=runner.artifact_hashes;calls=[]
            def read(path):
                value=original(path);calls.append(path)
                if len(calls)==2:(calls[0]/'runtime.log').write_bytes(b'changed-after-prior-kind')
                return value
            with patch.object(runner,'artifact_hashes',side_effect=read),self.assertRaises(RuntimeError):self.combined(p,v)

    def test_preflight_requires_actual_before_bootstrap_identity(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)
            with patch.object(runner,'checkout_identity',return_value={'commit':'a'*40}),patch.object(runner,'evidence_inputs',return_value={'source':'hash'}),patch.object(runner,'toolchain_identity',return_value={'clang':'hash'}):
                with self.assertRaises(FileNotFoundError):runner.preflight_snapshot(p)
                runner.preflight(p);before=runner.preflight_snapshot(p)
                self.assertTrue(before['report']['complete'])
                with patch.object(runner,'toolchain_identity',return_value={'clang':'changed'}),self.assertRaises(RuntimeError):runner.preflight_snapshot(p)

    def test_windows_gate_never_skips_on_wrong_platform(self):
        with tempfile.TemporaryDirectory() as t,patch.object(runner.sys,'platform','linux'),self.assertRaises(RuntimeError):runner.tests(Path(t),'windows')

    def test_checkout_requires_exact_sha_and_clean_tracked_files(self):
        with patch.dict(runner.os.environ,{'GITHUB_SHA':'a'*40}),patch.object(runner.subprocess,'check_output',side_effect=['a'*40+'\n','b'*40+'\n']),patch.object(runner.subprocess,'run',return_value=type('R',(),{'returncode':0})()):
            self.assertEqual(runner.checkout_identity(),{'commit':'a'*40,'tree':'b'*40})
        with patch.dict(runner.os.environ,{'GITHUB_SHA':'a'*40}),patch.object(runner.subprocess,'check_output',return_value='a'*40+'\n'),patch.object(runner.subprocess,'run',return_value=type('R',(),{'returncode':1})()),self.assertRaises(RuntimeError):runner.checkout_identity()
        with patch.dict(runner.os.environ,{'GITHUB_SHA':'bad'}),self.assertRaises(RuntimeError):runner.checkout_identity()

    def test_workflow_exact_required_order_and_budgets(self):
        text=(runner.ROOT/'.github/workflows/bootstrap-backend.yml').read_text(encoding='utf-8')
        required=['python tools/verify_bootstrap_backend_ci.py preflight --directory bin/bootstrap/backend',
                  'python tools/bootstrap.py verify --directory bin/bootstrap/backend',
                  'python tools/verify_bootstrap_backend_ci.py runtime --directory bin/bootstrap/backend',
                  'python tools/verify_bootstrap_backend_ci.py windows --directory bin/bootstrap/backend',
                  'python tools/verify_bootstrap_backend_ci.py combined --directory bin/bootstrap/backend']
        self.assertEqual(sorted(text.index(x) for x in required),[text.index(x) for x in required])
        self.assertIn('timeout-minutes: 45',text);self.assertIn('if: always()',text);self.assertIn('if-no-files-found: error',text)
        self.assertNotIn('continue-on-error',text);self.assertNotIn('cancel-in-progress: true',text)
        self.assertNotIn('llvm17',text.lower());self.assertNotIn('bootstrap-native',text)
        self.assertIn('GIT_CONFIG_KEY_0: core.autocrlf',text);self.assertIn('GIT_CONFIG_VALUE_0: "false"',text)

if __name__=='__main__':unittest.main()
