from pathlib import Path
import sys
import unittest
import tempfile
import json
import copy
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import measure_bootstrap_packs as m
import diagnose_bootstrap_slot_control as c
import diagnose_bootstrap_editor_fixture as d

class PackMeasurementTests(unittest.TestCase):
    def good(self,r,s):
        value = {'A':30,'B':20,'C':25}[s]
        metrics = [{'kind':kind,'fields':{'size':size,**{field:str(value) for field in fields}}}
                   for kind,size,fields in m.METRIC_GROUPS]
        return {'row':{'seconds':value},'classification':{'outcome':'passed','evidence_complete':True},
                'safe_to_continue':True,'metrics':metrics}
    def equal(self,r,s):
        row=self.good(r,s);row['row']['seconds']=100
        for metric in row['metrics']:
            for field in set(metric['fields'])-{'size'}:metric['fields'][field]='100'
        return row
    def result(self, execute=None):
        return m.run_samples(execute or self.equal,lambda rows:None)
    def flags(self,result):return result['summary']['engineering_screen']['review_flags']
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
        self.assertFalse(result['diagnostic_integrity_passed'])
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
            with patch.dict(sys.modules,{'bootstrap_pack_build':fakebuild,'verify_bootstrap_editor_windows':gate}), \
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


    def test_all_eleven_metric_keys_match_frozen_oracle_and_every_pair(self):
        _,metrics=m.normalize_log(('\n'.join(c.FULL_PROGRESS_LINES).replace('<timing>','1.25')+'\n').encode(),c,d)
        keys={metric['kind']+':'+metric['fields']['size']+':'+field
              for metric in metrics for field in c.TIMING_FIELDS[metric['kind']]}
        self.assertEqual(set(m.METRIC_KEYS),keys);self.assertEqual(len(keys),11)
        result=self.result();summary=result['summary']
        self.assertTrue(result['diagnostic_integrity_passed'])
        self.assertFalse(summary['engineering_screen']['requires_further_review'])
        for pair in summary['pairs']:
            for name in ('B/A','B/C'):
                self.assertEqual(set(pair['metric_pairs'][name]),keys)
                self.assertEqual(set(pair['observed_metric_ratios'][name]),keys)
                for row in pair['metric_pairs'][name].values():
                    self.assertEqual(row['numerator']['raw_values'],['100'])
                    self.assertEqual(row['denominator']['raw_values'],['100'])
                    self.assertEqual(row['ratio'],1)
                    self.assertEqual(row['undefined_reasons'],[])
        for name in ('B/A','B/C'):
            self.assertEqual(set(summary['metric_ratios'][name]),keys)
            self.assertTrue(all(row['completed_pairs']==6 and len(row['per_round'])==6
                                for row in summary['metric_ratios'][name].values()))

    def test_missing_metric_preserved_not_intersected(self):
        key='PERF_RU:100000:edit_ms'
        def execute(r,s):
            row=self.equal(r,s)
            if r==3 and s=='B':del row['metrics'][0]['fields']['edit_ms']
            return row
        result=self.result(execute)
        self.assertFalse(result['diagnostic_integrity_passed'])
        pair=result['summary']['pairs'][2]['metric_pairs']['B/A'][key]
        self.assertEqual(pair['numerator']['raw_values'],[])
        self.assertIsNone(pair['ratio']);self.assertIn('numerator:missing_metric',pair['undefined_reasons'])
        self.assertEqual(result['summary']['metric_ratios']['B/A'][key]['completed_pairs'],5)
        self.assertTrue(result['summary']['engineering_screen']['requires_further_review'])

    def test_duplicate_metric_retains_all_original_values(self):
        key='PERF_RU:100000:edit_ms'
        def execute(r,s):
            row=self.equal(r,s)
            if r==2 and s=='A':
                duplicate=copy.deepcopy(row['metrics'][0]);duplicate['fields']['edit_ms']='999'
                row['metrics'].append(duplicate)
            return row
        result=self.result(execute)
        self.assertFalse(result['diagnostic_integrity_passed'])
        observation=result['summary']['pairs'][1]['observations']['A']
        self.assertEqual(observation['metrics'][key]['raw_values'],['100','999'])
        self.assertIn('duplicate_metric_group',{i['reason'] for i in observation['issues']})
        pair=result['summary']['pairs'][1]['metric_pairs']['B/A'][key]
        self.assertIsNone(pair['ratio']);self.assertIn('denominator:duplicate_metric',pair['undefined_reasons'])

    def test_split_duplicate_metric_groups_cannot_supply_a_fake_complete_group(self):
        def execute(r,s):
            row=self.equal(r,s)
            if r==1 and s=='B':
                extra={'kind':'PERF_RU','fields':{'size':'100000','edit_ms':row['metrics'][0]['fields'].pop('edit_ms')}}
                row['metrics'].append(extra)
            return row
        result=self.result(execute)
        self.assertFalse(result['diagnostic_integrity_passed'])
        self.assertTrue(result['summary']['engineering_screen']['requires_further_review'])

    def test_zero_denominator_is_visible_and_requires_review_not_fake_ratio(self):
        key='PERF_RU:100000:initial_ms'
        for strategy,comparison in [('A','B/A'),('C','B/C')]:
            with self.subTest(strategy=strategy):
                def execute(r,s):
                    row=self.equal(r,s)
                    if r==4 and s==strategy:row['metrics'][0]['fields']['initial_ms']='0'
                    return row
                result=self.result(execute)
                self.assertTrue(result['diagnostic_integrity_passed'])
                pair=result['summary']['pairs'][3]['metric_pairs'][comparison][key]
                self.assertEqual(pair['denominator']['raw_values'],['0'])
                self.assertEqual(pair['denominator']['value'],0)
                self.assertIsNone(pair['ratio']);self.assertIn('zero_denominator',pair['undefined_reasons'])
                self.assertTrue(result['summary']['engineering_screen']['requires_further_review'])

    def test_finite_tiny_denominator_overflow_is_an_explicit_undefined_ratio(self):
        key='PERF_RU:100000:initial_ms'
        def execute(r,s):
            row=self.equal(r,s)
            if r==1 and s=='A':row['metrics'][0]['fields']['initial_ms']='5e-324'
            return row
        result=self.result(execute)
        pair=result['summary']['pairs'][0]['metric_pairs']['B/A'][key]
        self.assertEqual(pair['denominator']['raw_values'],['5e-324'])
        self.assertIsNone(pair['ratio']);self.assertIn('nonfinite_ratio',pair['undefined_reasons'])
        self.assertTrue(result['summary']['engineering_screen']['requires_further_review'])
        json.dumps(result['summary'],allow_nan=False)

    def test_zero_numerator_is_a_defined_zero_ratio(self):
        key='RU_GUI_SYNC:1000000:wall_ms'
        def execute(r,s):
            row=self.equal(r,s)
            if s=='B':row['metrics'][2]['fields']['wall_ms']='0'
            return row
        result=self.result(execute)
        self.assertTrue(result['diagnostic_integrity_passed'])
        self.assertEqual(result['summary']['metric_ratios']['B/A'][key]['values'],[0]*6)
        self.assertFalse(result['summary']['engineering_screen']['requires_further_review'])

    def test_invalid_metric_values_never_become_ratios(self):
        key='PERF_RU:100000:edit_ms'
        for bad in ('NaN','inf','-1','60001',True,{},None):
            with self.subTest(bad=bad):
                def execute(r,s):
                    row=self.equal(r,s)
                    if r==1 and s=='B':row['metrics'][0]['fields']['edit_ms']=bad
                    return row
                result=self.result(execute)
                self.assertFalse(result['diagnostic_integrity_passed'])
                pair=result['summary']['pairs'][0]['metric_pairs']['B/A'][key]
                self.assertIsNone(pair['ratio']);self.assertIn('numerator:invalid_metric_value',pair['undefined_reasons'])
                json.dumps(result['summary'],allow_nan=False)

    def test_unknown_metric_group_never_disappears_from_diagnostics(self):
        def execute(r,s):
            row=self.equal(r,s)
            if r==1 and s=='B':row['metrics'].append({'kind':'PERF_RU','fields':{'size':'999','initial_ms':'3'}})
            return row
        result=self.result(execute)
        self.assertFalse(result['diagnostic_integrity_passed'])
        issues=result['summary']['pairs'][0]['observations']['B']['issues']
        self.assertIn('unexpected_metric_group',{i['reason'] for i in issues})
        self.assertTrue(any(i.get('key')=='PERF_RU:999:initial_ms' and i['raw']=='3' for i in issues))

    def test_malformed_metric_records_and_runtime_preserve_reasons(self):
        for bad in (None,{},['bad'],[{'fields':[]}],[] ):
            with self.subTest(bad=bad):
                def execute(r,s):
                    row=self.equal(r,s)
                    if r==1 and s=='A':row['metrics']=bad
                    return row
                result=self.result(execute)
                self.assertFalse(result['diagnostic_integrity_passed'])
                self.assertTrue(result['summary']['engineering_screen']['requires_further_review'])
        for bad in (0,True,float('nan'),float('inf'),'bad',None):
            with self.subTest(seconds=bad):
                def execute(r,s):
                    row=self.equal(r,s)
                    if r==1 and s=='B':row['row']['seconds']=bad
                    return row
                result=self.result(execute)
                self.assertFalse(result['diagnostic_integrity_passed'])
                pair=result['summary']['pairs'][0]['wall_pairs']['B/A']
                self.assertIsNone(pair['ratio']);self.assertTrue(pair['undefined_reasons'])
                json.dumps(result['summary'],allow_nan=False)

    def test_predeclared_wall_screen_threshold_and_pair_count(self):
        for ratios,expected in [([1.03]*6,True),([1.031]*6,False),
                                ([1]*5+[1.06],True),([1]*4+[1.06]*2,False)]:
            with self.subTest(ratios=ratios):
                def execute(r,s):
                    row=self.equal(r,s)
                    if s=='B':row['row']['seconds']=ratios[r-1]*100
                    return row
                result=self.result(execute);screen=result['summary']['engineering_screen']
                self.assertEqual(screen['whole_fixture_screen_passed'],expected)
                self.assertEqual(screen['whole_fixture_pairs_at_most_limit'],sum(v<=1.05 for v in ratios))
                self.assertFalse(screen['automatic_acceptance']);self.assertTrue(screen['independent_review_required'])

    def test_one_wall_outlier_retained_and_reviewed_even_when_five_pairs_pass(self):
        def execute(r,s):
            row=self.equal(r,s)
            if r==6 and s=='B':row['row']['seconds']=106
            return row
        result=self.result(execute);screen=result['summary']['engineering_screen']
        self.assertTrue(screen['whole_fixture_screen_passed']);self.assertTrue(screen['requires_further_review'])
        self.assertEqual(result['summary']['ratios']['B/A']['values'],[1]*5+[1.06])
        self.assertTrue(any(f['reason']=='whole_fixture_individual_regression' and f['round']==6 for f in self.flags(result)))

    def test_one_metric_outlier_cannot_hide_behind_good_wall_or_metric_median(self):
        key='RU_GUI_SYNC:1000000:max_tick_ms'
        def execute(r,s):
            row=self.equal(r,s)
            if r==6 and s=='B':row['metrics'][2]['fields']['max_tick_ms']='200'
            return row
        result=self.result(execute);summary=result['summary']
        self.assertTrue(summary['engineering_screen']['whole_fixture_screen_passed'])
        self.assertEqual(summary['metric_ratios']['B/A'][key]['median'],1)
        self.assertEqual(summary['metric_ratios']['B/A'][key]['values'],[1]*5+[2])
        self.assertTrue(any(f['reason']=='metric_individual_regression' and f['key']==key and f['round']==6 for f in self.flags(result)))
        self.assertTrue(summary['engineering_screen']['requires_further_review'])

    def test_each_metric_median_regression_has_its_own_flag(self):
        def execute(r,s):
            row=self.equal(r,s)
            if s=='B':
                for metric in row['metrics']:
                    for field in set(metric['fields'])-{'size'}:metric['fields'][field]='106'
            return row
        result=self.result(execute)
        keys={f['key'] for f in self.flags(result) if f['reason']=='metric_median_regression'}
        self.assertEqual(keys,set(m.METRIC_KEYS))
        self.assertTrue(result['summary']['engineering_screen']['whole_fixture_screen_passed'])

    def test_slower_than_c_is_reported_not_a_regression_gate(self):
        def execute(r,s):
            row=self.equal(r,s)
            if s=='C':
                row['row']['seconds']=50
                for metric in row['metrics']:
                    for field in set(metric['fields'])-{'size'}:metric['fields'][field]='50'
            return row
        result=self.result(execute);screen=result['summary']['engineering_screen']
        self.assertEqual(result['summary']['ratios']['B/C']['median'],2)
        self.assertFalse(screen['crossover_required']);self.assertFalse(screen['requires_further_review'])
        self.assertFalse(result['performance_acceptance']);self.assertFalse(result['summary']['statistical_acceptance'])

    def test_incomplete_and_censored_raw_values_preserved_with_undefined_reasons(self):
        def execute(r,s):
            row=self.equal(r,s)
            if r==1 and s=='A':row['classification']={'outcome':'valid_censored','evidence_complete':True};row['row']['seconds']=60
            return row
        result=self.result(execute);pair=result['summary']['pairs'][0]
        self.assertEqual(pair['observations']['A']['seconds']['raw'],60)
        self.assertIsNone(pair['wall_pairs']['B/A']['ratio'])
        self.assertIn('observations_not_both_complete',pair['wall_pairs']['B/A']['undefined_reasons'])
        self.assertTrue(all(row['ratio'] is None and 'observations_not_both_complete' in row['undefined_reasons']
                            for row in pair['metric_pairs']['B/A'].values()))
        self.assertFalse(result['diagnostic_integrity_passed'])
        self.assertTrue(result['summary']['engineering_screen']['requires_further_review'])

    def test_aggregate_requires_all_eighteen_slots_in_predeclared_order(self):
        samples=self.result()['samples']
        for changed in (samples[:-1],samples+[samples[0]],list(reversed(samples))):
            with self.assertRaises(ValueError):m.summarize(changed)

if __name__=='__main__':unittest.main()
