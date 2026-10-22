#!/usr/bin/env python3
"""Compare complete notebook-cell latency for Python and native Ru AST kernels.

Includes parsing, validation, interpretation, GC, IPC and polling. It does not
measure pure arithmetic throughput or compare AOT-generated guest programs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rushu.kernel import Session

CASES = (
    ('small', '显 6*7.', '42\n'),
    ('loop_10000', '总 取 0. 循 10000 次 总 取 总+1. 环. 显 总.', '10000\n'),
    ('closure_1000', '算 造: 值 取 0. 算 加: 值 取 值+1. 得 值. 法. 得 算 加. 法. '
     '计 取 造. 最后 取 0. 循 1000 次 最后 取 计(). 环. 显 最后.', '1000\n'),
    ('arrays_2000', '循 2000 次 列 取 [1,2,3]. 环. 显 列 其 量.', '3\n'),
)


def execute(session, source, expected):
    after = session.snapshot()['cursor']
    started = time.perf_counter()
    session.execute(source, 'benchmark')
    output, errors, first = [], [], None
    while True:
        result = session.poll(after)
        after = result['cursor']
        for event in result['events']:
            if event['type'] == 'output' and event['stream'] == 'stdout':
                if first is None:
                    first = time.perf_counter()-started
                output.append(event['text'])
            if event['type'] == 'error':
                errors.append(event['message'])
        if result['state'] == 'dead' or errors:
            raise RuntimeError('benchmark cell failed: '+repr(errors))
        if result['state'] == 'idle' and not result.get('more'):
            break
        if time.perf_counter()-started > 120:
            raise RuntimeError('benchmark timed out')
        time.sleep(.0005)
    elapsed = time.perf_counter()-started
    actual = ''.join(output)
    if actual != expected:
        raise RuntimeError('benchmark output mismatch: '+repr(actual))
    return dict(seconds=elapsed, first_output_seconds=first,
                stdout_sha256=hashlib.sha256(actual.encode()).hexdigest())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-kernel', type=Path, required=True)
    parser.add_argument('--repetitions', type=int, default=7)
    parser.add_argument('-o', '--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if not 1 <= args.repetitions <= 50:
        parser.error('repetitions must be between 1 and 50')
    binary = args.native_kernel.resolve(strict=True)
    sessions = {'python': Session(), 'ru_ast': Session(native_kernel=binary)}
    try:
        # Finish process initialization before steady-cell measurements.
        for session in sessions.values():
            execute(session, '显 0.', '0\n')
        cases = []
        for name, source, expected in CASES:
            for session in sessions.values():
                execute(session, source, expected)
            samples = {engine: [] for engine in sessions}
            for repetition in range(args.repetitions):
                order = list(sessions) if repetition % 2 == 0 else list(reversed(sessions))
                for engine in order:
                    samples[engine].append(execute(sessions[engine], source, expected))
            cases.append(dict(name=name, source=source, expected=expected, samples=samples,
                median_seconds={engine: statistics.median(row['seconds'] for row in rows)
                                for engine, rows in samples.items()}))
        report = dict(schema=1, platform=sys.platform, system=platform.platform(),
            python=sys.version, machine=platform.machine(), repetitions=args.repetitions,
            native_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
            method='warm persistent cells; parse+execute+GC+IPC+0.5ms polling; interleaved engines; one warmup per case; no CPU affinity',
            cases=cases)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({case['name']: case['median_seconds'] for case in cases}))
        return 0
    finally:
        for session in sessions.values():
            session.close()


if __name__ == '__main__':
    raise SystemExit(main())
