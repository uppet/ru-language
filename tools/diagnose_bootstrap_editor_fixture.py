#!/usr/bin/env python3
"""Same-runner C control vs stage3 LLVM: diagnostic only, never a release gate.

The Python C frontend is used ONLY for the named control. The bootstrap binary
must already exist with an independently validated stage3 build receipt.
"""
import argparse
import ctypes
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import time

SCHEMA = 'ru-notepad-same-runner-diagnostic-v1'
ENTRY = 'tests/bootstrap_pipeline/dll_abi_probe.ru'
ORDER = ('python-c-baseline', 'python-c-via-llvm-control', 'stage3-llvm')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'invalid diagnostic input')
    raw = path.read_bytes()
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def emit_c(language, source, output):
    # Invoked in isolated Python (-I); no ambient PYTHONPATH/site frontend.
    sys.path.insert(0, str(Path(language).resolve()))
    from rulang.frontend import parse
    from rulang.modules import load_module_graph
    from rulang.compiler import Compiler
    text = Path(source).read_text(encoding='utf-8-sig')
    program = parse(text)
    graph = load_module_graph(str(Path(source).resolve()), program)
    graph.sources[graph.root] = text
    module_records = []
    for name, parsed in sorted(graph.sources.items()):
        raw = Path(name).read_bytes()
        decoded = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
        require(decoded == parsed, 'C graph source changed after parse')
        module_records.append({'path': str(Path(name).resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)})
    code = Compiler(program, graph.root, modules=graph, allow_native=True).compile()
    for record in module_records:
        require(identity(record['path']) == record, 'C graph source changed during generation')
    with Path(output).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(code)
    with Path(output).with_suffix('.sources.json').open('x', encoding='utf-8') as stream:
        json.dump({'module_sources': module_records, 'generated_c': identity(output)}, stream, indent=2)


def fresh_owned(path, source_roots):
    from ctypes import wintypes as w
    path = Path(path).absolute()
    require(not path.exists() and not any(p.is_symlink() for p in path.parents), 'diagnostic root must be fresh')
    require(re.fullmatch(r'[A-Za-z]:', path.drive) and all(p and p[-1] not in '. ' and not re.search(r'[<>:"|?*\x00-\x1f]', p)
            and not re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p, re.I) for p in path.parts[1:]), 'ordinary local path required')
    require(not any(path.resolve().is_relative_to(Path(r).resolve()) for r in source_roots), 'diagnostic cannot modify source')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetDriveTypeW.argtypes, kernel.GetDriveTypeW.restype = [w.LPCWSTR], w.UINT
    require(kernel.GetDriveTypeW(path.anchor) == 3, 'fixed local drive required')
    for parent in path.parents:
        if parent.exists():
            require(not parent.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT, 'reparse diagnostic parent forbidden')
    path.mkdir(parents=True, exist_ok=False)
    return path


def phase(result, name, callback):
    start = time.monotonic()
    row = {'name': name, 'started_monotonic': start, 'completed': False}
    result['phases'].append(row)
    try:
        value = callback()
        row['completed'] = True
        return value
    except Exception as exc:
        row['error'] = str(exc)
        raise
    finally:
        row['seconds'] = time.monotonic() - start


def command(argv, cwd, env, label, evidence, input=None, timeout=600):
    stdout, stderr = cwd/(label+'.stdout.log'), cwd/(label+'.stderr.log')
    record = {'argv': list(map(str, argv)), 'cwd': str(cwd), 'environment': env,
              'environment_sha256': hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest(),
              'timeout_seconds': timeout, 'returncode': None}
    evidence.append(record)
    stdin = None if input is None else input.encode('utf-8')
    record['stdin_sha256'] = None if stdin is None else hashlib.sha256(stdin).hexdigest()
    try:
        with stdout.open('xb') as out, stderr.open('xb') as err:
            done = subprocess.run(record['argv'], cwd=cwd, env=env, stdout=out, stderr=err, input=stdin, timeout=timeout)
        record['returncode'] = done.returncode
        require(done.returncode == 0, 'diagnostic command failed: '+label)
    finally:
        record['stdout'], record['stderr'] = identity(stdout), identity(stderr)
    raw = stdout.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == record['stdout']['sha256'] and len(raw) == record['stdout']['size'], 'diagnostic stdout changed before parse')
    return raw.decode('utf-8')


