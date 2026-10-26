#!/usr/bin/env python3
"""Strict isolated native CI gates; never a release/GUI-performance claim."""
import argparse
import ast
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EDITOR_COMMIT = 'd964ea9f7e27065aa5bbcced8d6c7526a6224dd1'
CURRENT_EDITOR_COMMIT = '1993ac7cd9c0f8edec833dc1f261a58ccc42779f'
C_TYPES = {'无值':'void', 'i8':'int8_t', 'u8':'uint8_t', 'i16':'int16_t',
           'u16':'uint16_t', 'i32':'int32_t', 'u32':'uint32_t', 'i64':'int64_t',
           'u64':'uint64_t', 'intptr':'intptr_t', 'uintptr':'uintptr_t',
           'f32':'float', 'f64':'double', '指针':'void *'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


GATES = {'source_ir_and_abi_fixed_point', 'native_binary_fixed_point',
         'same_nonempty_suite_for_each_stage', 'every_planned_case_ran',
         'every_case_passed_without_skips', 'test_runner_success_without_skips',
         'inputs_unchanged', 'artifacts_unchanged_during_tests'}


def planned_cases():
    # Test discovery only: never parse application source in Python.
    tree = ast.parse((ROOT/'tests/test_bootstrap.py').read_text(encoding='utf-8'))
    base = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'BootstrapTests')
    names = [node.name for node in base.body if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
    names += ['test_practical_'+row['name'] for row in json.loads((ROOT/'bootstrap/validation/practical.json').read_text(encoding='utf-8'))]
    require(len(names) == len(set(names)) == 35, 'existing bootstrap suite identity changed')
    return sorted(names)


def artifact_paths(directory):
    suffix = '.exe' if sys.platform == 'win32' else ''
    binaries = [directory/('stage'+str(i)+suffix) for i in (1,2,3)]
    return binaries+[directory/('stage'+str(i)+'.ll') for i in (2,3)]+[
        Path(str(binary)+ending) for binary in binaries[1:] for ending in ('.frontend.ll','.metadata.c')]


def stage3(directory):
    from tools.bootstrap_verify import input_paths, snapshots
    report = json.loads((directory/'verification.json').read_text(encoding='utf-8'))
    require(report.get('platform') == sys.platform, 'verification platform mismatch')
    require(report.get('m4_complete') is True, 'M4 verification incomplete')
    require(report.get('tests_run') == 105, 'must execute all 105 existing bootstrap cases')
    require(report.get('skipped') == 0 and report.get('failures') == 0 and report.get('errors') == 0,
            'bootstrap failures/errors/skips cannot satisfy acceptance')
    require(set(report.get('gates', {})) == GATES and all(value is True for value in report['gates'].values()),
            'bootstrap gate missing or failed')
    planned = planned_cases()
    require(report['planned_cases_by_stage'] == {str(i):planned for i in (1,2,3)}, 'planned suite identity mismatch')
    require(set(report['stages']) == {'1','2','3'}, 'generation evidence missing')
    for index, cls in (('1','BootstrapStage1Tests'),('2','BootstrapStage2Tests'),('3','BootstrapTests')):
        records = report['stages'][index]
        require(sorted(row['case'] for row in records) == planned and
                all(row['status'] == 'passed' and row['stage'] == int(index) and
                    row['id'] == '_ru_bootstrap_acceptance.'+cls+'.'+row['case'] for row in records),
                'each generation must execute and pass the same 35 distinct cases')
    expected_artifacts = {str(path) for path in artifact_paths(directory)}
    require(set(report['artifact_sha256']) == expected_artifacts, 'complete nine-artifact bootstrap identity required')
    for name, expected in report['artifact_sha256'].items():
        require(digest(name) == expected, 'bootstrap artifact changed: '+name)
    require(report['input_sha256'] == snapshots(input_paths()), 'verified bootstrap source inventory changed or incomplete')
    return directory/('stage3.exe' if sys.platform == 'win32' else 'stage3')


REQUIRED_NATIVE_CASES = {'frontend': ['BootstrapNativeFrontendTests.test_default_denies_native_even_dormant_or_raw_alias',
              'BootstrapNativeFrontendTests.test_dynamic_structure_fields_are_runtime_values_not_abi_shapes',
              'BootstrapNativeFrontendTests.test_import_all_native_wrappers_preserve_static_signature_checks',
              'BootstrapNativeFrontendTests.test_known_ordinary_methods_are_not_native_by_name',
              'BootstrapNativeFrontendTests.test_ordinary_metadata_does_not_acquire_native_parent',
              'BootstrapNativeFrontendTests.test_production_win32_exact_shape_prototypes',
              'BootstrapNativeFrontendTests.test_structure_cannot_masquerade_as_primitive_abi',
              'BootstrapNativeFrontendTests.test_unknown_mutable_rebound_and_shadowed_signatures_fail_closed',
              'BootstrapNativeFrontendTests.test_user_function_named_signature_is_not_a_builtin'],
 'windows': ['BootstrapNativeWindowsAcceptanceTests.test_native_callback_continue_preserves_frame_and_outer_loop',
             'BootstrapNativeWindowsAcceptanceTests.test_continue_cannot_cross_native_callback_boundary',
             'BootstrapNativeRequiredGate.test_production_fixture_inventory_matches_static_oracle',
             'BootstrapNativeRequiredGate.test_required_native_execution_cannot_be_satisfied_by_skips',
             'BootstrapNativeWindowsAcceptanceTests.test_active_closed_callback_reentry_uses_saved_fallback',
             'BootstrapNativeWindowsAcceptanceTests.test_closed_callback_tombstone_returns_fallback_without_ru',
             'BootstrapNativeWindowsAcceptanceTests.test_dynamic_64_field_structure_layout_and_lifetime',
             'BootstrapNativeWindowsAcceptanceTests.test_dynamic_unknown_signature_is_rejected_before_output_replace',
             'BootstrapNativeWindowsAcceptanceTests.test_exact_integer_pointer_bounds_and_struct_layout',
             'BootstrapNativeWindowsAcceptanceTests.test_failure_hook_recursion_preserves_first_error',
             'BootstrapNativeWindowsAcceptanceTests.test_first_callback_module_initialization_is_contained_and_retryable',
             'BootstrapNativeWindowsAcceptanceTests.test_foreign_thread_rejects_ru_body_and_failure_hook',
             'BootstrapNativeWindowsAcceptanceTests.test_last_error_snapshot_survives_nested_native_call',
             'BootstrapNativeWindowsAcceptanceTests.test_mixed_gp_xmm_and_stack_arguments_in_both_directions',
             'BootstrapNativeWindowsAcceptanceTests.test_nested_synchronous_callback_and_native_return_after_error',
             'BootstrapNativeWindowsAcceptanceTests.test_numeric_and_owner_errors_exit_before_entering_native_code',
             'BootstrapNativeWindowsAcceptanceTests.test_owned_pointer_return_and_copied_nested_view_survive_forced_gc',
             'BootstrapNativeWindowsAcceptanceTests.test_production_win32_declarations_and_nested_window_callback',
             'BootstrapNativeWindowsAcceptanceTests.test_runtime_error_uses_fallback_and_allows_later_native_call']}


def suite_cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from suite_cases(item)
        else:
            yield item.id().split('.', 1)[1]


def require_native_cases(cases, kind):
    require(len(cases) == len(set(cases)) and set(REQUIRED_NATIVE_CASES[kind]).issubset(cases),
            'required '+kind+' acceptance cases missing or duplicated')


def tests(directory, kind):
    compiler = stage3(directory)
    if kind == 'windows':
        require(sys.platform == 'win32', 'real Windows execution is required')
        os.environ['RU_BOOTSTRAP_NATIVE_REQUIRED'] = '1'
        os.environ['RU_BOOTSTRAP_NATIVE_COMPILER'] = str(compiler)
        filename = 'test_bootstrap_native_contract.py'
    else:
        os.environ['RU_BOOTSTRAP_FRONTEND_TEST_COMPILER'] = str(compiler)
        filename = 'test_bootstrap_native_frontend.py'
    name = '_native_ci_'+kind
    spec = importlib.util.spec_from_file_location(name, ROOT/'tests'/filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    run_native_suite(suite, directory, kind, compiler)
    require(stage3(directory) == compiler, 'verified stage3 identity changed')


class IdentityResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executed_ids = []

    def startTest(self, test):
        self.executed_ids.append(test.id().split('.', 1)[1])
        super().startTest(test)


def run_native_suite(suite, directory, kind, compiler):
    planned = list(suite_cases(suite))
    require_native_cases(planned, kind)
    result = unittest.TextTestRunner(verbosity=2, resultclass=IdentityResult).run(suite)
    report = {'scope':'real-stage3-'+kind, 'compiler':str(compiler), 'compiler_sha256':digest(compiler),
              'planned':len(planned), 'executed':result.testsRun,
              'planned_ids':planned, 'executed_ids':result.executed_ids,
              'skipped':len(result.skipped), 'failures':len(result.failures), 'errors':len(result.errors),
              'expected_failures':len(result.expectedFailures),
              'unexpected_successes':len(result.unexpectedSuccesses),
              'complete': bool(planned and result.testsRun == len(planned) and
                  result.executed_ids == planned and result.wasSuccessful() and
                  not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses)}
    (directory/('native-'+kind+'-tests.json')).write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    require(report['complete'], kind+' suite failed, skipped, expected-failed, or did not execute exact planned cases')
    return report


def editor_identity(editor_root, expected_commit=EDITOR_COMMIT):
    head = subprocess.check_output(['git','-C',str(editor_root),'rev-parse','HEAD'], text=True).strip()
    require(head == expected_commit, 'editor must be exactly '+expected_commit)
    dirty = subprocess.check_output(['git','-C',str(editor_root),'status','--porcelain'], text=True)
    require(not dirty, 'tracked editor source must be unmodified')
    entries = subprocess.check_output(['git','-C',str(editor_root),'ls-files','-s','-z'], text=True).split('\0')
    for entry in entries:
        if not entry:
            continue
        info, name = entry.split('\t', 1)
        if name.endswith('.ru'):
            data = (editor_root/name).read_bytes()
            blob = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            require(blob == info.split()[1], 'editor .ru worktree bytes differ from pinned Git blob: '+name)

    return head


def require_current_graph(matrix, editor_root, dependencies):
    expected_dependencies = {}
    for row in matrix['modules']:
        require(row['scope'] in ('app', 'compiler'), 'invalid editor oracle scope')
        path = ((editor_root if row['scope'] == 'app' else ROOT)/row['path']).resolve()
        require(digest(path) == row['sha256'], 'editor oracle source bytes changed: '+str(path))
        require(str(path) not in expected_dependencies, 'duplicate editor oracle dependency')
        expected_dependencies[str(path)] = row['sha256']
    require(len(expected_dependencies) == 26 and len(dependencies) == 26 and
            {row['path']:row['sha256'] for row in dependencies} == expected_dependencies,
            'current editor exact dependency graph differs from independent oracle')


def editor(directory, editor_root, current=False):
    require(sys.platform == 'win32', 'editor native LLVM link requires Windows x64')
    compiler = stage3(directory)
    head = editor_identity(editor_root, CURRENT_EDITOR_COMMIT if current else EDITOR_COMMIT)
    output = directory/('notepad-current-console-link' if current else 'notepad-console-link')
    output.mkdir(exist_ok=True)
    executable, ir, proof = output/'ru_notepad-console.exe', output/'application.ll', output/'compile-proof.json'
    from tools.bootstrap import compile_native
    from rulang.llvm_toolchain import LLVMToolchain
    forbidden = ('rulang.frontend.parse', 'rulang.modules.load_module_graph',
                 'rulang.native_c.NativeCPlan.__init__', 'rulang.native_c.NativeCPlan.emit_c',
                 'rulang.compiler.Compiler.compile', 'rulang.llvm_compiler.LLVMCompiler.compile', 'rulang.cli.build')
    with ExitStack() as guards:
        for name in forbidden:
            guards.enter_context(patch(name, side_effect=AssertionError('Python application frontend fallback: '+name)))
        build = compile_native(compiler, editor_root/'src/main.ru', executable, LLVMToolchain(),
                               emit_llvm=ir, keep_frontend=True, allow_native=True,
                               proof=proof, source_roots=(editor_root/'src',))
    require(build['compiler']['sha256'] == digest(compiler), 'editor was not built by verified stage3')
    require(executable.read_bytes()[:2] == b'MZ', 'editor output must be a native PE')
    require(build['binary_sha256'] == digest(executable), 'editor PE identity mismatch')
    require(build['standalone_ir_sha256'] == digest(ir), 'editor linked LLVM identity mismatch')
    matrix = json.loads((ROOT/'tests/fixtures/native'/('notepad_1993_contract.json' if current else 'notepad_d964_contract.json')).read_text(encoding='utf-8'))
    require(matrix['application_commit' if current else 'source_commit'] == head, 'ABI oracle has wrong source identity')
    module_count = 26 if current else 24
    if current:
        require_current_graph(matrix, editor_root, build['dependencies'])
    metadata_path = executable.with_name(executable.name+'.metadata.c')
    require(digest(metadata_path) == build['metadata_sha256'], 'editor metadata identity mismatch')
    metadata = metadata_path.read_text(encoding='utf-8')
    found = re.findall(r'typedef (.+) \(\*RuNativeCall_(\d+)\)\(([^\n]*)\);', metadata)
    actual = {(result,params) for result,index,params in found}
    expected = {(C_TYPES[row['result']], ', '.join(C_TYPES[value] for value in row['parameters']) or 'void')
                for row in matrix['shapes']}
    require(actual == expected and len(actual) == 62, 'complete editor ABI shape mismatch')
    callbacks = set(re.findall(r'static RuNativeCall_(\d+) const ru_native_callbacks_', metadata))
    callback_shapes = {(result,params) for result,index,params in found if index in callbacks}
    expected_callbacks = {(C_TYPES[row['result']], ', '.join(C_TYPES[value] for value in row['parameters']) or 'void')
                          for row in (matrix['callbacks'] if current else [row for row in matrix['shapes'] if row['callback']])}
    require(callback_shapes == expected_callbacks and len(callback_shapes) == 2, 'editor callback ABI mismatch')
    require(len(build['dependencies']) == module_count and (current or matrix['entry_module_count'] == module_count), 'editor module graph incomplete')
    tracked_editor = subprocess.check_output(['git','-C',str(editor_root),'ls-files','-z'], text=True).split('\0')
    tracked_stdlib = subprocess.check_output(['git','-C',str(ROOT),'ls-files','-z','rulang/stdlib'], text=True).split('\0')
    allowed = {(editor_root/name).resolve() for name in tracked_editor if name}
    allowed.update((ROOT/name).resolve() for name in tracked_stdlib if name)
    require(all(Path(row['path']).resolve() in allowed for row in build['dependencies']),
            'editor dependency outside exact tracked editor/verified language stdlib')
    require(metadata.count('ru_native_builtins(ru_practical_builtins())') == module_count, 'native module parent missing')
    bodies = re.findall(r'static Val boot_m_\d+_init\(void\) \{(.*?\nboot_m_\d+_state=2;[^\n]*)', metadata, re.S)
    require(len(bodies) == module_count and all('ru_native_callback_depth' in body and
            body.index('ru_native_callback_depth') < body.index('_state=1;') for body in bodies),
            'callback first-import protection missing or incorrectly ordered')
    require(stage3(directory) == compiler, 'stage3 changed while compiling editor')
    require(editor_identity(editor_root, head) == head, 'editor Git identity changed during compilation')
    report = {'scope':'stage3-LLVM-console-link-only; NOT GUI/resources/DLL packaging/performance acceptance',
              'editor_commit':head, 'compiler_sha256':digest(compiler), 'binary_sha256':digest(executable),
              'llvm_sha256':digest(ir), 'metadata_sha256':digest(metadata_path), 'compile_proof_sha256':digest(proof),
              'modules':module_count, 'shapes':62, 'callbacks':2,
              'application_python_frontend_forbidden':True, 'complete':True}
    (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('report','frontend','windows','editor','editor-current'))
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--editor-root', type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.mode == 'report':
        print('Verified complete 105-case three-generation fixed point:', stage3(directory))
    elif args.mode in ('editor', 'editor-current'):
        require(args.editor_root is not None, '--editor-root is required')
        editor(directory, args.editor_root.resolve(), current=args.mode == 'editor-current')
    else:
        tests(directory, args.mode)


if __name__ == '__main__':
    main()
