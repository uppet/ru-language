"""Dense host data-only contract; fake frontend is NOT native release evidence."""
from contextlib import ExitStack
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import bootstrap
from tools import bootstrap_dense_protocol as dense


class DenseHostTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.source = self.root/'main.ru'
        # Intentionally not valid Ru: host must not even try to parse it.
        self.source.write_bytes(b'HOST MUST NOT PARSE THIS application source')
        self.compiler = self.root/'compiler'
        self.compiler.write_bytes(b'opaque native compiler')
        self.output = self.root/'output'
        self.output.write_bytes(b'old output')
        self.manifest = self.root/'manifest.json'
        self.document = {'version': 1, 'functions': [{
            'module': 'main.ru', 'function': '计算',
            'params': {'文': 'borrow_ro_utf8', '始': 'u32', '终': 'u32'},
            'result': 'u32', 'effects': dense.EFFECTS,
            'ranges': [{'view': '文', 'begin': '始', 'end': '终'}]}]}
        self.save()
        self.calls = []
        self.change = lambda: None
        self.plan_change = lambda plan: plan
        self.metadata = dense.MARKER + '\n/* frontend generated bridges */\n'
        self.ir = 'target triple = "x86_64-unknown-linux-gnu"\ntarget datalayout = "layout"\n'
        self.toolchain = SimpleNamespace(triple='x86_64-unknown-linux-gnu', data_layout='layout', compile=self.compile)

    def save(self):
        self.manifest.write_text(json.dumps(self.document, ensure_ascii=False), encoding='utf-8')

    def compile(self, ir, runtime, stage):
        self.runtime = runtime
        binary, linked = stage/'binary', stage/'linked.ll'
        binary.write_bytes(b'new output')
        linked.write_text(ir, encoding='utf-8')
        return binary, linked

    def frontend(self, args, **kwargs):
        self.calls.append(args)
        Path(args[2]).write_text(self.ir, encoding='utf-8')
        Path(args[3]).write_text(self.metadata, encoding='utf-8')
        Path(args[7]).write_text(json.dumps([self.source.as_posix()]), encoding='utf-8')
        if dense.FLAG in args:
            at = args.index(dense.FLAG)
            packet = json.loads(Path(args[at+1]).read_text(encoding='utf-8'))
            rows = [[r[1], r[2], str(i), 'boot_dense_'+str(i), *r[3:]] for i, r in enumerate(packet[3])]
            plan = self.plan_change([dense.PROTOCOL, packet[1], rows])
            Path(args[at+2]).write_bytes(dense.plan_bytes(plan))
        self.change()
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    def invoke(self, platform='linux', **kwargs):
        with ExitStack() as stack:
            for name in ('rulang.frontend.parse', 'rulang.modules.load_module_graph',
                         'rulang.compiler.Compiler.compile', 'rulang.llvm_compiler.LLVMCompiler.compile',
                         'rulang.cli.build', 'rulang.native_c.NativeCPlan.__init__',
                         'rulang.native_c.NativeCPlan.emit_c', 'rulang.mi_source.read_manifest',
                         'rulang.mi_source.MiSourcePlan.__init__', 'rulang.mi_source.SourceLowerer.__init__',
                         'rulang.mi_ir.lower', 'rulang.mi_llvm.lower', 'rulang.mi_llvm.Emitter.__init__'):
                stack.enter_context(patch(name, side_effect=AssertionError('forbidden Python source processing: '+name)))
            stack.enter_context(patch.object(bootstrap.subprocess, 'run', side_effect=self.frontend))
            stack.enter_context(patch.object(bootstrap.sys, 'platform', platform))
            return bootstrap.compile_native(self.compiler, self.source, self.output, self.toolchain,
                                            experimental_mi_manifest=self.manifest, **kwargs)

    def test_dense_only_data_transport_and_proof(self):
        evidence = self.invoke(proof=self.root/'proof.json')
        self.assertEqual(len(self.calls[0]), 11)
        self.assertEqual(self.calls[0][8], dense.FLAG)
        self.assertNotIn('--allow-native=bootstrap-native-v1', self.calls[0])
        self.assertNotIn('ru_native_callback_dispatch', self.runtime)
        self.assertIn('boot_dense_utf8', self.runtime)
        packet = evidence['dense_transport']
        self.assertEqual(len(packet), 4)
        self.assertEqual(len(packet[3][0]), 8)
        self.assertEqual(len(evidence['dense_selected_plan']), 3)
        self.assertEqual(len(evidence['dense_selected_plan'][2][0]), 9)
        self.assertEqual(packet[3][0][3], [['文','borrow_ro_utf8'],['始','u32'],['终','u32']])
        self.assertEqual(evidence['dense_packet']['sha256'], hashlib.sha256(dense.packet_bytes(packet)).hexdigest())
        self.assertEqual(json.loads((self.root/'proof.json').read_text(encoding='utf-8')), evidence)
        self.assertIn('does not exclude ABA', evidence['input_identity_scope'])
        self.assertEqual(self.output.read_bytes(), b'new output')

    def test_combined_native_dense_marker_and_option_order(self):
        self.toolchain.triple = 'x86_64-pc-windows-msvc'
        self.ir = 'target triple = "' + self.toolchain.triple + '"\ntarget datalayout = "layout"\n'
        native = '/* RU_BOOTSTRAP_NATIVE_V1 ' + self.toolchain.triple + ' */\n'
        self.metadata = native + dense.MARKER + '\n'
        self.invoke(platform='win32', allow_native=True)
        self.assertEqual(self.calls[0][8:10], ['--allow-native=bootstrap-native-v1', dense.FLAG])
        self.assertIn('ru_native_callback_dispatch', self.runtime)
        for metadata in (native + native + dense.MARKER, native + dense.MARKER + native):
            self.metadata = metadata
            with self.assertRaises(ValueError):
                self.invoke(platform='win32', allow_native=True)

    def test_fixed_protocol_count_and_size_limits(self):
        original = copy.deepcopy(self.document)
        for field, value in [('params', {str(i):'u32' for i in range(65)}),
                             ('locals', {str(i):'u32' for i in range(65)}),
                             ('ranges', [{}] * 65), ('function', 'x'*257)]:
            self.document = copy.deepcopy(original)
            self.document['functions'][0][field] = value
            self.save()
            with self.subTest(field=field), self.assertRaises(ValueError):
                dense.prepare_transport(self.manifest, [self.source])
        self.document = original
        self.document['functions'] *= 257
        self.save()
        with self.assertRaises(ValueError):
            dense.prepare_transport(self.manifest, [self.source])
        with self.assertRaises(ValueError):
            dense.prepare_transport(self.manifest, [self.source]*10001)
        for value in (['x'*4097], ['x'*4096]*257):
            with self.assertRaises(ValueError):
                dense.packet_bytes(value)
        nested = ['x']
        for _ in range(17):
            nested = [nested]
        with self.assertRaises(ValueError):
            dense.packet_bytes(nested)
        with patch.object(dense, 'MAX_NODES', 3), self.assertRaises(ValueError):
            dense.packet_bytes(['a','b','c'])
        with patch.object(dense, 'SOURCE_BYTES', 2), self.assertRaises(ValueError):
            dense.inventory(self.source, [])

    def test_manifest_frozen_before_data_read(self):
        original = dense.prepare_transport
        def mutate(*args):
            result = original(*args)
            self.manifest.write_text('{}', encoding='utf-8')
            return result
        with patch.object(dense, 'prepare_transport', side_effect=mutate), self.assertRaises((ValueError, RuntimeError)):
            self.invoke()
        self.assertFalse(self.calls)

    def test_noncanonical_frontend_dependency_rejected(self):
        original = self.frontend
        def frontend(args, **kwargs):
            result = original(args, **kwargs)
            Path(args[7]).write_text(json.dumps([str(self.root)+'/./main.ru']), encoding='utf-8')
            return result
        self.frontend = frontend
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertEqual(self.output.read_bytes(), b'old output')

    def test_shared_target_matrix_and_host_platform_match(self):
        matrix = json.loads((bootstrap.ROOT/'tests/fixtures/dense/targets.json').read_text(encoding='utf-8'))
        for triple in matrix['accepted']:
            self.toolchain.triple = triple
            self.ir = 'target triple = "'+triple+'"\ntarget datalayout = "layout"\n'
            platform = 'win32' if 'windows' in triple else 'linux'
            with self.subTest(triple=triple):
                self.invoke(platform=platform)
                with self.assertRaises(ValueError):
                    self.invoke(platform='linux' if platform == 'win32' else 'win32')
        for triple in matrix['rejected']:
            self.toolchain.triple = triple
            for platform in ('linux','win32'):
                with self.subTest(triple=triple,platform=platform), self.assertRaises(ValueError):
                    self.invoke(platform=platform)

    def test_dense_input_hashing_never_uses_unbounded_generic_identity(self):
        with patch.object(bootstrap, 'file_identity', side_effect=AssertionError('unbounded input identity')):
            self.invoke()

    def test_oversize_sparse_inputs_rejected_before_read_or_frontend(self):
        for path, limit in ((self.manifest,dense.JSON_BYTES),(self.source,dense.SOURCE_BYTES)):
            before = path.read_bytes()
            with path.open('r+b') as stream:
                stream.truncate(limit+1)
            with self.subTest(path=path), patch.object(bootstrap,'file_identity',side_effect=AssertionError('unbounded read')):
                with self.assertRaises(ValueError):
                    self.invoke()
            path.write_bytes(before)
        self.assertFalse(self.calls)

    def test_stream_identity_limit_survives_growth_after_stat(self):
        old = dense.identity(self.source)
        with self.source.open('r+b') as stream:
            stream.truncate(dense.SOURCE_BYTES+1)
        with self.assertRaises(ValueError):
            dense.verify([old])
        with self.assertRaises(ValueError):
            dense.identity(self.source,limit=old['size'])

    def test_plan_canonical_bytes_and_reconstructable_proof_hashes(self):
        evidence = self.invoke()
        dense.verify_proof_hashes(evidence)
        for field in ('dense_packet','dense_plan'):
            bad = copy.deepcopy(evidence)
            bad[field]['sha256'] = '0'*64
            with self.assertRaises(ValueError):
                dense.verify_proof_hashes(bad)
        canonical = dense.plan_bytes(evidence['dense_selected_plan'])
        path = self.root/'plan.json'
        for data in (canonical.rstrip(b'\n'),canonical+b'\n',b' '+canonical,
                     json.dumps(evidence['dense_selected_plan'], ensure_ascii=False).encode()+b'\n'):
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                dense.validate_plan(path,evidence['dense_transport'])

    def test_missing_repeated_or_wrong_data_layout_rejected(self):
        triple = 'target triple = "x86_64-unknown-linux-gnu"\n'
        for layout in ('', 'target datalayout = "wrong"\n', 'target datalayout = "layout"\n'*2):
            self.ir = triple + layout
            with self.subTest(layout=layout), self.assertRaises(ValueError):
                self.invoke()
        self.assertEqual(self.output.read_bytes(),b'old output')

    def test_host_does_not_decide_eligibility(self):
        self.document['functions'][0]['params'] = {'a': 'borrow_ro_utf8', 'b': 'borrow_ro_utf8'}
        self.save()
        # A real frontend rejects this: host just transports the declared types.
        packet = dense.prepare_transport(self.manifest, [self.source])
        self.assertEqual(len(packet[3][0][3]), 2)

    def test_manifest_mutation_after_frontend_preserves_output(self):
        self.change = lambda: self.manifest.write_bytes(b'{}')
        with self.assertRaises((ValueError, RuntimeError)):
            self.invoke()
        self.assertEqual(self.output.read_bytes(), b'old output')

    def test_source_mutation_after_frontend_preserves_output(self):
        self.change = lambda: self.source.write_bytes(b'changed')
        with self.assertRaises((ValueError, RuntimeError)):
            self.invoke()
        self.assertEqual(self.output.read_bytes(), b'old output')

    def test_packet_mutation_after_frontend_preserves_output(self):
        self.change = lambda: Path(self.calls[-1][-2]).write_bytes(b'[]')
        with self.assertRaises((ValueError, RuntimeError)):
            self.invoke()
        self.assertEqual(self.output.read_bytes(), b'old output')

    def test_late_plan_mutation_preserves_output(self):
        original = self.compile
        def compile(*args):
            result = original(*args)
            Path(self.calls[-1][-1]).write_bytes(b'[]')
            return result
        self.toolchain.compile = compile
        with self.assertRaises((ValueError, RuntimeError)):
            self.invoke()
        self.assertEqual(self.output.read_bytes(), b'old output')

    def test_manifest_output_overlap_and_hardlink_alias(self):
        for target in (self.manifest, self.root/'alias'):
            if target != self.manifest:
                os.link(self.manifest, target)
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.invoke(proof=target)
        self.assertFalse(self.calls)

    def test_plan_shape_ids_symbols_and_contracts_fail_closed(self):
        mutations = [lambda p: p + ['extra'],
                     lambda p: [p[0], p[1], []],
                     lambda p: [p[0], p[1], [p[2][0] + ['extra']]],
                     lambda p: [p[0], p[1], [p[2][0][:-1]]]]
        for field, bad in ((0,'elsewhere'),(1,'wrong'),(2,'00'),(2,'x'),(3,'injected();'),
                           (4,[['终','u32'],['始','u32'],['文','borrow_ro_utf8']]),
                           (5,'u8'),(6,list(reversed(dense.EFFECTS))),(7,[['x','u32']]),(8,[])):
            def mutate(p, field=field, bad=bad):
                p[2][0][field] = bad
                return p
            mutations.append(mutate)
        for mutate in mutations:
            self.plan_change = mutate
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.invoke()
            self.assertEqual(self.output.read_bytes(), b'old output')

    def test_marker_mismatch_duplicate_unknown_and_order(self):
        for marker in ('', dense.MARKER*2, dense.MARKER.replace('V1','V2'), '\n'+dense.MARKER):
            self.metadata = marker
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                self.invoke()
        self.assertEqual(self.output.read_bytes(), b'old output')

    def test_unrequested_dense_marker_rejected(self):
        with patch.object(bootstrap.subprocess, 'run', side_effect=self.frontend), self.assertRaises(ValueError):
            bootstrap.compile_native(self.compiler, self.source, self.output, self.toolchain)

    def test_wrong_target_and_native_metadata_rejected(self):
        self.ir = 'target triple = "aarch64-unknown-linux-gnu"\n'
        with self.assertRaises(ValueError):
            self.invoke()
        self.metadata = '/* RU_BOOTSTRAP_NATIVE_V1 */\n'+dense.MARKER
        with self.assertRaises(ValueError):
            self.invoke()

    def test_manifest_schema_rejections(self):
        original = copy.deepcopy(self.document)
        changes = [lambda d: d.update(version=True), lambda d: d.update(extra=1),
                   lambda d: d.update(functions=[]), lambda d: d['functions'][0].update(extra=1),
                   lambda d: d['functions'][0].update(effects=list(reversed(dense.EFFECTS))),
                   lambda d: d['functions'][0].update(params={'x': []}),
                   lambda d: d['functions'][0].update(locals={'始':'u32'}),
                   lambda d: d['functions'][0].update(ranges=[{'view':'文','begin':'始','end':'终'}]*2)]
        for change in changes:
            self.document = copy.deepcopy(original)
            change(self.document)
            self.save()
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.invoke()
        self.assertFalse(self.calls)

    def test_duplicate_keys_depth_nonfinite_and_control(self):
        for raw in (b'{"version":1,"version":1,"functions":[]}',
                    b'{"a":{"x":1,"x":2}}', b'[NaN]', b'[Infinity]', b'[1e999]',
                    b'['*17+b']'*17, b'["\\u0000"]', b'["\\ud800"]', b'["\\u007f"]',
                    b'[] trailing', b'\xff', b'x'*(dense.JSON_BYTES+1)):
            with self.subTest(raw=raw[:50]), self.assertRaises((ValueError, UnicodeError)):
                dense.parse_json(raw)

    def test_source_alias_and_uninventoried_module_rejected(self):
        alias = self.root/'alias.ru'
        alias.symlink_to(self.source)
        with self.assertRaises(ValueError):
            dense.inventory(self.source, [])
        alias.unlink()
        os.link(self.source, alias)
        with self.assertRaises(ValueError):
            dense.inventory(self.source, [])
        alias.unlink()
        other = self.root/'other.ru'
        other.write_bytes(b'x')
        self.document['functions'][0]['module'] = 'other.ru'
        self.save()
        with self.assertRaises(ValueError):
            dense.prepare_transport(self.manifest, [self.source])

    def test_packet_only_strings_arrays_and_unicode_escape(self):
        for bad in (['x',1], ['x',None], ['x',{}], ['x','\0'], ['x','\udfff']):
            with self.assertRaises(ValueError):
                dense.packet_bytes(bad)
        value = ['汉字', 'quote" slash\\']
        self.assertEqual(json.loads(dense.packet_bytes(value)), value)
        self.assertNotIn(b'\\u', dense.packet_bytes(value))

    def test_packet_exclusive_write(self):
        with self.assertRaises(FileExistsError):
            dense.write_packet(self.source, ['x'])


