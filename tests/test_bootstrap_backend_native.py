"""Python frontend -> production LLVM14 ordinary native lifetime acceptance.

This is NOT pureRu stage3 FFI. Mainline's existing scalar-Mi manifest opt-in is
required for LLVM native capability: a test-only unused identity function is
selected, while all callback/lifetime bodies remain ordinary LLVM. No guard
change, bootstrap.compile_native, dense helper, or borrow_utf8 is involved.
One required case runs two PEs: untouched production and separately labelled
source/depth probe. Skips cannot satisfy RU_BOOTSTRAP_BACKEND_REQUIRED=1.
"""
from contextlib import ExitStack
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'tests/fixtures/backend_native'
NATIVE_FIXTURE = ROOT/'tests/fixtures/native/c_backend_bridge.c'



def sha(data):
    return hashlib.sha256(data).hexdigest()


def probe_runtime(runtime):
    signature = 'static RuNativeRaw ru_native_callback_dispatch(unsigned slot_index, int signature_id, const RuNativeRaw *raw_args)\n{'
    if runtime.count(signature) != 1:
        raise AssertionError('callback dispatcher anchor changed')
    start = runtime.index(signature)
    end = runtime.index('\nstatic Val rn_callback(',start)
    body = runtime[start:end]
    body = body.replace(signature, signature+'\n'
        '    const char *slot_test_source = ru_source;\n'
        '    unsigned slot_test_depth = ru_native_callback_depth;\n'
        '    int slot_test_call_depth = ru_call_depth;')
    final = '    rn_platform_set_error(entry_error); return answer;\n}'
    if body.count(final) != 1:
        raise AssertionError('callback cleanup anchor changed')
    body = body.replace(final,
        '    if (ru_source != slot_test_source || ru_native_callback_depth != slot_test_depth || ru_call_depth != slot_test_call_depth) abort();\n'
        '    fprintf(stderr, "SLOT_CALLBACK_STATE_RESTORED\\n");\n'+final)
    return runtime[:start]+body+runtime[end:]


