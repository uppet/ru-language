#!/usr/bin/env python3
"""Required real-stage3/LLVM14 shared slot gates. Not editor/default acceptance."""
import argparse
import hashlib
import io
from contextlib import redirect_stdout, redirect_stderr
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
from tools import verify_bootstrap_native_ci as native

MODULES = {'runtime': 'test_bootstrap_slot_reuse', 'windows': 'test_bootstrap_slot_reuse_native'}
REQUIRED = {'runtime': ['BootstrapSlotStructureTests.test_normalized_ir_and_runtime_preserve_operations', 'BootstrapSlotStructureTests.test_reuse_and_success_edge_differ_from_unsafe_unwind_rule', 'BootstrapSlotStructureTests.test_ssa_unique_physical_bounds_and_highwater', 'BootstrapSlotReuseTests.test_python_01_panic_check_success_keeps_outer_arguments', 'BootstrapSlotReuseTests.test_python_02_prepared_receiver_survives_argument_and_reentry', 'BootstrapSlotReuseTests.test_python_03_named_pack_contiguity_and_source_order', 'BootstrapSlotReuseTests.test_python_04_return_array_copy_before_frame_cleanup', 'BootstrapSlotReuseTests.test_python_05_panic_suppresses_remaining_args_then_resumes', 'BootstrapSlotReuseTests.test_python_06_nested_rescue_return_and_break', 'BootstrapSlotReuseTests.test_python_07_counted_nested_loops_branches_scalar_liveness', 'BootstrapSlotReuseTests.test_python_08_closures_env_escape_recursion_and_self', 'BootstrapSlotReuseTests.test_python_09_scope_rescue_closure_escapes', 'BootstrapSlotReuseTests.test_python_10_runtime_reentrant_callbacks_map_cycles', 'BootstrapSlotReuseTests.test_python_11_short_circuit_map_nested_values_and_assignment', 'BootstrapSlotReuseTests.test_python_12_early_finish_unreachable_branch_and_zero_arg_pack', 'BootstrapSlotReuseTests.test_python_13_return_break_other_branch_remains_correct', 'BootstrapSlotReuseTests.test_python_unsafe_unwind_reset_is_rejected', 'BootstrapSlotReuseTests.test_stage3_01_panic_check_success_keeps_outer_arguments', 'BootstrapSlotReuseTests.test_stage3_02_prepared_receiver_survives_argument_and_reentry', 'BootstrapSlotReuseTests.test_stage3_03_named_pack_contiguity_and_source_order', 'BootstrapSlotReuseTests.test_stage3_04_return_array_copy_before_frame_cleanup', 'BootstrapSlotReuseTests.test_stage3_05_panic_suppresses_remaining_args_then_resumes', 'BootstrapSlotReuseTests.test_stage3_06_nested_rescue_return_and_break', 'BootstrapSlotReuseTests.test_stage3_07_counted_nested_loops_branches_scalar_liveness', 'BootstrapSlotReuseTests.test_stage3_08_closures_env_escape_recursion_and_self', 'BootstrapSlotReuseTests.test_stage3_09_scope_rescue_closure_escapes', 'BootstrapSlotReuseTests.test_stage3_10_runtime_reentrant_callbacks_map_cycles', 'BootstrapSlotReuseTests.test_stage3_11_short_circuit_map_nested_values_and_assignment', 'BootstrapSlotReuseTests.test_stage3_12_early_finish_unreachable_branch_and_zero_arg_pack', 'BootstrapSlotReuseTests.test_stage3_13_return_break_other_branch_remains_correct', 'BootstrapSlotReuseTests.test_stage3_unsafe_unwind_reset_is_rejected'], 'windows': ['SlotReuseNativeCallbackTests.test_parent_temporaries_survive_nested_callback_panic_retry']}
require = native.require
digest = native.digest


def checkout_identity():
    require(os.environ.get('GITHUB_REF') == 'refs/heads/feature/bootstrap-slot-reuse-20261023',
            'slot experiment requires its isolated branch')
    expected=os.environ.get('GITHUB_SHA','')
    require(re.fullmatch('[a-f0-9]{40}',expected), 'exact CI commit required')
    actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,encoding='utf-8').strip()
    require(actual==expected,'checkout HEAD differs from CI commit')
    return actual


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


