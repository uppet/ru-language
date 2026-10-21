#!/usr/bin/env python3
"""Build Ru's native source compiler, then compile it with itself.

Only the stage0 path uses Python parsing/code generation. Later stages invoke
the native Ru compiler for all source processing. This host driver prepares the
unchanged C runtime, calls LLVM and publishes artifacts; it never interprets the
program being compiled.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rulang.c_runtime import runtime_source
from rulang.frontend import RuError
from rulang.llvm_toolchain import LLVMToolchain


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compile_native(compiler, source, output, toolchain, *, emit_llvm=None, keep_frontend=False):
    """No Python source parser, AST, module loader or code generator is called."""
    compiler, source, output = (Path(path).resolve() for path in (compiler, source, output))
    destinations = [output]
    if emit_llvm:
        destinations.append(Path(emit_llvm).resolve())
    if keep_frontend:
        destinations.extend(output.with_name(output.name+suffix) for suffix in ('.frontend.ll','.metadata.c'))
    if len(set(destinations)) != len(destinations) or source in destinations or any(p.is_dir() for p in destinations):
        raise ValueError('output paths must differ and cannot overwrite a source or directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='.ru-bootstrap-', dir=output.parent) as stage:
        stage = Path(stage)
        program, metadata, sources = stage/'frontend.ll', stage/'metadata.c', stage/'sources.json'
        result = subprocess.run([str(compiler), str(source), str(program), str(metadata),
                                 toolchain.triple, toolchain.data_layout, str(ROOT/'rulang/stdlib'), str(sources)],
                                capture_output=True, text=True, encoding='utf-8', timeout=300)
        if result.returncode:
            raise RuntimeError('native Ru compiler failed:\n'+(result.stderr or result.stdout))
        frontend_finished = time.monotonic()
        dependencies = {Path(path).resolve() for path in json.loads(sources.read_text(encoding='utf-8'))} | {source}
        if any(path in dependencies for path in destinations):
            raise ValueError('output path cannot overwrite an imported source')
        ir, descriptors = program.read_text(encoding='utf-8'), metadata.read_text(encoding='utf-8')
        runtime = ('#define RU_ENABLE_MODULO 1\n'+runtime_source({}, '', full=True)+'\n'+
                   (ROOT/'rulang/llvm_runtime.h').read_text(encoding='utf-8')+'\n'+descriptors)
        executable, standalone = toolchain.compile(ir, runtime, stage)
        evidence = {'source_ir_sha256': digest(ir.encode()), 'metadata_sha256': digest(descriptors.encode()),
                    'binary_sha256': digest(executable.read_bytes()), 'frontend_seconds': frontend_finished-started,
                    'seconds': time.monotonic()-started}
        # Keep the native frontend output for independent inspection/fixed points.
        if keep_frontend:
            for suffix, content in (('.frontend.ll', ir), ('.metadata.c', descriptors)):
                destination = output.with_name(output.name+suffix)
                staged = stage/('saved'+suffix)
                staged.write_text(content, encoding='utf-8', newline='\n')
                os.replace(staged, destination)
        if emit_llvm:
            emit_llvm = Path(emit_llvm).resolve()
            emit_llvm.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.ru-bootstrap-', dir=emit_llvm.parent) as saved:
                staged = Path(saved)/'program.ll'
                shutil.copyfile(standalone, staged)
                os.replace(staged, emit_llvm)
        os.replace(executable, output)
    return evidence


def bootstrap(directory, selected=None):
    from rulang.cli import build
    from rulang.frontend import parse
    source = ROOT/'bootstrap/compiler.ru'
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    toolchain = LLVMToolchain(selected)
    suffix = '.exe' if sys.platform == 'win32' else ''
    stages = [directory/('stage'+str(index)+suffix) for index in range(1, 4)]
    frozen_source = source.read_bytes()
    print('Stage0 → stage1: Python LLVM frontend compiles Ru compiler source', flush=True)
    stage0_started = time.monotonic()
    build(parse(frozen_source.decode('utf-8')), source, stages[0], target='llvm', llvm_clang=selected)
    report = {'platform': sys.platform, 'triple': toolchain.triple, 'llvm': toolchain.version,
              'source_sha256': digest(frozen_source), 'stage0_seconds': time.monotonic()-stage0_started, 'stages': []}
    for index in (0, 1):
        if source.read_bytes() != frozen_source:
            raise RuntimeError('compiler source changed during bootstrap; restart with a frozen source')
        print(f'Stage{index+1} → stage{index+2}: native Ru compiler compiles the same source', flush=True)
        evidence = compile_native(stages[index], source, stages[index+1], toolchain,
                                  emit_llvm=directory/('stage'+str(index+2)+'.ll'), keep_frontend=True)
        report['stages'].append(evidence)
    if source.read_bytes() != frozen_source:
        raise RuntimeError('compiler source changed during bootstrap; restart with a frozen source')
    first, second = report['stages']
    report['fixed_point'] = all(first[key] == second[key] for key in ('source_ir_sha256','metadata_sha256'))
    (directory/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    if not report['fixed_point']:
        raise RuntimeError('native frontend IR/metadata did not reach a fixed point')
    print('Native Ru source IR and ABI metadata reached an exact fixed point: '+str(stages[-1]), flush=True)
    return report


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--llvm-clang')
    sub = parser.add_subparsers(dest='command', required=True)
    cycle = sub.add_parser('bootstrap')
    cycle.add_argument('--directory', default=str(ROOT/'bin/bootstrap'/sys.platform))
    acceptance = sub.add_parser('verify', help='fresh bootstrap and the same M4 regressions on all three stages')
    acceptance.add_argument('--directory', default=str(ROOT/'bin/bootstrap'/sys.platform))
    build = sub.add_parser('build')
    build.add_argument('source')
    suffix = '.exe' if sys.platform == 'win32' else ''
    build.add_argument('--compiler', default=str(ROOT/'bin/bootstrap'/sys.platform/('stage3'+suffix)))
    build.add_argument('-o', '--output', required=True)
    build.add_argument('--emit-llvm')
    args = parser.parse_args(argv)
    try:
        if args.command == 'bootstrap':
            bootstrap(args.directory, args.llvm_clang)
        elif args.command == 'verify':
            from tools.bootstrap_verify import verify
            return 0 if verify(args.directory, args.llvm_clang)['m4_complete'] else 1
        else:
            compile_native(args.compiler, args.source, args.output, LLVMToolchain(args.llvm_clang),
                           emit_llvm=args.emit_llvm)
    except (RuError, OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