class BackendNativeCallbackTests(unittest.TestCase):
    def setUp(self):
        required = os.environ.get('RU_BOOTSTRAP_BACKEND_REQUIRED') == '1'
        windows = (sys.platform == 'win32' and ctypes.sizeof(ctypes.c_void_p)==8
                   and platform.machine().lower() in ('amd64','x86_64'))
        if not windows:
            reason = 'real Windows x64 required for PythonLLVM native acceptance'
            if required:
                self.fail(reason)
            self.skipTest(reason)
        evidence = os.environ.get('RU_BOOTSTRAP_BACKEND_EVIDENCE_DIR')
        if required and not evidence:
            self.fail('required execution needs persistent evidence directory')
        if evidence:
            self.assertTrue(Path(evidence).is_absolute(), 'evidence path must be absolute')
            self.directory = Path(evidence).resolve()/self._testMethodName
            self.directory.mkdir(parents=True,exist_ok=False)
        else:
            temp = tempfile.TemporaryDirectory(prefix='slot-native-')
            self.addCleanup(temp.cleanup)
            self.directory = Path(temp.name).resolve()
        for file in [FIXTURE/'main.ru',FIXTURE/'panic_module.ru',NATIVE_FIXTURE]:
            self.assertTrue(file.is_file(),'missing owned fixture: '+str(file))
        from rulang.frontend import RuError
        from rulang.llvm_toolchain import LLVMToolchain
        try:
            self.fixture_toolchain = LLVMToolchain(os.environ.get('RU_LLVM_CLANG'))
        except RuError as error:
            if required:
                self.fail('required production LLVM14 toolchain unavailable: '+str(error))
            self.skipTest('production LLVM14 toolchain unavailable; not execution evidence: '+str(error))

    def test_parent_temporaries_survive_nested_callback_panic_retry(self):
        from rulang.cli import build
        from rulang.frontend import parse
        from rulang.mi_ir import EFFECTS
        from rulang.llvm_compiler import LLVMCompiler
        from rulang.llvm_toolchain import LLVMToolchain
        fixture_toolchain = self.fixture_toolchain
        self.assertRegex(fixture_toolchain.version,r'clang version 14\.')
        dll = self.directory/'owned_bridge.dll'
        cfile = self.directory/'bridge.c'
        cfile.write_bytes(NATIVE_FIXTURE.read_bytes())
        fixture_command = fixture_toolchain.clang+['-std=c99','-shared','-O2','-Wall','-Wextra','-Werror','-pedantic',str(cfile),'-o',str(dll)]
        fixture_toolchain.run(fixture_command)
        self.assertEqual(dll.read_bytes()[:2],b'MZ')
        results = []
        for instrumented in (False,True):
            with self.subTest(instrumented=instrumented):
                directory = self.directory/('probe' if instrumented else 'production')
                directory.mkdir()
                toolchain = LLVMToolchain(os.environ.get('RU_LLVM_CLANG'))
                self.assertRegex(toolchain.version,r'clang version 14\.')
                self.assertRegex(toolchain.triple,r'^x86_64-pc-windows-msvc(?:[0-9]+(?:\.[0-9]+)*)?$')
                source = directory/'main.ru'
                text = (FIXTURE/'main.ru').read_bytes().decode('utf-8')
                self.assertEqual(text.count("'@DLL@'"),1)
                quoted = "'"+str(dll).replace('\\','\\\\').replace("'","\\'")+"'"
                # Existing mainline test-only scalar opt-in, not new capability.
                text = text.replace("'@DLL@'",quoted)+'\n算 后端许可值 值: 得 值. 法\n'
                source.write_bytes(text.encode('utf-8'))
                manifest = directory/'scalar-permission.json'
                manifest.write_bytes((json.dumps({'version':1,'functions':[{
                    'module':'main.ru','function':'后端许可值','params':{'值':'u32'},
                    'result':'u32','locals':{},'effects':EFFECTS}]},ensure_ascii=False)+'\n').encode())
                (directory/'panic_module.ru').write_bytes((FIXTURE/'panic_module.ru').read_bytes())
                binary = directory/'program.exe'
                probe = {}
                selection = {}
                original_runtime = LLVMCompiler.runtime_c
                def capture_runtime(instance):
                    records = instance.mi_plan.records
                    self.assertEqual(len(records),1)
                    self.assertEqual(records[0]['function'],'后端许可值')
                    self.assertEqual(records[0]['module'],str(source.resolve()))
                    self.assertEqual(records[0]['input_contracts'],{'值':'u32'})
                    ordinary = {}
                    names = {'造','合','内处理','内调','外处理','触','词'}
                    for module, function in instance.all_functions:
                        name = function.data['name']
                        if module == str(source.resolve()) and name in names:
                            self.assertNotIn(id(function),instance.mi_plan.functions)
                            ordinary[name] = instance.function_ids[id(function)]+'_llvm'
                    self.assertEqual(set(ordinary),names)
                    selection.update(scalar_function='后端许可值',ordinary_functions=ordinary)
                    return original_runtime(instance)
                original_compile = LLVMToolchain.compile
                def checked_compile(instance,ir,runtime,stage,full_runtime=False):
                    self.assertTrue(selection, 'runtime observation must precede tools')
                    for symbol in selection['ordinary_functions'].values():
                        match = re.search(r'define void @'+re.escape(symbol)+r'\(i8\* %global.*?\n\}',ir,re.S)
                        self.assertIsNotNone(match,'ordinary LLVM body missing: '+symbol)
                        self.assertIn('@rul_frame_new(',match[0])
                    self.assertEqual(len(re.findall(r'^define void @ru_mi_kernel_',ir,re.M)),1)
                    modified = probe_runtime(runtime) if instrumented else runtime
                    probe.update(original_runtime_sha256=sha(runtime.encode()),executed_runtime_sha256=sha(modified.encode()),
                                 frontend_ir_sha256=sha(ir.encode()))
                    (directory/'frontend.ll').write_bytes(ir.encode())
                    (directory/'runtime.original.c').write_bytes(runtime.encode())
                    (directory/'runtime.executed.c').write_bytes(modified.encode())
                    return original_compile(instance,ir,modified,stage,full_runtime=full_runtime)
                # Python parsing/planning is intentional here; prohibit only
                # accidental full C application code generation as a fallback.
                with ExitStack() as guards:
                    guards.enter_context(patch('rulang.compiler.Compiler.compile',side_effect=AssertionError('C application codegen fallback')))
                    guards.enter_context(patch.object(LLVMCompiler,'runtime_c',capture_runtime))
                    guards.enter_context(patch.object(LLVMToolchain,'compile',checked_compile))
                    result_binary, version = build(parse(text),source,binary,target='llvm',
                        llvm_clang=os.environ.get('RU_LLVM_CLANG'),allow_native=True,
                        mi_manifest=manifest,emit_llvm=directory/'application.ll')
                self.assertEqual(Path(result_binary),binary)
                self.assertEqual(version,toolchain.version)
                self.assertEqual(binary.read_bytes()[:2],b'MZ')
                env = {k:v for k,v in os.environ.items() if not k.upper().startswith('PYTHON')
                       and k.upper() not in ('PATH','VIRTUAL_ENV','CONDA_PREFIX','RU_GC_STATS')}
                windows = Path(os.environ.get('SystemRoot',r'C:\Windows'))
                env.update(PATH=os.pathsep.join([str(windows/'System32'),str(windows)]),RU_GC_THRESHOLD='1',RU_GC_STATS='1')
                empty = directory/'empty-cwd';empty.mkdir()
                run = subprocess.run([str(binary)],cwd=empty,env=env,capture_output=True,text=True,encoding='utf-8',timeout=45)
                (directory/'stdout.txt').write_bytes(run.stdout.encode())
                (directory/'stderr.txt').write_bytes(run.stderr.encode())
                self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                lines = run.stdout.splitlines()
                self.assertEqual(len(lines),3,run.stdout)
                for diagnostic in lines[:2]:
                    self.assertIn((directory/'panic_module.ru').as_posix()+':2:5:',diagnostic.replace('\\','/'))
                    self.assertIn('slot-panic',diagnostic)
                self.assertEqual(lines[2],'slot-native-ok')
                gc_lines = [line for line in run.stderr.splitlines() if 'RU_GC' in line]
                self.assertEqual(len(gc_lines),1,run.stderr)
                self.assertRegex(gc_lines[0],r'^RU_GC live=0 freed=[0-9]+ collections=[0-9]+$')
                if instrumented:
                    self.assertEqual(run.stderr.count('SLOT_CALLBACK_STATE_RESTORED'),12)
                    self.assertNotEqual(probe['original_runtime_sha256'],probe['executed_runtime_sha256'])
                else:
                    self.assertNotIn('SLOT_CALLBACK_',run.stderr)
                    self.assertEqual(probe['original_runtime_sha256'],probe['executed_runtime_sha256'])
                result = dict(instrumented=instrumented,probe=probe,selection=selection,frontend='Python LLVMCompiler, not pureRu stage3',
                    llvm_compiler_sha256=sha((ROOT/'rulang/llvm_compiler.py').read_bytes()),
                    binary_sha256=sha(binary.read_bytes()),dll_sha256=sha(dll.read_bytes()),fixture_command=fixture_command,
                    toolchain=toolchain.version,callback_invocations=12,outer_panic_fallbacks=2,
                    manifest_sha256=sha(manifest.read_bytes()),standalone_ir_sha256=sha((directory/'application.ll').read_bytes()),
                    inputs={str(p.relative_to(directory)):sha(p.read_bytes()) for p in (source, directory/'panic_module.ru',manifest)},
                    permission='Existing scalar Mi opt-in only; unused identity; ordinary callback bodies; no dense performance claim',
                    diagnostic_scope='Cross-module panic exact source/line/column; probe additionally checks source pointer, callback and call depths restored.',
                    proof_scope=('Test-only source/depth runtime probe; both original and executed runtime bytes separately saved/hashed.' if instrumented else 'Untouched production LLVM14 toolchain/runtime.'))
                (directory/'acceptance.json').write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode())
                results.append(result)
        self.assertEqual(len(results),2)
        (self.directory/'acceptance.json').write_bytes((json.dumps({'case':self.id(),'callback_bodies_ordinary':True,'python_llvm_route':True,'programs':results},ensure_ascii=False,indent=2)+'\n').encode())


if __name__ == '__main__':
    unittest.main()
