# Graphics host performance profile (2026-10-12)

## Scope and reproduction

Baseline: `/workspace/shared/ru-callback-limits`, reported Ru 0.13.3 (wip6d9f540).
Candidate: `/workspace/shared/ru-graphics-optimization`.
Fixture: `/workspace/shared/solar-demo/solar-system.ru`, SHA-256
`8886cc05c812e1119afb2655060797a4bdf8507b01b92c0dae96ae5b931c7e8c`.
The **same source and same initial 50 frames** were executed in both candidates.
42 drawing commands and approximately 5 KiB JSON per frame. This version uses
precomputed 720-frame coordinate tables; this benchmark does not pretend that
adding trigonometric built-ins alone speeds this fixture up.

These absolute paths describe this experiment; the original user-provided fixture
and raw result file are not shipped with the repository. To reproduce that
specific comparison, provide the identical SHA-256 fixture in both checkouts.
From the candidate checkout:

```
RU_BENCH_ROOT=/workspace/shared/ru-callback-limits python tools/profile_graphics.py --frames 50 --source /workspace/shared/solar-demo/solar-system.ru
python tools/profile_graphics.py --frames 50 --source /workspace/shared/solar-demo/solar-system.ru
```

For a self-contained benchmark using the shipped natural-loop math example:

```
python tools/profile_graphics.py --frames 50 --mode production
PYTHONPATH=. python tools/benchmark_animation_examples.py rushu/examples/ruguan/solar-system-math.ru --frames 50
```

This is a different fixture; do not compare its latency to the table below as a
runtime-only speedup. `graphics_scene_data.py --source ORIGINAL_FIXTURE --output
DATA.json` is an optional exporter for the original precomputed-table fixture,
not for the shipped natural-loop example.

Three alternating sequential baseline/candidate processes, no concurrent benchmark
started by this worker. Shared cloud host scheduling still introduces noise; no
CPU affinity or isolation was claimed. Source parsing/table initialization is
reported separately, not mixed into per-frame callback cost.

| Round | Baseline median ms | Candidate median ms | Baseline mean ms | Candidate mean ms |
|---|---:|---:|---:|---:|
| 1 | 49.327 | 39.344 | 50.883 | 40.872 |
| 2 | 48.572 | 36.923 | 54.768 | 40.962 |
| 3 | 51.381 | 42.690 | 53.864 | 46.072 |

Median-of-run-medians improves 49.327 to 39.344 ms (20.2% less callback time,
1.25x throughput). Ranges and means show this is not a precision latency claim.
Raw results: `/workspace/shared/graphics-alternating-benchmark.jsonl`.

## Cost attribution (diagnostic experiments only)

Initial 12-frame baseline run medians:

| Diagnostic mode | ms/frame |
|---|---:|
| Production trace and tracemalloc | 48.110 |
| No line trace, tracemalloc remains | 11.475 |
| Line trace, no tracemalloc | 3.662 |
| Neither diagnostic guard | 0.752 |

These costs are **not additive**: tracing creates temporary integers/frame
objects whose allocations are themselves tracked by tracemalloc. Diagnostic
modes temporarily disable protections only inside the standalone profiling
process; they are not supported product execution modes or proposed changes.
Production code retains both protections.

cProfile (also perturbing timing) over 12 baseline frames: 0.715 s total;
Interpreter.expr 0.707 s inclusive / 0.402 s self; graphics_member 0.224 s
inclusive / 0.139 s self; Canvas.command 0.040 s inclusive, of which json.dumps
0.034 s. Nested inclusive numbers overlap and must not be summed. The dominant
problem is Python interpreter dispatch under full line tracing plus allocation
tracking; 42 JSON command encodes are a secondary cost.

`python tools/graphics_scene_data.py` exports exact scene data and measures
serialization outside the callback trace but with tracemalloc on. Observed
median per complete 42-command snapshot: JSON UTF-8 sizing 0.514 ms; pickle encode
0.010 ms; pickle decode 0.077 ms. These are codec CPU times, **not measured IPC or
HTTP round trips**. The main server normally does not enable tracemalloc, so its
JSON sizing need not cost as much as this conservative host-process experiment.

## Candidate changes

1. Hoist the constant graphics member parameter schema out of each call, into a
MappingProxyType of tuples. Argument binding, names and all validation remain
unchanged. No per-canvas mutable object or argument value is cached.
2. Count every trace `line` event using a cached-small-integer countdown between
checks. Accumulate blocks of 128 only at the previous checking points. A final
check reconstructs the exact total from full blocks plus the partial block.
Tracing scope, time/memory check cadence and callback exception cleanup are
unchanged; no Python frame is excluded.

