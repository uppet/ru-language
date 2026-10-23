"""Required real LLVM14 owned-result pack gate, never a development adapter.

The runner binds RU_BOOTSTRAP_PACK_COMPILER to this run's freshly verified stage3.
Both ordinary emitters execute all 17 fixed-output cases at GC thresholds 1/17.
Deliberately unsafe diagnostic copies must exhibit their specific known failures;
compile failures, arbitrary crashes and timeouts never count as negative success.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import types
import unittest
from unittest.mock import patch

from rulang import llvm_compiler
from rulang.frontend import parse
from rulang.llvm_toolchain import LLVMToolchain
import test_bootstrap_slot_reuse as slots
from bootstrap_pack_cases import CASES, combined, sections

REPO = Path(llvm_compiler.__file__).resolve().parents[1]
REQUIRED = os.environ.get('RU_BOOTSTRAP_PACK_REQUIRED') == '1'
THRESHOLDS = (1, 17)
NEGATIVE_SOURCE = "算 等 值: 得 值. 法.\n显 [(等 'head'), (等 'tail')].\n"
NEGATIVE_EXPECTED = '[head, tail]\n'
NEGATIVE_WRONG = '[head, <算 等>]\n'
ROOT_SOURCE = "算 制 值: 垃圾 取 ['trigger']. 得 算: 得 值. 法. 法.\n闭包 取 制 ['owned'].\n显 闭包().\n"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unsafe_python_type():
    path = REPO/'rulang/llvm_compiler.py'
    text = path.read_text(encoding='utf-8')
    anchor = 'if len(values) == 1 or contiguous:'
    if text.count(anchor) != 1:
        raise AssertionError('exact reviewed Python pack boundary required')
    changed = text.replace(anchor, 'if True:  # diagnostic unsafe all-argument reuse')
    module = types.ModuleType('rulang.pack_unsafe_diagnostic')
    module.__package__ = 'rulang'
    module.__file__ = str(path)
    exec(compile(changed, str(path), 'exec'), module.__dict__)
    return module.LLVMCompiler, {'mutation':'force all argument regions to reuse',
        'original_sha256':digest(path), 'mutated_sha256':hashlib.sha256(changed.encode()).hexdigest()}


def unsafe_pure_source(source):
    anchor = '    复用 取 (值 其 量) == 1 或 连续.'
    if source.count(anchor) != 1:
        raise AssertionError('exact reviewed pure-Ru pack boundary required')
    return source.replace(anchor, '    复用 取 真.')


def early_root_drop(runtime):
    anchor = '{ rul_put(out,v_call(*(Val *)callee,(size_t)count,keys,args,line)); }'
    if runtime.count(anchor) != 1:
        raise AssertionError('exact runtime call boundary required')
    return runtime.replace(anchor, '{ if (count == 1) v_drop(((Val *)args)[0]); '
                           'rul_put(out,v_call(*(Val *)callee,(size_t)count,keys,args,line)); }')


def physical_slots(ir):
    """Check physical addresses, unique definitions and exact frame bounds."""
    result = []
    for body in re.findall(r'define void @[^}]+}', ir):
        names = re.findall(r'^  (%\w+) =', body, re.M)
        if len(names) != len(set(names)):
            raise AssertionError('duplicate SSA definition')
        extents = slots.frames(body)
        if len(extents) != 1:
            raise AssertionError('exactly one frame required per emitted function')
        rows = re.findall(r'(%v\d+) = call i8\* @rul_slot\(i8\* %frame, i32 (\d+)\)', body)
        indices = [int(index) for _, index in rows]
        if indices != list(range(extents[0])):
            raise AssertionError('cached physical slot inventory/highwater mismatch')
        result.append({'frame_slots':extents[0], 'addresses':len(rows)})
    if not result:
        raise AssertionError('actual generated functions required')
    return result


@unittest.skipUnless(REQUIRED, 'required isolated pack gate not requested')
class BootstrapPackRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stage3 = Path(os.environ.get('RU_BOOTSTRAP_PACK_COMPILER', ''))
        evidence = Path(os.environ.get('RU_BOOTSTRAP_PACK_EVIDENCE_DIR', ''))
        if not stage3.is_absolute() or not stage3.is_file() or not evidence.is_absolute():
            raise AssertionError('absolute verified stage3 and persistent evidence required')
        evidence.mkdir(parents=True, exist_ok=True)
        cls.output = Path(tempfile.mkdtemp(prefix='pack-lifetime-', dir=evidence)).resolve()
        cls.report = {'schema':'bootstrap-owned-pack-lifetime-v1', 'state':'running',
            'stage3':{'path':str(stage3),'sha256':digest(stage3)},
            'case_ids':[name for name, _, _ in CASES], 'thresholds':list(THRESHOLDS),
            'builds':{}, 'runs':{}, 'scope':'actual LLVM14 both ordinary emitters, not native FFI/performance'}
        cls.receipt = cls.output/'receipt.json'
        cls.outputs = {}
        cls.persist()
        try:
            tc = LLVMToolchain()
            if not re.search(r'clang version 14\.', tc.version):
                raise AssertionError('production LLVM14 required')
            cls.report['toolchain'] = {'version':tc.version,'triple':tc.triple,
                'data_layout':tc.data_layout,'clang':tc.clang,'tools':tc.tools}
            source, expected = combined()
            source_path = cls.output/'lifetime.ru'
            source_path.write_text(source, encoding='utf-8', newline='\n')
            (cls.output/'expected.stdout').write_text(expected, encoding='utf-8', newline='\n')
            cls.report['source_sha256'] = digest(source_path)
            python = cls.python_build(tc, llvm_compiler.LLVMCompiler, source, 'python')
            stage = cls.pure_build(tc, stage3, source_path, 'stage3')
            for label, binary in [('python',python), ('stage3',stage)]:
                for threshold in THRESHOLDS:
                    cls.execute(label+'-gc'+str(threshold), binary, threshold)
            negative_source = cls.output/'negative-all-reuse.ru'
            negative_source.write_text(NEGATIVE_SOURCE, encoding='utf-8', newline='\n')
            unsafe, mutation = unsafe_python_type()
            cls.report['python_negative'] = mutation
            binary = cls.python_build(tc, unsafe, NEGATIVE_SOURCE, 'python-unsafe-all-reuse')
            cls.execute('python-unsafe-all-reuse', binary, 1)
            negative_dir = cls.output/'pure-ru-negative-source'; negative_dir.mkdir()
            copied = negative_dir/'compiler.ru'
            original = REPO/'bootstrap/compiler.ru'
            copied.write_text(unsafe_pure_source(original.read_text(encoding='utf-8')), encoding='utf-8', newline='\n')
            emitter = REPO/'bootstrap/native_emit.ru'
            (negative_dir/'native_emit.ru').write_bytes(emitter.read_bytes())
            cls.report['pure_ru_negative'] = {'mutation':'force all argument regions to reuse',
                'original_source_sha256':digest(original), 'mutated_source_sha256':digest(copied),
                'native_emit_sha256':digest(emitter)}
            broken = cls.pure_build(tc, stage3, copied, 'stage3-unsafe-compiler')
            binary = cls.pure_build(tc, broken, negative_source, 'stage3-unsafe-all-reuse')
            cls.execute('stage3-unsafe-all-reuse', binary, 1)
            binary = cls.python_build(tc, llvm_compiler.LLVMCompiler, ROOT_SOURCE,
                                      'python-early-root-drop', runtime_transform=early_root_drop)
            cls.execute('python-early-root-drop', binary, 1)
            if digest(stage3) != cls.report['stage3']['sha256']:
                raise AssertionError('stage3 changed during pack gate')
            cls.report['state'] = 'executed-tests-pending'
            cls.persist()
        except Exception as error:
            cls.report.update(state='setup-failed', error=str(error))
            cls.persist()
            raise

    @classmethod
    def persist(cls):
        cls.receipt.write_text(json.dumps(cls.report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    @classmethod
    def python_build(cls, tc, compiler_type, source, label, runtime_transform=None):
        directory = cls.output/label; directory.mkdir()
        (directory/'source.ru').write_text(source, encoding='utf-8', newline='\n')
        compiler = compiler_type(parse(source), '<pack-lifetime-gate>', full_runtime=True)
        ir = compiler.compile(tc.triple, tc.data_layout)
        runtime = compiler.runtime_c()
        row = {'frontend':'Python LLVM', 'source_sha256':digest(directory/'source.ru'),
            'runtime_original_sha256':hashlib.sha256(runtime.encode()).hexdigest(),
            'physical_slots':physical_slots(ir), 'diagnostic_runtime':runtime_transform is not None}
        if runtime_transform:
            (directory/'runtime.original.c').write_text(runtime, encoding='utf-8', newline='\n')
            runtime = runtime_transform(runtime)
        cls.report['builds'][label] = row; cls.persist()
        started = time.perf_counter()
        try:
            binary, _ = tc.compile(ir, runtime, directory)
        finally:
            row['compile_seconds'] = time.perf_counter()-started; cls.persist()
        row.update(binary_sha256=digest(binary), ir_sha256=digest(directory/'program.ll'),
                   runtime_sha256=digest(directory/'runtime.c'))
        cls.persist()
        return binary

    @classmethod
    def pure_build(cls, tc, frontend, source, label):
        from tools import bootstrap
        if bootstrap.ROOT.resolve() != REPO:
            raise AssertionError('unexpected bootstrap host repository')
        directory = cls.output/label; directory.mkdir()
        binary = directory/'program.exe'; proof_path = directory/'build-proof.json'
        row = {'frontend':'actual Ru frontend', 'host':'tools.bootstrap.compile_native',
            'source_sha256':digest(source), 'frontend_sha256':digest(frontend),
            'proof_path':str(proof_path), 'forbidden_python_hooks':list(slots.FORBIDDEN_FRONTEND_HOOKS)}
        cls.report['builds'][label] = row; cls.persist()
        started = time.perf_counter()
        try:
            with slots.prohibit_python_frontend():
                proof = bootstrap.compile_native(frontend, source, binary, tc,
                    keep_frontend=True, emit_llvm=directory/'standalone.ll', proof=proof_path)
        finally:
            row['total_seconds'] = time.perf_counter()-started; cls.persist()
        frontend_ir = binary.with_name(binary.name+'.frontend.ll')
        row.update(binary_sha256=digest(binary), ir_sha256=proof['source_ir_sha256'],
            runtime_sha256=proof['runtime_sha256'], proof_sha256=digest(proof_path),
            physical_slots=physical_slots(frontend_ir.read_text(encoding='utf-8')))
        cls.persist()
        return binary

    @classmethod
    def execute(cls, label, binary, threshold):
        row = {'binary_sha256':digest(binary), 'gc_threshold':threshold, 'completed':False}
        cls.report['runs'][label] = row; cls.persist()
        stdout, stderr = '', ''
        try:
            result = subprocess.run([str(binary)], capture_output=True, text=True, encoding='utf-8',
                errors='strict', timeout=30,
                env={**os.environ,'RU_GC_THRESHOLD':str(threshold),'RU_GC_STATS':'1'})
            stdout, stderr = result.stdout, result.stderr
            cls.outputs[label] = result
            row.update(completed=True, returncode=result.returncode,
                       stdout_matches_all_cases=stdout==combined()[1], gc_live_zero=slots.gc_zero(stderr))
        except subprocess.TimeoutExpired as error:
            def decoded(value): return value.decode('utf-8','replace') if isinstance(value,bytes) else (value or '')
            stdout, stderr = decoded(error.stdout), decoded(error.stderr)
            row.update(timed_out=True, error='original 30-second runtime deadline exceeded')
            raise
        finally:
            for name, data in [('stdout',stdout),('stderr',stderr)]:
                path=cls.output/(label+'.'+name); path.write_text(data,encoding='utf-8',newline='\n')
                row[name+'_sha256']=digest(path)
            cls.persist()

    def test_python_unsafe_all_reuse_is_rejected(self):
        self.assert_bad_pack('python-unsafe-all-reuse')

    def test_stage3_unsafe_all_reuse_is_rejected(self):
        self.assert_bad_pack('stage3-unsafe-all-reuse')

    def assert_bad_pack(self, label):
        result = self.outputs[label]
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, NEGATIVE_WRONG)
        self.assertNotEqual(result.stdout, NEGATIVE_EXPECTED)
        self.assertTrue(slots.gc_zero(result.stderr), result.stderr)

    def test_early_original_argument_root_drop_is_rejected(self):
        result = self.outputs['python-early-root-drop']
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertIn('值的根计数失衡', result.stderr)
        self.assertTrue(slots.gc_zero(result.stderr), result.stderr)


def lifecycle_test(frontend, threshold, name, expected):
    def test(self):
        result = self.outputs[frontend+'-gc'+str(threshold)]
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(slots.gc_zero(result.stderr), result.stderr)
        counts = re.fullmatch(r'RU_GC live=0 freed=(\d+) collections=(\d+)\n',result.stderr)
        self.assertTrue(counts and int(counts[1]) > 0 and int(counts[2]) > 0, result.stderr)
        self.assertEqual(result.stdout, combined()[1])
        self.assertEqual(sections(result.stdout)[name], expected)
    return test


for _frontend in ('python','stage3'):
    for _threshold in THRESHOLDS:
        for _index, (_name, _source, _expected) in enumerate(CASES, 1):
            setattr(BootstrapPackRuntimeTests,
                f'test_{_frontend}_gc{_threshold}_{_index:02d}_{_name}',
                lifecycle_test(_frontend, _threshold, _name, _expected))


if __name__ == '__main__':
    unittest.main(verbosity=2)
