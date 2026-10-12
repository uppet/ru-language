"""Measure real GraphicsHost work without changing any callback budgets.

Run with the desired runtime checkout on PYTHONPATH. This measures host work,
not browser presentation FPS or equivalence to native JavaScript Canvas.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time
from rulang.frontend import parse
from rulang.interpreter import Interpreter
from rulang.graphics_runtime import GraphicsHost

parser = argparse.ArgumentParser()
parser.add_argument('sources', nargs='+', type=Path)
parser.add_argument('--frames', type=int, default=20)
args = parser.parse_args()
for path in args.sources:
    source = path.read_text()
    interpreter, events = Interpreter(), []
    host = GraphicsHost(interpreter, events.append)
    try:
        start = time.perf_counter()
        interpreter.execute(parse(source))
        host.flush()
        init_ms = (time.perf_counter() - start) * 1000
        samples = []
        for _ in range(args.frames):
            start = time.perf_counter()
            host.handle({'type': 'frame'})
            samples.append((time.perf_counter() - start) * 1000)
        print(json.dumps({'source': str(path), 'sha256': hashlib.sha256(source.encode()).hexdigest(),
            'frames': len(samples), 'init_ms': init_ms, 'callback_mean_ms': statistics.mean(samples),
            'callback_median_ms': statistics.median(samples), 'callback_max_ms': max(samples),
            'commands': len(events[-1]['commands']), 'budgets_unchanged': True,
            'measurement': 'Python GraphicsHost; excludes HTTP, browser scheduling and rendering'}, ensure_ascii=False), flush=True)
    finally:
        host.close()
