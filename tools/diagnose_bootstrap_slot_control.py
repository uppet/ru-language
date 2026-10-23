#!/usr/bin/env python3
"""Same-runner old6e stage3 control. Diagnostic only, never release/performance acceptance."""
import argparse
import hashlib
import importlib
import json
import os
import stat
from pathlib import Path
import sys
import time

OLD = '6e03236c4fecf5a5219eb28a3ba1c46bfeb36d65'
TREE = 'd7f53f270006729fc8761e3328d1bf8110c99b97'
APP = '5a900a037cd54f4f89c3658e246195bbf3d389d3'
APP_TREE = '06eefc5de1fb864cbb7676e5950acc23752d53c5'
ENTRY = 'tests/bootstrap_pipeline/dll_abi_probe.ru'
SCHEMA = 'ru-slot-old-stage3-control-v1'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(path):
    path = Path(path)
    require(path.is_absolute() and path.is_file() and not any(p.is_symlink() for p in (path, *path.parents)), 'unsafe control input')
    require(not any(getattr(p.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT for p in (path, *path.parents)), 'reparse control input')
    raw = path.read_bytes()
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def read(path):
    path = Path(path)
    record = identity(path)
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == record['sha256'] and len(raw) == record['size'], 'control input changed while reading')
    return json.loads(raw), record


def check(records):
    for record in records:
        require(identity(record['path']) == record, 'frozen control input changed')


