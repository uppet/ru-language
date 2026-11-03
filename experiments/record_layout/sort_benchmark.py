#!/usr/bin/env python3
"""Stable bottom-up Ru merge sort of dynamic records versus owned 3*u32 storage.
Linux portable native test adapter only; not production Linux ABI support.
"""
import argparse
import hashlib
import json
import platform
import shutil
import statistics
import subprocess
import sys
from pathlib import Path
import benchmark as scan

HERE = Path(__file__).resolve().parent
ROOT = scan.ROOT
MAX_COUNT = (16 * 1024 * 1024) // 24  # both owned buffers, not each individually


def records(count, pattern):
    for i in range(count):
        key = {'mixed': (i * 37) % 257, 'equal': 0,
               'sorted': i // 4, 'reverse': (count - 1 - i) // 4}[pattern]
        yield (65536 + (i * 4099) % 1000000000, 256 + key * 257, i)


def expected(count, pattern, full):
    rows = sorted(records(count, pattern), key=lambda row: row[1])
    # Order-sensitive, bounded exactly representable integer arithmetic.
    sums = [sum((i + 1) * row[j] % 1000000007 for i, row in enumerate(rows))
            % 1000000007 for j in range(3)]
    return ''.join(f'{x}\n' for row in rows for x in row) * full + ''.join(f'{x}\n' for x in sums)


def source(kind, count, pattern='mixed', full=False):
    if not 0 <= count <= MAX_COUNT or pattern not in ('mixed','equal','sorted','reverse'):
        raise ValueError('unsupported count or pattern')
    key = {'mixed':'(位*37)%257', 'equal':'0', 'sorted':'数学 其 整除 位 4',
           'reverse':f'数学 其 整除 ({count}-1-位) 4'}[pattern]
    if kind == 'dynamic':
        declarations = '''形 记录: 起 为 数. 长 为 数. 序 为 数. 象.
算 造 个数 为 数:
    列 取 [].
    循 个数 次 列 其 增 (新 记录 起:0 长:0 序:0). 环.
    得 列.
法.
作 写 列 位 为 数 起 为 数 长 为 数 序 为 数:
    项 取 列[位]. 项 其 起 取 起. 项 其 长 取 长. 项 其 序 取 序.
为.
'''
        for field in ('起','长','序'):
            declarations += f'算 读{field} 列 位 为 数: 得 列[位] 其 {field}. 法.\n'
    elif kind == 'packed':
        declarations = '''密 取 外言 '如:密'.
算 造 个数 为 数: 得 密 其 缓冲 ((数学 其 大 个数 1)*12). 法.
算 读字 列 位 为 数:
    得 (列 其 读字节 位)+256*(列 其 读字节 (位+1))+65536*(列 其 读字节 (位+2))+16777216*(列 其 读字节 (位+3)).
法.
作 写字 列 位 为 数 值 为 数:
    循 4 次
        列 其 写字节 位 (值%256).
        值 取 数学 其 整除 值 256. 位 取 位+1.
    环.
为.
作 写 列 位 为 数 起 为 数 长 为 数 序 为 数:
    写字 列 (位*12) 起. 写字 列 (位*12+4) 长. 写字 列 (位*12+8) 序.
为.
算 读起 列 位 为 数: 得 读字 列 (位*12). 法.
算 读长 列 位 为 数: 得 读字 列 (位*12+4). 法.
算 读序 列 位 为 数: 得 读字 列 (位*12+8). 法.
'''
    else:
        raise ValueError(kind)
    # The entire algorithm below is literally shared by both representations.
    return "数学 取 外言 '如:数学'.\n" + declarations + f'''显 111111111.
原 取 造 {count}. 辅 取 造 {count}.
位 取 0.
循 {count} 次
    键 取 {key}.
    写 原 位 (65536+(位*4099)%1000000000) (256+键*257) 位.
    位 取 位+1.
环.
显 222222222.
宽 取 1.
循 {max(0,(count-1).bit_length()) if count else 0} 次
    块 取 0.
    块数 取 数学 其 整除 ({count}+宽*2-1) (宽*2).
    循 块数 次
        中 取 数学 其 小 (块+宽) {count}.
        尾 取 数学 其 小 (块+宽*2) {count}.
        左 取 块. 右 取 中. 出 取 块.
        循 (尾-块) 次
            用左 取 0.
            若 左 < 中 则
                若 右 >= 尾 则 用左 取 1.
                另 若 (读长 原 左) <= (读长 原 右) 则 用左 取 1. 然.
                然.
            然.
            选 取 右.
            若 用左 == 1 则 选 取 左. 左 取 左+1.
            另 右 取 右+1. 然.
            写 辅 出 (读起 原 选) (读长 原 选) (读序 原 选).
            出 取 出+1.
        环.
        块 取 块+宽*2.
    环.
    暂 取 原. 原 取 辅. 辅 取 暂. 宽 取 宽*2.
环.
显 333333333.
甲 取 0. 乙 取 0. 丙 取 0. 位 取 0.
循 {count} 次
    起 取 读起 原 位. 长 取 读长 原 位. 序 取 读序 原 位.
    {'显 起. 显 长. 显 序.' if full else ''}
    甲 取 (甲+((位+1)*起)%1000000007)%1000000007.
    乙 取 (乙+((位+1)*长)%1000000007)%1000000007.
    丙 取 (丙+((位+1)*序)%1000000007)%1000000007.
    位 取 位+1.
环.
显 甲. 显 乙. 显 丙.
''' + ('原 其 关闭. 辅 其 关闭.\n' if kind == 'packed' else '')


def build(kind, count, pattern, full, directory):
    # Reuse only the tested source-to-C/toolchain/clock plumbing, not its workload.
    old = scan.source
    try:
        scan.source = lambda kind, count, unused: source(kind,count,pattern,full)
        return scan.build(kind,count,0,directory)
    finally:
        scan.source = old


def run(kind, directory, oracle):
    sample = scan.run(directory/kind,oracle,None)
    sample['sort_seconds'] = sample.pop('scan_seconds')
    return sample


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count',type=int,default=12000)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--directory',type=Path,default=HERE/'sort-results')
    parser.add_argument('--prepare-only',action='store_true')
    args = parser.parse_args()
    if not sys.platform.startswith('linux') or not 1 <= args.count <= MAX_COUNT or args.repeats < 3:
        parser.error(f'Linux, 1..{MAX_COUNT} records and >=3 repeats required')
    args.directory = args.directory.resolve()
    args.directory.mkdir(parents=True,exist_ok=True)
    artifacts = {kind:build(kind,args.count,'mixed',False,args.directory) for kind in ('dynamic','packed')}
    scan.runner(args.directory)  # compile before whole-process timing starts
    gcc = shutil.which('gcc')
    cc1 = subprocess.check_output([gcc,'-print-prog-name=cc1'],text=True).strip()
    tool_paths = [gcc, cc1, sys.executable, shutil.which('as'), shutil.which('ld')]
    for kind in artifacts:
        artifacts[kind]['executable_sha256'] = sha(args.directory/kind)
    report = {'schema':1,'algorithm':'same Ru stable bottom-up merge sort by length only',
              'count':args.count,'record_fields':'start:u32, length:u32, original_ordinal:u32',
              'packed_payload_bytes':args.count*24,'repeats':args.repeats,
              'platform':platform.platform(),'python':sys.version,
              'adapter':'tests/test_native_c_runtime.py portable_test_source; Linux test adapter, not production ABI',
              'cpu':Path('/proc/cpuinfo').read_text().split('model name')[1].split('\n')[0].strip(': \t'),
              'gcc':subprocess.check_output([gcc,'--version'],text=True),
              'toolchain_sha256':{p:sha(p) for p in tool_paths},
              'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),HERE/'benchmark.py',ROOT/'tests/test_native_c_runtime.py',*sorted((ROOT/'rulang').glob('*.py')),*sorted((ROOT/'rulang').glob('*.h')),*sorted((ROOT/'rulang/stdlib').rglob('*.ru'))]},
              'artifacts':artifacts,'expected_output':expected(args.count,'mixed',False),'samples':[]}
    if not args.prepare_only:
        for kind in ('dynamic','packed'):
            run(kind,args.directory,report['expected_output'])
        for repeat in range(args.repeats):
            for kind in (('dynamic','packed') if repeat%2==0 else ('packed','dynamic')):
                sample = run(kind,args.directory,report['expected_output'])
                sample.update(kind=kind,repeat=repeat)
                report['samples'].append(sample)
                print(kind,repeat,sample['initialization_seconds'],sample['sort_seconds'],sample['peak_rss_kib'],flush=True)
        report['medians'] = {kind:{metric:statistics.median(s[metric] for s in report['samples'] if s['kind']==kind)
                                  for metric in ('initialization_seconds','sort_seconds','whole_process_seconds','peak_rss_kib')}
                             for kind in ('dynamic','packed')}
    (args.directory/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__':
    main()
