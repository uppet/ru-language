#!/usr/bin/env python3
"""Compare equivalent binary64 workloads: Ru C, direct LLVM, Dart native AOT.

Opt-in measurements, never timing assertions. Examples:
  python3 tools/benchmark_aot.py --dart /path/to/dart --output dist/aot.json

Reported elapsed time includes process creation, runtime startup, computation
and final output. n=1 is a startup-dominated sample, not an isolated measurement
of runtime initialization. RSS is the process peak from GNU time, in KiB.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang import __version__
from rulang.cli import build
from rulang.frontend import parse


WORKLOADS = {
    'numeric_loop': (
        "次数 取 外参[0] 为 数. 累计 取 0. 位 取 0.\n"
        "循 次数 次 累计 取 (累计+位)%1000003. 位 取 位+1. 环.\n显 累计.",
        "double sum=0; for(int i=0;i<n;i++){sum=(sum+i.toDouble())%1000003.0;} print(sum.toStringAsFixed(0));"),
    'closure_calls': (
        "次数 取 外参[0] 为 数. 操作 取 造 0. 累计 取 0.\n"
        "循 次数 次 累计 取 (累计+(操作 1))%1000003. 环.\n显 累计.",
        "final next=make(0); double sum=0; for(int i=0;i<n;i++){sum=(sum+next(1))%1000003.0;} print(sum.toStringAsFixed(0));"),
    'array_allocation': (
        "次数 取 外参[0] 为 数. 位 取 0. 累计 取 0. 保留 取 [空].\n"
        "循 次数 次\n 列 取 [位,位+1,位+2]. 保留[0] 取 列.\n 累计 取 (累计+列[1])%1000003. 位 取 位+1.\n环.\n显 累计. 显 保留[0][2].",
        "final keep=<List<double>?>[null]; double sum=0; for(int i=0;i<n;i++){final x=i.toDouble(); final row=<double>[x,x+1,x+2]; keep[0]=row; sum=(sum+row[1])%1000003.0;} print(sum.toStringAsFixed(0)); print(keep[0]![2].toStringAsFixed(0));"),
}
RU_FACTORY = '算 造 起点 为 数: 值 取 起点. 算 加 步 为 数: 值 取 值+步. 得 值. 法. 得 算 加. 法.\n'
DART_FACTORY = 'double Function(double) make(double x) {return (double step) {x+=step; return x;};}\n'


def expected(name, n):
    total = n*(n-1)//2 if name == 'numeric_loop' else n*(n+1)//2
    output = str(total % 1000003)+'\n'
    if name == 'array_allocation':
        output += str(n+1)+'\n'
    return output


def run_checked(command, *, env, expected_output=None):
    start = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=120)
    elapsed = time.perf_counter()-start
    if result.returncode:
        raise RuntimeError(f'{command[0]} failed ({result.returncode}): {result.stderr}')
    if expected_output is not None and result.stdout != expected_output:
        raise RuntimeError(f'{command[0]} produced {result.stdout!r}; expected {expected_output!r}')
    return elapsed, result.stdout, result.stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dart', default=shutil.which('dart'), help='Dart SDK executable; used only for the comparison')
    parser.add_argument('--iterations', type=int, default=1000000)
    parser.add_argument('--repeats', type=int, default=7)
    parser.add_argument('--warmups', type=int, default=2)
    parser.add_argument('--work-directory', type=Path, default=ROOT/'bin/aot-benchmark')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.dart:
        parser.error('Dart SDK is required for a measured Dart AOT baseline; supply --dart')
    if args.iterations < 2 or args.iterations > 10000000 or args.repeats < 3 or args.warmups < 0:
        parser.error('require 2..10000000 iterations, >=3 repeats and >=0 warmups')
    timer = Path('/usr/bin/time')
    if not sys.platform.startswith('linux') or not timer.exists():
        parser.error('M1 measurements require Linux x86-64 and GNU /usr/bin/time')
    directory = args.work_directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    env = {key:value for key,value in os.environ.items() if key not in ('RU_GC_STATS','RU_GC_THRESHOLD')}
    env['DART_SUPPRESS_ANALYTICS'] = 'true'
    dart = str(Path(args.dart).resolve())
    _, dart_version, dart_stderr = run_checked([dart,'--version'],env=env)
    clang = shutil.which('clang-14')
    if not clang:
        parser.error('clang-14 is required for matched Ru C and LLVM comparisons')
    report = {
        'schema':1, 'measured_at':datetime.now(timezone.utc).isoformat(), 'ru_version':__version__,
        'platform':platform.platform(), 'machine':platform.machine(), 'processor':platform.processor(),
        'dart_version':(dart_version+dart_stderr).strip(),
        'clang_version':run_checked([clang,'--version'],env=env)[1].splitlines()[0],
        'iterations':args.iterations, 'repeats':args.repeats, 'warmups':args.warmups,
        'measurement':'whole-process wall seconds including startup, computation and output; peak RSS in KiB',
        'note':'Initial M1 baseline, not evidence of Dart-level performance; n=1 is startup-dominated.',
        'workloads':{},
    }
    for name,(ru_body,dart_body) in WORKLOADS.items():
        ru_source = (RU_FACTORY if name == 'closure_calls' else '') + '算 元初 外参 为 句 阵:\n' + ru_body + '\n得 0.\n法.\n'
        dart_source = (DART_FACTORY if name == 'closure_calls' else '') + 'void main(List<String> args) { final n=int.parse(args[0]); '+dart_body+' }\n'
        ru_path, dart_path = directory/(name+'.ru'), directory/(name+'.dart')
        ru_path.write_text(ru_source,encoding='utf-8')
        dart_path.write_text(dart_source,encoding='utf-8')
        entry = {'sources':{'ru':ru_source,'dart':dart_source}, 'backends':{}}
        programs = {}
        for backend in ('c','llvm','dart'):
            output = directory/(name+'-'+backend)
            start = time.perf_counter()
            if backend == 'dart':
                command=[dart,'compile','exe',str(dart_path),'-o',str(output)]
                run_checked(command,env=env)
                compiler=report['dart_version']
            else:
                command=[sys.executable,'ru','build',str(ru_path),'--target',backend,'-o',str(output)]
                command += ['--cc' if backend=='c' else '--llvm-clang',clang]
                _,compiler=build(parse(ru_source),ru_path,output,target=backend,
                                 **({'cc':clang} if backend=='c' else {'llvm_clang':clang}))
            compile_seconds=time.perf_counter()-start
            programs[backend]=output
            entry['backends'][backend]={'compile_seconds':compile_seconds,'build_command':command,
                'compiler':compiler,'artifact_bytes':output.stat().st_size,
                'artifact_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'samples':{}}
        for n in (1,args.iterations):
            oracle=expected(name,n)
            samples={backend:[] for backend in programs}
            for backend,program in programs.items():
                for _ in range(args.warmups):
                    run_checked([str(program),str(n)],env=env,expected_output=oracle)
            rng=random.Random(20261021+n)
            for repeat in range(args.repeats):
                order=list(programs); rng.shuffle(order)
                for backend in order:
                    rss_path=directory/'peak-rss.txt'
                    command=[str(timer),'-f','%M','-o',str(rss_path),str(programs[backend]),str(n)]
                    elapsed,_,_=run_checked(command,env=env,expected_output=oracle)
                    samples[backend].append({'wall_seconds':elapsed,'peak_rss_kib':int(rss_path.read_text().strip())})
            for backend,values in samples.items():
                elapsed=[item['wall_seconds'] for item in values]
                entry['backends'][backend]['samples'][str(n)]={'expected_stdout':oracle,'raw':values,
                    'median_seconds':statistics.median(elapsed),'min_seconds':min(elapsed),'max_seconds':max(elapsed),
                    'median_peak_rss_kib':statistics.median(item['peak_rss_kib'] for item in values)}
        report['workloads'][name]=entry
        print('Measured '+name,file=sys.stderr,flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(args.output)


if __name__ == '__main__':
    main()
