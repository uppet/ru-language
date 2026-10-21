#!/usr/bin/env python3
"""Record minimal interpreter benchmark timings; no thresholds.

Runs a few small programs that stress the hottest interpreter paths —
statement dispatch, function calls, arrays, and maps — and prints elapsed
seconds per benchmark.  CI logs these values so regressions can be spotted
by eye or mined later; nothing fails on timing here.
"""
import argparse
import json
import sys
import time

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rulang.frontend import parse
from rulang.interpreter import Interpreter

BENCHMARKS = {
    "fib20": """\
算 斐 值 为 数:
    若 值 <= 1 则
        得 值.
    另
        得 (斐 值: 值 - 1) + (斐 值: 值 - 2).
    然.
法.
(斐 值: 20).
""",
    "array_fill_sum": """\
列 取 [0].
循 99999 次
    列 其 增 0.
环.
和 取 0.
位 取 0.
循 100000 次
    和 取 和 + 列[位].
    位 取 位 + 1.
环.
""",
    "map_insert_query": """\
账目 取 典: 成.
位 取 0.
循 10000 次
    账目 其 增 目:位 相:位.
    位 取 位 + 1.
环.
查 取 0.
位 取 0.
循 10000 次
    查 取 查 + (账目 其 查 位).
    位 取 位 + 1.
环.
""",
}


def run_once(source):
    interpreter = Interpreter()
    program = parse(source)
    start = time.perf_counter()
    interpreter.execute(program)
    return time.perf_counter() - start


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit one JSON object")
    parser.add_argument("--repeat", type=int, default=1,
                        help="runs per benchmark; reports the median (default 1)")
    args = parser.parse_args()

    results = {}
    for name, source in BENCHMARKS.items():
        timings = sorted(run_once(source) for _ in range(max(1, args.repeat)))
        results[name] = timings[len(timings) // 2]

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        for name in sorted(results):
            print(f"{name}: {results[name]:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
