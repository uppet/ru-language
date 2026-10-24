#!/usr/bin/env python3
"""One controlled Windows callback diagnostic per arm; not an acceptance pass."""
import argparse,hashlib,json,os,re,shutil,subprocess,sys,time,traceback,types,unittest
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--repository',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--arm',choices=['baseline','bs','bs-no-target','bs-uwtable'],required=True);a=p.parse_args()
root=a.repository.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
expected='0b7adcb14f5039ea7ffa9892982877d0e83bc4bc' if a.arm=='baseline' else '3eb27e0ebfa97bdf8207f7ba2e2e754ea1b8b273'
actual=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
if actual!=expected:raise RuntimeError('wrong checkout')
sys.path[:0]=[str(root),str(root/'tests')]
report={'diagnostic_only':True,'arm':a.arm,'source_commit':actual,'processes':[],'interventions':[]}
def save(): (out/'diagnostic.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
save()
try:
 import test_mi_utf8 as target
 support=target.support
 if target.TOOLCHAIN is None:raise RuntimeError('actual LLVM14 required')
 report['llvm_version']=target.TOOLCHAIN.version
 report['toolchain']={'clang':target.TOOLCHAIN.clang,'tools':target.TOOLCHAIN.tools}
 report['tool_hashes']={p:digest(p) for p in [*target.TOOLCHAIN.clang,*target.TOOLCHAIN.tools.values()]}
 if a.arm=='bs-no-target':
  target.TOOLCHAIN.target_program=lambda program:program
  report['interventions'].append('LLVMToolchain instance target_program identity only; production files unchanged')
 if a.arm=='bs-uwtable':
  original_target=target.TOOLCHAIN.target_program
  def with_unwind(program):
   aligned=original_target(program)
   changed,count=re.subn(r'^(define [^\n]+) \{$',r'\1 uwtable {',aligned,flags=re.M)
   if not count:raise RuntimeError('no direct definitions to annotate')
   report['uwtable_definition_count']=count
   return changed
  target.TOOLCHAIN.target_program=with_unwind
  report['interventions'].append('add uwtable to direct definitions after unchanged bs target_program; diagnostic only')
 class OwnedTemporary:
  def __init__(self):self.name=str(out/'fixture');Path(self.name).mkdir(exist_ok=False)
  def cleanup(self):pass
 support.tempfile=types.SimpleNamespace(TemporaryDirectory=OwnedTemporary)
 def run(command,**kwargs):
  index=len(report['processes']);record={'command':list(map(str,command)),'status':'started'}
  executable=shutil.which(str(command[0])) or str(command[0])
  record['executable']={'path':str(Path(executable).resolve()),'sha256':digest(executable)}
  report['processes'].append(record);save();started=time.monotonic()
  stdout=stderr=b''
  try:
   result=subprocess.run(command,capture_output=True,timeout=120,**kwargs);stdout,stderr=result.stdout,result.stderr
   record.update(returncode=result.returncode,returncode_hex=f'0x{result.returncode & 0xffffffff:08X}',status='completed')
  except subprocess.TimeoutExpired as e:
   stdout,stderr=e.stdout or b'',e.stderr or b'';record.update(status='timeout',error=repr(e));raise
  except OSError as e:record.update(status='spawn_error',error=repr(e));raise
  finally:
   record['seconds']=time.monotonic()-started
   (out/f'process-{index}.stdout').write_bytes(stdout);(out/f'process-{index}.stderr').write_bytes(stderr);save()
  result.stdout=stdout.decode('utf-8',errors='replace');result.stderr=stderr.decode('utf-8',errors='replace')
  if result.returncode:raise AssertionError(f'exit={result.returncode} hex={record["returncode_hex"]}\n'+result.stdout+result.stderr)
  return result
 support.run=run
 case=target.UTF8LLVM('test_real_callback_nested_entry_failure_then_retry')
 with (out/'unittest.log').open('w',encoding='utf-8') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.TestSuite([case]))
 report.update(tests_run=result.testsRun,skipped=result.skipped,failures=[(str(t),s) for t,s in result.failures],errors=[(str(t),s) for t,s in result.errors],test_passed=result.wasSuccessful() and not result.skipped)
 if result.testsRun!=1 or result.skipped:raise RuntimeError('single diagnostic did not execute')
except BaseException:
 report['driver_error']=traceback.format_exc();raise
finally:
 report['files']={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='diagnostic.json'};save()
 print(json.dumps(report,indent=2))
