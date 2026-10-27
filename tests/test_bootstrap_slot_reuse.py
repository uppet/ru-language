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
import shutil
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


class ContiguousSlots(LLVMCompiler):
    """Isolate slot reuse from the independent-payload storage optimization."""
    independent_slots = False


class UncachedReuseSlots(ContiguousSlots):
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
        self.call_abi('clear_count', '%frame', str(self.slot_count))


class UnsafeUnwindSlots(LLVMCompiler):
    """Test-only known bug: success edges still retain outer expressions."""
    def panic_transfer(self):
        super().panic_transfer()
        self.slot_count = 0


def lower(compiler_type, source, triple=None, layout=None):
    compiler = compiler_type(parse(source), '<slot-lifetime-gate>', full_runtime=True)
    return compiler.compile(triple, layout), compiler.runtime_c()


def normalize(ir):
    # Storage selection is independent of the physical-slot reuse under test.
    # The monotonic and reusable layouts have different static root maps. Their
    # actual cleanup is exercised by the runtime cases and negative controls.
    ir = re.sub(r'^  call void @llvm\.lifetime\.(?:start|end)\.p0i8\([^\n]*\)\n', '', ir, flags=re.M)
    ir = re.sub(r'^  call void @rul_frame_roots\([^\n]*\)\n', '', ir, flags=re.M)
    ir = re.sub(r'  %frame_bytes = call i64 @rul_frame_size\(i32 (\d+)\)\n'
                r'  %frame = alloca i8, i64 %frame_bytes, align 16\n'
                r'  call void @rul_frame_init\(i8\* %frame, i32 \1\)',
                r'  %frame = call i8* @rul_frame_new(i32 \1)', ir)
    ir = re.sub(r'call void @rul_frame_drop\(i8\* %frame\)',
                'call void @rul_frame_free(i8* %frame)', ir)
    ir = re.sub(r'(@rul_clear_count\(i8\* %frame, i32 )\d+', r'\g<1>LIVE', ir)
    ir = re.sub(r'(@rul_frame_new\(i32 )\d+', r'\g<1>FRAME', ir)
    return re.sub(r'(@rul_slot\(i8\* %frame, i32 )\d+', r'\g<1>SLOT', ir)


def frames(ir):
    return [int(value) for value in re.findall(r'@rul_(?:local_)?frame_(?:new\(|init\(i8\* %frame, )i32 (\d+)\)', ir)]


def value_operations(ir):
    """Compare every value/control operation after resolving argument storage.

    Each pack is consumed immediately after its copies. Real forced-GC cases
    separately verify lifetime and ownership, including the negative controls.
    """
    aliases = dict(re.findall(r'(%pack\d+) = getelementptr i8, i8\* (%v\d+), i64 0', ir))
    first = None
    for line in ir.splitlines():
        match = re.search(r'@rul_args_set\(i8\* %argpack, i32 0, i8\* (%v\d+)\)', line)
        if match:
            first = match[1]
        if re.search(r'call void @rul_(?:init_)?(?:call|new|array|member_finish)\(', line):
            for pointer in re.findall(r'%pack\d+\b', line):
                if pointer not in aliases:
                    assert first is not None, line
                    aliases[pointer] = first
    output = []
    for line in ir.splitlines(True):
        if line.startswith('  ') and (
                re.search(r'@(?:llvm\.lifetime\.|rul_(?:local_)?(?:frame_|slot\(|clear))', line)
                or re.search(r'@rul_args_(?:size|set)\(', line)
                or re.match(r'  %(?:frame|value_storage\d+|argpack|pack\d+) = (?:alloca|getelementptr)', line)):
            continue
        output.append(re.sub(r'%pack\d+\b', lambda item: aliases.get(item[0], item[0]), line))
    return ''.join(output)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_identity(path):
    path = Path(path).resolve()
    content = path.read_bytes()
    return {'path':str(path), 'sha256':hashlib.sha256(content).hexdigest(), 'size':len(content)}


