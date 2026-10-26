"""Binding caches preserve mutable lexical environments and invocation lifetime."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from rulang.frontend import parse
from rulang.llvm_compiler import LLVMCompiler
from test_bootstrap import TOOLCHAIN, prepared_stages
from tools.bootstrap import compile_native


SOURCE = """
值 取 10.
算 局部:
 显 值.
 值 取 ['local'].
 显 值.
 算 改: 值 取 ['changed']. 得 值. 法.
 显 改(). 显 值.
 循 3 次
  段: 值 取 ['block']. 显 值. 落.
  试 卒 'caught'. 救 原因 值 取 [原因]. 显 值. 终.
  显 值.
 环.
 得 算: 得 值. 法.
法.
留 取 局部(). 显 值.
循 30 次 垃圾 取 ['pressure',[]]. 环.
显 留().
算 递归 数值:
 若 数值 == 0 则 得 0. 然.
 下 取 递归 (数值-1).
 得 下+数值.
法.
显 (递归 12).
算 外:
 项 取 1.
 算 内:
  显 项. 项 取 项+1. 显 项. 得 项.
 法.
 显 内(). 显 项. 得 算 内.
法.
变 取 外(). 显 变().
算 重入 回调 数值:
 若 数值 == 0 则 得 ['end']. 然.
 本地 取 [数值].
 丢 取 回调 回调 (数值-1).
 得 本地.
法.
显 (重入 (算 重入) 20).
"""
EXPECTED = ('10\n[local]\n[changed]\n[changed]\n' +
            '[block]\n[caught]\n[changed]\n' * 3 +
            '10\n[changed]\n78\n1\n2\n2\n2\n2\n3\n3\n[20]\n')


@unittest.skipUnless(TOOLCHAIN, 'LLVM14 required')
class LLVMBindingExecutionTests(unittest.TestCase):
    def test_both_frontends_cache_binding_not_value_or_ancestor(self):
        selected = os.environ.get('RU_BINDING_TEST_COMPILER')
        if selected:
            native = Path(selected).resolve()
            self.assertTrue(native.is_file())
        else:
            directory, _ = prepared_stages()
            native = directory/('stage3.exe' if os.name == 'nt' else 'stage3')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = root/'bindings.ru'
            entry.write_text(SOURCE, encoding='utf-8')
            for label in ('python-llvm', 'bootstrap-llvm'):
                with self.subTest(frontend=label):
                    directory = root/label
                    directory.mkdir()
                    if label == 'python-llvm':
                        compiler = LLVMCompiler(parse(SOURCE), str(entry))
                        ir = compiler.compile(TOOLCHAIN.triple, TOOLCHAIN.data_layout)
                        binary, _ = TOOLCHAIN.compile(ir, compiler.runtime_c(), directory)
                    else:
                        binary = directory/'program.exe'
                        with patch('rulang.frontend.parse', side_effect=AssertionError('host parser')), \
                                patch.object(LLVMCompiler, 'compile', side_effect=AssertionError('host codegen')):
                            compile_native(native, entry, binary, TOOLCHAIN, keep_frontend=True)
                        ir = Path(str(binary)+'.frontend.ll').read_text(encoding='utf-8')
                    self.assertIn('call void @rul_get_cached(', ir)
                    self.assertIn('call void @rul_bind_cached(', ir)
                    result = subprocess.run([str(binary)], capture_output=True, text=True,
                        encoding='utf-8', timeout=45, env={**os.environ,
                        'RU_GC_THRESHOLD':'1', 'RU_GC_STATS':'1'})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, EXPECTED)
                    self.assertRegex(result.stderr, r'^RU_GC live=0 freed=\d+ collections=\d+\s*$')
