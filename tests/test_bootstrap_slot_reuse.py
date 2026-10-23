"""Required LLVM14 slot lifetime gate; never substitutes the LLVM17 dev adapter.

Runner contract:
 RU_BOOTSTRAP_SLOT_REQUIRED=1
 RU_BOOTSTRAP_SLOT_COMPILER=<absolute path to this run's fresh stage3>
 RU_BOOTSTRAP_SLOT_EVIDENCE_DIR=<absolute owned persistent output directory>

The caller must bind stage3's hash to the successful fresh bootstrap receipt.
Normal repository discovery may skip the dynamic class when REQUIRED is absent;
with REQUIRED=1 missing stage3, tools, outputs or GC evidence are hard failures.
"""
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from rulang import llvm_compiler
from rulang.frontend import parse
from rulang.llvm_compiler import LLVMCompiler
from rulang.llvm_toolchain import LLVMToolchain
from bootstrap_slot_cases import CASES, combined

REPO = Path(llvm_compiler.__file__).resolve().parents[1]
REQUIRED = os.environ.get('RU_BOOTSTRAP_SLOT_REQUIRED') == '1'
FORBIDDEN_FRONTEND_HOOKS = (
    'rulang.frontend.parse',
    'rulang.modules.load_module_graph',
    'rulang.compiler.Compiler.compile',
    'rulang.llvm_compiler.LLVMCompiler.compile',
    'rulang.native_c.NativeCPlan.__init__',
    'rulang.native_c.NativeCPlan.emit_c',
    'rulang.cli.build',
    'rulang.mi_source.MiSourcePlan.__init__',
    'rulang.mi_source.SourceLowerer.__init__',
    'rulang.mi_source.read_manifest',
    'rulang.mi_ir.lower',
    'rulang.mi_llvm.lower',
    'rulang.mi_llvm.Emitter.__init__',
)


@contextmanager
def prohibit_python_frontend():
    with ExitStack() as guards:
        for name in FORBIDDEN_FRONTEND_HOOKS:
            guards.enter_context(patch(name, side_effect=AssertionError('Python application frontend forbidden: '+name)))
        yield


class UncachedReuseSlots(LLVMCompiler):
    """Exact prior925 address emission, with the same normal slot reuse."""
    def slot(self):
        ident = '%' + self.fresh('v')
        self.entry_allocations.append(f'  {ident} = call i8* @rul_slot(i8* %frame, i32 {self.slot_count})')
        self.slot_count += 1
        self.slot_peak = max(self.slot_peak, self.slot_count)
        return ident


def canonical_addresses(ir):
    table, aliases, output = {}, {}, []
    for line in ir.splitlines(True):
        if line.startswith('define '):
            table, aliases = {}, {}
        match = re.fullmatch(r'  (%v\d+) = call i8\* @rul_slot\(i8\* %frame, i32 (\d+)\)\n', line)
        if match:
            name, index = match.groups()
            if index in table:
                aliases[name] = table[index]
                continue
            table[index] = name
        output.append(re.sub(r'%v\d+\b', lambda value: aliases.get(value[0], value[0]), line))
    return ''.join(output)


class LegacyMonotonicSlots(UncachedReuseSlots):
    """Test-only old physical allocation rule, not an alternate compiler path."""
    def clear_temporaries(self):
        self.call_abi('clear', '%frame')


class UnsafeUnwindSlots(LLVMCompiler):
    """Test-only known bug: success edges still retain outer expressions."""
    def panic_transfer(self):
        super().panic_transfer()
        self.slot_count = 0


def lower(compiler_type, source, triple=None, layout=None):
    compiler = compiler_type(parse(source), '<slot-lifetime-gate>', full_runtime=True)
    return compiler.compile(triple, layout), compiler.runtime_c()


def normalize(ir):
    ir = re.sub(r'(@rul_frame_new\(i32 )\d+', r'\g<1>FRAME', ir)
    return re.sub(r'(@rul_slot\(i8\* %frame, i32 )\d+', r'\g<1>SLOT', ir)


