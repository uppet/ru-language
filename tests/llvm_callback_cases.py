"""Real Windows LLVM callback lifecycle, reusing the C backend's Ru fixtures."""
import json
import os
from pathlib import Path
import re
import tempfile
import unittest

import test_native_c_backend as acceptance
from rulang.cli import build
from rulang.frontend import parse
from rulang.llvm_toolchain import LLVMToolchain
from rulang.mi_ir import EFFECTS


@unittest.skipUnless(acceptance.WINDOWS_X64, 'real Windows x64 LLVM callback ABI required')
class LLVMCallbackTests(unittest.TestCase):
    callbacks = acceptance.NativeCWindowsAcceptanceTests.callbacks
    program = acceptance.NativeCWindowsAcceptanceTests.program

    @classmethod
    def setUpClass(cls):
        # A missing LLVM14 installation is an error on the required Windows job.
        cls.toolchain = LLVMToolchain()
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.fixture = Path(directory.name)/'owned-bridge.dll'
        cls.toolchain.run(cls.toolchain.clang + ['-std=c99', '-shared', '-O2',
            str(acceptance.ROOT/'tests/fixtures/native/c_backend_bridge.c'), '-o', str(cls.fixture)])

    def build_executable(self, source, directory):
        directory = Path(directory)
        script, binary = directory/'program.ru', directory/'program.exe'
        # Existing scalar Mi opt-in permits native ABI; all tested callback
        # bodies remain ordinary direct LLVM functions, including failures.
        source += '\n算 回调验收许可 值: 得 值. 法\n'
        script.write_text(source, encoding='utf-8')
        manifest = directory/'manifest.json'
        manifest.write_text(json.dumps({'version': 1, 'functions': [{
            'module': 'program.ru', 'function': '回调验收许可', 'params': {'值': 'u32'},
            'result': 'u32', 'locals': {}, 'effects': EFFECTS}]}, ensure_ascii=False), encoding='utf-8')
        build(parse(source), script, binary, target='llvm', allow_native=True,
              mi_manifest=manifest, llvm_clang=os.environ.get('RU_LLVM_CLANG'))
        self.assertEqual(binary.read_bytes()[:2], b'MZ')
        return binary, script

    def run_executable(self, executable, *, timeout=45, arguments=()):
        result = acceptance.bounded_run([str(executable), *arguments], timeout=timeout,
            env=dict(os.environ, RU_GC_THRESHOLD='1', RU_GC_STATS='1'))
        evidence = os.environ.get('RU_LLVM_CALLBACK_EVIDENCE')
        if evidence:
            stem = Path(evidence)/self._testMethodName
            stem.parent.mkdir(parents=True, exist_ok=True)
            stem.with_suffix('.stdout').write_text(result.stdout, encoding='utf-8')
            stem.with_suffix('.stderr').write_text(result.stderr, encoding='utf-8')
            stem.with_suffix('.json').write_text(json.dumps({'returncode': result.returncode,
                'llvm': self.toolchain.version, 'triple': self.toolchain.triple,
                'gc_threshold': 1}), encoding='utf-8')
        self.assertRegex(result.stderr, r'RU_GC live=0 freed=\d+ collections=\d+\n')
        result.stderr = re.sub(r'RU_GC live=0 freed=\d+ collections=\d+\n', '', result.stderr)
        return result

    def assert_native_parity(self, body, expected, *, success=True):
        with tempfile.TemporaryDirectory() as directory:
            executable, _ = self.build_executable(self.program(body), directory)
            result = self.run_executable(executable)
        self.assertEqual(result.returncode == 0, success, result.stdout+result.stderr)
        self.assertEqual(result.stdout, expected)
        self.assertEqual(result.stderr, '')
        return result, result

    test_normal_nested_and_panic = acceptance.NativeCWindowsAcceptanceTests.test_nested_synchronous_callback_and_native_return_after_error
    test_ordinary_error_and_recovery = acceptance.NativeCWindowsAcceptanceTests.test_runtime_error_uses_fallback_and_allows_later_native_call
    test_closed_tombstone = acceptance.NativeCWindowsAcceptanceTests.test_closed_callback_tombstone_returns_fallback_without_ru
    test_active_closed_reentry = acceptance.NativeCWindowsAcceptanceTests.test_active_closed_callback_reentry_uses_saved_fallback
    test_first_import_and_retry = acceptance.NativeCWindowsAcceptanceTests.test_first_callback_module_initialization_is_contained_and_retryable
