#!/usr/bin/env python3
"""Fixed-C production-wrapper diagnostic only; not a stage3/editor build proof."""
import argparse
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

SCHEMA = 'ru-notepad-fixed-c-launcher-diagnostic-v1'
MARKER = 'BOOTSTRAP_WRAPPER_VALID_PASS'
SENTINEL = 'fixed-main-entered.txt'
SOURCE = b'''#include <stdio.h>
int main(int argc, char **argv) {
    FILE *f;
    (void)argc; (void)argv;
    f = fopen("fixed-main-entered.txt", "wb");
    if (!f) return 71;
    if (fwrite("entered\\n", 1, 8, f) != 8) { fclose(f); return 72; }
    if (fclose(f)) return 73;
    puts("BOOTSTRAP_WRAPPER_VALID_PASS");
    return 0;
}
'''


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def plans(tools, app, build, triple, flags):
    return [
        [tools['clang'], '--target='+triple, '-std=c99', '-O2', '-c', str(build/'fixed-main.c'), '-o', str(build/'application.obj')],
        [tools['clang'], '--target='+triple, '-std=c99', '-O2', '-c', str(app/'packaging/bootstrap_gui_launcher.c'), '-I', str(app/'packaging'), '-o', str(build/'launcher.obj')],
        [tools['resource-compiler'], '/nologo', '/fo', str(build/'application.res'), str(app/'packaging/app.rc')],
        [tools['clang'], '--target='+triple, str(build/'application.obj'), str(build/'launcher.obj'), str(build/'application.res'),
         '-o', str(build/'ru_notepad.exe'), *flags, '-Xlinker', '/SUBSYSTEM:WINDOWS',
         '-Xlinker', '/ENTRY:wWinMainCRTStartup', '-Xlinker', '/MACHINE:X64', '-lshell32', '-luser32']]


def run_cases(gate, api, binary, owned, copies):
    results = {}
    for name, invalid in (('valid-main', False), ('invalid-surrogate', True)):
        directory = owned/name
        directory.mkdir(exist_ok=False)
        target = directory/'ru_notepad.exe'
        shutil.copyfile(binary['path'], target)
        record = gate.identity(target)
        require((record['sha256'], record['size']) == (binary['sha256'], binary['size']), 'wrapper diagnostic copy changed')
        copies.append(record)
        result = gate.run_child(api, target, ['\ud800'] if invalid else [],
                                invalid=invalid, marker=None if invalid else MARKER)
        sentinel = directory/SENTINEL
        if invalid:
            result['main_sentinel_absent'] = not sentinel.exists()
            if sentinel.exists():
                result.update(passed=False, error='invalid command line entered fixed C main')
        else:
            result['main_sentinel_exact'] = sentinel.is_file() and not sentinel.is_symlink() and sentinel.read_bytes() == b'entered\n'
            if not result['main_sentinel_exact']:
                result.update(passed=False, error='valid command line did not prove fixed C main entry')
            else:
                result['main_sentinel'] = gate.identity(sentinel)
        results[name] = result
    return results


