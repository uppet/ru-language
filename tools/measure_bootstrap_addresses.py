#!/usr/bin/env python3
"""Six predeclared paired application rounds; ordinary address cache, not dense."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

ORDERS = ('ABC', 'BCA', 'CAB', 'CBA', 'ACB', 'BAC')
SCHEMA = 'ru-address-measurement-v1'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def normalize_log(raw, classifier, diagnostic):
    require(isinstance(raw, bytes) and 0 < len(raw) <= 1024*1024, 'bounded nonempty log required')
    text = raw.decode('utf-8').replace('\r\n', '\n')
    require('\r' not in text and text.endswith('\n'), 'complete UTF8 LF records required')
    lines = []
    metrics = []
    for line in text[:-1].split('\n'):
        if line.startswith(('PERF_RU ', 'RU_GUI_SYNC ')):
            metric = diagnostic.metric(line)
            kind, fields = metric['kind'], metric['fields']
            require(kind in classifier.TIMING_FIELDS and set(fields) == classifier.METRIC_FIELDS[kind], 'unexpected metric schema')
            times = classifier.TIMING_FIELDS[kind]
            require(all(math.isfinite(float(fields[k])) and 0 <= float(fields[k]) <= 60000 for k in times), 'invalid metric timing')
            words = line.split()
            line = ' '.join(words[:1]+[word.split('=')[0]+'=<timing>' if word.split('=')[0] in times else word for word in words[1:]])
            metrics.append(metric)
        lines.append(line)
    return tuple(lines), metrics


def summarize(samples):
    """Never substitute a censored runtime for a completed observation."""
    require(len(samples) == 18, 'all eighteen observations required')
    for index, sample in enumerate(samples):
        require(sample['round'] == index//3+1 and sample['strategy'] == ORDERS[index//3][index%3], 'sample order changed')
    pairs = []
    for round_number in range(1,7):
        group = {s['strategy']:s for s in samples if s['round'] == round_number}
        ratios = {}
        for numerator, denominator in (('B','A'),('B','C')):
            left, right = group[numerator], group[denominator]
            if left['classification']['outcome'] == right['classification']['outcome'] == 'passed':
                a, b = left['row']['seconds'], right['row']['seconds']
                require(all(type(v) in (int,float) and math.isfinite(v) and v > 0 for v in (a,b)), 'invalid completed runtime')
                ratios[numerator+'/'+denominator] = a/b
        metric_ratios = {}
        def metric_values(sample):
            output = {}
            if sample['classification'].get('outcome') not in ('passed','valid_censored'): return output
            for metric in sample.get('metrics',[]):
                for field in ('initial_ms','edit_ms','wall_ms','max_tick_ms','max_chunk_ms'):
                    if field in metric['fields']:
                        output[metric['kind']+':'+metric['fields']['size']+':'+field]=float(metric['fields'][field])
            return output
        for numerator,denominator in (('B','A'),('B','C')):
            left,right=metric_values(group[numerator]),metric_values(group[denominator])
            metric_ratios[numerator+'/'+denominator]={key:left[key]/right[key] for key in sorted(left.keys() & right.keys()) if right[key]>0}
        pairs.append({'round':round_number,'completed_ratios':ratios,'observed_metric_ratios':metric_ratios})
    aggregates = {}
    for name in ('B/A','B/C'):
        values = [p['completed_ratios'][name] for p in pairs if name in p['completed_ratios']]
        aggregates[name] = {'completed_pairs':len(values),'values':values,
                            'median':statistics.median(values) if values else None,
                            'minimum':min(values) if values else None,'maximum':max(values) if values else None}
    return {'pairs':pairs,'ratios':aggregates,'statistical_acceptance':False,
            'limitations':['Six paired rounds are a signal study, not a population guarantee.',
                           'Incomplete observations have no completed runtime ratio.',
                           'This measures ordinary address caching, not dense specialization.']}


def run_samples(execute, persist):
    """Keep all scheduled observations even after a product failure; never call it success."""
    samples = []
    unsafe = False
    for round_number, order in enumerate(ORDERS,1):
        for strategy in order:
            sample = {'round':round_number,'strategy':strategy,'attempted':not unsafe}
            try:
                require(not unsafe, 'not executed: prior process/evidence safety uncertain')
                sample.update(execute(round_number,strategy))
                unsafe = sample.get('safe_to_continue') is not True
            except Exception as exc:
                unsafe = True
                sample.update(classification={'outcome':'invalid','evidence_complete':False},
                              error={'type':type(exc).__name__,'message':str(exc)})
            samples.append(sample)
            persist(samples)
    valid = all(s['classification'].get('evidence_complete') is True and
                (s['classification'].get('outcome') == 'passed' or
                 s['strategy'] == 'A' and s['classification'].get('outcome') == 'valid_censored')
                for s in samples)
    return {'schema':SCHEMA,'orders':list(ORDERS),'samples':samples,
            'diagnostic_integrity_passed':valid,'performance_acceptance':False,
            'summary':summarize(samples)}


def reserve_output(root, output):
    root=Path(root).resolve()
    output=Path(output).absolute()
    require(output==root/'measurement.json' and not output.exists() and not output.is_symlink(),
            'output must be the fresh owned measurement.json')
    with output.open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps({'schema':SCHEMA,'status':'prevalidation-pending','performance_acceptance':False})+'\n')
    return output


def write_report(path, value):
    # Every completed or refused slot is durable; final failure never discards partial samples.
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def measure(prepared_path, owned_root, output):
    import importlib
    import os
    import bootstrap_address_build as build
    import diagnose_bootstrap_slot_control as classifier
    import diagnose_bootstrap_editor_fixture as diagnostic
    require(sys.platform == 'win32','real Windows measurement required')
    require(not any(os.environ.get(k) for k in ('GITHUB_TOKEN','GH_TOKEN')), 'download token must not reach measurements')
    prepared_path=Path(prepared_path).resolve()
    require(Path(owned_root).absolute()==prepared_path.parent/'samples','samples must be the fixed prepared evidence sibling')
    # Reserve a fresh destination before validation so refusal is also durable.
    untrusted,_=classifier.read(prepared_path)
    app_hint=Path(untrusted['editor_root']).resolve()
    root=diagnostic.fresh_owned(owned_root,[app_hint,Path(__file__).resolve().parents[1]]).resolve()
    output=reserve_output(root,output)
    try:
        prepared=build.validate_prepared(prepared_path)
        prepared_identity=classifier.identity(prepared_path)
    except Exception as exc:
        write_report(output,{'schema':SCHEMA,'status':'prevalidation-failed','error':str(exc),'diagnostic_integrity_passed':False,'performance_acceptance':False})
        raise
    app=Path(prepared['editor_root']).resolve()
    sys.path.insert(0,str(app/'tools'))
    gate=importlib.import_module('verify_bootstrap_editor_windows')
    require(Path(gate.__file__).resolve()==app/'tools/verify_bootstrap_editor_windows.py','wrong pinned runtime observer')
    classifier.validate_progress_graph(prepared['sources'])
    dependencies=prepared['dependencies']
    env=prepared['runtime_environment']
    api=gate.load_windows_harness(app).Windows()
    frozen_logs=[]
    def revalidate():
        require(classifier.identity(prepared_path)==prepared_identity,'prepared manifest changed')
        require(build.validate_prepared(prepared_path)==prepared,'prepared inputs changed')
        classifier.check(frozen_logs)
    def execute(round_number,strategy):
        revalidate()
        directory=root/('round-%02d-%s'%(round_number,strategy))
        binary=prepared['strategies'][strategy]['binary']
        exe,copies=diagnostic.stage(binary,directory,dependencies,gate)
        expected={'ru_notepad.exe':binary,**{name:dependencies['binaries'][name] for name in (*gate.DLLS,'RuSyntaxWrongAbi.dll')}}
        def check_copies():
            require(set(expected)=={Path(r['path']).name for r in copies} and len(copies)==5,'exact five copies required')
            require(exe==directory/'ru_notepad.exe','wrong staged executable')
            for record in copies:
                path=Path(record['path']);source=expected[path.name]
                require(path==directory/path.name and classifier.identity(path)==record,'copy path/bytes changed')
                require(classifier.identity(source['path'])==source and (record['sha256'],record['size'])==(source['sha256'],source['size']),'copy does not match proven binary/DLL')
        check_copies()
        row=diagnostic.runtime_child(gate,api,exe,env)
        row['partial_log']=diagnostic.partial_log(directory,gate)
        write_report(directory/'raw-observation.json',row)
        classification=classifier.classify_observation(row,directory,diagnostic)
        revalidate();check_copies()
        partial=row['partial_log']
        require(partial.get('available') is True,'sample log missing')
        record=partial['identity']
        require(Path(record['path']).parent==directory,'sample log outside owned directory')
        require(classifier.identity(record['path'],max_bytes=1024*1024)==record,'sample log identity changed')
        with Path(record['path']).open('rb') as stream:raw=stream.read(1024*1024+1)
        require(hashlib.sha256(raw).hexdigest()==record['sha256'] and len(raw)==record['size'],'sample log changed while reading')
        lines,metrics=normalize_log(raw,classifier,diagnostic)
        if classification['outcome']=='passed':
            require(lines==classifier.FULL_PROGRESS_LINES,'complete 149 assertion oracle differs')
        elif classification['outcome']=='valid_censored':
            require(strategy=='A','new candidate/C control must complete')
        require(classifier.identity(record['path'],max_bytes=1024*1024)==record,'sample log changed after parse')
        # Complete actual DLL mapping is required even for successful observations.
        modules=row.get('diagnostic_module_observations',{})
        require(modules.get('pid')==row.get('pid') and modules.get('complete') is True and set(modules.get('verified',{}))==set(gate.DLLS),'actual sample DLL mapping incomplete')
        for name,identity in modules['verified'].items():require(identity==classifier.identity(directory/name),'actual DLL differs from staged bytes')
        frozen_logs.append(record)
        cleanup=row.get('observation',{}).get('cleanup',{})
        safe=classification['outcome'] in ('passed','valid_censored') and cleanup.get('process_reaped') is True and cleanup.get('windows_remaining')==[] and cleanup.get('errors')==[] and cleanup.get('watchdog_stopped') is True
        return {'row':row,'classification':classification,'safe_to_continue':safe,'copies':copies,'metrics':metrics,'log':record}
    def persist(samples):
        write_report(output,{'schema':SCHEMA,'status':'running','prepared':prepared_identity,'orders':list(ORDERS),'samples':samples,'performance_acceptance':False})
    result=run_samples(execute,persist)
    try:revalidate()
    except Exception as exc:result.update(diagnostic_integrity_passed=False,final_integrity_error=str(exc))
    result.update(status='complete' if result['diagnostic_integrity_passed'] else 'failed',prepared=prepared_identity,child_seconds=60,release_permission=False)
    write_report(output,result)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--prepared',required=True)
    parser.add_argument('--owned-root',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    result=measure(args.prepared,args.owned_root,Path(args.output).resolve())
    return 0 if result['diagnostic_integrity_passed'] else 1

if __name__=='__main__':raise SystemExit(main())
