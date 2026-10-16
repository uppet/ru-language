"""Generic owned-memory U32LE snapshots, independent of application code.

The POSIX C class uses the existing test-artifact-only platform adapter. It is
not Windows ABI evidence. The Windows class builds and launches the production
standalone backend, with Python used only as a separate parity oracle.
"""
import ctypes as C
import gc
import io
import math
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch
import weakref

from rulang import native_runtime as N
from rulang.compiler import Compiler
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter
from rulang.js_compiler import JSCompiler
import test_native_c_backend as acceptance
import test_native_c_runtime as portable

PREFIX = acceptance.PREFIX
MEMBER = '读U32LE阵'

# An alignment-one inner structure begins two bytes into its root owner. Its
# member-relative offset zero is valid even though its physical address is not
# aligned to a uint32_t. No pointer fabrication or dereference is involved.
NESTED_SETUP = """
字型 取 密 其 结构 [['a',密 其 u8],['b',密 其 u8],['c',密 其 u8],['d',密 其 u8],['e',密 其 u8],['f',密 其 u8],['g',密 其 u8],['h',密 其 u8]].
中型 取 密 其 结构 [['lead',密 其 u8],['inner',字型]].
外型 取 密 其 结构 [['lead',密 其 u8],['middle',中型],['tail',密 其 u32]].
外 取 外型 其 新建. 中 取 外 其 读 'middle'. 内 取 中 其 读 'inner'.
内 其 写 'a' 120. 内 其 写 'b' 86. 内 其 写 'c' 52. 内 其 写 'd' 18.
内 其 写 'e' 255. 内 其 写 'f' 255. 内 其 写 'g' 255. 内 其 写 'h' 255.
"""

UNALIGNED_ONE_SETUP = """
四型 取 密 其 结构 [['a',密 其 u8],['b',密 其 u8],['c',密 其 u8],['d',密 其 u8]].
包型 取 密 其 结构 [['lead',密 其 u8],['inner',四型],['tail',密 其 u32]].
包 取 包型 其 新建. 一视 取 包 其 读 'inner'.
一视 其 写 'a' 120. 一视 其 写 'b' 86. 一视 其 写 'c' 52. 一视 其 写 'd' 18.
"""

SUCCESS_BODY = NESTED_SETUP + UNALIGNED_ONE_SETUP + """
快照 取 内 其 读U32LE阵 0 2. 显 快照.
显 内 其 读U32LE阵 个数:1 字节偏移:4.
显 (快照[1] + 1).
另份 取 内 其 读U32LE阵 0 2. 显 快照 == 另份.
另份[0] := 7. 显 内 其 读U32LE阵 0 1. 内 其 写 'a' 1. 显 内 其 读U32LE阵 0 1. 显 快照.
外 其 关闭. 显 快照.
显 一视 其 读U32LE阵 0 1. 显 一视 其 读U32LE阵 4 0. 包 其 关闭.
文甲 取 密 其 UTF8 'ABCDxyz'. 显 文甲 其 读U32LE阵 0 2.
文乙 取 密 其 UTF16 'ABC'. 显 文乙 其 读U32LE阵 0 2.
文甲 其 关闭. 文乙 其 关闭.
缓 取 密 其 缓冲 17. 显 缓 其 读U32LE阵 0 4.
空甲 取 缓 其 读U32LE阵 16 0. 空乙 取 缓 其 读U32LE阵 16 0.
显 空甲. 显 空甲 == 空乙. 空甲 其 增 7. 显 空乙.
齐缓 取 密 其 缓冲 16. 显 齐缓 其 读U32LE阵 16 0.
大缓 取 密 其 缓冲 16388. 满列 取 大缓 其 读U32LE阵 4 4096.
显 满列 其 量. 显 满列[0] + 满列[4095].
大缓 其 关闭. 满列[4095] := 4294967295. 显 满列[4095].
缓 其 关闭. 齐缓 其 关闭.
算 留视图:
    根 取 外型 其 新建. 层 取 根 其 读 'middle'. 子 取 层 其 读 'inner'.
    子 其 写 'a' 120. 子 其 写 'b' 86. 子 其 写 'c' 52. 子 其 写 'd' 18.
    得 子.
法
留 取 留视图().
循 40 次 临时 取 ['collect',1,2,3]. 环
脱离 取 留 其 读U32LE阵 0 1. 留 其 关闭. 留 取 空.
循 40 次 临时 取 ['collect',4,5,6]. 环
显 脱离.
"""
SUCCESS_OUTPUT = (
    '[305419896, 4294967295]\n[4294967295]\n4294967296\n假\n'
    '[305419896]\n[305419777]\n[305419896, 4294967295]\n[305419896, 4294967295]\n'
    '[305419896]\n[]\n'
    '[1145258561, 8026488]\n[4325441, 67]\n[0, 0, 0, 0]\n'
    '[]\n假\n[]\n[]\n4096\n0\n4294967295\n[305419896]\n'
)

