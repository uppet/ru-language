#!/usr/bin/env python3
"""Three diagnostic probe builds; each entire worker has one owned 600s budget.

No Python frontend is used for A/B. C is explicitly Python-C-via-LLVM control.
The Windows worker is suspended until assigned to a kill-on-close Job Object.
"""
import argparse
import ctypes
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time

BUDGET = 600
ENTRY = 'tests/bootstrap_pipeline/dll_abi_probe.ru'
SCHEMA = 'ru-bootstrap-pack-prepared-v1'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def no_links(path):
    path=Path(os.path.abspath(path))
    for item in (path,*path.parents):
        info=item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not (getattr(info,'st_file_attributes',0)&0x400),
            'symlink/reparse evidence path forbidden')
    return path


def identity(path):
    path = no_links(path)
    require(path.is_file() and not path.is_symlink(), 'regular input required')
    raw = path.read_bytes()
    return dict(path=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))


def verify(record):
    path=no_links(record['path'])
    require(type(record['size']) is int and record['size']>=0 and path.is_file() and not path.is_symlink(), 'invalid frozen input')
    require(path.stat().st_size==record['size'], 'input/artifact size changed')
    with path.open('rb') as stream:
        raw=stream.read(record['size']+1)
    observed=dict(path=str(path.resolve()),sha256=hashlib.sha256(raw).hexdigest(),size=len(raw))
    require(observed==record, 'input/artifact identity changed')
    return path


