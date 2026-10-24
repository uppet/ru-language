"""Independent stage3 native acceptance; existing Python suite is only an oracle.

RU_BOOTSTRAP_NATIVE_REQUIRED=1 makes lack of real Windows/stage3 a failure.
RU_BOOTSTRAP_NATIVE_COMPILER selects the already bootstrapped stage3 executable.
This suite never obtains frontend IR or ABI plans from Python.
"""
from contextlib import ExitStack
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_bootstrap_native_oracle', ROOT/'tests/test_native_c_backend.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def stage3_path():
    return Path(os.environ.get('RU_BOOTSTRAP_NATIVE_COMPILER', ROOT/'bin/bootstrap/win32/stage3.exe'))


class BootstrapNativeRequiredGate(unittest.TestCase):
    def test_required_native_execution_cannot_be_satisfied_by_skips(self):
        if os.environ.get('RU_BOOTSTRAP_NATIVE_REQUIRED') == '1':
            self.assertTrue(oracle.WINDOWS_X64, 'required acceptance needs real Windows x64, not a skip')
            self.assertTrue(stage3_path().is_file(), 'required acceptance needs an actual stage3 executable')

    def test_production_fixture_inventory_matches_static_oracle(self):
        # Oracle only: no production build path invokes this Python planner.
        from rulang.frontend import parse
        from rulang.modules import load_module_graph
        from rulang.native_c import NativeCPlan
        fixture = ROOT/'tests/fixtures/native/notepad_win32.ru'
        matrix = json.loads((ROOT/'tests/fixtures/native/notepad_win32_contract.json').read_text(encoding='utf-8'))
        self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(),matrix['source_sha256'])
        self.assertEqual(len(matrix['bindings']),51)
        self.assertEqual(len(matrix['shapes']),31)
        self.assertEqual({name:item['size'] for name,item in matrix['structures'].items()},
                         {'POINT':8,'RECT':16,'MSG':48,'WNDCLASS':80,'NMHDR':24,'TCITEM':40,
                          'OPENFILE':152,'ALLFILEFILTER':30,'INITCONTROLS':8})
        plan = NativeCPlan(load_module_graph(fixture,parse(fixture.read_text(encoding='utf-8'))))
        self.assertEqual({(shape.result,shape.params) for shape in plan.signatures},
                         {(shape['result'],tuple(shape['parameters'])) for shape in matrix['shapes']})


