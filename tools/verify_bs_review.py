#!/usr/bin/env python3
"""Isolated review evidence; never changes production inputs or retries samples."""
import argparse, hashlib, importlib, json, math, os, platform, statistics, subprocess, sys, time, traceback, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BS='3eb27e0ebfa97bdf8207f7ba2e2e754ea1b8b273'
APP='2cb3b8c81ba300745b244c51b50d5625430fbe4f'
ADAPTER='6840d99e027221a2772e1b15d8c6be6b0a28a3f5'
BASE='d964ea9f7e27065aa5bbcced8d6c7526a6224dd1'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def git(root,*args): return subprocess.check_output(['git','-C',str(root),*args],text=True,encoding='utf-8').strip()
def require(x,m):
 if not x: raise RuntimeError(m)
def source_identity():
 files=git(ROOT,'ls-tree','-r','--name-only',BS).splitlines()
 result={}
 for name in files:
  p=ROOT/name; data=p.read_bytes(); expected=git(ROOT,'rev-parse',BS+':'+name)
  actual=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
  require(actual==expected,'production source differs: '+name);result[name]=sha(p)
 return result

def core(out):
 sys.path[:0]=[str(ROOT/'tests'),str(ROOT)]
 stage=out/('stage3.exe' if os.name=='nt' else 'stage3')
 require(stage.is_file(),'missing verified stage3')
 os.environ['RU_FRAME_TEST_COMPILER']=str(stage.resolve())
 os.environ['RU_BINDING_TEST_COMPILER']=str(stage.resolve())
 names=['test_llvm_bindings','test_llvm_frames','test_llvm_target_attributes']
 suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(n)) for n in names)
 with (out/'new-suites.log').open('w',encoding='utf-8') as log:
  result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
 report={'tests_run':result.testsRun,'skipped':result.skipped,'failures':[(str(t),s) for t,s in result.failures],
  'errors':[(str(t),s) for t,s in result.errors],'stage3_sha256':sha(stage),'source_sha256':source_identity()}
 save(out/'new-suites.json',report)
 print((out/'new-suites.log').read_text(encoding='utf-8'))
 require(result.testsRun==6 and result.wasSuccessful() and not result.skipped,'six new tests must execute without skips')

def configure(out,editor,mingw):
 sys.path.insert(0,str(ROOT))
 from rulang.llvm_toolchain import LLVMToolchain
 require(git(editor,'rev-parse','HEAD')==APP,'wrong editor helper checkout')
 require(not git(editor,'status','--porcelain'),'dirty editor checkout')
 tc=LLVMToolchain()
 require(len(tc.clang)==1,'unexpected clang command')
 tools={'clang':tc.clang[0],**tc.tools,'python':sys.executable}
 for key,path in [('linker',Path(os.environ['VCToolsInstallDir'])/'bin/Hostx64/x64/link.exe'),('resource',Path(os.environ['WindowsSdkDir'])/'bin'/os.environ['WindowsSDKVersion'].strip('\\/')/'x64/rc.exe')]:tools[key]=str(path)
 native={k:str((mingw/v).resolve()) for k,v in {'cc':'gcc.exe','cxx':'g++.exe','make':'mingw32-make.exe','windres':'windres.exe','ar':'ar.exe','ranlib':'ranlib.exe','objdump':'objdump.exe'}.items()}
 lock={'source_sha256':source_identity(),'tool_paths':tools,'tool_sha256':{k:sha(v) for k,v in tools.items()},'platform':platform.platform(),'processor':platform.processor(),'llvm':tc.version,'target':tc.function_target}
 save(out/'tool-lock.json',lock)
 config={'app_source':{'path':str(editor),'commit':APP,'tree':git(editor,'rev-parse','HEAD^{tree}')},'app_baseline':{'commit':BASE,'tree':'2522d03114c808480e42911be850b75e0ae14206'},'mingw_tool_paths':native,'mingw_tool_sha256':{k:sha(v) for k,v in native.items()}}
 save(out/'dependencies-config.json',config)
 with open(os.environ['GITHUB_ENV'],'a',encoding='utf-8') as stream:stream.write('RU_LLVM_CLANG='+tools['clang']+'\n')

