#!/usr/bin/env python3
"""Fail-closed real LLVM14 owned-result argument-pack gate; no performance claim."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tests'))
from tools import verify_bootstrap_native_ci as native
from tools import verify_bootstrap_slot_ci as slot

MODULES = {'runtime':'test_bootstrap_pack_runtime', 'windows':'test_bootstrap_pack_native'}
CASE_IDS = (
    'panic_check_success_keeps_outer_arguments',
    'prepared_receiver_survives_argument_and_reentry',
    'named_pack_contiguity_and_source_order',
    'return_array_copy_before_frame_cleanup',
    'panic_suppresses_remaining_args_then_resumes',
    'nested_rescue_return_and_break',
    'counted_nested_loops_branches_scalar_liveness',
    'closures_env_escape_recursion_and_self',
    'scope_rescue_closure_escapes',
    'runtime_reentrant_callbacks_map_cycles',
    'short_circuit_map_nested_values_and_assignment',
    'early_finish_unreachable_branch_and_zero_arg_pack',
    'return_break_other_branch_remains_correct',
    'single_complex_argument_retained_through_callee_gc',
    'contiguous_heap_args_and_escaping_closure',
    'complex_middle_result_and_multicomplex_fallback',
    'single_argument_panic_recovery_closure_survives',
)
REQUIRED = {
    'runtime': ['BootstrapPackRuntimeTests.test_'+frontend+'_gc'+str(threshold)+'_'+f'{index:02d}_'+name
        for frontend in ('python','stage3') for threshold in (1,17)
        for index,name in enumerate(CASE_IDS,1)] + [
            'BootstrapPackRuntimeTests.test_python_unsafe_all_reuse_is_rejected',
            'BootstrapPackRuntimeTests.test_stage3_unsafe_all_reuse_is_rejected',
            'BootstrapPackRuntimeTests.test_early_original_argument_root_drop_is_rejected'],
    'windows':['PackNativeCallbackTests.test_parent_temporaries_survive_nested_callback_panic_retry'],
}
UNIT_FILES = ('test_llvm_argument_pack.py','test_bootstrap_pack_ci.py',
    'test_bootstrap_pack_artifact.py','test_bootstrap_pack_build.py',
    'test_bootstrap_pack_measurement.py','test_bootstrap_pack_workflow.py')
INPUT_FILES = (
    'tools/verify_bootstrap_pack_ci.py','tools/verify_bootstrap_slot_ci.py',
    'tools/verify_bootstrap_native_ci.py','tools/bootstrap.py','tools/bootstrap_compare.py',
    'tools/bootstrap_verify.py','tools/bootstrap_native_runtime.py',
    'bootstrap/compiler.ru','bootstrap/native_emit.ru','rulang/llvm_compiler.py',
    'rulang/llvm_runtime.h','rulang/runtime.h','rulang/native_runtime.h',
    'rulang/llvm_toolchain.py','rulang/toolchain_environment.py',
    'tests/bootstrap_pack_cases.py','tests/bootstrap_slot_cases.py',
    'tests/test_bootstrap_pack_runtime.py','tests/test_bootstrap_pack_native.py',
    'tests/test_bootstrap_slot_reuse.py','tests/test_bootstrap_slot_reuse_native.py',
    '.github/workflows/bootstrap-argument-pack.yml',
    'tools/bootstrap_pack_artifact.py','tools/bootstrap_pack_build.py','tools/measure_bootstrap_packs.py',
) + tuple('tests/'+name for name in UNIT_FILES)
require = native.require
digest = native.digest
EvidenceResult = slot.EvidenceResult
suite_cases = slot.suite_cases
toolchain_identity = slot.toolchain_identity
artifact_hashes = slot.artifact_hashes
validate_legacy = slot.validate_legacy


def checkout_identity():
    require(os.environ.get('GITHUB_REF') == 'refs/heads/feature/bootstrap-argument-pack-20261023',
            'pack experiment requires its exact isolated branch')
    expected = os.environ.get('GITHUB_SHA','')
    require(re.fullmatch('[a-f0-9]{40}',expected), 'exact CI commit required')
    actual = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,encoding='utf-8').strip()
    require(actual == expected, 'checkout HEAD differs from CI commit')
    return actual


def required_cases(kind):
    return sorted(MODULES[kind]+'.'+name for name in REQUIRED[kind])


def require_cases(cases, kind):
    require(sorted(cases) == required_cases(kind), 'exact required pack '+kind+' cases missing, extra or duplicated')


def evidence_inputs(kind):
    paths = [ROOT/name for name in INPUT_FILES]
    if kind == 'windows':
        paths.extend(ROOT/name for name in ('tests/fixtures/slot_reuse_native/main.ru',
            'tests/fixtures/slot_reuse_native/panic_module.ru','tests/fixtures/native/c_backend_bridge.c'))
    require(len(paths) == len(set(paths)) and all(p.is_file() for p in paths), 'required unique pack input missing')
    return {p.relative_to(ROOT).as_posix():digest(p) for p in paths}


def validate_results(report, kind):
    require(report.get('kind') == kind, 'pack report kind mismatch')
    expected = required_cases(kind)
    require(report.get('planned') == expected, 'pack planned cases mismatch')
    require(all(type(report.get(key)) is int for key in ('executed','skipped','failures','errors')),
            'pack result counts must be integers')
    records = report.get('records', [])
    require(sorted(row.get('id','') for row in records) == expected and
            all(row.get('status') == 'passed' for row in records), 'every exact pack case must pass once')
    require(report.get('executed') == len(expected) and
            report.get('skipped') == report.get('failures') == report.get('errors') == 0 and
            report.get('runner_success') is True, 'pack failures/errors/skips cannot satisfy acceptance')


def tests(directory, kind):
    directory = Path(directory).resolve(); directory.mkdir(parents=True,exist_ok=True)
    output = directory/('pack-'+kind+'-tests.json')
    report = {'format':1,'kind':kind,'complete':False,'status':'running'}
    output.write_text(json.dumps(report)+'\n',encoding='utf-8')
    try:
        require(kind != 'windows' or sys.platform == 'win32', 'real Windows required; pack callback gate cannot skip')
        commit = checkout_identity()
        compiler = native.stage3(directory)
        compiler_hash = digest(compiler)
        bootstrap_hash = digest(directory/'verification.json')
        frozen = evidence_inputs(kind); toolchain = toolchain_identity()
        evidence = directory/('pack-'+kind+'-artifacts-'+uuid.uuid4().hex); evidence.mkdir()
        # Existing native helper retains its required-mode protections. PACK names
        # are used by the new non-native suite; values identify the same compiler.
        environment = {
            'RU_BOOTSTRAP_PACK_REQUIRED':'1','RU_BOOTSTRAP_PACK_COMPILER':str(compiler),
            'RU_BOOTSTRAP_PACK_EVIDENCE_DIR':str(evidence),
            'RU_BOOTSTRAP_SLOT_REQUIRED':'1','RU_BOOTSTRAP_SLOT_COMPILER':str(compiler),
            'RU_BOOTSTRAP_SLOT_EVIDENCE_DIR':str(evidence),
        }
        previous = {key:os.environ.get(key) for key in environment}
        try:
            os.environ.update(environment)
            name=MODULES[kind]
            spec=importlib.util.spec_from_file_location(name,ROOT/'tests'/(name+'.py'))
            module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
            suite=unittest.defaultTestLoader.loadTestsFromModule(module)
            require_cases(list(suite_cases(suite)),kind)
            result=unittest.TextTestRunner(verbosity=2,resultclass=EvidenceResult).run(suite)
        finally:
            for key,value in previous.items():
                if value is None: os.environ.pop(key,None)
                else: os.environ[key]=value
        report.update(commit=commit,platform=sys.platform,compiler=str(compiler),compiler_sha256=compiler_hash,
            bootstrap_report_sha256=bootstrap_hash,inputs=frozen,toolchain=toolchain,
            planned=required_cases(kind),records=result.records,executed=result.testsRun,
            skipped=len(result.skipped),failures=len(result.failures),errors=len(result.errors),
            runner_success=result.wasSuccessful(),evidence_directory=evidence.name)
        validate_results(report,kind)
        require(native.stage3(directory)==compiler and digest(compiler)==compiler_hash and
                digest(directory/'verification.json')==bootstrap_hash,'verified bootstrap changed during pack suite')
        require(evidence_inputs(kind)==frozen and toolchain_identity()==toolchain,'pack sources/toolchain changed')
        report['artifacts']=artifact_hashes(evidence)
        report.update(complete=True,status='passed',scope='actual-new-stage3-LLVM14-owned-argument-pack; not dense/editor performance')
    except Exception as error:
        report.update(complete=False,status='failed',error=str(error));raise
    finally:
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def unit_inputs():
    # Bind implementation, emitters and fixtures as well as the portable test files.
    # The same complete input set is used on Linux and Windows unit-only runs.
    return evidence_inputs('windows')


def unit_cases():
    """Enumerate the exact fixed-module test inventory; do not execute tests."""
    suite=unittest.TestSuite()
    for name in UNIT_FILES:
        require((ROOT/'tests'/name).is_file(),'required pack portable source missing')
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=name))
    planned=sorted(suite_cases(suite))
    require(planned and len(planned)==len(set(planned)),'pack portable cases absent/duplicated')
    return planned


def validate_units(report, directory):
    require(report.get('complete') is True and report.get('inputs')==unit_inputs(), 'pack units stale or incomplete')
    planned=report.get('planned',[]);records=report.get('records',[])
    require(planned==unit_cases(),'pack portable planned inventory differs from exact fixed modules')
    require(all(type(report.get(key)) is int for key in ('executed','skipped','failures','errors')),
            'pack portable counts must be integers')
    require(report.get('executed')==len(planned) and
            report.get('skipped')==report.get('failures')==report.get('errors')==0 and
            sorted(row.get('id','') for row in records)==planned and
            all(row.get('status')=='passed' for row in records),'pack portable cases absent, failed or skipped')
    require(report.get('log_sha256')==digest(Path(directory)/'pack-unit-tests.log'),'pack portable log changed')


def combined(directory):
    directory=Path(directory).resolve();destination=directory/'pack-verification.json'
    destination.write_text('{"complete":false,"status":"running"}\n',encoding='utf-8')
    commit=checkout_identity()
    bootstrap_raw=(directory/'verification.json').read_bytes()
    bootstrap_hash=hashlib.sha256(bootstrap_raw).hexdigest()
    compiler=native.stage3(directory)
    require(digest(directory/'verification.json')==bootstrap_hash,'verified bootstrap bytes changed')
    compiler_hash=digest(compiler);tc=toolchain_identity()
    report_raw=(directory/'report.json').read_bytes()
    require(json.loads(report_raw)==json.loads(bootstrap_raw).get('bootstrap'),'bootstrap generation report differs from verified receipt')
    generation_hash=hashlib.sha256(report_raw).hexdigest()
    slot_units_raw=(directory/'slot-unit-tests.json').read_bytes()
    slot_units=json.loads(slot_units_raw)
    require(slot_units.get('complete') is True,'existing slot portable guards incomplete')
    slot_units_hash=hashlib.sha256(slot_units_raw).hexdigest()
    # Revalidate original105/native/slot gates, never replace them with new tests.
    legacy=slot.combined(directory)
    require(legacy.get('complete') is True and legacy.get('commit')==commit and
            legacy.get('compiler_sha256')==compiler_hash,'existing slot/native gates incomplete')
    legacy_raw=(directory/'slot-verification.json').read_bytes()
    require(json.loads(legacy_raw)==legacy,'existing aggregate bytes changed after validation')
    kinds=['runtime']+(['windows'] if sys.platform=='win32' else [])
    hashes=dict(legacy['reports'])
    hashes.update({'slot-verification.json':hashlib.sha256(legacy_raw).hexdigest(),
        'verification.json':bootstrap_hash,'report.json':generation_hash,'slot-unit-tests.json':slot_units_hash})
    checked=[]
    for kind in kinds:
        path=directory/('pack-'+kind+'-tests.json');raw=path.read_bytes();report=json.loads(raw)
        validate_results(report,kind)
        require(report.get('format')==1 and report.get('complete') is True and report.get('platform')==sys.platform and
                report.get('commit')==commit and report.get('compiler')==str(compiler) and
                report.get('compiler_sha256')==compiler_hash and report.get('bootstrap_report_sha256')==bootstrap_hash and
                report.get('inputs')==evidence_inputs(kind) and report.get('toolchain')==tc,'pack report identity stale or incomplete')
        name=report.get('evidence_directory','')
        require(re.fullmatch('pack-'+kind+r'-artifacts-[a-f0-9]{32}',name),'pack artifact directory identity invalid')
        require(report.get('artifacts')==artifact_hashes(directory/name),'pack application artifacts changed')
        hashes[path.name]=hashlib.sha256(raw).hexdigest();checked.append((kind,report['inputs'],directory/name,report['artifacts']))
    units_path=directory/'pack-unit-tests.json';units_raw=units_path.read_bytes()
    unit_report=json.loads(units_raw)
    validate_units(unit_report,directory)
    frozen_unit_inputs=dict(unit_report['inputs'])
    frozen_unit_log=unit_report['log_sha256']
    hashes[units_path.name]=hashlib.sha256(units_raw).hexdigest()
    # Inherit the hashes of bytes actually validated above. Never re-baseline a
    # referenced report after another verifier has already consumed it.
    require(native.stage3(directory)==compiler and digest(compiler)==compiler_hash and
            digest(directory/'verification.json')==bootstrap_hash and toolchain_identity()==tc,
            'bootstrap/toolchain changed during pack aggregate')
    require(all(evidence_inputs(kind)==inputs and artifact_hashes(path)==artifacts
                for kind,inputs,path,artifacts in checked),'pack sources/artifacts changed during aggregate')
    require(unit_inputs()==frozen_unit_inputs and digest(directory/'pack-unit-tests.log')==frozen_unit_log,
            'pack portable inputs/log changed during aggregate')
    require(all(digest(directory/name)==value for name,value in hashes.items()),'pack referenced report changed')
    report={'format':1,'complete':True,'platform':sys.platform,'commit':commit,
        'scope':'owned argument-pack plus existing105/native/slot gates; editor and performance remain separate',
        'compiler_sha256':compiler_hash,'bootstrap_report_sha256':bootstrap_hash,
        'required_kinds':kinds,'reports':hashes,'toolchain':tc,
        'unit_log_sha256':frozen_unit_log}
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


def units(directory):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    output=directory/'pack-unit-tests.json';log=directory/'pack-unit-tests.log'
    report={'complete':False,'scope':'portable synthetic gates, not LLVM14/Windows execution'}
    output.write_text(json.dumps(report)+'\n',encoding='utf-8');buffer=io.StringIO()
    try:
        before=unit_inputs();expected=unit_cases();suite=unittest.TestSuite()
        for name in UNIT_FILES: suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=name))
        planned=sorted(suite_cases(suite));require(planned==expected,'pack portable execution differs from fixed inventory')
        with redirect_stdout(buffer),redirect_stderr(buffer):
            result=unittest.TextTestRunner(stream=buffer,verbosity=2,resultclass=EvidenceResult).run(suite)
        report.update(planned=planned,records=result.records,executed=result.testsRun,skipped=len(result.skipped),
            failures=len(result.failures),errors=len(result.errors),inputs=before)
        require(result.wasSuccessful() and not result.skipped and result.testsRun==len(planned) and
                all(row['status']=='passed' for row in result.records),'pack portable tests failed or skipped')
        require(unit_inputs()==before,'pack portable sources changed');report['complete']=True
    except Exception as error:
        report['error']=str(error);raise
    finally:
        raw=buffer.getvalue().encode();log.write_bytes(raw);report['log_sha256']=hashlib.sha256(raw).hexdigest()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(buffer.getvalue())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind',choices=(*MODULES,'report','units','checkout'))
    parser.add_argument('--directory',required=True,type=Path);args=parser.parse_args()
    if args.kind=='checkout': return print(checkout_identity())
    if args.kind=='units': return units(args.directory)
    if args.kind=='report': print(json.dumps(combined(args.directory),indent=2))
    else: tests(args.directory,args.kind)


if __name__=='__main__': main()
