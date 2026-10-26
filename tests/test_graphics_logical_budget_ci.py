"""Calibration evidence controls: no actual children, sleeps, or budget changes."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('logical_calibration_under_test',ROOT/'tools/calibrate_graphics_logical_budget.py')
collector=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(collector)


class LogicalCalibrationContractTests(unittest.TestCase):
    def receipt(self,descriptor,mode="measure"):
        return {'schema':collector.SCHEMA,'mode':mode,'sample_every':256,
            'descriptor':descriptor,'measurement_complete':True,'functional_assertions_passed':True,
            'unittest':{'tests_run':1,'errors':0,'failures':0,'skipped':[]},
            'events':[{'charged_event':True,'nesting_depth':0,'truncated':False,'snapshot':{'schema_version':2,'model_version':'logical-work-v2','closed':True,
                'work_limit':262144 if mode=='acceptance' else None,'first_exhaustion_kind':None,'total':1,'raw_total':1,
                'attempted_total':1,'charged_units':1,'attempted_units':1,
                'weighted_counts':[[kind,1 if kind=='expr' else 0] for kind in ('expr','stmt','loop','call','helper_item','bulk_unit')],
                'counts':[[kind,1 if kind=='expr' else 0] for kind in ('expr','stmt','loop','call','helper_item','bulk_unit')]}}]}

    def run_scenario(self,action='success',mutate=None,drift=False,mode='measure',descriptors=None,fault_index=0):
        descriptors=descriptors or [{'kind':'ui','case':name,'repeat':0} for name in ('first','second','third')]
        with tempfile.TemporaryDirectory(prefix='budget-ci-') as directory:
            out=Path(directory);(out/'000').mkdir()
            (out/'000/result.json').write_text(json.dumps(self.receipt(descriptors[0],mode)),encoding='utf-8')
            calls=[]
            def run(command,**kwargs):
                descriptor=json.loads(command[command.index('--child')+1])
                receipt=Path(command[command.index('--out')+1])
                self.assertFalse(receipt.exists())
                self.assertEqual(command[1:3],['-X','faulthandler'])
                self.assertEqual(command[command.index('--repo-root')+1],str(collector.ROOT))
                self.assertEqual(kwargs['timeout'],120)
                calls.append(descriptor)
                current=action if len(calls)==fault_index+1 else 'success'
                if current=='startup': raise OSError('controlled spawn failure')
                if current=='timeout': raise subprocess.TimeoutExpired(command,120,output=b'partial out',stderr=b'partial err')
                row=self.receipt(descriptor,mode)
                if mutate and len(calls)==fault_index+1: mutate(row)
                if current=='failed-functional':
                    row['functional_assertions_passed']=False;row['unittest']['errors']=1
                if current=='budget-stop':
                    row.update(functional_assertions_passed=False,diagnostic_class='budget-exhausted',
                               error={'type':'BudgetExceeded'},cleanup={'structure_depth':0,'depth':0,'call_state':[0],'active_budget':False,'canvas_closed':True})
                    row['unittest']['errors']=1
                    row['events'][0].update(truncated=True,error={'type':'BudgetExceeded'})
                    row['events'][0]['snapshot'].update(first_exhaustion_kind='work',attempted_units=262145,attempted_total=262145)
                if current!='missing': receipt.write_text('{bad' if current=='malformed' else json.dumps(row),encoding='utf-8')
                code=-1073741571 if current=='crash' else (1 if current in ('failed-functional','budget-stop') else 0)
                return subprocess.CompletedProcess(command,code,b'out',b'err')
            hashes=[{'code':'before'},{'code':'changed' if drift else 'before'}]
            with patch.object(collector,'repo_identity',return_value={'checkout_head':'fixed'}), \
                 patch.object(collector,'plan',return_value=descriptors), \
                 patch.object(collector,'source_hashes',side_effect=hashes), \
                 patch.object(collector.platform,'platform',return_value='fixture'), \
                 patch.object(collector.subprocess,'run',side_effect=run):
                code=collector.collect(mode,'full' if mode=='acceptance' else 'ui',256,out)
            report=json.loads((out/'report.json').read_text(encoding='utf-8'))
            self.assertEqual(calls,descriptors)
            self.assertEqual([a['descriptor'] for a in report['attempts']],descriptors)
            if mode!='acceptance': self.assertFalse(report['product_acceptance'])
            logs={}
            for i,attempt in enumerate(report['attempts']):
                for suffix in ('stdout','stderr'):
                    data=(out/f'{i:03d}'/suffix).read_bytes();logs[i,suffix]=data
                    self.assertEqual(collector.digest(data),attempt[suffix+'_sha256'])
            return code,report,logs

    def test_complete_measurement_never_claims_product_acceptance(self):
        code,report,_=self.run_scenario()
        self.assertEqual(code,0);self.assertTrue(report['measurement_complete'])
        self.assertTrue(report['functional_assertions_passed'])
        self.assertFalse(report['product_acceptance'])

    def test_recorded_functional_failure_is_not_hidden_by_collection_success(self):
        code,report,_=self.run_scenario('failed-functional')
        self.assertEqual(code,0);self.assertTrue(report['measurement_complete'])
        self.assertFalse(report['functional_assertions_passed'])
        self.assertEqual(report['attempts'][0]['returncode'],1)

    def test_spawn_timeout_crash_missing_and_bad_receipts_continue_full_plan(self):
        for action in ('startup','timeout','crash','missing','malformed'):
            with self.subTest(action=action):
                code,report,logs=self.run_scenario(action)
                self.assertEqual(code,1);self.assertFalse(report['measurement_complete'])
                self.assertFalse(report['functional_assertions_passed'])
                first=report['attempts'][0]
                if action=='timeout':
                    self.assertTrue(first['timeout'])
                    self.assertEqual((logs[0,'stdout'],logs[0,'stderr']),(b'partial out',b'partial err'))
                if action=='crash': self.assertEqual(first['returncode_hex'],'0xc00000fd')
                if action=='startup': self.assertIn('OSError',first['error'])

    def test_green_flags_cannot_hide_skip_inventory_or_bad_snapshot(self):
        mutations=[lambda row:row['unittest'].update(skipped=[['case','unavailable']]),
                   lambda row:row['unittest'].update(tests_run=True),
                   lambda row:row['unittest'].update(tests_run=0),
                   lambda row:row['unittest'].update(errors=1),
                   lambda row:row.update(events=[]),
                   lambda row:row['events'][0]['snapshot'].update(total=99),
                   lambda row:row['events'][0]['snapshot'].update(closed=False),
                   lambda row:row['events'][0]['snapshot'].update(work_limit=500000),
                   lambda row:row['events'][0]['snapshot'].update(schema_version=1),
                   lambda row:row['events'][0]['snapshot'].update(raw_total=2),
                   lambda row:row['events'][0]['snapshot'].update(charged_units=2),
                   lambda row:row['events'][0]['snapshot'].update(model_version='raw-v1'),
                   lambda row:row.update(sample_every=64)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                code,report,_=self.run_scenario(mutate=mutation)
                self.assertEqual(code,1);self.assertFalse(report['measurement_complete'])

    def test_source_drift_fails_receipt_even_with_all_green_children(self):
        code,report,_=self.run_scenario(drift=True)
        self.assertEqual(code,1);self.assertFalse(report['measurement_complete'])

    def test_ignored_event_cannot_reuse_prior_snapshot_and_nested_open_is_distinct(self):
        descriptor={'kind':'ui','case':'case','repeat':0}
        row=self.receipt(descriptor)
        row['events'].append({'charged_event':False,'snapshot':None,'nesting_depth':0})
        self.assertTrue(collector.valid_receipt(row,descriptor,'measure',256))
        row['events'][-1]['snapshot']=row['events'][0]['snapshot']
        self.assertFalse(collector.valid_receipt(row,descriptor,'measure',256))
        row['events'].pop()
        from copy import deepcopy
        nested=deepcopy(row['events'][0])
        nested['nesting_depth']=1;nested['snapshot']['closed']=False
        row['events'].append(nested)
        self.assertTrue(collector.valid_receipt(row,descriptor,'measure',256))
        nested['nesting_depth']=0
        self.assertFalse(collector.valid_receipt(row,descriptor,'measure',256))

    def test_handle_wrapper_marks_unchanged_snapshot_unbudgeted(self):
        from rulang.execution_budget import Budget,BudgetPolicy
        from rulang.graphics_runtime import GraphicsHost
        def snapshot(count):
            budget=Budget(BudgetPolicy(None,256),clock=lambda:0.,memory=lambda:0,
                          started=0.,memory_start=0)
            budget.charge('expr',count);budget.close()
            return budget.snapshot()
        old,new=snapshot(1),snapshot(2)
        def handle(host,event):
            if event['type']=='fresh': host.budget_snapshot=new
        def work(vm,host,descriptor,directory,evidence):
            host.budget_snapshot=old
            host.handle({'type':'ignored'})
            host.handle({'type':'fresh'})
            return {'functional_assertions_passed':True}
        descriptor={'kind':'workload','case':'fixture','n':0,'repeat':0}
        with tempfile.TemporaryDirectory() as directory:
            receipt=Path(directory)/'result.json'
            with patch.object(GraphicsHost,'handle',handle),patch.object(collector,'workload',work):
                self.assertEqual(collector.child('measure',256,descriptor,receipt),0)
            row=json.loads(receipt.read_text(encoding='utf-8'))
        self.assertEqual([e['charged_event'] for e in row['events']],[False,True])
        self.assertIsNone(row['events'][0]['snapshot'])
        self.assertEqual(row['events'][1]['snapshot']['total'],2)
        self.assertTrue(collector.valid_receipt(row,descriptor,'measure',256))

    def test_acceptance_separates_required_functionality_from_budget_stress_observation(self):
        descriptors=[{'kind':'contract','case':'required','repeat':0},
                     {'kind':'ui','case':collector.UI[0],'repeat':0},
                     {'kind':'workload','case':'text-helper','n':65536,'repeat':0},
                     {'kind':'workload','case':'map-protocol','n':4096,'repeat':0}]
        code,report,_=self.run_scenario(mode='acceptance',descriptors=descriptors)
        self.assertEqual(code,0);self.assertTrue(report['product_interaction_gate'])
        self.assertTrue(report['product_acceptance'])
        code,report,_=self.run_scenario('budget-stop',mode='acceptance',descriptors=descriptors,fault_index=3)
        self.assertEqual(code,0);self.assertTrue(report['product_acceptance'])
        self.assertFalse(report['functional_assertions_passed'])
        self.assertTrue(report['pressure_observation_complete'])
        code,report,_=self.run_scenario('failed-functional',mode='acceptance',descriptors=descriptors,fault_index=3)
        self.assertEqual(code,1);self.assertTrue(report['product_interaction_gate'])
        self.assertFalse(report['pressure_observation_complete'])
        for index in (0,1,2):
            with self.subTest(required_index=index):
                code,report,_=self.run_scenario('budget-stop',mode='acceptance',descriptors=descriptors,fault_index=index)
                self.assertEqual(code,1);self.assertFalse(report['product_interaction_gate'])
                self.assertFalse(report['product_acceptance'])

    def test_budget_stress_cannot_hide_missing_cleanup_or_ordinary_runtime_error(self):
        descriptor={'kind':'workload','case':'map-protocol','n':4096,'repeat':0}
        row=self.receipt(descriptor,'acceptance')
        row.update(functional_assertions_passed=False,diagnostic_class='budget-exhausted',error={'type':'BudgetExceeded'},
                   cleanup={'structure_depth':0,'depth':0,'call_state':[0],'active_budget':False,'canvas_closed':True})
        row['events'][0].update(truncated=True,error={'type':'BudgetExceeded'})
        row['events'][0]['snapshot'].update(first_exhaustion_kind='work',attempted_units=262145,attempted_total=262145)
        self.assertTrue(collector.observed_budget_stop(row,'acceptance'))
        from copy import deepcopy
        for mutate in (lambda r:r.pop('cleanup'),lambda r:r['cleanup'].update(depth=1),
                       lambda r:r['error'].update(type='RuError'),lambda r:r['events'][0].update(error={'type':'AssertionError'}),
                       lambda r:r['events'][0]['snapshot'].update(attempted_units=1)):
            with self.subTest(mutation=mutate):
                bad=deepcopy(row);mutate(bad)
                self.assertFalse(collector.observed_budget_stop(bad,'acceptance'))

    def test_snapshot_limits_attempts_and_resource_evidence_fail_closed(self):
        from copy import deepcopy
        descriptor={'kind':'workload','case':'map-protocol','n':4096,'repeat':0}
        row=self.receipt(descriptor,'acceptance')
        def valid(value): return collector.valid_snapshot(value,row['events'][0],'acceptance')
        original=row['events'][0]['snapshot']
        self.assertTrue(valid(original))
        for updates in ({'attempted_units':2},{'attempted_total':2},
                        {'elapsed_sample':True},{'elapsed_sample':float('nan')},
                        {'elapsed_sample':float('inf')},{'net_allocated_sample':True},
                        {'net_allocated_sample':1.5}):
            with self.subTest(updates=updates):
                value=deepcopy(original);value.update(updates);self.assertFalse(valid(value))
        value=deepcopy(original)
        for key in ('counts','weighted_counts'): value[key][0][1]=262145
        value.update(total=262145,raw_total=262145,charged_units=262145,
                     attempted_total=262145,attempted_units=262145)
        self.assertFalse(valid(value))  # Internally consistent, but above limit.
        value.update(first_exhaustion_kind='work',attempted_units=262146,attempted_total=262146)
        self.assertFalse(valid(value))  # Already-charged excess is not a valid stop.
        for kind,field,good,bad_values in (
                ('time','elapsed_sample',1.0,(0,0.999,True,None,float('nan'),float('inf'),'1.1')),
                ('memory','net_allocated_sample',67108865,(0,67108864,True,None,67108865.0,float('nan')))):
            value=deepcopy(original);value.update(first_exhaustion_kind=kind);value[field]=good
            self.assertTrue(valid(value))
            for bad in bad_values:
                with self.subTest(kind=kind,bad=bad):
                    malformed=deepcopy(value);malformed[field]=bad;self.assertFalse(valid(malformed))
            value['attempted_units']=2
            self.assertFalse(valid(value))

    def test_fixed_plan_modes_reject_unregistered_sampling_and_acceptance(self):
        for args in [('acceptance','ui',256,False),('acceptance','full',64,False),('measure','full',64,False),
                     ('measure','sensitivity',256,False),('measure','full',128,False),
                     ('baseline-natural','full',256,False),('measure','large-text',64,False)]:
            with self.subTest(args=args),self.assertRaises(ValueError): collector.plan(*args)
        large=collector.plan('measure','large-text',256,False)
        self.assertEqual(len(large),9)
        self.assertEqual([(row['n'],row['repeat']) for row in large],[(n,r) for n in (65536,262144,1048576) for r in range(3)])
        self.assertTrue(all(row['case']=='text-helper' for row in large))
        base=collector.plan('baseline-natural','ui',256,False)
        self.assertEqual([row['case'] for row in base],list(collector.UI))
        self.assertEqual(len(collector.plan('measure','sensitivity',64,False)),15)
        linux=collector.plan('measure','full',256,False)
        windows=collector.plan('measure','full',256,True)
        self.assertEqual(len(linux),177);self.assertEqual(len(windows),177)
        self.assertEqual(sum(row['case']=='native-reentry' for row in windows),9)
        self.assertFalse(any(row['case']=='native-reentry' for row in linux))
        acceptance=collector.plan('acceptance','full',256,False)
        contracts=collector.plan('contracts','full',256,False)
        self.assertEqual(acceptance,contracts+linux+large)
        with patch.object(collector.unittest.defaultTestLoader,'loadTestsFromName',return_value=unittest.TestSuite()):
            with self.assertRaises(ValueError): collector.plan('acceptance','full',256,False)


if __name__=='__main__': unittest.main()
