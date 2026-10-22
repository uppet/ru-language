"""Source-driven dense path tests, separate from historical fixed-kernel evidence."""
import copy
import ctypes as C
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from rulang.compiler import Compiler
from rulang.frontend import RuError, parse
from rulang.modules import load_module_graph
from rulang.mi_ir import EFFECTS, VIEW
from rulang.mi_source import MiSourcePlan

SCAN = (HERE / 'ascii.ru').read_text(encoding='utf-8')
SPEC = json.loads((HERE / 'manifest.json').read_text(encoding='utf-8'))['functions'][0]


def run(command, **kwargs):
    result = subprocess.run(command, text=True, encoding='utf-8', capture_output=True, timeout=120, **kwargs)
    if result.returncode: raise AssertionError(result.stdout + result.stderr)
    return result


def portable(source):
    if os.name == 'nt': return source
    from test_native_c_runtime import TEST_PLATFORM
    source, n = re.subn(r'/\* RU_NATIVE_PLATFORM_BEGIN \*/.*?/\* RU_NATIVE_PLATFORM_END \*/', lambda _: TEST_PLATFORM, source, flags=re.S)
    assert n == 1
    guard = '#error "Ru native C requires Windows x64"'
    assert source.count(guard) == 1
    return source.replace(guard, '/* test-only POSIX owner fixture, NOT Windows ABI evidence */')


