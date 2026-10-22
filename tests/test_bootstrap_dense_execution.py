"""Opt-in development ONLY: C-seeded frontend + LLVM17 object + GCC runtime.

This deliberately does not implement/replace the production LLVM14 toolchain.
No result here is LLVM14 stage1/2/3, fixed-point or Windows release evidence.
"""
import ctypes as C
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from tools import bootstrap
from tools.bootstrap_dense_protocol import EFFECTS

COMPILER = os.environ.get('RU_BOOTSTRAP_DENSE_TEST_COMPILER')
LIBLLVM = '/usr/lib/x86_64-linux-gnu/libLLVM-17.so'


class DevelopmentLLVM17:
    triple = 'x86_64-pc-linux-gnu'
    data_layout = 'e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128'
    version = 'DEVELOPMENT ONLY: LLVM17 object + GCC; standalone artifact is frontend-only, NOT release evidence'
    def __init__(self):
        self.lib = C.CDLL(LIBLLVM)
        def api(name, result, *args):
            f = getattr(self.lib, name)
            f.restype, f.argtypes = result, args
            return f
        p, pp = C.c_void_p, C.POINTER(C.c_void_p)
        text, err = C.c_char_p, C.POINTER(C.c_char_p)
        for name in ('LLVMInitializeX86TargetInfo','LLVMInitializeX86Target','LLVMInitializeX86TargetMC','LLVMInitializeX86AsmPrinter'):
            api(name, None)()
        self.context = api('LLVMContextCreate',p)()
        self.buffer = api('LLVMCreateMemoryBufferWithMemoryRangeCopy',p,text,C.c_size_t,text)
        self.parse = api('LLVMParseIRInContext',C.c_int,p,p,pp,err)
        self.verify = api('LLVMVerifyModule',C.c_int,p,C.c_int,err)
        self.target = api('LLVMGetTargetFromTriple',C.c_int,text,pp,err)
        self.machine = api('LLVMCreateTargetMachine',p,p,text,text,text,C.c_int,C.c_int,C.c_int)
        self.emit = api('LLVMTargetMachineEmitToFile',C.c_int,p,p,text,C.c_int,err)
        self.dispose_module = api('LLVMDisposeModule',None,p)
        self.dispose_machine = api('LLVMDisposeTargetMachine',None,p)

    def compile(self, ir, runtime, stage):
        self.runtime = runtime
        module, target, error = C.c_void_p(), C.c_void_p(), C.c_char_p()
        data = ir.encode()
        assert self.parse(self.context, self.buffer(data,len(data),b'development'), C.byref(module), C.byref(error)) == 0, error.value
        try:
            assert self.verify(module,2,C.byref(error)) == 0, error.value
            assert self.target(self.triple.encode(),C.byref(target),C.byref(error)) == 0, error.value
            machine = self.machine(target,self.triple.encode(),b'generic',b'',2,2,0)
            obj = stage/'development-llvm17.o'
            try:
                assert self.emit(machine,module,str(obj).encode(),1,C.byref(error)) == 0, error.value
            finally:
                self.dispose_machine(machine)
        finally:
            self.dispose_module(module)
        cfile, binary = stage/'development-runtime.c', stage/'development-program'
        if getattr(self, 'instrument_borrow', False):
            # Test-only probes, never part of fixed runtime or released metadata.
            runtime = re.sub(r'(    Val mi_owner = v_copy\(args\[(\d+)\]\);)',
                lambda m: ('    size_t dev_roots = args['+m[2]+'].heap->roots;\n'
                           '    size_t dev_gc = ru_collections;\n'+m[1]), runtime)
            runtime = runtime.replace('    v_drop(mi_owner);',
                '    if (mi_owner.heap->roots != dev_roots+1 || ru_collections != dev_gc) abort();\n'
                '    v_drop(mi_owner);\n'
                '    if (mi_owner.heap->roots != dev_roots || ru_collections != dev_gc) abort();\n'
                '    fprintf(stderr, "DEV_BORROW_BALANCED_NO_GC\\n");')
        cfile.write_text(runtime, encoding='utf-8')
        command = ['cc','-std=c99','-O2',str(cfile),str(obj),'-lm','-o',str(binary)]
        result = subprocess.run(command,capture_output=True,text=True, encoding='utf-8')
        if result.returncode:
            raise RuntimeError(result.stderr)
        frontend = stage/'development-frontend-only.ll'
        frontend.write_text(ir, encoding='utf-8')
        return binary, frontend


@unittest.skipUnless(COMPILER and Path(LIBLLVM).is_file() and shutil.which('cc'),
                     'explicit development frontend + LLVM17 library + cc required')
class DenseExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dense-execute-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source, self.kernel, self.manifest, self.binary = [self.root/name for name in ('main.ru','kernel.ru','manifest.json','program')]
        self.toolchain = DevelopmentLLVM17()

    def build(self, source, kernel='算 工 字节 始 终: 得 终-始. 法', params=None, ranges=True, result_type="u32"):
        self.source.write_text(source, encoding='utf-8')
        self.kernel.write_text(kernel, encoding='utf-8')
        spec = {'module':'kernel.ru','function':'工',
                'params': params or {'字节':'borrow_ro_utf8','始':'u32','终':'u32'},
                'result':result_type,'effects':EFFECTS}
        if ranges: spec['ranges'] = [{'view':'字节','begin':'始','end':'终'}]
        self.manifest.write_text(json.dumps({'version':1,'functions':[spec]},ensure_ascii=False),encoding='utf-8')
        with ExitStack() as stack:
            for name in ('rulang.frontend.parse','rulang.modules.load_module_graph',
                         'rulang.compiler.Compiler.compile','rulang.llvm_compiler.LLVMCompiler.compile',
                         'rulang.cli.build','rulang.native_c.NativeCPlan.__init__','rulang.native_c.NativeCPlan.emit_c',
                         'rulang.mi_source.MiSourcePlan.__init__',
                         'rulang.mi_source.SourceLowerer.__init__','rulang.mi_ir.lower','rulang.mi_llvm.lower'):
                stack.enter_context(patch(name,side_effect=AssertionError('Python source hook forbidden: '+name)))
            proof = bootstrap.compile_native(COMPILER,self.source,self.binary,self.toolchain,
                                             experimental_mi_manifest=self.manifest,keep_frontend=True)
        self.assertIsNone(proof['native_protocol'])
        self.assertIn('DEVELOPMENT ONLY',proof['toolchain']['version'])
        return proof

    def run_binary(self):
        return subprocess.run([str(self.binary)],capture_output=True,text=True,
                              env=dict(os.environ,RU_GC_THRESHOLD='1',RU_GC_STATS='1'),timeout=30, encoding='utf-8')

    def test_utf8_empty_byte_offsets_and_gc_zero(self):
        self.build("核 取 外言 'kernel.ru'. 显 核 其 工 '中文😀' 0 10. 显 核 其 工 '' 0 0. 显 核 其 工 '中文😀' 1 4.")
        result = self.run_binary()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'10\n0\n3\n')
        self.assertIn('RU_GC live=0',result.stderr)
        ir = self.binary.with_name(self.binary.name+'.frontend.ll').read_text(encoding='utf-8')
        bodies = re.findall(r'define void @boot_dense_[^{]+\{(.*?)\n\}',ir,re.S)
        self.assertEqual(len(bodies),1)
        self.assertNotRegex(bodies[0],r'\b(call|invoke)\b')
        metadata = self.binary.with_name(self.binary.name+'.metadata.c').read_text(encoding='utf-8')
        self.assertLess(metadata.index('Val mi_owner = v_copy('),metadata.index('v_drop(mi_owner);'))
        self.assertLess(metadata.index('v_drop(mi_owner);'),metadata.index('if (mi_out[0] != 0)'))

    def test_instrumented_borrow_root_restored_and_no_gc(self):
        self.toolchain.instrument_borrow = True
        self.build("核 取 外言 'kernel.ru'. 显 核 其 工 '中文😀' 0 10.")
        result = self.run_binary()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'10\n')
        self.assertEqual(result.stderr.count('DEV_BORROW_BALANCED_NO_GC'),1)
        self.assertIn('RU_GC live=0',result.stderr)

    def test_scalar_and_range_rejection_before_borrow(self):
        for args, diagnostic in [("'abc' (-1) 2",'密整数参数'),("'abc' 0.5 2",'密整数参数'),
                                 ("'abc' 0 4294967296",'密整数参数'),("'abc' 2 1",'密视图起止范围越界'),
                                 ("'abc' 0 4",'密视图起止范围越界'),("123 0 0",'密 UTF8 视图需要')]:
            with self.subTest(args=args):
                self.build("核 取 外言 'kernel.ru'. 显 核 其 工 "+args+'.')
                result = self.run_binary()
                self.assertNotEqual(result.returncode,0)
                self.assertIn(diagnostic,result.stderr)
                self.assertIn('RU_GC live=0',result.stderr)

    def test_checked_kernel_failure_span_and_release(self):
        self.toolchain.instrument_borrow = True
        for kernel,args,status in [('算 工 字节 始 终: 得 字节[始]. 法',"'' 0 0",1),
                                   ('算 工 字节 始 终: 得 始+终. 法',"'' 4294967295 1",2)]:
            with self.subTest(status=status):
                self.build("核 取 外言 'kernel.ru'. 显 核 其 工 "+args+'.',kernel,ranges=False,result_type='u8' if status == 1 else 'u32')
                result = self.run_binary()
                self.assertNotEqual(result.returncode,0)
                self.assertIn(str(self.kernel),result.stderr)
                self.assertIn('status='+str(status),result.stderr)
                self.assertEqual(result.stderr.count('DEV_BORROW_BALANCED_NO_GC'),1)
                self.assertRegex(result.stderr,r'列=[1-9][0-9]*')
                self.assertIn('RU_GC live=0',result.stderr)

    def test_changed_renamed_source_remains_generic_and_unsupported_fails(self):
        self.build("核 取 外言 'kernel.ru'. 显 核 其 工 'abcd' 1 3.",
                   '算 工 字节 始 终: 得 始+终. 法')
        result = self.run_binary()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'4\n')
        previous = self.binary.read_bytes()
        with self.assertRaises(RuntimeError):
            self.build("核 取 外言 'kernel.ru'. 显 核 其 工 'abcd' 1 3.",
                       '算 工 字节 始 终: 显 字节. 得 始. 法')
        self.assertEqual(self.binary.read_bytes(),previous)


if __name__ == '__main__': unittest.main()
