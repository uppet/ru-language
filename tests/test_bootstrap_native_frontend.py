"""Direct frontend semantic probes; explicitly distinguishes development from stage3.

Set RU_BOOTSTRAP_FRONTEND_TEST_COMPILER to a built compiler. A stage0-C compiler
is useful development evidence only; it cannot satisfy stage3/LLVM release gates.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "密 取 外言 '如:密'.\n"
COMPILER = os.environ.get('RU_BOOTSTRAP_FRONTEND_TEST_COMPILER')

@unittest.skipUnless(COMPILER,'set explicit frontend compiler; stage0-C is development-only evidence')
class BootstrapNativeFrontendTests(unittest.TestCase):
    def compile(self,source,native=True):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            script=root/'main.ru'; script.write_text(source,encoding='utf-8')
            ir, metadata, manifest = [root/n for n in ('main.ll','metadata.c','sources.json')]
            args=[COMPILER,str(script),str(ir),str(metadata),'x86_64-pc-windows-msvc',
                  'e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128',
                  str(ROOT/'rulang/stdlib'),str(manifest)]
            if native: args.append('--allow-native=bootstrap-native-v1')
            result=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',timeout=120)
            return result,metadata.read_text(encoding='utf-8') if metadata.exists() else ''

    def test_production_win32_exact_shape_prototypes(self):
        from rulang.native_c import C_TYPES
        fixture=ROOT/'tests/fixtures/native/notepad_win32.ru'
        matrix=json.loads((fixture.parent/'notepad_win32_contract.json').read_text(encoding='utf-8'))
        result,metadata=self.compile(fixture.read_text(encoding='utf-8'))
        self.assertEqual(result.returncode,0,result.stderr)
        prototypes=set(re.findall(r'typedef (.+) \(\*RuNativeCall_\d+\)\(([^\n]*)\);',metadata))
        expected={(C_TYPES[s['result']],', '.join(C_TYPES[t] for t in s['parameters']) or 'void') for s in matrix['shapes']}
        self.assertEqual(prototypes,expected)
        self.assertIn('ru_native_builtins(ru_practical_builtins())',metadata)
        self.assertIn('if (ru_native_callback_depth) ru_fail',metadata)
        bodies = re.findall(r'static Val boot_m_\d+_init\(void\) \{(.*?\nboot_m_\d+_state=2;[^\n]*)',metadata,re.S)
        self.assertEqual(len(bodies),2)
        for body in bodies:
            self.assertLess(body.index('ru_native_callback_depth'),body.index('_state=1;'))

    def test_unknown_mutable_rebound_and_shadowed_signatures_fail_closed(self):
        cases=(
            "签 取 密 其 签名 (读) ([]) 'win64'.",
            "参 取 [密 其 i32]. 参 其 增 (密 其 f64). 签 取 密 其 签名 (密 其 i32) 参 'win64'.",
            "型 取 密 其 i32. 型 取 密 其 f64. 签 取 密 其 签名 型 ([]) 'win64'.",
            "型 取 密 其 i32. 若 读 则 型 取 密 其 f64. 然 签 取 密 其 签名 型 ([]) 'win64'.",
            "型 取 密 其 i32. 算 工 型: 得 密 其 签名 型 ([]) 'win64'. 法 工 (读).",
            "算 工 密: 得 密 其 签名 (读) ([]) 'win64'. 法 工 密.",
            "型 取 密 其 i32. 算 工: 型 取 读. 得 密 其 签名 型 ([]) 'win64'. 法 工.",
            "型 取 密 其 i32. 试 卒 'x'. 救 型 签 取 密 其 签名 型 ([]) 'win64'. 终",
            "型 取 密 其 i32. 算 外 型: 算 内: 得 密 其 签名 型 ([]) 'win64'. 法 得 内. 法 外 (读).",
            "算 外 密: 算 内: 得 密 其 签名 (读) ([]) 'win64'. 法 得 内. 法 外 密.",
        )
        for case in cases:
            with self.subTest(case=case):
                result,metadata=self.compile(PREFIX+case)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(metadata,'')
                self.assertIn('原生',result.stderr)

    def test_dynamic_structure_fields_are_runtime_values_not_abi_shapes(self):
        source=PREFIX+"字段 取 []. 序 取 0. 循 64 次 字段 其 增 [('f'+(序 为 句)),密 其 u32]. 序 取 序+1. 环 型 取 密 其 结构 字段. 显 型 其 大小."
        result,metadata=self.compile(source)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotRegex(metadata,r'typedef .*RuNativeCall_')

    def test_structure_cannot_masquerade_as_primitive_abi(self):
        cases=(
            "型 取 密 其 结构 [['x',密 其 i32]]. 签 取 密 其 签名 型 ([]) 'win64'.",
            "型 取 密 其 结构 [['x',密 其 i32]]. 签 取 密 其 签名 (密 其 i32) ([型]) 'win64'.",
            "型 取 密 其 结构 (读). 签 取 密 其 签名 (密 其 i32) ([型]) 'win64'.",
        )
        for source in cases:
            with self.subTest(source=source):
                result,metadata=self.compile(PREFIX+source)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(metadata,'')

    def test_import_all_native_wrappers_preserve_static_signature_checks(self):
        result,metadata=self.compile("尽取 外言 '如:密'. 签 取 签名 i32 ([指针]) 'win64'.")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertRegex(metadata,r'typedef int32_t \(\*RuNativeCall_0\)\(void \*\);')
        result,metadata=self.compile("尽取 外言 '如:密'. 签 取 签名 (读) ([]) 'win64'.")
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(metadata,'')

    def test_user_function_named_signature_is_not_a_builtin(self):
        result,metadata=self.compile("算 签名 返回 参数 约定: 得 7. 法 显 签名 1 2 3.")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('typedef ',metadata.split('Ahead-of-time primitive ABI thunks:')[-1])

    def test_known_ordinary_methods_are_not_native_by_name(self):
        source="形 普通: 算 签名 值: 得 值. 法 算 绑定 值: 得 值. 法 算 回调 值: 得 值. 法 象 对象 取 新 普通. 对象 其 签名 1. 对象 其 绑定 2. 对象 其 回调 3."
        result,_=self.compile(source)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_ordinary_metadata_does_not_acquire_native_parent(self):
        result,metadata=self.compile("显 'ordinary'.",native=False)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('ru_native_builtins',metadata)
        self.assertNotIn('ru_native_generated_call',metadata)

    def test_default_denies_native_even_dormant_or_raw_alias(self):
        for source in (PREFIX,"若 不实 则 外言 '如:密'. 然",'别名 取 __密.'):
            with self.subTest(source=source):
                result,metadata=self.compile(source,native=False)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(metadata,'')

if __name__=='__main__': unittest.main()
