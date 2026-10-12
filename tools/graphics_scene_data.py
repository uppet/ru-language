"""Export the exact solar fixture for matching native browser benchmarks."""
import argparse, json, sys, time, pickle, statistics
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rulang.frontend import parse
from rulang.interpreter import Interpreter
from rulang.graphics_runtime import GraphicsHost
from rushu.kernel import Session
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, required=True, help='Original precomputed solar fixture with 横表/纵表 arrays')
parser.add_argument('--output', type=Path, default=Path('graphics-bench-data.json'))
args = parser.parse_args()
it=Interpreter();events=[];host=GraphicsHost(it,events.append)
it.execute(parse(args.source.read_text()));host.flush()
data={'initial':events[-1], 'values':{k:it.global_scope.values[k] for k in ('名字','颜色','介绍','轨道','大小','横表','纵表')}, 'frames':[]}
for _ in range(3):host.handle({'type':'frame'});data['frames'].append(events[-1])
args.output.write_text(json.dumps(data,ensure_ascii=False))
event=events[-1];b=pickle.dumps(event)
results={}
for name,fn in [('json_size',lambda:Session._event_size(event)),('pickle_encode',lambda:pickle.dumps(event)),('pickle_decode',lambda:pickle.loads(b))]:
 times=[]
 for _ in range(100):
  start=time.perf_counter();fn();times.append((time.perf_counter()-start)*1000)
 results[name]={'median_ms':statistics.median(times),'mean_ms':statistics.mean(times)}
print(json.dumps({'segment_benchmarks_with_tracemalloc_no_callback_trace':results,'commands':len(event['commands']),'payload_bytes':Session._event_size(event)}))
host.close()
