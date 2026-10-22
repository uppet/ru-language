"""Actual LLVM Mi kernels, ordinary callers, and real owner cleanup.

Linux NativeMemory integration uses the existing test-only platform adapter.
Windows executes the production owner implementation and native LLVM ABI.
"""
import contextlib
import io
import os
from pathlib import Path
import random
import subprocess
import unittest
from unittest.mock import patch

from experiments.mi_source import test_source as source_tests
from rulang.cli import main
from rulang.compiler import Compiler
from rulang.frontend import RuError
from rulang.llvm_compiler import LLVMCompiler
from rulang.llvm_toolchain import LLVMToolchain
from rulang.mi_ir import C_HEADER, EFFECTS
from rulang.mi_llvm import c_adapter

try:
    TOOLCHAIN = LLVMToolchain()
except RuError:
    TOOLCHAIN = None


@unittest.skipUnless(TOOLCHAIN, '需要 LLVM 14 工具链')
class SourceLLVMTests(source_tests.SourceTests):
    compiler_class = LLVMCompiler

    def generate_program(self, compiler, directory):
        if not hasattr(self, 'programs'): self.programs = {}
        self.programs[str(directory)] = compiler.compile(TOOLCHAIN.triple, TOOLCHAIN.data_layout)
        return compiler.runtime_c()

    def link_program(self, source, directory):
        binary, _ = TOOLCHAIN.compile(self.programs[str(directory)], source, directory)
        return binary

    def replace_main(self, generated, probe, directory):
        self.programs[str(directory)] = self.programs[str(directory)].replace('@main(', '@unused_ordinary_main(')
        return generated + probe

    def probe_function(self, compiler, fn):
        return compiler.function_ids[id(fn)] + '_bridge'

    def test_c_js_random_differential_and_all_bytes(self):
        # Retain the independent C/JS oracle, then exercise LLVM against a
        # Python byte oracle (including checked failures and their full spans).
        super().test_c_js_random_differential_and_all_bytes()
        directory, _, _, _, _, plan = self.fixture()
        record = plan.records[0]
        runtime = C_HEADER + c_adapter(record['ir'], record['symbol']) + r'''
#include <stdio.h>
int main(void) {
    uint8_t bytes[128]; uint32_t length, begin, end, byte, i;
    while (scanf("%u %u %u", &length, &begin, &end) == 3) {
        if (length > sizeof(bytes)) return 2;
        for (i=0; i<length; ++i) {
            if (scanf("%u", &byte) != 1 || byte > 255) return 3;
            bytes[i] = (uint8_t)byte;
        }
        RuMiResult r = ru_mi_kernel_0((RuMiView){length ? bytes : NULL,length},begin,end);
        printf("%d %u %u %u\n",r.status,r.value,r.line,r.col);
    }
    return 0;
}
'''
        binary, _ = TOOLCHAIN.compile(plan.compute_source('llvm'), runtime, directory)
        rng = random.Random(20261022)
        rows = [([b], 0, 1) for b in range(256)] + [([], 0, 0)]
        for _ in range(600):
            data = [rng.randrange(256) if rng.random() < .2 else rng.randrange(32, 127)
                    for _ in range(rng.randrange(96))]
            begin = rng.randrange(len(data) + 1); end = rng.randrange(begin, len(data) + 1)
            rows.append((data, begin, end))
        rows += [([65], 0, 2), ([65], 1, 0)]
        request = '\n'.join(' '.join(map(str, [len(data), begin, end, *data])) for data, begin, end in rows)
        actual = source_tests.run([str(binary)], input=request).stdout.splitlines()
        self.assertEqual(len(actual), len(rows))
        for row, result in zip(rows, actual):
            data, begin, end = row
            status, value, line, col = map(int, result.split())
            if begin > end:
                self.assertEqual((status, line), (2, 4)); self.assertGreater(col, 0)
            elif end > len(data):
                self.assertEqual((status, line), (1, 5)); self.assertGreater(col, 0)
            else:
                expected = 0
                for byte in data[begin:end]:
                    if byte >= 128 or byte in (13, 10, 62): break
                    expected += 1
                self.assertEqual((status, value, line, col), (0, expected, 0, 0), row)

    def test_dense_bodies_never_use_c_lowering_or_val_operations(self):
        _, entry, ast, graph, manifest, _ = self.fixture(
            '算 加 左 右: 得 左 + 右. 法.',
            {'module':'ascii.ru','function':'加','params':{'左':'u32','右':'u32'},'result':'u32','effects':EFFECTS},
            "核 取 外言 './ascii.ru'. 显 核 其 加 3 4.")
        with patch.object(Compiler, 'compile', side_effect=AssertionError('C lowering')), \
                patch('rulang.mi_source.lower', side_effect=AssertionError('C/JS Mi lowering')):
            compiler = LLVMCompiler(ast, str(entry), modules=graph, mi_manifest=manifest)
            generated = compiler.compile()
            runtime = compiler.runtime_c()
        kernel = generated[generated.index('define void @ru_mi_kernel_0_llvm'):].split('\n}', 1)[0]
        self.assertNotIn('@rul_', kernel)
        self.assertNotIn('call ', kernel)
        self.assertNotIn('uint32_t t', runtime)
        self.assertIn('icmp ugt i32', kernel)

    def test_u8_overflow_subtraction_and_elif(self):
        spec = {'module':'ascii.ru','function':'核','params':{'值':'u8'},'result':'u8','effects':EFFECTS}
        source = '算 核 值: 若 值 == 0 则 得 1. 另若 值 == 1 则 得 值 - 1. 另 得 值 + 1. 然. 得 0. 法.'
        for value, expected in ((0, '1\n'), (1, '0\n'), (254, '255\n'), (255, '')):
            _, _, _, binary = self.compile_program(source, spec, f"核 取 外言 './ascii.ru'. 显 核 其 核 {value}.")
            result = subprocess.run([binary], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.stdout, expected)
            self.assertEqual(result.returncode == 0, value != 255)
            if value == 255: self.assertIn('status=2', result.stderr)

    def test_nested_repeat_break_and_return(self):
        spec = {'module':'ascii.ru','function':'核','params':{'次数':'u32'},'result':'u32',
                'locals':{'计数':'u32'},'effects':EFFECTS}
        source = '算 核 次数: 计数 取 0. 循 次数 次 循 3 次 计数 取 计数 + 1. 若 计数 == 5 则 得 计数. 然. 破. 环. 环. 得 计数. 法.'
        for count, expected in ((0, 0), (3, 3), (9, 5)):
            _, _, _, binary = self.compile_program(source, spec, f"核 取 外言 './ascii.ru'. 显 核 其 核 {count}.")
            self.assertEqual(source_tests.run([str(binary)]).stdout, f'{expected}\n')

    def test_cli_opt_in_and_failed_build_preserves_artifacts(self):
        directory, entry, _, _, manifest, _ = self.fixture('算 常数: 得 42. 法.',
            {'module':'ascii.ru','function':'常数','params':{},'result':'u32','effects':EFFECTS},
            "核 取 外言 './ascii.ru'. 显 核 其 常数.")
        binary, ll = directory/'cli.exe', directory/'cli.ll'
        args = ['build', str(entry), '--target', 'llvm', '--experimental-mi-manifest', str(manifest),
                '-o', str(binary), '--emit-llvm', str(ll)]
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(main(args), 0)
        self.assertEqual(source_tests.run([str(binary)]).stdout, '42\n')
        before = binary.read_bytes(), ll.read_bytes()
        (directory/'ascii.ru').write_text('算 常数: 显 1. 得 42. 法.', encoding='utf-8')
        with contextlib.redirect_stderr(io.StringIO()): self.assertEqual(main(args), 1)
        self.assertEqual((binary.read_bytes(), ll.read_bytes()), before)

    def test_manifest_cannot_be_overwritten_by_build_outputs(self):
        directory, entry, ast, graph, manifest, _ = self.fixture('算 常数: 得 42. 法.',
            {'module':'ascii.ru','function':'常数','params':{},'result':'u32','effects':EFFECTS})
        from rulang.cli import build
        before = manifest.read_bytes()
        for target in ('c', 'llvm'):
            for output, kwargs in ((manifest, {}), (directory/'program',
                    {'emit_llvm' if target == 'llvm' else 'emit_c': manifest})):
                with self.subTest(target=target, output=output), \
                        patch('subprocess.run', side_effect=AssertionError('tools')), \
                        self.assertRaises(RuError):
                    build(ast, entry, output, modules=graph, target=target, mi_manifest=manifest, **kwargs)
        self.assertEqual(manifest.read_bytes(), before)

    @unittest.skipUnless(os.name == 'nt', '真实 NativeMemory CLI 桥仅支持 Windows x64')
    def test_windows_cli_native_memory_bridge_requires_permission(self):
        directory, entry, _, _, manifest, _ = self.fixture(caller=(source_tests.HERE/'caller.ru').read_text(encoding='utf-8'))
        binary = directory/'native.exe'
        args = ['build', str(entry), '--target', 'llvm', '--experimental-mi-manifest', str(manifest), '-o', str(binary)]
        with contextlib.redirect_stderr(io.StringIO()): self.assertEqual(main(args), 1)
        self.assertFalse(binary.exists())
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(main(args + ['--allow-native']), 0)
        result = source_tests.run([str(binary)], env=dict(os.environ, RU_GC_THRESHOLD='1', RU_GC_STATS='1'))
        self.assertEqual(result.stdout, '3\n')
        self.assertIn('RU_GC live=0', result.stderr)

    def test_ordinary_output_unchanged_without_manifest(self):
        super().test_ordinary_output_unchanged_without_manifest()
        _, entry, ast, graph, _, _ = self.fixture()
        compiler = LLVMCompiler(ast, str(entry), modules=graph)
        self.assertNotIn('ru_mi_', compiler.compile())
        self.assertNotIn('RuMi', compiler.runtime_c())


if __name__ == '__main__': unittest.main(verbosity=2)
