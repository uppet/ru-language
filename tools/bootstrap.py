#!/usr/bin/env python3
"""Build Ru's native source compiler, then compile it with itself.

Only the stage0 path uses Python parsing/code generation. Later stages invoke
the native Ru compiler for all source processing. This host driver prepares the
unchanged C runtime, calls LLVM and publishes artifacts; it never interprets the
program being compiled.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rulang.c_runtime import runtime_source
from rulang.frontend import RuError
from rulang.llvm_toolchain import LLVMToolchain
from tools import bootstrap_dense_protocol as dense_protocol
from tools.bootstrap_native_runtime import (BASE_HEADERS, NATIVE_HEADERS, NATIVE_FLAG,
    NATIVE_MARKER, NATIVE_PROTOCOL, NATIVE_TRIPLE, fixed_native_runtime,
    supported_native_triple, native_marker)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_identity(path):
    path = Path(path).resolve()
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('build input must be a regular file: ' + str(path))
    content = path.read_bytes()
    return {'path': str(path), 'sha256': digest(content), 'size': len(content)}


def verify_identities(identities):
    for identity in identities:
        if file_identity(identity['path']) != identity:
            raise RuntimeError('build input changed before publication: ' + identity['path'])


def publish_artifacts(artifacts):
    """Pre-stage all bytes, then atomically replace each file (not a transaction).

    The caller orders proof last. A publication failure may leave mixed old/new
    outputs; validators must compare proof hashes and fail closed on mismatch.
    """
    with ExitStack() as cleanup:
        prepared = []
        for source, destination in artifacts:
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            sibling = Path(cleanup.enter_context(tempfile.TemporaryDirectory(
                prefix='.ru-bootstrap-', dir=destination.parent)))
            staged = sibling/'new'
            shutil.copy2(source, staged)
            prepared.append((staged, destination))
        for staged, destination in prepared:
            os.replace(staged, destination)


def compile_native(compiler, source, output, toolchain, *, emit_llvm=None, keep_frontend=False,
                   interpreter_host=False, allow_native=False, proof=None, source_roots=(), linker=None, experimental_mi_manifest=None):
    """No Python source parser, AST, module loader or code generator is called."""
    compiler, source, output = (Path(path).resolve() for path in (compiler, source, output))
    dense = experimental_mi_manifest is not None
    frozen_inventory = allow_native or dense
    manifest = (dense_protocol.canonical_file(experimental_mi_manifest, resolve_cli=True)
                if dense else None)
    if dense and not ((sys.platform == 'linux' and toolchain.triple in dense_protocol.LINUX_TARGETS) or
                      (sys.platform == 'win32' and supported_native_triple(toolchain.triple))):
        raise ValueError('dense-v1 requires a supported Linux/Windows x64 LLVM target')
    if dense and (source.stat().st_size > dense_protocol.SOURCE_BYTES or
                  manifest.stat().st_size > dense_protocol.JSON_BYTES):
        raise ValueError('dense-v1: source/manifest byte limit exceeded')
    verify_inputs = dense_protocol.verify if dense else verify_identities
    if dense and interpreter_host:
        raise ValueError('dense-v1 and interpreter-host capabilities cannot be combined')
    linker_identity = None
    if linker is not None:
        if sys.platform != 'win32' or not supported_native_triple(toolchain.triple):
            raise ValueError('explicit bootstrap linker requires Windows x64 MSVC target')
        raw = str(linker)
        path = Path(raw)
        if (not path.is_absolute() or any(char in raw for char in ('\0', '\r', '\n', '"'))
                or path.name.lower() not in ('link.exe', 'lld-link.exe')
                or any(parent.is_symlink() for parent in [path, *path.parents])
                or not path.is_file()):
            raise ValueError('linker must be an absolute regular link.exe or lld-link.exe path')
        linker_identity = dense_protocol.identity(path) if dense else file_identity(path)
        from copy import copy
        toolchain = copy(toolchain)
        flags = list(getattr(toolchain, 'link_flags', []))
        if any(str(flag).startswith(('-fuse-ld', '--ld-path', '-B')) for flag in flags):
            raise ValueError('toolchain already selects a linker')
        toolchain.link_flags = [*flags, '-fuse-ld='+linker_identity['path']]
    if allow_native and (sys.platform != 'win32' or not supported_native_triple(toolchain.triple)):
        raise ValueError('bootstrap native v1 requires Windows x86-64 target ' + NATIVE_TRIPLE)
    if allow_native and source.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('native source input exceeds 64 MiB limit')
    if allow_native and interpreter_host:
        raise ValueError('native and interpreter-host capabilities cannot be combined')
    destinations = [output]
    if proof:
        destinations.append(Path(proof).resolve())
    if emit_llvm:
        destinations.append(Path(emit_llvm).resolve())
    if keep_frontend:
        destinations.extend(output.with_name(output.name+suffix) for suffix in ('.frontend.ll','.metadata.c'))
    if len(set(destinations)) != len(destinations) or source in destinations or compiler in destinations or any(p.is_dir() for p in destinations):
        raise ValueError('output paths must differ and cannot overwrite a source or directory')
    fixed_paths = [ROOT/'rulang'/name for name in BASE_HEADERS]
    fixed_paths += [ROOT/'rulang/c_runtime.py', ROOT/'rulang/llvm_toolchain.py',
                    ROOT/'rulang/toolchain_environment.py', Path(__file__).resolve(),
                    ROOT/'tools/bootstrap_native_runtime.py']
    if allow_native:
        fixed_paths += [ROOT/'rulang'/name for name in NATIVE_HEADERS]
        fixed_paths.append(ROOT/'rulang/native_c_runtime.py')
    if dense:
        fixed_paths += [ROOT/'rulang/bootstrap_dense_runtime.h',
                        ROOT/'tools/bootstrap_dense_protocol.py', manifest]
        fixed_paths += sorted((ROOT/'bootstrap').glob('*.ru'))
    if interpreter_host:
        fixed_paths += [ROOT/'rulang'/name for name in
                        ('interpreter_host.py', 'interpreter_host.h', 'interpreter_frames.h')]
    protected = {path.resolve() for path in fixed_paths} | {source, compiler}
    if linker_identity:
        protected.add(Path(linker_identity['path']))
    if protected.intersection(destinations):
        raise ValueError('output path cannot overwrite a compiler or runtime input')
    if dense:
        dense_protocol.reject_overlap(protected, destinations)
    frozen_inputs = [linker_identity if linker_identity and str(path) == linker_identity['path']
                     else (dense_protocol.identity(path, limit=dense_protocol.JSON_BYTES if path == manifest
                                                   else dense_protocol.SOURCE_BYTES) if dense else file_identity(path))
                     for path in sorted(protected)]
    # Native releases use a pre-read byte inventory, never a post-read claim.
    # Additional external import trees must be explicitly supplied; the host
    # enumerates files and hashes bytes, but does not discover imports itself.
    inventory = {}
    if dense:
        dense_inventory = dense_protocol.inventory(source, [ROOT/'rulang/stdlib', *source_roots])
        inventory = {str(Path(item['path'])): item for item in dense_inventory}
        dense_protocol.reject_overlap(inventory, destinations)
        packet = dense_protocol.prepare_transport(manifest, inventory)
    elif allow_native:
        roots = {source.parent, ROOT/'rulang/stdlib'} | {Path(path).resolve() for path in source_roots}
        if any(not root.is_dir() for root in roots):
            raise ValueError('native source inventory roots must be directories')
        paths = {source}
        total_bytes = source.stat().st_size
        for root in sorted(roots):
            for path in root.rglob('*.ru'):
                resolved = path.resolve()
                if not resolved.is_relative_to(root):
                    raise ValueError('native source inventory symlink escapes its root: ' + str(path))
                if not stat.S_ISREG(path.stat().st_mode):
                    raise ValueError('native source inventory requires regular files: ' + str(path))
                if resolved in paths:
                    continue
                paths.add(resolved)
                total_bytes += path.stat().st_size
                if len(paths) > 10000 or total_bytes > 64 * 1024 * 1024:
                    raise ValueError('native source inventory exceeds 10000 files / 64 MiB limit')
        if not stat.S_ISREG(source.stat().st_mode) or total_bytes > 64 * 1024 * 1024:
            raise ValueError('native source input must be a regular file within 64 MiB inventory limit')
        if paths.intersection(destinations):
            raise ValueError('output path cannot overwrite a frozen native source input')
        inventory = {str(path): file_identity(path) for path in sorted(paths)}
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='.ru-bootstrap-', dir=output.parent) as stage:
        stage = Path(stage)
        program, metadata, sources = stage/'frontend.ll', stage/'metadata.c', stage/'sources.json'
        dense_args = []
        if dense:
            packet_path, plan_path = stage/'dense.packet', stage/'dense.plan.json'
            dense_protocol.reject_overlap([*protected, *inventory],
                                          [*destinations, packet_path, plan_path, program, metadata, sources])
            packet_identity = dense_protocol.write_packet(packet_path, packet)
            dense_args = [dense_protocol.FLAG, str(packet_path), str(plan_path)]
            dense_protocol.verify([packet_identity, *inventory.values()])
        if dense:
            dense_protocol.verify(frozen_inputs)
        verify_inputs(frozen_inputs)
        result = subprocess.run([str(compiler), str(source), str(program), str(metadata),
                                 toolchain.triple, toolchain.data_layout, str(ROOT/'rulang/stdlib'), str(sources)] + ([NATIVE_FLAG] if allow_native else []) + dense_args,
                                capture_output=True, text=True, encoding='utf-8', timeout=300)
        if result.returncode:
            raise RuntimeError('native Ru compiler failed:\n'+(result.stderr or result.stdout))
        frontend_finished = time.monotonic()
        if dense:
            dense_protocol.verify(frozen_inputs)
            verify_inputs(frozen_inputs)
            dense_protocol.verify([packet_identity, *inventory.values()])
        source_paths = (dense_protocol.read_json(sources, dense_protocol.PACKET_BYTES) if dense else
                        json.loads(sources.read_text(encoding='utf-8')))
        if not isinstance(source_paths, list) or not all(isinstance(path, str) and path for path in source_paths):
            raise ValueError('frontend source manifest must be a list of source paths')
        if frozen_inventory and any(not Path(path).is_absolute() or '..' in Path(path).parts for path in source_paths):
            raise ValueError('native source manifest requires absolute paths without traversal')
        if dense and (len(source_paths) > dense_protocol.MAX_FILES or
                      len(source_paths) != len(set(source_paths)) or
                      any(path not in packet[2] for path in source_paths)):
            raise ValueError('dense-v1: frontend dependencies must use exact frozen canonical paths')
        dependencies = {Path(path).resolve() for path in source_paths} | {source}
        if frozen_inventory:
            missing = dependencies - {Path(path) for path in inventory}
            if missing:
                raise ValueError('native dependency absent from pre-read source inventory; add --source-root: ' +
                                 ', '.join(str(path) for path in sorted(missing)))
            verify_inputs(inventory.values())
            dependency_identities = [inventory[str(path)] for path in sorted(dependencies)]
        else:
            dependency_identities = [file_identity(path) for path in sorted(dependencies)]
        if any(path in dependencies for path in destinations):
            raise ValueError('output path cannot overwrite an imported source')
        ir, descriptors = program.read_text(encoding='utf-8'), metadata.read_text(encoding='utf-8')
        if allow_native:
            if not descriptors.startswith(native_marker(toolchain.triple)):
                raise ValueError('missing or incompatible bootstrap native metadata protocol')
            triples = re.findall(r'^target triple = "([^"\n]+)"$', ir, re.M)
            if triples != [toolchain.triple]:
                raise ValueError('native frontend IR target triple does not match host capability')
            runtime = fixed_native_runtime()
        else:
            if 'RU_BOOTSTRAP_NATIVE_' in descriptors:
                raise ValueError('native metadata requires explicit --allow-native')
            runtime = runtime_source({}, '', full=True)+'\n'+(ROOT/'rulang/llvm_runtime.h').read_text(encoding='utf-8')
        dense_protocol.validate_metadata(descriptors, ir, toolchain.triple,
                                         enabled=dense, native=allow_native, data_layout=toolchain.data_layout)
        if dense:
            selected_plan, plan_identity = dense_protocol.validate_plan(plan_path, packet, return_identity=True)
            if any(row[0] not in source_paths for row in selected_plan[2]):
                raise ValueError('dense-v1: selected plan module absent from frontend dependency report')
            runtime += '\n' + (ROOT/'rulang/bootstrap_dense_runtime.h').read_text(encoding='utf-8')
        if interpreter_host:
            from rulang.interpreter_host import integrate_host
            runtime = integrate_host(runtime)
            if sys.platform == 'win32':
                # The interpreter has several native host frames per guest
                # frame. Reserve stack for its checked, recoverable depth bound;
                # keep the caller's toolchain and ordinary AOT defaults intact.
                from copy import copy
                toolchain = copy(toolchain)
                toolchain.link_flags = [*toolchain.link_flags, '-Xlinker', '/STACK:16777216']
        runtime = '#define RU_ENABLE_MODULO 1\n'+runtime+'\n'+descriptors
        executable, standalone = toolchain.compile(ir, runtime, stage)
        evidence = {'source_ir_sha256': digest(ir.encode()), 'metadata_sha256': digest(descriptors.encode()),
                    'binary_sha256': digest(executable.read_bytes()), 'frontend_seconds': frontend_finished-started,
                    'seconds': time.monotonic()-started,
                    'schema': 'ru-bootstrap-build-proof-v1',
                    'artifacts': {'binary': {'path': str(output), 'sha256': digest(executable.read_bytes())},
                                  'standalone_ir': {'path': str(Path(emit_llvm).resolve()) if emit_llvm else None,
                                                    'sha256': digest(standalone.read_bytes())}},
                    'host_python': sys.version,
                    'linker': linker_identity,
                    'native_protocol': NATIVE_PROTOCOL if allow_native else None,
                    'compiler': (next(item for item in frozen_inputs if item['path'] == str(compiler))
                                 if dense else file_identity(compiler)), 'source': str(source),
                    'dependencies': dependency_identities,
                    'dependency_observation': ('pre-frontend inventory; verified after frontend and before publication'
                                               if frozen_inventory else 'after-frontend; verified unchanged before publication'),
                    'source_inventory': list(inventory.values()),
                    'source_inventory_limits': {'files': 10000, 'bytes': 64 * 1024 * 1024} if frozen_inventory else None,
                    'input_identity_scope': ('pre/post byte inventory; not per-read snapshots; does not exclude ABA mutations'
                                             if frozen_inventory else 'post-frontend observation'),
                    'host_inputs': frozen_inputs,
                    'runtime_sha256': digest(runtime.encode()),
                    'standalone_ir_sha256': digest(standalone.read_bytes()),
                    'target_triple': toolchain.triple, 'data_layout': toolchain.data_layout,
                    'toolchain': {'version': getattr(toolchain, 'version', None),
                                  'clang': getattr(toolchain, 'clang', None),
                                  'tools': getattr(toolchain, 'tools', None),
                                  'link_flags': getattr(toolchain, 'link_flags', None)}}
        if dense:
            evidence['dense_protocol'] = dense_protocol.PROTOCOL
            evidence['dense_plan_encoding'] = dense_protocol.PLAN_ENCODING
            evidence['dense_manifest'] = next(item for item in frozen_inputs if item['path'] == str(manifest))
            evidence['dense_packet'] = packet_identity
            evidence['dense_plan'] = plan_identity
            evidence['dense_transport'] = packet
            evidence['dense_selected_plan'] = selected_plan
            dense_protocol.verify_proof_hashes(evidence)
            dense_protocol.verify([packet_identity, plan_identity, *inventory.values()])
        if keep_frontend:
            evidence['artifacts']['frontend_ir'] = {'path': str(output.with_name(output.name+'.frontend.ll')),
                                                    'sha256': evidence['source_ir_sha256']}
            evidence['artifacts']['metadata'] = {'path': str(output.with_name(output.name+'.metadata.c')),
                                                 'sha256': evidence['metadata_sha256']}
        verify_inputs(inventory.values())
        verify_inputs(frozen_inputs)
        verify_inputs(dependency_identities)
        # Prepare all output bytes before publication; proof is committed last.
        artifacts = []
        if keep_frontend:
            for suffix, content in (('.frontend.ll', ir), ('.metadata.c', descriptors)):
                staged = stage/('saved'+suffix)
                staged.write_text(content, encoding='utf-8', newline='\n')
                artifacts.append((staged, output.with_name(output.name+suffix)))
        if emit_llvm:
            artifacts.append((standalone, Path(emit_llvm).resolve()))
        artifacts.append((executable, output))
        if proof:
            staged = stage/'proof.json'
            staged.write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
            artifacts.append((staged, Path(proof).resolve()))
        if dense:
            dense_protocol.verify([packet_identity, plan_identity, *inventory.values()])
            dense_protocol.verify(frozen_inputs)
            verify_inputs(frozen_inputs)
            dense_protocol.reject_overlap([*protected, *inventory, packet_path, plan_path], destinations)
        publish_artifacts(artifacts)
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
    # Freeze the entire bundled Ru input set, including imported frontend helpers.
    bootstrap_inputs = [file_identity(path) for path in sorted(
        set((ROOT/'bootstrap').rglob('*.ru')) | set((ROOT/'rulang/stdlib').rglob('*.ru')))]
    print('Stage0 → stage1: Python LLVM frontend compiles Ru compiler source', flush=True)
    stage0_started = time.monotonic()
    build(parse(frozen_source.decode('utf-8')), source, stages[0], target='llvm', llvm_clang=selected)
    report = {'platform': sys.platform, 'triple': toolchain.triple, 'llvm': toolchain.version,
              'source_sha256': digest(frozen_source), 'source_inputs': bootstrap_inputs, 'stage0_seconds': time.monotonic()-stage0_started, 'stages': []}
    for index in (0, 1):
        verify_identities(bootstrap_inputs)
        if source.read_bytes() != frozen_source:
            raise RuntimeError('compiler source changed during bootstrap; restart with a frozen source')
        print(f'Stage{index+1} → stage{index+2}: native Ru compiler compiles the same source', flush=True)
        evidence = compile_native(stages[index], source, stages[index+1], toolchain,
                                  emit_llvm=directory/('stage'+str(index+2)+'.ll'), keep_frontend=True)
        report['stages'].append(evidence)
    if source.read_bytes() != frozen_source:
        raise RuntimeError('compiler source changed during bootstrap; restart with a frozen source')
    verify_identities(bootstrap_inputs)
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
    build.add_argument('--allow-native', action='store_true', help='opt in to versioned Windows native ABI')
    build.add_argument('--experimental-mi-manifest', help='explicit private dense UTF8 manifest (default off)')
    build.add_argument('--proof', help='write build input and artifact identity evidence')
    build.add_argument('--linker', help='pin an absolute Windows link.exe or lld-link.exe path')
    build.add_argument('--source-root', action='append', default=[],
                       help='extra directory of .ru inputs to freeze before native frontend execution')
    args = parser.parse_args(argv)
    try:
        if args.command == 'bootstrap':
            bootstrap(args.directory, args.llvm_clang)
        elif args.command == 'verify':
            from tools.bootstrap_verify import verify
            return 0 if verify(args.directory, args.llvm_clang)['m4_complete'] else 1
        else:
            compile_native(args.compiler, args.source, args.output, LLVMToolchain(args.llvm_clang),
                           emit_llvm=args.emit_llvm, allow_native=args.allow_native, proof=args.proof,
                           source_roots=args.source_root, linker=args.linker,
                           experimental_mi_manifest=args.experimental_mi_manifest)
    except (RuError, OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