def verify_identities(identities):
    if any(file_identity(item['path']) != item for item in identities):
        raise AssertionError('slot gate build input changed during the production build')


def toolchain_identity(toolchain):
    commands = {'clang':toolchain.clang[0], **toolchain.tools}
    return {'version':toolchain.version, 'triple':toolchain.triple,
            'data_layout':toolchain.data_layout, 'clang':list(toolchain.clang),
            'tools':dict(toolchain.tools), 'link_flags':list(toolchain.link_flags),
            'executables':{name:file_identity(shutil.which(command) or command)
                           for name,command in commands.items()}}


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



NATIVE_HELPER_IMPORT = "密发射器 取 外言 'native_emit.ru'.\n"


def source_import_count(source):
    # Test-only lexical guard, not a Ru parser/application frontend. Ignore
    # strings and comments so generated source fragments are not dependencies.
    bare = re.sub(r"#[^\n]*|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"",
                  ' ', source, flags=re.S)
    return len(re.findall(r'(?<!\w)外言(?!\w)', bare))


def copy_negative_compiler(original, directory):
    """Freeze only the reviewed compiler + unchanged static native helper."""
    original, directory = Path(original), Path(directory)
    helper = original.with_name('native_emit.ru')
    for path in (original, helper):
        if path.is_symlink() or not path.is_file() or path.resolve().parent != original.parent.resolve():
            raise AssertionError('negative compiler dependency must be a local regular file')
    originals = [file_identity(path) for path in (original, helper)]
    source_bytes, helper_bytes = original.read_bytes(), helper.read_bytes()
    source, helper_source = source_bytes.decode('utf-8'), helper_bytes.decode('utf-8')
    if (not source.startswith(NATIVE_HELPER_IMPORT) or source_import_count(source) != 1
            or source_import_count(helper_source) != 0):
        raise AssertionError('negative compiler requires exactly the reviewed static native_emit import')
    copied, copied_helper = directory/'compiler.ru', directory/'native_emit.ru'
    if any(path.exists() or path.is_symlink() for path in (copied, copied_helper)):
        raise AssertionError('negative compiler destinations must be fresh')
    copied.write_bytes(bad_pure_ru_source(source).encode('utf-8'))
    copied_helper.write_bytes(helper_bytes)
    verify_identities(originals)
    copies = [file_identity(path) for path in (copied, copied_helper)]
    if copies[1]['sha256'] != originals[1]['sha256'] or copies[1]['size'] != originals[1]['size']:
        raise AssertionError('native helper copy differs from frozen original')
    return copied, {'mutation':'reset cursor at panic-transfer unwind emission',
        'original_source_sha256': originals[0]['sha256'],
        'mutated_source_sha256': copies[0]['sha256'],
        'topology':'compiler.ru plus exact unchanged native_emit.ru; no other imports',
        'original_inputs': originals, 'copied_inputs': copies}

