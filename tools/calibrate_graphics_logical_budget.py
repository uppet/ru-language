#!/usr/bin/env python3
"""Pre-registered logical-budget measurements and narrowly scoped acceptance.

Direct GraphicsHost children have its cooperative 1 s/64 MiB guards plus this
runner's 120 s process bound. They do not claim the 如书 Session 10 s watchdog.
Acceptance separately includes the original Session watchdog contract tests; it
is a logical-budget gate, not general editor/GUI release certification.
"""
import argparse
from dataclasses import asdict
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import traceback
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'ru-graphics-logical-calibration-v2'
UI = tuple('test_ruui.RuUIParityTests.'+name for name in (
    'test_mixer_interactions_preset_and_theme', 'test_scroll_clips_hits_and_drag_reveals',
    'test_scroll_drag_clamps_and_second_drag_resumes'))
SIZES = (0, 1, 16, 256, 4096)
GROUPS = ('empty-loop', 'arithmetic-loop', 'cross-owner', 'array-callback',
          'map-protocol', 'sort-callback', 'text-helper', 'collection-helper')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def source_hashes():
    paths=[]
    for folder in ('rulang','rushu','tests','examples','tools'):
        paths.extend(p for p in (ROOT/folder).rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo'))
    paths += [ROOT/name for name in ('ru','ru.py','pyproject.toml') if (ROOT/name).is_file()]
    result={str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in sorted(paths)}
    result['__collector__']=digest(Path(__file__).resolve().read_bytes())
    return result


def repo_identity():
    result={}
    for key,args in (('checkout_head',['rev-parse','HEAD']),('checkout_tree',['rev-parse','HEAD^{tree}']),
                     ('worktree_status',['status','--porcelain'])):
        process=subprocess.run(['git','-C',str(ROOT),*args],capture_output=True,timeout=10)
        if process.returncode: raise RuntimeError('Cannot identify actual repo root: '+process.stderr.decode(errors='replace'))
        result[key]=process.stdout.decode('utf-8').strip()
    result['note']='Checkout identity may have synthetic ancestry; source hashes identify actual production inputs'
    return result


def plan(mode, corpus, cadence, windows):
    if mode == 'acceptance':
        if corpus!='full' or cadence!=256: raise ValueError('Acceptance is fixed full+contracts+large-text at cadence 256')
        return (plan('contracts','full',256,windows)+plan('measure','full',256,windows)
                +plan('measure','large-text',256,windows))
    if cadence not in (64, 256, 1024):
        raise ValueError('Only pre-registered cadences 64/256/1024 are permitted')
    if mode == 'contracts':
        sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
        def flatten(suite):
            for item in suite:
                if isinstance(item,unittest.TestSuite): yield from flatten(item)
                else: yield item
        names=[]
        for module in ('test_graphics_logical_budget','test_graphics_logical_budget_ci'):
            cases=[t.id() for t in flatten(unittest.defaultTestLoader.loadTestsFromName(module))]
            if not cases or any('_FailedTest' in name for name in cases):
                raise ValueError('Missing required contract module '+module)
            names.extend(cases)
        names.sort()
        names += ['test_rushu_graphics_bridge.SpawnedGraphicsBridgeTests.'+name for name in (
            'test_hard_watchdog_kills_blocked_worker_and_restarts',
            'test_stop_blocked_callback_before_watchdog_and_recover')]
        if not names or len(set(names))!=len(names) or any('_FailedTest' in n for n in names):
            raise ValueError('Missing/duplicate contract tests')
        return [{'kind':'contract','case':name,'repeat':0} for name in names]
    if mode == 'baseline-natural':
        if corpus != 'ui' or cadence != 256:
            raise ValueError('Baseline is one unchanged UI pass, not a new full benchmark')
        return [{'kind': 'ui', 'case': case, 'repeat': 0} for case in UI]
    if corpus=='large-text':
        if cadence!=256: raise ValueError('Large-text corpus is registered at cadence 256 only')
        return [{'kind':'workload','case':'text-helper','n':n,'repeat':repeat}
                for n in (65536,262144,1048576) for repeat in range(3)]
    if (corpus == 'full' and cadence != 256) or (corpus == 'sensitivity' and cadence not in (64, 1024)):
        raise ValueError('Cadence/corpus differs from the registered plan')
    cases = [{'kind': 'ui', 'case': case} for case in UI]
    if corpus == 'full':
        cases += [{'kind': 'workload', 'case': group, 'n': n} for group in GROUPS for n in SIZES]
        cases += [{'kind': 'workload', 'case': group, 'n': n}
                  for group in ('unary', 'nested-display') for n in (0, 1, 16, 64)]
        cases += [{'kind': 'workload', 'case': 'typed-array', 'n': n} for n in SIZES]
        cases += [{'kind': 'workload', 'case': 'native-reentry' if windows else 'host-reentry', 'n': n}
                  for n in (1, 2, 8)]
    elif corpus == 'sensitivity':
        cases += [{'kind': 'workload', 'case': group, 'n': 4096}
                  for group in ('empty-loop', 'arithmetic-loop')]
    return [dict(case, repeat=repeat) for case in cases for repeat in range(3)]


def workload(vm, host, descriptor, directory, evidence):
    """Run fixed Ru workloads through an actual graphics event, not fake charges."""
    from rulang.frontend import parse
    n, name = descriptor['n'], descriptor['case']
    setup, body, expected = '', '', None
    if name == 'empty-loop':
        body, expected = f'循 {n} 次 环 结果 其 增 0.', [0.0]
    elif name == 'arithmetic-loop':
        body, expected = f'和 取 0. 循 {n} 次 和 取 和+1. 环 结果 其 增 和.', [float(n)]
    elif name == 'cross-owner':
        module = directory/'logical-owner.ru'
        module.write_text('算 加 值: 得 值+1. 法\n', encoding='utf-8')
        setup = "库 取 外言 'logical-owner.ru'."
        body, expected = f'和 取 0. 循 {n} 次 和 取 库 其 加 和. 环 结果 其 增 和.', [float(n)]
    elif name in ('array-callback', 'typed-array', 'sort-callback', 'collection-helper'):
        setup = f'原 取 []. 位 取 {n}. 循 {n} 次 原 其 增 位. 位 取 位-1. 环 '
        if name == 'array-callback':
            body, expected = '结果 其 增 (原 其 另成 (算 项: 得 项+1. 法)).', [[float(x+1) for x in range(n,0,-1)]]
        elif name == 'typed-array':
            setup += '算 检 项 为 数 阵: 得 项 其 量. 法 '
            body, expected = '结果 其 增 (检 原).', [float(n)]
        elif name == 'sort-callback':
            body, expected = '结果 其 增 (原 其 排序 (算 左 右: 得 左 < 右. 法)).', [[float(x) for x in range(1,n+1)]]
        else:
            body, expected = f'结果 其 增 原[0:{n}].', [[float(x) for x in range(n,0,-1)]]
    elif name == 'map-protocol':
        setup = '形 键形: 值 为 数. 算 印: 得 0. 法 算 同 另一: 得 其 值 == 另一 其 值. 法 象 '
        body = f'表 取 {{}}. 位 取 0. 循 {n} 次 表 其 增 (新 键形 值:位) 位. 位 取 位+1. 环 位 取 0. 和 取 0. 循 {n} 次 和 取 和+(表 其 查 (新 键形 值:位)). 位 取 位+1. 环 结果 其 增 和.'
        expected = [float(n*(n-1)//2)]
    elif name == 'text-helper':
        text = ('a甲'*((n+1)//2))[:n]
        setup = "文库 取 外言 '如:文本'. 文 取 "+json.dumps(text, ensure_ascii=False)+'.'
        body, expected = "结果 其 增 (文库 其 替换 文 '甲' '乙').", [text.replace('甲','乙')]
    elif name == 'unary':
        body, expected = '结果 其 增 '+'非 '*n+'真.', [n % 2 == 0]
    elif name == 'nested-display':
        value = '1'
        for _ in range(n):
            value = '['+value+']'
        setup = '原 取 '+value+'.'
        body, expected = '结果 其 增 (原 为 句).', ['['*n+'1'+']'*n]
    elif name == 'host-reentry':
        setup = "竞 取 外言 '如:竞'. 层 取 [0]. 算 比 左 右: 若 层[0] < "+str(n)+" 则 层[0] 取 层[0]+1. 竞 其 排序 [2,1] (算 比). 层[0] 取 层[0]-1. 然 得 左-右. 法 "
        body, expected = '结果 其 增 (竞 其 排序 [2,1] (算 比)).', [[1.0,2.0]]
    elif name == 'native-reentry':
        import shutil
        compiler = shutil.which(os.environ.get('CC','gcc'))
        if compiler is None:
            raise RuntimeError('Required Windows native compiler missing (not a skip)')
        library = directory/'budget-bridge.dll'
        built = subprocess.run([compiler,'-shared','-O2',str(ROOT/'tests/fixtures/native/bridge.c'),'-o',str(library)],capture_output=True,timeout=60)
        save(evidence/'native-build.json', {'returncode':built.returncode,'compiler':compiler,
              'compiler_sha256':digest(Path(compiler).read_bytes())})
        (evidence/'native-build.stdout').write_bytes(built.stdout)
        (evidence/'native-build.stderr').write_bytes(built.stderr)
        if built.returncode:
            raise RuntimeError('Required native bridge compilation failed')
        save(evidence/'native-dll.json', {'sha256':digest(library.read_bytes())})
        setup = "密 取 外言 '如:密'. 库 取 密 其 动态库 "+json.dumps(str(library),ensure_ascii=False)+". 签 取 密 其 签名 (密 其 i64) ([(密 其 u64)]) 'cdecl'. 原生调 取 库 其 绑定 'invoke_callback' (密 其 签名 (密 其 i64) ([(密 其 指针),(密 其 u64)]) 'cdecl'). 回 取 密 其 回调 签 (算 值: 若 值 其 数 == 0 则 得 1. 然 得 (((原生调 其 调用 [回,(值 其 数)-1]) 其 值) 其 数)+1. 法) (-9)."
        body, expected = f'结果 其 增 (((原生调 其 调用 [回,{n}]) 其 值) 其 数).', [float(n+1)]
    else:
        raise ValueError('Unregistered workload '+name)
    source = "观 取 外言 '如:观'. 图 取 观 其 画布 64 64. 结果 取 []. "+setup+' 图 其 每帧 (作 帧: '+body+' 为).'
    (evidence/'workload.ru').write_text(source,encoding='utf-8')
    vm.execute(parse(source), source_path=directory/'main.ru')
    host.handle({'type':'frame'})
    actual = vm.global_scope.values['结果']
    if actual != expected:
        raise AssertionError('Workload state mismatch: '+name)
    return {'source_sha256':digest(source.encode()), 'state_sha256':digest(json.dumps(actual,ensure_ascii=False).encode()), 'functional_assertions_passed':True}


def child(mode, cadence, descriptor, out):
    sys.path[:0] = [str(ROOT),str(ROOT/'tests')]
    from rulang.graphics_runtime import GraphicsHost
    from rulang.interpreter import Interpreter
    record = {'schema':SCHEMA,'mode':mode,'sample_every':cadence,'descriptor':descriptor,
              'measurement_complete':False,'functional_assertions_passed':False,'events':[],
              'model_version':'historical-baseline' if mode=='baseline-natural' else 'logical-work-v2',
              'watchdog_scope':'direct-host-1s-cooperative-120s-child-not-session-watchdog'}
    out.parent.mkdir(parents=True,exist_ok=True)
    record['runtime_modules']={}
    for module_name in ('rulang.interpreter','rulang.graphics_runtime'):
        module_path=Path(sys.modules[module_name].__file__).resolve()
        expected=(ROOT/(module_name.replace('.','/')+'.py')).resolve()
        if module_path!=expected: raise RuntimeError('Child imported wrong production tree: '+str(module_path))
        record['runtime_modules'][module_name]={'path':str(module_path),'sha256':digest(module_path.read_bytes())}
    original_init, original_handle = GraphicsHost.__init__, GraphicsHost.handle
    def init(host,*args,**kwargs):
        if mode == 'measure':
            from rulang.execution_budget import BudgetPolicy
            kwargs['budget_policy'] = BudgetPolicy(work_limit=None,sample_every=cadence,calibration_only=True)
        original_init(host,*args,**kwargs)
    nesting=[0]
    def handle(host,*args,**kwargs):
        started = time.monotonic()
        before=getattr(host,'budget_snapshot',None)
        depth=nesting[0];nesting[0]+=1
        event=args[0] if args else kwargs.get('event',{})
        row={'event_type':event.get('type') if isinstance(event,dict) else None,
             'nesting_depth':depth,'error':None}
        try:
            return original_handle(host,*args,**kwargs)
        except BaseException as error:
            row['error']={'type':type(error).__name__,'message':str(error)}
            raise
        finally:
            nesting[0]-=1
            snapshot=getattr(host,'budget_snapshot',None)
            fresh=snapshot is not None and snapshot is not before
            row.update(handle_wall_seconds=time.monotonic()-started,charged_event=fresh,
                       ignored_or_unbudgeted=not fresh,
                       snapshot=asdict(snapshot) if fresh else None,
                       truncated=bool(fresh and snapshot.first_exhaustion_kind))
            # Inner snapshots share the outer budget and may still be open.
            # Neither nested snapshots nor ignored inputs are added to a total.
            record['events'].append(row)
            save(out,record)
    try:
        with patch.object(GraphicsHost,'__init__',init), patch.object(GraphicsHost,'handle',handle):
            if descriptor['kind'] in ('ui','contract'):
                suite = unittest.defaultTestLoader.loadTestsFromName(descriptor['case'])
                result = unittest.TextTestRunner(verbosity=2).run(suite)
                record['unittest'] = {'tests_run':result.testsRun,'failures':len(result.failures),
                                     'errors':len(result.errors),'skipped':result.skipped}
                record['functional_assertions_passed'] = result.wasSuccessful() and result.testsRun==1 and not result.skipped
            else:
                with tempfile.TemporaryDirectory(prefix='logical-workload-') as directory:
                    vm = Interpreter(stdout=io.StringIO(),allow_native=descriptor['case']=='native-reentry')
                    host = GraphicsHost(vm,lambda event:None)
                    try:
                        record.update(workload(vm,host,descriptor,Path(directory),out.parent))
                    finally:
                        host.close()
                        from rulang.execution_budget import current_budget
                        record['cleanup']={'structure_depth':vm.structure_depth,'depth':vm.depth,
                            'call_state':list(vm.call_state),'active_budget':current_budget() is not None,
                            'canvas_closed':host.canvas is None}
        record['measurement_complete'] = True
    except BaseException as error:
        record['error'] = {'type':type(error).__name__,'message':str(error),
                           'category':getattr(error,'category',None)}
        traceback.print_exc()
        record['measurement_complete'] = True
    finally:
        if any(event.get('truncated') for event in record['events']):
            record['diagnostic_class']='budget-exhausted'
        elif record['functional_assertions_passed']:
            record['diagnostic_class']='completed'
        else:
            error=record.get('error',{})
            category=error.get('category') or ''
            if 'native' in error.get('message','').lower() and ('compil' in error.get('message','').lower() or 'bridge' in error.get('message','').lower()):
                record['diagnostic_class']='native-build'
            elif '语法' in category or '结构' in category:
                record['diagnostic_class']='parse-or-validation'
            elif error.get('type')=='AssertionError' or record.get('unittest',{}).get('failures',0):
                record['diagnostic_class']='assertion'
            else:
                record['diagnostic_class']='infrastructure-or-runtime'
        record['sample_eligibility']=(
            'complete-logical-measurement' if mode in ('measure','acceptance') and record['functional_assertions_passed'] and any(e.get('charged_event') for e in record['events']) else
            'truncated-budget-measurement' if record['diagnostic_class']=='budget-exhausted' else
            'not-a-logical-measurement')
        save(out,record)
    return 0 if record['functional_assertions_passed'] else 1


def valid_snapshot(snapshot,event,mode):
    if not (isinstance(snapshot,dict) and snapshot.get('schema_version')==2
            and snapshot.get('model_version')=='logical-work-v2'
            and ((type(snapshot.get('work_limit')) is int and snapshot['work_limit']==262144)
                 if mode=='acceptance' else snapshot.get('work_limit') is None)
            and (snapshot.get('closed') is True or (type(event.get('nesting_depth')) is int
                 and event['nesting_depth']>0 and snapshot.get('closed') is False))): return False
    keys=set(('expr','stmt','loop','call','helper_item','bulk_unit'))
    parts=[]
    for name in ('counts','weighted_counts'):
        values=snapshot.get(name)
        if not isinstance(values,list): return False
        try: mapped=dict(values)
        except (TypeError,ValueError): return False
        if set(mapped)!=keys or len(mapped)!=len(values) or any(type(v) is not int or v<0 for v in mapped.values()): return False
        parts.append(mapped)
    raw,weighted=parts
    for key in keys-{'bulk_unit'}:
        if weighted[key]!=raw[key]: return False
    if not ((raw['bulk_unit']+63)//64<=weighted['bulk_unit']<=raw['bulk_unit']): return False
    for name,value in (('raw_total',sum(raw.values())),('total',sum(raw.values())),('charged_units',sum(weighted.values()))):
        if type(snapshot.get(name)) is not int or snapshot[name]!=value: return False
    if type(snapshot.get('attempted_total')) is not int or snapshot['attempted_total']<snapshot['total']: return False
    if type(snapshot.get('attempted_units')) is not int or snapshot['attempted_units']<snapshot['charged_units']: return False
    limit=snapshot.get('work_limit')
    if limit is not None and snapshot['charged_units']>limit: return False
    kind=snapshot.get('first_exhaustion_kind')
    if kind not in (None,'work','time','memory'): return False
    if kind=='work':
        if type(limit) is not int or not (snapshot['charged_units']<=limit<snapshot['attempted_units']): return False
        if snapshot['attempted_total']<=snapshot['total']: return False
    elif snapshot['attempted_units']!=snapshot['charged_units'] or snapshot['attempted_total']!=snapshot['total']:
        return False
    elapsed=snapshot.get('elapsed_sample')
    allocated=snapshot.get('net_allocated_sample')
    if elapsed is not None and (type(elapsed) not in (int,float) or (type(elapsed) is float and not math.isfinite(elapsed))): return False
    if allocated is not None and type(allocated) is not int: return False
    # The runtime compares sampled > deadline strictly. Subtraction can round
    # elapsed back to exactly 1.0, so retain that documented boundary receipt.
    if kind=='time' and (elapsed is None or elapsed<1.0): return False
    if kind=='memory' and (type(allocated) is not int or allocated<=67108864): return False
    return True


def valid_receipt(row,descriptor,mode,cadence):
    if not (isinstance(row,dict) and row.get('schema')==SCHEMA and row.get('mode')==mode
            and row.get('descriptor')==descriptor and type(row.get('sample_every')) is int
            and row['sample_every']==cadence and row.get('measurement_complete') is True
            and type(row.get('functional_assertions_passed')) is bool): return False
    if descriptor['kind'] in ('ui','contract'):
        test=row.get('unittest')
        if not (isinstance(test,dict) and type(test.get('tests_run')) is int and test['tests_run']==1
                and type(test.get('errors')) is int and test['errors']>=0
                and type(test.get('failures')) is int and test['failures']>=0
                and test.get('skipped')==[]): return False
        if row['functional_assertions_passed'] and (test['errors'] or test['failures']): return False
    events=row.get('events')
    if not isinstance(events,list): return False
    if mode in ('measure','acceptance') and descriptor['kind']!='contract' and row['functional_assertions_passed']:
        if not any(e.get('charged_event') is True for e in events): return False
        for event in events:
            if event.get('charged_event') is False:
                if event.get('snapshot') is not None: return False
                continue
            snapshot=event.get('snapshot')
            if not valid_snapshot(snapshot,event,mode): return False
            if snapshot.get('first_exhaustion_kind') is not None or event.get('truncated') is not False: return False
    return True


def observed_budget_stop(row,mode):
    if row.get('functional_assertions_passed') is not False or row.get('diagnostic_class')!='budget-exhausted': return False
    if row.get('cleanup')!={'structure_depth':0,'depth':0,'call_state':[0],'active_budget':False,'canvas_closed':True}: return False
    if row.get('error',{}).get('type')!='BudgetExceeded': return False
    for event in row.get('events',[]):
        snapshot=event.get('snapshot')
        if (event.get('truncated') is True and event.get('charged_event') is True
                and event.get('error',{}).get('type')=='BudgetExceeded'
                and valid_snapshot(snapshot,event,mode) and snapshot.get('closed') is True
                and snapshot.get('first_exhaustion_kind') in ('work','time','memory')):
            if snapshot['first_exhaustion_kind']=='work' and not (type(snapshot.get('work_limit')) is int and snapshot['attempted_units']>snapshot['work_limit']):
                continue
            return True
    return False


def collect(mode,corpus,cadence,out):
    scheduled = plan(mode,corpus,cadence,sys.platform=='win32')
    out.mkdir(parents=True,exist_ok=True)
    report = {'schema':SCHEMA,'mode':mode,'sample_every':cadence,'corpus':corpus,
              'python':sys.version,'platform':platform.platform(),'workflow_head':os.environ.get('GITHUB_SHA'),'actual_repo':repo_identity(),
              'repo_root':str(ROOT),'source_before':source_hashes(),'planned':scheduled,'attempts':[],
              'measurement_complete':False,'functional_assertions_passed':False,'product_acceptance':False,
              'model_version':'historical-baseline' if mode=='baseline-natural' else 'logical-work-v2'}
    save(out/'report.json',report)
    for index, descriptor in enumerate(scheduled):
        directory = out/f'{index:03d}'
        directory.mkdir(exist_ok=True)
        receipt = directory/'result.json'
        receipt.unlink(missing_ok=True)
        attempt = {'descriptor':descriptor,'returncode':None,'timeout':False,'receipt':None}
        report['attempts'].append(attempt)
        save(out/'report.json',report)  # Persist attempted work before spawn.
        stdout=stderr=b''
        try:
            command=[sys.executable,'-X','faulthandler',str(Path(__file__).resolve()),'--mode',mode,
                     '--sample-every',str(cadence),'--repo-root',str(ROOT),'--out',str(receipt.resolve()),'--child',json.dumps(descriptor)]
            completed=subprocess.run(command,cwd=ROOT,capture_output=True,timeout=120)
            stdout,stderr=completed.stdout,completed.stderr
            attempt.update(returncode=completed.returncode,returncode_hex=hex(completed.returncode & 0xffffffff))
            if receipt.exists():
                attempt['receipt']=json.loads(receipt.read_text(encoding='utf-8'))
        except subprocess.TimeoutExpired as error:
            attempt['timeout']=True
            stdout,stderr=error.stdout or b'',error.stderr or b''
        except Exception as error:
            attempt['error']=type(error).__name__+': '+str(error)
        finally:
            for suffix,data in (('stdout',stdout),('stderr',stderr)):
                (directory/suffix).write_bytes(data)
                attempt[suffix+'_sha256']=digest(data)
            save(out/'report.json',report)
    try:
        report['source_after']=source_hashes()
    except Exception as error:
        report['source_after']=None
        report['source_error']=str(error)
    def valid(attempt):
        row=attempt['receipt']
        return (valid_receipt(row,attempt['descriptor'],mode,cadence) and not attempt['timeout']
                and attempt['returncode'] in (0,1))
    report['measurement_complete']=(report['source_before']==report['source_after'] and
        len(report['attempts'])==len(scheduled) and all(valid(a) for a in report['attempts']))
    report['functional_assertions_passed']=report['measurement_complete'] and all(
        a['returncode']==0 and a['receipt'].get('functional_assertions_passed') is True for a in report['attempts'])
    report['measurement_inventory']={key:sum(isinstance(a['receipt'],dict) and a['receipt'].get('sample_eligibility')==key for a in report['attempts']) for key in ('complete-logical-measurement','truncated-budget-measurement','not-a-logical-measurement')}
    if mode=='acceptance':
        def required(descriptor):
            return (descriptor['kind'] in ('ui','contract') or
                    descriptor.get('case')=='text-helper' and descriptor.get('n') in (65536,262144,1048576))
        required_attempts=[a for a in report['attempts'] if required(a['descriptor'])]
        report['required_acceptance_passed']=(report['measurement_complete'] and bool(required_attempts)
            and all(a['returncode']==0 and a['receipt']['functional_assertions_passed'] is True for a in required_attempts))
        pressure=[a for a in report['attempts'] if not required(a['descriptor'])]
        report['pressure_observation_complete']=(report['measurement_complete'] and all(
            a['returncode']==0 and a['receipt']['functional_assertions_passed'] is True
            or a['returncode']==1 and observed_budget_stop(a['receipt'],mode) for a in pressure))
        report['product_interaction_gate']=report['required_acceptance_passed']
        report['product_acceptance']=report['required_acceptance_passed'] and report['pressure_observation_complete']
        report['acceptance_scope']='logical-budget contracts + three original UI cases + large normal text; other stress is observation, not functionality pass'
    save(out/'report.json',report)
    success=(report['product_acceptance'] if mode=='acceptance' else
             report['functional_assertions_passed'] if mode=='contracts' else report['measurement_complete'])
    return 0 if success else 1


def main():
    global ROOT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('baseline-natural','measure','acceptance','contracts'),required=True)
    parser.add_argument('--sample-every',type=int,required=True)
    parser.add_argument('--corpus',choices=('full','sensitivity','ui','large-text'),default='full')
    parser.add_argument('--repo-root',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--child')
    args=parser.parse_args()
    ROOT=args.repo_root.resolve()
    if args.child:
        return child(args.mode,args.sample_every,json.loads(args.child),args.out)
    return collect(args.mode,args.corpus,args.sample_every,args.out)


if __name__=='__main__':
    raise SystemExit(main())