def compile_c(source, directory, *, shared=False):
    directory = Path(directory)
    cfile = directory / 'test.c'
    output = directory / ('test.dll' if shared and os.name == 'nt' else 'test.so' if shared else 'test.exe' if os.name == 'nt' else 'test')
    cfile.write_text(source, encoding='utf-8', newline='\n')
    command = [os.environ.get('CC', 'gcc'), '-std=c99', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-pedantic']
    if shared: command += ['-shared'] + ([] if os.name == 'nt' else ['-fPIC'])
    if os.environ.get('MI_UBSAN'): command += ['-fsanitize=undefined', '-fno-sanitize-recover=all']
    command += [str(cfile), '-lm']
    if os.name != 'nt': command += ['-ldl', '-pthread']
    run(command + ['-o', str(output)])
    return output


class SourceTests(unittest.TestCase):
    def fixture(self, source=SCAN, spec=None, caller=None):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        directory = Path(temp.name)
        (directory / 'ascii.ru').write_text(source, encoding='utf-8')
        document = {'version': 1, 'functions': [copy.deepcopy(spec or SPEC)]}
        manifest = directory / 'manifest.json'; manifest.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
        entry = directory / ('caller.ru' if caller else 'ascii.ru')
        if caller: entry.write_text(caller, encoding='utf-8')
        ast = parse(entry.read_text(encoding='utf-8'))
        graph = load_module_graph(entry, ast)
        plan = MiSourcePlan(graph, manifest)
        return directory, entry, ast, graph, manifest, plan

    def compile_program(self, source=SCAN, spec=None, caller=None):
        fixture = self.fixture(source, spec, caller)
        directory, entry, ast, graph, manifest, _ = fixture
        compiler = Compiler(ast, str(entry), modules=graph, allow_native=True, mi_manifest=manifest)
        generated = compiler.compile()
        binary = compile_c(portable(generated) if compiler.native_enabled else generated, directory)
        return fixture, compiler, generated, binary

    def test_ordinary_caller_imported_source_gc(self):
        caller = (HERE / 'caller.ru').read_text(encoding='utf-8')
        _, _, generated, binary = self.compile_program(caller=caller)
        result = run([str(binary)], env=dict(os.environ, RU_GC_THRESHOLD='1', RU_GC_STATS='1'))
        self.assertEqual(result.stdout, '3\n')
        self.assertIn('RU_GC live=0', result.stderr)
        self.assertIn('ru_mi_kernel_0(mi_borrow.view, mi_p1, mi_p2)', generated)
        self.assertLess(generated.index('ru_mi_release(&mi_borrow);'), generated.index('if (mi_result.status != RU_MI_OK)'))

    def test_c_js_random_differential_and_all_bytes(self):
        directory, _, _, _, _, plan = self.fixture()
        source = plan.compute_source('c') + '\nRuMiResult test_call(const uint8_t *data, uint32_t length, uint32_t begin, uint32_t end) { return ru_mi_kernel_0((RuMiView){data,length},begin,end); }\n'
        binary = compile_c(source, directory, shared=True)
        class Result(C.Structure): _fields_ = [('status', C.c_int), ('value', C.c_uint32), ('line', C.c_uint32), ('col', C.c_uint32)]
        library = C.CDLL(str(binary)); fn = library.test_call
        if os.name == 'nt':
            # Windows locks loaded DLL files; release before TemporaryDirectory cleanup.
            import _ctypes
            self.addCleanup(_ctypes.FreeLibrary, library._handle)
        fn.argtypes = [C.POINTER(C.c_uint8), C.c_uint32, C.c_uint32, C.c_uint32]; fn.restype = Result
        rng = random.Random(20261022)
        rows = [{'data': [b], 'begin': 0, 'end': 1} for b in range(256)]
        rows += [{'data': [], 'begin': 0, 'end': 0}]
        for _ in range(600):
            data = [rng.randrange(256) if rng.random() < .2 else rng.randrange(32, 127) for _ in range(rng.randrange(96))]
            begin = rng.randrange(len(data) + 1); end = rng.randrange(begin, len(data) + 1)
            rows.append(dict(data=data, begin=begin, end=end))
        (directory / 'kernel.js').write_text(plan.compute_source('js'), encoding='utf-8')
        (directory / 'driver.js').write_text("const k=require('./kernel.js');const fs=require('fs');console.log(JSON.stringify(JSON.parse(fs.readFileSync(0,'utf8')).map(r=>k.ru_mi_kernel_0(Uint8Array.from(r.data),r.begin,r.end))));", encoding='utf-8')
        js = json.loads(run(['node', str(directory / 'driver.js')], input=json.dumps(rows)).stdout)
        for row, actual_js in zip(rows, js):
            data, begin, end = row['data'], row['begin'], row['end']; expected = 0
            for byte in data[begin:end]:
                if byte >= 128 or byte in (13, 10, 62): break
                expected += 1
            memory = (C.c_uint8 * len(data))(*data); actual_c = fn(memory, len(data), begin, end)
            self.assertEqual((actual_c.status, actual_c.value), (0, expected), row)
            self.assertEqual(actual_js, dict(status=0, value=expected, line=0, col=0), row)
        # Kernel load check and checked subtraction retain exact source locations.
        memory = (C.c_uint8 * 1)(65)
        self.assertEqual((fn(memory, 1, 0, 2).status, fn(memory, 1, 0, 2).line), (1, 5))
        self.assertEqual((fn(memory, 1, 1, 0).status, fn(memory, 1, 1, 0).line), (2, 4))

    def test_rename_constants_conditions_drive_generated_results(self):
        caller = "密 取 外言 '如:密'. 核 取 外言 './ascii.ru'. 缓冲 取 密 其 UTF8 'abc>xyz?'. 显 核 其 {name} 缓冲 0 8. 缓冲 其 关闭."
        variants = [(SCAN, SPEC, 3)]
        spec = copy.deepcopy(SPEC); spec['function'] = '改名'; spec['params'] = {'输入': VIEW, '起点': 'u32', '终点': 'u32'}; spec['ranges'] = [{'view':'输入','begin':'起点','end':'终点'}]
        modified = SCAN.replace('ASCII段', '改名').replace('字节', '输入').replace('始', '起点').replace('终', '终点').replace('== 62', '== 63')
        variants.append((modified, spec, 7))
        variants.append((SCAN.replace('项 == 62', '项 != 62'), SPEC, 0))
        for source, spec, expected in variants:
            fixture, _, _, binary = self.compile_program(source, spec, caller.format(name=spec['function']))
            self.assertEqual(run([str(binary)]).stdout, f'{expected}\n')
            self.assertEqual(fixture[-1].records[0]['ir']['params'], spec['params'])

    def test_scalar_signature_not_named_seed_count_length(self):
        spec = {'module':'ascii.ru', 'function':'加', 'params':{'右':'u32','左':'u32'}, 'result':'u32','effects':EFFECTS}
        caller = "核 取 外言 './ascii.ru'. 显 核 其 加 3 4."
        _, _, generated, binary = self.compile_program('算 加 右 左: 未用 取 右. 得 右 + 左. 法.', spec, caller)
        self.assertEqual(run([str(binary)]).stdout, '7\n')
        self.assertNotIn('RuNative', generated)
        self.assertNotIn('ru_mi_acquire', generated)

    def test_zero_parameter_ordinary_wrapper_exact_return(self):
        spec = {'module':'ascii.ru','function':'常数','params':{},'result':'u32','effects':EFFECTS}
        _, _, _, binary = self.compile_program('算 常数: 得 4294967295. 法.', spec, "核 取 外言 './ascii.ru'. 显 核 其 常数.")
        self.assertEqual(run([str(binary)]).stdout, '4294967295\n')

    def test_dead_local_keeps_checked_overflow(self):
        spec = {'module':'ascii.ru','function':'核','params':{'值':'u32'},'result':'u32','effects':EFFECTS}
        source = '算 核 值: 若 真 则 丢弃 取 值 + 1. 然. 得 值. 法.'
        caller = "模 取 外言 './ascii.ru'. 显 模 其 核 7. 显 模 其 核 4294967295."
        _, _, _, binary = self.compile_program(source, spec, caller)
        result = subprocess.run([str(binary)], text=True, encoding='utf-8', capture_output=True, timeout=20)
        self.assertEqual(result.stdout, '7\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('status=2', result.stderr)
        self.assertIn('ascii.ru:1:', result.stderr)

    def test_zero_truth_and_short_circuit_checked_load(self):
        source = '算 试验 字节 始 终: 若 0 则 若 真 或 字节[终] == 1 则 得 7. 然. 然. 得 0. 法.'
        spec = copy.deepcopy(SPEC); spec['function'] = '试验'
        caller = "密 取 外言 '如:密'. 核 取 外言 './ascii.ru'. 缓冲 取 密 其 缓冲 1. 显 核 其 试验 缓冲 1 1. 缓冲 其 关闭."
        _, _, _, binary = self.compile_program(source, spec, caller)
        self.assertEqual(run([str(binary)]).stdout, '7\n')

    def test_exact_integer_token_ignores_ordinary_float(self):
        spec = {'module':'ascii.ru', 'function':'界', 'params':{}, 'result':'u32','effects':EFFECTS}
        directory, entry, ast, graph, manifest, _ = self.fixture('算 界: 得 4294967295. 法.', spec)
        ast[0].data['body'][0].data['expr'].data['value'] = -999.0
        plan = MiSourcePlan(graph, manifest)
        self.assertIn('4294967295u', plan.compute_source('c'))
        with self.assertRaisesRegex(RuError, '9007199254740993'):
            self.fixture('算 界: 得 9007199254740993. 法.', spec)

    def test_rejected_ast_effects_and_source_locations(self):
        examples = ['显 始. 得 始.', '得 字节.', '副本 取 字节. 得 始.', '字节[始] 取 0. 得 始.', '得 外部 始.', '得 (算: 得 1. 法).', '循 破. 环. 得 始.', '得 始 / 2.']
        for body in examples:
            with self.subTest(body=body), self.assertRaises(RuError) as caught:
                self.fixture('算 ASCII段 字节 始 终:\n    ' + body + '\n法.')
            self.assertGreaterEqual(caught.exception.line, 2)
            self.assertGreater(caught.exception.col, 0)
            self.assertTrue(caught.exception.source_name.endswith('ascii.ru'))

    def test_manifest_and_inferred_local_types_are_fixed(self):
        spec = {'module':'ascii.ru','function':'核','params':{'字节':VIEW},'result':'u32','effects':EFFECTS,'locals':{'长度':'u8'}}
        with self.assertRaisesRegex(RuError, '类型不匹配') as caught:
            self.fixture('算 核 字节:\n 长度 取 字节 其 量.\n 得 长度.\n法.', spec)
        self.assertEqual(caught.exception.line, 2)
        spec.pop('locals')
        with self.assertRaisesRegex(RuError, '类型不匹配') as caught:
            self.fixture('算 核 字节:\n 长度 取 字节[0].\n 长度 取 字节 其 量.\n 得 0.\n法.', spec)
        self.assertEqual(caught.exception.line, 3)

    def test_manifest_invalid_shapes_reject_cleanly(self):
        _, _, _, graph, manifest, _ = self.fixture()
        variants = [{'result': []}, {'params': []}, {'params': {'字节':[]}}, {'locals':[]}, {'ranges':{}}, {'ranges':[{'view':[],'begin':'始','end':'终'}]}, {'effects':[]}, {'module':[]}, {'function':[]}, {'params':{'字节':VIEW,'始':'u32','终':'u32','另一':VIEW}}]
        for changes in variants:
            spec = {**copy.deepcopy(SPEC), **changes}; manifest.write_text(json.dumps({'version':1,'functions':[spec]}), encoding='utf-8')
            with self.subTest(changes=changes), self.assertRaises(RuError): MiSourcePlan(graph, manifest)

    def test_same_name_module_identity_and_duplicate_manifest(self):
        caller = "甲 取 外言 './ascii.ru'. 乙 取 外言 './other.ru'. 显 甲 其 ASCII段 [65,62] 0 2. 显 乙 其 ASCII段 2."
        directory, entry, ast, graph, manifest, _ = self.fixture()
        (directory / 'other.ru').write_text('算 ASCII段 值: 得 值 + 100. 法.', encoding='utf-8')
        (directory / 'caller.ru').write_text(caller, encoding='utf-8')
        entry = directory / 'caller.ru'; ast = parse(caller); graph = load_module_graph(entry, ast)
        plan = MiSourcePlan(graph, manifest)
        self.assertEqual(len(plan.functions), 1)
        self.assertEqual(plan.records[0]['module'], str((directory / 'ascii.ru').resolve()))
        manifest.write_text(json.dumps({'version':1,'functions':[SPEC, SPEC]}), encoding='utf-8')
        with self.assertRaisesRegex(RuError, '重复'): MiSourcePlan(graph, manifest)

    def test_ordinary_output_unchanged_without_manifest(self):
        directory, entry, ast, graph, _, _ = self.fixture()
        generated = Compiler(ast, str(entry), modules=graph).compile()
        self.assertNotIn('RuMi', generated)
        self.assertNotIn('ru_mi_', generated)

    def test_failure_release_and_source_span(self):
        spec = copy.deepcopy(SPEC); spec.pop('ranges')
        source = '算 ASCII段 字节 始 终:\n    得 终 + 1.\n法.'
        directory, entry, ast, graph, manifest, plan = self.fixture(source, spec, "密 取 外言 '如:密'. 核 取 外言 './ascii.ru'.")
        compiler = Compiler(ast, str(entry), modules=graph, allow_native=True, full_runtime=True, mi_manifest=manifest)
        generated = compiler.compile(); function = compiler.function_ids[id(compiler.mi_plan.records[0]['node'])]
        probe = r'''
int main(void) {
    ru_init(); (void)ru_native_builtins(ru_contest_builtins());
    Val memory = rn_memory(NULL, 3, 1);
    RuNative *object = (RuNative *)memory.heap;
    Val args[] = {memory, v_num(0), v_num(4294967295.0)};
    RuNativeTrap trap = {0}; ru_native_trap = &trap;
    if (!setjmp(trap.jump)) { (void)FUNCTION(NULL, v_null(), 777, args); return 10; }
    ru_native_trap = NULL;
    if (ru_mi_active_borrows || object->as.memory.mi_read_borrows) return 11;
    if (!strstr(trap.message, "ascii.ru:2:") || !strstr(trap.message, "列=")) return 12;
    args[2] = v_num(2);
    Val result = FUNCTION(NULL, v_null(), 1, args);
    if (result.kind != RU_NUM || result.n != 3) return 13;
    v_drop(result);
    args[1] = v_num(NAN); ru_native_trap = &trap;
    if (!setjmp(trap.jump)) { (void)FUNCTION(NULL, v_null(), 1, args); return 14; }
    ru_native_trap = NULL;
    if (ru_mi_active_borrows || object->as.memory.mi_read_borrows) return 15;
    args[1] = v_num(0);
    RuMiSourceBorrow borrow = ru_mi_acquire(memory, ru_mi_memory(memory, 1), 1);
    ru_native_trap = &trap;
    if (!setjmp(trap.jump)) { Val ignored; (void)ru_native_member(memory, "关闭", 0, NULL, NULL, 1, &ignored); return 16; }
    ru_native_trap = NULL;
    if (ru_mi_active_borrows != 1 || object->as.memory.mi_read_borrows != 1 || object->closed) return 17;
    ru_mi_release(&borrow);
    Val ignored; (void)ru_native_member(memory, "关闭", 0, NULL, NULL, 1, &ignored); v_drop(ignored);
    ru_native_trap = &trap;
    if (!setjmp(trap.jump)) { (void)FUNCTION(NULL, v_null(), 1, args); return 18; }
    ru_native_trap = NULL;
    if (ru_mi_active_borrows || object->as.memory.mi_read_borrows) return 19;
    v_drop(memory); ru_shutdown(); puts("failure released; retry passed"); return 0;
}
'''.replace('FUNCTION', function)
        generated = generated[:generated.index('int main(int argc, char **argv) {')] + probe
        binary = compile_c(portable(generated), directory)
        result = run([str(binary)], env=dict(os.environ, RU_GC_THRESHOLD='1', RU_GC_STATS='1'))
        self.assertIn('failure released; retry passed', result.stdout)
        self.assertIn('RU_GC live=0', result.stderr)

    def test_generator_bad_manifest_and_external_module_identity(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        directory = Path(temp.name); config = directory / 'config'; config.mkdir()
        manifest = config / 'manifest.json'
        generator = ROOT / 'experiments/mi_kernel/generate.py'
        for bad in ({}, {'version':1,'functions':[None]}, {'version':1,'functions':[{'module':[]}]}):
            manifest.write_text(json.dumps(bad), encoding='utf-8')
            result = subprocess.run([sys.executable, str(generator), '--manifest', str(manifest), '--out', str(directory / 'out')], capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('Traceback', result.stderr)
            self.assertIn('编译错误', result.stderr)
            self.assertFalse((directory / 'out').exists())
        functions = []
        for name in ('a', 'b'):
            child = directory / name; child.mkdir()
            (child / 'same.ru').write_text('算 同名 值: 得 值. 法.', encoding='utf-8')
            functions.append({'module':'../'+name+'/same.ru','function':'同名','params':{'值':'u32'},'result':'u32','effects':EFFECTS})
        manifest.write_text(json.dumps({'version':1,'functions':functions}), encoding='utf-8')
        run([sys.executable, str(generator), '--manifest', str(manifest), '--out', str(directory / 'out')])
        records = json.loads((directory / 'out/ir.json').read_text(encoding='utf-8'))
        self.assertEqual([r['module'] for r in records], ['../a/same.ru','../b/same.ru'])

    def test_boundary_rejects_before_narrowing_or_borrow(self):
        caller_prefix = "密 取 外言 '如:密'. 核 取 外言 './ascii.ru'. 缓冲 取 密 其 缓冲 3. "
        for args, message in [('缓冲 (-1) 2', '精确范围'), ('缓冲 0 4294967296', '精确范围'), ('缓冲 2 1', '起止范围'), ('缓冲 0 4', '起止范围'), ('[1,2] 0 2', 'NativeMemory')]:
            with self.subTest(args=args):
                _, _, _, binary = self.compile_program(caller=caller_prefix + '显 核 其 ASCII段 ' + args + '.')
                result = subprocess.run([str(binary)], text=True, encoding='utf-8', capture_output=True, timeout=20)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)


if __name__ == '__main__':
    suite = unittest.main(verbosity=2, exit=False)
    evidence = {'tests': suite.result.testsRun, 'errors': len(suite.result.errors), 'failures': len(suite.result.failures), 'success': suite.result.wasSuccessful(), 'platform':sys.platform, 'native_windows_execution':os.name == 'nt', 'posix_adapter_is_test_only':os.name != 'nt', 'js_scope':'compute semantics only, not ordinary NativeMemory bridge', 's1_complete':False, 'mode':'ubsan' if os.environ.get('MI_UBSAN') else 'ordinary'}
    out = HERE / 'test-output'; out.mkdir(exist_ok=True)
    (out / (evidence['mode'] + '.json')).write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
    raise SystemExit(0 if suite.result.wasSuccessful() else 1)
