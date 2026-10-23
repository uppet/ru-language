"""Focused ordinary (not dense) stage3/LLVM14 Windows slot-lifetime gate.

Keep the existing frontend9/native17 gates unchanged. This additional case
runs an untouched production PE, then a separately labelled source/depth probe
PE. A skip is never success when RU_BOOTSTRAP_SLOT_REQUIRED=1.
"""
from contextlib import ExitStack
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'tests/fixtures/slot_reuse_native'
NATIVE_FIXTURE = ROOT/'tests/fixtures/native/c_backend_bridge.c'
FORBIDDEN = ('rulang.frontend.parse', 'rulang.modules.load_module_graph',
             'rulang.compiler.Compiler.compile', 'rulang.llvm_compiler.LLVMCompiler.compile',
             'rulang.native_c.NativeCPlan.__init__', 'rulang.native_c.NativeCPlan.emit_c',
             'rulang.cli.build', 'rulang.mi_source.MiSourcePlan.__init__',
             'rulang.mi_source.SourceLowerer.__init__', 'rulang.mi_source.read_manifest',
             'rulang.mi_ir.lower', 'rulang.mi_llvm.lower', 'rulang.mi_llvm.Emitter.__init__')


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


class SlotReuseNativeCallbackTests(unittest.TestCase):
    def setUp(self):
        required = os.environ.get('RU_BOOTSTRAP_SLOT_REQUIRED') == '1'
        compiler = os.environ.get('RU_BOOTSTRAP_SLOT_COMPILER')
        windows = (sys.platform == 'win32' and ctypes.sizeof(ctypes.c_void_p)==8
                   and platform.machine().lower() in ('amd64','x86_64'))
        if not windows or not compiler or not Path(compiler).is_file():
            reason = 'real Windows x64 and explicit newly bootstrapped stage3 required'
            if required:
                self.fail(reason)
            self.skipTest(reason)
        self.assertTrue(Path(compiler).is_absolute(), 'compiler path must be absolute')
        evidence = os.environ.get('RU_BOOTSTRAP_SLOT_EVIDENCE_DIR')
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
        self.compiler = Path(compiler).resolve()
        for file in [FIXTURE/'main.ru',FIXTURE/'panic_module.ru',NATIVE_FIXTURE]:
            self.assertTrue(file.is_file(),'missing owned fixture: '+str(file))

    def test_parent_temporaries_survive_nested_callback_panic_retry(self):
        from tools.bootstrap import compile_native
        from rulang.llvm_toolchain import LLVMToolchain
        results = []
        for instrumented in (False,True):
            with self.subTest(instrumented=instrumented):
                directory = self.directory/('probe' if instrumented else 'production')
                directory.mkdir()
                toolchain = LLVMToolchain(os.environ.get('RU_LLVM_CLANG'))
                self.assertRegex(toolchain.version,r'clang version 14\.')
                self.assertRegex(toolchain.triple,r'^x86_64-pc-windows-msvc(?:[0-9]+(?:\.[0-9]+)*)?$')
                dll = directory/'owned_bridge.dll'
                cfile = directory/'bridge.c'
                cfile.write_bytes(NATIVE_FIXTURE.read_bytes())
                fixture_command = toolchain.clang+['-std=c99','-shared','-O2','-Wall','-Wextra','-Werror','-pedantic',str(cfile),'-o',str(dll)]
                toolchain.run(fixture_command)
                self.assertEqual(dll.read_bytes()[:2],b'MZ')
                source = directory/'main.ru'
                text = (FIXTURE/'main.ru').read_bytes().decode('utf-8')
                self.assertEqual(text.count("'@DLL@'"),1)
                quoted = "'"+str(dll).replace('\\','\\\\').replace("'","\\'")+"'"
                source.write_bytes(text.replace("'@DLL@'",quoted).encode('utf-8'))
                (directory/'panic_module.ru').write_bytes((FIXTURE/'panic_module.ru').read_bytes())
                binary = directory/'program.exe'
                probe = {}
                if instrumented:
                    original_compile = toolchain.compile
                    def checked_compile(ir,runtime,stage):
                        modified = probe_runtime(runtime)
                        probe.update(original_runtime_sha256=sha(runtime.encode()),instrumented_runtime_sha256=sha(modified.encode()))
                        (directory/'runtime.original.c').write_bytes(runtime.encode())
                        (directory/'runtime.instrumented.c').write_bytes(modified.encode())
                        return original_compile(ir,modified,stage)
                    toolchain.compile = checked_compile
                with ExitStack() as guards:
                    for name in FORBIDDEN:
                        guards.enter_context(patch(name,side_effect=AssertionError('Python application frontend forbidden: '+name)))
                    build = compile_native(self.compiler,source,binary,toolchain,
                        allow_native=True,keep_frontend=True,source_roots=(directory,),
                        emit_llvm=directory/'application.ll',proof=directory/'compile-proof.json')
                self.assertEqual(build['compiler']['sha256'],sha(self.compiler.read_bytes()))
                self.assertEqual(binary.read_bytes()[:2],b'MZ')
                metadata = binary.with_name(binary.name+'.metadata.c').read_bytes()
                self.assertIn(b'RU_BOOTSTRAP_NATIVE_V1',metadata)
                self.assertNotIn(b'RU_BOOTSTRAP_DENSE',metadata)
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
                self.assertEqual(run.stderr.count('RU_GC live=0 '),1,run.stderr)
                self.assertNotRegex(run.stderr,r'RU_GC live=[1-9]')
                if instrumented:
                    self.assertEqual(run.stderr.count('SLOT_CALLBACK_STATE_RESTORED'),12)
                    self.assertEqual(build['runtime_sha256'],probe['original_runtime_sha256'])
                    self.assertNotEqual(probe['original_runtime_sha256'],probe['instrumented_runtime_sha256'])
                else:
                    self.assertNotIn('SLOT_CALLBACK_',run.stderr)
                result = dict(instrumented=instrumented,probe=probe,compiler_sha256=sha(self.compiler.read_bytes()),
                    binary_sha256=sha(binary.read_bytes()),dll_sha256=sha(dll.read_bytes()),fixture_command=fixture_command,
                    toolchain=toolchain.version,callback_invocations=12,outer_panic_fallbacks=2,
                    diagnostic_scope='Cross-module panic exact source/line/column; probe additionally checks source pointer, callback and call depths restored.',
                    proof_scope=('Production build proof runtime hash describes pre-probe runtime; actual instrumented bytes are separately saved/hashed.' if instrumented else 'Untouched production LLVM14 toolchain/runtime.'))
                (directory/'acceptance.json').write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode())
                results.append(result)
        self.assertEqual(len(results),2)
        (self.directory/'acceptance.json').write_bytes((json.dumps({'case':self.id(),'ordinary_only':True,'programs':results},ensure_ascii=False,indent=2)+'\n').encode())


if __name__ == '__main__':
    unittest.main()
