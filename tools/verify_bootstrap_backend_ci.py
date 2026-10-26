#!/usr/bin/env python3
"""Required main-profile backend optimization acceptance; not bootstrap native FFI.

Preserves the existing main host/runtime and M4 report format. All application
processing on the stage3 lifecycle route is pure Ru. The Windows DLL gate is
explicitly Python LLVM with the pre-existing scalar-manifest native opt-in.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest
import uuid
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tests'))
MODULES = {'runtime':'test_bootstrap_slot_reuse', 'windows':'test_bootstrap_backend_native'}
REQUIRED = {'runtime': ['BootstrapSlotStructureTests.test_normalized_ir_and_runtime_preserve_operations', 'BootstrapSlotStructureTests.test_reuse_and_success_edge_differ_from_unsafe_unwind_rule', 'BootstrapSlotStructureTests.test_ssa_unique_physical_bounds_and_highwater', 'BootstrapSlotReuseTests.test_python_01_panic_check_success_keeps_outer_arguments', 'BootstrapSlotReuseTests.test_python_02_prepared_receiver_survives_argument_and_reentry', 'BootstrapSlotReuseTests.test_python_03_named_pack_contiguity_and_source_order', 'BootstrapSlotReuseTests.test_python_04_return_array_copy_before_frame_cleanup', 'BootstrapSlotReuseTests.test_python_05_panic_suppresses_remaining_args_then_resumes', 'BootstrapSlotReuseTests.test_python_06_nested_rescue_return_and_break', 'BootstrapSlotReuseTests.test_python_07_counted_nested_loops_branches_scalar_liveness', 'BootstrapSlotReuseTests.test_python_08_closures_env_escape_recursion_and_self', 'BootstrapSlotReuseTests.test_python_09_scope_rescue_closure_escapes', 'BootstrapSlotReuseTests.test_python_10_runtime_reentrant_callbacks_map_cycles', 'BootstrapSlotReuseTests.test_python_11_short_circuit_map_nested_values_and_assignment', 'BootstrapSlotReuseTests.test_python_12_early_finish_unreachable_branch_and_zero_arg_pack', 'BootstrapSlotReuseTests.test_python_13_return_break_other_branch_remains_correct', 'BootstrapSlotReuseTests.test_python_unsafe_unwind_reset_is_rejected', 'BootstrapSlotReuseTests.test_stage3_01_panic_check_success_keeps_outer_arguments', 'BootstrapSlotReuseTests.test_stage3_02_prepared_receiver_survives_argument_and_reentry', 'BootstrapSlotReuseTests.test_stage3_03_named_pack_contiguity_and_source_order', 'BootstrapSlotReuseTests.test_stage3_04_return_array_copy_before_frame_cleanup', 'BootstrapSlotReuseTests.test_stage3_05_panic_suppresses_remaining_args_then_resumes', 'BootstrapSlotReuseTests.test_stage3_06_nested_rescue_return_and_break', 'BootstrapSlotReuseTests.test_stage3_07_counted_nested_loops_branches_scalar_liveness', 'BootstrapSlotReuseTests.test_stage3_08_closures_env_escape_recursion_and_self', 'BootstrapSlotReuseTests.test_stage3_09_scope_rescue_closure_escapes', 'BootstrapSlotReuseTests.test_stage3_10_runtime_reentrant_callbacks_map_cycles', 'BootstrapSlotReuseTests.test_stage3_11_short_circuit_map_nested_values_and_assignment', 'BootstrapSlotReuseTests.test_stage3_12_early_finish_unreachable_branch_and_zero_arg_pack', 'BootstrapSlotReuseTests.test_stage3_13_return_break_other_branch_remains_correct', 'BootstrapSlotReuseTests.test_stage3_unsafe_unwind_reset_is_rejected'], 'windows': ['BackendNativeCallbackTests.test_parent_temporaries_survive_nested_callback_panic_retry']}

def require(condition, message):
    if not condition: raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_report(path):
    raw = Path(path).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def checkout_identity():
    expected = os.environ.get('GITHUB_SHA', '')
    require(re.fullmatch(r'[0-9a-f]{40}', expected), 'exact CI commit required')
    actual = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,encoding='utf-8').strip()
    require(actual == expected, 'checkout differs from exact CI commit')
    require(subprocess.run(['git','diff','--quiet','HEAD','--'],cwd=ROOT).returncode == 0, 'tracked checkout bytes changed')
    tree = subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=ROOT,text=True,encoding='utf-8').strip()
    return {'commit':actual, 'tree':tree}


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

GATES = {'native_binary_fixed_point', 'test_runner_success_without_skips', 'inputs_unchanged', 'source_ir_and_abi_fixed_point', 'every_planned_case_ran', 'artifacts_unchanged_during_tests', 'same_nonempty_suite_for_each_stage', 'every_case_passed_without_skips'}

def bootstrap_snapshot(directory):
    from tools.bootstrap_verify import input_paths, snapshots
    report, report_hash = read_report(directory/'verification.json')
    require(report.get('format') == 1 and report.get('milestone') == 'M4', 'M4 report schema mismatch')
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
    from tools.bootstrap_compare import compare_native
    binary2 = directory/('stage2.exe' if sys.platform == 'win32' else 'stage2')
    binary3 = directory/('stage3.exe' if sys.platform == 'win32' else 'stage3')
    comparison = compare_native(binary2.read_bytes(), binary3.read_bytes())
    require(comparison['normalized_equal'] and comparison == report['native_comparison'], 'native fixed-point evidence mismatch')
    for suffix in ('.frontend.ll', '.metadata.c'):
        require(Path(str(binary2)+suffix).read_bytes() == Path(str(binary3)+suffix).read_bytes(), 'frontend/metadata fixed point mismatch')
    cycle = report['bootstrap']
    require(cycle['fixed_point'] is True and len(cycle['stages']) == 2, 'bootstrap cycle missing')
    require(cycle['source_sha256'] == digest(ROOT/'bootstrap/compiler.ru'), 'compiler source identity mismatch')
    for binary, row in zip((binary2,binary3),cycle['stages']):
        require(row['binary_sha256'] == digest(binary) and
                row['source_ir_sha256'] == digest(str(binary)+'.frontend.ll') and
                row['metadata_sha256'] == digest(str(binary)+'.metadata.c'), 'cycle artifact hash mismatch')
    require(digest(directory/'verification.json') == report_hash, 'M4 report changed after reading')
    return {'report_sha256':report_hash, 'compiler':str(binary3), 'compiler_sha256':digest(binary3),
            'inputs':report['input_sha256'], 'artifacts':report['artifact_sha256'],
            'triple':cycle['triple'], 'llvm':cycle['llvm']}

def required_cases(kind):
    return sorted(MODULES[kind]+'.'+name for name in REQUIRED[kind])

def suite_cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from suite_cases(item)
        else:
            yield item.id()

def require_cases(cases, kind):
    require(sorted(cases) == required_cases(kind), 'exact required slot '+kind+' cases missing, extra or duplicated')

class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
        self.active = {}

    def startTest(self, test):
        super().startTest(test)
        row = {'id':test.id(), 'status':'running'}
        self.records.append(row)
        self.active[test.id()] = row

    def status(self, test, value):
        row = self.active.get(test.id())
        if row is None:
            row = {'id':test.id()}
            self.records.append(row)
        row['status'] = value

    def addSuccess(self, test):
        super().addSuccess(test)
        if self.active[test.id()]['status'] == 'running': self.status(test, 'passed')

    def addFailure(self, test, err):
        super().addFailure(test, err); self.status(test, 'failed')

    def addError(self, test, err):
        super().addError(test, err); self.status(test, 'error')

    def addSkip(self, test, reason):
        super().addSkip(test, reason); self.status(test, 'skipped')

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err); self.status(test, 'expected-failure')

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test); self.status(test, 'unexpected-success')

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None: self.status(test, 'failed-subtest')

def validate_results(report, kind):
    require(report.get('kind') == kind, 'slot report kind mismatch')
    expected = required_cases(kind)
    require(report.get('planned') == expected, 'slot planned cases mismatch')
    require(all(type(report.get(key)) is int for key in ('executed','skipped','failures','errors')),
            'slot result counts must be integers')
    records = report.get('records', [])
    require(sorted(row.get('id', '') for row in records) == expected and
            all(row.get('status') == 'passed' for row in records), 'every exact slot case must pass once')
    require(report.get('executed') == len(expected) and
            report.get('skipped') == report.get('failures') == report.get('errors') == 0 and
            report.get('runner_success') is True, 'slot failures/errors/skips cannot satisfy acceptance')

def artifact_hashes(path):
    require(path.is_dir() and not path.is_symlink(), 'slot evidence directory missing or aliased')
    result = {}
    for p in sorted(path.rglob('*')):
        require(not p.is_symlink(), 'slot evidence cannot contain symlinks')
        if p.is_file(): result[p.relative_to(path).as_posix()] = digest(p)
    require(result, 'actual slot application artifacts required')
    return result

def toolchain_identity():
    from rulang.llvm_toolchain import LLVMToolchain
    LINUX_TARGETS = ('x86_64-pc-linux-gnu', 'x86_64-unknown-linux-gnu')
    tc = LLVMToolchain()  # Enforces actual matching LLVM14 executables; no adapters.
    require(re.search(r'clang version 14\.', tc.version), 'actual LLVM14 toolchain required')
    require((sys.platform == 'linux' and tc.triple in LINUX_TARGETS) or
            (sys.platform == 'win32' and re.fullmatch(r'x86_64-pc-windows-msvc(?:[0-9]+(?:\.[0-9]+)*)?', tc.triple) is not None),
            'unsupported slot toolchain target')
    require(len(tc.clang) == 1, 'required acceptance forbids Clang command wrappers or extra arguments')
    clang = Path(shutil.which(tc.clang[0]) or tc.clang[0]).resolve()
    files = {'clang': {'path':str(clang), 'sha256':digest(clang)}}
    for name, value in tc.tools.items():
        path = Path(value).resolve()
        files[name] = {'path':str(path), 'sha256':digest(path)}
    require(set(files) == {'clang','llvm-as','llvm-link','opt','llvm-dis','llc'}, 'complete LLVM14 tools required')
    return {'version':tc.version, 'triple':tc.triple, 'data_layout':tc.data_layout,
            'clang_argv':list(tc.clang), 'resolved_clang':str(clang),
            'link_flags':list(tc.link_flags), 'executables':files}

INPUTS = ('bootstrap/compiler.ru', 'rulang/llvm_compiler.py', 'tools/bootstrap.py',
          'tools/bootstrap_verify.py', 'tools/bootstrap_compare.py', 'tests/test_bootstrap.py',
          'tools/verify_bootstrap_backend_ci.py', 'tests/test_bootstrap_backend_ci.py',
          '.github/workflows/bootstrap-backend.yml', 'tests/bootstrap_slot_cases.py',
          'tests/test_bootstrap_slot_reuse.py', 'tests/test_bootstrap_backend_native.py',
          'tests/fixtures/backend_native/main.ru', 'tests/fixtures/backend_native/panic_module.ru',
          'tests/fixtures/native/c_backend_bridge.c')


def evidence_inputs():
    require(all((ROOT/p).is_file() for p in INPUTS), 'required backend source missing')
    return {p:digest(ROOT/p) for p in INPUTS}


def preflight(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory/'backend-preflight.json'
    result = {'complete':False}
    path.write_text(json.dumps(result)+'\n',encoding='utf-8')
    try:
        result.update(checkout=checkout_identity(),inputs=evidence_inputs(),toolchain=toolchain_identity(),complete=True)
    finally:
        path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')


def preflight_snapshot(directory):
    path = directory/'backend-preflight.json'
    report, raw_hash = read_report(path)
    require(report.get('complete') is True and report.get('checkout') == checkout_identity() and
            report.get('inputs') == evidence_inputs() and report.get('toolchain') == toolchain_identity(),
            'pre-bootstrap source/toolchain baseline missing or changed')
    require(digest(path) == raw_hash, 'preflight report changed after read')
    return {'sha256':raw_hash,'report':report}


def tests(directory, kind):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    output = directory/('backend-'+kind+'-tests.json')
    report = {'format':1, 'kind':kind, 'complete':False, 'status':'running'}
    output.write_text(json.dumps(report)+'\n', encoding='utf-8')
    try:
        require(kind != 'windows' or sys.platform == 'win32', 'actual Windows required')
        before = preflight_snapshot(directory)
        checkout = checkout_identity()
        bootstrap = bootstrap_snapshot(directory)
        frozen = evidence_inputs()
        toolchain = toolchain_identity()
        require(toolchain['triple'] == bootstrap['triple'] and toolchain['version'] == bootstrap['llvm'], 'bootstrap/current toolchain mismatch')
        evidence = directory/('backend-'+kind+'-artifacts-'+uuid.uuid4().hex)
        evidence.mkdir()
        os.environ.update(RU_BOOTSTRAP_SLOT_REQUIRED='1', RU_BOOTSTRAP_SLOT_COMPILER=bootstrap['compiler'],
                          RU_BOOTSTRAP_SLOT_EVIDENCE_DIR=str(evidence), RU_BOOTSTRAP_BACKEND_REQUIRED='1',
                          RU_BOOTSTRAP_BACKEND_EVIDENCE_DIR=str(evidence))
        name = MODULES[kind]
        spec = importlib.util.spec_from_file_location(name, ROOT/'tests'/(name+'.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        require_cases(list(suite_cases(suite)), kind)
        result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
        report.update(preflight=before, checkout=checkout, platform=sys.platform, bootstrap=bootstrap, inputs=frozen, toolchain=toolchain,
                      planned=required_cases(kind), records=result.records, executed=result.testsRun,
                      skipped=len(result.skipped), failures=len(result.failures), errors=len(result.errors),
                      runner_success=result.wasSuccessful(), evidence_directory=evidence.name)
        validate_results(report, kind)
        require(preflight_snapshot(directory) == before and bootstrap_snapshot(directory) == bootstrap and checkout_identity() == checkout, 'bootstrap or checkout changed')
        require(evidence_inputs() == frozen and toolchain_identity() == toolchain, 'source/toolchain changed')
        report['artifacts'] = artifact_hashes(evidence)
        report.update(complete=True, status='passed', scope=('actual-stage3-and-PythonLLVM-lifecycle' if kind == 'runtime'
                    else 'PythonLLVM-existing-scalar-manifest-native-opt-in; not pureRu native'))
    except Exception as error:
        report.update(complete=False, status='failed', error=str(error))
        raise
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def combined(directory):
    directory = Path(directory).resolve()
    output = directory/'backend-acceptance.json'
    result = {'format':1,'complete':False,'status':'running'}
    output.write_text(json.dumps(result)+'\n',encoding='utf-8')
    try:
        before = preflight_snapshot(directory)
        checkout = checkout_identity(); bootstrap = bootstrap_snapshot(directory)
        frozen = evidence_inputs(); toolchain = toolchain_identity()
        kinds = ['runtime'] + (['windows'] if sys.platform == 'win32' else [])
        reports = {}
        for kind in kinds:
            path = directory/('backend-'+kind+'-tests.json')
            report, raw_hash = read_report(path)
            validate_results(report,kind)
            require(report.get('complete') is True and report.get('status') == 'passed', 'incomplete backend report')
            require(report['preflight'] == before and report['platform'] == sys.platform and report['checkout'] == checkout and report['bootstrap'] == bootstrap,
                    'backend report identity mismatch')
            require(report['inputs'] == frozen and report['toolchain'] == toolchain, 'backend source/toolchain mismatch')
            name = report['evidence_directory']
            require(Path(name).name == name and name.startswith('backend-'+kind+'-artifacts-'), 'invalid evidence path')
            require(artifact_hashes(directory/name) == report['artifacts'], 'backend artifacts changed')
            reports[kind] = {'sha256':raw_hash, 'report':report}
        require(preflight_snapshot(directory) == before and checkout_identity() == checkout and bootstrap_snapshot(directory) == bootstrap and
                evidence_inputs() == frozen and toolchain_identity() == toolchain, 'acceptance inputs changed')
        for kind, entry in reports.items():
            require(digest(directory/('backend-'+kind+'-tests.json')) == entry['sha256'], 'validated report changed')
            require(artifact_hashes(directory/entry['report']['evidence_directory']) == entry['report']['artifacts'],
                    'validated artifacts changed')
        result.update(complete=True,status='passed',preflight=before,checkout=checkout,bootstrap=bootstrap,inputs=frozen,
                      toolchain=toolchain,reports=reports,scope='ordinary backend correctness; not editor performance or pureRu native FFI')
    except Exception as error:
        result.update(status='failed',error=str(error)); raise
    finally:
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['preflight','runtime','windows','combined'])
    parser.add_argument('--directory',type=Path,required=True)
    args = parser.parse_args()
    if args.command == 'preflight': preflight(args.directory)
    elif args.command == 'combined': combined(args.directory)
    else: tests(args.directory,args.command)

if __name__ == '__main__': main()
