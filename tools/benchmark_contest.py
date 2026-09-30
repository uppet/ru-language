#!/usr/bin/env python3
"""Opt-in correctness/performance probe; no time-based CI assertion.

Run: python3 tools/benchmark_contest.py --tokens 500000 --lines 100000
Reports per-process elapsed seconds and peak RSS (KiB, using /usr/bin/time or a small native wait4 probe).
The interpreter/native programs consume identical files and must match a Python
reference byte-for-byte. Native C is recompiled with common C11/O2 flags, no -lm.
"""
import argparse
from datetime import datetime, timezone
import json
import os
import random
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.compiler import Compiler
from rulang.modules import load_module_graph

TOKEN_SOURCE = """竞 取 外言 '如:竞赛'.
入 取 竞 其 读入.
和 取 0. 数量 取 0.
循
    值 取 入 其 数.
    若 值 == 空 则 破. 然
    和 取 和+值. 数量 取 数量+1.
环
显 和. 显 数量.
"""
LINE_SOURCE = """竞 取 外言 '如:竞赛'.
入 取 竞 其 读入. 出 取 竞 其 蓄出. 数量 取 0.
循
    文 取 入 其 行.
    若 文 == 空 则 破. 然
    数量 取 数量+1.
    出 其 行 文 其 量.
环
出 其 清. 显 数量.
"""


SORT_SOURCE = """竞 取 外言 '如:竞赛'.
算 造比较 方向 为 数:
    算 比 左 为 数 右 为 数: 得 (左-右)*方向. 法
    得 算 比.
法
入 取 竞 其 读入. 列 取 [].
循
    值 取 入 其 数.
    若 值 == 空 则 破. 然
    列 其 增 值.
环
比较器 取 造比较 1.
序 取 竞 其 排序 列 比较器. 出 取 竞 其 蓄出. 位次 取 0.
循 序 其 量 次
    出 其 行 序[位次]. 位次 取 位次+1.
环
出 其 清.
"""