def build_proof(folder):
 candidate=folder/'compiler'; application=folder/'application'
 def original(name):return subprocess.check_output(['git','-C',str(ROOT),'show',ADAPTER+':'+name])
 changed={'bootstrap/compiler.ru','rulang/llvm_compiler.py','rulang/llvm_runtime.h','rulang/llvm_toolchain.py'}
 # git archive preserves bytes; the adapter emitter splice intentionally uses text newline normalization.
 for name in git(ROOT,'ls-tree','-r','--name-only',ADAPTER).splitlines():
  if name not in changed:require((candidate/name).read_bytes()==original(name),'unplanned adapter change: '+name)
 for name in changed-{'bootstrap/compiler.ru'}:require((candidate/name).read_bytes()==(ROOT/name).read_bytes(),'ordinary compiler mismatch: '+name)
 old=original('bootstrap/compiler.ru').decode().replace('\r\n','\n'); current=(ROOT/'bootstrap/compiler.ru').read_text(encoding='utf-8')
 start,end='算 新号 全 前:','算 读文 文件:'
 require(old.count(start)==old.count(end)==current.count(start)==current.count(end)==1,'ambiguous emitter markers')
 wanted=old[:old.index(start)]+current[current.index(start):current.index(end)]+old[old.index(end):]
 abi=next(l for l in current.splitlines() if l.startswith('LLVM接口 取 '))
 wanted='\n'.join(abi if l.startswith('LLVM接口 取 ') else l for l in wanted.splitlines())+'\n'
 require((candidate/'bootstrap/compiler.ru').read_text(encoding='utf-8')==wanted,'emitter splice mismatch')
 proof=json.loads((folder/'bootstrap/proof.json').read_text(encoding='utf-8'))
 build=json.loads((folder/'bootstrap/build.json').read_text(encoding='utf-8'))
 require(build==proof and proof['schema']=='ru-bootstrap-build-proof-v1','build proof mismatch')
 require(proof['native_protocol'] is not None and Path(proof['source']).resolve()==(application/'tests/ru_syntax_native.ru').resolve(),'wrong native opt-in fixture')
 require(Path(proof['compiler']['path']).resolve()==(folder/'stages/stage3.exe').resolve(),'not freshly bootstrapped stage3')
 identities=[proof['compiler'],*proof['dependencies'],*proof['source_inventory'],*proof['host_inputs'],*proof['artifacts'].values()]
 for record in identities:require(sha(record['path'])==record['sha256'],'proof artifact or source changed: '+record['path'])
 require(proof['binary_sha256']==sha(folder/'bootstrap/program.exe'),'binary proof mismatch')
 require(proof['source_ir_sha256']==sha(folder/'bootstrap/program.exe.frontend.ll'),'frontend proof mismatch')
 return proof

