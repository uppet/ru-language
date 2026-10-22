"""Build a local, explicitly experimental notepad A/B from frozen source bytes.

Uses the current Ru checkout, including uncommitted work whose inputs are hashed.
Does not modify the product compiler pin, installed app, or official CI receipts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

RU = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RU))
from rulang.compiler import Compiler
from rulang.frontend import parse
from rulang.llvm_compiler import LLVMCompiler
from rulang.llvm_toolchain import LLVMToolchain
from rulang.modules import load_module_graph


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(app):
    return {str(p.relative_to(app)).replace('\\', '/'): sha(p)
            for directory in ('src', 'locales', 'packaging', 'assets')
            for p in sorted((app/directory).rglob('*')) if p.is_file()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--app-root', required=True, type=Path)
    ap.add_argument('--runtime', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--arm', choices=('ordinary', 'dense'), required=True)
    ap.add_argument('--incremental', action='store_true', help='bounded same-line-count convergence experiment')
    ap.add_argument('--target', choices=('c', 'llvm', 'c-llvm'), required=True)
    ap.add_argument('--gcc', default='C:/msys64/mingw64/bin/gcc.exe')
    ap.add_argument('--windres', default='C:/msys64/mingw64/bin/windres.exe')
    args = ap.parse_args()
    if sys.platform != 'win32': ap.error('actual Windows build only')
    app, runtime, out = args.app_root.resolve(), args.runtime.resolve(), args.output.resolve()
    if out.exists(): ap.error('use a fresh output directory')
    out.mkdir(parents=True)
    before = snapshot(app)
    ru_inputs = {p.relative_to(RU).as_posix(): sha(p) for p in sorted((RU/'rulang').glob('*'))
                 if p.suffix in ('.py', '.h')}
    receipt = json.loads((runtime/'BUILD.json').read_text(encoding='utf-8-sig'))
    dependencies = {n: sha(runtime/n) for n in ('Scintilla.dll', 'Lexilla.dll', 'RuSyntax.dll')}
    assert all(h == receipt['binaries'][n]['sha256'] for n, h in dependencies.items())
    # Reused DLLs must match both installed binary receipts and the exact current
    # application helper source, rather than silently mixing native revisions.
    for n, h in receipt['source']['tracked_source_sha256'].items():
        if n.startswith('native/'):
            assert sha(app/n) == h, n
    entry = app/'src/main.ru'
    program = parse(entry.read_text(encoding='utf-8'))
    graph = load_module_graph(entry, program)
    syntax = str((app/'src/markdown_syntax.ru').resolve())
    flags = [n for n in graph[syntax] if n.kind == 'bind' and n.data['name'] == '_密扫描策略']
    assert len(flags) == 1
    entries = flags[0].data['expr'].data['entries']
    assert len(entries) == 1 and entries[0][0].data['value'] == 'enabled'
    assert entries[0][1].kind == 'fact' and entries[0][1].data['value'] is False
    entries[0][1].data['value'] = args.arm == 'dense'
    incremental = [n for n in graph[syntax] if n.kind == 'bind' and n.data['name'] == '_增量策略']
    if incremental:
        assert len(incremental) == 1
        incremental_flag = incremental[0].data['expr'].data['entries'][0][1]
        assert incremental_flag.kind == 'fact' and incremental_flag.data['value'] is False
        incremental_flag.data['value'] = args.incremental
    else:
        assert not args.incremental, 'apply notepad-incremental.patch for --incremental'
    manifest = app/'experiments/markdown-dense-manifest.json'
    compiler_type = LLVMCompiler if args.target == 'llvm' else Compiler
    compiler = compiler_type(program, str(entry), modules=graph, allow_native=True, mi_manifest=manifest,
                             mi_backend='llvm' if args.target == 'c-llvm' else 'c')
    environment = dict(os.environ)
    environment['PATH'] = str(Path(args.gcc).parent) + os.pathsep + environment['PATH']
    resource = out/'resource.o'
    subprocess.run([args.windres, '-I', str(app/'packaging'), str(app/'packaging/app.rc'), str(resource)],
                   env=environment, check=True, timeout=60)
    launcher = (app/'packaging/diagnostic_launcher.c').read_text(encoding='utf-8')
    started = time.monotonic()
    if args.target in ('llvm', 'c-llvm'):
        toolchain = LLVMToolchain()
        if args.target == 'llvm':
            ir = compiler.compile(toolchain.triple, toolchain.data_layout)
            assert ir.count('define i32 @main(') == 1
            ir = ir.replace('define i32 @main(', 'define i32 @ru_program_main(', 1)
            runtime_c = compiler.runtime_c() + '\nint ru_program_main(int, char **);\n' + launcher
        else:
            # Retain the mature C caller/UI backend, emitting ONLY selected Mi
            # kernels directly as LLVM. This is not whole-program direct LLVM.
            generated = compiler.compile()
            ir = compiler.mi_plan.compute_source('llvm')
            runtime_c = '#define main ru_program_main\n' + generated + '\n#undef main\n' + launcher
        toolchain.link_flags += [str(resource), '-lshell32', '-luser32',
                                '-Wl,/SUBSYSTEM:WINDOWS,/ENTRY:mainCRTStartup']
        native, saved_ir = toolchain.compile(ir, runtime_c, out)
        os.replace(native, out/'ru_notepad.exe')
        assert saved_ir.is_file()
    else:
        generated = compiler.compile()
        source = out/'program.c'
        source.write_text('#define main ru_program_main\n' + generated + '\n#undef main\n' + launcher,
                          encoding='utf-8', newline='\n')
        subprocess.run([args.gcc, '-std=c99', '-O2', '-Wall', '-Wextra', '-Wno-unused-function',
                        '-static-libgcc', str(source), '-o', str(out/'ru_notepad.exe'), '-lm', str(resource),
                        '-mwindows', '-lshell32', '-luser32'], env=environment, check=True, timeout=600)
    assert snapshot(app) == before, 'application inputs changed during build'
    assert all(sha(RU/n) == h for n, h in ru_inputs.items()), 'compiler inputs changed during build'
    for name, h in dependencies.items():
        shutil.copyfile(runtime/name, out/name); assert sha(out/name) == h
    data = {'experimental': True, 'formal_product_acceptance': False, 'arm': args.arm, 'target': args.target,
            'incremental': args.incremental,
            'source_sha256': before, 'compiler_input_sha256': ru_inputs, 'manifest_sha256': sha(manifest),
            'dependencies': dependencies, 'seconds': time.monotonic()-started,
            'exe_sha256': sha(out/'ru_notepad.exe'),
            'activation_ast_changes': int(args.arm == 'dense') + int(args.incremental),
            'runtime_tested': False}
    (out/'experiment-build.json').write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: data[k] for k in ('arm', 'target', 'seconds', 'exe_sha256')}, indent=2))


if __name__ == '__main__': main()
