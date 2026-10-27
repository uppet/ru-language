#!/usr/bin/env python3
"""Build and measure the frozen 149-assertion Windows ru_notepad syntax suite.

The pinned native adapter supplies the experimental FFI frontend/driver only.
Ordinary lowering and LLVM runtime/toolchain come from this checkout. No dense
Mi mode, application rewrite or generated-IR rewrite is used.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tarfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = '6840d99e027221a2772e1b15d8c6be6b0a28a3f5'
APPLICATION = 'd964ea9f7e27065aa5bbcced8d6c7526a6224dd1'
DLLS = ('Scintilla.dll', 'Lexilla.dll', 'RuSyntax.dll')
ORDINARY_FILES = ('llvm_compiler.py', 'llvm_runtime.h', 'llvm_toolchain.py',
                  'compiler.py', 'runtime.h', 'c_runtime.py')


def splice_frontend(original, current):
    """Replace only ordinary lowering, preserving native rules and literal bytes."""
    for start, end in (
        ('算 新号 全 前:', '算 读文 文件:'),
        ('算 检函 全 模块 函 保护 值域:', '算 检块 全 模块 体 函 循深 可声明 顶 保护 值域:'),
        ('算 描述符 全:', '    序 取 0. 类列 取 全[\'类\']. 类指 取 [].'),
        ('算 发全 全 三元 布局:', '算 元初 参数 为 句 阵:'),
    ):
        if any(text.count(marker) != 1 for text in (original, current) for marker in (start, end)):
            raise ValueError('ambiguous ordinary frontend boundary: '+start)
        original = original[:original.index(start)]+current[current.index(start):current.index(end)]+original[original.index(end):]
    # splitlines() also splits literal Unicode whitespace/control characters in
    # the compiler's tables. Only LF separates the declaration we replace.
    marker = 'LLVM接口 取 '
    start = original.index(marker)
    end = original.index('\n', start)
    current_start = current.index(marker)
    abi = current[current_start:current.index('\n', current_start)]
    return original[:start]+abi+original[end:]


def adapt_driver(name, original):
    """The pinned FFI host selects the current private descriptor layout only."""
    if name == 'tools/bootstrap.py':
        old, new = "runtime_source({}, '', full=True)", "runtime_source({}, '', full=True, llvm=True)"
    elif name == 'tools/bootstrap_native_runtime.py':
        old, new = 'from rulang.c_runtime import _FEATURE, _MAP_REGION', 'from rulang.c_runtime import _FEATURE, _MAP_REGION, _LLVM_REGION'
    else:
        raise ValueError(name)
    if original.count(old) != 1:
        raise ValueError('unexpected pinned driver: '+name)
    original = original.replace(old, new)
    if name.endswith('bootstrap_native_runtime.py'):
        anchor = "    return source + '\\n' + (directory/'llvm_runtime.h').read_text(encoding='utf-8')"
        if original.count(anchor) != 1:
            raise ValueError('unexpected pinned runtime assembly')
        original = original.replace(anchor, '    source = _LLVM_REGION.sub(lambda m: m[1], source)\n'+anchor)
    return original


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
    (candidate/'bootstrap/compiler.ru').write_text(splice_frontend(original, current), encoding='utf-8', newline='\n')
    for name in ('tools/bootstrap.py', 'tools/bootstrap_native_runtime.py'):
        path = candidate/name
        path.write_text(adapt_driver(name, path.read_text(encoding='utf-8')), encoding='utf-8', newline='\n')
    for name in ORDINARY_FILES:
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
        'comparison_compiler': 'current checkout: C and direct LLVM emitters with the same runtime',
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


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def measure(args):
    out = args.output.resolve()
    inputs = json.loads((out/'inputs.json').read_text(encoding='utf-8'))
    def verify():
        for name, expected in inputs['files'].items():
            require(sha(out/name) == expected, 'changed benchmark input: '+name)
    verify()
    folder = out/'measurement'
    folder.mkdir(exist_ok=False)
    plan = {'pairs': [{'round': n+1, 'order': list(('c-llvm', 'bootstrap') if n%2 == 0 else ('bootstrap', 'c-llvm'))}
                      for n in range(6)], 'timeout_seconds': 180, 'retries': 0, 'required_passes': 149}
    save(folder/'plan.json', plan)
    save(folder/'before.json', inputs)
    env = os.environ.copy()
    env.pop('RU_GC_THRESHOLD', None)
    env.pop('RU_GC_STATS', None)
    attempts, records, invalid = [], [], []
    labels = None
    try:
        for step in plan['pairs']:
            pair = {}
            for arm in step['order']:
                binary = out/arm/'program.exe'
                row = {'round': step['round'], 'arm': arm, 'status': 'started', 'timeout': False,
                       'binary_sha256': sha(binary)}
                attempts.append(row)
                save(folder/'attempts.json', attempts)
                stem = folder/(str(step['round'])+'-'+arm)
                started = time.perf_counter()
                try:
                    result = subprocess.run([str(binary)], cwd=binary.parent, capture_output=True,
                                            env=env, timeout=plan['timeout_seconds'])
                    stdout, stderr = result.stdout, result.stderr
                    row['returncode'] = result.returncode
                except subprocess.TimeoutExpired as error:
                    stdout, stderr = error.stdout or b'', error.stderr or b''
                    row.update(returncode=None, timeout=True)
                except OSError as error:
                    stdout, stderr = b'', str(error).encode('utf-8')
                    row.update(returncode=None, error=repr(error))
                row.update(wall_ms=(time.perf_counter()-started)*1000, status='finished')
                for name, content in [('stdout', stdout), ('stderr', stderr)]:
                    stem.with_suffix('.'+name).write_bytes(content)
                    row[name+'_sha256'] = hashlib.sha256(content).hexdigest()
                try:
                    require(row['returncode'] == 0 and not row['timeout'] and not stderr, 'process failed or stderr nonempty')
                    lines = stdout.decode('utf-8').splitlines()
                    passes = [line for line in lines if line.startswith('PASS: ')]
                    require(len(passes) == 149 and lines.count('TOTAL PASS: 149') == 1 and
                            not any(line.startswith('FAIL:') for line in lines), '149 complete passes required')
                    if labels is None:
                        labels = passes
                    require(passes == labels, 'assertion order changed')
                    row['metrics'] = []
                    for line in lines:
                        if line.startswith(('PERF_RU ', 'RU_GUI_SYNC ')):
                            metric = {'kind': line.split()[0]}
                            metric.update({k: float(v) for k, v in (s.split('=') for s in line.split()[1:])})
                            row['metrics'].append(metric)
                    require(all(math.isfinite(v) and v > 0 for v in values(row)), 'invalid metric')
                    row['passes'] = len(passes)
                except Exception:
                    row['validation_error'] = traceback.format_exc()
                    invalid.append(row)
                pair[arm] = row
                save(folder/'attempts.json', attempts)
                print(f"round {step['round']} {arm}: {row['wall_ms']:.3f} ms; passes={row.get('passes', 0)}", flush=True)
            records.append(pair)
            save(folder/'raw.json', records)
    finally:
        verify()
        save(folder/'after.json', {'verified': True, 'attempts': len(attempts), 'invalid': len(invalid)})
    require(len(attempts) == 12 and not invalid, 'invalid samples retained; no retries')
    result = []
    for index, name in enumerate(('100KB initial', '100KB edit', '1MB initial', '1MB edit', 'Unicode sync', 'total')):
        c = [values(pair['c-llvm'])[index] for pair in records]
        b = [values(pair['bootstrap'])[index] for pair in records]
        changes = [100*(1-y/x) for x, y in zip(c, b)]
        result.append({'case': name, 'c_ms': c, 'bootstrap_ms': b, 'c_median_ms': statistics.median(c),
                       'bootstrap_median_ms': statistics.median(b), 'bootstrap_reduction_percent': statistics.median(changes),
                       'all_pairs_reduction_percent': changes, 'range_percent': [min(changes), max(changes)],
                       'bootstrap_faster_pairs': sum(x > 0 for x in changes), 'c_faster_pairs': sum(x < 0 for x in changes)})
    save(folder/'summary.json', result)
    print(json.dumps(result, indent=2), flush=True)


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
