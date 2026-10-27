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
    source += '算 大包: 得 [' + ','.join(map(str, range(65))) + ']. 法.\n'
    source += """
甲 取 栈界. 乙 取 堆界. 丙 取 大包.
算 深 层:
 值 取 ['held',层].
 若 层 > 0 则 得 [值,(深 (层-1))]. 然.
 得 值.
法.
链 取 深 90.
循 100 次 废 取 ['pressure', []]. 环.
显 甲[62]. 显 乙[63]. 显 丙[64]. 显 链[0].
"""
    source += """
算 取回 值: 循 5 次 垃圾 取 ['pressure',[]]. 环. 得 值. 法.
算 成对 甲 乙: 循 5 次 垃圾 取 ['pressure',[]]. 环. 得 [甲,乙]. 法.
算 失败 甲 乙: 卒 'packed failure'. 法.
显 (成对 (取回 ['outer']) (成对 (取回 ['inner']) (取回 ['last']))).
显 (成对 乙:(取回 ['right']) 甲:(取回 ['left'])).
试 失败 (取回 ['one']) (取回 ['two']). 救 原因 显 原因. 终.
显 (成对 (取回 ['retry']) (取回 ['alive'])).
"""
    # A heap result in slot 63 is cleared at a normal statement boundary and
    # reused repeatedly, exercising the high mask word in both native emitters.
    source += '\n算 清高: 循 3 次 值 取 [' + ','.join(map(str, range(63))) + ']. 环. 得 7. 法.\n显 清高().\n'
    return source, (expected + '62\n63\n64\n[held, 90]\n'
        '[[outer], [[inner], [last]]]\n[[left], [right]]\n'
        'packed failure\n[[retry], [alive]]\n7\n')


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