# Each statement must fail *inside* the new member call (or its ordinary
# argument binder), rather than while manufacturing the bad argument.
INVALID_ARGUMENTS = (
    '-1', '0.5', '-0.5', '1e308', '9007199254740992',
    '真', '假', "'0'", "''", '空', '[]', '{}',
    '((密 其 u32) 其 值 0)', '((密 其 f64) 其 值 0)',
    '((密 其 指针) 其 值 0)',
)
REJECTIONS = [f'缓 其 读U32LE阵 ({value}) 0.' for value in INVALID_ARGUMENTS]
REJECTIONS += [f'缓 其 读U32LE阵 0 ({value}).' for value in INVALID_ARGUMENTS]
REJECTIONS += [
    '缓 其 读U32LE阵 1 0.', '缓 其 读U32LE阵 2 1.',
    '缓 其 读U32LE阵 3 0.', '缓 其 读U32LE阵 17 0.',
    '缓 其 读U32LE阵 20 0.', '缓 其 读U32LE阵 16 1.',
    '缓 其 读U32LE阵 12 2.', '缓 其 读U32LE阵 0 5.',
    '大缓 其 读U32LE阵 0 4097.',
    '内 其 读U32LE阵 8 1.', '内 其 读U32LE阵 12 0.',
    '一视 其 读U32LE阵 4 1.', '一视 其 读U32LE阵 8 0.',
    '已关 其 读U32LE阵 0 0.', '旧内 其 读U32LE阵 0 0.',
    '闭视 其 读U32LE阵 0 0.',
    '原指 其 读U32LE阵 0 0.', '有主指 其 读U32LE阵 0 1.',
    '缓 其 读U32LE阵.', '缓 其 读U32LE阵 0.',
    '缓 其 读U32LE阵 0 0 0.',
    '缓 其 读U32LE阵 偏移:0 个数:0.',
    '缓 其 读U32LE阵 字节偏移:0 数量:0.',
]


REJECTION_SETUP = NESTED_SETUP + UNALIGNED_ONE_SETUP + """
缓 取 密 其 缓冲 17. 大缓 取 密 其 缓冲 16388.
已关 取 密 其 缓冲 4. 已关 其 关闭.
旧外 取 外型 其 新建. 旧中 取 旧外 其 读 'middle'. 旧内 取 旧中 其 读 'inner'. 旧外 其 关闭.
闭视 取 中 其 读 'inner'. 闭视 其 关闭.
原指 取 (密 其 指针) 其 值 '4096'. 有主指 取 缓 其 地址.
"""


def rejection_body(statements=REJECTIONS):
    """Contain expected errors at a genuine native callback boundary."""
    body = (acceptance.binding('原生调', 'invoke_callback', 'i64', ['指针', 'u64'])
            + acceptance.binding('回声', 'echo_i64', 'i64', ['i64'])
            + "签 取 密 其 签名 (密 其 i64) ([密 其 u64]) 'cdecl'.\n"
            + REJECTION_SETUP)
    for index, statement in enumerate(statements):
        body += f"""
坏回 取 密 其 回调 签 (算 值: {statement} 得 999. 法) (-7).
果 取 原生调 其 调用 [坏回,1].
断言 (((果 其 值) 其 数) == -7) '失败值 {index}'.
断言 ((果 其 回调错误) != 空) '缺少错误 {index}'.
断言 (非 (密 其 回调中)) '回调深度 {index}'.
断言 (((确认 (回声 其 调用 [19])) 其 数) == 19) '错误后恢复 {index}'.
验列 取 内 其 读U32LE阵 0 2.
断言 (验列[0] == 305419896 且 验列[1] == 4294967295) '错误后内存 {index}'.
坏回 其 关闭.
"""
    body += "外 其 关闭. 包 其 关闭. 缓 其 关闭. 大缓 其 关闭. 显 'rejections-recovered'.\n"
    return body


