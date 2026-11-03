#!/usr/bin/env python3
"""Paired legacy structural vs generation fixed-point ABI analysis.

This diagnostic harness never executes Ru/native code and never changes the
production step budget. An explicit --diagnostic-step-limit affects these child
analyses only. Each mode runs in a fresh process; timing covers NativeCPlan,
not parsing or C compilation. Peak RSS covers the complete worker process.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def worker(args):
    import resource
    from rulang.frontend import RuError
    from rulang.modules import load_module_graph
    from rulang import native_c
    graph = load_module_graph(args.source)
    native_c.MAX_ANALYSIS_STEPS = args.diagnostic_step_limit
    if args.worker == 'structural':
        native_c.NativeCPlan._fixed_point_state = native_c.NativeCPlan._state
    reports = []
    started = time.perf_counter()
    result = {'mode': args.worker}
    try:
        plan = native_c.NativeCPlan(graph, diagnostics=reports.append)
        result['thunks_sha256'] = hashlib.sha256(plan.emit_c().encode()).hexdigest()
        result['shapes'] = [[s.result, list(s.params)] for s in plan.signatures]
        result['status'] = 'completed'
    except RuError as error:
        result.update(status='rejected', error=str(error))
    result['wall_seconds'] = time.perf_counter() - started
    result['peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result['analysis'] = reports[-1]
    result['source_sha256'] = {str(path): hashlib.sha256(text.encode()).hexdigest()
                               for path, text in graph.sources.items()}
    print(json.dumps(result, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--diagnostic-step-limit', type=int, default=200000)
    parser.add_argument('--worker', choices=('structural', 'generation'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.repeats < 3 or args.diagnostic_step_limit < 1:
        parser.error('require >=3 repeats and positive diagnostic limit')
    if not sys.platform.startswith('linux'):
        parser.error('peak RSS units are currently verified on Linux only')
    if args.worker:
        worker(args)
        return
    if args.output is None:
        parser.error('--output is required')
    samples = []
    for repeat in range(args.repeats):
        order = ('structural', 'generation') if repeat % 2 == 0 else ('generation', 'structural')
        for mode in order:
            run = subprocess.run([sys.executable, __file__, str(args.source.resolve()),
                                  '--worker', mode, '--diagnostic-step-limit', str(args.diagnostic_step_limit)],
                                 text=True, capture_output=True, check=True)
            result = json.loads(run.stdout)
            result['repeat'] = repeat
            samples.append(result)
            print(f'{repeat + 1}/{args.repeats} {mode}: {result["wall_seconds"]:.3f}s {result["status"]}', file=sys.stderr, flush=True)
    completed = [sample for sample in samples if sample['status'] == 'completed']
    report = {
        'schema': 1, 'platform': platform.platform(), 'python': sys.version,
        'analyzer_sha256': hashlib.sha256((ROOT/'rulang/native_c.py').read_bytes()).hexdigest(),
        'compiler_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'compiler_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
        'measurement': 'fresh-process planner wall seconds, excluding parsing; whole worker peak RSS KiB; paired alternating order',
        'production_step_limit': 200000, 'diagnostic_step_limit': args.diagnostic_step_limit,
        'same_sources': all(sample['source_sha256'] == samples[0]['source_sha256'] for sample in samples),
        'all_completed': len(completed) == len(samples),
        'same_completed_thunks': bool(completed) and len({sample['thunks_sha256'] for sample in completed}) == 1,
        'median_seconds': {mode: statistics.median(s['wall_seconds'] for s in samples if s['mode'] == mode)
                           for mode in ('structural', 'generation')},
        'samples': samples,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
