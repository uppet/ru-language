import importlib.util
import ast
import hashlib
import os
import json
from pathlib import Path
import tempfile
import types
import stat
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('pack_build',Path(__file__).resolve().parents[1]/'tools/bootstrap_pack_build.py')
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)

class Clock:
    def __init__(self):self.now=4.002
    def __call__(self):return self.now
    def sleep(self,n):self.now+=n

class Job:
    pid=12345
    def __init__(self, clock, stdout, stderr, *, done=1, code=0, orphan=False, stuck=False, close_error=False):
        self.clock=clock;self.done=clock()+done;self.code=code;self.orphan=orphan;self.stuck=stuck
        self.close_error=close_error;self.killed=False;self.closed=False
        stdout.write_bytes(b'owned stdout');stderr.write_bytes(b'owned stderr')
    def exit_code(self):return 1 if self.killed else (self.code if self.clock()>=self.done else None)
    def active(self):return 1 if self.stuck else (0 if self.killed else int(self.orphan or self.exit_code() is None))
    def terminate(self):self.killed=True
    def close(self):
        self.closed=True
        if self.close_error:raise OSError('close failed')

class Budgets(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.clock=Clock()
    def tearDown(self):self.temp.cleanup()
    def run_job(self, **kw):
        def factory(argv,cwd,env,out,err):
            self.job=Job(self.clock,out,err,**kw);return self.job
        return m.supervise(['python','worker'],self.root,{},self.root/'evidence',job_factory=factory,clock=self.clock,sleep=self.clock.sleep)
    def evidence(self):return json.loads((self.root/'evidence/budget.json').read_bytes())
    def test_success_tree_reaped(self):
        row=self.run_job();self.assertTrue(row['completed']);self.assertTrue(row['tree_empty']);self.assertTrue(self.job.closed)
        self.assertFalse(self.job.killed);m.verify(row['stdout']);m.verify(row['stderr'])
    def test_whole_tree_deadline_not_per_command(self):
        with self.assertRaises(ValueError):self.run_job(done=2000)
        row=self.evidence();self.assertTrue(row['timed_out']);self.assertTrue(self.job.killed)
        self.assertGreaterEqual(row['deadline_observed_monotonic'],row['deadline_monotonic']);self.assertTrue(row['process_reaped'])
    def test_root_success_does_not_hide_live_descendant(self):
        with self.assertRaises(ValueError):self.run_job(orphan=True)
        self.assertTrue(self.evidence()['timed_out']);self.assertTrue(self.job.killed)
    def test_nonzero_keeps_error(self):
        with self.assertRaises(ValueError):self.run_job(code=9)
        row=self.evidence();self.assertFalse(row['timed_out']);self.assertEqual(row['exit_code'],9);self.assertFalse(row['completed'])
    def test_cleanup_failure_never_success(self):
        with self.assertRaises(ValueError):self.run_job(close_error=True)
        self.assertEqual(self.evidence()['cleanup_errors'],['close failed'])
    def test_live_tree_after_termination_fails(self):
        with self.assertRaises(ValueError):self.run_job(done=2000,stuck=True)
        self.assertFalse(self.evidence()['tree_empty']);self.assertTrue(self.evidence()['cleanup_errors'])
    def test_creation_failure_persisted(self):
        def bad(*args):raise OSError('create failed')
        with self.assertRaises(ValueError):m.supervise([],self.root,{},self.root/'evidence',job_factory=bad,clock=self.clock,sleep=self.clock.sleep)
        self.assertEqual(self.evidence()['first_error']['message'],'create failed');self.assertFalse(self.evidence()['process_reaped'])
    def test_completion_query_crosses_original_deadline(self):
        def factory(argv,cwd,env,out,err):
            self.job=Job(self.clock,out,err,done=0)
            original=self.job.active
            def slow_query():self.clock.sleep(601);return original()
            self.job.active=slow_query
            return self.job
        with self.assertRaises(ValueError):m.supervise([],self.root,{},self.root/'evidence',job_factory=factory,clock=self.clock,sleep=self.clock.sleep)
        self.assertTrue(self.evidence()['timed_out']);self.assertFalse(self.evidence()['completed'])
    def test_creation_time_in_same_budget(self):
        def slow(argv,cwd,env,out,err):
            self.clock.sleep(601);self.job=Job(self.clock,out,err);return self.job
        with self.assertRaises(ValueError):m.supervise([],self.root,{},self.root/'evidence',job_factory=slow,clock=self.clock,sleep=self.clock.sleep)
        self.assertTrue(self.evidence()['timed_out']);self.assertTrue(self.job.killed)

class Identities(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
    def tearDown(self):self.tmp.cleanup()
    def test_same_bytes_read_and_hash(self):
        p=self.root/'a.json';p.write_bytes(b'{"v":"UTF8"}\r\n');data,row=m.read(p);self.assertEqual(row,m.identity(p));self.assertEqual(data,{'v':'UTF8'})
        p.write_bytes(b'{}')
        with self.assertRaises(ValueError):m.verify(row)
    def test_graph_normalized_and_duplicate_rejected(self):
        app=self.root/'app';lang=self.root/'language';app.mkdir();lang.mkdir();p=app/'x.ru';p.write_text('x');r=m.identity(p)
        self.assertEqual(m.normalized_graph([r],app,lang),{'app/x.ru':{'sha256':r['sha256'],'size':1}})
        with self.assertRaises(ValueError):m.normalized_graph([r,r],app,lang)
        with self.assertRaises(ValueError):m.normalized_graph([r],lang,lang)
    def test_prepared_recomposition_rejects_mutation(self):
        p=self.root/'config';p.write_bytes(b'{}');data={'schema':m.SCHEMA,'status':'prepared-diagnostic-only','config':m.identity(p),'owned_root':str(self.root),'build_budgets':{},'sources':[]}
        with patch.object(m,'assembled',return_value={**data,'unexpected':True}):
            with self.assertRaisesRegex(ValueError,'identities changed'):m.validate_prepared_data(data)
    def test_exact_language_delta_preserves_runtime(self):
        old={'runtime.c':'stable',**{key:'old' for key in m.LANGUAGE_DELTA}}
        new={'runtime.c':'stable',**{key:'new' for key in m.LANGUAGE_DELTA},**m.EMITTER_HASHES}
        m.validate_language_delta(old,new)
        for changed in ({**new,'runtime.c':'modified'}, {**new,'surprise':'new'}, {**new,'bootstrap/compiler.ru':'other'}):
            with self.assertRaises(ValueError):m.validate_language_delta(old,changed)
        with self.assertRaises(ValueError):m.validate_language_delta(old,{k:v for k,v in new.items() if k!='runtime.c'})
    def test_c_pipeline_exact_paths_and_bytes(self):
        d=self.root/'llvm';d.mkdir()
        for name in m.C_ARTIFACT_NAMES:(d/name).write_bytes(b'fixed')
        source=self.root/'probe.c';source.write_bytes(b'fixed')
        b={'data_layout':'layout','target_triple':'triple','linked_inputs':{n:m.identity(d/n) for n in ('launcher.obj','application.res')}}
        (d/'program.ll').write_bytes(b'target datalayout = "layout"\ntarget triple = "triple"\n')
        row={'binary':m.identity(d/'ru_notepad.exe')};control={'artifacts':[m.identity(d/n) for n in m.C_ARTIFACT_NAMES]};graph={'generated_c':m.identity(source)}
        m.validate_c_outputs(d,row,control,graph,b)
        with self.assertRaises(ValueError):m.validate_c_outputs(d,{'binary':m.identity(d/'program.exe')},control,graph,b)
        with self.assertRaises(ValueError):m.validate_c_outputs(d,row,{'artifacts':control['artifacts'][:-1]},graph,b)
        (d/'runtime.c').write_bytes(b'other')
        with self.assertRaises(ValueError):m.validate_c_outputs(d,row,control,graph,b)
    def test_failed_final_validation_leaves_no_success_manifest(self):
        p=self.root/'prepared.json'
        with patch.object(m,'validate_prepared_data'),patch.object(m,'validate_prepared',side_effect=ValueError('changed')):
            with self.assertRaises(ValueError):m.publish_prepared(p,{'status':'prepared-diagnostic-only'})
        self.assertFalse(p.exists())
    def test_prepublication_validation_rejects_without_output(self):
        p=self.root/'prepared.json'
        with patch.object(m,'validate_prepared_data',side_effect=ValueError('invalid')):
            with self.assertRaises(ValueError):m.publish_prepared(p,{})
        self.assertFalse(p.exists())
    def test_reparse_ancestor_rejected(self):
        p=self.root/'source';p.write_bytes(b'x');original=Path.lstat
        def attrs(path):
            info=original(path)
            if path==self.root:return types.SimpleNamespace(st_mode=stat.S_IFDIR,st_file_attributes=0x400)
            return info
        with patch.object(Path,'lstat',attrs):
            with self.assertRaisesRegex(ValueError,'reparse'):m.identity(p)
    def test_symlink_ancestor_rejected(self):
        d=self.root/'real';d.mkdir();(d/'input').write_bytes(b'x');link=self.root/'alias'
        try:link.symlink_to(d,target_is_directory=True)
        except OSError:self.skipTest('symlink creation unavailable')
        with self.assertRaises(ValueError):m.identity(link/'input')
    def test_no_overwrite(self):
        p=self.root/'a.json';m.save(p,{'a':1})
        with self.assertRaises((ValueError,FileExistsError)):m.save(p,{'a':2})
        self.assertEqual(json.loads(p.read_bytes()),{'a':1})



# Exact bodies from immutable46c. This guard needs no remote or old checkout.
FROZEN_SAFETY_HASHES = {'WindowsJob': 'e02f649c14937bd97b8dcc4696d9a74eeb57e85b5ffe26cf62f149fd32f52374', 'supervise': '204925c09d201bfb4f309bba24dce1372e28661d0f8c0ee7460994ed56e5a397', 'no_links': '7d243458465b1458442a0dd99577232cdcf9daa25b1bfa200490f0df11ef8e7a', 'identity': 'b370af9db28c25b074d3f95e297ec66c38511fe24f152a7baa1df3abbad03551', 'read': '3e9f820e6e95f1cae0d2f371ebc6f0a2aca8db88f523a5369f39505f15f5dae5', 'verify': 'c14ffea59614cefa6d9af1ed1db67f5d677d319fb0caec37f245da047159c936', 'normalized_graph': 'ecd99aa83fa7308e086dd52192264b5864a08876b99c61caaa46ee9fac410912', 'validate_probe': 'e4dfdeb82ee183549ed42176f87e9c4d167523c65565d70b6abda4765724f387', 'validate_c_outputs': 'd8347e938a84b1e55c6bb8ff7170181f7610ef37c72d2f684b3bfa50045ab349', 'publish_prepared': '40583fc44dd659359754145a8f82ac5474d4f555a29492e1ac661c7dd35a1874'}

class PackSourcePolicyTests(unittest.TestCase):
    def test_ten_safety_functions_are_byte_identical_to_immutable46c(self):
        raw=Path(m.__file__).read_bytes();lines=raw.splitlines(keepends=True)
        nodes={node.name:node for node in ast.parse(raw).body if isinstance(node,(ast.FunctionDef,ast.ClassDef))}
        self.assertEqual(len(FROZEN_SAFETY_HASHES),10)
        for name,expected in FROZEN_SAFETY_HASHES.items():
            node=nodes[name];body=b''.join(lines[node.lineno-1:node.end_lineno])
            with self.subTest(name=name):self.assertEqual(hashlib.sha256(body).hexdigest(),expected)
    def test_pack_only_exact_seventeen_paths_and_twenty_one_frozen_inputs(self):
        expected=frozenset({'tests/test_bootstrap_pack_workflow.py', 'tests/bootstrap_pack_cases.py', 'rulang/llvm_compiler.py', 'tools/bootstrap_pack_build.py', 'tests/test_bootstrap_pack_ci.py', 'tests/test_bootstrap_pack_measurement.py', 'tools/verify_bootstrap_pack_ci.py', 'bootstrap/compiler.ru', '.github/workflows/bootstrap-argument-pack.yml', 'tests/test_llvm_argument_pack.py', 'tools/measure_bootstrap_packs.py', 'tests/test_bootstrap_pack_artifact.py', 'tools/bootstrap_pack_artifact.py', 'tools/verify_bootstrap_slot_ci.py', 'tests/test_bootstrap_pack_native.py', 'tests/test_bootstrap_pack_build.py', 'tests/test_bootstrap_pack_runtime.py'})
        self.assertEqual(m.LANGUAGE_DELTA,expected)
        self.assertEqual(len(m.LANGUAGE_DELTA),17)
        self.assertEqual(set(m.MEASUREMENT_INPUTS),expected | {
            'tools/diagnose_bootstrap_editor_fixture.py','tools/diagnose_bootstrap_slot_control.py',
            'rulang/llvm_toolchain.py','rulang/toolchain_environment.py'})
        self.assertEqual(len(m.MEASUREMENT_INPUTS),21)
        self.assertEqual(m.BASE_COMMIT,'46c81ccfde815b8917be9107288b9a80b08758c9')
        self.assertEqual(m.BASE_TREE,'19c4199f3381bca19be01d5e703ef0b691ec7f8b')
        self.assertEqual(m.BUDGET,600)
    def test_missing_or_unchanged_required_delta_never_passes_subset_policy(self):
        old={'untouched':'same'}
        new={**old,**{key:'new' for key in m.LANGUAGE_DELTA},**m.EMITTER_HASHES}
        m.validate_language_delta(old,new)
        for key in m.LANGUAGE_DELTA:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):m.validate_language_delta(old,{k:v for k,v in new.items() if k!=key})
                with self.assertRaises(ValueError):m.validate_language_delta({**old,key:new[key]},new)
    def test_reviewed_emitter_bytes_match_candidate_not_just_well_formed_pins(self):
        root=Path(m.__file__).resolve().parents[1]
        for name,expected in m.EMITTER_HASHES.items():
            with self.subTest(name=name):self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),expected)


class PackArtifactBindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve();self.receipts={}
        self.config={'build_configs':{},'artifact_receipts':{}}
        for label,commit,tree,schema in (
                ('A',m.BASE_COMMIT,m.BASE_TREE,'ru-pack-old46c-artifact-v1'),
                ('B','b'*40,'c'*40,'ru-pack-current-artifact-v1')):
            folder=self.root/label;folder.mkdir();path=folder/'receipt.json'
            receipt={'commit':commit,'tree':tree,'schema':schema,'run_id':12345}
            path.write_text(json.dumps(receipt));self.receipts[folder]=receipt
            self.config['artifact_receipts'][label]=m.identity(path)
            self.config['build_configs'][label]={'ru_source':{'commit':commit,'tree':tree},
                'bootstrap_directory':str(folder),'verification':str(folder/'verification.json')}
        def verified(directory,*,expected_receipt_sha256):
            self.assertEqual(expected_receipt_sha256,m.identity(Path(directory)/'receipt.json')['sha256'])
            return self.receipts[Path(directory)]
        self.loader=types.SimpleNamespace(__file__=str(Path(m.__file__).resolve().parent/'bootstrap_pack_artifact.py'),
                                         verify_output=verified)
    def run_binding(self):
        with patch.object(m.importlib,'import_module',return_value=self.loader),patch.dict(os.environ,{'GITHUB_SHA':'b'*40,'GITHUB_RUN_ID':'12345'}):
            return m.artifact_inputs(self.config)
    def test_exact_old46c_and_current_run_receipt_bindings(self):
        result=self.run_binding();self.assertEqual(set(result),{'A','B'})
        self.assertEqual(result['A']['commit'],m.BASE_COMMIT)
    def test_original_loader_receipt_hash_cannot_be_rebased(self):
        (self.root/'A/receipt.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'original artifact receipt changed'):self.run_binding()
    def test_wrong_old_commit_tree_or_schema_is_rejected(self):
        for key,value in [('commit','a'*40),('tree','a'*40),('schema','ru-slot-address-old925-artifact-v1')]:
            with self.subTest(key=key):
                old=dict(self.receipts[self.root/'A']);self.receipts[self.root/'A'][key]=value
                # Even matching attacker-supplied config cannot relabel the old pin.
                source=dict(self.config['build_configs']['A']['ru_source'])
                if key in source:self.config['build_configs']['A']['ru_source'][key]=value
                try:
                    with self.assertRaises(ValueError):self.run_binding()
                finally:
                    self.receipts[self.root/'A']=old;self.config['build_configs']['A']['ru_source']=source
    def test_wrong_current_run_commit_schema_or_verification_location_is_rejected(self):
        for key,value in [('run_id',12346),('commit','d'*40),('schema','ru-slot-address-current-artifact-v1')]:
            with self.subTest(key=key):
                old=dict(self.receipts[self.root/'B']);self.receipts[self.root/'B'][key]=value
                source=dict(self.config['build_configs']['B']['ru_source'])
                if key in source:self.config['build_configs']['B']['ru_source'][key]=value
                try:
                    with self.assertRaises(ValueError):self.run_binding()
                finally:
                    self.receipts[self.root/'B']=old;self.config['build_configs']['B']['ru_source']=source
        self.config['build_configs']['B']['verification']=str(self.root/'A/verification.json')
        with self.assertRaises(ValueError):self.run_binding()
    def test_missing_receipt_or_wrong_loader_module_is_rejected(self):
        del self.config['artifact_receipts']['A']
        with self.assertRaises(ValueError):self.run_binding()
        self.loader.__file__=str(self.root/'bootstrap_pack_artifact.py')
        with self.assertRaises(ValueError):self.run_binding()


if __name__=='__main__':unittest.main()
