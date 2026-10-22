"""Sequential six-process Windows GUI A/B; preserve the original 30-second gate."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--app-root', type=Path, required=True)
    ap.add_argument('--control', type=Path, required=True)
    ap.add_argument('--incremental', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--first-control', type=Path, help='reuse one completed original-gate run, with matching binary hashes')
    args = ap.parse_args()
    if sys.platform != 'win32': ap.error('actual Windows GUI only')
    builds = {'control': args.control.resolve(), 'incremental': args.incremental.resolve()}
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    receipts = {k: json.loads((p/'experiment-build.json').read_text()) for k, p in builds.items()}
    a, b = receipts['control'], receipts['incremental']
    assert a['incremental'] is False and b['incremental'] is True
    assert a['target'] == b['target'] == 'c-llvm' and a['arm'] == b['arm'] == 'dense'
    for key in ('source_sha256', 'compiler_input_sha256', 'manifest_sha256', 'dependencies'):
        assert a[key] == b[key], key
    before, after = [(p/'runtime.c').read_bytes() for p in builds.values()]
    changes = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
    assert len(before) == len(after) and len(changes) == 1
    offset = changes[0]
    assert before[offset] == ord('0') and after[offset] == ord('1')
    assert before[offset-7:offset+2] == b'v_fact(0)'
    assert (builds['control']/'program.ll').read_bytes() == (builds['incremental']/'program.ll').read_bytes()
    proof = {'same_application_sources': True, 'same_compiler_sources': True, 'same_libraries': True,
             'same_direct_llvm_kernels': True, 'c_source_different_bytes': 1,
             'difference': 'incremental enabled: v_fact(0) -> v_fact(1)',
             'compiler_receipt_activation_ast_changes_counts_dense_flag_only': True}
    (out/'build-pair-proof.json').write_text(json.dumps(proof, indent=2)+'\n')
    runs, counts = [], {'control': 0, 'incremental': 0}
    # Adjacent opposite-order pairs reduce systematic order effects. Each arm
    # still has just three samples, not enough for latency percentiles.
    for index, arm in enumerate(('control', 'incremental', 'incremental', 'control', 'control', 'incremental')):
        counts[arm] += 1
        name = f'{arm}-{counts[arm]}'
        work = out/name
        if index == 0 and args.first_control:
            work.mkdir()
            shutil.copyfile(args.first_control.resolve()/'result.json', work/'result.json')
        else:
            command = [sys.executable, str(Path(__file__).with_name('run_gui.py')),
                       '--app-root', str(args.app_root.resolve()), '--binary-dir', str(builds[arm]),
                       '--output', str(work)]
            with (out/(name+'.log')).open('w', encoding='utf-8') as log:
                completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=600)
            assert completed.returncode == 0, name
        result = json.loads((work/'result.json').read_text(encoding='utf-8'))
        assert result['passed'] is True, name
        assert result['runtime_sha256']['ru_notepad.exe'] == sha(builds[arm]/'ru_notepad.exe') == receipts[arm]['exe_sha256']
        assert all(result['runtime_sha256'][n] == h for n, h in a['dependencies'].items())
        runs.append({'arm': arm, 'name': name, 'result': result})
        (out/'runs.json').write_text(json.dumps(runs, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({'completed': name, 'undo_ms': {
            c['kind']: c['stages'][-1]['wall_ms'] for c in result['markdown_performance']['cases']}}), flush=True)
    comparison = []
    for case in ('many-lines', 'singleline', 'unclosed-fence'):
        for operation in ('open', 'insert', 'backspace', 'undo'):
            row = {'case': case, 'operation': operation}
            for arm in builds:
                stages = [s for run in runs if run['arm'] == arm
                          for c in run['result']['markdown_performance']['cases'] if c['kind'] == case
                          for s in c['stages'] if s['operation'] == operation]
                values = [s['wall_ms'] for s in stages]
                row[arm] = {'wall_ms': values, 'median_ms': statistics.median(values),
                            'min_ms': min(values), 'max_ms': max(values),
                            'published': [s['last_progress']['diagnostic']['published'] for s in stages],
                            'bulkCalls': [s['last_progress']['diagnostic']['bulkCalls'] for s in stages],
                            'undo_commands': [s['undo_commands'] for s in stages]}
            row['speedup'] = row['control']['median_ms']/row['incremental']['median_ms']
            comparison.append(row)
    summary = {'passed': True, 'samples_per_arm': 3, 'order': [r['name'] for r in runs],
               'original_timeout_seconds': 30, 'original_gate_unchanged': True,
               'full_product_acceptance': False, 'remote_ci_executed': False,
               'builds': receipts, 'proof': proof, 'comparison': comparison}
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'comparison': comparison}, indent=2), flush=True)


if __name__ == '__main__': main()