def stage(binary, directory, dependencies, gate):
    directory.mkdir(exist_ok=False)
    records = []
    for record in [binary, *[dependencies['binaries'][name] for name in (*gate.DLLS, 'RuSyntaxWrongAbi.dll')]]:
        source = gate.verify_identity(record)
        target = directory/('ru_notepad.exe' if record is binary else source.name)
        shutil.copyfile(source, target)
        copied = identity(target)
        require((copied['sha256'], copied['size']) == (record['sha256'], record['size']), 'diagnostic copy changed')
        records.append(copied)
    return directory/'ru_notepad.exe', records


def compare_graph(control, bootstrap):
    def indexed(records):
        result = {}
        for record in records:
            key = str(Path(record['path']).resolve())
            require(key not in result, 'duplicate graph source path')
            result[key] = (record['sha256'], record['size'])
        return result
    require(indexed(control) == indexed(bootstrap), 'C and stage3 actual source graphs differ')


def metric(line):
    schemas = {
        'PERF_RU': ({'size', 'initial_read_bytes', 'edit_read_bytes', 'reused_bytes', 'max_read'},
                    {'initial_ms', 'edit_ms', 'max_tick_ms', 'max_chunk_ms'}),
        'RU_GUI_SYNC': ({'size', 'source_chars', 'read_bytes', 'max_read', 'chunks'},
                       {'wall_ms', 'max_tick_ms', 'max_chunk_ms'}),
    }
    parts = line.split()
    integers, floats = schemas[parts[0]]
    fields = {}
    for token in parts[1:]:
        require(token.count('=') == 1, 'malformed diagnostic metric')
        key, value = token.split('=', 1)
        require(key not in fields and key in integers | floats, 'unknown/duplicate diagnostic metric')
        if key in integers:
            require(re.fullmatch(r'[0-9]+', value), 'invalid integer metric')
        else:
            require(re.fullmatch(r'[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?', value)
                    and math.isfinite(float(value)), 'invalid finite nonnegative metric')
        fields[key] = value
    require(set(fields) == integers | floats, 'incomplete diagnostic metric')
    return {'kind': parts[0], 'fields': fields}


def partial_log(directory, gate):
    paths = list(directory.glob('ru_notepad-*.log'))
    require(len(paths) <= 1, 'ambiguous diagnostic child logs')
    if not paths:
        return {'available': False, 'metrics': []}
    raw, record = gate.read_log_bytes(paths[0])
    text = raw.decode('utf-8')
    metrics = []
    for line in text.splitlines():
        if line.startswith(('PERF_RU ', 'RU_GUI_SYNC ')):
            metrics.append(metric(line))
    require(gate.read_log_bytes(paths[0])[1] == record, 'partial diagnostic log changed')
    return {'available': True, 'identity': record, 'last_output_lines': text.splitlines()[-20:], 'metrics': metrics}


def runtime_child(gate, api, exe, environment):
    # Both children inherit one environment. Preserve actual module observations
    # on timeout too; this does not relax or replace gate.run_child's assertions.
    original_env = dict(os.environ)
    original_modules = gate.loaded_dlls
    observations = {'pid': None, 'snapshots': 0, 'verified': {}, 'complete': False}
    def observe(pid):
        require(observations['pid'] in (None, pid), 'diagnostic observed a different child PID')
        observations['pid'] = pid
        modules = original_modules(pid)
        observations['snapshots'] += 1
        for name, record in modules.items():
            expected = identity(exe.parent/name)
            require(record == expected, 'diagnostic module outside same owned DLL bytes')
            observations['verified'][name] = record
        observations['complete'] = set(gate.DLLS) <= set(observations['verified'])
        return modules
    try:
        os.environ.clear()
        os.environ.update(environment)
        gate.loaded_dlls = observe
        row = gate.run_child(api, exe, ['ru'], marker='BOOTSTRAP_DLL_ABI_PASS:ru', required_dlls=gate.DLLS)
        if observations['pid'] is not None:
            require(row.get('pid') == observations['pid'], 'observed module PID differs from owned process')
        row['diagnostic_module_observations'] = observations
        return row
    finally:
        gate.loaded_dlls = original_modules
        os.environ.clear()
        os.environ.update(original_env)


