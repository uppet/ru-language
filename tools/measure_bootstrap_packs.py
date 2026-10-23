#!/usr/bin/env python3
"""Six predeclared paired application rounds; ordinary argument pack, not dense."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

ORDERS = ('ABC', 'BCA', 'CAB', 'CBA', 'ACB', 'BAC')
SCHEMA = 'ru-pack-measurement-v1'
# These are the complete timing keys in the immutable 149-assertion fixture.
METRIC_GROUPS = (
    ('PERF_RU', '100000', ('initial_ms', 'edit_ms', 'max_tick_ms', 'max_chunk_ms')),
    ('PERF_RU', '1000000', ('initial_ms', 'edit_ms', 'max_tick_ms', 'max_chunk_ms')),
    ('RU_GUI_SYNC', '1000000', ('wall_ms', 'max_tick_ms', 'max_chunk_ms')),
)
METRIC_KEYS = tuple(sorted(kind+':'+size+':'+field
    for kind,size,fields in METRIC_GROUPS for field in fields))
TIMING_FIELDS = frozenset(field for _,_,fields in METRIC_GROUPS for field in fields)
WALL_MEDIAN_LIMIT = 1.03
WALL_PAIR_LIMIT = 1.05
WALL_REQUIRED_PAIRS = 5
METRIC_REVIEW_LIMIT = 1.05


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


def finite_number(raw, *, positive=False):
    # bool is not a measured number. Preserve invalid raw data in the receipt,
    # but never turn it into a ratio or a non-standard JSON NaN/Infinity token.
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        return None
    try:
        value = float(raw)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        return None
    return value


def json_raw(raw):
    if isinstance(raw, float) and not math.isfinite(raw):
        return repr(raw)
    if raw is None or isinstance(raw, (str, int, float, bool)):
        return raw
    return repr(raw)


def metric_observation(sample):
    """Keep all eleven keys and every duplicate value, never intersect or overwrite."""
    raw_values = {key:[] for key in METRIC_KEYS}
    issues = []
    groups_seen = {}
    metrics = sample.get('metrics', [])
    if not isinstance(metrics, list):
        issues.append({'reason':'malformed_metric_records','raw':json_raw(metrics)})
        metrics = []
    for index, metric in enumerate(metrics):
        if not isinstance(metric, dict) or not isinstance(metric.get('fields'), dict):
            issues.append({'reason':'malformed_metric_record','index':index,'raw':json_raw(metric)})
            continue
        fields = metric['fields']
        group = str(metric.get('kind'))+':'+str(fields.get('size'))
        if group not in {kind+':'+size for kind,size,_ in METRIC_GROUPS}:
            issues.append({'reason':'unexpected_metric_group','index':index,'group':group})
        groups_seen[group] = groups_seen.get(group, 0) + 1
        if groups_seen[group] > 1:
            issues.append({'reason':'duplicate_metric_group','index':index,'group':group})
        for field in sorted(TIMING_FIELDS & fields.keys()):
            key = group+':'+field
            if key not in raw_values:
                issues.append({'reason':'unexpected_metric_key','index':index,'key':key,
                               'raw':json_raw(fields[field])})
            else:
                raw_values[key].append(json_raw(fields[field]))
    values = {}
    for key, raws in raw_values.items():
        reason, value = None, None
        if not raws:
            reason = 'missing_metric'
        elif len(raws) != 1:
            reason = 'duplicate_metric'
        else:
            value = finite_number(raws[0])
            if value is None or value > 60000:
                reason, value = 'invalid_metric_value', None
        values[key] = {'raw_values':raws,'value':value,'undefined_reason':reason}
        if reason:
            issues.append({'reason':reason,'key':key})
    runtime = sample.get('row')
    raw_seconds = json_raw(runtime.get('seconds') if isinstance(runtime, dict) else None)
    seconds = finite_number(raw_seconds, positive=True)
    return {'outcome':sample.get('classification', {}).get('outcome'),
            'evidence_complete':sample.get('classification', {}).get('evidence_complete') is True,
            'seconds':{'raw':raw_seconds,'value':seconds,
                       'undefined_reason':None if seconds is not None else 'invalid_or_missing_runtime'},
            'metrics':values,'issues':issues,'metric_data_complete':not issues}


def ratio_record(numerator, denominator, *, completed):
    """A reason-bearing pair exists even when no defensible ratio exists."""
    reasons = []
    if not completed:
        reasons.append('observations_not_both_complete')
    for label, row in (('numerator',numerator),('denominator',denominator)):
        if row.get('undefined_reason'):
            reasons.append(label+':'+row['undefined_reason'])
    left, right = numerator.get('value'), denominator.get('value')
    if right == 0:
        reasons.append('zero_denominator')
    if left is None or right is None:
        if not reasons:
            reasons.append('missing_numeric_value')
    ratio = None if reasons else left/right
    if ratio is not None and not math.isfinite(ratio):
        reasons.append('nonfinite_ratio')
        ratio = None
    return {'numerator':numerator,'denominator':denominator,'ratio':ratio,
            'undefined_reasons':reasons}


def aggregate_pairs(rows):
    values = [row['ratio'] for row in rows if row['ratio'] is not None]
    return {'completed_pairs':len(values),'values':values,'per_round':rows,
            'median':statistics.median(values) if values else None,
            'minimum':min(values) if values else None,'maximum':max(values) if values else None}


def summarize(samples):
    """No censored substitution, silent missing metrics, or automatic acceptance."""
    require(len(samples) == 18, 'all eighteen observations required')
    for index, sample in enumerate(samples):
        require(sample['round'] == index//3+1 and sample['strategy'] == ORDERS[index//3][index%3], 'sample order changed')
    pairs, flags = [], []
    data_complete = True
    for round_number in range(1,7):
        group = {s['strategy']:metric_observation(s) for s in samples if s['round'] == round_number}
        for strategy, row in group.items():
            if row['outcome'] != 'passed' or not row['evidence_complete']:
                data_complete = False
                flags.append({'reason':'incomplete_observation','round':round_number,
                              'strategy':strategy,'outcome':row['outcome']})
            if not row['metric_data_complete'] or row['seconds']['value'] is None:
                data_complete = False
                flags.append({'reason':'invalid_or_missing_measurements','round':round_number,
                              'strategy':strategy,'issues':row['issues'],
                              'seconds_reason':row['seconds']['undefined_reason']})
        ratios, wall_pairs, metric_ratios, metric_pairs = {}, {}, {}, {}
        for numerator, denominator in (('B','A'),('B','C')):
            name = numerator+'/'+denominator
            left, right = group[numerator], group[denominator]
            completed = all(row['outcome']=='passed' and row['evidence_complete'] for row in (left,right))
            wall = ratio_record(left['seconds'],right['seconds'],completed=completed)
            wall_pairs[name] = wall
            if wall['ratio'] is not None:
                ratios[name] = wall['ratio']
            else:
                flags.append({'reason':'undefined_wall_ratio','round':round_number,
                              'comparison':name,'undefined_reasons':wall['undefined_reasons']})
            details = {key:ratio_record(left['metrics'][key],right['metrics'][key],completed=completed)
                       for key in METRIC_KEYS}
            metric_pairs[name] = details
            metric_ratios[name] = {key:row['ratio'] for key,row in details.items()}
            for key,row in details.items():
                if row['ratio'] is None:
                    flags.append({'reason':'undefined_metric_ratio','round':round_number,
                                  'comparison':name,'key':key,'undefined_reasons':row['undefined_reasons']})
        pairs.append({'round':round_number,'observations':group,'wall_pairs':wall_pairs,
                      'completed_ratios':ratios,'observed_metric_ratios':metric_ratios,
                      'metric_pairs':metric_pairs})
    aggregates, metric_aggregates = {}, {}
    for name in ('B/A','B/C'):
        aggregates[name] = aggregate_pairs([{'round':p['round'],**p['wall_pairs'][name]} for p in pairs])
        metric_aggregates[name] = {key:aggregate_pairs([
            {'round':p['round'],**p['metric_pairs'][name][key]} for p in pairs]) for key in METRIC_KEYS}
    wall = aggregates['B/A']
    within = sum(value <= WALL_PAIR_LIMIT for value in wall['values'])
    wall_screen = (wall['completed_pairs']==6 and wall['median'] <= WALL_MEDIAN_LIMIT
                   and within >= WALL_REQUIRED_PAIRS)
    if not wall_screen:
        flags.append({'reason':'whole_fixture_screen_not_satisfied','median':wall['median'],
                      'completed_pairs':wall['completed_pairs'],'pairs_at_most_limit':within})
    # Flag every outlier without deleting it. A fifth good pair cannot conceal
    # the sixth adverse observation; flags demand independent review, not retry.
    for row in wall['per_round']:
        if row['ratio'] is not None and row['ratio'] > WALL_PAIR_LIMIT:
            flags.append({'reason':'whole_fixture_individual_regression','round':row['round'],
                          'comparison':'B/A','ratio':row['ratio']})
    for key, rows in metric_aggregates['B/A'].items():
        if rows['median'] is not None and rows['median'] > METRIC_REVIEW_LIMIT:
            flags.append({'reason':'metric_median_regression','comparison':'B/A',
                          'key':key,'median':rows['median']})
        for row in rows['per_round']:
            if row['ratio'] is not None and row['ratio'] > METRIC_REVIEW_LIMIT:
                flags.append({'reason':'metric_individual_regression','comparison':'B/A',
                              'key':key,'round':row['round'],'ratio':row['ratio']})
    return {'pairs':pairs,'ratios':aggregates,'metric_ratios':metric_aggregates,
            'expected_metric_keys':list(METRIC_KEYS),'measurement_integrity_complete':data_complete,
            'engineering_screen':{'whole_fixture_screen_passed':wall_screen,
                'thresholds':{'whole_fixture_median_max':WALL_MEDIAN_LIMIT,
                    'whole_fixture_individual_max':WALL_PAIR_LIMIT,
                    'whole_fixture_required_pairs':WALL_REQUIRED_PAIRS,
                    'metric_review_ratio':METRIC_REVIEW_LIMIT},
                'whole_fixture_pairs_at_most_limit':within,
                'requires_further_review':bool(flags),'review_flags':flags,
                'crossover_required':False,'automatic_acceptance':False,
                'independent_review_required':True},
            'statistical_acceptance':False,
            'limitations':['Six paired rounds are an engineering screen, not a population guarantee.',
                           'Every raw observation and every undefined ratio reason is retained; no outlier is removed.',
                           'Passing the screen is not merge or performance acceptance; B/C is descriptive only.',
                           'This measures ordinary argument packing, not dense specialization.']}


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
                s['classification'].get('outcome') == 'passed'
                for s in samples)
    summary = summarize(samples)
    valid = valid and summary['measurement_integrity_complete']
    return {'schema':SCHEMA,'orders':list(ORDERS),'samples':samples,
            'diagnostic_integrity_passed':valid,'performance_acceptance':False,
            'summary':summary}


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
    import bootstrap_pack_build as build
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