def frames(ir):
    return [int(value) for value in re.findall(r'@rul_frame_new\(i32 (\d+)\)', ir)]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def gc_zero(stderr):
    # A later zero line must not hide an earlier leak or duplicated shutdown.
    lines = re.findall(r'^RU_GC[^\n]*', stderr, re.M)
    return len(lines) == 1 and re.fullmatch(r'RU_GC live=0 freed=\d+ collections=\d+', lines[0]) is not None


def bad_pure_ru_source(source):
    old = "    清环境 状 深. 调用 状 'clear' (['%frame']). 跳 状 目标. 得 空."
    new = "    清环境 状 深. 调用 状 'clear' (['%frame']). 设 状 '位数' 0. 跳 状 目标. 得 空."
    if source.count(old) != 1:
        raise AssertionError('expected exactly one unmodified pure-Ru panic-transfer boundary')
    return source.replace(old, new)


def sections(stdout):
    result, position = {}, 0
    for index, (name, _, _) in enumerate(CASES):
        marker = name + '\n'
        if not stdout.startswith(marker, position):
            raise AssertionError('missing/out-of-order case marker: ' + name)
        start = position + len(marker)
        if index + 1 == len(CASES):
            end = len(stdout)
        else:
            end = stdout.find(CASES[index+1][0]+'\n', start)
            if end < 0:
                raise AssertionError('missing next case marker after: ' + name)
        result[name] = stdout[start:end]
        position = end
    return result


class BootstrapSlotStructureTests(unittest.TestCase):
    def test_normalized_ir_and_runtime_preserve_operations(self):
        for name, source, _ in CASES:
            with self.subTest(case=name):
                old, old_runtime = lower(LegacyMonotonicSlots, source)
                new, new_runtime = lower(LLVMCompiler, source)
                uncached, uncached_runtime = lower(UncachedReuseSlots, source)
                self.assertEqual(normalize(old), normalize(uncached))
                self.assertEqual(canonical_addresses(uncached), new)
                self.assertEqual(old_runtime, uncached_runtime)
                self.assertEqual(old_runtime, new_runtime)
                self.assertEqual(len(frames(old)), len(frames(new)))
                self.assertTrue(all(new_size <= old_size for old_size,new_size in zip(frames(old),frames(new))))

    def test_ssa_unique_physical_bounds_and_highwater(self):
        ir, _ = lower(LLVMCompiler, combined()[0])
        for body in re.findall(r'define void @[^}]+}', ir):
            names = re.findall(r'^  (%\w+) =', body, re.M)
            self.assertEqual(len(names), len(set(names)))
            extent = frames(body)[0]
            indices = [int(value) for value in re.findall(r'@rul_slot\(i8\* %frame, i32 (\d+)\)', body)]
            self.assertEqual(extent, max(indices, default=-1)+1)
            self.assertEqual(len(indices), len(set(indices)))
            self.assertEqual(indices, list(range(extent)))

    def test_reuse_and_success_edge_differ_from_unsafe_unwind_rule(self):
        old, _ = lower(LegacyMonotonicSlots, '显 1. '*100)
        new, _ = lower(LLVMCompiler, '显 1. '*100)
        self.assertEqual(frames(old), [100])
        self.assertEqual(frames(new), [1])
        source = CASES[0][1]
        correct, _ = lower(LLVMCompiler, source)
        unsafe, _ = lower(UnsafeUnwindSlots, source)
        self.assertNotEqual(correct, unsafe)