def run_pair(build_control, run_control, run_bootstrap, rows=None):
    """A control failure must not skip or replace the bootstrap observation."""
    rows = {} if rows is None else rows
    try:
        binary = build_control()
        rows[ORDER[0]] = run_control(binary)
    except Exception as exc:
        rows.setdefault(ORDER[0], {'executed': False})
        rows[ORDER[0]].update(passed=False, error=str(exc))
    # This call independently validates frozen inputs before launching anything.
    rows[ORDER[-1]] = run_bootstrap()
    return rows


def compile_c_via_llvm(toolchain_type, generated, directory, receipt, driver, gate, environment, result, revalidate):
    """Python-generated C control, NOT a stage3 build or bootstrap proof."""
    tools = receipt['tool_paths']
    triple, layout = receipt['target_triple'], receipt['data_layout']
    generated_record = identity(generated)
    require(generated_record == result['control_source_graph']['generated_c'], 'shared generated C changed')
    raw = generated.read_bytes()
    require(identity(generated) == generated_record, 'shared generated C changed while reading')
    directory.mkdir(exist_ok=False)
    evidence = {'frontend': 'Python Compiler C emission (diagnostic control only)',
                'backend': 'LLVMToolchain.compile internalize/default<O2>/globaldce then llc',
                'bootstrap_proof': False, 'release_permission': False, 'generated_c': generated_record,
                'target_triple': triple, 'data_layout': layout, 'commands': [], 'artifacts': [],
                'linker_selections': [], 'environment': environment,
                'environment_sha256': hashlib.sha256(json.dumps(environment, sort_keys=True).encode()).hexdigest()}
    result['llvm_control'] = evidence
    linker_record = identity(tools['linker'])
    driver.validate_toolchain(tools, receipt['tool_sha256'])
    def frozen():
        require(identity(generated) == generated_record, 'shared generated C changed during LLVM control')
        driver.validate_toolchain(tools, receipt['tool_sha256'])
        for record in evidence['artifacts']: gate.verify_identity(record)
    pipeline_names = ('program.ll','runtime.c','program.bc','runtime.bc','linked.bc','optimized.bc','standalone.ll','program.o','program.exe')
    def freeze_pipeline_outputs():
        frozen()
        seen = {record['path'] for record in evidence['artifacts']}
        for name in pipeline_names:
            path = directory/name
            if path.is_file() and str(path.resolve()) not in seen:
                evidence['artifacts'].append(identity(path))
    class ControlToolchain(toolchain_type):
        def run(self, argv, input=None):
            argv = list(map(str,argv))
            require(argv and argv[0] in tools.values(), 'LLVM control attempted unpinned executable')
            # Same pure-object link, exact target and locked linker; no IR rewrite.
            pure_link = argv == [tools['clang'], str(directory/'program.o'), '-o', str(directory/'program.exe'),
                                 *driver.explicit_linker_flags(linker_record)]
            require(str(directory/'program.exe') not in argv or pure_link, 'unexpected LLVM console linker argv')
            if pure_link: argv.insert(1, '--target='+triple)
            freeze_pipeline_outputs()
            selection = None
            if pure_link:
                selection = driver.inspect_linker_command(argv,linker_record,environment,str(directory),triple)
                evidence['linker_selections'].append(selection)
            value = command(argv,directory,environment,'llvm-'+str(len(evidence['commands'])),evidence['commands'], input=input, timeout=120)
            if selection: driver.verify_linker_selection(selection,tools,expected_command=argv,triple=triple)
            freeze_pipeline_outputs()
            return value
    chain = ControlToolchain(tools['clang'])
    require(chain.clang == [tools['clang']] and chain.tools == {name:tools[name] for name in ('llvm-as','llvm-link','opt','llvm-dis','llc')}, 'LLVM control selected different tools')
    require(chain.triple == triple and chain.data_layout == layout, 'LLVM control target/layout differs')
    chain.link_flags = driver.explicit_linker_flags(linker_record)
    program = 'target datalayout = '+json.dumps(layout)+'\ntarget triple = '+json.dumps(triple)+'\n'
    console, ir = chain.compile(program,raw.decode('utf-8'),directory,full_runtime=False)
    require(len(evidence['linker_selections']) == 1, 'LLVM control pure-object explicit link not observed')
    names = ('program.ll','runtime.c','program.bc','runtime.bc','linked.bc','optimized.bc','standalone.ll','program.o','program.exe')
    require({Path(record['path']).name for record in evidence['artifacts']} == set(names), 'incomplete LLVM pipeline evidence')
    require((directory/'runtime.c').read_bytes() == raw, 'LLVM runtime C differs from shared C')
    require((directory/'program.ll').read_bytes() == program.encode(), 'empty target module changed')
    # Reuse the proven fixed C launcher object and original SDK resource bytes.
    # main stays main in the LLVM module; no textual IR/name transformation.
    evidence['reused_gui_inputs'] = {name:receipt['linked_inputs'][name] for name in ('launcher.obj','application.res')}
    for name, record in evidence['reused_gui_inputs'].items():
        shutil.copyfile(gate.verify_identity(record),directory/name)
        copied = identity(directory/name)
        require((copied['sha256'],copied['size']) == (record['sha256'],record['size']), 'reused GUI input changed')
        evidence['artifacts'].append(copied)
    plan = driver.link_commands(tools,ir,Path('unused-fixed-wrapper'),Path('unused-app'),directory,triple)
    frozen()
    command(plan[0],directory,environment,'gui-llc',evidence['commands'])
    evidence['artifacts'].append(identity(directory/'application.obj'))
    frozen()
    selection = driver.inspect_linker_command(plan[-1],linker_record,environment,str(directory),triple)
    evidence['linker_selections'].append(selection)
    command(plan[-1],directory,environment,'gui-link',evidence['commands'])
    driver.verify_linker_selection(selection,tools,expected_command=plan[-1],triple=triple)
    frozen()
    binary = directory/'ru_notepad.exe'
    driver.verify_gui_pe(binary)
    evidence['artifacts'].append(identity(binary))
    for record in evidence['reused_gui_inputs'].values(): gate.verify_identity(record)
    revalidate()
    evidence['complete'] = True
    return identity(binary)