def read(path):
    path = no_links(path)
    require(path.is_file() and not path.is_symlink(), 'regular JSON input required')
    with path.open('rb') as stream:
        raw = stream.read(32*1024*1024+1)
    require(len(raw) <= 32*1024*1024, 'oversized JSON evidence')
    record = dict(path=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
    data = json.loads(raw)
    verify(record)
    return data, record


def save(path, data):
    path = Path(path)
    no_links(path.parent)
    pending = path.with_suffix('.pending.json')
    with pending.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    require(not path.exists(), 'refuse existing output')
    os.replace(pending, path)


class WindowsJob:
    """Only this freshly created process tree; no name-based/global taskkill."""
    def __init__(self, argv, cwd, environment, stdout, stderr):
        require(sys.platform == 'win32' and ctypes.sizeof(ctypes.c_void_p) == 8, 'Windows x64 required')
        import msvcrt
        from ctypes import wintypes as w
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.job = self.process = self.thread = None
        self.pid = None
        self.files = []
        class Basic(ctypes.Structure):
            _fields_ = [('user',ctypes.c_int64),('kernel',ctypes.c_int64),('flags',w.DWORD),
                ('minimum',ctypes.c_size_t),('maximum',ctypes.c_size_t),('active',w.DWORD),
                ('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name,ctypes.c_uint64) for name in ('readops','writeops','otherops','readbytes','writebytes','otherbytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),
                ('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        class Accounting(ctypes.Structure):
            _fields_ = [(name,ctypes.c_int64) for name in ('user','kernel','perioduser','periodkernel')]+[
                ('pagefaults',w.DWORD),('total',w.DWORD),('active',w.DWORD),('terminated',w.DWORD)]
        class Startup(ctypes.Structure):
            _fields_ = [('cb',w.DWORD),('reserved',w.LPWSTR),('desktop',w.LPWSTR),('title',w.LPWSTR),
                *[(name,w.DWORD) for name in ('x','y','xsize','ysize','xchars','ychars','fill','flags')],
                ('show',w.WORD),('reserved2size',w.WORD),('reserved2',ctypes.POINTER(ctypes.c_byte)),
                ('stdin',w.HANDLE),('stdout',w.HANDLE),('stderr',w.HANDLE)]
        class PI(ctypes.Structure):
            _fields_ = [('process',w.HANDLE),('thread',w.HANDLE),('pid',w.DWORD),('tid',w.DWORD)]
        self.Accounting = Accounting
        specs = {
            'CreateJobObjectW': ([ctypes.c_void_p,w.LPCWSTR],w.HANDLE),
            'SetInformationJobObject': ([w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD],w.BOOL),
            'QueryInformationJobObject': ([w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p],w.BOOL),
            'AssignProcessToJobObject': ([w.HANDLE,w.HANDLE],w.BOOL),
            'TerminateJobObject': ([w.HANDLE,w.UINT],w.BOOL),
            'TerminateProcess': ([w.HANDLE,w.UINT],w.BOOL),
            'ResumeThread': ([w.HANDLE],w.DWORD),
            'CloseHandle': ([w.HANDLE],w.BOOL),
            'WaitForSingleObject': ([w.HANDLE,w.DWORD],w.DWORD),
            'GetExitCodeProcess': ([w.HANDLE,ctypes.POINTER(w.DWORD)],w.BOOL),
            'CreateProcessW': ([w.LPCWSTR,w.LPWSTR,ctypes.c_void_p,ctypes.c_void_p,w.BOOL,w.DWORD,
                ctypes.c_void_p,w.LPCWSTR,ctypes.POINTER(Startup),ctypes.POINTER(PI)],w.BOOL),
        }
        for name,(args,result) in specs.items():
            f=getattr(self.k,name);f.argtypes=args;f.restype=result
        require(ctypes.sizeof(Startup)==104 and ctypes.sizeof(PI)==24 and ctypes.sizeof(Extended)==144
            and ctypes.sizeof(Accounting)==48, 'unexpected Windows x64 ABI structure layout')
        require(argv and Path(argv[0]).is_absolute() and all('\0' not in str(x) for x in argv), 'invalid worker argv')
        self._assigned = False
        try:
            self.job = self.k.CreateJobObjectW(None,None)
            self.check(self.job,'CreateJobObject')
            limits=Extended();limits.basic.flags=0x2000  # KILL_ON_JOB_CLOSE; no breakaway flags.
            self.check(self.k.SetInformationJobObject(self.job,9,ctypes.byref(limits),ctypes.sizeof(limits)),'job limits')
            for path,mode in ((os.devnull,'rb'),(stdout,'xb'),(stderr,'xb')):
                self.files.append(open(path,mode))
            handles=[msvcrt.get_osfhandle(f.fileno()) for f in self.files]
            for h in handles: os.set_handle_inheritable(h,True)
            startup=Startup();startup.cb=ctypes.sizeof(startup);startup.flags=0x100
            startup.stdin,startup.stdout,startup.stderr=handles
            require(all(isinstance(k,str) and isinstance(v,str) and '\0' not in k+v and '=' not in k for k,v in environment.items()),'invalid environment')
            block=ctypes.create_unicode_buffer('\0'.join(k+'='+v for k,v in sorted(environment.items(),key=lambda p:p[0].upper()))+'\0\0')
            command=ctypes.create_unicode_buffer(subprocess.list2cmdline(list(map(str,argv))))
            info=PI()
            try:
                self.check(self.k.CreateProcessW(str(argv[0]),command,None,None,True,0x4|0x400,
                    block,str(cwd),ctypes.byref(startup),ctypes.byref(info)),'CreateProcess suspended')
                self.process,self.thread,self.pid=info.process,info.thread,int(info.pid)
            finally:
                for h in handles: os.set_handle_inheritable(h,False)
            self.check(self.k.AssignProcessToJobObject(self.job,self.process),'assign suspended worker')
            self._assigned=True
            self.check(self.k.ResumeThread(self.thread)!=0xffffffff,'resume owned worker')
        except BaseException:
            if self.process:
                self.k.TerminateProcess(self.process,1)
                self.k.WaitForSingleObject(self.process,5000)
            self.close()
            raise

    def check(self, value, label):
        if not value:
            raise OSError(ctypes.get_last_error(), label)

    def exit_code(self):
        from ctypes import wintypes as w
        status=self.k.WaitForSingleObject(self.process,0)
        require(status in (0,258),'process wait failed')
        if status==258: return None
        code=w.DWORD();self.check(self.k.GetExitCodeProcess(self.process,ctypes.byref(code)),'exit code')
        return int(code.value)

    def active(self):
        row=self.Accounting()
        self.check(self.k.QueryInformationJobObject(self.job,1,ctypes.byref(row),ctypes.sizeof(row),None),'job accounting')
        return int(row.active)

    def terminate(self):
        self.check(self.k.TerminateJobObject(self.job,1),'terminate owned job')

    def close(self):
        errors=[]
        for name in ('thread','process','job'):
            handle=getattr(self,name,None)
            if handle:
                if not self.k.CloseHandle(handle): errors.append(name)
                setattr(self,name,None)
        for f in self.files:
            try:f.close()
            except OSError as e:errors.append(str(e))
        require(not errors,'owned handle close failed: '+','.join(errors))


def supervise(argv, cwd, environment, evidence, *, job_factory=WindowsJob, clock=time.monotonic, sleep=time.sleep):
    """600 seconds covers creation, all compilation/link children, and worker completion."""
    evidence=Path(evidence);evidence.mkdir(parents=True,exist_ok=False)
    started=clock();deadline=started+BUDGET
    result=dict(schema='ru-owned-build-budget-v1',argv=list(map(str,argv)),cwd=str(cwd),
        environment_sha256=hashlib.sha256(json.dumps(environment,sort_keys=True).encode()).hexdigest(),
        started_monotonic=started,deadline_monotonic=deadline,budget_seconds=BUDGET,
        completed=False,timed_out=False,first_error=None,pid=None,cleanup_errors=[],process_reaped=False,tree_empty=False)
    job=None
    try:
        job=job_factory(argv,cwd,environment,evidence/'stdout.log',evidence/'stderr.log')
        result['pid']=job.pid
        while True:
            now=clock()
            if now>=deadline:
                result.update(timed_out=True,deadline_observed_monotonic=now)
                raise TimeoutError('aggregate build exceeded original 600s deadline')
            code=job.exit_code()
            if code is not None and job.active()==0:
                completed=clock()
                if completed>=deadline:
                    result.update(timed_out=True,deadline_observed_monotonic=completed)
                    raise TimeoutError('aggregate deadline crossed while observing completion')
                result['completed_monotonic']=completed
                result['exit_code']=code
                require(code==0,'build worker returned failure')
                result['completed']=True
                break
            sleep(min(0.05,max(0,deadline-now)))
    except Exception as exc:
        result['first_error']=dict(type=type(exc).__name__,message=str(exc),observed_monotonic=clock())
    finally:
        if job is not None:
            try:
                if job.exit_code() is None or job.active()!=0:
                    job.terminate()
                    result['terminated_owned_tree']=True
                cleanup_deadline=clock()+5
                while clock()<cleanup_deadline:
                    if job.exit_code() is not None and job.active()==0:break
                    sleep(0.01)
                result['exit_code']=job.exit_code()
                result['process_reaped']=result['exit_code'] is not None
                result['tree_empty']=job.active()==0
                require(result['process_reaped'] and result['tree_empty'],'owned build tree cleanup incomplete')
            except Exception as exc:result['cleanup_errors'].append(str(exc))
            try:job.close()
            except Exception as exc:result['cleanup_errors'].append(str(exc))
        for name in ('stdout','stderr'):
            path=evidence/(name+'.log')
            if path.is_file():result[name]=identity(path)
        result['finished_monotonic']=clock()
        if result['cleanup_errors'] or not result['process_reaped'] or not result['tree_empty']:
            result['completed']=False
        save(evidence/'budget.json',result)
    require(result['completed'] and not result['timed_out'],'strategy build failed; see budget.json')
    return result


def context(config):
    require(config.get('schema')=='ru-bootstrap-pack-build-config-v1','wrong build configuration')
    require(not any(os.environ.get(k) for k in ('GITHUB_TOKEN','GH_TOKEN')), 'tokens forbidden in build workers')
    app=no_links(config['editor_root']).resolve()
    for value in config['build_configs'].values():
        require(value['app_source']['commit']=='2cb3b8c81ba300745b244c51b50d5625430fbe4f'
            and value['app_source']['tree']=='5c63f94cd9e3816608cc95b834f91428bbeb3c49'
            and Path(value['app_source']['path']).resolve()==app, 'wrong fixed editor pin')
    def git(*args):
        return subprocess.run(['git','-C',str(app),*args],capture_output=True,text=True,check=True,timeout=30).stdout.strip()
    require(git('rev-parse','HEAD')=='2cb3b8c81ba300745b244c51b50d5625430fbe4f'
        and git('rev-parse','HEAD^{tree}')=='5c63f94cd9e3816608cc95b834f91428bbeb3c49'
        and not git('status','--porcelain','--untracked-files=all'), 'editor source changed before import')
    sys.path.insert(0,str(app/'tools'))
    modules={}
    for name in ('build_bootstrap_release','verify_bootstrap_editor_windows','prepare_bootstrap_dependencies'):
        module=importlib.import_module(name)
        require(Path(module.__file__).resolve()==app/'tools'/(name+'.py'),'wrong pinned app module')
        modules[name]=module
    return app,modules['build_bootstrap_release'],modules['verify_bootstrap_editor_windows'],modules['prepare_bootstrap_dependencies']


def normalized_graph(records, app, language):
    result={}
    roots={'app':Path(app).resolve(),'language':Path(language).resolve()}
    for record in records:
        path=verify(record).resolve()
        matches=[(name,path.relative_to(root).as_posix()) for name,root in roots.items() if path.is_relative_to(root)]
        require(len(matches)==1,'graph source outside/overlapping frozen roots')
        key='/'.join(matches[0]);require(key not in result,'duplicate graph member')
        result[key]={'sha256':record['sha256'],'size':record['size']}
    require(result,'empty source graph')
    return result


def validate_probe(path, expected, driver, gate):
    """Single dll-probe equivalent of the existing three-entry gate; no fake app receipt."""
    receipt,record=read(path);directory=Path(path).resolve().parent
    require(receipt.get('schema')=='ru-notepad-bootstrap-llvm-build-v1'
        and receipt.get('status')=='built-not-runtime-accepted-not-publishable'
        and receipt.get('native_acceptance') is False and receipt.get('entry_source')==ENTRY,'invalid probe build receipt')
    require(receipt['source_pins']=={k:expected[k] for k in ('ru_source','app_source')},'probe source pin mismatch')
    require(receipt['tool_paths']==expected['tool_paths'] and receipt['tool_sha256']==expected['tool_sha256'],'probe tool configuration changed')
    require(receipt['toolchain_identity_scopes']=={
        'bootstrap':'existing M4 LLVM14/target/fixedpoint; bootstrap linker identity not recorded or locked',
        'application':'explicit config-hash toolchain/linker'},'toolchain scope changed')
    for key,pin in receipt['source_pins'].items():
        require(driver.snapshot(Path(pin['path']),pin['commit'],pin['tree'])==receipt['source_sha256'][key],'probe source changed')
    app=Path(expected['app_source']['path']).resolve()
    driver.verify_app_baseline(app,receipt['app_baseline'],receipt['source_sha256']['app_source'])
    for name,digest in receipt['driver_inputs'].items():require(identity(name)['sha256']==digest,'driver changed')
    driver.validate_toolchain(receipt['tool_paths'],receipt['tool_sha256'])
    driver.verify_gui_pe(verify(receipt['final_binary']))
    require(verify(receipt['final_binary']).resolve()==directory/'ru_notepad.exe','binary outside probe build')
    proof,proof_record=read(directory/'compile-proof.json')
    require(proof_record['sha256']==receipt['compile_proof_sha256']
        and proof['standalone_ir_sha256']==receipt['standalone_ir_sha256'],'proof/IR binding changed')
    compiler=Path(expected['bootstrap_directory']).resolve()/'stage3.exe'
    require(Path(proof['compiler']['path']).resolve()==compiler,'wrong stage3 compiler')
    require(receipt['bootstrap_verification']==identity(expected['verification']),'verification identity changed')
    require(receipt['bootstrap']['stage3_sha256']==identity(compiler)['sha256']
        and receipt['bootstrap']['verification_sha256']==receipt['bootstrap_verification']['sha256'],'bootstrap hash mismatch')
    frozen={str((Path(pin['path'])/name).resolve()):digest for key,pin in receipt['source_pins'].items()
        for name,digest in receipt['source_sha256'][key].items()}
    frozen[str(compiler)]=receipt['bootstrap']['stage3_sha256']
    frozen.update({str(Path(p).resolve()):receipt['tool_sha256'][k] for k,p in receipt['tool_paths'].items()})
    driver.verify_proof(proof,source=app/ENTRY,compiler=compiler,ir=directory/'application.ll',
        binary=directory/'intermediate-console.exe',triple=receipt['target_triple'],layout=receipt['data_layout'],frozen=frozen,tools=receipt['tool_paths'])
    require(set(receipt['linked_inputs'])=={'application.obj','launcher.obj','application.res'},'missing GUI link inputs')
    for name,value in receipt['linked_inputs'].items():require(verify(value).resolve()==directory/name,'GUI input outside build')
    driver.verify_linker_selection(receipt['final_linker_selection'],receipt['tool_paths'],expected_command=receipt['commands'][-1],triple=receipt['target_triple'])
    driver.verify_linker_probe(receipt['linker_probe'],receipt['tool_paths'],receipt['target_triple'],directory)
    verify(record);verify(proof_record)
    return receipt,record,proof,proof_record


BASE_COMMIT = '46c81ccfde815b8917be9107288b9a80b08758c9'
BASE_TREE = '19c4199f3381bca19be01d5e703ef0b691ec7f8b'
LANGUAGE_DELTA = frozenset((
    '.github/workflows/bootstrap-argument-pack.yml',
    'bootstrap/compiler.ru',
    'rulang/llvm_compiler.py',
    'tests/bootstrap_pack_cases.py',
    'tests/test_bootstrap_pack_artifact.py',
    'tests/test_bootstrap_pack_build.py',
    'tests/test_bootstrap_pack_ci.py',
    'tests/test_bootstrap_pack_measurement.py',
    'tests/test_bootstrap_pack_native.py',
    'tests/test_bootstrap_pack_runtime.py',
    'tests/test_bootstrap_pack_workflow.py',
    'tests/test_llvm_argument_pack.py',
    'tools/bootstrap_pack_artifact.py',
    'tools/bootstrap_pack_build.py',
    'tools/measure_bootstrap_packs.py',
    'tools/verify_bootstrap_pack_ci.py',
    'tools/verify_bootstrap_slot_ci.py',
))
# Frozen production bytes; never derive these pins from the candidate at runtime.
EMITTER_HASHES = {
    'bootstrap/compiler.ru':'c4ae09dad12958def0733e06ef74f0c4580657d731d6fbdeee87f2ce4df24155',
    'rulang/llvm_compiler.py':'010609128d90711221e100c2784332a427475714633c7b91ce7c9eccfb39464c'}
MEASUREMENT_INPUTS = tuple(sorted(LANGUAGE_DELTA | {
    'tools/diagnose_bootstrap_editor_fixture.py','tools/diagnose_bootstrap_slot_control.py',
    'rulang/llvm_toolchain.py','rulang/toolchain_environment.py'}))


def validate_language_delta(old, new):
    require(not (set(old)-set(new)), 'language source deletions forbidden')
    changed={key for key in set(old)|set(new) if old.get(key)!=new.get(key)}
    require(changed==LANGUAGE_DELTA, 'unexpected language/runtime/tool source delta')
    require(all(new.get(key)==value for key,value in EMITTER_HASHES.items()), 'pack emitter differs from reviewed candidate')


def validate_common(config):
    app,driver,gate,deps=context(config)
    require(set(config['build_configs'])=={'A','B'},'exactly A/B stage3 configurations required')
    a,b=(config['build_configs'][x] for x in ('A','B'))
    for item in (a,b):
        require(item.get('entry_source')==ENTRY,'measurement only builds exact DLL probe')
        require(Path(item['app_source']['path']).resolve()==app,'wrong editor source')
    for field in ('app_source','app_baseline','tool_paths','tool_sha256'):
        require(a[field]==b[field],'A/B build inputs differ: '+field)
    require(a['ru_source']['commit']==BASE_COMMIT and a['ru_source']['tree']==BASE_TREE, 'A must be exact immutable46c source')
    require(a['ru_source']['commit']!=b['ru_source']['commit'],'A/B compiler versions must be distinct')
    snapshots={}
    for label,item in (('A',a),('B',b)):
        snapshots[label]={key:driver.snapshot(Path(item[key]['path']),item[key]['commit'],item[key]['tree']) for key in ('ru_source','app_source')}
    validate_language_delta(snapshots['A']['ru_source'],snapshots['B']['ru_source'])
    language=Path(b['ru_source']['path']).resolve()
    require(Path(__file__).resolve()==language/'tools/bootstrap_pack_build.py','adapter is not in pinned B source')
    required=MEASUREMENT_INPUTS
    records=list(config['measurement_inputs'])
    require(len({r['path'] for r in records})==len(records),'duplicate measurement inputs')
    require({r['path'] for r in records}=={str(language/name) for name in required}, 'measurement input set differs')
    for name in required:
        require(identity(language/name) in records,'missing frozen measurement input: '+name)
    for record in records:
        path=verify(record).resolve();require(path.is_relative_to(language),'measurement code outside B checkout')
        require(snapshots['B']['ru_source'].get(path.relative_to(language).as_posix())==record['sha256'],'measurement code not tracked')
    dependencies=deps.validate_receipt(Path(config['dependencies_receipt']))
    require(dependencies['app_source']==b['app_source'] and dependencies['source_sha256']==snapshots['B']['app_source'],'dependency source differs')
    driver.validate_toolchain(b['tool_paths'],b['tool_sha256'])
    return app,language,driver,gate,deps,dependencies,snapshots


def artifact_inputs(config):
    # Revalidate the original loader receipt byte pin, never establish a new baseline.
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    loader=importlib.import_module('bootstrap_pack_artifact')
    require(Path(loader.__file__).resolve()==Path(__file__).resolve().parent/'bootstrap_pack_artifact.py','wrong artifact verifier')
    require(set(config['artifact_receipts'])=={'A','B'},'missing original artifact receipts')
    results={}
    for label,row in config['artifact_receipts'].items():
        path=Path(row['path']).resolve()
        require(path.name=='receipt.json' and identity(path)['sha256']==row['sha256'],'original artifact receipt changed')
        receipt=loader.verify_output(path.parent,expected_receipt_sha256=row['sha256'])
        expected=config['build_configs'][label]
        require(receipt['commit']==expected['ru_source']['commit'] and receipt['tree']==expected['ru_source']['tree'],'artifact source pin mismatch')
        require(Path(expected['bootstrap_directory']).resolve()==path.parent and Path(expected['verification']).resolve()==path.parent/'verification.json','artifact directory/config mismatch')
        if label=='A':
            require(receipt['schema']=='ru-pack-old46c-artifact-v1' and receipt['commit']==BASE_COMMIT and receipt['tree']==BASE_TREE,'wrong A reference')
        else:
            require(receipt['schema']=='ru-pack-current-artifact-v1'
                and receipt['commit']==os.environ.get('GITHUB_SHA')
                and str(receipt['run_id'])==os.environ.get('GITHUB_RUN_ID'),'B is not current-run artifact')
        results[label]=receipt
    return results


def worker(config_path, strategy, owned):
    config,config_record=read(config_path)
    app,language,driver,gate,deps,dependencies,snapshots=validate_common(config)
    artifact_inputs(config)
    owned=Path(owned).resolve()
    if strategy in ('A','B'):
        driver.build(config['build_configs'][strategy],owned/strategy)
        validate_probe(owned/strategy/'build-receipt.json',config['build_configs'][strategy],driver,gate)
        return
    require(strategy=='C','unrecognized strategy')
    b,br,proof,pr=validate_probe(owned/'B/build-receipt.json',config['build_configs']['B'],driver,gate)
    sys.path.insert(0,str(language/'tools'));sys.path.insert(0,str(language))
    diag=importlib.import_module('diagnose_bootstrap_editor_fixture')
    from rulang.llvm_toolchain import LLVMToolchain
    from rulang.toolchain_environment import llvm_environment
    require(Path(diag.__file__).resolve()==language/'tools/diagnose_bootstrap_editor_fixture.py','wrong C control generator')
    for module,relative in [('rulang.llvm_toolchain','rulang/llvm_toolchain.py'),('rulang.toolchain_environment','rulang/toolchain_environment.py')]:
        require(Path(sys.modules[module].__file__).resolve()==language/relative,'wrong LLVM control module')
    env=llvm_environment()
    require(not any(env.get(k) for k in ('CL','_CL_','LINK','_LINK_')),'ambient LLVM flags forbidden')
    sdk={k:v for k,v in env.items() if k.upper() in {'PATH','INCLUDE','LIB','LIBPATH','WINDOWSSDKDIR','WINDOWSSDKVERSION','VCTOOLSINSTALLDIR','VCTOOLSVERSION'}}
    require(sdk==b['sdk_crt_environment'],'C control SDK differs')
    croot=owned/'C';croot.mkdir(exist_ok=False)
    generated=croot/'probe.c'
    result={'schema':'ru-python-c-llvm-measurement-build-v1','commands':[],'release_permission':False,'bootstrap_proof':False}
    diag.command([sys.executable,'-I','-B',str(language/'tools/diagnose_bootstrap_editor_fixture.py'),
        '--emit-c',str(language),str(app/ENTRY),str(generated)],croot,env,'emit-c',result['commands'])
    graph,graph_record=read(generated.with_suffix('.sources.json'))
    require(normalized_graph(graph['module_sources'],app,language)==normalized_graph(proof['dependencies'],app,language),'C and B source graph differ')
    result['control_source_graph']=graph
    result['control_graph_receipt']=graph_record
    def revalidate():
        verify(config_record);verify(graph_record);artifact_inputs(config)
        validate_common(config)
        validate_probe(owned/'B/build-receipt.json',config['build_configs']['B'],driver,gate)
    binary=diag.compile_c_via_llvm(LLVMToolchain,generated,croot/'llvm',b,driver,gate,env,result,revalidate)
    result['binary']=binary
    result['source_graph']=normalized_graph(graph['module_sources'],app,language)
    revalidate()
    save(croot/'control-receipt.json',result)


C_ARTIFACT_NAMES = ('program.ll','runtime.c','program.bc','runtime.bc','linked.bc','optimized.bc',
    'standalone.ll','program.o','program.exe','launcher.obj','application.res','application.obj','ru_notepad.exe')


def validate_c_outputs(directory, row, control, graph, b):
    directory=Path(directory).resolve()
    require({r['path'] for r in control['artifacts']}=={str(directory/name) for name in C_ARTIFACT_NAMES}
        and len(control['artifacts'])==len(C_ARTIFACT_NAMES), 'C artifact paths/set incomplete')
    require(row['binary']==identity(directory/'ru_notepad.exe'), 'C final binary outside exact pipeline')
    require((directory/'runtime.c').read_bytes()==verify(graph['generated_c']).read_bytes(), 'C runtime differs from shared generated C')
    program='target datalayout = '+json.dumps(b['data_layout'])+'\ntarget triple = '+json.dumps(b['target_triple'])+'\n'
    require((directory/'program.ll').read_bytes()==program.encode(), 'C empty target module changed')
    for name in ('launcher.obj','application.res'):
        copied=identity(directory/name);original=b['linked_inputs'][name]
        require((copied['sha256'],copied['size'])==(original['sha256'],original['size']), 'C copied GUI input differs')


def validate_c(path, b, driver, gate, app, language):
    row,record=read(path)
    require(row.get('schema')=='ru-python-c-llvm-measurement-build-v1' and row.get('bootstrap_proof') is False
        and row.get('release_permission') is False,'invalid C control identity')
    control=row['llvm_control']
    require(control.get('complete') is True and control.get('bootstrap_proof') is False,'incomplete LLVM C control')
    for name in ('target_triple','data_layout'):require(control[name]==b[name],'C control target differs')
    verify(row['control_graph_receipt'])
    graph,gr=read(row['control_graph_receipt']['path'])
    require(gr==row['control_graph_receipt'] and graph==row['control_source_graph'],'C graph receipt changed')
    require(control['generated_c']==graph['generated_c'],'C generation identity differs')
    verify(graph['generated_c'])
    require(row['source_graph']==normalized_graph(graph['module_sources'],app,language),'C graph changed')
    validate_c_outputs(Path(path).resolve().parent/'llvm',row,control,graph,b)
    artifacts=control['artifacts']
    require(len({r['path'] for r in artifacts})==len(artifacts),'duplicate C artifacts')
    for r in artifacts:verify(r)
    require(row['binary'] in artifacts,'C binary not in complete LLVM evidence')
    driver.verify_gui_pe(verify(row['binary']))
    for name,r in control['reused_gui_inputs'].items():
        require(r==b['linked_inputs'][name],'C GUI glue differs')
        verify(r)
    require(set(control['reused_gui_inputs'])=={'launcher.obj','application.res'},'C reused GUI inputs incomplete')
    require(len(control['linker_selections'])==2,'C explicit link evidence missing')
    directory=Path(path).resolve().parent/'llvm'
    expected_links=[
        [b['tool_paths']['clang'],'--target='+b['target_triple'],str(directory/'program.o'),'-o',str(directory/'program.exe'),
         *driver.explicit_linker_flags(identity(b['tool_paths']['linker']))],
        driver.link_commands(b['tool_paths'],directory/'standalone.ll',Path('unused-fixed-wrapper'),Path('unused-app'),directory,b['target_triple'])[-1]]
    require([v['command'] for v in control['linker_selections']]==expected_links,'C linker commands differ from exact pipeline')
    for selection in control['linker_selections']:
        matching=[c for c in control['commands'] if c['argv']==selection['command']]
        require(len(matching)==1 and matching[0]['returncode']==0,'C linker command not executed')
        driver.verify_linker_selection(selection,b['tool_paths'],expected_command=matching[0]['argv'],triple=b['target_triple'])
    for command in [*row['commands'],*control['commands']]:
        require(command['returncode']==0,'failed C compile command')
        verify(command['stdout']);verify(command['stderr'])
        require(command['environment_sha256']==hashlib.sha256(json.dumps(command['environment'],sort_keys=True).encode()).hexdigest(),'C command environment changed')
    require(control['environment_sha256']==hashlib.sha256(json.dumps(control['environment'],sort_keys=True).encode()).hexdigest(),'C environment changed')
    require(control['environment']==control['commands'][0]['environment'],'C compile environment differs')
    sdk={k:v for k,v in control['environment'].items() if k.upper() in {'PATH','INCLUDE','LIB','LIBPATH','WINDOWSSDKDIR','WINDOWSSDKVERSION','VCTOOLSINSTALLDIR','VCTOOLSVERSION'}}
    require(sdk==b['sdk_crt_environment'],'C recorded SDK differs')
    require(len(row['commands'])==1 and row['commands'][0]['argv']==[sys.executable,'-I','-B',str(language/'tools/diagnose_bootstrap_editor_fixture.py'),'--emit-c',str(language),str(app/ENTRY),str(Path(path).resolve().parent/'probe.c')], 'C frontend command differs')
    for command in [*row['commands'],*control['commands']]:
        require(command['environment']==control['environment'],'C command environment drift')
    for command in control['commands']:
        require(command['argv'][0] in b['tool_paths'].values() and Path(command['cwd']).resolve()==directory, 'C command tool/cwd differs')
        expected_timeout=600 if Path(command['stdout']['path']).name in ('gui-llc.stdout.log','gui-link.stdout.log') else 120
        require(command['timeout_seconds']==expected_timeout,'C LLVM command budget changed')
    verify(record)
    return row,record


def assembled(config_path, owned, budgets):
    config,config_record=read(config_path)
    app,language,driver,gate,deps,dependencies,snapshots=validate_common(config)
    artifacts=artifact_inputs(config)
    a,ar,ap,apr=validate_probe(Path(owned)/'A/build-receipt.json',config['build_configs']['A'],driver,gate)
    b,br,bp,bpr=validate_probe(Path(owned)/'B/build-receipt.json',config['build_configs']['B'],driver,gate)
    for field in ('target_triple','data_layout','tool_paths','tool_sha256','sdk_crt_environment'):
        require(a[field]==b[field],'A/B backend mismatch: '+field)
    ag=normalized_graph(ap['dependencies'],app,config['build_configs']['A']['ru_source']['path'])
    bg=normalized_graph(bp['dependencies'],app,language)
    require(ag==bg,'A/B actual source graph differs')
    c,cr=validate_c(Path(owned)/'C/control-receipt.json',b,driver,gate,app,language)
    require(c['source_graph']==bg,'C actual source graph differs')
    env=deps.dependency_environment(dependencies['tool_paths'],os.environ)
    env.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
    require(set(budgets)=={'A','B','C'},'three aggregate budgets required')
    for label,record in budgets.items():
        require(Path(record['path']).resolve()==Path(owned).resolve()/('budget-'+label)/'budget.json','budget outside own strategy')
        budget,observed=read(verify(record));require(observed==record,'budget changed')
        require(budget['completed'] is True and budget['timed_out'] is False and budget['first_error'] is None
            and budget['cleanup_errors']==[] and budget['tree_empty'] is True and budget['process_reaped'] is True
            and budget['exit_code']==0 and budget['budget_seconds']==600,'failed aggregate worker')
        start,deadline,end=(budget[k] for k in ('started_monotonic','deadline_monotonic','completed_monotonic'))
        require(all(type(v) in (int,float) and math.isfinite(v) for v in (start,deadline,end))
            and deadline==start+600 and start<=end<deadline
            and end<=budget['finished_monotonic'], 'aggregate absolute completion evidence invalid')
        for key in ('stdout','stderr'):verify(budget[key])
    return {'schema':SCHEMA,'status':'prepared-diagnostic-only','release_permission':False,'performance_acceptance':False,
        'config':config_record,'editor_root':str(app),'owned_root':str(Path(owned).resolve()),
        'measurement_inputs':config['measurement_inputs'],'source_inventories':snapshots,
        'sources':[{'repository':key.split('/',1)[0],'path':key.split('/',1)[1],**value} for key,value in sorted(bg.items())],
        'source_graph':bg,'host_python':identity(sys.executable),
        'dependencies_receipt':identity(config['dependencies_receipt']),'dependencies':dependencies,
        'runtime_environment':env,'runtime_environment_sha256':hashlib.sha256(json.dumps(env,sort_keys=True).encode()).hexdigest(),
        'artifact_receipts':config['artifact_receipts'],'artifact_identities':{k:v['identity'] for k,v in artifacts.items()},
        'build_budgets':budgets,'strategies':{
            'A':{'frontend':'old46c-stage3-LLVM','binary':a['final_binary'],'receipt':ar,'proof':apr},
            'B':{'frontend':'current-stage3-LLVM','binary':b['final_binary'],'receipt':br,'proof':bpr},
            'C':{'frontend':'Python-C-via-LLVM-control-not-bootstrap','binary':c['binary'],'receipt':cr}},
        'tool_paths':b['tool_paths'],'tool_sha256':b['tool_sha256'],'sdk_crt_environment':b['sdk_crt_environment']}


def validate_prepared(path):
    prepared,record=read(path)
    validate_prepared_data(prepared)
    verify(record)
    return prepared


def validate_prepared_data(prepared):
    require(prepared.get('schema')==SCHEMA and prepared.get('status')=='prepared-diagnostic-only','wrong prepared manifest')
    verify(prepared['config'])
    actual=assembled(prepared['config']['path'],prepared['owned_root'],prepared['build_budgets'])
    require(prepared==actual,'prepared source/tool/graph/artifact identities changed')
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    classifier=importlib.import_module('diagnose_bootstrap_slot_control')
    require(Path(classifier.__file__).resolve()==Path(__file__).resolve().parent/'diagnose_bootstrap_slot_control.py','wrong oracle validator')
    classifier.validate_progress_graph(prepared['sources'])
    return prepared


def publish_prepared(output, result):
    output=Path(output)
    validate_prepared_data(result)
    save(output,result)
    try:
        validate_prepared(output)
    except Exception:
        output.unlink()  # A failed final check must not leave a successful prepared manifest.
        raise


def prepare(config_path, output):
    require(sys.platform=='win32' and ctypes.sizeof(ctypes.c_void_p)==8,'Windows x64 build required')
    config,record=read(config_path)
    app,language,driver,gate,deps,dependencies,snapshots=validate_common(config)
    artifact_inputs(config)
    sys.path.insert(0,str(language/'tools'))
    diag=importlib.import_module('diagnose_bootstrap_editor_fixture')
    require(Path(diag.__file__).resolve()==language/'tools/diagnose_bootstrap_editor_fixture.py','wrong diagnostic module')
    roots=[app,*[v['ru_source']['path'] for v in config['build_configs'].values()],
        *[v['bootstrap_directory'] for v in config['build_configs'].values()]]
    owned=diag.fresh_owned(config['owned_root'],roots)
    output=Path(output).resolve()
    require(output.is_relative_to(owned) and not output.exists(),'prepared output must be fresh within owned root')
    budgets={}
    environment=dict(os.environ)
    environment.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
    try:
        for strategy in ('A','B','C'):
            verify(record)
            argv=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'--worker',str(Path(config_path).resolve()),
                '--strategy',strategy,'--owned',str(owned)]
            supervise(argv,owned,environment,owned/('budget-'+strategy))
            budgets[strategy]=identity(owned/('budget-'+strategy)/'budget.json')
        result=assembled(config_path,owned,budgets)
        verify(record)
        verify(record)
        publish_prepared(output,result)
        return result
    except Exception as exc:
        save(owned/'preparation-failure.json',{'schema':'ru-bootstrap-pack-build-failure-v1',
            'error':str(exc),'config':record,'budgets':budgets,'release_permission':False})
        raise


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--worker',type=Path);parser.add_argument('--strategy',choices=('A','B','C'));parser.add_argument('--owned',type=Path)
    args=parser.parse_args()
    if args.worker:
        require(args.strategy and args.owned and not args.config and not args.output,'invalid worker arguments')
        worker(args.worker,args.strategy,args.owned)
    else:
        require(args.config and args.output and not args.strategy and not args.owned,'config/output required')
        prepare(args.config,args.output)


if __name__=='__main__':
    main()