class NativeMemoryBatchPythonTests(unittest.TestCase):
    def setUp(self):
        supported = patch.object(N, '_supported', return_value=True)
        supported.start()
        self.addCleanup(supported.stop)
        self.output = io.StringIO()
        self.owner = Interpreter(allow_native=True, stdout=self.output)
        self.owner.execute(parse(PREFIX))
        self.node = parse('显 1.')[0]

    def memory(self, raw):
        storage = (C.c_ubyte * len(raw)).from_buffer_copy(raw)
        return N._wrap(N.NativeMemory(storage), self.owner._native_context)

    def read(self, memory, offset=0.0, count=1.0, *, owner=None):
        handled, result = N.native_member(owner or self.owner, self.node, memory,
                                          MEMBER, [(None, offset), (None, count)])
        self.assertTrue(handled)
        return result

    def test_generic_ru_program(self):
        self.owner.execute(parse(SUCCESS_BODY))
        self.assertEqual(self.output.getvalue(), SUCCESS_OUTPUT)

    def test_rejection_matrix_and_recovery_in_interpreter(self):
        self.owner.execute(parse(REJECTION_SETUP))
        for statement in REJECTIONS:
            with self.subTest(statement=statement), self.assertRaises(RuError):
                self.owner.execute(parse(statement))
            self.assertEqual(self.read(self.owner.global_scope.values['内'], 0.0, 2.0),
                             [305419896.0, 4294967295.0])

    def test_explicit_little_endian_plain_numbers_and_independent_snapshots(self):
        memory = self.memory(bytes.fromhex('00000000 ffffffff 78563412 00000080'))
        first = self.read(memory, 0.0, 4.0)
        second = self.read(memory, 0.0, 4.0)
        self.assertIs(type(first), list)
        self.assertTrue(all(type(value) is float for value in first))
        self.assertEqual(first, [0.0, 4294967295.0, 305419896.0, 2147483648.0])
        self.assertIsNot(first, second)
        second[0] = 12.0
        self.assertEqual(self.read(memory, 0.0, 4.0), first)
        N._unwrap(memory).storage[4] = 0
        self.assertEqual(self.read(memory, 4.0, 1.0), [4294967040.0])
        N._unwrap(memory).closed = True
        self.assertEqual(first, [0.0, 4294967295.0, 305419896.0, 2147483648.0])

    def test_zero_boundary_alignment_and_4096_limit(self):
        memory = self.memory(bytes(4097 * 4))
        values = self.read(memory, 4.0, 4096.0)
        self.assertEqual(values, [0.0] * 4096)
        for offset, count in ((0.0, 4097.0), (4.0, 4097.0),
                              (16388.0, 1.0), (16392.0, 0.0)):
            with self.subTest(offset=offset, count=count), self.assertRaises(RuError):
                self.read(memory, offset, count)
        end = self.read(memory, 16388.0, 0.0)
        self.assertEqual(end, [])
        self.assertIsNot(end, self.read(memory, 16388.0, 0.0))
        odd = self.memory(bytes(17))
        self.assertEqual(self.read(odd, 16.0, 0.0), [])
        self.assertEqual(self.read(odd, 0.0, 4.0), [0.0] * 4)
        for offset, count in ((1.0, 0.0), (2.0, 1.0), (3.0, 0.0),
                              (17.0, 0.0), (16.0, 1.0), (12.0, 2.0)):
            with self.subTest(offset=offset, count=count), self.assertRaises(RuError):
                self.read(odd, offset, count)
        self.assertEqual(self.read(odd, -0.0, -0.0), [])

    def test_only_finite_exact_nonnegative_ordinary_numbers(self):
        memory = self.memory(bytes(16))
        context = self.owner._native_context
        invalid = [True, False, '0', '', None, [], {},
                   -1.0, 0.5, -0.5, math.nan, math.inf, -math.inf,
                   1e308, float(2 ** 53),
                   N._wrap(N.NativeScalar(N.PRIMITIVES['u32'], 0), context),
                   N._wrap(N.NativeScalar(N.PRIMITIVES['f64'], 0.0), context),
                   N._wrap(N.NativeScalar(N.PRIMITIVES['指针'], 0), context)]
        for value in invalid:
            for arguments in ((value, 0.0), (0.0, value)):
                with self.subTest(arguments=arguments), self.assertRaises(RuError):
                    self.read(memory, *arguments)
        self.assertEqual(self.read(memory, 0.0, 1.0), [0.0])

    def test_nested_views_are_relative_unaligned_and_owned(self):
        self.owner.execute(parse(NESTED_SETUP))
        outer = self.owner.global_scope.values['外']
        middle = self.owner.global_scope.values['中']
        inner = self.owner.global_scope.values['内']
        self.assertEqual(N._unwrap(inner).address - N._unwrap(outer).address, 2)
        self.assertNotEqual(N._unwrap(inner).address % 4, 0)
        self.assertEqual(self.read(inner, 0.0, 2.0), [305419896.0, 4294967295.0])
        self.assertEqual(self.read(inner, 4.0, 1.0), [4294967295.0])
        with self.assertRaises(RuError):
            self.read(inner, 8.0, 1.0)
        N._unwrap(middle).closed = True
        with self.assertRaisesRegex(RuError, '关闭'):
            self.read(inner, 0.0, 0.0)
        N._unwrap(middle).closed = False
        N._unwrap(outer).closed = True
        with self.assertRaisesRegex(RuError, '关闭'):
            self.read(inner, 0.0, 0.0)

    def test_alignment_one_four_byte_view_at_root_plus_one(self):
        self.owner.execute(parse(UNALIGNED_ONE_SETUP))
        outer = self.owner.global_scope.values['包']
        view = self.owner.global_scope.values['一视']
        self.assertEqual(N._unwrap(view).address - N._unwrap(outer).address, 1)
        self.assertGreater(N._unwrap(outer).size, N._unwrap(view).size + 4)
        self.assertEqual(self.read(view, 0.0, 1.0), [305419896.0])
        self.assertEqual(self.read(view, 4.0, 0.0), [])
        for offset, count in ((4.0, 1.0), (8.0, 0.0)):
            with self.subTest(offset=offset, count=count), self.assertRaises(RuError):
                self.read(view, offset, count)

    def test_view_retains_parent_but_snapshot_does_not(self):
        self.owner.execute(parse(NESTED_SETUP))
        inner = self.owner.global_scope.values.pop('内')
        self.owner.global_scope.values.pop('中')
        outer = self.owner.global_scope.values.pop('外')
        reference = weakref.ref(N._unwrap(outer))
        del outer
        gc.collect()
        self.assertIsNotNone(reference())
        snapshot = self.read(inner, 0.0, 2.0)
        del inner
        gc.collect()
        self.assertIsNone(reference(), 'a plain numeric snapshot must not retain native owners')
        self.assertEqual(snapshot, [305419896.0, 4294967295.0])

    def test_closed_receivers_and_raw_or_owned_pointers_are_rejected(self):
        memory = self.memory(bytes(8))
        for pointer in (N.NativeScalar(N.PRIMITIVES['指针'], 4096),
                        N.NativeScalar(N.PRIMITIVES['指针'], N._unwrap(memory).address,
                                       (N._unwrap(memory),))):
            with self.subTest(pointer=pointer), self.assertRaisesRegex(RuError, '未知原生成员'):
                self.read(N._wrap(pointer, self.owner._native_context), 0.0, 0.0)
        N._unwrap(memory).closed = True
        with self.assertRaisesRegex(RuError, '关闭'):
            self.read(memory, 0.0, 0.0)

    def test_context_thread_and_permissions_still_apply_to_empty_reads(self):
        memory = self.memory(bytes(4))
        other = Interpreter(allow_native=True, stdout=io.StringIO())
        with self.assertRaisesRegex(RuError, '跨解释器'):
            self.read(memory, 0.0, 0.0, owner=other)
        denied = Interpreter(stdout=io.StringIO())
        denied_memory = N._wrap(N._unwrap(memory), denied._native_context)
        with self.assertRaisesRegex(RuError, '默认关闭'):
            self.read(denied_memory, 0.0, 0.0, owner=denied)
        errors = []

        def foreign_read():
            try:
                self.read(memory, 0.0, 0.0)
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=foreign_read, daemon=True)
        thread.start()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), 'cross-thread rejection must not block')
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuError)
        self.assertIn('所属解释器线程', str(errors[0]))
        self.assertEqual(self.read(memory, 0.0, 1.0), [0.0])

    def test_python_copy_allocation_failure_stays_inside_callback_and_recovers(self):
        self.owner.execute(parse("""
缓 取 密 其 缓冲 4.
签 取 密 其 签名 (密 其 i64) ([密 其 u64]) 'cdecl'.
回 取 密 其 回调 签 (算 值: 列 取 缓 其 读U32LE阵 0 1. 得 列[0]. 法) (-7).
"""))
        callback = N._unwrap(self.owner.global_scope.values['回'])
        context = self.owner._native_context
        context.depth = 1  # Model the enclosing synchronous native call.
        try:
            with patch.object(C, 'string_at', side_effect=MemoryError('batch-copy-allocation')) as copy:
                self.assertEqual(callback.trampoline(1), -7)
                copy.assert_called_once()
            self.assertEqual(callback.active, 0)
            self.assertEqual(context.callback_depth, 0)
            self.assertEqual(len(context.errors), 1)
            self.assertIn('batch-copy-allocation', context.errors[0])
            context.errors.clear()  # The outer native call normally drains this.
            self.assertEqual(callback.trampoline(1), 0)
            self.assertEqual(context.errors, [])
            self.assertEqual(callback.active, 0)
            self.assertEqual(context.callback_depth, 0)
        finally:
            context.depth = 0
            callback.close()
        self.assertEqual(self.read(self.owner.global_scope.values['缓']), [0.0])

    def test_new_member_does_not_bypass_native_preflight(self):
        source = "显 'side-effect'. 若 假 则 密 取 外言 '如:密'. 缓 取 密 其 缓冲 4. 缓 其 读U32LE阵 0 1. 然"
        output = io.StringIO()
        with self.assertRaisesRegex(RuError, '默认关闭'):
            Interpreter(stdout=output).execute(parse(source))
        self.assertEqual(output.getvalue(), '')
        for compiler in (Compiler, JSCompiler):
            with self.subTest(compiler=compiler), self.assertRaises(RuError):
                compiler(parse(source), str(acceptance.ROOT / 'batch-denied.ru')).compile()


