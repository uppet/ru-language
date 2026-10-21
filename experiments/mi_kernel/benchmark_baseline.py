#!/usr/bin/env python3
"""Local reproducible experiment, not a performance assertion or product benchmark.

No packages, remote access, or production edits. Timings include array allocation,
input construction, and all repeated scans, excluding process launch/compilation.
C and JS common workload has the same semantic bytes but different storage.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / 'benchmark-output'
EXE = '.exe' if os.name == 'nt' else ''
CC = os.environ.get('CC', 'gcc')
CLOCK = r'''#if defined(_WIN32)
#include <windows.h>
typedef LARGE_INTEGER BmTime;
static void bm_now(BmTime *value) { if (!QueryPerformanceCounter(value)) abort(); }
static double bm_seconds(BmTime a, BmTime b) {
    LARGE_INTEGER frequency;
    if (!QueryPerformanceFrequency(&frequency) || frequency.QuadPart <= 0) abort();
    return (double)(b.QuadPart-a.QuadPart)/(double)frequency.QuadPart;
}
#else
#include <time.h>
typedef struct timespec BmTime;
static void bm_now(BmTime *value) { if (clock_gettime(CLOCK_MONOTONIC, value)) abort(); }
static double bm_seconds(BmTime a, BmTime b) {
    return (double)(b.tv_sec-a.tv_sec)+(b.tv_nsec-a.tv_nsec)/1e9;
}
#endif
'''
PATTERN = [65, 13, 10, 66, 10, 67, 13, 68]

def run(args, **kw):
    return subprocess.run([str(x) for x in args], check=True, text=True,
                          capture_output=True, cwd=ROOT, **kw)

def summary(values):
    xs = sorted(values)
    return {'samples_seconds': values, 'median_seconds': statistics.median(xs),
            'p95_seconds': xs[max(0, math.ceil(.95 * len(xs)) - 1)]}

def ordinary_source(n, repetitions):
    assert n % len(PATTERN) == 0
    return (HERE / 'baseline.ru').read_text() + f'''\n字节们 取 [].
循 {n // len(PATTERN)} 次
''' + ''.join(f'    字节们 其 增 {x}.\n' for x in PATTERN) + f'''环.
总数 取 0.
循 {repetitions} 次
    总数 取 总数 + (数行界 字节:字节们).
环.
显 总数.
'''

def build_ordinary(n, repetitions):
    src = OUT / 'ordinary.ru'
    src.write_text(ordinary_source(n, repetitions))
    c = OUT / 'ordinary.c'
    exe = OUT / ('ordinary' + EXE)
    run([sys.executable, ROOT/'ru', 'build', src, '-o', exe, '--emit-c', c])
    original = c.read_text()
    # Instrument the compiler's actual main; keep an uninstrumented artifact.
    timed = '#define _POSIX_C_SOURCE 200809L\n#include <stdlib.h>\n' + CLOCK + original
    start = 'int main(int argc, char **argv) {'
    assert timed.count(start) == 1
    timed = timed.replace(start, start + '\nBmTime bm_a,bm_b; bm_now(&bm_a);')
    finish = 'ru_shutdown(); return status;'
    assert timed.count(finish) == 1
    timed = timed.replace(finish, 'ru_shutdown(); bm_now(&bm_b); fprintf(stderr,"BM_SECONDS %.9f\\n", bm_seconds(bm_a,bm_b)); return status;')
    tc = OUT/'ordinary-timed.c'; tc.write_text(timed)
    run([CC,'-O2','-std=c99',tc,'-lm','-o',exe])
    js = OUT/'ordinary.js'
    run([sys.executable, ROOT/'ru','build',src,'--target','js','-o',js])
    original_js = js.read_text()
    (OUT/'ordinary-timed.js').write_text('const bmStart=process.hrtime.bigint();\n' + original_js + '\nconsole.error("BM_SECONDS",Number(process.hrtime.bigint()-bmStart)/1e9);\n')
    return {'generated_c_bytes': len(original.encode()), 'generated_js_bytes':len(original_js.encode()), 'timed_executable_bytes':exe.stat().st_size}

def measure(command, expected, samples):
    # One warmup separate from recorded observations.
    for i in range(samples + 1):
        p=run(command)
        if p.stdout.strip() != str(expected):
            raise AssertionError((command,p.stdout,expected))
        line=[x for x in p.stderr.splitlines() if x.startswith('BM_SECONDS ')][-1]
        if i == 0: values=[]
        else: values.append(float(line.split()[1]))
    return summary(values)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bytes',type=int,default=65536)
    ap.add_argument('--repetitions',type=int,default=4)
    ap.add_argument('--samples',type=int,default=9)
    ap.add_argument('--ordinary-only',action='store_true')
    args=ap.parse_args()
    if args.bytes <= 0 or args.bytes % 8 or args.repetitions < 1 or args.samples < 2:
        ap.error('bytes must be positive multiple of 8; repetitions >= 1; samples >= 2')
    OUT.mkdir(exist_ok=True)
    sizes=build_ordinary(args.bytes,args.repetitions)
    expected=(args.bytes//8)*3*args.repetitions
    result={'workload':{'bytes':args.bytes,'repetitions':args.repetitions,'pattern':PATTERN,'expected_checksum':expected},
            'measurement':'in-process end-to-end (input construction + repeated scans + cleanup); compilation and process launch excluded',
            'limitations':['ASCII/raw bytes only; ordinary dynamic-number array (inline Val numbers in C) is not native contiguous byte storage','No ru_notepad integration; this is a host-specific kernel experiment, not a GUI speedup claim','No allocation/boxing counter instrumentation; sizes are actual artifact bytes, not memory-use measurements','Timing is host-specific and noisy; p95 is nearest-rank over recorded samples; do not compare different platforms as an optimization effect'],
            'source_commit':os.environ.get('GITHUB_SHA'),
            'environment':{'clock':'QueryPerformanceCounter' if os.name=='nt' else 'CLOCK_MONOTONIC','platform':platform.platform(),'python':sys.version,'gcc':run([CC,'--version']).stdout.splitlines()[0],'node':run(['node','--version']).stdout.strip()},
            'ordinary_artifacts':sizes,
            'ordinary_c':measure([OUT/('ordinary' + EXE)],expected,args.samples),
            'ordinary_js':measure(['node',OUT/'ordinary-timed.js'],expected,args.samples)}
    if not args.ordinary_only:
        result.update(typed(args,expected))
        for name,expected_hash in result['kernel_sha256'].items():
            if hashlib.sha256((HERE/'generated'/name).read_bytes()).hexdigest()!=expected_hash:
                raise RuntimeError('Kernel changed during benchmark; rerun after generator freezes')
    (OUT/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

def typed(args,expected):
    header=(HERE/'generated'/'kernel.h').resolve()
    kernel_paths=[header,HERE/'generated'/'kernel.js']
    kernel_hashes={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in kernel_paths}
    # Separate translation units, no LTO: prevent compiler hoisting repeated scans.
    calls=OUT/'typed-calls.c'
    calls.write_text('#include "../generated/kernel.h"\n'+\
        'MiResult bm_direct(const uint8_t *p,uint32_t n) { return mi_kernel(p,n,0); }\n'+\
        'MiResult bm_wrapper(MiOwner *o,uint32_t n) { return mi_scan(o,0,n,0); }\n')
    main=OUT/'typed-main.c'
    main.write_text(r'''#define _POSIX_C_SOURCE 200809L
#include <time.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "HEADER"
MiResult bm_direct(const uint8_t *,uint32_t);
MiResult bm_wrapper(MiOwner *,uint32_t);
CLOCK_IMPLEMENTATION
int main(int argc,char **argv) {
 if(argc!=4)return 2;
 uint32_t n=(uint32_t)strtoul(argv[1],0,10), reps=(uint32_t)strtoul(argv[2],0,10);
 int wrapper=!strcmp(argv[3],"wrapper");
 BmTime start,ready,scanned,end;
 bm_now(&start);
 uint8_t *data=malloc(n); if(!data)return 3;
 const uint8_t pattern[8]={65,13,10,66,10,67,13,68};
 for(uint32_t i=0;i<n;++i)data[i]=pattern[i%8];
 MiOwner owner={data,n,0,0};
 bm_now(&ready);
 uint64_t checksum=0;
 for(uint32_t i=0;i<reps;++i){
  MiResult r=wrapper?bm_wrapper(&owner,n):bm_direct(data,n);
  if(r.status)return 4;checksum+=r.count;
 }
 bm_now(&scanned);
 if(mi_close(&owner)!=MI_OK || owner.borrows)return 5;
 free(data);
 printf("%llu\n",(unsigned long long)checksum);
 bm_now(&end);
 fprintf(stderr,"BM_SETUP %.9f\nBM_SCAN %.9f\nBM_SECONDS %.9f\n",bm_seconds(start,ready),bm_seconds(ready,scanned),bm_seconds(start,end));
 return 0;
}
'''.replace('HEADER','../generated/kernel.h').replace('CLOCK_IMPLEMENTATION',CLOCK))
    exe=OUT/('typed' + EXE)
    run([CC,'-O2','-std=c99',calls,main,'-o',exe])
    js=OUT/'typed-benchmark.js'
    js.write_text(r'''const {Owner,scan}=require('KERNEL');
const n=Number(process.argv[2]), reps=Number(process.argv[3]);
const start=process.hrtime.bigint();
const pattern=[65,13,10,66,10,67,13,68];
const data=new Uint8Array(n);
for(let i=0;i<n;++i)data[i]=pattern[i%8];
const beforeOwner=process.hrtime.bigint();
const owner=new Owner(data); // n-byte explicit owner input copy
const ready=process.hrtime.bigint();
let checksum=0;
for(let i=0;i<reps;++i){const r=scan(owner,0,n,0);if(r.status)throw Error(r.status);checksum+=r.count;}
const scanned=process.hrtime.bigint();
if(owner.borrows||owner.close())throw Error('owner cleanup');
console.log(checksum);
const end=process.hrtime.bigint();
console.error('BM_OWNER_COPY',Number(ready-beforeOwner)/1e9);
console.error('BM_SETUP',Number(ready-start)/1e9);
console.error('BM_SCAN',Number(scanned-ready)/1e9);
console.error('BM_SECONDS',Number(end-start)/1e9);
'''.replace('KERNEL','../generated/kernel.js'))
    def with_parts(command):
        observed={}
        for i in range(args.samples+1):
            p=run(command)
            if p.stdout.strip()!=str(expected):raise AssertionError(p.stdout)
            if i:
                for line in p.stderr.splitlines():
                    if line.startswith('BM_'):
                        key,value=line.split()
                        observed.setdefault(key,[]).append(float(value))
        return {key:summary(values) for key,values in observed.items()}
    for x in kernel_paths:
        if hashlib.sha256(x.read_bytes()).hexdigest()!=kernel_hashes[x.name]:
            raise RuntimeError('Kernel changed during benchmark; rerun after generator freezes')
    return {'kernel_sha256':kernel_hashes,'typed_artifacts':{'generated_header_bytes':header.stat().st_size,'generated_js_bytes':(HERE/'generated'/'kernel.js').stat().st_size,'benchmark_executable_bytes':exe.stat().st_size},
            'typed_notes':['C separate compilation units with -O2 and no LTO prevent repeated-call hoisting','C borrows trusted contiguous storage, 0 input copy bytes; JS owner creation explicitly copies bytes once','Setup/scan subtimings only available for typed harness; ordinary end-to-end includes runtime initialization, input construction, output and GC cleanup; typed includes input construction, output and explicit owner close (not forced JS GC)','Typed C direct includes one exported function call per scan; wrapper adds checked synchronous borrow; JS is semantic comparison, not native performance'],
            'typed_c_direct':with_parts([exe,args.bytes,args.repetitions,'direct']),
            'typed_c_wrapper':with_parts([exe,args.bytes,args.repetitions,'wrapper']),
            'typed_js_wrapper':with_parts(['node',js,args.bytes,args.repetitions])}

if __name__=='__main__': main()
