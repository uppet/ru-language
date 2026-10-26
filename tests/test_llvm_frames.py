"""Execute owned argument packs and escaped results under GC."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from bootstrap_pack_cases import combined
from rulang.frontend import parse
from rulang.llvm_compiler import LLVMCompiler
from test_bootstrap import TOOLCHAIN, prepared_stages
from tools.bootstrap import compile_native


def fixture():
    source, expected = combined()
    # Larger argument packs escape their frame and remain alive during the next
    # call and collection, including recursively nested heap values.
    source += '\n算 栈界: 得 [' + ','.join(map(str, range(63))) + ']. 法.\n'
    source += '算 堆界: 得 [' + ','.join(map(str, range(64))) + ']. 法.\n'
    source += """
甲 取 栈界. 乙 取 堆界.
算 深 层:
 值 取 ['held',层].
 若 层 > 0 则 得 [值,(深 (层-1))]. 然.
 得 值.
法.
链 取 深 90.
循 100 次 废 取 ['pressure', []]. 环.
显 甲[62]. 显 乙[63]. 显 链[0].
"""
    return source, expected + '62\n63\n[held, 90]\n'


@unittest.skipUnless(TOOLCHAIN, 'LLVM14 required')
class LLVMFrameExecutionTests(unittest.TestCase):
    def test_both_frontends_preserve_owned_results_through_gc(self):
        source, expected = fixture()
        selected = os.environ.get('RU_FRAME_TEST_COMPILER')
        if selected:
            native = Path(selected).resolve()
            self.assertTrue(native.is_file())
        else:
            directory, _ = prepared_stages()
            native = directory/('stage3.exe' if os.name == 'nt' else 'stage3')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = root/'frames.ru'
            entry.write_text(source, encoding='utf-8')
            for label in ('python-llvm', 'bootstrap-llvm'):
                with self.subTest(frontend=label):
                    directory = root/label
                    directory.mkdir()
                    if label == 'python-llvm':
                        compiler = LLVMCompiler(parse(source), str(entry))
                        ir = compiler.compile(TOOLCHAIN.triple, TOOLCHAIN.data_layout)
                        binary, _ = TOOLCHAIN.compile(ir, compiler.runtime_c(), directory)
                    else:
                        binary = directory/'program.exe'
                        with patch('rulang.frontend.parse', side_effect=AssertionError('host parser')), \
                                patch.object(LLVMCompiler, 'compile', side_effect=AssertionError('host codegen')):
                            compile_native(native, entry, binary, TOOLCHAIN, keep_frontend=True)
                        ir = Path(str(binary)+'.frontend.ll').read_text(encoding='utf-8')
                    result = subprocess.run([str(binary)], capture_output=True, text=True,
                        encoding='utf-8', timeout=45, env={**os.environ,
                        'RU_GC_THRESHOLD':'1', 'RU_GC_STATS':'1'})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, expected)
                    self.assertRegex(result.stderr, r'^RU_GC live=0 freed=\d+ collections=\d+\s*$')