The previous code allowed final counts up to and including 500000; final 500001
failed. During a callback it checked at multiples of 128, so the first failing
in-callback line was 500096. Candidate retains exactly this existing behavior,
including the pre-existing check granularity. Dedicated tests cover 0, 127, 128,
129, 499999, 500000, 500001, 500096 and longer overruns.

## Existing protection semantics, unchanged

- 1 s monotonic deadline; check every 128 traced Python lines and at return.
- 500000 *Python implementation line events*, not Ru source lines/AST nodes.
- `tracemalloc.start(1)` already uses the minimum traceback depth. Baseline is
current live traced allocation bytes at canvas creation; compare current live
bytes minus that baseline to 64 MiB. This is not peak memory, RSS, GPU memory or
all-system memory. A temporary allocation freed before a sampling point may not
trip it. Tracing lasts until canvas close (unless another owner started it).
- POSIX address-space soft limit during callbacks is the minimum of 512 MiB and
existing finite limits, restored in finally.
- Out-of-process 10 s graphics watchdog, process/session generation checks,
stop/reset and graphics data validation remain untouched.

## Frontend and transport constraints (not changed)

The runtime and browser scene validation cap FPS at 30. Browser dispatch has a
`ceil(1000/fps)+2 ms` minimum spacing: the fixture's 20 FPS becomes at least
52 ms; a 30 FPS request becomes at least 36 ms. It waits for graphics_done before
sending another event, so only one callback is in flight. POST acceptance is not
callback completion. A GET starts after POST; if it arrives too early, the
browser currently waits 50 ms before polling again while work is pending.
Thus an approximately 39 ms callback can be presented on a roughly 50+ ms cycle
even before expensive rendering or remote HTTP latency. Every frame sends a
complete scene and browser validation/retention/rendering runs on that snapshot.

No polling interval, rate limit, server API, watchdog or frontend validation was
modified. Lowering 50 to 16 ms would increase GET load and cannot remove the
Python cost. A bounded long-poll events endpoint could wake on new events while
preserving generation/cursor checks and single flight, but needs a separate
protocol/concurrency design and tests for stop, reset, HTTP disconnect, timeout,
thread usage, and stale sessions. It has not been implemented.

The candidate alone does **not** establish near-native JS Canvas performance.
A same-scene browser benchmark must distinguish JS scene computation, actual
Canvas draw CPU, end-to-end presentation intervals, and bridge waits. The data
export provides the exact source's positions, labels, descriptions and scenes
for that comparison. Reaching native execution throughput likely requires a
separately reviewed execution architecture (for example isolated JS/worker
execution with equivalent lifecycle/resource controls), not removing guardrails.

## Final integrated expression optimization

The final candidate also puts common mutually exclusive expression kinds first
and dispatches arithmetic/comparison operators directly rather than constructing
operator-lambda dictionaries on every evaluation. Expression order, short
circuiting, type checks, zero division, finite checks and diagnostic nodes remain
unchanged. All Python lines still produce trace events; fewer conditionals and
temporary objects reduce actual implementation work, without skipping events.

With all production guards active, the shipped natural-loop example
`rushu/examples/ruguan/solar-system-math.ru` (SHA-256
`c0dceb4e68275d545e060119c211bcff7496a846e5f64322540a7c927ce66085`)
had three baseline run medians 127.13/113.22/117.04 ms, host-only medians
100.42/102.10/95.88 ms, and final medians 35.87/38.22/41.77 ms. The baseline here
includes the new mathematics library so **the exact same natural-loop source**
runs on both sides. Median of run medians falls from 117.04 to 38.22 ms, about
67% less callback time or 3.06× callback throughput.

The original expanded/precomputed fixture separately recorded final medians
19.93/21.42 ms, compared with its own approximately 49 ms baseline. Do not use
one fixture's baseline and the other's final value to claim a speedup.

These final runs followed the initial alternating runs; they were not randomized
matched pairs on isolated hardware. Shared-host noise is visible. Natural-source
initialization took roughly 12–30 ms, compared with roughly 194–317 ms for the
original table-building source; initialization is excluded from callback timing.
Both scenes retain 42 commands per running frame.

Callback throughput is not presentation FPS, and these results do not establish
near-native Canvas performance. The integrated real-browser measurements and
full regression results are recorded in [release validation](rushu-0.3.2-validation.md).