def require_frozen_compiler_manifest(dependencies, frozen):
    # Match the production host's canonical filesystem identities, not the Ru
    # frontend's slash spelling. Do not let canonicalization collapse aliases.
    if (not isinstance(dependencies, list) or len(dependencies) != 2
            or any(not isinstance(path, str) or not Path(path).is_absolute()
                   or '..' in Path(path).parts for path in dependencies)):
        raise AssertionError('negative compiler manifest requires two absolute non-traversing paths')
    actual = {str(Path(path).resolve()) for path in dependencies}
    expected = {item['path'] for item in frozen}
    if len(actual) != 2 or len(frozen) != 2 or len(expected) != 2 or actual != expected:
        raise AssertionError('negative compiler manifest must match exact frozen two-file topology')
    verify_identities(frozen)


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
                new, new_runtime = lower(ContiguousSlots, source)
                uncached, uncached_runtime = lower(UncachedReuseSlots, source)
                self.assertEqual(normalize(old), normalize(uncached))
                self.assertEqual(canonical_addresses(uncached), new)
                self.assertEqual(old_runtime, uncached_runtime)
                self.assertEqual(old_runtime, new_runtime)
                independent, independent_runtime = lower(LLVMCompiler, source)
                self.assertEqual(value_operations(new), value_operations(independent))
                self.assertEqual(new_runtime, independent_runtime)
                self.assertEqual(len(frames(old)), len(frames(new)))
                self.assertTrue(all(new_size <= old_size for old_size,new_size in zip(frames(old),frames(new))))

    def test_ssa_unique_physical_bounds_and_highwater(self):
        ir, _ = lower(LLVMCompiler, combined()[0])
        for body in re.findall(r'define void @[^}]+}', ir):
            names = re.findall(r'^  (%\w+) =', body, re.M)
            self.assertEqual(len(names), len(set(names)))
            extent = frames(body)[0]
            indices = [int(value) for value in re.findall(r'@rul_(?:local_)?slot\(i8\* %frame, i32 (\d+)[,)]', body)]
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
        self._assert_negative_compiler_topology()

    def _assert_negative_compiler_topology(self):
        original = REPO/'bootstrap/compiler.ru'
        helper = original.with_name('native_emit.ru')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root/'copy'; target.mkdir()
            with prohibit_python_frontend():
                copied, record = copy_negative_compiler(original, target)
            with self.subTest(topology='exact helper and sole unsafe compiler mutation'):
                self.assertEqual(copied.read_bytes(), bad_pure_ru_source(original.read_bytes().decode()).encode())
                self.assertEqual((target/'native_emit.ru').read_bytes(), helper.read_bytes())
                verify_identities(record['original_inputs'] + record['copied_inputs'])
                self.assertEqual(source_import_count("# 外言 ignored\n显 '外言'."), 0)
            paths = [str(target/'compiler.ru'), str(target/'native_emit.ru')]
            require_frozen_compiler_manifest(paths, record['copied_inputs'])
            require_frozen_compiler_manifest([Path(path).as_posix() for path in paths], record['copied_inputs'])
            if os.name == 'nt':
                # Windows resolves case and any short temporary-root spelling
                # back to the same actual files; Linux remains case-sensitive.
                require_frozen_compiler_manifest([path.swapcase() for path in paths], record['copied_inputs'])
            invalid_manifests = [paths[:1], paths+paths[:1], [paths[0], paths[0]],
                [paths[0], str(root/'outside.ru')],
                [paths[0], str(target/'..'/'copy'/'native_emit.ru')],
                [paths[0], 'native_emit.ru']]
            for invalid_paths in invalid_manifests:
                with self.subTest(manifest=invalid_paths), self.assertRaises(AssertionError):
                    require_frozen_compiler_manifest(invalid_paths, record['copied_inputs'])

            for index, identity in enumerate(record['copied_inputs']):
                path = Path(identity['path']); before = path.read_bytes()
                with self.subTest(tampered_copy=index):
                    path.write_bytes(before+b'\n# changed')
                    with self.assertRaisesRegex(AssertionError, 'input changed'):
                        verify_identities(record['copied_inputs'])
                    path.write_bytes(before)
            fixtures = root/'fixtures'; fixtures.mkdir()
            compiler = fixtures/'compiler.ru'; dependency = fixtures/'native_emit.ru'
            source_bytes, helper_bytes = original.read_bytes(), helper.read_bytes()
            invalid = [
                (source_bytes.replace(b'native_emit.ru', b'../native_emit.ru', 1), helper_bytes),
                (source_bytes.replace(b'native_emit.ru', b'unknown.ru', 1), helper_bytes),
                (source_bytes + "\n另件 取 外言\n 'unknown.ru'.\n".encode(), helper_bytes),
                (source_bytes, helper_bytes + "\n另件 取 外言 'unknown.ru'.\n".encode()),
                (source_bytes, helper_bytes + "\n另件 取 外言 路径.\n".encode()),
            ]
            for index, (compiler_bytes, dependency_bytes) in enumerate(invalid):
                compiler.write_bytes(compiler_bytes); dependency.write_bytes(dependency_bytes)
                destination = root/('invalid-'+str(index)); destination.mkdir()
                with self.subTest(unknown_or_escape=index), prohibit_python_frontend():
                    with self.assertRaisesRegex(AssertionError, 'exactly the reviewed static'):
                        copy_negative_compiler(compiler, destination)
                    self.assertEqual(list(destination.iterdir()), [])
            compiler.write_bytes(source_bytes); dependency.write_bytes(helper_bytes)
            destination = root/'mutation'; destination.mkdir()
            mutation = bad_pure_ru_source
            def mutate_original(text):
                dependency.write_bytes(helper_bytes+b'\n# changed during copy')
                return mutation(text)
            with self.subTest(tampered_original='during copy'):
                with patch(__name__+'.bad_pure_ru_source', side_effect=mutate_original):
                    with self.assertRaisesRegex(AssertionError, 'input changed'):
                        copy_negative_compiler(compiler, destination)


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
            cls.report['toolchain'] = toolchain_identity(toolchain)
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
            copied, negative = copy_negative_compiler(REPO/'bootstrap/compiler.ru', negative_source)
            cls.report['pure_ru_negative'] = negative
            frozen_negative = negative['original_inputs'] + negative['copied_inputs']
            verify_identities(frozen_negative)
            broken = cls.pure_ru_build(toolchain, stage3, copied, 'stage3-unsafe-compiler',
                                      frozen_dependencies=negative['copied_inputs'])
            verify_identities(frozen_negative)
            binary = cls.pure_ru_build(toolchain, broken, source_path, 'stage3-unsafe-unwind')
            cls.execute('stage3-unsafe-unwind', binary)
            verify_identities(frozen_negative)
            if digest(stage3) != cls.report['stage3']['sha256']:
                raise AssertionError('stage3 changed during gate execution')
            verify_identities(cls.report['toolchain']['executables'].values())
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
    def pure_ru_build(cls, toolchain, frontend, source, label, *, frozen_dependencies=()):
        from tools import bootstrap
        if bootstrap.ROOT.resolve() != REPO:
            raise AssertionError('bootstrap host loaded from a different repository')
        directory = cls.output/label; directory.mkdir()
        binary = directory/'program.exe'
        evidence_path = directory/'build-evidence.json'
        tools = toolchain_identity(toolchain)
        headers = ('runtime.h','io_runtime.h','contest_runtime.h','practical_runtime.h','llvm_runtime.h')
        identities = [file_identity(path) for path in
            [frontend, source, REPO/'tools/bootstrap.py', REPO/'rulang/llvm_toolchain.py',
             REPO/'rulang/c_runtime.py', *[REPO/'rulang'/name for name in headers]]]
        identities.extend(tools['executables'].values())
        identities.extend(frozen_dependencies)
        verify_identities(identities)
        cls.report['builds'][label] = {'host':'tools.bootstrap.compile_native',
                                      'source_sha256':digest(source),
                                      'frontend_sha256':digest(frontend),
                                      'evidence_path':str(evidence_path),
                                      'forbidden_python_hooks':list(FORBIDDEN_FRONTEND_HOOKS)}
        capture = {}
        original_compile = toolchain.compile
        if getattr(original_compile, '__func__', None) is not LLVMToolchain.compile:
            raise AssertionError('slot capture requires the original LLVMToolchain.compile method')
        def capture_compile(program, runtime, stage, *args, **kwargs):
            if capture:
                raise AssertionError('production host compiled more than once')
            source_manifest = (Path(stage)/'sources.json').read_bytes()
            dependencies = json.loads(source_manifest.decode('utf-8'))
            if not isinstance(dependencies, list) or not all(isinstance(path,str) and Path(path).is_absolute() for path in dependencies):
                raise AssertionError('invalid actual frontend source manifest')
            if frozen_dependencies:
                require_frozen_compiler_manifest(dependencies, frozen_dependencies)
            dependency_identities = [file_identity(path) for path in sorted(set(dependencies) | {str(Path(source).resolve())})]
            (directory/'actual-program.ll').write_text(program, encoding='utf-8', newline='\n')
            (directory/'actual-runtime.c').write_text(runtime, encoding='utf-8', newline='\n')
            (directory/'actual-sources.json').write_bytes(source_manifest)
            capture.update({'ir_sha256':hashlib.sha256(program.encode('utf-8')).hexdigest(),
                'runtime_sha256':hashlib.sha256(runtime.encode('utf-8')).hexdigest(),
                'source_manifest_sha256':hashlib.sha256(source_manifest).hexdigest(),
                'dependencies':dependency_identities,
                'compile_options':{'positional':list(args), 'keyword':dict(kwargs)}})
            # Observe only: pass all actual inputs unchanged to the existing
            # production compiler. No runtime reconstruction or alternate chain.
            native, standalone = original_compile(program, runtime, stage, *args, **kwargs)
            verify_identities(dependency_identities)
            capture.update({'binary_sha256':digest(native), 'standalone_ir_sha256':digest(standalone)})
            return native, standalone
        cls.persist()
        started = time.perf_counter()
        try:
            with prohibit_python_frontend(), patch.object(toolchain, 'compile', side_effect=capture_compile):
                host_return = bootstrap.compile_native(frontend, source, binary, toolchain,
                    keep_frontend=True, emit_llvm=directory/'standalone.ll')
        finally:
            cls.report['builds'][label]['total_seconds'] = time.perf_counter()-started
            cls.persist()
        verify_identities(identities)
        if toolchain_identity(toolchain) != tools:
            raise AssertionError('selected LLVM toolchain configuration changed during the production build')
        if not capture or 'binary_sha256' not in capture:
            raise AssertionError('production host did not complete the original LLVM compile')
        frontend_ir = binary.with_name(binary.name+'.frontend.ll')
        metadata = binary.with_name(binary.name+'.metadata.c')
        if (host_return['source_ir_sha256'] != capture['ir_sha256'] or digest(frontend_ir) != capture['ir_sha256']
                or host_return['binary_sha256'] != capture['binary_sha256'] or digest(binary) != capture['binary_sha256']
                or host_return['metadata_sha256'] != digest(metadata)
                or digest(directory/'standalone.ll') != capture['standalone_ir_sha256']):
            raise AssertionError('production host return/artifacts disagree with actual compile inputs or outputs')
        evidence = {'schema':'slot-test-capture-main-host-v1', 'host_return':host_return,
                    'input_identities':identities, 'toolchain':tools, 'actual_compile':capture,
                    'observation':'test-only capture of original production compile; not a production build proof; '
                                  'dependency hashes observed after frontend and checked after compile, not per-read snapshots'}
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        cls.report['builds'][label].update({'binary_sha256':digest(binary),
            'ir_sha256':capture['ir_sha256'],'runtime_sha256':capture['runtime_sha256'],
            'emission_seconds':host_return['frontend_seconds'],
            'compile_seconds':host_return['seconds']-host_return['frontend_seconds'],
            'evidence_sha256':digest(evidence_path), 'host_return':host_return,
            'frame_extents':frames(frontend_ir.read_text(encoding='utf-8'))})
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
        # Argument storage can change which value overwrites the live callee
        # slot: a non-function, or the one-argument inner function 等.
        # Require this specific first-case corruption, not any runtime failure.
        self.assertRegex(result.stderr, r'值不是函数|函数「等」需要 1 个位置实参，收到 3 个')
        self.assertTrue(gc_zero(result.stderr), result.stderr)

    def test_stage3_unsafe_unwind_reset_is_rejected(self):
        result = self.outputs['stage3-unsafe-unwind']
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, CASES[0][0]+'\n')
        self.assertRegex(result.stderr, r'值不是函数|函数「等」需要 1 个位置实参，收到 3 个')
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
