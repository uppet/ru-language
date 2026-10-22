"""Direct protocol/selection/metadata gates; explicit compiler binary required.
A C-seeded compiler proves development behavior, not LLVM14/stage3 execution.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
COMPILER=os.environ.get('RU_BOOTSTRAP_DENSE_TEST_COMPILER')
VERSION='bootstrap-dense-v1'
EFFECTS=['borrow-read','no-escape','no-callback','no-gc','may-fail']
TRIPLE='x86_64-pc-linux-gnu'
LAYOUT='e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128'

@unittest.skipUnless(COMPILER,'set explicit dense frontend compiler; seed evidence is development-only')
class DenseFrontendTests(unittest.TestCase):
    def setUp(self):
        evidence=os.environ.get('RU_BOOTSTRAP_DENSE_EVIDENCE_DIR')
        if evidence:
            self.root=Path(evidence).resolve()/self._testMethodName
            self.root.mkdir(parents=True,exist_ok=False)
        else:
            self.temp=tempfile.TemporaryDirectory(prefix='dense-protocol-')
            self.addCleanup(self.temp.cleanup)
            self.root=Path(self.temp.name).resolve()
        self.main=self.root/'main.ru'; self.kernel=self.root/'kernel.ru'
        self.main.write_text("核 取 外言 'kernel.ru'. 显 核 其 工 'abc' 0 3.",encoding='utf-8')
        self.kernel.write_text('算 工 字节 始 终: 得 终-始. 法',encoding='utf-8')
        self.manifest=self.root/'manifest.json'; self.manifest.write_text('{}',encoding='utf-8')
        self.packet_path=self.root/'packet.data'
        self.record=['kernel.ru',self.kernel.as_posix(),'工',
                     [['字节','borrow_ro_utf8'],['始','u32'],['终','u32']],
                     'u32',EFFECTS,[],[['字节','始','终']]]
        self.packet=[VERSION,self.manifest.as_posix(),[self.main.as_posix(),self.kernel.as_posix()],[self.record]]
        self.ir=self.root/'program.ll'; self.meta=self.root/'metadata.c';self.sources=self.root/'sources.json'; self.plan=self.root/'plan.json'

    def build(self,packet=None,raw=None,dense=True,native=False,extra=(),target=None):
        if raw is None: raw=json.dumps(self.packet if packet is None else packet,ensure_ascii=False)
        self.packet_path.write_text(raw,encoding='utf-8')
        triple=target or ('x86_64-pc-windows-msvc' if native else TRIPLE)
        args=[COMPILER,str(self.main),str(self.ir),str(self.meta),triple,LAYOUT,str(ROOT/'rulang/stdlib'),str(self.sources)]
        if native: args+=['--allow-native=bootstrap-native-v1']
        if dense: args+=['--dense-utf8=bootstrap-dense-v1',str(self.packet_path),str(self.plan)]
        return subprocess.run(args+list(extra),capture_output=True,text=True,encoding='utf-8',timeout=60)

    def fail(self,result):
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(self.ir.exists())
        self.assertFalse(self.meta.exists())
        self.assertFalse(self.plan.exists())

    def test_selected_body_bridge_and_proof(self):
        r=self.build(); self.assertEqual(r.returncode,0,r.stderr)
        proof=json.loads(self.plan.read_text(encoding='utf-8'));self.assertEqual(proof[:2],[VERSION,self.manifest.as_posix()])
        self.assertEqual(len(proof[2]),1)
        rec=proof[2][0];self.assertEqual(rec[0:2],[self.kernel.as_posix(),'工'])
        self.assertEqual(rec[3],'boot_dense_'+rec[2]);self.assertEqual(rec[4:],[*self.record[3:]])
        ir=self.ir.read_text(encoding='utf-8');meta=self.meta.read_text(encoding='utf-8')
        self.assertIn('define void @'+rec[3]+'_llvm(',ir)
        self.assertNotIn('define void @boot_fn_'+rec[2]+'_llvm(',ir)
        self.assertTrue(meta.startswith('/* RU_BOOTSTRAP_DENSE_UTF8_V1 */\n'))
        a=meta.index('boot_dense_scalar(');b=meta.index('boot_dense_utf8(');c=meta.index('密视图起止范围越界');d=meta.index('Val mi_owner = v_copy(')
        e=meta.index('v_drop(mi_owner);');f=meta.index('if (mi_out[0] != 0)');g=meta.index('return v_num((double)mi_out[1])')
        self.assertLess(a,b);self.assertLess(b,c);self.assertLess(c,d);self.assertLess(d,e);self.assertLess(e,f);self.assertLess(f,g)
        self.assertIn('ru_fail((int)mi_out[2]',meta)
        self.assertIn('mi_out[3], (int)mi_out[0]',meta)

    def test_both_optins_and_ordinary_mode(self):
        r=self.build(dense=False);self.assertEqual(r.returncode,0,r.stderr)
        self.assertNotIn('DENSE',self.meta.read_text(encoding='utf-8'));self.assertNotIn('@boot_dense_',self.ir.read_text(encoding='utf-8'))
        r=self.build(native=True);self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue(self.meta.read_text(encoding='utf-8').startswith('/* RU_BOOTSTRAP_NATIVE_V1 x86_64-pc-windows-msvc */\n/* RU_BOOTSTRAP_DENSE_UTF8_V1 */\n'))

    def test_exact_five_original_wij_selected_generically(self):
        self.kernel.write_bytes((ROOT/'tests/fixtures/dense/markdown_ascii_kernel.ru').read_bytes())
        self.main.write_text("核 取 外言 'kernel.ru'. 显 核 其 字节量 '中文😀'.",encoding='utf-8')
        specs=json.loads((ROOT/'tests/fixtures/dense/markdown-dense-manifest.json').read_text(encoding='utf-8'))['functions']
        self.packet[3]=[["kernel.ru",self.kernel.as_posix(),s['function'],list(map(list,s['params'].items())),s['result'],s['effects'],list(map(list,s.get('locals',{}).items())),[[r['view'],r['begin'],r['end']] for r in s.get('ranges',[])]] for s in specs]
        result=self.build();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(json.loads(self.plan.read_text(encoding='utf-8'))[2]),5)
        self.assertEqual(self.ir.read_text(encoding='utf-8').count('define void @boot_dense_'),5)

    def test_decoder_never_executes_code(self):
        for raw in ("显 'BAD'.",json.dumps(self.packet,ensure_ascii=False)+" 显 'BAD'.",'[]', '{"x":1}', '["bootstrap-dense-v1",读]', '['*18+'"x"'+']'*18):
            with self.subTest(raw=raw[:60]):self.fail(self.build(raw=raw))

    def test_versions_shapes_duplicates_and_effects(self):
        mutations=[lambda p:p.__setitem__(0,'future'),lambda p:p.append('unknown'),
          lambda p:p[2].append(p[2][0]),lambda p:p[3].append(copy.deepcopy(p[3][0])),
          lambda p:p[3][0].append('unknown'),lambda p:p[3][0][3].append(['始','u32']),
          lambda p:p[3][0].__setitem__(5,list(reversed(EFFECTS))),
          lambda p:p[3][0][7].append(['字节','始','终']),
          lambda p:p[3][0][3][0].__setitem__(1,'borrow_ro_u8'),
          lambda p:p[3][0][3].reverse(),lambda p:p[3][0].__setitem__(4,'void'),
          lambda p:p[3][0][6].append(['unknown','u8']),
          lambda p:p[3][0][7].__setitem__(0,['始','始','终'])]
        for mutate in mutations:
            p=copy.deepcopy(self.packet);mutate(p)
            with self.subTest(packet=p):self.fail(self.build(packet=p))

    def test_missing_or_aliased_module_and_unloaded_identity(self):
        for index,value in ((0,'KERNEL.ru'),(0,'other/kernel.ru'),(1,self.main.as_posix()),(1,'//server/share/kernel.ru')):
            p=copy.deepcopy(self.packet);p[3][0][index]=value
            with self.subTest(value=value):self.fail(self.build(packet=p))
        extra=self.root/'extra.ru';extra.write_text('算 工 字节 始 终: 得 始. 法',encoding='utf-8')
        p=copy.deepcopy(self.packet);p[2].append(extra.as_posix());p[3][0][0]='extra.ru';p[3][0][1]=extra.as_posix()
        self.fail(self.build(packet=p))

    def test_inventory_gate_before_source_open(self):
        p=copy.deepcopy(self.packet);p[2].remove(self.kernel.as_posix())
        self.fail(self.build(packet=p))
        self.assertNotIn('define ',self.build(packet=p).stdout)

    def test_source_changes_are_not_handwritten_kernels(self):
        self.kernel.write_text('算 工 字节 始 终: 得 终*始. 法',encoding='utf-8')
        self.fail(self.build())
        self.kernel.write_text('算 外: 算 工 字节 始 终: 得 始. 法 得 0. 法',encoding='utf-8')
        self.main.write_text("核 取 外言 'kernel.ru'. 显 核 其 外.",encoding='utf-8')
        self.fail(self.build())

    def test_two_modules_with_same_function_name_use_full_identity(self):
        second=self.root/'second.ru';second.write_text('算 工 字节 始 终: 得 字节 其 量. 法',encoding='utf-8')
        self.main.write_text("甲 取 外言 'kernel.ru'. 乙 取 外言 'second.ru'. 显 甲 其 工 'abc' 0 3. 显 乙 其 工 'abc' 0 3.",encoding='utf-8')
        self.packet[2].append(second.as_posix())
        self.packet[3][0][0]='second.ru';self.packet[3][0][1]=second.as_posix()
        r=self.build();self.assertEqual(r.returncode,0,r.stderr)
        rec=json.loads(self.plan.read_text(encoding='utf-8'))[2][0]
        self.assertEqual(rec[0],second.as_posix())
        self.assertEqual(self.ir.read_text(encoding='utf-8').count('define void @boot_dense_'),1)
        self.assertIn('define void @boot_fn_',self.ir.read_text(encoding='utf-8'))

    def test_protocol_limits_and_string_control_characters(self):
        changes=[lambda p:p.__setitem__(0,'x'*4097),lambda p:p.__setitem__(2,['/x']*10001),
                 lambda p:p.__setitem__(3,[p[3][0]]*257),
                 lambda p:p[3][0].__setitem__(2,'x'*257),
                 lambda p:p[3][0].__setitem__(3,[['x','u32']]*65),
                 lambda p:p[3][0].__setitem__(6,[['x','u32']]*65),
                 lambda p:p[3][0].__setitem__(7,[['字节','始','终']]*65),
                 lambda p:p[3][0].__setitem__(2,'bad\nname'),
                 lambda p:p[3][0].__setitem__(2,'bad'+chr(127)+'name')]
        for change in changes:
            p=copy.deepcopy(self.packet);change(p)
            with self.subTest(kind=str(p)[:40]):self.fail(self.build(packet=p))
        self.fail(self.build(raw=' '*1048577))

    def test_absolute_above_root_alias_rejected(self):
        p=copy.deepcopy(self.packet)
        alias=lambda value:'/..'+value
        p[1]=alias(p[1]);p[2]=[alias(path) for path in p[2]];p[3][0][1]=alias(p[3][0][1])
        original=self.main;self.main=Path(alias(self.main.as_posix()))
        try:self.fail(self.build(packet=p))
        finally:self.main=original
        p=copy.deepcopy(self.packet);p[1]='C:/../manifest.json'
        self.fail(self.build(packet=p))

    def test_dense_target_contract(self):
        cases=json.loads((ROOT/'tests/fixtures/dense/targets.json').read_text(encoding='utf-8'))
        for triple in cases['rejected']:
            with self.subTest(triple=triple):self.fail(self.build(target=triple))
        for triple in cases['accepted']:
            with self.subTest(triple=triple):
                result=self.build(target=triple)
                self.assertEqual(result.returncode,0,result.stderr)

    def test_failed_plan_keeps_existing_artifacts(self):
        for path in (self.ir,self.meta,self.sources,self.plan):path.write_text('KEEP',encoding='utf-8')
        p=copy.deepcopy(self.packet);p[3][0][5]=['no-gc']
        r=self.build(packet=p);self.assertNotEqual(r.returncode,0)
        for path in (self.ir,self.meta,self.sources,self.plan):self.assertEqual(path.read_text(encoding='utf-8'),'KEEP')

    def test_output_cannot_overwrite_packet_or_manifest(self):
        for target in (self.packet_path,self.manifest):
            original_ir=self.ir; self.ir=target
            r=self.build();self.assertNotEqual(r.returncode,0)
            self.ir=original_ir
        self.assertEqual(self.manifest.read_text(encoding='utf-8'),'{}')

    def test_unknown_repeated_cli_flags_rejected(self):
        for extra in (['--allow-native=bootstrap-native-v1'],['--future'],['--dense-utf8=bootstrap-dense-v1']):
            self.fail(self.build(extra=extra))

if __name__=='__main__':unittest.main()