@unittest.skipUnless(oracle.WINDOWS_X64, 'requires real Windows x64 execution; not execution evidence')
class BootstrapNativeWindowsAcceptanceTests(oracle.NativeCWindowsAcceptanceTests):
    @classmethod
    def setUpClass(cls):
        if not stage3_path().is_file():
            if os.environ.get('RU_BOOTSTRAP_NATIVE_REQUIRED') == '1':
                raise AssertionError('stage3 executable missing')
            raise unittest.SkipTest('bootstrap stage3 executable not supplied; not execution evidence')
        try:
            super().setUpClass()
        except unittest.SkipTest as error:
            if os.environ.get('RU_BOOTSTRAP_NATIVE_REQUIRED') == '1':
                raise AssertionError('required fixture execution cannot skip: '+str(error)) from error
            raise

    def build_executable(self, source, directory):
        from tools.bootstrap import compile_native
        from rulang.llvm_toolchain import LLVMToolchain
        directory = Path(directory)
        script, executable = directory/'program.ru', directory/'program.exe'
        script.write_text(source, encoding='utf-8')
        # Driver is permitted to package fixed C runtime text, never to inspect
        # a source AST, load its module graph, plan its ABI, or emit its code.
        forbidden = ('rulang.frontend.parse', 'rulang.modules.load_module_graph',
                     'rulang.native_c.NativeCPlan.__init__', 'rulang.native_c.NativeCPlan.emit_c',
                     'rulang.compiler.Compiler.compile')
        with ExitStack() as guards:
            for name in forbidden:
                guards.enter_context(patch(name, side_effect=AssertionError('Python frontend fallback: '+name)))
            compile_native(stage3_path(), script, executable,
                           LLVMToolchain(os.environ.get('RU_LLVM_CLANG')),
                           allow_native=True, keep_frontend=True,
                           source_roots=(ROOT/'tests/fixtures/native',))
        self.assertEqual(executable.read_bytes()[:2], b'MZ')
        metadata = executable.with_name(executable.name+'.metadata.c').read_text(encoding='utf-8')
        self.assertIn('ru_native_generated_call', metadata)
        self.assertNotIn('Python.h', metadata)
        return executable, script

    def test_dynamic_64_field_structure_layout_and_lifetime(self):
        source = oracle.PREFIX+oracle.ASSERT+"""
字段 取 []. 序 取 0.
循 64 次 字段 其 增 [('f'+(序 为 句)),密 其 u32]. 序 取 序+1. 环
型 取 密 其 结构 字段.
断言 ((型 其 大小) == 256) 'dynamic structure size'.
断言 ((型 其 偏移 'f63') == 252) 'dynamic field offset'.
物 取 型 其 新建.
物 其 写 'f63' 4294967295.
断言 (((物 其 读 'f63') 其 句) == '4294967295') 'dynamic field width'.
物 其 关闭.
显 'dynamic-structure-ok'.
"""
        with tempfile.TemporaryDirectory() as directory:
            executable,_ = self.build_executable(source,directory)
            result = self.run_executable(executable)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(result.stdout,'dynamic-structure-ok\n')

    def test_production_win32_declarations_and_nested_window_callback(self):
        # Exact saved production module, not equivalent hand-written signatures.
        win32 = ROOT/'tests/fixtures/native/notepad_win32.ru'
        source = oracle.PREFIX+oracle.ASSERT+"窗 取 外言 "+oracle.ru_string(win32)+".\n"+"""
断言 (((窗 其 MSG) 其 大小) == 48) 'MSG layout'.
断言 (((窗 其 OPENFILE) 其 大小) == 152) 'OPENFILE layout'.
断言 (((窗 其 WNDCLASS) 其 大小) == 80) 'WNDCLASSEX layout'.
断言 (((窗 其 TCITEM) 其 偏移 'text') == 16) 'TCITEM pointer alignment'.
算 处理 柄, 号, 宽, 长:
    若 (号 其 数) == 32769 则 得 窗 其 发送 柄 32770 0 0. 然
    若 (号 其 数) == 32770 则 得 -7. 然
    得 窗 其 结果 ((窗 其 DefWindowProcW) 其 调用 [柄,号,宽,长]).
法
实例 取 窗 其 结果 ((窗 其 GetModuleHandleW) 其 调用 [空]).
类名 取 密 其 UTF16 'RuBootstrapNativeContract'.
回 取 密 其 回调 (窗 其 WNDPROC) (算 处理) 0.
回 其 失败时 (窗 其 PostQuitMessage) ([1]).
类 取 (窗 其 WNDCLASS) 其 新建.
类 其 写 'size' ((窗 其 WNDCLASS) 其 大小).
类 其 写 'proc' (回 其 地址).
类 其 写 'instance' 实例.
类 其 写 'name' (类名 其 地址).
窗 其 成功 ((窗 其 RegisterClassExW) 其 调用 [类]) 'RegisterClassExW'.
类 其 关闭.
柄 取 窗 其 成功 ((窗 其 CreateWindowExW) 其 调用 [0,类名,类名,0,0,0,32,32,空,空,实例,空]) 'CreateWindowExW'.
断言 (((窗 其 发送 柄 32769 0 0) 其 数) == -7) 'nested WNDPROC'.
窗 其 成功 ((窗 其 DestroyWindow) 其 调用 [柄]) 'DestroyWindow'.
窗 其 成功 ((窗 其 UnregisterClassW) 其 调用 [类名,实例]) 'UnregisterClassW'.
回 其 关闭.
类名 其 关闭.
显 'win32-bootstrap-ok'.
"""
        with tempfile.TemporaryDirectory() as directory:
            executable, _ = self.build_executable(source,directory)
            result = self.run_executable(executable)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(result.stdout,'win32-bootstrap-ok\n')
        self.assertEqual(result.stderr,'')

    def test_dynamic_unknown_signature_is_rejected_before_output_replace(self):
        from tools.bootstrap import compile_native
        from rulang.llvm_toolchain import LLVMToolchain
        cases = (
            "签 取 密 其 签名 (密 其 i32) (读) 'win64'.",
            "签 取 密 其 签名 (读) ([]) 'win64'.",
            "签 取 密 其 签名 (密 其 i32) ([]) (读).",
            "参 取 [密 其 i32]. 参 其 增 (密 其 f64). 签 取 密 其 签名 (密 其 i32) 参 'win64'.",
        )
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory)/'bad.ru', Path(directory)/'preserved.exe'
            for body in cases:
                with self.subTest(body=body):
                    source.write_text(oracle.PREFIX+body,encoding='utf-8')
                    output.write_bytes(b'preserved')
                    with self.assertRaises((RuntimeError, ValueError)):
                        compile_native(stage3_path(),source,output,LLVMToolchain(os.environ.get('RU_LLVM_CLANG')),allow_native=True)
                    self.assertEqual(output.read_bytes(),b'preserved')


if __name__ == '__main__':
    unittest.main()