class MemoryBatchExecutableCases:
    """Shared cases only, not a TestCase or an imported test-class alias."""
    def test_owned_memory_snapshots(self):
        self.check_program(SUCCESS_BODY, SUCCESS_OUTPUT)

    def test_rejections_are_contained_and_recover(self):
        self.check_program(rejection_body(), 'rejections-recovered\n', fixture=True)


@unittest.skipUnless(os.name == 'posix' and shutil.which('gcc'),
                     'generic C state tests require POSIX GCC')
class NativeMemoryBatchPortableCTests(MemoryBatchExecutableCases, unittest.TestCase):
    # Reuse the existing owned fixture, artifact adapter, bounded launch, and
    # forced-GC accounting without inheriting any unrelated TestCase methods.
    @classmethod
    def setUpClass(cls):
        portable.NativeCPortableRuntimeTests.setUpClass.__func__(cls)

    build_executable = portable.NativeCPortableRuntimeTests.build_executable
    run_executable = portable.NativeCPortableRuntimeTests.run_executable

    def check_program(self, body, expected, *, fixture=False):
        source = PREFIX + acceptance.ASSERT
        if fixture:
            source += '库 取 密 其 动态库 ' + acceptance.ru_string(self.fixture) + '.\n'
        source += body
        for full in (False, True):
            with self.subTest(full_runtime=full), tempfile.TemporaryDirectory() as directory:
                executable, _ = self.build_executable(source, directory, full=full)
                result = self.run_executable(executable)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout, expected)
            self.assertEqual(result.stderr, '')

    def test_nonfinite_internal_numbers_are_rejected_by_the_c_member(self):
        # Ru arithmetic cannot normally produce these values. Inject only
        # numeric literals in this test artifact to exercise the C boundary,
        # without weakening production checks or relying on a native f64 result
        # (which would be rejected before reaching the memory member).
        replacements = {float(31337 + index).hex(): value
                        for index, value in enumerate(('NAN', 'INFINITY', '-INFINITY'))}
        statements = [f'缓 其 读U32LE阵 {31337 + index} 0.' for index in range(3)]
        statements += [f'缓 其 读U32LE阵 0 {31337 + index}.' for index in range(3)]
        original = portable.portable_test_source

        def inject(source, path, *, full=False):
            generated = original(source, path, full=full)
            for literal, replacement in replacements.items():
                needle = 'v_num(' + literal + ')'
                self.assertEqual(generated.count(needle), 2)
                generated = generated.replace(needle, 'v_num(' + replacement + ')')
            return generated

        with patch.object(portable, 'portable_test_source', side_effect=inject):
            self.check_program(rejection_body(statements), 'rejections-recovered\n', fixture=True)


    def test_array_storage_oom_is_contained_without_leaks_and_recovers(self):
        # Fail the actual allocation immediately after the snapshot array heap
        # has been registered. Its unfinished item storage must remain safe for
        # callback unwinding, forced GC, and the final live=0 accounting.
        original = portable.portable_test_source

        def inject(source, path, *, full=False):
            generated = original(source, path, full=full)
            allocation = 'array->items = (Val *)ru_alloc(count * sizeof(Val), line);'
            self.assertEqual(generated.count(allocation), 1)
            generated = generated.replace(
                allocation, 'rn_test_batch_oom = count == 7; ' + allocation)
            allocator = 'void *p = malloc(size ? size : 1);'
            self.assertEqual(generated.count(allocator), 1)
            generated = generated.replace(
                allocator, 'void *p = rn_test_batch_oom ? '
                '(rn_test_batch_oom = 0, (void *)NULL) : malloc(size ? size : 1);')
            return 'static int rn_test_batch_oom;\n' + generated

        body = rejection_body(['大缓 其 读U32LE阵 0 7.'])
        body = body.replace(
            "断言 ((果 其 回调错误) != 空) '缺少错误 0'.",
            "断言 ((果 其 回调错误) 其 含 '内存不足') '缺少分配失败诊断'.")
        with patch.object(portable, 'portable_test_source', side_effect=inject):
            self.check_program(body, 'rejections-recovered\n', fixture=True)


