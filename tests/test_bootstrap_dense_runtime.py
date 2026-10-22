"""Required real-stage3/LLVM14 application gates, separate from development tests.

The strict runner supplies REQUIRED=1, an authenticated fresh stage3, and a persistent
artifact directory. Missing requirements fail; no LLVM17/C-seed fallback exists.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import unittest
import uuid
from unittest.mock import patch

from rulang.llvm_toolchain import LLVMToolchain
from tools import bootstrap
from tools.bootstrap_dense_protocol import EFFECTS, verify_proof_hashes

FORBIDDEN = (
    'rulang.frontend.parse', 'rulang.modules.load_module_graph',
    'rulang.compiler.Compiler.compile', 'rulang.llvm_compiler.LLVMCompiler.compile',
    'rulang.cli.build', 'rulang.native_c.NativeCPlan.__init__', 'rulang.native_c.NativeCPlan.emit_c',
    'rulang.mi_source.read_manifest', 'rulang.mi_source.MiSourcePlan.__init__',
    'rulang.mi_source.SourceLowerer.__init__', 'rulang.mi_ir.lower',
    'rulang.mi_llvm.lower', 'rulang.mi_llvm.Emitter.__init__',
)


def identity(path):
    data = Path(path).read_bytes()
    return {'path': str(Path(path).resolve()), 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}


def write_source_bytes(path, text):
    # Preserve original fixture bytes on Windows too; no text newline translation.
    Path(path).write_bytes(text.encode('utf-8'))


def require_runtime_inputs():
    if os.environ.get('RU_BOOTSTRAP_DENSE_REQUIRED') != '1':
        raise unittest.SkipTest('not requested; cannot satisfy required dense acceptance')
    compiler = os.environ.get('RU_BOOTSTRAP_DENSE_TEST_COMPILER')
    evidence = os.environ.get('RU_BOOTSTRAP_DENSE_EVIDENCE_DIR')
    if not compiler or not Path(compiler).is_absolute() or not Path(compiler).is_file():
        raise RuntimeError('required fresh stage3 executable is missing or not absolute')
    if not evidence or not Path(evidence).is_absolute():
        raise RuntimeError('required persistent evidence directory is missing or not absolute')
    # Production implementation checks Clang plus all five tools are LLVM14.
    toolchain = LLVMToolchain()
    if not re.search(r'clang version 14\.', toolchain.version):
        raise RuntimeError('required actual LLVM14 toolchain unavailable')
    return Path(compiler).resolve(), Path(evidence).resolve(), toolchain


class DenseRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler, cls.evidence_root, cls.toolchain = require_runtime_inputs()
        cls.compiler_identity = identity(cls.compiler)
        cls.evidence_root.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.directory = self.evidence_root/(self._testMethodName+'-'+uuid.uuid4().hex[:12])
        self.directory.mkdir()
        self.counter = 0

    def spec(self, name='工', params=None, result='u32', ranges=False):
        item = {'module':'kernel.ru','function':name,
                'params':params if params is not None else {'字节':'borrow_ro_utf8','始':'u32','终':'u32'},
                'result':result,'effects':list(EFFECTS)}
        if ranges: item['ranges'] = [{'view':'字节','begin':'始','end':'终'}]
        return item

    def build(self, source, kernel, specs=None, *, probe=False, directory=None):
        self.counter += 1
        directory = directory or self.directory/str(self.counter)
        directory.mkdir(exist_ok=True)
        entry, module, manifest = directory/'main.ru', directory/'kernel.ru', directory/'manifest.json'
        write_source_bytes(entry,source)
        write_source_bytes(module,kernel)
        manifest.write_text(json.dumps({'version':1,'functions':specs or [self.spec()]},ensure_ascii=False),encoding='utf-8')
        output = directory/('program.exe' if os.name == 'nt' else 'program')
        proof_path, llvm_path = directory/'proof.json', directory/'standalone.ll'
        with ExitStack() as guards:
            for name in FORBIDDEN:
                guards.enter_context(patch(name,side_effect=AssertionError('forbidden Python application processing: '+name)))
            if probe:
                # Additional test-only build, AFTER uninstrumented production run.
                # Original LLVMToolchain.compile still executes LLVM14 in full;
                # this only adds assertions to generated boundary metadata.
                original = self.toolchain.compile
                def instrument(ir, runtime, stage):
                    ordinary = runtime.encode('utf-8')
                    count = [0]
                    def before(match):
                        count[0] += 1
                        arg = match[2]
                        return ('    fprintf(stderr, "DENSE_TEST_RETAIN_ATTEMPT\\n");\n'
                                '    size_t dev_roots = args['+arg+'].heap->roots;\n'
                                '    size_t dev_gc = ru_collections;\n'+match[1])
                    changed = re.sub(r'(    Val mi_owner = v_copy\(args\[(\d+)\]\);)',before,runtime)
                    if not count[0]: raise AssertionError('required borrow probe site absent')
                    changed = changed.replace('    v_drop(mi_owner);',
                        '    if (mi_owner.heap->roots != dev_roots+1 || ru_collections != dev_gc) abort();\n'
                        '    v_drop(mi_owner);\n'
                        '    if (mi_owner.heap->roots != dev_roots || ru_collections != dev_gc) abort();\n'
                        '    fprintf(stderr, "DENSE_TEST_RELEASED_NO_GC\\n");')
                    (directory/'runtime.original.c').write_bytes(ordinary)
                    (directory/'runtime.instrumented.c').write_bytes(changed.encode('utf-8'))
                    (directory/'instrumentation.json').write_text(json.dumps({
                        'test_only':True,'not_uninstrumented_production_proof':True,
                        'original_runtime_sha256':hashlib.sha256(ordinary).hexdigest(),
                        'instrumented_runtime_sha256':hashlib.sha256(changed.encode()).hexdigest(),
                        'borrow_sites':count[0]},indent=2)+'\n', encoding='utf-8')
                    return original(ir,changed,stage)
                guards.enter_context(patch.object(self.toolchain,'compile',side_effect=instrument))
            proof = bootstrap.compile_native(self.compiler,entry,output,self.toolchain,
                experimental_mi_manifest=manifest,keep_frontend=True,emit_llvm=llvm_path,proof=proof_path,
                source_roots=[directory],linker=os.environ.get('RU_BOOTSTRAP_DENSE_LINKER'))
        self.assertEqual(identity(self.compiler),self.compiler_identity)
        verify_proof_hashes(proof)
        if probe:
            instrumentation = json.loads((directory/'instrumentation.json').read_text(encoding='utf-8'))
            self.assertEqual(proof['runtime_sha256'],instrumentation['original_runtime_sha256'])
            self.assertNotEqual(instrumentation['original_runtime_sha256'],instrumentation['instrumented_runtime_sha256'])
            self.assertEqual(identity(directory/'runtime.original.c')['sha256'],instrumentation['original_runtime_sha256'])
            self.assertEqual(identity(directory/'runtime.instrumented.c')['sha256'],instrumentation['instrumented_runtime_sha256'])
        self.assertIsNone(proof['native_protocol'])
        self.assertEqual(proof['toolchain']['version'],self.toolchain.version)
        self.assertEqual(proof['target_triple'],self.toolchain.triple)
        self.assertEqual(proof['data_layout'],self.toolchain.data_layout)
        self.assertEqual(json.loads(proof_path.read_text(encoding='utf-8')),proof)
        return output, proof

    def run_app(self, output):
        result = subprocess.run([str(output)],capture_output=True,text=True,encoding='utf-8',timeout=60,
                                env=dict(os.environ,RU_GC_THRESHOLD='1',RU_GC_STATS='1'))
        (output.parent/'stdout.txt').write_text(result.stdout,encoding='utf-8')
        (output.parent/'stderr.txt').write_text(result.stderr,encoding='utf-8')
        (output.parent/'execution.json').write_text(json.dumps({'returncode':result.returncode,
            'binary':identity(output),'compiler':self.compiler_identity,'gc_threshold':1},indent=2)+'\n', encoding='utf-8')
        self.assertIn('RU_GC live=0',result.stderr)
        return result

    def assert_success(self, output, expected):
        result = self.run_app(output)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,expected)
        return result

    def test_five_original_wij_kernels_and_selected_llvm_only(self):
        fixtures = bootstrap.ROOT/'tests/fixtures/dense'
        kernel = (fixtures/'markdown_ascii_kernel.ru').read_bytes().decode('utf-8')
        specs = json.loads((fixtures/'markdown-dense-manifest.json').read_text(encoding='utf-8'))['functions']
        for spec in specs: spec['module'] = 'kernel.ru'
        source = """核 取 外言 'kernel.ru'.