def run_three(build_control, run_control, build_llvm, run_llvm, run_bootstrap, rows=None):
    """Each named control can fail independently; bootstrap still runs once."""
    rows = {} if rows is None else rows
    for label, build, run in ((ORDER[0],build_control,run_control),(ORDER[1],build_llvm,run_llvm)):
        try:
            rows[label] = run(build())
        except Exception as exc:
            rows.setdefault(label, {'executed': False})
            rows[label].update(passed=False,error=str(exc))
    rows[ORDER[2]] = run_bootstrap()
    return rows


def diagnose(config):
    require(sys.platform == 'win32' and platform.machine() in ('AMD64', 'x86_64') and ctypes.sizeof(ctypes.c_void_p) == 8, 'real Windows x64 required')
    gate_config = config['gate_config']
    app = Path(config['editor_root']).resolve()
    sys.path.insert(0, str(app/'tools'))
    gate = importlib.import_module('verify_bootstrap_editor_windows')
    deps = importlib.import_module('prepare_bootstrap_dependencies')
    require(Path(gate.__file__).resolve() == app/'tools/verify_bootstrap_editor_windows.py', 'wrong pinned GUI validator')
    receipts = gate.validate_receipts(gate_config)
    dll_receipt = receipts['dll_probe_receipt']
    require(Path(dll_receipt['source_pins']['app_source']['path']).resolve() == app, 'diagnostic app differs from proof')
    language = Path(dll_receipt['source_pins']['ru_source']['path']).resolve()
    require(Path(__file__).resolve() == language/'tools/diagnose_bootstrap_editor_fixture.py', 'diagnostic must be in pinned language checkout')
    diagnostic_paths = ('tools/diagnose_bootstrap_editor_fixture.py', 'tests/test_bootstrap_editor_diagnostic.py', '.github/workflows/bootstrap-native.yml')
    for relative in diagnostic_paths:
        require(dll_receipt['source_sha256']['ru_source'].get(relative) == identity(language/relative)['sha256'],
                'diagnostic/workflow path absent or changed in tracked source inventory: '+relative)
    dependencies = deps.validate_receipt(Path(gate_config['dependencies_receipt']))
    require(dependencies['app_source'] == dll_receipt['source_pins']['app_source'] and dependencies['source_sha256'] == dll_receipt['source_sha256']['app_source'], 'C and LLVM dependencies/source differ')
    owned = fresh_owned(config['owned_root'], [app, language])
    result = {'schema': SCHEMA, 'diagnostic_only': True, 'release_permission': False,
              'bootstrap_acceptance': False, 'performance_acceptance': False,
              'fixed_order': list(ORDER), 'runtime_seconds_per_child': 60,
              'not_statistical_benchmark': True, 'phases': [], 'commands': [], 'copies': [],
              'source_pins': dll_receipt['source_pins'], 'source_sha256': dll_receipt['source_sha256'],
              'entry': identity(app/ENTRY), 'dependencies_receipt': identity(gate_config['dependencies_receipt']),
              'stage3_receipt': identity(gate_config['dll_probe_receipt']),
              'inputs': [*[identity(language/name) for name in diagnostic_paths], identity(sys.executable), identity(app/'packaging/diagnostic_launcher.c')],
              'tool_paths': dependencies['tool_paths'], 'tool_sha256': dependencies['tool_sha256'],
              'limitations': ['fixed order may have warm-cache/time effects', 'C-via-LLVM controls toolchain differences but frontend/runtime representation and fixed-order effects remain', '60s incomplete observations remain censored']}
    env = deps.dependency_environment(dependencies['tool_paths'], os.environ)
    env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    result['runtime_environment'] = env
    result['runtime_environment_sha256'] = hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()
    result['invocation'] = list(sys.argv)
    tools = dependencies['tool_paths']
    api = gate.load_windows_harness(app).Windows()
    def revalidate():
        gate.validate_receipts(gate_config)
        deps.validate_receipt(Path(gate_config['dependencies_receipt']))
        for record in [*result['inputs'], *result['copies'], *result.get('llvm_control',{}).get('artifacts',[]), result['entry'], result['dependencies_receipt'], result['stage3_receipt']]:
            gate.verify_identity(record)
    def build_control():
        revalidate()
        build = owned/'c-build'; build.mkdir()
        generated, translation, resource, binary = (build/name for name in ('probe.c', 'probe-gui.c', 'app-resource.o', 'python-c-baseline.exe'))
        phase(result, 'control-generate-c', lambda: command([sys.executable, '-I', '-B', __file__, '--emit-c', str(language), str(app/ENTRY), str(generated)], build, env, 'generate-c', result['commands']))
        graph_path = generated.with_suffix('.sources.json')
        graph_raw = graph_path.read_bytes(); graph = json.loads(graph_raw)
        graph_record = {'path': str(graph_path.resolve()), 'size': len(graph_raw), 'sha256': hashlib.sha256(graph_raw).hexdigest()}
        require(identity(graph_path) == graph_record, 'C graph evidence changed')
        proof_path = Path(gate_config['dll_probe_receipt']).parent/'compile-proof.json'
        proof_raw = proof_path.read_bytes()
        require(hashlib.sha256(proof_raw).hexdigest() == dll_receipt['compile_proof_sha256'], 'stage3 proof changed before graph comparison')
        compare_graph(graph['module_sources'], json.loads(proof_raw)['dependencies'])
        result['control_source_graph'] = graph
        result['inputs'].append(graph_record)
        generated_record = identity(generated)
        require(generated_record == graph['generated_c'], 'C generation output changed')
        result['control_artifacts'] = [generated_record]
        result['inputs'].append(generated_record)
        launcher = (app/'packaging/diagnostic_launcher.c').read_bytes()
        translation.write_bytes(b'#define main ru_program_main\n'+generated.read_bytes()+b'\n#undef main\n'+launcher)
        translation_record = identity(translation)
        result['control_artifacts'].append(translation_record)
        result['inputs'].append(translation_record)
        phase(result, 'control-resource', lambda: command([tools['windres'], '-I', str(app/'packaging'), str(app/'packaging/app.rc'), str(resource)], build, env, 'resource', result['commands']))
        resource_record = identity(resource)
        result['control_artifacts'].append(resource_record)
        result['inputs'].append(resource_record)
        phase(result, 'control-compile-link', lambda: command([tools['cc'], '-std=c99', '-O2', '-Wall', '-Wextra', '-Wno-unused-function', '-static-libgcc', str(translation), '-o', str(binary), '-lm', str(resource), '-mwindows', '-lshell32', '-luser32'], build, env, 'compile-link', result['commands']))
        result['control_artifacts'].append(identity(binary))
        result['inputs'].append(result['control_artifacts'][-1])
        for record in result['control_artifacts']: gate.verify_identity(record)
        gate.verify_gui_pe(binary)
        revalidate()
        return identity(binary)
    def build_llvm_control():
        revalidate()
        sys.path.insert(0,str(language))
        from rulang.llvm_toolchain import LLVMToolchain
        from rulang.toolchain_environment import llvm_environment
        require(Path(sys.modules['rulang.llvm_toolchain'].__file__).resolve() == language/'rulang/llvm_toolchain.py'
                and Path(sys.modules['rulang.toolchain_environment'].__file__).resolve() == language/'rulang/toolchain_environment.py', 'wrong pinned LLVM control module')
        driver = importlib.import_module('build_bootstrap_release')
        require(Path(driver.__file__).resolve() == app/'tools/build_bootstrap_release.py', 'wrong pinned GUI build driver')
        for name in ('rulang/llvm_toolchain.py','rulang/toolchain_environment.py'):
            require(dll_receipt['source_sha256']['ru_source'].get(name) == identity(language/name)['sha256'], 'LLVM control code not tracked in frozen source')
            result['inputs'].append(identity(language/name))
        llvm_env = llvm_environment()
        require(not any(llvm_env.get(k) for k in ('CL','_CL_','LINK','_LINK_')), 'ambient LLVM control flags forbidden')
        sdk = {k:v for k,v in llvm_env.items() if k.upper() in {'PATH','INCLUDE','LIB','LIBPATH','WINDOWSSDKDIR','WINDOWSSDKVERSION','VCTOOLSINSTALLDIR','VCTOOLSVERSION'}}
        require(sdk == dll_receipt['sdk_crt_environment'], 'LLVM control SDK/CRT environment differs from bootstrap')
        return phase(result,'control-c-via-llvm',lambda: compile_c_via_llvm(LLVMToolchain,owned/'c-build/probe.c',owned/'c-llvm-build',dll_receipt,driver,gate,llvm_env,result,revalidate))
    def run_backend(label, binary):
        revalidate()
        exe, copies = stage(binary, owned/label, dependencies, gate)
        result['copies'].extend(copies)
        row = phase(result, 'run-'+label, lambda: runtime_child(gate, api, exe, env))
        result['results'][label] = row
        row['backend'] = label
        row['censored'] = bool(row.get('cleanup_killed'))
        row['partial_output'] = partial_log(exe.parent, gate)
        revalidate()
        return row
    result['results'] = {}
    try:
        run_three(build_control,
            lambda binary: run_backend(ORDER[0], binary),
            build_llvm_control, lambda binary: run_backend(ORDER[1], binary),
            lambda: run_backend(ORDER[2], dll_receipt['final_binary']), result['results'])
        result['status'] = 'diagnostic-complete'
    except Exception as exc:
        result.update(status='diagnostic-failed', error=str(exc))
    try:
        revalidate()
        for row in result.get('results', {}).values():
            if row.get('partial_output', {}).get('available'):
                require(gate.read_log_bytes(row['partial_output']['identity']['path'])[1] == row['partial_output']['identity'], 'diagnostic evidence changed')
    except Exception as exc:
        result.update(status='diagnostic-failed', evidence_error=str(exc))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--emit-c', nargs=3)
    args = parser.parse_args()
    if args.emit_c:
        require(args.config is None and args.output is None, 'conflicting worker mode')
        emit_c(*args.emit_c)
        return 0
    require(args.config and args.output and not args.output.exists(), 'fresh diagnostic output required')
    config_raw = args.config.read_bytes()
    try:
        result = diagnose(json.loads(config_raw))
    except Exception as exc:
        result = {'schema': SCHEMA, 'diagnostic_only': True, 'release_permission': False, 'bootstrap_acceptance': False, 'status': 'diagnostic-failed', 'error': str(exc)}
    require(args.config.read_bytes() == config_raw, 'diagnostic config changed')
    result['config_sha256'] = hashlib.sha256(config_raw).hexdigest()
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=True)
    return 0 if result.get('status') == 'diagnostic-complete' and set(result.get('results', {})) == set(ORDER) and all(row.get('passed') is True for row in result.get('results', {}).values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
