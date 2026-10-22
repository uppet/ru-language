"""Real NativeMemory ownership tests. Platform-only POSIX adapter is test-only."""
import ctypes as C
import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import weakref

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(HERE)]
from rulang import native_runtime as n
import bridge
from bridge import scan, _acquire, _release


def member(memory, name, *args):
    return n._member(None, None, None, memory, name,
                     lambda names: dict(zip(names, args)))


class RealMemoryPython(unittest.TestCase):
    def setUp(self):
        self.platform = patch.object(n, '_supported', return_value=True)
        self.platform.start()
        self.addCleanup(self.platform.stop)
        self.context = n.NativeContext(n.NativeCapability(True))

    def scan(self, memory, offset=0, length=2, seed=0):
        return scan(memory, offset, length, seed, context=self.context)

    def acquire(self, memory, offset=0, length=2, seed=0):
        return _acquire(memory, offset, length, seed, context=self.context)

    def nested(self):
        class Leaf(C.Structure):
            _fields_ = [('a', C.c_uint8), ('b', C.c_uint8)]
        class Middle(C.Structure):
            _fields_ = [('leaf', Leaf)]
        class Outer(C.Structure):
            _fields_ = [('pad', C.c_uint8), ('middle', Middle)]
        # Existing descriptor factory, real nested member reads and parent graph.
        leaf = n.NativeType('leaf', Leaf, 'struct', fields=(('a', n.PRIMITIVES['u8']), ('b', n.PRIMITIVES['u8'])))
        middle = n.NativeType('middle', Middle, 'struct', fields=(('leaf', leaf),))
        outer = n.NativeType('outer', Outer, 'struct', fields=(('pad', n.PRIMITIVES['u8']), ('middle', middle)))
        root = n.NativeMemory(Outer(), outer)
        mid = member(root, '读', 'middle')
        view = member(mid, '读', 'leaf')
        member(view, '写', 'a', 13.0); member(view, '写', 'b', 10.0)
        return root, mid, view

    def test_nested_gc_and_same_root_conflicts(self):
        root, mid, view = self.nested()
        token = self.acquire(view)
        references = [weakref.ref(x) for x in (root, mid, view)]
        del root, mid, view
        gc.collect()
        self.assertTrue(all(r() is not None for r in references))
        try:
            for r in references:
                with self.assertRaisesRegex(n.NativeFault, '借用'):
                    member(r(), '关闭')
            with self.assertRaisesRegex(n.NativeFault, '借用'):
                member(references[-1](), '写', 'a', 65.0)
            with self.assertRaisesRegex(n.NativeFault, 'effect'):
                n._invoke(None, None, [])
            self.assertEqual(self.scan(references[-1]()), 1)
            self.assertEqual(references[0]().mi_read_borrows, 1)
        finally:
            _release(token)
        gc.collect()
        self.assertTrue(all(r() is None for r in references))
        self.assertEqual(n._mi_active_borrows, 0)

    def test_failure_cleanup_range_and_legacy(self):
        root, mid, view = self.nested()
        for offset, length, seed in ((-1, 1, 0), (0, 3, 0), (0, 2, 0x100000000), (0, 2, 0xffffffff)):
            with self.assertRaises(n.NativeFault):
                self.scan(view, offset, length, seed)
            self.assertEqual(root.mi_read_borrows, 0)
            self.assertEqual(n._mi_active_borrows, 0)
            self.assertEqual(self.scan(view), 1)
        self.assertEqual(self.scan(view, 2, 0), 0)
        member(view, '写', 'a', 65.0)
        self.assertEqual(self.scan(view), 1)
        member(mid, '关闭')
        with self.assertRaisesRegex(n.NativeFault, '关闭'):
            self.scan(view)
        self.assertFalse(root.closed)

    def test_lifo_counts_same_and_different_roots(self):
        root, _, view = self.nested()
        other_root, _, other_view = self.nested()
        outer = self.acquire(view)
        inner = self.acquire(view)
        separate = self.acquire(other_view)
        self.assertEqual((root.mi_read_borrows, other_root.mi_read_borrows, n._mi_active_borrows), (2, 1, 3))
        for token in (outer, inner):
            with self.assertRaisesRegex(n.NativeFault, 'LIFO'):
                _release(token)
            self.assertIs(bridge._borrow_top, separate)
            self.assertEqual((root.mi_read_borrows, other_root.mi_read_borrows, n._mi_active_borrows), (2, 1, 3))
        _release(separate)
        self.assertEqual((root.mi_read_borrows, other_root.mi_read_borrows, n._mi_active_borrows), (2, 0, 2))
        _release(inner)
        self.assertEqual((root.mi_read_borrows, n._mi_active_borrows), (1, 1))
        _release(outer)
        self.assertIsNone(bridge._borrow_top)
        self.assertEqual((root.mi_read_borrows, n._mi_active_borrows), (0, 0))
        with self.assertRaisesRegex(n.NativeFault, 'LIFO'):
            _release(outer)
        self.assertEqual(self.scan(view), 1)

    def test_write_validation_priority(self):
        root, mid, view = self.nested()
        closed = member(mid, '读', 'leaf')
        member(closed, '关闭')
        token = self.acquire(view)
        try:
            with self.assertRaisesRegex(n.NativeFault, '关闭'):
                member(closed, '写', 'missing', None)
            with self.assertRaisesRegex(n.NativeFault, '未知结构字段'):
                member(view, '写', 'missing', None)
            with self.assertRaisesRegex(n.NativeFault, '借用'):
                member(view, '写', 'a', None)
            self.assertEqual(root.mi_read_borrows, 1)
        finally:
            _release(token)
        with self.assertRaisesRegex(n.NativeFault, '原生标量'):
            member(view, '写', 'a', None)

    def test_reference_exception_cleanup(self):
        root, _, view = self.nested()
        with patch.object(n, "_retain", side_effect=MemoryError):
            with self.assertRaises(MemoryError):
                self.scan(view)
        self.assertEqual(root.mi_read_borrows, 0)
        self.assertEqual(n._mi_active_borrows, 0)
        with patch("bridge.C.c_ubyte") as byte:
            byte.from_address.side_effect = RuntimeError("reference failure")
            with self.assertRaises(RuntimeError):
                self.scan(view)
        self.assertEqual(root.mi_read_borrows, 0)
        self.assertEqual(n._mi_active_borrows, 0)
        self.assertEqual(self.scan(view), 1)

    def test_reentrant_and_permission_denial_before_borrow(self):
        root, _, view = self.nested()
        for field in ('depth', 'callback_depth'):
            setattr(self.context, field, 1)
            with self.assertRaisesRegex(n.NativeFault, '重入'):
                self.scan(view)
            setattr(self.context, field, 0)
        self.context._capability = n.NativeCapability(False)
        with self.assertRaisesRegex(n.NativeFault, '默认关闭'):
            self.scan(view)
        self.assertEqual(root.mi_read_borrows, 0)


