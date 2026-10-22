#!/usr/bin/env python3
"""Required real-stage3/LLVM14 shared dense gates. Not editor/default acceptance."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import verify_bootstrap_native_ci as native

MODULES = {'frontend': 'test_bootstrap_dense_frontend',
           'runtime': 'test_bootstrap_dense_runtime',
           'windows': 'test_bootstrap_dense_native_callback'}
REQUIRED = {
 'frontend': ['DenseFrontendTests.'+name for name in (
  'test_selected_body_bridge_and_proof', 'test_both_optins_and_ordinary_mode',
  'test_exact_five_original_wij_selected_generically', 'test_decoder_never_executes_code',
  'test_versions_shapes_duplicates_and_effects', 'test_missing_or_aliased_module_and_unloaded_identity',
  'test_inventory_gate_before_source_open', 'test_source_changes_are_not_handwritten_kernels',
  'test_two_modules_with_same_function_name_use_full_identity', 'test_protocol_limits_and_string_control_characters',
  'test_absolute_above_root_alias_rejected', 'test_dense_target_contract',
  'test_failed_plan_keeps_existing_artifacts', 'test_output_cannot_overwrite_packet_or_manifest',
  'test_unknown_repeated_cli_flags_rejected')],
 'runtime': ['DenseRuntimeTests.'+name for name in (
  'test_five_original_wij_kernels_and_selected_llvm_only',
  'test_generic_changed_source_and_whole_plan_failure',
  'test_utf8_empty_byte_offsets_and_scalar_edges', 'test_scalar_and_range_errors_before_retain',
  'test_bounds_overflow_exact_source_span', 'test_production_and_instrumented_owner_gc_lifecycle')],
 'windows': ['BootstrapDenseNativeCallbackTests.'+name for name in (
  'test_callback_checked_errors_recover_production',
  'test_callback_source_depth_and_roots_restore_instrumented')],
}
require = native.require
digest = native.digest


def required_cases(kind):
    return sorted(MODULES[kind]+'.'+name for name in REQUIRED[kind])


def suite_cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from suite_cases(item)
        else:
            yield item.id()


def require_cases(cases, kind):
    require(sorted(cases) == required_cases(kind), 'exact required dense '+kind+' cases missing, extra or duplicated')


def evidence_inputs(kind):
    # Source text is only hashed, never parsed or used to generate application code.
    paths = [Path(__file__).resolve(), ROOT/'tools/verify_bootstrap_native_ci.py',
             ROOT/'tests'/(MODULES[kind]+'.py'), ROOT/'tests/test_bootstrap_dense_ci.py',
             ROOT/'.github/workflows/bootstrap-dense.yml', ROOT/'tests/test_bootstrap_dense_workflow.py',
             ROOT/'tests/test_bootstrap_dense_fixture_portability.py']
    paths += [ROOT/'tests/fixtures/dense'/name for name in
              ('targets.json','markdown_ascii_kernel.ru','markdown-dense-manifest.json')]
    paths += sorted((ROOT/'tests/fixtures/dense').rglob('*'))
    if kind == 'windows':
        fixture = ROOT/'tests/fixtures/dense_native'
        require(fixture.is_dir() and any(fixture.iterdir()), 'required Windows dense DLL fixture missing')
        paths += sorted(fixture.rglob('*'))
    paths = [p for p in paths if not p.is_dir()]
    require(all(p.is_file() for p in paths), 'required dense runner/test input missing')
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}


def toolchain_identity():
    from rulang.llvm_toolchain import LLVMToolchain
    from tools.bootstrap_dense_protocol import LINUX_TARGETS
    from tools.bootstrap import supported_native_triple
    tc = LLVMToolchain()  # Enforces actual matching LLVM14 executables; no adapters.
    require(re.search(r'clang version 14\.', tc.version), 'actual LLVM14 toolchain required')
    require((sys.platform == 'linux' and tc.triple in LINUX_TARGETS) or
            (sys.platform == 'win32' and supported_native_triple(tc.triple)),
            'unsupported dense toolchain target')
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
    require(report.get('kind') == kind, 'dense report kind mismatch')
    expected = required_cases(kind)
    require(report.get('planned') == expected, 'dense planned cases mismatch')
    require(all(type(report.get(key)) is int for key in ('executed','skipped','failures','errors')),
            'dense result counts must be integers')
    records = report.get('records', [])
    require(sorted(row.get('id', '') for row in records) == expected and
            all(row.get('status') == 'passed' for row in records), 'every exact dense case must pass once')
    require(report.get('executed') == len(expected) and
            report.get('skipped') == report.get('failures') == report.get('errors') == 0 and
            report.get('runner_success') is True, 'dense failures/errors/skips cannot satisfy acceptance')


def artifact_hashes(path):
    require(path.is_dir() and not path.is_symlink(), 'dense evidence directory missing or aliased')
    result = {}
    for p in sorted(path.rglob('*')):
        require(not p.is_symlink(), 'dense evidence cannot contain symlinks')
        if p.is_file(): result[p.relative_to(path).as_posix()] = digest(p)
    require(result, 'actual dense application artifacts required')
    return result


def tests(directory, kind):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    output = directory/('dense-'+kind+'-tests.json')
    report = {'format':1, 'kind':kind, 'complete':False, 'status':'running'}
    output.write_text(json.dumps(report)+'\n', encoding='utf-8')  # Invalidate stale success first.
    try:
        require(kind != 'windows' or sys.platform == 'win32', 'real Windows required; cannot skip callback gate')
        compiler = native.stage3(directory)
        bootstrap_hash = digest(directory/'verification.json')
        frozen = evidence_inputs(kind)
        toolchain = toolchain_identity()
        evidence = directory/('dense-'+kind+'-artifacts-'+uuid.uuid4().hex)
        evidence.mkdir()
        os.environ.update(RU_BOOTSTRAP_DENSE_REQUIRED='1',
                          RU_BOOTSTRAP_DENSE_TEST_COMPILER=str(compiler),
                          RU_BOOTSTRAP_DENSE_COMPILER=str(compiler),
                          RU_BOOTSTRAP_DENSE_EVIDENCE_DIR=str(evidence))
        name = MODULES[kind]
        spec = importlib.util.spec_from_file_location(name, ROOT/'tests'/(name+'.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        require_cases(list(suite_cases(suite)), kind)
        result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
        report.update(platform=sys.platform, compiler=str(compiler), compiler_sha256=digest(compiler),
                      bootstrap_report_sha256=bootstrap_hash, inputs=frozen, toolchain=toolchain,
                      planned=required_cases(kind), records=result.records, executed=result.testsRun,
                      skipped=len(result.skipped), failures=len(result.failures), errors=len(result.errors),
                      runner_success=result.wasSuccessful(), evidence_directory=evidence.name)
        validate_results(report, kind)
        require(native.stage3(directory) == compiler and digest(directory/'verification.json') == bootstrap_hash,
                'verified bootstrap identity changed during dense suite')
        require(evidence_inputs(kind) == frozen, 'dense runner/test inputs changed')
        require(toolchain_identity() == toolchain, 'LLVM14 toolchain changed')
        report['artifacts'] = artifact_hashes(evidence)
        report.update(complete=True, status='passed', scope='actual-new-stage3-LLVM14-shared-dense; not editor/default/performance acceptance')
    except Exception as error:
        report.update(complete=False, status='failed', error=str(error))
        raise
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def validate_legacy(report, compiler, kind):
    # Preserve the existing FFI format. It does not contain new dense per-case or
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
    destination = directory/'dense-verification.json'
    destination.write_text('{"complete":false,"status":"running"}\n', encoding='utf-8')
    compiler = native.stage3(directory)
    compiler_hash = digest(compiler)
    bootstrap_hash = digest(directory/'verification.json')
    tc = toolchain_identity()
    kinds = ['frontend','runtime'] + (['windows'] if sys.platform == 'win32' else [])
    hashes = {}
    checked_evidence = []
    for kind in kinds:
        path = directory/('dense-'+kind+'-tests.json')
        raw = path.read_bytes()
        report = json.loads(raw)
        validate_results(report, kind)
        require(report.get('format') == 1 and report.get('complete') is True and
                report.get('platform') == sys.platform and report.get('compiler') == str(compiler) and
                report.get('compiler_sha256') == digest(compiler) and
                report.get('bootstrap_report_sha256') == digest(directory/'verification.json') and
                report.get('inputs') == evidence_inputs(kind) and report.get('toolchain') == tc,
                'dense report identity stale or incomplete')
        name = report.get('evidence_directory', '')
        require(re.fullmatch('dense-'+kind+r'-artifacts-[a-f0-9]{32}', name), 'dense artifact directory identity invalid')
        require(report.get('artifacts') == artifact_hashes(directory/name), 'dense application artifacts changed')
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
            'dense inputs/application artifacts changed during aggregate verification')
    require(all(digest(directory/name) == value for name,value in hashes.items()),
            'acceptance reports changed during aggregate verification')
    report = {'format':1, 'complete':True, 'platform':sys.platform,
              'scope':'required shared dense and existing FFI gates; editor/B GUI and benefit acceptance remain separate',
              'compiler_sha256':digest(compiler), 'bootstrap_report_sha256':digest(directory/'verification.json'),
              'required_kinds':kinds, 'reports':hashes, 'toolchain':tc}
    destination.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=(*MODULES, 'report'))
    parser.add_argument('--directory', required=True, type=Path)
    args = parser.parse_args()
    if args.kind == 'report': print(json.dumps(combined(args.directory), indent=2))
    else: tests(args.directory, args.kind)


if __name__ == '__main__': main()
