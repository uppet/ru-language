#!/usr/bin/env python3
"""Measure small-string storage cost in two frozen generated C runtimes.

Input C files must expose v_array, v_str, v_drop and ru_gc (the slice benchmark
outputs do). This is a runtime mechanism probe, not a Ru end-to-end workload.
One rooted array retains all separately allocated one-byte strings. The array
is identical in both runs. Metadata and allocator rounding both affect RSS.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys

from benchmark_string_slices import MEASURE, sha

BODY = r'''
int main(void) {
    size_t count = COUNT, i;
    Val *initial = (Val *)calloc(count, sizeof(Val));
    Val holder;
    if (!initial) return 90;
    holder = v_array(count, initial, 1);
    free(initial);
    for (i = 0; i < count; ++i) {
        Val text = v_str("x");
        ((RuArray *)holder.heap)->items[i] = text;
        v_drop(text);
    }
    printf("%zu %zu %zu\n", count, sizeof(RuString), ru_live);
    v_drop(holder); ru_gc();
    return ru_live ? 91 : 0;
}
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before-c',type=Path,required=True)
    parser.add_argument('--after-c',type=Path,required=True)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--count',type=int,default=1000000)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--cc',default=shutil.which('gcc'))
    args=parser.parse_args()
    if args.count<1 or args.repeats<3 or not args.cc or not sys.platform.startswith('linux'):
        parser.error('Linux, positive count, >=3 repeats and C compiler required')
    directory=args.directory.resolve()
    directory.mkdir(parents=True,exist_ok=True)
    result_path=directory/'results.json'
    if result_path.exists():
        parser.error('directory already has results')
    env=dict(os.environ)
    for key in ('RU_GC_THRESHOLD','RU_GC_STATS'):
        env.pop(key,None)
    report={'schema':1,'measured_at':datetime.now(timezone.utc).isoformat(),'count':args.count,
            'measurement':'runtime probe; retained distinct one-byte strings plus identical array; whole process including cleanup; isolated small runner child RSS KiB',
            'compiler':subprocess.check_output([args.cc,'--version'],text=True).splitlines()[0], 'programs':{}}
    for name,path in [('before',args.before_c),('after',args.after_c)]:
        raw=path.read_text(encoding='utf-8')
        original_hash=sha(raw.encode('utf-8'))
        raw,n=re.subn(r'\bint main\(int argc, char \*\*argv\)', 'int ru_original_main(int argc, char **argv)',raw)
        if n!=1:
            raise RuntimeError('expected exactly one generated C main')
        cfile=directory/(name+'.c')
        cfile.write_text(raw+BODY.replace('COUNT',str(args.count)),encoding='utf-8')
        binary=directory/name
        command=[args.cc,'-std=c99','-O2',str(cfile),'-lm','-o',str(binary)]
        subprocess.run(command,check=True,capture_output=True)
        report['programs'][name]={'input_c_sha256':original_hash,'probe_c_sha256':sha(cfile.read_bytes()),'compile_command':command,'samples':[]}
    for repeat in range(args.repeats):
        for name in (['before','after'] if repeat%2==0 else ['after','before']):
            result=subprocess.run([sys.executable,'-c',MEASURE,str(directory/name)],env=env,capture_output=True,text=True,check=True,timeout=610)
            sample=json.loads(result.stdout)
            sample['repeat']=repeat
            if sample['returncode'] or sample['stderr'] or int(sample['stdout'].split()[0])!=args.count:
                raise RuntimeError(sample)
            report['programs'][name]['samples'].append(sample)
            print(json.dumps({'engine':name,**sample}),flush=True)
            result_path.write_text(json.dumps(report,indent=2)+'\n')
    for row in report['programs'].values():
        row['median_seconds']=statistics.median(s['seconds'] for s in row['samples'])
        row['median_peak_rss_kib']=statistics.median(s['peak_rss_kib'] for s in row['samples'])
    result_path.write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':
    main()