def save(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def graph(records, app, language):
    """Exact relative membership with two explicit repository roots, not basename matching."""
    roots = {'app': Path(app).resolve(), 'language': Path(language).resolve()}
    require(not roots['app'].is_relative_to(roots['language']) and not roots['language'].is_relative_to(roots['app']), 'overlapping source roots')
    result = {}
    for record in records:
        path = Path(record['path']).resolve()
        matches = [(name, path.relative_to(root).as_posix()) for name, root in roots.items() if path.is_relative_to(root)]
        require(len(matches) == 1 and matches[0] not in result, 'unknown/duplicate source graph member')
        require(identity(path) == record, 'source graph bytes changed')
        result[matches[0]] = (record['sha256'], record['size'])
    require(result, 'empty source graph')
    return result


def language_delta(old, new):
    allowed = {
        'bootstrap/compiler.ru', 'rulang/llvm_compiler.py',
        'tests/test_bootstrap_editor_diagnostic.py',
        '.github/workflows/bootstrap-slot-reuse.yml',
        'tests/bootstrap_slot_cases.py', 'tests/fixtures/slot_reuse_native/main.ru',
        'tests/fixtures/slot_reuse_native/panic_module.ru', 'tests/test_bootstrap_slot_ci.py',
        'tests/test_bootstrap_slot_reuse.py', 'tests/test_bootstrap_slot_reuse_native.py',
        'tests/test_bootstrap_slot_workflow.py', 'tools/verify_bootstrap_slot_ci.py',
        'tools/bootstrap_slot_old_artifact.py', 'tests/test_bootstrap_slot_old_artifact.py',
        'tools/diagnose_bootstrap_slot_control.py', 'tests/test_bootstrap_slot_control.py',
    }
    changed = {name for name in old.keys() | new.keys() if old.get(name) != new.get(name)}
    require(changed == allowed and not old.keys() - new.keys(), 'unreviewed old/new language delta')
    for name, digest in {
        'bootstrap/compiler.ru':'d83691c0eb9af56d8954224b49906b1fb8b910e520577ead43efc9671e269a60',
        'rulang/llvm_compiler.py':'1edd71ceaa97b5eed6e8ea519dbe32bfc88b510df54b33f3af1c787bbb7b6f26',
        'tests/test_bootstrap_editor_diagnostic.py':'0a257f51a6f90c4b78a6a9524366f5f92e71497d6b565e9b0a352ad2cf5365e2',
    }.items():
        require(new.get(name) == digest, 'unreviewed production/mock-fix patch')
    return sorted(changed)


def compare(old, new):
    language_delta(old['source_sha256']['ru_source'], new['source_sha256']['ru_source'])
    for field in ('app_source',):
        require(old['source_pins'][field] == new['source_pins'][field], 'different editor source')
    for field in ('tool_paths', 'tool_sha256', 'target_triple', 'data_layout', 'sdk_crt_environment', 'app_baseline', 'entry_source'):
        require(old[field] == new[field], 'old/new control differs: '+field)
    require(old['source_sha256']['app_source'] == new['source_sha256']['app_source'], 'different editor inventory')


def context(config):
    require(sys.platform == 'win32', 'real Windows required')
    require(not any(os.environ.get(name) for name in ('GITHUB_TOKEN', 'GH_TOKEN')), 'artifact token must be scoped to download step only')
    import bootstrap_slot_old_artifact as loader
    import diagnose_bootstrap_editor_fixture as diagnostic
    base, base_record = read(config['base_config'])
    gate_config, gate_record = read(config['gate_config'])
    app = Path(base['app_source']['path']).resolve()
    require(base['app_source']['commit'] == APP and base['app_source']['tree'] == APP_TREE, 'unreviewed editor pin')
    sys.path.insert(0, str(app/'tools'))
    modules = [importlib.import_module(name) for name in ('verify_bootstrap_editor_windows', 'build_bootstrap_release', 'prepare_bootstrap_dependencies')]
    for module in modules:
        require(Path(module.__file__).resolve() == app/'tools'/(module.__name__+'.py'), 'unreviewed editor helper')
    gate, driver, deps = modules
    receipts = gate.validate_receipts(gate_config)
    new = receipts['dll_probe_receipt']
    require(new['source_pins'] == {name: base[name] for name in ('ru_source', 'app_source')}, 'base config differs from new receipt')
    require(new['tool_paths'] == base['tool_paths'] and new['tool_sha256'] == base['tool_sha256'], 'base tools differ')
    require(Path(__file__).resolve() == Path(base['ru_source']['path']).resolve()/'tools/diagnose_bootstrap_slot_control.py', 'control not from current source')
    old_root = Path(config['old_source']).resolve()
    driver.snapshot(old_root, OLD, TREE)
    artifact = loader.verify_output(Path(config['old_artifact']))
    dependencies = deps.validate_receipt(Path(gate_config['dependencies_receipt']))
    require(dependencies['app_source'] == new['source_pins']['app_source'] and dependencies['source_sha256'] == new['source_sha256']['app_source'], 'dependency source differs')
    require(dependencies['tool_paths'] == base['mingw_tool_paths'] and dependencies['tool_sha256'] == base['mingw_tool_sha256'], 'dependency tools differ')
    environment = deps.dependency_environment(dependencies['tool_paths'], os.environ)
    environment.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    return base, gate_config, new, artifact, dependencies, environment, modules, diagnostic, [base_record, gate_record]


def validate_old(path, config, new, driver, gate):
    old, receipt_record = read(path)
    require(old['schema'] == 'ru-notepad-bootstrap-llvm-build-v1' and old['status'] == 'built-not-runtime-accepted-not-publishable' and old['native_acceptance'] is False, 'invalid old build receipt')
    require(old['source_pins']['ru_source'] == {'path': str(Path(config['old_source']).resolve()), 'commit': OLD, 'tree': TREE}, 'old source identity changed')
    require(old['entry_source'] == ENTRY, 'wrong old fixture')
    compare(old, new)
    for name, pin in old['source_pins'].items():
        require(driver.snapshot(Path(pin['path']), pin['commit'], pin['tree']) == old['source_sha256'][name], 'old source changed')
    for name, digest in old['driver_inputs'].items():
        require(identity(name)['sha256'] == digest, 'old driver input changed')
    driver.validate_toolchain(old['tool_paths'], old['tool_sha256'])
    driver.verify_gui_pe(gate.verify_identity(old['final_binary']))
    directory = Path(path).parent
    proof, proof_record = read(directory/'compile-proof.json')
    require(proof_record['sha256'] == old['compile_proof_sha256'] and proof['standalone_ir_sha256'] == old['standalone_ir_sha256'], 'old proof changed')
    compiler = Path(config['old_artifact'])/'stage3.exe'
    require(Path(proof['compiler']['path']).resolve() == compiler.resolve(), 'wrong old compiler path')
    require(old['bootstrap_verification'] == identity(Path(config['old_artifact'])/'verification.json'), 'old verification changed')
    require(old['bootstrap']['stage3_sha256'] == identity(compiler)['sha256'] and old['bootstrap']['verification_sha256'] == old['bootstrap_verification']['sha256'], 'old bootstrap identity changed')
    frozen = {str((Path(pin['path'])/name).resolve()): digest for key, pin in old['source_pins'].items() for name, digest in old['source_sha256'][key].items()}
    frozen[str(compiler.resolve())] = old['bootstrap']['stage3_sha256']
    frozen.update({str(Path(path).resolve()): old['tool_sha256'][name] for name, path in old['tool_paths'].items()})
    driver.verify_proof(proof, source=Path(old['source_pins']['app_source']['path'])/ENTRY, compiler=compiler,
        ir=directory/'application.ll', binary=directory/'intermediate-console.exe', triple=old['target_triple'], layout=old['data_layout'], frozen=frozen, tools=old['tool_paths'])
    require(set(old['linked_inputs']) == {'application.obj','launcher.obj','application.res'}, 'old linked inputs incomplete')
    for name, record in old['linked_inputs'].items():
        require(gate.verify_identity(record).resolve() == (directory/name).resolve(), 'old linked input outside build')
    driver.verify_linker_selection(old['final_linker_selection'], old['tool_paths'], expected_command=old['commands'][-1], triple=old['target_triple'])
    driver.verify_linker_probe(old['linker_probe'], old['tool_paths'], old['target_triple'], directory)
    gate_config, gate_config_record = read(config['gate_config'])
    new_proof, new_proof_record = read(Path(gate_config['dll_probe_receipt']).parent/'compile-proof.json')
    require(new_proof_record['sha256'] == new['compile_proof_sha256'], 'new proof changed')
    app = old['source_pins']['app_source']['path']
    old_graph = graph(proof['dependencies'], app, config['old_source'])
    new_graph = graph(new_proof['dependencies'], app, new['source_pins']['ru_source']['path'])
    require(old_graph == new_graph, 'old/new actual fixture source graphs differ')
    return old, [receipt_record, proof_record, new_proof_record, gate_config_record], [{'repository': k[0], 'path': k[1], 'sha256': v[0], 'size': v[1]} for k,v in sorted(old_graph.items())]


def prepare(config, config_record):
    base, gate_config, new, artifact, dependencies, env, modules, diag, inputs = context(config)
    gate, driver, deps = modules
    owned = diag.fresh_owned(config['owned_root'], [base['ru_source']['path'], base['app_source']['path'], config['old_source'], config['old_artifact']])
    old_config = dict(base, ru_source={'path':str(Path(config['old_source']).resolve()), 'commit':OLD, 'tree':TREE},
        bootstrap_directory=str(Path(config['old_artifact']).resolve()), verification=str(Path(config['old_artifact']).resolve()/'verification.json'), entry_source=ENTRY)
    save(owned/'old-config.json', old_config)
    start = time.monotonic()
    driver.build(old_config, owned/'build')
    old, records, sources = validate_old(owned/'build/build-receipt.json', config, new, driver, gate)
    # Same dependencies, no rebuild or replacement; old runtime is executed only later.
    exe, copies = diag.stage(old['final_binary'], owned/'runtime', dependencies, gate)
    result = {'schema':SCHEMA, 'phase':'prepared-not-executed', 'diagnostic_only':True, 'performance_acceptance':False,
        'config': config_record, 'old_artifact':artifact, 'old_receipt':str(owned/'build/build-receipt.json'),
        'inputs':inputs+records+[identity(owned/'old-config.json')], 'copies':copies, 'exe':str(exe),
        'runtime_environment':env, 'source_graph':sources, 'compile_seconds':time.monotonic()-start,
        'old_source_provenance':old['source_pins']['ru_source'], 'new_source_provenance':new['source_pins']['ru_source']}
    context(config)
    check([config_record, *result['inputs'], *copies])
    return result


def verify_copies(prepared, config, old, dependencies, gate):
    directory = Path(config['owned_root']).resolve()/'runtime'
    expected = {'ru_notepad.exe':old['final_binary']}
    expected.update({name:dependencies['binaries'][name] for name in (*gate.DLLS,'RuSyntaxWrongAbi.dll')})
    require(len(expected) == 5 and prepared['exe'] == str(directory/'ru_notepad.exe'), 'old executable outside exact prepared runtime')
    records = prepared['copies']
    require(isinstance(records,list) and len(records) == 5, 'exact five old runtime copies required')
    by_path = {record['path']:record for record in records}
    require(len(by_path) == 5 and set(by_path) == {str(directory/name) for name in expected}, 'old runtime copy paths differ')
    for name, source in expected.items():
        require(identity(source['path']) == source, 'old runtime source identity changed')
        copied = by_path[str(directory/name)]
        require(identity(directory/name) == copied, 'old runtime copy identity changed')
        require((copied['sha256'],copied['size']) == (source['sha256'],source['size']), 'old runtime copy differs from proven executable/dependency')


def run(config, config_record, prepared_path, three_path):
    prepared, prepared_record = read(prepared_path)
    require(prepared['schema'] == SCHEMA and prepared['phase'] == 'prepared-not-executed' and prepared['config'] == config_record, 'wrong preparation')
    base, gate_config, new, artifact, dependencies, env, modules, diag, inputs = context(config)
    gate, driver, deps = modules
    require(artifact == prepared['old_artifact'], 'old artifact changed')
    require(prepared['old_receipt'] == str(Path(config['owned_root']).resolve()/'build/build-receipt.json'), 'old receipt outside prepared build')
    old, records, sources = validate_old(prepared['old_receipt'], config, new, driver, gate)
    require(sources == prepared['source_graph'], 'prepared comparison changed')
    three, three_record = read(three_path)
    require(three.get('schema') == diag.SCHEMA and three.get('fixed_order') == list(diag.ORDER) and three.get('runtime_seconds_per_child') == 60, 'missing original three-route diagnostic')
    require(three['runtime_environment'] == env and three['runtime_environment_sha256'] == hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest(), 'old/new runtime environment differs')
    require(three['stage3_receipt'] == identity(gate_config['dll_probe_receipt']), 'three-route uses different new stage3')
    require(three.get('status') == 'diagnostic-complete' and set(three.get('results', {})) == set(diag.ORDER), 'three-route execution incomplete')
    three_inputs = [*three['inputs'], *three['copies'], three['entry'], three['dependencies_receipt'], three['stage3_receipt'], *three.get('llvm_control', {}).get('artifacts', [])]
    for result in three['results'].values():
        if result.get('partial_output', {}).get('available'):
            three_inputs.append(result['partial_output']['identity'])
        if 'log' in result:
            three_inputs.append(result['log'])
    frozen = [*three_inputs, config_record, prepared_record, three_record, *prepared['inputs'], *prepared['copies'], *inputs, *records]
    check(frozen)
    verify_copies(prepared, config, old, dependencies, gate)
    api = gate.load_windows_harness(Path(base['app_source']['path'])).Windows()
    row = diag.runtime_child(gate, api, Path(prepared['exe']), env)
    row['partial_log'] = diag.partial_log(Path(prepared['exe']).parent, gate)
    context(config)
    validate_old(prepared['old_receipt'], config, new, driver, gate)
    check(frozen)
    verify_copies(prepared, config, old, dependencies, gate)
    return {'schema':SCHEMA, 'phase':'executed', 'diagnostic_only':True, 'performance_acceptance':False,
        'release_permission':False, 'runtime_seconds':60, 'fixed_order':[*diag.ORDER, 'old6e-stage3-llvm'],
        'not_statistical_benchmark':True, 'limitations':['fixed order/cache effects remain', 'incomplete 60s metrics are censored, never assigned a completed ratio'],
        'preparation':prepared_record, 'three_route':three_record, 'old':row, 'comparison_sources':sources,
        'old_source_provenance':old['source_pins']['ru_source'], 'new_source_provenance':new['source_pins']['ru_source']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare','run'))
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--three-route', type=Path)
    args = parser.parse_args()
    try:
        config, record = read(args.config)
        if args.phase == 'prepare':
            result = prepare(config, record)
        else:
            require(args.prepared is not None and args.three_route is not None, 'run inputs required')
            result = run(config, record, args.prepared, args.three_route)
        save(args.output, result)
        return 0 if args.phase == 'prepare' or result['old'].get('passed') is True else 1
    except Exception as exc:
        if not args.output.exists():
            failure = {'schema':SCHEMA, 'phase':args.phase, 'passed':False, 'diagnostic_prerequisite_or_execution_failure':str(exc), 'performance_acceptance':False}
            if hasattr(exc, 'cmd'):
                failure['failed_command'] = list(map(str, exc.cmd))
                failure['returncode'] = exc.returncode
                for name in ('stdout','stderr'):
                    value = getattr(exc, name, None)
                    failure[name] = value.decode('utf-8','replace') if isinstance(value, bytes) else value
            save(args.output, failure)
        raise


if __name__ == '__main__':
    raise SystemExit(main())
