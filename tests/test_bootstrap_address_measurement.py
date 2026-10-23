from pathlib import Path
import sys
import unittest
import tempfile
import json
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import measure_bootstrap_addresses as m
import diagnose_bootstrap_slot_control as c
import diagnose_bootstrap_editor_fixture as d

class AddressMeasurementTests(unittest.TestCase):
    def good(self,r,s):
        return {'row':{'seconds':{'A':30,'B':20,'C':25}[s]},'classification':{'outcome':'passed','evidence_complete':True},'safe_to_continue':True}
    def test_six_predeclared_orders_all_eighteen_and_summary(self):
        writes=[]; result=m.run_samples(self.good,lambda rows:writes.append(len(rows)))
        self.assertEqual(writes,list(range(1,19)))
        self.assertTrue(result['diagnostic_integrity_passed'])
        self.assertEqual(result['summary']['ratios']['B/C']['values'],[.8]*6)
        self.assertFalse(result['performance_acceptance'])
    def test_old_censor_retained_without_fabricated_ratio(self):
        def execute(r,s):
            row=self.good(r,s)
            if s=='A': row['classification']={'outcome':'valid_censored','evidence_complete':True};row['row']={'passed':False,'seconds':60}
            return row
        result=m.run_samples(execute,lambda rows:None)
        self.assertTrue(result['diagnostic_integrity_passed'])
        self.assertEqual(result['summary']['ratios']['B/A']['completed_pairs'],0)
        self.assertIsNone(result['summary']['ratios']['B/A']['median'])
        self.assertTrue(all(not s['row']['passed'] for s in result['samples'] if s['strategy']=='A'))
    def test_new_or_c_censor_fails_no_dropped_sample(self):
        for strategy in 'BC':
            def execute(r,s):
                row=self.good(r,s)
                if s==strategy:row['classification']={'outcome':'valid_censored','evidence_complete':True}
                return row
            result=m.run_samples(execute,lambda rows:None)
            self.assertFalse(result['diagnostic_integrity_passed']);self.assertEqual(len(result['samples']),18)
    def test_unknown_or_unreaped_stops_execution_records_remaining(self):
        calls=[]
        def execute(r,s):
            calls.append((r,s));raise RuntimeError('cleanup unknown')
        result=m.run_samples(execute,lambda rows:None)
        self.assertEqual(len(calls),1);self.assertEqual(len(result['samples']),18)
        self.assertFalse(result['diagnostic_integrity_passed'])
        self.assertEqual(result['summary']['ratios']['B/C']['completed_pairs'],0)
    def test_unreaped_row_retained_and_no_next_process(self):
        calls=[]
        def execute(r,s):
            calls.append((r,s));row=self.good(r,s);row['safe_to_continue']=False
            row['classification']={'outcome':'invalid','evidence_complete':False}
            row['row']['cleanup_error']='wait failed';return row
        result=m.run_samples(execute,lambda rows:None)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['samples'][0]['row']['cleanup_error'],'wait failed')
        self.assertTrue(result['samples'][0]['attempted'])
        self.assertTrue(all(not s['attempted'] for s in result['samples'][1:]))
        self.assertFalse(result['diagnostic_integrity_passed'])

    def test_order_mutation_rejected(self):
        result=m.run_samples(self.good,lambda rows:None)
        result['samples'][0]['strategy']='B'
        with self.assertRaises(ValueError):m.summarize(result['samples'])
    def test_frozen_full_oracle_no_metric_relaxation(self):
        lines=[]
        for line in c.FULL_PROGRESS_LINES:
            lines.append(line.replace('<timing>','1.25'))
        raw=('\n'.join(lines)+'\n').encode()
        normalized,metrics=m.normalize_log(raw,c,d)
        self.assertEqual(normalized,c.FULL_PROGRESS_LINES);self.assertEqual(len(metrics),3)
        for mutation in (raw[:-1],raw+b'FAIL unknown\n',raw.replace(b'size=100000 ',b'size=999 ',1),raw.replace(b'1.25',b'nan',1)):
            try: altered,_=m.normalize_log(mutation,c,d)
            except (ValueError,UnicodeError):continue
            self.assertNotEqual(altered,c.FULL_PROGRESS_LINES)
    def test_orchestration_stages_18_fresh_copies_full_logs_and_raw_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();app=root/'app';(app/'tools').mkdir(parents=True)
            inputs=root/'inputs';inputs.mkdir();artifacts={}
            for name in ('A.exe','B.exe','C.exe','Scintilla.dll','Lexilla.dll','RuSyntax.dll','RuSyntaxWrongAbi.dll'):
                path=inputs/name;path.write_bytes(name.encode());artifacts[name]=c.identity(path)
            evidence=root/'evidence';evidence.mkdir()
            prepared={'editor_root':str(app),'dependencies':{'binaries':{k:v for k,v in artifacts.items() if k.endswith('.dll')}},
                'runtime_environment':{},'sources':['synthetic-graph'],
                'strategies':{key:{'binary':artifacts[key+'.exe']} for key in 'ABC'}}
            prep=evidence/'prepared.json';prep.write_text(json.dumps(prepared),encoding='utf-8')
            fakebuild=SimpleNamespace(validate_prepared=lambda path:json.loads(Path(path).read_bytes()))
            def verify(record):
                self.assertEqual(c.identity(record['path']),record);return Path(record['path'])
            gate=SimpleNamespace(__file__=str(app/'tools/verify_bootstrap_editor_windows.py'),
                DLLS=('Scintilla.dll','Lexilla.dll','RuSyntax.dll'),verify_identity=verify,
                load_windows_harness=lambda app:SimpleNamespace(Windows=lambda:object()),
                read_log_bytes=lambda path:(Path(path).read_bytes(),c.identity(path)))
            calls=[]
            def runtime(gate,api,exe,env):
                calls.append(str(exe));self.assertEqual(env,{})
                (exe.parent/'ru_notepad-1.log').write_bytes(('\n'.join(c.FULL_PROGRESS_LINES).replace('<timing>','1.25')+'\n').encode())
                return {'executed':True,'passed':True,'pid':123,'seconds':1,'cleanup_killed':False,'exit_code':0,
                    'observation':{'schema':'ru-notepad-child-observation-v2',
                        'clock':{'started_monotonic':10,'deadline_monotonic':70,'finished_monotonic':11,'budget_seconds':60},
                        'nondeadline_errors':[],'deadline_events':[],'first_error':None,
                        'cleanup':{'pid':123,'errors':[],'process_reaped':True,'exit_code':0,'windows_remaining':[],
                                   'handshake_closed':True,'watchdog_stopped':True}},
                    'diagnostic_module_observations':{'pid':123,'complete':True,'snapshots':1,
                        'verified':{name:c.identity(exe.parent/name) for name in gate.DLLS}}}
            def fresh(path,roots):
                path=Path(path);self.assertFalse(path.exists());path.mkdir();return path
            with patch.dict(sys.modules,{'bootstrap_address_build':fakebuild,'verify_bootstrap_editor_windows':gate}), \
                 patch.object(m.sys,'platform','win32'),patch.object(d,'fresh_owned',side_effect=fresh), \
                 patch.object(d,'runtime_child',side_effect=runtime),patch.object(c,'validate_progress_graph'):
                result=m.measure(prep,evidence/'samples',evidence/'samples/measurement.json')
            self.assertTrue(result['diagnostic_integrity_passed']);self.assertEqual(len(set(calls)),18)
            self.assertEqual(len(list((evidence/'samples').glob('*/raw-observation.json'))),18)
            self.assertEqual(len(list((evidence/'samples').glob('*/ru_notepad-*.log'))),18)
            self.assertEqual(json.loads((evidence/'samples/measurement.json').read_bytes())['status'],'complete')

    def test_output_cannot_overwrite_input_or_escape_owned_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();source=root/'prepared.json';source.write_bytes(b'unchanged')
            for output in (source,root.parent/'measurement.json'):
                with self.assertRaises(ValueError):m.reserve_output(root,output)
            output=m.reserve_output(root,root/'measurement.json')
            with self.assertRaises(ValueError):m.reserve_output(root,output)
            self.assertEqual(source.read_bytes(),b'unchanged')

    def test_logs_bounded_utf8_no_empty(self):
        for raw in (b'',b'\xff\n',b'x'*(1024*1024+1),b'PASS x\r'):
            with self.assertRaises((ValueError,UnicodeError)):m.normalize_log(raw,c,d)

if __name__=='__main__':unittest.main()
