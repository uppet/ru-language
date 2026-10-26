#!/usr/bin/env python3
"""Build and measure the frozen 149-assertion Windows ru_notepad syntax suite.

The pinned native adapter supplies the experimental FFI frontend/driver only.
Ordinary lowering and LLVM runtime/toolchain come from this checkout. No dense
Mi mode, application rewrite or generated-IR rewrite is used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = '6840d99e027221a2772e1b15d8c6be6b0a28a3f5'
APPLICATION = 'd964ea9f7e27065aa5bbcced8d6c7526a6224dd1'
DLLS = ('Scintilla.dll', 'Lexilla.dll', 'RuSyntax.dll')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def archive(repository, revision, destination):
    destination.mkdir()
    packed = destination.parent/(destination.name+'.tar')
    subprocess.run(['git', '-C', str(repository), 'archive', '--format=tar',
                    '--output='+str(packed), revision], check=True)
    # Both revisions are fixed, reviewed project sources, not downloaded input.
    with tarfile.open(packed) as source:
        source.extractall(destination)
    packed.unlink()


def prepare(args):
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    candidate, app = out/'compiler', out/'application'
    archive(args.compiler_repository, ADAPTER, candidate)
    archive(args.notepad_repository, APPLICATION, app)
    original = (candidate/'bootstrap/compiler.ru').read_text(encoding='utf-8')
    current = (ROOT/'bootstrap/compiler.ru').read_text(encoding='utf-8')
    # Copy the complete ordinary emitter, retaining the adapter's native parser,
    # native descriptors and native emitter module unchanged.
    start, end = '算 新号 全 前:', '算 读文 文件:'
    def span(source):
        assert source.count(start) == source.count(end) == 1
        return source.index(start), source.index(end)
    a, b = span(original)
    c, d = span(current)
    original = original[:a]+current[c:d]+original[b:]
    abi = next(line for line in current.splitlines() if line.startswith('LLVM接口 取 '))
    original = '\n'.join(abi if line.startswith('LLVM接口 取 ') else line
                         for line in original.splitlines())+'\n'
    (candidate/'bootstrap/compiler.ru').write_text(original, encoding='utf-8')
    for name in ('llvm_compiler.py', 'llvm_runtime.h', 'llvm_toolchain.py'):
        shutil.copyfile(ROOT/'rulang'/name, candidate/'rulang'/name)
    sys.path.insert(0, str(candidate))
    from tools.bootstrap import bootstrap, compile_native
    from rulang.llvm_toolchain import LLVMToolchain
    from rulang.compiler import Compiler
    from rulang.frontend import parse
    from rulang.modules import load_module_graph
    tc = LLVMToolchain(args.llvm_clang)
    bootstrap(out/'stages', args.llvm_clang)
    source = app/'tests/ru_syntax_native.ru'
    native_dir, c_dir = out/'bootstrap', out/'c-llvm'
    native_dir.mkdir()
    c_dir.mkdir()
    build = compile_native(out/'stages/stage3.exe', source, native_dir/'program.exe', tc,
        keep_frontend=True, emit_llvm=native_dir/'optimized.ll', allow_native=True,
        source_roots=[app], proof=native_dir/'proof.json')
    save(native_dir/'build.json', build)
    text = source.read_text(encoding='utf-8')
    program = parse(text)
    graph = load_module_graph(str(source), program)
    graph.sources[graph.root] = text
    code = Compiler(program, graph.root, modules=graph, allow_native=True).compile()
    # Identical O2 bitcode/link/opt/llc pipeline; only user-source lowering differs.
    tc.compile('', code, c_dir)
    for folder in (native_dir, c_dir):
        for dll in DLLS:
            shutil.copyfile(args.dll_directory/dll, folder/dll)
    tracked = [*candidate.rglob('*.ru'), *candidate.rglob('*.py'),
               *candidate.rglob('*.h'), *app.rglob('*.ru'),
               *(folder/name for folder in (native_dir, c_dir) for name in (*DLLS, 'program.exe'))]
    save(out/'inputs.json', {'adapter_commit': ADAPTER, 'application_commit': APPLICATION,
        'comparison_baseline': '0b7adcb14f5039ea7ffa9892982877d0e83bc4bc',
        'platform': platform.platform(), 'machine': platform.machine(),
        'processor': platform.processor(), 'python': sys.version,
        'llvm': tc.version, 'triple': tc.triple, 'target_attributes': tc.function_target,
        'files': {str(path.relative_to(out)): sha(path) for path in sorted(tracked)}})
    print('BUILD COMPLETE: '+str(out), flush=True)


def values(row):
    a, b, g = row['metrics']
    assert a['kind'] == b['kind'] == 'PERF_RU' and g['kind'] == 'RU_GUI_SYNC'
    assert a['size'] == 100000 and b['size'] == g['size'] == 1000000
    assert a['edit_read_bytes'] == b['edit_read_bytes'] == 32768
    assert a['initial_read_bytes'] == 100000 and b['initial_read_bytes'] == 1000000
    assert g['read_bytes'] == 1000000 and g['source_chars'] == 636370
    return [a['initial_ms'], a['edit_ms'], b['initial_ms'], b['edit_ms'],
            g['wall_ms'], row['wall_ms']]


def measure(args):
    out = args.output.resolve()
    inputs = json.loads((out/'inputs.json').read_text(encoding='utf-8'))
    for name, expected in inputs['files'].items():
        assert sha(out/name) == expected, 'changed benchmark input: '+name
    result_dir = out/'measurement'
    result_dir.mkdir(exist_ok=False)
    env = dict(os.environ)
    env.pop('RU_GC_THRESHOLD', None)
    env.pop('RU_GC_STATS', None)
    records = []
    for index in range(6):
        pair = {}
        order = ('c-llvm', 'bootstrap') if index % 2 == 0 else ('bootstrap', 'c-llvm')
        for arm in order:
            executable = out/arm/'program.exe'
            started = time.perf_counter()
            result = subprocess.run([str(executable)], cwd=executable.parent,
                capture_output=True, timeout=180, env=env)
            wall = (time.perf_counter()-started)*1000
            stem = result_dir/f'{index+1}-{arm}'
            stem.with_suffix('.stdout').write_bytes(result.stdout)
            stem.with_suffix('.stderr').write_bytes(result.stderr)
            text = result.stdout.decode('utf-8')
            assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
            assert 'TOTAL PASS: 149' in text, text[-1000:]
            metrics = []
            for line in text.splitlines():
                if line.startswith(('PERF_RU ', 'RU_GUI_SYNC ')):
                    metric = {'kind': line.split()[0]}
                    metric.update({k: float(v) for k, v in
                                   (item.split('=') for item in line.split()[1:])})
                    metrics.append(metric)
            row = {'binary_sha256': sha(executable), 'wall_ms': wall, 'metrics': metrics}
            values(row)
            pair[arm] = row
            print(f'round {index+1} {arm}: {wall:.3f} ms; 149 assertions passed', flush=True)
        records.append(pair)
        save(result_dir/'raw.json', records)
    summary = []
    for i, name in enumerate(('100KB initial', '100KB edit', '1MB lines initial',
                             '1MB lines edit', '1MB Unicode sync', 'total')):
        c = [values(pair['c-llvm'])[i] for pair in records]
        native = [values(pair['bootstrap'])[i] for pair in records]
        ratios = [b/a for a, b in zip(c, native)]
        summary.append({'case': name, 'c_ms': c, 'bootstrap_ms': native,
            'c_median_ms': statistics.median(c), 'bootstrap_median_ms': statistics.median(native),
            'paired_ratio_median': statistics.median(ratios),
            'all_six_faster': all(r < 1 for r in ratios)})
    save(result_dir/'summary.json', summary)
    assert all(row['all_six_faster'] for row in summary), 'performance gate not met'
    print('All six metrics faster in every pair.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'measure'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--notepad-repository', type=Path)
    parser.add_argument('--compiler-repository', type=Path, default=ROOT,
                        help='object store; useful for a WSL worktree built by Windows Python')
    parser.add_argument('--dll-directory', type=Path)
    parser.add_argument('--llvm-clang', default=os.environ.get('RU_LLVM_CLANG'))
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('requires actual Windows x64, Scintilla and LLVM14')
    if args.action == 'prepare':
        if not args.notepad_repository or not args.dll_directory:
            parser.error('prepare requires --notepad-repository and --dll-directory')
        prepare(args)
    else:
        measure(args)


if __name__ == '__main__':
    main()