def diagnose(config, owned_path):
    require(sys.platform == 'win32' and platform.machine() in ('AMD64', 'x86_64'), 'real Windows x64 required')
    require(config.get('schema') == 'ru-notepad-bootstrap-llvm-config-v1', 'unsupported source/tool config')
    app, language = (Path(config[key]['path']).resolve() for key in ('app_source', 'ru_source'))
    require(Path(__file__).resolve() == language/'tools/diagnose_bootstrap_launcher_windows.py', 'diagnostic must be in pinned language checkout')
    sys.path.insert(0, str(app/'tools'))
    driver = importlib.import_module('build_bootstrap_release')
    gate = importlib.import_module('verify_bootstrap_editor_windows')
    for module, name in ((driver,'build_bootstrap_release.py'),(gate,'verify_bootstrap_editor_windows.py')):
        require(Path(module.__file__).resolve() == app/'tools'/name, 'wrong pinned diagnostic module')
    sources = {key: driver.snapshot(Path(pin['path']).resolve(), pin['commit'], pin['tree'])
               for key,pin in ((key,config[key]) for key in ('ru_source','app_source'))}
    driver.verify_app_baseline(app, config['app_baseline'], sources['app_source'])
    diagnostic_paths = ('tools/diagnose_bootstrap_launcher_windows.py', 'tests/test_bootstrap_launcher_diagnostic.py',
                        'tools/diagnose_bootstrap_editor_fixture.py', '.github/workflows/bootstrap-native.yml', 'rulang/toolchain_environment.py')
    for relative in diagnostic_paths:
        require(sources['ru_source'].get(relative) == driver.identity(language/relative)['sha256'], 'untracked diagnostic input: '+relative)
    spec = importlib.util.spec_from_file_location('_fixed_launcher_environment', language/'rulang/toolchain_environment.py')
    environment_module = importlib.util.module_from_spec(spec);spec.loader.exec_module(environment_module)
    environment = environment_module.llvm_environment()
    require(not any(environment.get(k) for k in ('CL','_CL_','LINK','_LINK_')), 'ambient compiler/linker flag injection forbidden')
    sys.path.insert(0,str(language/'tools'))
    helper = importlib.import_module('diagnose_bootstrap_editor_fixture')
    require(Path(helper.__file__).resolve() == language/'tools/diagnose_bootstrap_editor_fixture.py', 'wrong owned-directory helper')
    owned = helper.fresh_owned(owned_path,[app,language])
    build = owned/'build';build.mkdir()
    tools = {name:str(Path(path).resolve()) for name,path in config['tool_paths'].items()}
    driver.validate_toolchain(tools,config['tool_sha256'])
    linker = driver.identity(tools['linker'])
    result = {'schema':SCHEMA,'scope':'fixed-C production-wrapper diagnostic only; no stage3/compiler/editor proof',
              'bootstrap_acceptance':False,'release_permission':False,'performance_acceptance':False,
              'runtime_seconds_per_child':60,'source_pins':{key:config[key] for key in sources},'source_sha256':sources,
              'tool_paths':tools,'tool_sha256':config['tool_sha256'],'commands':[],'artifacts':[], 'copies':[],
              'environment_sha256':digest(json.dumps(sorted(environment.items()),ensure_ascii=False).encode()),
              'sdk_crt_environment':{k:v for k,v in environment.items() if k.upper() in {'PATH','INCLUDE','LIB','LIBPATH','WINDOWSSDKDIR','WINDOWSSDKVERSION','VCTOOLSINSTALLDIR','VCTOOLSVERSION'}}}
    result['production_glue_inputs'] = [driver.identity(app/name) for name in
        ('packaging/bootstrap_gui_launcher.c','packaging/diagnostic_launcher.c','packaging/app.rc','packaging/app.manifest','assets/app-icon.ico')]
    result['diagnostic_inputs'] = [driver.identity(language/name) for name in diagnostic_paths]
    fixed = build/'fixed-main.c';fixed.write_bytes(SOURCE)
    result['artifacts'].append(driver.identity(fixed))
    def frozen():
        driver.validate_toolchain(tools,config['tool_sha256'])
        require(fixed.read_bytes() == SOURCE, 'fixed main source changed')
        for record in result['artifacts']+result['copies']+result['production_glue_inputs']+result['diagnostic_inputs']: gate.verify_identity(record)
    def command(argv, cwd, stdin=None):
        frozen()
        record={'argv':list(map(str,argv)),'cwd':str(cwd),'timeout_seconds':600,'environment_sha256':result['environment_sha256']}
        result['commands'].append(record)
        label='command-'+str(len(result['commands']))
        stdout,stderr=build/(label+'.stdout.log'),build/(label+'.stderr.log')
        try:
            with stdout.open('xb') as out,stderr.open('xb') as err:
                done=subprocess.run(record['argv'],cwd=cwd,env=environment,input=stdin,stdout=out,stderr=err,timeout=600)
            record['returncode']=done.returncode
            require(done.returncode == 0,'fixed wrapper diagnostic command failed')
        finally:
            record['stdout'],record['stderr']=driver.identity(stdout),driver.identity(stderr)
        raw=stdout.read_bytes()
        require(digest(raw)==record['stdout']['sha256'],'compiler stdout changed before parse')
        frozen()
        return raw.decode('utf-8')
    try:
        require(re.match(r'clang version 14\.',command([tools['clang'],'--version'],build)), 'LLVM14 required')
        ir=command([tools['clang'],'-S','-emit-llvm','-x','c','-','-o','-'],build,b'')
        triples=re.findall(r'^target triple = "([^"]+)"',ir,re.M);layouts=re.findall(r'^target datalayout = "([^"]+)"',ir,re.M)
        require(len(triples)==len(layouts)==1 and re.fullmatch(r'x86_64-pc-windows-msvc(?:[0-9]+(?:\.[0-9]+)*)?',triples[0]),'unsupported exact wrapper target')
        triple=triples[0];result.update(target_triple=triple,data_layout=layouts[0])
        plan=plans(tools,app,build,triple,driver.explicit_linker_flags(linker))
        for index,argv in enumerate(plan):
            if index==3:
                result['linker_selection']=driver.inspect_linker_command(argv,linker,environment,str(app/'packaging'),triple)
            command(argv,app/'packaging')
            output=build/('application.obj','launcher.obj','application.res','ru_notepad.exe')[index]
            result['artifacts'].append(driver.identity(output))
            if index==3:driver.verify_linker_selection(result['linker_selection'],tools,expected_command=argv,triple=triple)
        binary=result['artifacts'][-1];driver.verify_gui_pe(Path(binary['path']))
        result['results']=run_cases(gate,gate.load_windows_harness(app).Windows(),binary,owned,result['copies'])
        gate.verify_log_records(result['results'])
        frozen()
        result['status']='diagnostic-passed' if all(row.get('passed') is True for row in result['results'].values()) else 'diagnostic-failed'
    except Exception as exc:
        result.update(status='diagnostic-failed',error=str(exc))
    try:
        frozen()
        for key,pin in result['source_pins'].items():
            require(driver.snapshot(Path(pin['path']).resolve(),pin['commit'],pin['tree']) == sources[key], 'source changed during wrapper diagnostic')
        for row in result.get('results',{}).values():
            if 'main_sentinel' in row:gate.verify_identity(row['main_sentinel'])
        gate.verify_log_records(result.get('results',{}))
    except Exception as exc:
        result.update(status='diagnostic-failed',evidence_error=str(exc))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,type=Path);parser.add_argument('--owned-root',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();require(not args.output.exists(),'fresh diagnostic output required')
    raw=args.config.read_bytes()
    try:result=diagnose(json.loads(raw),args.owned_root)
    except Exception as exc:result={'schema':SCHEMA,'scope':'fixed-C wrapper diagnostic only','status':'diagnostic-failed','release_permission':False,'bootstrap_acceptance':False,'error':str(exc)}
    require(args.config.read_bytes()==raw,'diagnostic config changed');result['config_sha256']=digest(raw)
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2,ensure_ascii=True)
    return 0 if result['status']=='diagnostic-passed' else 1


if __name__=='__main__':raise SystemExit(main())