@unittest.skipUnless(shutil.which('cc'), 'development C compiler unavailable')
class DenseRuntimeTests(unittest.TestCase):
    def test_fixed_runtime_exact_scalar_and_utf8_byte_contract(self):
        # Fixed helper unit test only; generated retain/call/drop belongs to Ru.
        header = bootstrap.ROOT/'rulang/bootstrap_dense_runtime.h'
        source = r'''
#include <stdint.h>
#include <stddef.h>
#include <math.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
enum {RU_NUM, RU_STR};
typedef struct {size_t len; char data[8];} RuString;
typedef struct {int kind; double n; RuString *s;} Val;
static jmp_buf trap;
static int got_line;
static void ru_fail(int line, const char *message, ...) {got_line=line; longjmp(trap,1);}
#include "HEADER"
static void reject(double n, uint32_t max) {
  Val v={RU_NUM,n,0};
  if (!setjmp(trap)) {boot_dense_scalar(v,37,max); exit(2);}
  if(got_line!=37) exit(3);
}
int main(void) {
  Val v={RU_NUM,4294967295.0,0};
  if(boot_dense_scalar(v,1,UINT32_MAX)!=UINT32_MAX) return 4;
  v.n=255; if(boot_dense_scalar(v,1,255)!=255) return 5;
  v.n=-0.0; if(boot_dense_scalar(v,1,255)!=0) return 6;
  reject(NAN,UINT32_MAX); reject(INFINITY,UINT32_MAX);
  reject(-1,UINT32_MAX); reject(0.5,UINT32_MAX);
  reject(4294967296.0,UINT32_MAX); reject(256,255);
  RuString text={3,{(char)0xe4,(char)0xb8,(char)0xad,0}};
  v.kind=RU_STR; v.s=&text;
  BootDenseUtf8 b=boot_dense_utf8(v,2);
  if(b.length!=3 || b.data!=(const unsigned char *)text.data) return 7;
  text.len=0; if(boot_dense_utf8(v,2).length!=0) return 8;
  if(!setjmp(trap)) {boot_dense_scalar(v,37,255); return 9;}
  v.kind=RU_NUM;
  if(!setjmp(trap)) {boot_dense_utf8(v,37); return 10;}
#if SIZE_MAX > UINT32_MAX
  v.kind=RU_STR; text.len=(size_t)UINT32_MAX+1;
  if(!setjmp(trap)) {boot_dense_utf8(v,37); return 11;}
#endif
  return 0;
}
'''.replace('HEADER', header.as_posix())
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp).resolve()/'test.c'
            binary = Path(temp).resolve()/'test'
            path.write_text(source, encoding='utf-8')
            result = subprocess.run(['cc','-std=c99','-Wall','-Wextra',str(path),'-lm','-o',str(binary)], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(subprocess.run([str(binary)]).returncode, 0)


if __name__ == '__main__':
    unittest.main()