显 核 其 ASCII段 'abc>def' 0 7.
显 核 其 重复ASCII段 'aaaaB' 0 5.
显 核 其 字节量 'a中😀é'.
显 核 其 安全围栏段 'abc\\nxyz\\n' 0 8 96.
显 核 其 计换行 'a\\nb\\n' 0 4.
"""
        output,proof = self.build(source,kernel,specs)
        self.assert_success(output,'3\n4\n10\n8\n2\n')
        self.assertEqual(len(proof['dense_selected_plan'][2]),5)
        ir = output.with_name(output.name+'.frontend.ll').read_text(encoding='utf-8')
        metadata = output.with_name(output.name+'.metadata.c').read_text(encoding='utf-8')
        self.assertEqual(ir.count('define void @boot_dense_'),5)
        for record in proof['dense_selected_plan'][2]:
            self.assertIn('define void @'+record[3]+'_llvm(',ir)
            self.assertNotIn('define void @boot_fn_'+record[2]+'_llvm(',ir)
            self.assertIn('extern void '+record[3]+'_llvm(',metadata)
            self.assertNotRegex(metadata,r'\b'+record[3]+r'_llvm\([^;]*\)\s*\{')
        for body in re.findall(r'define void @boot_dense_[^{]+\{(.*?)\n\}',ir,re.S):
            self.assertNotRegex(body,r'\b(call|invoke)\b')
        self.assertEqual((output.parent/'kernel.ru').read_bytes(),(fixtures/'markdown_ascii_kernel.ru').read_bytes())

    def test_generic_changed_source_and_whole_plan_failure(self):
        spec = self.spec('别名')
        caller = "核 取 外言 'kernel.ru'. 显 核 其 别名 'abcd' 1 3."
        output,_ = self.build(caller,'算 别名 字节 始 终: 得 始+终. 法',[spec])
        self.assert_success(output,'4\n')
        old = {path:identity(path) for path in (output,output.parent/'proof.json',output.parent/'standalone.ll',
               output.with_name(output.name+'.frontend.ll'),output.with_name(output.name+'.metadata.c'))}
        inputs = {path:path.read_bytes() for path in (output.parent/'main.ru',output.parent/'kernel.ru',output.parent/'manifest.json')}
        # First selection is valid; second fails lowering. Entire old publication survives.
        kernel = '算 别名 字节 始 终: 得 始+终. 法\n算 后坏 字节 始 终: 显 字节. 得 始. 法'
        with self.assertRaises(RuntimeError):
            self.build(caller,kernel,[spec,self.spec('后坏')],directory=output.parent)
        for path, frozen in old.items(): self.assertEqual(identity(path),frozen)
        for path, data in inputs.items():
            path.with_name(path.name+'.rejected-input.txt').write_bytes(path.read_bytes())
            path.write_bytes(data)

    def test_utf8_empty_byte_offsets_and_scalar_edges(self):
        specs = [self.spec('字节',{'文':'borrow_ro_utf8','位':'u32'},'u8'),
                 self.spec('长度',{'文':'borrow_ro_utf8'}),
                 self.spec('边界',{'文':'borrow_ro_utf8','小':'u8','大':'u32'})]
        kernel = '算 字节 文 位: 得 文[位]. 法\n算 长度 文: 得 文 其 量. 法\n算 边界 文 小 大: 得 大. 法'
        caller = "核 取 外言 'kernel.ru'. 显 核 其 长度 ''. 显 核 其 长度 '中😀'. 显 核 其 字节 '中😀' 3. 显 核 其 字节 '中😀' 6. 显 核 其 边界 '' 255 4294967295."
        output,_ = self.build(caller,kernel,specs)
        self.assert_success(output,'0\n7\n240\n128\n4294967295\n')

    def test_scalar_and_range_errors_before_retain(self):
        spec = self.spec(ranges=True)
        kernel = '算 工 字节 始 终: 得 终-始. 法'
        for args,error in [("'abc' (-1) 2",'密整数参数'),("'abc' 0.5 2",'密整数参数'),
                           ("'abc' 0 4294967296",'密整数参数'),("'abc' 真 2",'密整数参数'),("'abc' 2 1",'密视图起止范围越界'),
                           ("'abc' 0 4",'密视图起止范围越界'),("123 0 0",'密 UTF8 视图需要')]:
            for probe in (False,True):
                with self.subTest(args=args,probe=probe):
                    output,_ = self.build("核 取 外言 'kernel.ru'. 显 核 其 工 "+args+'.',kernel,[spec],probe=probe)
                    result = self.run_app(output)
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn(error,result.stderr)
                    self.assertNotIn('DENSE_TEST_RETAIN_ATTEMPT',result.stderr)
                    self.assertNotIn('DENSE_TEST_RELEASED_NO_GC',result.stderr)

        for probe in (False,True):
            output,_ = self.build("核 取 外言 'kernel.ru'. 显 核 其 工 '' 256.",
                '算 工 字节 小: 得 小. 法',
                [self.spec(params={'字节':'borrow_ro_utf8','小':'u8'},result='u8')],probe=probe)
            result = self.run_app(output)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('密整数参数',result.stderr)
            self.assertNotIn('DENSE_TEST_RETAIN_ATTEMPT',result.stderr)
            self.assertNotIn('DENSE_TEST_RELEASED_NO_GC',result.stderr)

    def test_bounds_overflow_exact_source_span(self):
        cases = [('算 工 字节 始 终:\n 得 字节[始].\n法',"'' 0 0",'u8',1,6),
                 ('算 工 字节 始 终:\n 得 始+终.\n法',"'' 4294967295 1",'u32',2,5)]
        for kernel,args,type_,status,column in cases:
            for probe in (False,True):
                with self.subTest(status=status,probe=probe):
                    output,_ = self.build("核 取 外言 'kernel.ru'. 显 核 其 工 "+args+'.',kernel,
                                          [self.spec(result=type_)],probe=probe)
                    result = self.run_app(output)
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn((output.parent/'kernel.ru').as_posix()+':2:',result.stderr)
                    self.assertIn('列='+str(column)+'，status='+str(status),result.stderr.replace(' ',''))
                    self.assertEqual(result.stderr.count('DENSE_TEST_RELEASED_NO_GC'),int(probe))

    def test_production_and_instrumented_owner_gc_lifecycle(self):
        caller = "核 取 外言 'kernel.ru'. 循 50 次 显 核 其 工 '中文😀' 0 10. 环"
        kernel = '算 工 字节 始 终: 得 终-始. 法'
        for probe in (False,True):
            output,_ = self.build(caller,kernel,[self.spec(ranges=True)],probe=probe)
            result = self.assert_success(output,'10\n'*50)
            self.assertEqual(result.stderr.count('DENSE_TEST_RELEASED_NO_GC'),50 if probe else 0)


if __name__ == '__main__': unittest.main()
