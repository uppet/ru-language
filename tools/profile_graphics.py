"""Diagnostic microbenchmark; disabled guards are attribution ONLY, never product settings."""
import os
import argparse, cProfile, hashlib, json, statistics, sys, time, tracemalloc
from pathlib import Path
sys.path.insert(0,os.environ.get("RU_BENCH_ROOT",str(Path(__file__).resolve().parents[1])))
from rulang.frontend import parse
from rulang.interpreter import Interpreter
from rulang.graphics_runtime import GraphicsHost
p=argparse.ArgumentParser();p.add_argument('--frames',type=int,default=20);p.add_argument('--mode',choices=['production','no-trace','no-tracemalloc','bare','profile'],default='production');p.add_argument('--source',default=str(Path(__file__).resolve().parents[1] / 'rushu/examples/ruguan/solar-system-math.ru'));a=p.parse_args()
s=Path(a.source).read_text();it=Interpreter();events=[];host=GraphicsHost(it,events.append)
t=time.perf_counter();it.execute(parse(s));host.flush();initial=time.perf_counter()-t
if a.mode in ('no-tracemalloc','bare'):tracemalloc.stop()
original=sys.settrace
if a.mode in ('no-trace','bare'):sys.settrace=lambda _:None
prof=cProfile.Profile();times=[]
try:
 if a.mode=='profile':prof.enable()
 for n in range(a.frames):
  t=time.perf_counter();host.handle({'type':'frame'});times.append((time.perf_counter()-t)*1000);events[:]=events[-1:]
finally:
 sys.settrace=original
 if a.mode=='profile':prof.disable();prof.dump_stats('/tmp/graphics-profile.pstats')
print(json.dumps({'mode':a.mode,'frames':len(times),'initial_ms':initial*1000,'median_ms':statistics.median(times),'mean_ms':statistics.mean(times),'min_ms':min(times),'max_ms':max(times),'commands':len(events[-1]['commands']),'json_bytes':len(json.dumps(events[-1],ensure_ascii=False,separators=(',',':')).encode()),'source_sha256':hashlib.sha256(s.encode()).hexdigest()}))
host.close()