def measured(command, input_file, expected, directory, label):
    output, diagnostic = directory/(label+'.out'), directory/(label+'.err')
    rss_file = directory/(label+'.rss')
    timer = Path('/usr/bin/time')
    resource_probe = directory/'rss-probe'
    wrapped = ([str(timer), '-f', '%M', '-o', str(rss_file), *command] if timer.exists()
        else [str(resource_probe), str(rss_file), *command] if resource_probe.exists() else command)
    start = time.perf_counter()
    child_env = {**os.environ, 'RU_GC_STATS':'1'}
    child_env.pop('RU_GC_THRESHOLD', None)
    with input_file.open('rb') as stdin, output.open('wb') as stdout, diagnostic.open('wb') as stderr:
        result = subprocess.run(wrapped, stdin=stdin, stdout=stdout, stderr=stderr,
                                env=child_env, timeout=300)
    elapsed = time.perf_counter()-start
    rss = int(rss_file.read_text()) if timer.exists() else None
    if resource_probe.exists() and not timer.exists():
        probe = json.loads(rss_file.read_text())
        rss, elapsed = probe['rss'], probe['elapsed']
        if sys.platform == 'darwin':
            rss //= 1024
    if result.returncode or output.read_bytes() != expected:
        raise RuntimeError(f'{label}: failed status={result.returncode}; {diagnostic.read_text()}')
    stats = diagnostic.read_text().strip()
    if command[0] != sys.executable and 'RU_GC live=0 ' not in stats:
        raise RuntimeError(label+': missing final GC accounting')
    return {'elapsed_seconds':round(elapsed,4), 'peak_rss_kib':rss,
            'stdout_bytes':len(expected), 'correct':True, 'native_gc':stats or None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tokens', type=int, default=500000)
    parser.add_argument('--lines', type=int, default=100000)
    parser.add_argument('--sort', type=int, default=40000)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.tokens < 1 or args.lines < 1 or args.sort < 1:
        parser.error('counts must be positive')
    cc = shutil.which('gcc') or shutil.which('clang') or shutil.which('cc')
    if not cc:
        parser.error('a C compiler is required')
    results = {'timestamp_utc':datetime.now(timezone.utc).isoformat(), 'platform':sys.platform,
               'python':sys.version.split()[0], 'compiler':subprocess.check_output([cc,'--version'],text=True).splitlines()[0],
               'native_flags':['-std=c11','-O2'], 'measurements':{}}
    with tempfile.TemporaryDirectory(prefix='ru-contest-bench-') as temp:
        directory = Path(temp)
        if sys.platform.startswith('linux') and not Path('/usr/bin/time').exists():
            # This tiny process avoids counting a Python launcher's pre-exec
            # RSS as the child program's high-water mark.
            probe = directory/'rss-probe.c'
            probe.write_text(r'''#define _DEFAULT_SOURCE
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
int main(int argc, char **argv) {
    struct timespec a,b; struct rusage usage; int status; pid_t child; FILE *out;
    if (argc<3) return 2;
    clock_gettime(CLOCK_MONOTONIC,&a); child=fork();
    if (child<0) return 2;
    if (!child) { execvp(argv[2],argv+2); _exit(127); }
    while (wait4(child,&status,0,&usage)<0) if(errno!=EINTR) return 2;
    clock_gettime(CLOCK_MONOTONIC,&b); out=fopen(argv[1],"w"); if(!out) return 2;
    fprintf(out,"{\"rss\":%ld,\"elapsed\":%.9f}",usage.ru_maxrss,
        (double)(b.tv_sec-a.tv_sec)+(double)(b.tv_nsec-a.tv_nsec)/1e9);
    fclose(out); return WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
}
''',encoding='utf-8')
            subprocess.run([cc,'-std=c11','-O2',str(probe),'-o',str(directory/'rss-probe')],check=True,capture_output=True)
        token_values = [index % 2001-1000 for index in range(args.tokens)]
        token_data = ' '.join(map(str,token_values)).encode()
        line_values = ['如😀 abc' if index%3 else '' for index in range(args.lines)]
        # Always include a final non-newline row (nonempty), mixed LF and CRLF.
        line_values[-1] = '终'
        line_data = ''.join(value+('\r\n' if index%2 else '\n') for index,value in enumerate(line_values[:-1]))+line_values[-1]
        sort_values = list(range(args.sort))
        random.Random(20260930).shuffle(sort_values)
        jobs = [('tokens',TOKEN_SOURCE,token_data,f'{sum(token_values)}\n{len(token_values)}\n'.encode()),
                ('lines',LINE_SOURCE,line_data.encode(),(''.join(str(len(value))+'\n' for value in line_values)+str(len(line_values))+'\n').encode()),
                ('sort',SORT_SOURCE,' '.join(map(str,sort_values)).encode(),''.join(str(i)+'\n' for i in range(args.sort)).encode())]
        for name,source,data,expected in jobs:
            ru, cfile, binary, infile = [directory/(name+suffix) for suffix in ('.ru','.c','','.in')]
            ru.write_text(source,encoding='utf-8'); infile.write_bytes(data)
            graph = load_module_graph(ru)
            cfile.write_text(Compiler(graph[graph.root],graph.root,modules=graph).compile(),encoding='utf-8')
            subprocess.run([cc,'-std=c11','-O2',str(cfile),'-o',str(binary)],check=True,capture_output=True)
            results['measurements'][name] = {'items':{'tokens':args.tokens,'lines':args.lines,'sort':args.sort}[name],
                'input_bytes':len(data), 'interpreter':measured([sys.executable,str(ROOT/'ru'),'run',str(ru)],infile,expected,directory,name+'-python'),
                'native':measured([str(binary)],infile,expected,directory,name+'-native')}
    encoded = json.dumps(results,ensure_ascii=False,indent=2)+'\n'
    print(encoded,end='')
    if args.output:
        args.output.write_text(encoded,encoding='utf-8')


if __name__ == '__main__':
    main()