@unittest.skipUnless(acceptance.WINDOWS_X64, 'requires real Windows x64 execution')
class NativeMemoryBatchWindowsParityTests(MemoryBatchExecutableCases,
                                         acceptance.NativeExecutableMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fixture_directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixture_directory.cleanup)
        cls.fixture = Path(cls.fixture_directory.name) / 'c_backend_bridge.dll'
        result = acceptance.bounded_run(
            [*cls.compiler, '-std=c99', '-shared', '-O2', '-Wall', '-Wextra',
             '-Werror', '-pedantic',
             str(acceptance.ROOT / 'tests/fixtures/native/c_backend_bridge.c'),
             '-o', str(cls.fixture)], timeout=90)
        if result.returncode:
            raise AssertionError('owned C fixture failed to compile:\n' + result.stderr)

    def check_program(self, body, expected, *, fixture=False):
        source = PREFIX + acceptance.ASSERT
        if fixture:
            source += '库 取 密 其 动态库 ' + acceptance.ru_string(self.fixture) + '.\n'
        source += body
        with tempfile.TemporaryDirectory() as directory:
            executable, script = self.build_executable(source, directory)
            native = self.run_executable(executable)
            interpreted = acceptance.cli('run', '--allow-native', script)
        for name, result in (('production C executable', native), ('Python oracle', interpreted)):
            with self.subTest(backend=name):
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout, expected)
                self.assertEqual(result.stderr, '')

    def test_foreign_thread_cannot_reach_memory_read(self):
        body = (acceptance.binding('异调', 'invoke_foreign_thread', 'i64', ['指针', 'u64'])
                + """
缓 取 密 其 缓冲 4. 计 取 [0].
签 取 密 其 签名 (密 其 i64) ([密 其 u64]) 'cdecl'.
回 取 密 其 回调 签 (算 值:
    计[0] := 计[0] + 1. 列 取 缓 其 读U32LE阵 0 1. 得 列[0].
法) (-11).
果 取 异调 其 调用 [回,1].
断言 (((果 其 值) 其 数) == -11) '异线程失败值'.
断言 ((果 其 回调错误) != 空) '异线程没有错误'.
断言 (计[0] == 0) '异线程执行如正文'.
显 缓 其 读U32LE阵 0 1. 回 其 关闭. 缓 其 关闭.
""")
        self.check_program(body, '[0]\n', fixture=True)


if __name__ == '__main__':
    unittest.main()
