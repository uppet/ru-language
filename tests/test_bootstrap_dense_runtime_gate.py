"""Requirement preflight negatives; these mocks never build an application."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_bootstrap_dense_runtime as required


class DenseRuntimeRequirementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.compiler = self.root/'stage3'
        self.compiler.write_bytes(b'not executed: requirement test fixture only')
        self.env = {'RU_BOOTSTRAP_DENSE_REQUIRED':'1',
                    'RU_BOOTSTRAP_DENSE_TEST_COMPILER':str(self.compiler),
                    'RU_BOOTSTRAP_DENSE_EVIDENCE_DIR':str(self.root/'evidence')}

    def test_required_missing_compiler_fails_not_skip(self):
        for path in ('', 'relative-stage3', str(self.root/'absent')):
            with patch.dict(os.environ,{**self.env,'RU_BOOTSTRAP_DENSE_TEST_COMPILER':path},clear=True):
                with self.assertRaises(RuntimeError): required.require_runtime_inputs()

    def test_required_missing_evidence_directory_fails_not_skip(self):
        for path in ('','relative-evidence'):
            with patch.dict(os.environ,{**self.env,'RU_BOOTSTRAP_DENSE_EVIDENCE_DIR':path},clear=True):
                with self.assertRaises(RuntimeError): required.require_runtime_inputs()

    def test_required_missing_llvm14_fails_not_skip(self):
        with patch.dict(os.environ,self.env,clear=True), patch.object(required,'LLVMToolchain',side_effect=RuntimeError('missing LLVM14')):
            with self.assertRaisesRegex(RuntimeError,'missing LLVM14'): required.require_runtime_inputs()

    def test_non14_cannot_satisfy_required_version(self):
        with patch.dict(os.environ,self.env,clear=True), patch.object(required,'LLVMToolchain',return_value=SimpleNamespace(version='clang version 17.0.0')):
            with self.assertRaisesRegex(RuntimeError,'LLVM14'): required.require_runtime_inputs()

    def test_source_fixture_bytes_survive_windows_newline_model(self):
        path = self.root/'fixture.ru'
        text = '算 字节 文:\n 得 文 其 量.\n法\n'
        def windows_text_write(target, data, *args, **kwargs):
            return target.write_bytes(data.replace('\n','\r\n').encode('utf-8'))
        with patch.object(Path,'write_text',autospec=True,side_effect=windows_text_write):
            required.write_source_bytes(path,text)
        self.assertEqual(path.read_bytes(),text.encode('utf-8'))
        self.assertNotIn(b'\r',path.read_bytes())

    def test_optional_discovery_skip_is_not_required_evidence(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(unittest.SkipTest): required.require_runtime_inputs()


if __name__ == '__main__': unittest.main()
