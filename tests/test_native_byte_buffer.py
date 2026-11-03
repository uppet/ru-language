"""Owned byte buffer contracts. POSIX adapters test mechanisms, not Windows ABI."""
import ctypes as C
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from rulang import native_runtime as N
from rulang.compiler import Compiler
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter
import test_native_c_runtime as portable

PREFIX = "库 取 外言 '如:字带'.\n"
SUCCESS = PREFIX + """
缓 取 库 其 新建 0. 别 取 缓.
显 (缓 其 量)(). 显 (缓 其 容量)().
显 缓 其 快照 0 0.
缓 其 增 0. 缓 其 增 255.
取字函数 取 缓 其 读. 长 取 缓 其 量. 关 取 缓 其 关闭.
副 取 缓 其 快照 0 2. 副[0] := 17.
缓 其 扩容 33. 显 (别 其 容量)(). 显 取字函数 0. 显 取字函数 1.
缓 其 写 0 128. 显 副.
缓 其 改长 1. 缓 其 改长 3. 显 缓 其 快照 0 3.
另缓 取 库 其 新建 2. 另缓 其 增 7. 显 另缓 其 快照 0 1.
缓 取 空. 别 取 空.
循 30 次 垃圾 取 [1,2,3]. 环.
显 长(). 显 取字函数 0. 关(). 关().
试 取字函数 0. 救 原因 显 原因. 终.
试 长(). 救 原因 显 原因. 终.
显 副. (另缓 其 关闭)().
"""
EXPECTED = '0\n0\n[]\n33\n0\n255\n[17, 255]\n[128, 0, 0]\n[7]\n3\n128\n字带已关闭\n字带已关闭\n[17, 255]\n'
INVALID = [
    '库 其 新建 (-1).', '库 其 新建 0.5.', '库 其 新建 16777217.',
    '库 其 新建 真.', "库 其 新建 '2'.",
    '缓 其 读 (-1).', '缓 其 读 2.', '缓 其 读 0.5.',
    '缓 其 写 2 1.', '缓 其 写 0 (-1).', '缓 其 写 0 256.',
    '缓 其 写 0 0.5.', '缓 其 增 真.', '缓 其 增 256.',
    '缓 其 扩容 (-1).', '缓 其 扩容 16777217.', '缓 其 改长 0.5.',
    '缓 其 改长 16777217.', '缓 其 快照 1 0.', '缓 其 快照 0 3.',
    '缓 其 快照 0.5 1.', '缓 其 快照 0 真.',
]

CLOSED_OPERATIONS = [
    '(缓 其 量)().', '(缓 其 容量)().', '缓 其 读 0.',
    '缓 其 写 0 1.', '缓 其 增 1.', '缓 其 扩容 0.',
    '缓 其 改长 0.', '缓 其 快照 0 0.',
]


def interpreted(source, supported=True):
    output = io.StringIO()
    with patch.object(N, '_supported', return_value=supported):
        Interpreter(stdout=output, allow_native=True).execute(parse(source))
    return output.getvalue()


