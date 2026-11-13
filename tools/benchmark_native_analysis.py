#!/usr/bin/env python3
"""Paired legacy structural vs generation fixed-point ABI analysis.

This diagnostic harness never executes Ru/native code and never changes the
production analyzer. By default there is no whole-program step quota. An
explicit --diagnostic-step-limit stops these diagnostic child analyses only.
Each mode runs the production two-stage factory in a fresh process. Planning
and thunk generation are reported separately; neither includes parsing or C
compilation. --strategy full selects the precise reference engine instead.
Peak RSS covers the complete worker process.
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
    from rulang.native_tiered import build_native_c_plan
    from unittest.mock import patch
    graph = load_module_graph(args.source)

    class DiagnosticLimit(RuError):
        pass

    original_charge = native_c.NativeCPlan._charge
    visits = 0
    def diagnostic_charge(plan, node):
        nonlocal visits
        original_charge(plan, node)
        visits += 1
        if args.diagnostic_step_limit is not None and visits > args.diagnostic_step_limit:
            raise DiagnosticLimit('explicit diagnostic step limit reached', category='诊断停止')
    fixed_point = (native_c.NativeCPlan._state if args.worker == 'structural'
                   else native_c.NativeCPlan._fixed_point_state)
    reports = []
    started = time.perf_counter()
    result = {'mode': args.worker, 'strategy': args.strategy, 'diagnostic_step_limit': args.diagnostic_step_limit}
    try:
        builder = build_native_c_plan if args.strategy == 'tiered' else native_c.NativeCPlan
        with patch.object(native_c.NativeCPlan, '_charge', diagnostic_charge), \
                patch.object(native_c.NativeCPlan, '_fixed_point_state', fixed_point):
            plan = builder(graph, diagnostics=reports.append)
        result['planning_seconds'] = time.perf_counter() - started
        emit_started = time.perf_counter()
        result['thunks_sha256'] = hashlib.sha256(plan.emit_c().encode()).hexdigest()
        result['emit_seconds'] = time.perf_counter() - emit_started
        result['shapes'] = [[s.result, list(s.params)] for s in plan.signatures]
        result['status'] = 'completed'
    except DiagnosticLimit as error:
        result.update(status='diagnostic-limit', error=str(error))
    except RuError as error:
        result.update(status='rejected', error=str(error))
    result['wall_seconds'] = time.perf_counter() - started
    result['peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result['analysis'] = reports[-1] if reports else None
    result['source_sha256'] = {str(path): hashlib.sha256(text.encode()).hexdigest()
                               for path, text in graph.sources.items()}
    print(json.dumps(result, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--strategy', choices=('tiered', 'full'), default='tiered')
    parser.add_argument('--diagnostic-step-limit', type=int, default=None,
                        help='optional child-only diagnostic stop; omitted means no step quota')
    parser.add_argument('--worker', choices=('structural', 'generation'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.repeats < 3 or (args.diagnostic_step_limit is not None and args.diagnostic_step_limit < 1):
        parser.error('require >=3 repeats and a positive diagnostic limit when supplied')
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
            command = [sys.executable, __file__, str(args.source.resolve()), '--worker', mode, '--strategy', args.strategy]
            if args.diagnostic_step_limit is not None:
                command += ['--diagnostic-step-limit', str(args.diagnostic_step_limit)]
            run = subprocess.run(command, text=True, capture_output=True, check=True)
            result = json.loads(run.stdout)
            result['repeat'] = repeat
            samples.append(result)
            print(f'{repeat + 1}/{args.repeats} {mode}: {result["wall_seconds"]:.3f}s {result["status"]}', file=sys.stderr, flush=True)
    completed = [sample for sample in samples if sample['status'] == 'completed']
    # Recovery/source archives may have no Git metadata; never invent a commit.
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, None
    report = {
        'schema': 2, 'platform': platform.platform(), 'python': sys.version,
        'analyzer_sha256': hashlib.sha256((ROOT/'rulang/native_c.py').read_bytes()).hexdigest(),
        'factory_sha256': hashlib.sha256((ROOT/'rulang/native_tiered.py').read_bytes()).hexdigest(),
        'strategy': args.strategy,
        'compiler_commit': commit, 'compiler_dirty': dirty,
        'measurement': 'fresh-process wall_seconds includes planning and thunk emission; planning_seconds/emit_seconds separate; parsing excluded; whole worker peak RSS KiB; paired alternating order',
        'production_step_limit': None, 'diagnostic_step_limit': args.diagnostic_step_limit,
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
