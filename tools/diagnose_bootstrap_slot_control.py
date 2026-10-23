#!/usr/bin/env python3
"""Same-runner old6e stage3 control. Diagnostic only, never release/performance acceptance."""
import argparse
import hashlib
import importlib
import json
import math
import os
import stat
from pathlib import Path
import sys
import time

OLD = '6e03236c4fecf5a5219eb28a3ba1c46bfeb36d65'
TREE = 'd7f53f270006729fc8761e3328d1bf8110c99b97'
APP = '2cb3b8c81ba300745b244c51b50d5625430fbe4f'
APP_TREE = '5c63f94cd9e3816608cc95b834f91428bbeb3c49'
ENTRY = 'tests/bootstrap_pipeline/dll_abi_probe.ru'
SCHEMA = 'ru-slot-old-stage3-control-v1'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(path, *, max_bytes=None):
    path = Path(path)
    require(path.is_absolute() and path.is_file() and not any(p.is_symlink() for p in (path, *path.parents)), 'unsafe control input')
    require(not any(getattr(p.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT for p in (path, *path.parents)), 'reparse control input')
    if max_bytes is None:
        raw = path.read_bytes()
    else:
        with path.open('rb') as stream:
            raw = stream.read(max_bytes+1)
        require(len(raw) <= max_bytes, 'control input exceeds bound')
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
    validate_progress_graph(sources)
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
    observation = classify_observation(row, Path(prepared['exe']).parent, diag)
    new_routes_passed = all(result.get('passed') is True for result in three['results'].values())
    return {'schema':SCHEMA, 'phase':'executed', 'diagnostic_only':True, 'performance_acceptance':False,
        'old_observation':observation, 'new_routes_passed':new_routes_passed,
        'diagnostic_integrity_passed':new_routes_passed and observation['evidence_complete'] is True,
        'release_permission':False, 'runtime_seconds':60, 'fixed_order':[*diag.ORDER, 'old6e-stage3-llvm'],
        'not_statistical_benchmark':True, 'limitations':['fixed order/cache effects remain', 'incomplete 60s metrics are censored, never assigned a completed ratio'],
        'preparation':prepared_record, 'three_route':three_record, 'old':row, 'comparison_sources':sources,
        'old_source_provenance':old['source_pins']['ru_source'], 'new_source_provenance':new['source_pins']['ru_source']}


# Frozen233 complete149-assertion oracle: successful C-to-LLVM and stage3
# transcripts agree after only the explicitly listed timing fields are masked.
PROGRESS_GRAPH_SHA256 = '9d9d898ca7efd0e1ada3616cff234df7f6063fa6970d658b7d4b8d9cc2ae6ca7'
FULL_PROGRESS_LINES = ('Ru Notepad diagnostic log',
 '[launcher] Starting Ru program.',
 'PASS: production bulk decoder matches all six old-decoder fields across a full 64-event batch',
 'PASS: production bulk decoder checks high bits in the last event of a full batch',
 'PASS: production bulk decoder preserves exact near-32-MB event coordinates and unsigned metadata',
 'PASS: production bulk decoder rejects high-bit corruption 0 before combining words',
 'PASS: production bulk decoder rejects high-bit corruption 1 before combining words',
 'PASS: production bulk decoder rejects high-bit corruption 2 before combining words',
 'PASS: production bulk decoder ignores stale event bytes when the native count is zero',
 'PASS: production bulk decoder rejects a count exceeding its 1024-byte event capacity',
 'PASS: production bulk decoder rejects a negative count',
 'PASS: production bulk decoder rejects a fractional count',
 'PASS: production bulk decoder rejects malformed kind/style/length/position/line 0',
 'PASS: production bulk decoder rejects malformed kind/style/length/position/line 1',
 'PASS: production bulk decoder rejects malformed kind/style/length/position/line 2',
 'PASS: production bulk decoder rejects malformed kind/style/length/position/line 3',
 'PASS: production bulk decoder rejects malformed kind/style/length/position/line 4',
 'PASS: production bulk decoder rejects malformed kind/style/length/position/line 5',
 'PASS: production bulk decoder rejects malformed kind/style/length/position/line 6',
 'PASS: production bulk decoder rejects malformed kind/style/length/position/line 7',
 'PASS: production bulk decoder rejects a non-token before the styled range',
 'PASS: production bulk decoder preserves long identifier events starting before the styled range',
 'PASS: production bulk decoder preserves the 64-byte delayed keyword boundary',
 'PASS: production bulk decoder rejects decreasing event positions',
 'PASS: production bulk decoder preserves equal-position event ordering',
 'PASS: decoded event rows remain detached after source mutation and closure',
 'PASS: checked low49 decoding preserves event coordinates near the 32 MB boundary',
 'PASS: corrupt high event bits fail ordinarily before any lossy native conversion',
 'PASS: initial checkpoint failure releases the already-created native context exactly once',
 'PASS: failed initialization returns no released context or checkpoint to the plain fallback',
 'PASS: initial checkpoint failure keeps its specific visible warning outside rescue scope',
 'PASS: Ru attaches independently of Lexilla availability',
 'PASS: Ru uses real SCLEX_CONTAINER instead of borrowed lexer',
 'PASS: selection never performs eager lexical scanning',
 'PASS: real SCN_STYLENEEDED reaches the owning container bridge',
 'PASS: style-needed notification queues without synchronous rescanning',
 'PASS: container queue drains without fallback',
 'PASS: every UTF-8 byte of 算 is a keyword',
 'PASS: Han function name retains identifier style',
 'PASS: every Han and emoji byte in quoted string is styled',
 'PASS: number following multibyte source has correct byte offset',
 'PASS: function header has base fold level and header flag',
 'PASS: if header nests exactly once',
 'PASS: function and if body has depth two',
 'PASS: 法 closes matching function level',
 'PASS: styling and folding preserve exact UTF-8 text',
 'PASS: styling and folding never dirty a clean document',
 'PASS: styling and folding create no undo entry',
 'PASS: styling preserves selection anchor and caret',
 'PASS: Ru palette preserves line-number style',
 'PASS: dedicated fold margin is visible',
 'PASS: fold action accepts completed owning document',
 'PASS: collapse actually hides nested native lines',
 'PASS: collapse changes native expanded flag',
 'PASS: expand restores native line visibility',
 'PASS: plain switch reveals every previously hidden line',
 'PASS: plain switch clears old fold levels',
 'PASS: plain switch clears all Ru style bytes',
 'PASS: plain switch cancels scanner state',
 'PASS: C++ switch reveals every Ru fold even without Lexilla',
 'PASS: JSON switch reveals every Ru fold even without Lexilla',
 'PASS: first typing into empty Ru document restarts a nonterminal checkpoint',
 'PASS: EOF append never restores a finished scanner',
 'PASS: EOF undo and redo remain incrementally highlighted',
 'PASS: multiline quote initially styles Han bytes',
 'PASS: deleting opening quote invalidates multiline lexical state',
 'PASS: undo restores multiline quote state',
 'PASS: Ru block comment spans Han and emoji bytes',
 'PASS: Ru keyword resumes after the real 释. block-comment terminator',
 'PASS: same-length comment opener replacement invalidates lexical suffix',
 'PASS: undo restores Ru multiline comment state',
 'PASS: real native insert/delete notifications reached owning bridge',
 'PASS: style and fold notifications are observed without recursive text invalidation',
 'PASS: UTF-8 quote and emoji styles cross checkpoint boundary correctly',
 'PASS: deleting LF from checkpoint-adjacent CRLF safely resumes lexical state',
 'PASS: keyword offset adjusts correctly after CRLF partial deletion',
 'PASS: bounded timer returns before a large initial scan completes',
 'PASS: edit during incomplete work invalidates suffix without unsafe reuse',
 'PASS: unclosed BOF comment propagates through previously pending source',
 'PASS: removing existing collapsed function headers with BOF comment reveals every old hidden line',
 'PASS: tentative reference-call opener starts without a fold header',
 'PASS: temporary statement confirms an opener before the restart checkpoint',
 'PASS: checkpoint restore retracts a previously published earlier header and reveals its lines',
 'PASS: BOF insertion unequal edit queues its own revision and preserves exact dirty text',
 'PASS: BOF insertion incremental text/styles/all fold levels equal an independent fresh scan',
 'PASS: BOF insertion highlighting preserves one-edit undo and the original savepoint',
 'PASS: BOF deletion unequal edit queues its own revision and preserves exact dirty text',
 'PASS: BOF deletion incremental text/styles/all fold levels equal an independent fresh scan',
 'PASS: BOF deletion highlighting preserves one-edit undo and the original savepoint',
 'PASS: middle insertion unequal edit queues its own revision and preserves exact dirty text',
 'PASS: middle insertion incremental text/styles/all fold levels equal an independent fresh scan',
 'PASS: middle insertion highlighting preserves one-edit undo and the original savepoint',
 'PASS: middle deletion unequal edit queues its own revision and preserves exact dirty text',
 'PASS: middle deletion incremental text/styles/all fold levels equal an independent fresh scan',
 'PASS: middle deletion highlighting preserves one-edit undo and the original savepoint',
 'PASS: EOF insertion unequal edit queues its own revision and preserves exact dirty text',
 'PASS: EOF insertion incremental text/styles/all fold levels equal an independent fresh scan',
 'PASS: EOF insertion highlighting preserves one-edit undo and the original savepoint',
 'PASS: EOF deletion unequal edit queues its own revision and preserves exact dirty text',
 'PASS: EOF deletion incremental text/styles/all fold levels equal an independent fresh scan',
 'PASS: EOF deletion highlighting preserves one-edit undo and the original savepoint',
 'PASS: matrix multiline edit has published a bounded prefix while work remains pending',
 'PASS: repeated edits during pending work discard old states and match every fresh byte style and fold level',
 'PASS: edit in later function preserves unaffected collapsed earlier fold',
 'PASS: editing one HWND preserves another document byte styles',
 'PASS: editing one HWND never invalidates another document generation',
 'PASS: SETDOCPOINTER rejects queued stale document state',
 'PASS: replacement document obtains a fresh generation',
 'PASS: explicit release removes lifecycle state',
 'PASS: large Ru selection only queues work',
 'PASS: large Ru initial scan completes',
 'PASS: initial scan reads source exactly once in bounded chunks',
 'PASS: no native range exceeds 1024 UTF-8 bytes',
 'PASS: same-byte edit proves full-state checkpoint convergence',
 'PASS: ordinary edit does not rescan the full document',
 'PASS: performance edit preserves document length',
 'PASS: same-byte replacement retains Ru identifier byte style',
 'PASS: background styling preserves edited dirty state',
 'PASS: single undo after background scan reaches original savepoint',
 'PERF_RU size=100000 initial_ms=<timing> edit_ms=<timing> initial_read_bytes=100000 edit_read_bytes=32768 '
 'reused_bytes=67232 max_read=1024 max_tick_ms=<timing> max_chunk_ms=<timing>',
 'PASS: two distant coalesced replacements converge only after both changed ranges',
 'PASS: both coalesced replacements receive correct byte styles',
 'PASS: two edits retain their original undo history through convergence',
 'PASS: insertion and deletion at different positions can safely converge',
 'PASS: net-zero shifted replacement has correct combined identifier style',
 'PASS: net-zero edit revisits styles published beyond an intermediate checkpoint',
 'PASS: large Ru selection only queues work',
 'PASS: large Ru initial scan completes',
 'PASS: initial scan reads source exactly once in bounded chunks',
 'PASS: no native range exceeds 1024 UTF-8 bytes',
 'PASS: same-byte edit proves full-state checkpoint convergence',
 'PASS: ordinary edit does not rescan the full document',
 'PASS: performance edit preserves document length',
 'PASS: same-byte replacement retains Ru identifier byte style',
 'PASS: background styling preserves edited dirty state',
 'PASS: single undo after background scan reaches original savepoint',
 'PERF_RU size=1000000 initial_ms=<timing> edit_ms=<timing> initial_read_bytes=1000000 edit_read_bytes=32768 '
 'reused_bytes=967232 max_read=1024 max_tick_ms=<timing> max_chunk_ms=<timing>',
 'PASS: GUI-equivalent synchronous corpus has the exact Unicode character and byte counts',
 'PASS: core synchronous fixture retains Scintilla default all-modification notifications',
 'PASS: GUI-equivalent synchronous selection queues work without draining it',
 'RU_GUI_SYNC size=1000000 source_chars=636370 wall_ms=<timing> read_bytes=1000000 max_read=1023 max_tick_ms=<timing> '
 'max_chunk_ms=<timing> chunks=8798',
 'PASS: GUI-equivalent synchronous scan finishes with exact bounded reads',
 'PASS: GUI-equivalent synchronous scan matches all sixteen head and tail style bytes',
 'PASS: GUI-equivalent synchronous styling preserves exact source, line count, savepoint and empty undo',
 'PASS: STYLES_NONE document suppresses Ru even when currently empty',
 'PASS: large-document mode schedules no scanning',
 'PASS: large-document styles storage remains disabled',
 'PASS: unexpected structural complexity reports plain fallback',
 'PASS: complexity fallback preserves exact clean source',
 'PASS: complexity fallback leaves all lines visible',
 'PASS: complexity fallback clears partial style bytes',
 'PASS: destroyed HWND cannot resume a stale queue',
 'PASS: surviving editor remains independently styled after sibling destroy',
 'PASS: all current and shared checkpoint roots explicitly close and release at final teardown',
 'TOTAL PASS: 149',
 'BOOTSTRAP_DLL_ABI_PASS:ru',
 '[launcher] Ru program returned with status 0.')
TIMING_FIELDS = {'PERF_RU': {'max_tick_ms', 'initial_ms', 'edit_ms', 'max_chunk_ms'}, 'RU_GUI_SYNC': {'max_tick_ms', 'wall_ms', 'max_chunk_ms'}}
METRIC_FIELDS = {
    'PERF_RU': {'max_read', 'max_chunk_ms', 'reused_bytes', 'size', 'edit_read_bytes', 'max_tick_ms', 'edit_ms', 'initial_read_bytes', 'initial_ms'},
    'RU_GUI_SYNC': {'max_read', 'source_chars', 'chunks', 'size', 'max_tick_ms', 'max_chunk_ms', 'read_bytes', 'wall_ms'},
}

def validate_progress_graph(sources):
    digest = hashlib.sha256(json.dumps(sources, sort_keys=True, separators=(',',':')).encode()).hexdigest()
    require(digest == PROGRESS_GRAPH_SHA256, 'progress oracle source graph differs')


def finite_time(value):
    return type(value) in (int,float) and math.isfinite(value) and value >= 0


def classify_observation(row, directory, diagnostic):
    """Classify evidence, never rewrite the old program's passed/error fields."""
    def invalid(reason):
        return {'outcome':'invalid','evidence_complete':False,'reason':reason}
    try:
        require(isinstance(row,dict), 'old observation is not an object')
        require(row.get('executed') is True and type(row.get('pid')) is int and row['pid'] > 0, 'owned process identity missing')
        observation = row.get('observation')
        require(isinstance(observation,dict) and set(observation) == {'schema','clock','deadline_events','first_error','nondeadline_errors','cleanup'} and observation['schema'] == 'ru-notepad-child-observation-v2', 'structured observation missing')
        require(observation['nondeadline_errors'] == [], 'nondeadline runtime errors present or unknown')
        clock = observation['clock']
        require(isinstance(clock,dict) and set(clock) == {'started_monotonic','deadline_monotonic','finished_monotonic','budget_seconds'}, 'absolute clock evidence missing')
        require(type(clock['budget_seconds']) is int and clock['budget_seconds'] == 60, 'absolute clock budget differs')
        started, deadline, finished = [clock[key] for key in ('started_monotonic','deadline_monotonic','finished_monotonic')]
        require(all(finite_time(value) for value in (started,deadline,finished)) and deadline == started+60 and deadline > started and finished >= started, 'absolute clock identity invalid')
        require(finite_time(row.get('seconds')) and row['seconds'] == finished-started, 'elapsed result differs from absolute clock')
        def observed(record):
            now = record.get('observed_monotonic')
            require(finite_time(now) and deadline <= now <= finished and record.get('elapsed_seconds') == now-started, 'deadline not reached or elapsed evidence differs')
            return now
        cleanup = observation['cleanup']
        require(isinstance(cleanup,dict) and set(cleanup) == {'pid','errors','process_reaped','exit_code','windows_remaining','handshake_closed','watchdog_stopped'}, 'cleanup schema missing')
        require(cleanup['pid'] == row['pid'] and type(cleanup['pid']) is int and cleanup['errors'] == [] and
                cleanup['process_reaped'] is True and type(cleanup['exit_code']) is int and
                cleanup['windows_remaining'] == [] and cleanup['handshake_closed'] is True and
                cleanup['watchdog_stopped'] is True, 'owned process cleanup incomplete')
        if 'exit_code' in row:
            require(row['exit_code'] == cleanup['exit_code'] and type(row['exit_code']) is int, 'exit evidence differs')
        events = observation['deadline_events']
        require(isinstance(events,list), 'deadline event list missing')
        if row.get('passed') is True:
            require(row.get('cleanup_killed') is False and not row.get('error') and cleanup['exit_code'] == 0 and
                    observation['first_error'] is None and events == [] and finished <= deadline, 'completed observation contradicts success')
            return {'outcome':'passed','evidence_complete':True,'program_passed':True}
        require(row.get('passed') is False and row.get('cleanup_killed') is True and cleanup['exit_code'] != 0, 'not an owned terminated old observation')
        require(deadline <= finished <= deadline+5, 'not the bounded absolute 60s observation')
        first = observation['first_error']
        require(isinstance(first,dict) and set(first) == {'code','phase','observed_monotonic','elapsed_seconds','exception_type','message'} and first['code'] == 'deadline' and first['exception_type'] == 'FunctionalDeadlineError' and first['phase'] in ('runtime','acceptance'), 'first error is not a structured deadline')
        observed(first)
        require(all(isinstance(first[name],str) and bool(first[name]) for name in ('phase','exception_type','message')), 'invalid first deadline event')
        require(1 <= len(events) <= 3, 'deadline event count invalid')
        sources = []
        for event in events:
            require(isinstance(event,dict) and set(event) == {'source','budget_seconds','observed_monotonic','elapsed_seconds'}, 'deadline event schema invalid')
            require(event['source'] in ('watchdog','poll-loop','elapsed-postcheck') and type(event['budget_seconds']) is int and
                    event['budget_seconds'] == 60, 'deadline event identity invalid')
            observed(event)
            sources.append(event['source'])
        require(len(sources) == len(set(sources)) and any(event['source'] in ('watchdog','poll-loop') and event['observed_monotonic'] <= first['observed_monotonic'] for event in events), 'no causal owned deadline event before first error')
        modules = row.get('diagnostic_module_observations',{})
        require(modules.get('pid') == row['pid'] and modules.get('complete') is True and type(modules.get('snapshots')) is int and modules['snapshots'] > 0, 'actual old DLL observation incomplete')
        names = ('Scintilla.dll','Lexilla.dll','RuSyntax.dll')
        require(set(modules.get('verified',{})) == set(names), 'actual old DLL set differs')
        directory = Path(directory).resolve()
        for name in names:
            require(modules['verified'][name] == identity(directory/name), 'actual old DLL identity differs')
        partial = row.get('partial_log',{})
        require(partial.get('available') is True, 'old partial log unavailable')
        logs = list(directory.glob('ru_notepad-*.log'))
        require(len(logs) == 1 and partial['identity'] == identity(logs[0], max_bytes=1024*1024), 'old partial log path/identity differs')
        with logs[0].open('rb') as stream:
            raw = stream.read(1024*1024+1)
        require(hashlib.sha256(raw).hexdigest() == partial['identity']['sha256'] and len(raw) == partial['identity']['size'] and len(raw) <= 1024*1024, 'old partial log changed or oversized')
        text = raw.decode('utf-8').replace('\r\n','\n')
        require('\r' not in text and text.endswith('\n'), 'old partial log framing invalid')
        normalized = []; metrics = []
        for line in text[:-1].split('\n'):
            if line.startswith(('PERF_RU ','RU_GUI_SYNC ')):
                metric = diagnostic.metric(line); metrics.append(metric)
                require(metric['kind'] in TIMING_FIELDS and set(metric['fields']) == METRIC_FIELDS[metric['kind']], 'unexpected progress metric schema')
                timing = TIMING_FIELDS[metric['kind']]
                require(all(math.isfinite(float(metric['fields'][name])) and 0 <= float(metric['fields'][name]) <= 60000 for name in timing), 'timing exceeds fixed observation budget')
                parts = line.split()
                line = ' '.join(parts[:1]+[item.split('=')[0]+'=<timing>' if item.split('=')[0] in timing else item for item in parts[1:]])
            normalized.append(line)
        require(metrics == partial.get('metrics'), 'old partial metrics missing/changed')
        require(0 < len(normalized) < len(FULL_PROGRESS_LINES) and tuple(normalized) == FULL_PROGRESS_LINES[:len(normalized)], 'partial log is not a strict prefix of the frozen complete fixture oracle')
        require(identity(logs[0], max_bytes=1024*1024) == partial['identity'], 'old partial log changed after validation')
        return {'outcome':'valid_censored','evidence_complete':True,'program_passed':False,
                'deadline_seconds':60,
                'completed_metrics':[metric['kind']+':'+metric['fields']['size'] for metric in metrics],
                'missing_metrics':[name for name in ('PERF_RU:100000','PERF_RU:1000000','RU_GUI_SYNC:1000000') if name not in {metric['kind']+':'+metric['fields']['size'] for metric in metrics}]+['whole-fixture completion'],
                'log_identity':partial['identity'],'normalized_prefix_sha256':hashlib.sha256(('\n'.join(normalized)+'\n').encode()).hexdigest(), 'complete_oracle_sha256':hashlib.sha256(('\n'.join(FULL_PROGRESS_LINES)+'\n').encode()).hexdigest(), 'not_proof_of_progress_or_no_hang':True}
    except (ValueError,KeyError,TypeError,OverflowError,OSError) as exc:
        return invalid(str(exc))


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
        return 0 if args.phase == 'prepare' or result.get('diagnostic_integrity_passed') is True else 1
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