class NativeByteBufferTests(unittest.TestCase):
    def test_owned_library_lifecycle(self):
        self.assertEqual(interpreted(SUCCESS), EXPECTED)

    def test_rejections_leave_live_storage_unchanged(self):
        for bad in INVALID:
            with self.subTest(bad=bad):
                output = io.StringIO()
                with patch.object(N, '_supported', return_value=True):
                    owner = Interpreter(stdout=output, allow_native=True)
                    owner.execute(parse(PREFIX + '缓 取 库 其 新建 2. 缓 其 增 1. 缓 其 增 255.'))
                    with self.assertRaises(RuError):
                        owner.execute(parse(bad))
                    owner.execute(parse('显 缓 其 快照 0 2. 显 (缓 其 量)(). 显 (缓 其 容量)().'))
                self.assertEqual(output.getvalue(), '[1, 255]\n2\n2\n')

    def test_all_closed_operations_reject(self):
        for statement in CLOSED_OPERATIONS:
            with self.subTest(statement=statement), self.assertRaisesRegex(RuError, '已关闭'):
                interpreted(PREFIX + '缓 取 库 其 新建 0. (缓 其 关闭)().' + statement)

    def test_growth_failure_preserves_owner_and_contents(self):
        with patch.object(N, '_supported', return_value=True):
            output = io.StringIO()
            owner = Interpreter(stdout=output, allow_native=True)
            owner.execute(parse(PREFIX + '缓 取 库 其 新建 2. 缓 其 增 1. 缓 其 增 255.'))
            original = N._member
            for failure_at in ('缓冲', '复制到'):
                def injected(context, interpreter, node, obj, name, bind):
                    if name == failure_at:
                        N._fault('owned allocation/copy failure fixture')
                    return original(context, interpreter, node, obj, name, bind)
                with patch.object(N, '_member', side_effect=injected):
                    with self.assertRaisesRegex(RuError, 'failure fixture'):
                        owner.execute(parse('缓 其 扩容 8.'))
                owner.execute(parse('显 缓 其 快照 0 2. 显 (缓 其 容量)().'))
            self.assertEqual(output.getvalue(), '[1, 255]\n2\n[1, 255]\n2\n')

    def test_native_capability_stays_required(self):
        with self.assertRaisesRegex(RuError, '默认关闭'):
            Interpreter(stdout=io.StringIO()).execute(parse(PREFIX))
        with self.assertRaisesRegex(RuError, 'Windows x64'):
            interpreted(PREFIX, supported=False)

    def test_raw_bytes_overlap_and_closed_owners(self):
        body = """
密 取 外言 '如:密'. 甲 取 密 其 缓冲 4. 乙 取 密 其 缓冲 4.
甲 其 写字节 0 1. 甲 其 写字节 1 2. 甲 其 写字节 2 3. 甲 其 写字节 3 4.
甲 其 复制到 甲 0 1 3.
显 甲 其 读U32LE阵 0 1.
甲 其 复制到 乙 0 0 4. 甲 其 复制到 乙 4 4 0.
甲 其 关闭. 显 乙 其 读U32LE阵 0 1.
"""
        self.assertEqual(interpreted(body), '[50462977]\n[50462977]\n')
        for bad in ['甲 其 读字节 0.', '甲 其 写字节 0 2.', '甲 其 复制到 乙 0 0 0.', '乙 其 复制到 甲 0 0 0.']:
            with self.subTest(bad=bad), self.assertRaisesRegex(RuError, '已关闭'):
                interpreted(body + bad)

    def test_raw_bounds_typed_storage_and_borrow_guards(self):
        with patch.object(N, '_supported', return_value=True):
            owner = Interpreter(allow_native=True)
            node = parse('显 0.')[0]
            raw = N.NativeMemory((C.c_ubyte * 4)(1, 2, 3, 4))
            other = N.NativeMemory((C.c_ubyte * 4)())
            def call(obj, member, *args):
                return N.native_member(owner, node, N._wrap(obj, owner._native_context), member,
                                       [(None, N._wrap(x, owner._native_context) if isinstance(x, N.NativeMemory) else x) for x in args])
            bad = [('读字节', -1.0), ('读字节', 4.0), ('读字节', .5),
                   ('写字节', 0.0, 256.0), ('写字节', 0.0, True),
                   ('复制到', other, 3.0, 0.0, 2.0), ('复制到', other, 0.0, 3.0, 2.0),
                   ('复制到', other, 0.0, 0.0, 1e308)]
            for member, *args in bad:
                with self.subTest(member=member, args=args), self.assertRaises(RuError):
                    call(raw, member, *args)
                self.assertEqual(bytes(raw.storage), b'\1\2\3\4')
                self.assertEqual(bytes(other.storage), bytes(4))
            raw.mi_read_borrows = 1
            self.assertEqual(call(raw, '读字节', 0.0), (True, 1.0))
            call(raw, '复制到', other, 0.0, 0.0, 4.0)
            self.assertEqual(bytes(other.storage), b'\1\2\3\4')
            for obj, member, args in [(raw, '写字节', [0.0, 5.0]),
                                      (other, '复制到', [raw, 0.0, 0.0, 1.0]),
                                      (raw, '关闭', [])]:
                with self.assertRaisesRegex(RuError, '借用'):
                    call(obj, member, *args)
            raw.mi_read_borrows = 0
            typed = N.NativeMemory((C.c_ubyte * 4)(), N.PRIMITIVES['u32'])
            view = N.NativeMemory((C.c_ubyte * 4)(), parent=raw)
            for invalid in (typed, view):
                for member, args in [('读字节', [0.0]), ('写字节', [0.0, 1.0]),
                                     ('复制到', [other, 0.0, 0.0, 1.0])]:
                    with self.assertRaisesRegex(RuError, '无结构'):
                        call(invalid, member, *args)
                with self.assertRaisesRegex(RuError, '无结构'):
                    call(raw, '复制到', invalid, 0.0, 0.0, 1.0)

    def run_c(self, source, portable_host=True):
        if not portable_host:
            self.assertEqual(os.name, 'nt', 'production native execution requires Windows')
            self.assertTrue(shutil.which('gcc'), 'Windows native contracts require GCC; do not skip')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            code = (portable.portable_test_source(source, str(path / 'main.ru')) if portable_host else
                    Compiler(parse(source), str(path / 'main.ru'), allow_native=True).compile())
            executable = path / ('main.exe' if os.name == 'nt' else 'main')
            (path / 'main.c').write_text(code, encoding='utf-8')
            command = ['gcc', '-std=c99', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-pedantic',
                       str(path / 'main.c'), '-lm', '-o', str(executable)]
            if portable_host:
                command += ['-ldl', '-pthread']
            if os.environ.get('RU_NATIVE_TEST_SANITIZE') == '1':
                command[1:1] = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-g']
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, encoding='utf-8', timeout=30,
                                    env=dict(os.environ, RU_GC_THRESHOLD='1', RU_GC_STATS='1'))
            return result

    def test_windows_production_requires_compiler(self):
        with patch.object(os, 'name', 'nt'), patch.object(shutil, 'which', return_value=None):
            with self.assertRaisesRegex(AssertionError, 'require GCC; do not skip'):
                self.run_c(SUCCESS, portable_host=False)

    @unittest.skipUnless(os.name == 'posix' and shutil.which('gcc'), 'POSIX mechanism fixture requires GCC')
    def test_portable_c_library_lifecycle(self):
        result = self.run_c(SUCCESS)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, EXPECTED)
        self.assertRegex(result.stderr, r'RU_GC live=0 ')

    def assert_c_copy_and_negative_controls(self, *, portable_host):
        # Identical source and expectations on the test adapter and real Win64.
        # Only run_c's platform selection differs; Windows never rewrites C.
        prefix = "密 取 外言 '如:密'. 甲 取 密 其 缓冲 4. 乙 取 密 其 缓冲 4. "
        source = prefix + "甲 其 写字节 0 1. 甲 其 写字节 1 2. 甲 其 写字节 2 3. 甲 其 写字节 3 4. "
        source += "甲 其 复制到 甲 0 1 3. 显 甲 其 读U32LE阵 0 1. "
        source += "甲 其 复制到 甲 1 0 3. 显 甲 其 读U32LE阵 0 1. "
        source += "甲 其 复制到 乙 4 4 0. 甲 其 复制到 个数:4 目标位:0 目标:乙 源位:0. 显 乙 其 读U32LE阵 0 1."
        result = self.run_c(source, portable_host=portable_host)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '[50462977]\n[50528769]\n[50528769]\n')
        self.assertRegex(result.stderr, r'RU_GC live=0 ')
        self.assertNotIn('AddressSanitizer', result.stderr)
        self.assertNotIn('runtime error:', result.stderr)
        for bad, message in [
            ('甲 其 读字节 (-1).', '字节位置'),
            ('甲 其 读字节 4.', '字节位置'),
            ('甲 其 读字节 0.5.', '整数'),
            ('甲 其 写字节 4 1.', '字节位置'),
            ('甲 其 写字节 0 真.', '整数'),
            ('甲 其 写字节 0 256.', '字节值'),
            ('甲 其 复制到 乙 3 0 2.', '复制个数'),
            ('甲 其 复制到 乙 0 3 2.', '复制个数'),
            ('甲 其 复制到 乙 0 0 1e308.', '整数'),
            ('甲 其 复制到 乙 0 0 (-1).', '复制个数'),
            ('甲 其 复制到 乙 5 0 0.', '源位'),
            ('甲 其 复制到 乙 0 5 0.', '目标位'),
            ('甲 其 关闭. 甲 其 读字节 0.', '已关闭'),
            ('甲 其 关闭. 甲 其 写字节 0 1.', '已关闭'),
            ('甲 其 关闭. 甲 其 复制到 乙 0 0 0.', '已关闭'),
            ('乙 其 关闭. 甲 其 复制到 乙 0 0 0.', '已关闭'),
            ("型 取 密 其 结构 [['x',密 其 u32]]. 物 取 型 其 新建. 物 其 读字节 0.", '无结构'),
            ("型 取 密 其 结构 [['x',密 其 u32]]. 物 取 型 其 新建. 物 其 写字节 0 1.", '无结构'),
            ("型 取 密 其 结构 [['x',密 其 u32]]. 物 取 型 其 新建. 物 其 复制到 甲 0 0 1.", '无结构'),
            ("型 取 密 其 结构 [['x',密 其 u32]]. 物 取 型 其 新建. 甲 其 复制到 物 0 0 1.", '无结构'),
        ]:
            with self.subTest(bad=bad):
                result = self.run_c(prefix + bad, portable_host=portable_host)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertNotIn('AddressSanitizer', result.stderr)
                self.assertNotIn('runtime error:', result.stderr)

    def assert_c_owned_negative_controls(self, *, portable_host):
        prefix = PREFIX + '缓 取 库 其 新建 2. 缓 其 增 1. 缓 其 增 255.\n'
        # C argument type faults terminate before the language-level handler.
        # Test those as independent processes rather than pretending recovery.
        type_faults = {'库 其 新建 真.', "库 其 新建 '2'.", '缓 其 增 真.', '缓 其 快照 0 真.'}
        for bad in sorted(type_faults):
            with self.subTest(bad=bad):
                result = self.run_c(prefix + bad, portable_host=portable_host)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('须为数', result.stderr)
                self.assertNotIn('AddressSanitizer', result.stderr)
                self.assertNotIn('runtime error:', result.stderr)
        source = prefix
        recoverable = [bad for bad in INVALID if bad not in type_faults]
        for bad in recoverable:
            source += '试 ' + bad + " 救 原因 显 'rejected'. 终.\n"
            source += '显 缓 其 快照 0 2. 显 (缓 其 量)(). 显 (缓 其 容量)().\n'
        source += '(缓 其 关闭)(). (缓 其 关闭)().\n'
        for statement in CLOSED_OPERATIONS:
            source += '试 ' + statement + ' 救 原因 显 原因. 终.\n'
        result = self.run_c(source, portable_host=portable_host)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'rejected\n[1, 255]\n2\n2\n' * len(recoverable)
                         + '字带已关闭\n' * len(CLOSED_OPERATIONS))
        self.assertRegex(result.stderr, r'RU_GC live=0 ')
        self.assertNotIn('AddressSanitizer', result.stderr)
        self.assertNotIn('runtime error:', result.stderr)

    @unittest.skipUnless(os.name == 'posix' and shutil.which('gcc'), 'POSIX mechanism fixture requires GCC')
    def test_portable_c_copy_and_negative_controls(self):
        self.assert_c_copy_and_negative_controls(portable_host=True)

    @unittest.skipUnless(os.name == 'posix' and shutil.which('gcc'), 'POSIX mechanism fixture requires GCC')
    def test_portable_c_owned_negative_controls(self):
        self.assert_c_owned_negative_controls(portable_host=True)

    @unittest.skipUnless(os.name == 'nt', 'real Windows x64 GCC execution')
    def test_windows_production_copy_and_negative_controls(self):
        self.assert_c_copy_and_negative_controls(portable_host=False)

    @unittest.skipUnless(os.name == 'nt', 'real Windows x64 GCC execution')
    def test_windows_production_owned_negative_controls(self):
        self.assert_c_owned_negative_controls(portable_host=False)

    @unittest.skipUnless(os.name == 'nt', 'real Windows x64 GCC execution')
    def test_windows_production_library(self):
        result = self.run_c(SUCCESS, portable_host=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, EXPECTED)
        self.assertRegex(result.stderr, r'RU_GC live=0 ')


if __name__ == '__main__':
    unittest.main()
