"""Real stage3 + LLVM14 Win64 native/dense interaction, never an emulator.

The first test uses the untouched production runtime/toolchain. The second
adds test-only assertions to that same runtime before production LLVM14 runs;
its evidence explicitly records original/probed runtime hashes. Neither test
uses a Python application frontend or the development LLVM17 adapter.
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
FIXTURE = ROOT / 'tests/fixtures/dense_native'
FORBIDDEN = (
    'rulang.frontend.parse', 'rulang.modules.load_module_graph',
    'rulang.compiler.Compiler.compile', 'rulang.llvm_compiler.LLVMCompiler.compile',
    'rulang.cli.build', 'rulang.native_c.NativeCPlan.__init__',
    'rulang.native_c.NativeCPlan.emit_c', 'rulang.mi_source.MiSourcePlan.__init__',
    'rulang.mi_source.SourceLowerer.__init__', 'rulang.mi_source.read_manifest',
    'rulang.mi_ir.lower', 'rulang.mi_llvm.lower', 'rulang.mi_llvm.Emitter.__init__',
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ru_string(value):
    return "'" + str(value).replace('\\', '\\\\').replace("'", "\\'") + "'"


def probe_runtime(runtime):
    """Assert exact retained-owner balance/no-GC and callback source/depth restore.

    Structural count assertions make runtime changes fail closed, never silently
    omit a probe. This is not used by the production (uninstrumented) test.
    """
    retain = re.compile(r'    Val mi_owner = v_copy\(args\[(\d+)\]\);')
    if len(retain.findall(runtime)) != 3:
        raise AssertionError('expected exactly three dense bridges')
    runtime = retain.sub(lambda m:
        '    size_t test_roots = args[' + m[1] + '].heap->roots;\n'
        '    size_t test_gc = ru_collections;\n' + m[0], runtime)
    drop = '    v_drop(mi_owner);'
    if runtime.count(drop) != 3:
        raise AssertionError('expected exactly three owner release sites')
    runtime = runtime.replace(drop,
        '    if (mi_owner.heap->roots != test_roots+1 || ru_collections != test_gc) abort();\n'
        '    RuHeap *test_owner = mi_owner.heap;\n' + drop + '\n'
        '    if (test_owner->roots != test_roots || ru_collections != test_gc) abort();\n'
        '    fprintf(stderr, "DENSE_OWNER_RESTORED_NO_GC\\n");')
    signature = 'static RuNativeRaw ru_native_callback_dispatch(unsigned slot_index, int signature_id, const RuNativeRaw *raw_args)\n{'
    if runtime.count(signature) != 1:
        raise AssertionError('expected exactly one native callback dispatcher')
    start = runtime.index(signature)
    end = runtime.index('\nstatic Val rn_callback(', start)
    body = runtime[start:end]
    body = body.replace(signature, signature + '\n'
        '    unsigned test_depth = ru_native_callback_depth;\n'
        '    const char *test_source = ru_source;')
    final = '    rn_platform_set_error(entry_error); return answer;\n}'
    if body.count(final) != 1:
        raise AssertionError('expected exactly one callback cleanup return')
    body = body.replace(final,
        '    if (ru_native_callback_depth != test_depth || ru_source != test_source) abort();\n'
        '    fprintf(stderr, "DENSE_CALLBACK_STATE_RESTORED\\n");\n' + final)
    return runtime[:start] + body + runtime[end:]


class BootstrapDenseNativeCallbackTests(unittest.TestCase):
    def setUp(self):
        required = os.environ.get('RU_BOOTSTRAP_DENSE_REQUIRED') == '1'
        windows = (sys.platform == 'win32' and ctypes.sizeof(ctypes.c_void_p) == 8
                   and platform.machine().lower() in ('amd64', 'x86_64'))
        compiler = os.environ.get('RU_BOOTSTRAP_DENSE_COMPILER') or os.environ.get('RU_BOOTSTRAP_DENSE_TEST_COMPILER')
        reason = None
        if not windows:
            reason = 'real Windows x64 required; not native execution evidence'
        elif not compiler or not Path(compiler).is_file():
            reason = 'new bootstrapped stage3 executable required'
        if reason:
            if required:
                self.fail(reason)
            self.skipTest(reason)
        evidence = os.environ.get('RU_BOOTSTRAP_DENSE_EVIDENCE_DIR')
        if required and not evidence:
            self.fail('required execution needs persistent RU_BOOTSTRAP_DENSE_EVIDENCE_DIR')
        if evidence:
            self.assertTrue(Path(evidence).is_absolute(), 'evidence directory must be absolute')
        self.compiler = Path(compiler).resolve()
        if os.environ.get('RU_BOOTSTRAP_DENSE_COMPILER') and os.environ.get('RU_BOOTSTRAP_DENSE_TEST_COMPILER'):
            self.assertEqual(self.compiler, Path(os.environ['RU_BOOTSTRAP_DENSE_TEST_COMPILER']).resolve())
        from rulang.llvm_toolchain import LLVMToolchain
        self.toolchain = LLVMToolchain(os.environ.get('RU_LLVM_CLANG'))
        self.assertRegex(self.toolchain.version, r'clang version 14\.')
        self.assertRegex(self.toolchain.triple, r'^x86_64-pc-windows-msvc(?:[0-9]+(?:\.[0-9]+)*)?$')
        for name in ('main.ru', 'kernel.ru', 'manifest.json', 'bridge.c'):
            self.assertTrue((FIXTURE/name).is_file(), 'missing required owned fixture: '+name)
        if evidence:
            self.directory = Path(evidence).resolve() / self._testMethodName
            self.directory.mkdir(parents=True, exist_ok=False)
        else:
            temp = tempfile.TemporaryDirectory(prefix='dense-native-')
            self.addCleanup(temp.cleanup)
            self.directory = Path(temp.name).resolve()
        for name in ('kernel.ru', 'manifest.json', 'bridge.c'):
            (self.directory/name).write_bytes((FIXTURE/name).read_bytes())
        self.dll = self.directory/'dense_bridge.dll'
        self.fixture_command = self.toolchain.clang + [
            '-std=c99', '-shared', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
            str(self.directory/'bridge.c'), '-o', str(self.dll)]
        self.toolchain.run(self.fixture_command)
        self.assertEqual(self.dll.read_bytes()[:2], b'MZ')
        self.source = self.directory/'main.ru'
        source = (FIXTURE/'main.ru').read_bytes().decode('utf-8')
        self.assertEqual(source.count('@DLL@'), 1)
        self.source.write_bytes(source.replace('@DLL@', ru_string(self.dll)).encode('utf-8'))

    def exercise(self, instrumented):
        from tools.bootstrap import compile_native
        binary = self.directory/'program.exe'
        probe = {}
        if instrumented:
            original_compile = self.toolchain.compile
            def checked_compile(ir, runtime, directory):
                changed = probe_runtime(runtime)
                probe.update(original_runtime_sha256=sha(runtime.encode()),
                             instrumented_runtime_sha256=sha(changed.encode()))
                (self.directory/'runtime.original.c').write_bytes(runtime.encode())
                (self.directory/'runtime.instrumented.c').write_bytes(changed.encode())
                return original_compile(ir, changed, directory)
            self.toolchain.compile = checked_compile
        with ExitStack() as guards:
            for name in FORBIDDEN:
                guards.enter_context(patch(name, side_effect=AssertionError('Python application frontend forbidden: '+name)))
            build = compile_native(self.compiler, self.source, binary, self.toolchain,
                allow_native=True, experimental_mi_manifest=self.directory/'manifest.json',
                keep_frontend=True, emit_llvm=self.directory/'application.ll',
                proof=self.directory/'compile-proof.json', source_roots=(self.directory,))
        self.assertEqual(binary.read_bytes()[:2], b'MZ')
        self.assertEqual(build['compiler']['sha256'], sha(self.compiler.read_bytes()))
        metadata = binary.with_name(binary.name+'.metadata.c').read_text(encoding='utf-8')
        self.assertIn('RU_BOOTSTRAP_NATIVE_V1', metadata)
        self.assertIn('RU_BOOTSTRAP_DENSE_UTF8_V1', metadata)
        self.assertEqual(metadata.count('Val mi_owner = v_copy('), 3)
        # Execute the exact produced PE directly; neither Python nor a compiler
        # can be discovered through the child's PATH, and cwd is empty.
        empty = self.directory/'empty-cwd'
        empty.mkdir()
        env = {k:v for k,v in os.environ.items() if not k.upper().startswith('PYTHON')
               and k.upper() not in ('PATH','VIRTUAL_ENV','CONDA_PREFIX','RU_GC_STATS')}
        windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
        env.update(PATH=os.pathsep.join((str(windows/'System32'), str(windows))),
                   RU_GC_THRESHOLD='1', RU_GC_STATS='1')
        result = subprocess.run([str(binary)],cwd=empty,env=env,capture_output=True,
                                text=True,encoding='utf-8',timeout=45)
        (self.directory/'stdout.txt').write_bytes(result.stdout.encode())
        (self.directory/'stderr.txt').write_bytes(result.stderr.encode())
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 5, result.stdout)
        kernel = (self.directory/'kernel.ru').as_posix()
        self.assertIn(kernel+':2:', lines[0].replace('\\','/'))
        self.assertIn('列=9，status=1', lines[0])
        self.assertIn(kernel+':5:', lines[1].replace('\\','/'))
        self.assertIn('列=8，status=2', lines[1])
        for line, phrase, call_line in zip(lines[2:4], ('密整数参数', '密视图起止范围越界'), (19,20)):
            self.assertIn(phrase, line)
            self.assertIn(self.source.as_posix()+':'+str(call_line)+':', line.replace('\\','/'))
        self.assertEqual(lines[4], 'dense-native-retry-ok')
        self.assertEqual(len(re.findall(r'RU_GC live=0(?:\s|$)', result.stderr)), 1)
        self.assertNotRegex(result.stderr, r'RU_GC live=[1-9]')
        self.assertNotIn('Traceback',result.stderr)
        if instrumented:
            self.assertEqual(build['runtime_sha256'], probe['original_runtime_sha256'])
            self.assertEqual(result.stderr.count('DENSE_OWNER_RESTORED_NO_GC'), 10)
            self.assertEqual(result.stderr.count('DENSE_CALLBACK_STATE_RESTORED'), 9)
            self.assertNotEqual(probe['original_runtime_sha256'],probe['instrumented_runtime_sha256'])
        else:
            self.assertNotIn('DENSE_OWNER_',result.stderr)
            self.assertNotIn('DENSE_CALLBACK_',result.stderr)
        receipt = dict(case=self.id(),compiler_sha256=sha(self.compiler.read_bytes()),
            binary_sha256=sha(binary.read_bytes()),dll_sha256=sha(self.dll.read_bytes()),
            fixture_command=self.fixture_command,toolchain=self.toolchain.version,
            instrumented=instrumented,probe=probe,returncode=result.returncode,
            callback_invocations=9,callback_successes=5,callback_contained_errors=4,
            scope=('Test-only runtime instrumentation; production proof runtime hash identifies pre-probe runtime, '
                   'not the executed instrumented bytes.' if instrumented else
                   'Untouched production LLVMToolchain14 and runtime; actual Win64 execution.'),
            diagnostic_scope='Checked kernel source/line/column exact; scalar/range bridge source+line (existing runtime diagnostic has no column).')
        (self.directory/'acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    def test_callback_checked_errors_recover_production(self):
        self.exercise(False)

    def test_callback_source_depth_and_roots_restore_instrumented(self):
        self.exercise(True)


if __name__ == '__main__':
    unittest.main()
