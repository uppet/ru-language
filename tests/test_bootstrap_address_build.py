import importlib.util
import json
from pathlib import Path
import tempfile
import types
import stat
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('address_build',Path(__file__).resolve().parents[1]/'tools/bootstrap_address_build.py')
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

if __name__=='__main__':unittest.main()