class RealMemoryC(unittest.TestCase):
    def test_generated_runtime(self):
        from test_native_c_runtime import portable_test_source
        if os.name == "nt":
            from rulang.compiler import Compiler
            from rulang.frontend import parse
            source = Compiler(parse("密 取 外言 '如:密'.\n"), "borrow-test.ru", allow_native=True, full_runtime=True).compile()
        else:
            source = portable_test_source("密 取 外言 '如:密'.\n", 'borrow-test.ru', full=True)
        source = source[:source.index('int main(int argc, char **argv) {')]
        source += '\n' + (HERE.parent / 'mi_kernel/generated/kernel.h').read_text(encoding='utf-8')
        source += '\n' + (HERE / 'bridge.h').read_text(encoding='utf-8')
        source += '\n' + (HERE / 'runtime_probe.c').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            from experiments.mi_source.test_source import compile_c
            executable = compile_c(source, path)
            result = subprocess.run([str(executable)], capture_output=True, text=True, encoding='utf-8', timeout=45, env=dict(os.environ, RU_GC_THRESHOLD='1', RU_GC_STATS='1'))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('real owner borrow checks passed', result.stdout)
            self.assertIn('RU_GC live=0', result.stderr)


if __name__ == '__main__':
    run = unittest.main(verbosity=2, exit=False)
    evidence = HERE / 'test-output'
    evidence.mkdir(exist_ok=True)
    mode = 'ubsan' if os.environ.get('MI_UBSAN') else 'ordinary'
    summary = {
        'platform': sys.platform,
        'c_platform_adapter': 'production-win64' if os.name == 'nt' else 'test-only-posix',
        'mode': mode,
        'tests': run.result.testsRun,
        'failures': len(run.result.failures),
        'errors': len(run.result.errors),
        'skipped': len(run.result.skipped),
        'success': run.result.wasSuccessful(),
        'native_windows_execution': os.name == 'nt',
        'external_ffi_abi_exercised': False,
    }
    (evidence / (mode + '.json')).write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8', newline='\n')
    raise SystemExit(0 if run.result.wasSuccessful() else 1)