@unittest.skipUnless(REQUIRED, 'required isolated slot gate not requested')
class BootstrapSlotReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # No find-in-PATH/default stage3 or skip-on-tool-error is permitted here.
        stage3 = Path(os.environ.get('RU_BOOTSTRAP_SLOT_COMPILER', ''))
        evidence = Path(os.environ.get('RU_BOOTSTRAP_SLOT_EVIDENCE_DIR', ''))
        if not stage3.is_absolute() or not stage3.is_file():
            raise AssertionError('required absolute fresh stage3 path is missing')
        if not evidence.is_absolute():
            raise AssertionError('required absolute persistent evidence directory is missing')
        evidence.mkdir(parents=True, exist_ok=True)
        cls.output = Path(tempfile.mkdtemp(prefix='slot-lifetime-', dir=evidence)).resolve()
        cls.report = {'schema':'bootstrap-slot-lifetime-v1', 'state':'running',
                      'stage3':{'path':str(stage3),'sha256':digest(stage3)},
                      'case_ids':[name for name, _, _ in CASES], 'builds':{}, 'runs':{},
                      'scope':'real LLVM14, Python LLVM + supplied fresh stage3; no native FFI claims'}
        cls.receipt = cls.output/'receipt.json'
        cls.persist()
        try:
            toolchain = LLVMToolchain()  # Existing strict LLVM14+host checks.
            cls.report['toolchain'] = {'version':toolchain.version,'triple':toolchain.triple,
                'data_layout':toolchain.data_layout,'clang':toolchain.clang,'tools':toolchain.tools}
            source, expected = combined()
            source_path = cls.output/'lifetime.ru'
            source_path.write_text(source, encoding='utf-8', newline='\n')
            (cls.output/'expected.stdout').write_text(expected, encoding='utf-8', newline='\n')
            cls.report['source_sha256'] = digest(source_path)
            cls.outputs = {}
            for label, compiler_type in [('python',LLVMCompiler), ('python-unsafe-unwind',UnsafeUnwindSlots)]:
                directory = cls.output/label; directory.mkdir()
                ir, runtime = lower(compiler_type, source, toolchain.triple, toolchain.data_layout)
                started = time.perf_counter()
                binary, _ = toolchain.compile(ir, runtime, directory)
                cls.record_build(label, directory, binary)
                cls.report['builds'][label]['compile_seconds'] = time.perf_counter()-started
                cls.execute(label, binary)

            # Only the real Ru frontend receives source on this route. Reuse the
            # exact production host, including its identity/protocol guards,
            # fixed runtime assembly, optimization passes and existing timeouts.
            binary = cls.pure_ru_build(toolchain, stage3, source_path, 'stage3')
            cls.execute('stage3', binary)

            # Build a deliberately broken *copy* with the correct fresh stage3.
            # Every build/emission must succeed; only the known first-case runtime
            # ownership error qualifies as negative-control rejection.
            negative_source = cls.output/'pure-ru-negative-source'; negative_source.mkdir()
            original = REPO/'bootstrap/compiler.ru'
            emitter = REPO/'bootstrap/native_emit.ru'
            copied = negative_source/'compiler.ru'
            copied.write_text(bad_pure_ru_source(original.read_text(encoding='utf-8')),
                              encoding='utf-8', newline='\n')
            (negative_source/'native_emit.ru').write_bytes(emitter.read_bytes())
            cls.report['pure_ru_negative'] = {'mutation':'reset cursor at panic-transfer unwind emission',
                'original_source_sha256':digest(original),'mutated_source_sha256':digest(copied),
                'native_emit_sha256':digest(emitter)}
            broken = cls.pure_ru_build(toolchain, stage3, copied, 'stage3-unsafe-compiler')
            binary = cls.pure_ru_build(toolchain, broken, source_path, 'stage3-unsafe-unwind')
            cls.execute('stage3-unsafe-unwind', binary)
            if digest(stage3) != cls.report['stage3']['sha256']:
                raise AssertionError('stage3 changed during gate execution')
            cls.report['state'] = 'executed-tests-pending'
            cls.persist()
        except Exception as error:
            cls.report['state'] = 'setup-failed'
            cls.report['error'] = str(error)
            cls.persist()
            raise

    @classmethod
    def persist(cls):
        cls.receipt.write_text(json.dumps(cls.report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    @classmethod
    def pure_ru_build(cls, toolchain, frontend, source, label):
        from tools import bootstrap
        if bootstrap.ROOT.resolve() != REPO:
            raise AssertionError('bootstrap host loaded from a different repository')
        directory = cls.output/label; directory.mkdir()
        binary = directory/'program.exe'
        proof_path = directory/'build-proof.json'
        cls.report['builds'][label] = {'host':'tools.bootstrap.compile_native',
                                      'source_sha256':digest(source),
                                      'frontend_sha256':digest(frontend),
                                      'proof_path':str(proof_path),
                                      'forbidden_python_hooks':list(FORBIDDEN_FRONTEND_HOOKS)}
        cls.persist()
        started = time.perf_counter()
        try:
            with prohibit_python_frontend():
                proof = bootstrap.compile_native(frontend, source, binary, toolchain,
                    keep_frontend=True, emit_llvm=directory/'standalone.ll', proof=proof_path)
        finally:
            cls.report['builds'][label]['total_seconds'] = time.perf_counter()-started
            cls.persist()
        cls.report['builds'][label].update({'binary_sha256':digest(binary),
            'ir_sha256':proof['source_ir_sha256'],'runtime_sha256':proof['runtime_sha256'],
            'emission_seconds':proof['frontend_seconds'],
            'compile_seconds':proof['seconds']-proof['frontend_seconds'],
            'proof_sha256':digest(proof_path),
            'frame_extents':frames(binary.with_name(binary.name+'.frontend.ll').read_text(encoding='utf-8'))})
        cls.persist()
        return binary

    @classmethod
    def record_build(cls, label, directory, binary):
        cls.report['builds'].setdefault(label, {}).update({'binary_sha256':digest(binary),
            'ir_sha256':digest(directory/'program.ll'), 'runtime_sha256':digest(directory/'runtime.c'),
            'frame_extents':frames((directory/'program.ll').read_text(encoding='utf-8'))})
        cls.persist()

    @classmethod
    def execute(cls, label, binary):
        result = subprocess.run([str(binary)], capture_output=True, text=True, encoding='utf-8',
                                errors='strict', timeout=30,
                                env={**os.environ,'RU_GC_THRESHOLD':'1','RU_GC_STATS':'1'})
        cls.outputs[label] = result
        (cls.output/(label+'.stdout')).write_text(result.stdout, encoding='utf-8', newline='\n')
        (cls.output/(label+'.stderr')).write_text(result.stderr, encoding='utf-8', newline='\n')
        cls.report['runs'][label] = {'returncode':result.returncode,
            'stdout_matches_all_cases':result.stdout==combined()[1],
            'gc_live_zero':gc_zero(result.stderr)}
        cls.persist()

    def test_python_unsafe_unwind_reset_is_rejected(self):
        result = self.outputs['python-unsafe-unwind']
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, CASES[0][0]+'\n')
        self.assertIn('值不是函数', result.stderr)
        self.assertTrue(gc_zero(result.stderr), result.stderr)

    def test_stage3_unsafe_unwind_reset_is_rejected(self):
        result = self.outputs['stage3-unsafe-unwind']
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, CASES[0][0]+'\n')
        self.assertIn('值不是函数', result.stderr)
        self.assertTrue(gc_zero(result.stderr), result.stderr)


def lifecycle_test(frontend, name, expected):
    def test(self):
        result = self.outputs[frontend]
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(gc_zero(result.stderr), result.stderr)
        self.assertEqual(sections(result.stdout)[name], expected)
    return test


for _frontend in ('python','stage3'):
    for _index, (_name, _source, _expected) in enumerate(CASES, 1):
        setattr(BootstrapSlotReuseTests, f'test_{_frontend}_{_index:02d}_{_name}',
                lifecycle_test(_frontend, _name, _expected))


if __name__ == '__main__':
    unittest.main(verbosity=2)
