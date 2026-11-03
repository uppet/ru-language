#!/usr/bin/env python3
"""Opt-in paired whole-process string slicing benchmark, no timing assertions.

Freeze an old run first using --label baseline. Then use --label candidate
--baseline-directory PATH/TO/baseline to alternate its preserved generated C
with the current compiler output. Sources, C, runtime snapshots, hashes,
compiler version, wall-time/RSS samples and outputs are retained. Linux only.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.compiler import Compiler
from rulang.frontend import parse
from rulang.modules import load_module_graph

SOURCE = """算 元初 外参 为 句 阵:
文 取 ((新 件 路径:外参[0]) 其 读) 其 值.
块长 取 65536. 总长 取 文 其 量. 位 取 0. 合计 取 0.
循
    若 位 == 总长 则 破. 然.
    终位 取 位 + 块长.
    若 终位 > 总长 则 终位 取 总长. 然.
    合计 取 合计 + (文[位:终位] 其 量).
    位 取 终位.
环.
显 合计.
得 0.
法.
"""
# A fresh, small parent prevents the large data-generation process's pre-exec
# RSS from contaminating the measured child's high-water mark after fork.
MEASURE = r'''
import json, resource, subprocess, sys, time
start = time.perf_counter()
p = subprocess.run(sys.argv[1:], capture_output=True, text=True, timeout=600)
seconds = time.perf_counter()-start
print(json.dumps({'seconds':seconds, 'peak_rss_kib':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
                  'returncode':p.returncode, 'stdout':p.stdout, 'stderr':p.stderr}))
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--directory', type=Path, required=True)
    ap.add_argument('--label', required=True)
    ap.add_argument('--baseline-directory', type=Path)
    ap.add_argument('--characters', type=int, default=32000000)
    ap.add_argument('--repeats', type=int, default=3)
    ap.add_argument('--cases', nargs='+', choices=['ascii','unicode'], default=['ascii','unicode'])
    ap.add_argument('--cc', default=shutil.which('gcc'))
    ap.add_argument('--prepare-only', action='store_true', help='freeze source/C/manifest without measurements')
    args = ap.parse_args()
    if args.characters < 1 or args.repeats < 3 or not args.cc or not sys.platform.startswith('linux'):
        ap.error('Linux, positive character count, >=3 repeats and C compiler required')
    directory = args.directory.resolve()/args.label
    directory.mkdir(parents=True, exist_ok=True)
    if (directory/'results.json').exists():
        ap.error('label already has results; use a fresh label to preserve evidence')
    source = directory/'slices.ru'
    source.write_text(SOURCE, encoding='utf-8')
    runtime = (ROOT/'rulang/runtime.h').read_bytes()
    (directory/'runtime.h').write_bytes(runtime)
    graph = load_module_graph(str(source), parse(SOURCE))
    generated = Compiler(graph[graph.root], graph.root, modules=graph).compile()
    if (ROOT/'rulang/runtime.h').read_bytes() != runtime:
        raise RuntimeError('runtime changed during generation; discard this preparation and use a new label')
    cfile = directory/'slices.c'
    cfile.write_text(generated, encoding='utf-8')
    binary = directory/'slices'
    flags = ['-std=c99', '-O2']
    compile_command = [args.cc, *flags, str(cfile), '-lm', '-o', str(binary)]
    subprocess.run(compile_command, check=True, capture_output=True)
    env = dict(os.environ)
    for key in ('RU_GC_THRESHOLD', 'RU_GC_STATS'):
        env.pop(key, None)
    report = {'schema': 2, 'measured_at': datetime.now(timezone.utc).isoformat(),
              'label': args.label, 'git_head': subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
              'working_diff_sha256': sha(subprocess.check_output(['git','diff','HEAD'], cwd=ROOT)),
              'runtime_sha256': sha(runtime), 'source_sha256': sha(source.read_bytes()),
              'generated_c_sha256': sha(cfile.read_bytes()),
              'platform': platform.platform(), 'machine': platform.machine(), 'python_version': sys.version,
              'compiler': subprocess.check_output([args.cc,'--version'], text=True).splitlines()[0],
              'compile_command': compile_command,
              'measurement': 'whole target process monotonic seconds (startup, input read, slicing, output); child peak RSS KiB from isolated small Python runner; no warmups; shared host, not exclusive CPU',
              'block_characters': 65536, 'cases': []}
    programs = [('c', binary)]
    if args.baseline_directory:
        baseline = args.baseline_directory.resolve()
        metadata = json.loads((baseline/'results.json').read_text())
        before_c = (baseline/'slices.c').read_bytes()
        if sha(before_c) != metadata['generated_c_sha256'] or metadata['source_sha256'] != report['source_sha256']:
            raise RuntimeError('baseline C hash/source mismatch')
        before = directory/'baseline.c'
        before.write_bytes(before_c)
        before_binary = directory/'baseline'
        subprocess.run([args.cc,*flags,str(before),'-lm','-o',str(before_binary)],check=True,capture_output=True)
        report['baseline'] = {k:metadata[k] for k in ('git_head','runtime_sha256','source_sha256','generated_c_sha256')}
        programs = [('baseline-c', before_binary), ('candidate-c', binary)]
    result_path = directory/'results.json'
    result_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.prepare_only:
        return
    for name, unit in [('ascii', 'a'), ('unicode', '甲😀éa')]:
        if name not in args.cases:
            continue
        text = (unit*((args.characters+len(unit)-1)//len(unit)))[:args.characters]
        data = directory/(name+'.txt')
        raw = text.encode('utf-8')
        data.write_bytes(raw)
        input_hash,byte_count=sha(raw),len(raw)
        del text,raw
        commands = [(label,[str(program),str(data)]) for label,program in programs]
        commands += [('python',[sys.executable,str(ROOT/'ru'),'run',str(source),'--',str(data)])]
        rows = {label:{'case':name,'engine':label,'characters':args.characters,'utf8_bytes':byte_count,'input_sha256':input_hash,'command':command,'samples':[]} for label,command in commands}
        report['cases'].extend(rows.values())
        for repeat in range(args.repeats):
            # Alternate pair order so persistent thermal/load drift does not
            # systematically favor the candidate. Python follows each pair.
            ordered = commands if repeat%2==0 else [*reversed(commands[:-1]),commands[-1]]
            for label,command in ordered:
                measured=subprocess.run([sys.executable,'-c',MEASURE,*command],env=env,capture_output=True,text=True,timeout=610,check=True)
                sample=json.loads(measured.stdout)
                sample['repeat']=repeat
                if sample['returncode'] or sample['stdout'] != str(args.characters)+'\n':
                    raise RuntimeError(f'{label}: {sample}')
                rows[label]['samples'].append(sample)
                result_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                print(json.dumps({'case':name,'engine':label,**sample},ensure_ascii=False),flush=True)
        for row in rows.values():
            row['median_seconds']=statistics.median(sample['seconds'] for sample in row['samples'])
        result_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__ == '__main__':
    main()