def measure(out):
 sys.path.insert(0,str(ROOT))
 from tools.benchmark_bootstrap_syntax import values
 inputs=json.loads((out/'comparison/inputs.json').read_text(encoding='utf-8'))
 lock=json.loads((out/'tool-lock.json').read_text(encoding='utf-8'))
 folder=out/'comparison'; dest=out/'measurement';dest.mkdir(exist_ok=False)
 def verify():
  require(source_identity()==lock['source_sha256'],'review source changed')
  for name,h in inputs['files'].items():require(sha(folder/name)==h,'input changed: '+name)
  for name,p in lock['tool_paths'].items():require(sha(p)==lock['tool_sha256'][name],'tool changed: '+name)
  sys.path.insert(0,str(Path(args.editor)/'tools'))
  from prepare_bootstrap_dependencies import validate_receipt
  validate_receipt(out/'dependencies/dependencies-receipt.json')
 proof=build_proof(folder);save(dest/'build-proof-checked.json',proof)
 verify();save(dest/'before.json',{'inputs':inputs,'tools':lock})
 env=dict(os.environ)
 for k in ('RU_GC_THRESHOLD','RU_GC_STATS'):env.pop(k,None)
 records=[]; attempts=[]; problem=None
 try:
  for round_ in range(6):
   pair={}; order=('c-llvm','bootstrap') if round_%2==0 else ('bootstrap','c-llvm')
   for arm in order:
    exe=folder/arm/'program.exe'; stem=dest/f'{round_+1}-{arm}';start=time.perf_counter();row={'round':round_+1,'arm':arm,'binary_sha256':sha(exe),'timeout':False,'status':'started'}
    attempts.append(row);save(dest/'attempts.json',attempts)
    try:
     p=subprocess.run([str(exe)],cwd=exe.parent,capture_output=True,env=env,timeout=180)
     stdout,stderr=p.stdout,p.stderr; row['returncode']=p.returncode
    except subprocess.TimeoutExpired as e:
     stdout,stderr=e.stdout or b'',e.stderr or b'';row.update(timeout=True,returncode=None)
    except OSError as e:
     stdout,stderr=b'',str(e).encode('utf-8');row.update(returncode=None,error=repr(e))
    row['status']='finished'
    row['wall_ms']=(time.perf_counter()-start)*1000
    stem.with_suffix('.stdout').write_bytes(stdout);stem.with_suffix('.stderr').write_bytes(stderr)
    row.update(stdout_sha256=sha(stem.with_suffix('.stdout')),stderr_sha256=sha(stem.with_suffix('.stderr')))
    save(dest/'attempts.json',attempts)
    require(not row['timeout'] and row['returncode']==0,'failed process; evidence retained')
    text=stdout.decode('utf-8');lines=text.splitlines()
    require(sum(l.startswith('PASS: ') for l in lines)==149 and lines.count('TOTAL PASS: 149')==1 and not any(l.startswith('FAIL:') for l in lines),'149 complete PASS lines required')
    metrics=[]
    for line in lines:
     if line.startswith(('PERF_RU ','RU_GUI_SYNC ')):
      metric={'kind':line.split()[0]};metric.update({k:float(v) for k,v in (s.split('=') for s in line.split()[1:])});metrics.append(metric)
    row['metrics']=metrics;require(all(math.isfinite(v) and v>0 for v in values(row)),'invalid elapsed metric');pair[arm]=row;save(dest/'attempts.json',attempts)
    print(f'round {round_+1} {arm}: {row["wall_ms"]:.3f} ms',flush=True)
   records.append(pair);save(dest/'raw.json',records)
 except BaseException:
  problem=traceback.format_exc();save(dest/'failure.json',{'error':problem});raise
 finally:
  try:verify();build_proof(folder);save(dest/'after.json',{'verified':True,'attempt_count':len(attempts),'error':problem})
  except BaseException:save(dest/'after.json',{'verified':False,'error':traceback.format_exc()});raise
 summary=[]
 for i,name in enumerate(('100KB initial','100KB edit','1MB initial','1MB edit','Unicode sync','total')):
  c=[values(p['c-llvm'])[i] for p in records];b=[values(p['bootstrap'])[i] for p in records];ratios=[y/x for x,y in zip(c,b)]
  summary.append({'case':name,'c_ms':c,'bootstrap_ms':b,'ratios':ratios,'paired_ratio_median':statistics.median(ratios),'all_six_faster':all(r<1 for r in ratios)})
 save(dest/'summary.json',summary)
 # Preserve a complete honest measurement even when the author's stronger claim fails.
 require(all(x['all_six_faster'] for x in summary),'reported every-pair speedup not reproduced; do not rerun to select green')

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('action',choices=['core','configure','measure']);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--editor',type=Path);parser.add_argument('--mingw',type=Path);args=parser.parse_args();args.out=args.out.resolve();args.out.mkdir(parents=True,exist_ok=True)
 if args.editor:args.editor=args.editor.resolve()
 try:
  if args.action=='core':core(args.out)
  elif args.action=='configure':configure(args.out,args.editor,args.mingw)
  else:measure(args.out)
 except BaseException:
  save(args.out/(args.action+'-failure.json'),{'error':traceback.format_exc()});raise