def evidence_inputs(kind):
    # Hash only: no application AST parsing in this runner.
    paths = [Path(__file__).resolve(), ROOT/'tools/verify_bootstrap_native_ci.py',
             ROOT/'tests'/(MODULES[kind]+'.py'), ROOT/'tests/test_bootstrap_slot_ci.py',
             ROOT/'.github/workflows/bootstrap-slot-reuse.yml', ROOT/'tests/test_bootstrap_slot_workflow.py',
             ROOT/'tests/bootstrap_slot_cases.py',
             ROOT/'tools/bootstrap_slot_old_artifact.py', ROOT/'tools/diagnose_bootstrap_slot_control.py',
             ROOT/'tests/test_bootstrap_slot_old_artifact.py', ROOT/'tests/test_bootstrap_slot_control.py']
    if kind == 'windows':
        fixture = ROOT/'tests/fixtures/slot_reuse_native'
        require(fixture.is_dir() and any(fixture.iterdir()), 'required Windows slot DLL fixture missing')
        paths += sorted(fixture.rglob('*'))
        paths += [ROOT/'tests/fixtures/native/c_backend_bridge.c']
    paths = [p for p in paths if not p.is_dir()]
    require(all(p.is_file() for p in paths), 'required slot runner/test input missing')
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}


def toolchain_identity():
    from rulang.llvm_toolchain import LLVMToolchain
    LINUX_TARGETS = ('x86_64-pc-linux-gnu', 'x86_64-unknown-linux-gnu')
    from tools.bootstrap import supported_native_triple
    tc = LLVMToolchain()  # Enforces actual matching LLVM14 executables; no adapters.
    require(re.search(r'clang version 14\.', tc.version), 'actual LLVM14 toolchain required')
    require((sys.platform == 'linux' and tc.triple in LINUX_TARGETS) or
            (sys.platform == 'win32' and supported_native_triple(tc.triple)),
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


def tests(directory, kind):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    output = directory/('slot-'+kind+'-tests.json')
    report = {'format':1, 'kind':kind, 'complete':False, 'status':'running'}
    output.write_text(json.dumps(report)+'\n', encoding='utf-8')  # Invalidate stale success first.
    try:
        require(kind != 'windows' or sys.platform == 'win32', 'real Windows required; cannot skip callback gate')
        commit = checkout_identity()
        compiler = native.stage3(directory)
        bootstrap_hash = digest(directory/'verification.json')
        frozen = evidence_inputs(kind)
        toolchain = toolchain_identity()
        evidence = directory/('slot-'+kind+'-artifacts-'+uuid.uuid4().hex)
        evidence.mkdir()
        os.environ.update(RU_BOOTSTRAP_SLOT_REQUIRED='1',
                          RU_BOOTSTRAP_SLOT_COMPILER=str(compiler),
                          RU_BOOTSTRAP_SLOT_EVIDENCE_DIR=str(evidence))
        name = MODULES[kind]
        spec = importlib.util.spec_from_file_location(name, ROOT/'tests'/(name+'.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        require_cases(list(suite_cases(suite)), kind)
        result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
        report.update(commit=commit, platform=sys.platform, compiler=str(compiler), compiler_sha256=digest(compiler),
                      bootstrap_report_sha256=bootstrap_hash, inputs=frozen, toolchain=toolchain,
                      planned=required_cases(kind), records=result.records, executed=result.testsRun,
                      skipped=len(result.skipped), failures=len(result.failures), errors=len(result.errors),
                      runner_success=result.wasSuccessful(), evidence_directory=evidence.name)
        validate_results(report, kind)
        require(native.stage3(directory) == compiler and digest(directory/'verification.json') == bootstrap_hash,
                'verified bootstrap identity changed during slot suite')
        require(evidence_inputs(kind) == frozen, 'slot runner/test inputs changed')
        require(toolchain_identity() == toolchain, 'LLVM14 toolchain changed')
        report['artifacts'] = artifact_hashes(evidence)
        report.update(complete=True, status='passed', scope='actual-new-stage3-LLVM14-ordinary-slot-reuse; not dense specialization/editor performance acceptance')
    except Exception as error:
        report.update(complete=False, status='failed', error=str(error))
        raise
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def validate_legacy(report, compiler, kind):
    # Preserve the existing FFI format. It does not contain new slot per-case or
    # toolchain fields; do not retroactively claim those guarantees for this file.
    require(report.get('scope') == 'real-stage3-'+kind and
            report.get('compiler') == str(compiler) and
            report.get('complete') is True and report.get('compiler_sha256') == digest(compiler) and
            report.get('skipped') == report.get('failures') == report.get('errors') == 0 and
            report.get('executed') == report.get('planned') and
            report.get('planned', 0) >= len(native.REQUIRED_NATIVE_CASES[kind]),
            'existing FFI regression identity/counts required')


def combined(directory):
    directory = Path(directory).resolve()
    destination = directory/'slot-verification.json'
    destination.write_text('{"complete":false,"status":"running"}\n', encoding='utf-8')
    commit = checkout_identity()
    compiler = native.stage3(directory)
    compiler_hash = digest(compiler)
    bootstrap_hash = digest(directory/'verification.json')
    tc = toolchain_identity()
    kinds = ['runtime'] + (['windows'] if sys.platform == 'win32' else [])
    hashes = {}
    checked_evidence = []
    for kind in kinds:
        path = directory/('slot-'+kind+'-tests.json')
        raw = path.read_bytes()
        report = json.loads(raw)
        validate_results(report, kind)
        require(report.get('format') == 1 and report.get('complete') is True and
                report.get('platform') == sys.platform and report.get('commit') == commit and report.get('compiler') == str(compiler) and
                report.get('compiler_sha256') == digest(compiler) and
                report.get('bootstrap_report_sha256') == digest(directory/'verification.json') and
                report.get('inputs') == evidence_inputs(kind) and report.get('toolchain') == tc,
                'slot report identity stale or incomplete')
        name = report.get('evidence_directory', '')
        require(re.fullmatch('slot-'+kind+r'-artifacts-[a-f0-9]{32}', name), 'slot artifact directory identity invalid')
        require(report.get('artifacts') == artifact_hashes(directory/name), 'slot application artifacts changed')
        checked_evidence.append((kind, report['inputs'], directory/name, report['artifacts']))
        hashes[path.name] = hashlib.sha256(raw).hexdigest()
    for kind in ['frontend'] + (['windows'] if sys.platform == 'win32' else []):
        path = directory/('native-'+kind+'-tests.json')
        raw = path.read_bytes()
        old = json.loads(raw)
        validate_legacy(old, compiler, kind)
        hashes[path.name] = hashlib.sha256(raw).hexdigest()
    require(native.stage3(directory) == compiler and digest(compiler) == compiler_hash and
            digest(directory/'verification.json') == bootstrap_hash and toolchain_identity() == tc,
            'bootstrap/toolchain changed during aggregate verification')
    require(all(evidence_inputs(kind) == inputs and artifact_hashes(path) == artifacts
                for kind, inputs, path, artifacts in checked_evidence),
            'slot inputs/application artifacts changed during aggregate verification')
    require(all(digest(directory/name) == value for name,value in hashes.items()),
            'acceptance reports changed during aggregate verification')
    report = {'format':1, 'complete':True, 'platform':sys.platform, 'commit':commit,
              'scope':'required ordinary-slot-reuse and existing FFI gates; editor GUI/performance and dense specialization remain separate',
              'compiler_sha256':digest(compiler), 'bootstrap_report_sha256':digest(directory/'verification.json'),
              'required_kinds':kinds, 'reports':hashes, 'toolchain':tc}
    destination.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


def units(directory):
    """Persist portable guard logs even if later stage3/bootstrap never starts."""
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=True)
    output = directory/'slot-unit-tests.json'; log = directory/'slot-unit-tests.log'
    report = {'complete':False, 'scope':'portable synthetic gate tests, not LLVM acceptance'}
    output.write_text(json.dumps(report)+'\n', encoding='utf-8')
    buffer = io.StringIO()
    try:
        paths = [ROOT/'tests'/name for name in ('test_bootstrap_slot_ci.py','test_bootstrap_slot_workflow.py',
                 'test_bootstrap_slot_old_artifact.py','test_bootstrap_slot_control.py')]
        require(all(p.is_file() for p in paths), 'required portable gate source missing')
        before = {p.relative_to(ROOT).as_posix():digest(p) for p in paths}
        suite = unittest.TestSuite()
        for path in paths:
            suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests'), pattern=path.name))
        planned = sorted(suite_cases(suite))
        require(planned and len(planned)==len(set(planned)), 'portable guard cases absent/duplicated')
        with redirect_stdout(buffer), redirect_stderr(buffer):
            result = unittest.TextTestRunner(stream=buffer, verbosity=2, resultclass=EvidenceResult).run(suite)
        report.update(planned=planned, records=result.records, executed=result.testsRun,
                      skipped=len(result.skipped), failures=len(result.failures), errors=len(result.errors), inputs=before)
        require(result.wasSuccessful() and not result.skipped and result.testsRun==len(planned) and
                all(row['status']=='passed' for row in result.records), 'portable guards failed or skipped')
        require(before=={p.relative_to(ROOT).as_posix():digest(p) for p in paths}, 'portable guard inputs changed')
        report['complete']=True
    except Exception as error:
        report['error']=str(error); raise
    finally:
        raw=buffer.getvalue().encode('utf-8');log.write_bytes(raw)
        report['log_sha256']=hashlib.sha256(raw).hexdigest()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(buffer.getvalue())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=(*MODULES, 'report', 'units', 'checkout'))
    parser.add_argument('--directory', required=True, type=Path)
    args = parser.parse_args()
    if args.kind == 'checkout': return print(checkout_identity())
    if args.kind == 'units': return units(args.directory)
    if args.kind == 'report': print(json.dumps(combined(args.directory), indent=2))
    else: tests(args.directory, args.kind)


if __name__ == '__main__': main()

