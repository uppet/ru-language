"""Immutable UTF8 kernels in ordinary code and actual synchronous FFI callbacks."""
import contextlib
import io
import os
import subprocess
import unittest

from experiments.mi_source import test_source as support
from rulang.compiler import Compiler
from rulang.frontend import RuError
from rulang.mi_ir import EFFECTS, UTF8, VIEW

class UTF8C(unittest.TestCase):
    fixture = support.SourceTests.fixture

    def build(self, source, spec, caller, *, native=False, fixture=None):
        fixture = fixture or self.fixture(source, spec, caller)
        directory, entry, ast, graph, manifest, _ = fixture
        compiler = Compiler(ast, str(entry), modules=graph, mi_manifest=manifest, allow_native=native)
        runtime = compiler.compile()
        if compiler.native_enabled:
            runtime = support.portable(runtime)
        binary = support.compile_c(runtime, directory)
        return fixture, compiler, runtime, binary

    @staticmethod
    def spec(name='字节量', params=None, result='u32'):
        return {'module':'ascii.ru','function':name,'params':params or {'字节':UTF8},'result':result,'effects':EFFECTS}

    def test_empty_unicode_byte_length_and_no_native_runtime(self):
        caller = "核 取 外言 './ascii.ru'. 显 核 其 字节量 ''. 显 核 其 字节量 'a中😀é'."
        _, compiler, runtime, binary = self.build('算 字节量 字节: 得 字节 其 量. 法.', self.spec(), caller)
        result = support.run([str(binary)], env=dict(os.environ, RU_GC_THRESHOLD='1', RU_GC_STATS='1'))
        self.assertEqual(result.stdout, '0\n10\n')
        self.assertIn('RU_GC live=0', result.stderr)
        self.assertFalse(compiler.native_enabled)
        self.assertNotIn('RuNative', runtime)
        self.assertNotIn('ru_mi_acquire', runtime)

    def test_byte_offsets_and_checked_failure_span(self):
        spec = self.spec('核字节', {'字节':UTF8,'位':'u32'}, 'u8')
        source = '算 核字节 字节 位:\n 得 字节[位].\n法.'
        caller = "核 取 外言 './ascii.ru'. 显 核 其 核字节 '中😀' 3. 显 核 其 核字节 '中😀' 6. 显 核 其 核字节 '中😀' 7."
        _, _, _, binary = self.build(source, spec, caller)
        result = subprocess.run([binary], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.stdout, '240\n128\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ascii.ru:2:', result.stderr)
        self.assertIn('status=1', result.stderr)

    def test_wrong_inputs_do_not_coerce_or_copy(self):
        for value in ('[1,2]', '123', '空'):
            caller = f"核 取 外言 './ascii.ru'. 显 核 其 字节量 {value}."
            _, _, _, binary = self.build('算 字节量 字节: 得 字节 其 量. 法.', self.spec(), caller)
            result = subprocess.run([binary], capture_output=True, text=True, encoding='utf-8')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('不可变普通句', result.stderr)

    def test_mixed_views_still_rejected(self):
        spec = self.spec('核字节', {'字节':UTF8,'另一':VIEW})
        with self.assertRaisesRegex(RuError, '一个只读视图'):
            self.fixture('算 核字节 字节 另一: 得 字节 其 量. 法.', spec)

    def test_real_callback_nested_entry_failure_then_retry(self):
        spec = self.spec('核字节', {'字节':UTF8,'位':'u32'}, 'u8')
        source = '算 核字节 字节 位:\n 得 字节[位].\n法.'
        fixture = self.fixture(source, spec)
        directory = fixture[0]
        export = '__declspec(dllexport) ' if os.name == 'nt' else ''
        library = support.compile_c(export + 'int invoke(int (*fn)(void)) { return fn(); }\n', directory, shared=True)
        path = library.as_posix().replace("'", "\\'")
        caller = f"""
密 取 外言 '如:密'. 核 取 外言 './ascii.ru'.
库 取 密 其 动态库 '{path}'.
调 取 库 其 绑定 'invoke' (密 其 签名 (密 其 i32) ([密 其 指针]) 'cdecl').
签 取 密 其 签名 (密 其 i32) ([]) 'cdecl'.
调用次数 取 [0].
回 取 密 其 回调 签 (算:
    调用次数[0] 取 调用次数[0]+1.
    若 调用次数[0] == 1 则 得 核 其 核字节 'abc' 3. 然
    得 核 其 核字节 '中😀' 3.
法) (-9).
首 取 调 其 调用 [回].
显 (首 其 值) 其 数.
显 (首 其 回调错误) 其 含 'status=1'.
后 取 调 其 调用 [回].
显 (后 其 值) 其 数.
显 (后 其 回调错误) == 空.
回 其 关闭. 库 其 关闭.
"""
        entry = directory/'caller.ru'; entry.write_text(caller, encoding='utf-8')
        from rulang.frontend import parse
        from rulang.modules import load_module_graph
        ast = parse(caller); graph = load_module_graph(entry, ast)
        fixture = (directory, entry, ast, graph, fixture[4], fixture[5])
        _, _, _, binary = self.build(source, spec, caller, native=True, fixture=fixture)
        result = support.run([str(binary)], env=dict(os.environ, RU_GC_THRESHOLD='1', RU_GC_STATS='1'))
        self.assertEqual(result.stdout, '-9\n真\n240\n真\n')
        self.assertIn('RU_GC live=0', result.stderr)


