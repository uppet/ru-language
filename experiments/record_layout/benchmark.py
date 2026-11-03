#!/usr/bin/env python3
"""Actual Ru dynamic records versus packed four-u8 records. Linux host experiment.

Both algorithms are generated from Ru source by the same Compiler. Only the
existing test-only POSIX platform adapter and phase clock instrumentation are
inserted in emitted C. No hand-written C hot loop or unsupported production
Linux native ABI is introduced.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from rulang.compiler import Compiler
from rulang.frontend import parse
from test_native_c_runtime import portable_test_source

CLOCK = r'''
#define _POSIX_C_SOURCE 200809L
#include <time.h>
#include <stdio.h>
#include <stdlib.h>
static struct timespec bm_times[3];
static void bm_mark(int n) { if(clock_gettime(CLOCK_MONOTONIC, &bm_times[n])) abort(); }
static double bm_elapsed(int a, int b) {
 return (double)(bm_times[b].tv_sec-bm_times[a].tv_sec)+(double)(bm_times[b].tv_nsec-bm_times[a].tv_nsec)/1e9;
}
'''


def source(kind, count, scans):
    declarations = ("形 记录: 甲 为 数. 乙 为 数. 丙 为 数. 丁 为 数. 象.\n"
                    if kind == 'dynamic' else "密 取 外言 '如:密'.\n")
    setup = '数据 取 [].' if kind == 'dynamic' else f'数据 取 密 其 缓冲 {count * 4}.'
    fill = ("数据 其 增 (新 记录 甲:甲 乙:乙 丙:丙 丁:丁)." if kind == 'dynamic' else
            "数据 其 写字节 (位*4) 甲. 数据 其 写字节 (位*4+1) 乙. 数据 其 写字节 (位*4+2) 丙. 数据 其 写字节 (位*4+3) 丁.")
    read = ("项 取 数据[位]. 甲 取 项 其 甲. 乙 取 项 其 乙. 丙 取 项 其 丙. 丁 取 项 其 丁." if kind == 'dynamic' else
            "甲 取 数据 其 读字节 (位*4). 乙 取 数据 其 读字节 (位*4+1). 丙 取 数据 其 读字节 (位*4+2). 丁 取 数据 其 读字节 (位*4+3).")
    return declarations + f'''显 111111111.
{setup}
位 取 0.
循 {count} 次
    甲 取 位%251. 乙 取 (位+17)%251. 丙 取 (位+63)%251. 丁 取 (位+127)%251.
    {fill}
    位 取 位+1.
环.
显 222222222.
总 取 0.
循 {scans} 次
    位 取 0.
    循 {count} 次
        {read}
        总 取 总+甲+2*乙+3*丙+4*丁.
        位 取 位+1.
    环.
环.
显 333333333.
显 总.
''' + ("数据 其 关闭.\n" if kind == 'packed' else '')


def expected(count, scans):
    return str(sum(i%251+2*((i+17)%251)+3*((i+63)%251)+4*((i+127)%251) for i in range(count))*scans)+'\n'


def build(kind, count, scans, directory):
    ru = source(kind, count, scans)
    path = directory/f'{kind}.ru'
    path.write_text(ru, encoding='utf-8')
    generated = (Compiler(parse(ru), str(path)).compile() if kind == 'dynamic' else portable_test_source(ru, str(path)))
    (directory/f'{kind}.c').write_text(generated, encoding='utf-8')
    instrumented = CLOCK+generated
    for index, marker in enumerate((111111111, 222222222, 333333333)):
        line = ru.splitlines().index(f'显 {marker}.')+1
        pattern = rf'v_print\([^;\n]+, {line}\);'
        replacement = f'bm_mark({index});'
        if index == 2:
            replacement += r' fprintf(stderr,"BM_PHASES %.9f %.9f\n",bm_elapsed(0,1),bm_elapsed(1,2));'
        instrumented, matches = re.subn(pattern, lambda _:replacement, instrumented)
        if matches != 1:
            raise AssertionError((kind, line, matches))
    timed = directory/f'{kind}-timed.c'
    timed.write_text(instrumented, encoding='utf-8')
    exe = directory/kind
    command = ['gcc','-std=c99','-O2',str(timed),'-lm','-ldl','-pthread','-o',str(exe)]
    subprocess.run(command,check=True,capture_output=True,text=True)
    return {'source_sha256':hashlib.sha256(ru.encode()).hexdigest(),
            'generated_c_sha256':hashlib.sha256(generated.encode()).hexdigest(),
            'instrumented_c_sha256':hashlib.sha256(instrumented.encode()).hexdigest(),
            'compiler_command':command}


RUNNER = r"""
#define _DEFAULT_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/wait.h>
#include <sys/resource.h>
int main(int argc, char **argv) {
    if (argc != 2) return 125;
    pid_t pid=fork();
    if(pid<0)return 125;
    if(!pid){execl(argv[1],argv[1],(char *)NULL);_exit(126);}
    int status; struct rusage usage;
    if(wait4(pid,&status,0,&usage)<0)return 125;
    fprintf(stderr,"BM_RSS %ld\n",usage.ru_maxrss);
    return WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
}
"""


def runner(directory):
    path=directory/'measure.c'
    path.write_text(RUNNER,encoding='utf-8')
    exe=directory/'measure'
    subprocess.run(['gcc','-std=c99','-O2',str(path),'-o',str(exe)],check=True,capture_output=True,text=True)
    return exe


def run(exe, expected_output, output):
    env = {k:v for k,v in os.environ.items() if k not in ('RU_GC_THRESHOLD','RU_GC_STATS')}
    started = time.perf_counter()
    measurement_runner=exe.parent/'measure'
    if not measurement_runner.exists():
        runner(exe.parent)
    result = subprocess.run([str(measurement_runner),str(exe)],env=env,
                            capture_output=True,text=True,check=True,timeout=180)
    elapsed = time.perf_counter()-started
    if result.stdout != expected_output:
        raise AssertionError((result.stdout,expected_output,result.stderr))
    phases = re.search(r'BM_PHASES ([0-9.]+) ([0-9.]+)',result.stderr)
    if not phases:
        raise AssertionError(result.stderr)
    return {'initialization_seconds':float(phases[1]),'scan_seconds':float(phases[2]),
            'whole_process_seconds':elapsed,'peak_rss_kib':int(re.search(r'BM_RSS (\d+)',result.stderr)[1]),
            'stdout':result.stdout,'stderr':result.stderr}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count',type=int,default=100000)
    parser.add_argument('--scans',type=int,default=4)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--directory',type=Path,default=HERE/'results')
    parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args()
    if not sys.platform.startswith('linux') or args.count<1 or args.count>1000000 or not 1 <= args.scans <= 1000 or args.repeats<3:
        parser.error('Linux host, 1..1000000 records, 1..1000 scans, >=3 repeats required')
    args.directory.mkdir(parents=True,exist_ok=True)
    artifacts={kind:build(kind,args.count,args.scans,args.directory) for kind in ('dynamic','packed')}
    report={'schema':1,'count':args.count,'scans':args.scans,'repeats':args.repeats,
            'expected_output':expected(args.count,args.scans),'platform':platform.platform(),
            'python':sys.version,'gcc':subprocess.run(['gcc','--version'],capture_output=True,text=True,check=True).stdout.splitlines()[0],
            'source_commit':subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip(),
            'runtime_sha256':{name:hashlib.sha256((ROOT/'rulang'/name).read_bytes()).hexdigest() for name in ('runtime.h','native_runtime.h')},
            'artifacts':artifacts,'samples':[]}
    if not args.prepare_only:
        for kind in ('dynamic','packed'):
            run(args.directory/kind,report['expected_output'],args.directory/'rss.txt')
        for repeat in range(args.repeats):
            for kind in (('dynamic','packed') if repeat%2==0 else ('packed','dynamic')):
                result=run(args.directory/kind,report['expected_output'],args.directory/'rss.txt')
                result.update(kind=kind,repeat=repeat)
                report['samples'].append(result)
                print(kind,repeat,result['initialization_seconds'],result['scan_seconds'],result['peak_rss_kib'],flush=True)
        report['medians']={kind:{metric:statistics.median(s[metric] for s in report['samples'] if s['kind']==kind)
                                for metric in ('initialization_seconds','scan_seconds','whole_process_seconds','peak_rss_kib')}
                           for kind in ('dynamic','packed')}
    (args.directory/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
