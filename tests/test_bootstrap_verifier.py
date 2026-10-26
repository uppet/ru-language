"""Negative controls for M4 acceptance and narrowly bounded PE normalization."""
import struct
import hashlib
from pathlib import Path, PureWindowsPath
import tempfile
from unittest.mock import patch
from tools import bootstrap_verify
import unittest

from tools.bootstrap_compare import compare_native, normalize_native
from tools.bootstrap_verify import regression_gates


def pe_fixture(timestamp):
    content = bytearray(1024)
    content[:2] = b'MZ'
    struct.pack_into('<I', content, 0x3c, 0x80)
    content[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHI', content, 0x84, 0x8664, 1, timestamp)
    struct.pack_into('<H', content, 0x94, 240)
    struct.pack_into('<H', content, 0x98, 0x20b)
    struct.pack_into('<II', content, 0x98+112+6*8, 0x1000, 28)
    struct.pack_into('<IIII', content, 0x98+240+8, 512, 0x1000, 512, 512)
    struct.pack_into('<I', content, 512+4, timestamp)
    struct.pack_into('<I', content, 512+12, 13)
    content[800:804] = b'code'
    return bytes(content)


class BootstrapVerifierTests(unittest.TestCase):
    def test_windows_snapshot_uses_canonical_relative_posix_keys(self):
        # Real Windows path semantics, exercised even on a POSIX test host.
        class WindowsInput(PureWindowsPath):
            def read_bytes(self):
                return self.name.encode('utf-8')
        paths = [WindowsInput('C:/source/tools/bootstrap.py'),
                 WindowsInput('C:/source/bootstrap/compiler.ru')]
        with patch.object(bootstrap_verify, 'ROOT', PureWindowsPath('C:/source')):
            actual = bootstrap_verify.snapshots(paths)
        self.assertEqual(actual, {
            'bootstrap/compiler.ru': hashlib.sha256(b'compiler.ru').hexdigest(),
            'tools/bootstrap.py': hashlib.sha256(b'bootstrap.py').hexdigest()})
        self.assertNotIn('bootstrap\\compiler.ru', actual)

    def test_native_snapshot_preserves_exact_bytes_and_membership(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root/'nested'/'input.ru'
            source.parent.mkdir()
            source.write_bytes(b'first\r\n')
            with patch.object(bootstrap_verify, 'ROOT', root):
                before = bootstrap_verify.snapshots([source])
                self.assertEqual(before, {'nested/input.ru': hashlib.sha256(b'first\r\n').hexdigest()})
                source.write_bytes(b'changed\n')
                self.assertNotEqual(before, bootstrap_verify.snapshots([source]))
                self.assertEqual(bootstrap_verify.snapshots([]), {})

    def test_snapshot_outside_root_is_rejected(self):
        class WindowsInput(PureWindowsPath):
            def read_bytes(self):
                raise AssertionError('outside source must not be read')
        with patch.object(bootstrap_verify, 'ROOT', PureWindowsPath('C:/source')):
            with self.assertRaises(ValueError):
                bootstrap_verify.snapshots([WindowsInput('C:/outside/input.ru')])

    def test_only_known_pe_timestamps_are_ignored(self):
        first, second = pe_fixture(1234), pe_fixture(5678)
        comparison = compare_native(first, second)
        self.assertFalse(comparison['raw_equal'])
        self.assertTrue(comparison['normalized_equal'])
        self.assertEqual([f['offset'] for f in comparison['normalization'][0]], [0x88, 516])
        self.assertEqual([f['value'] for f in comparison['normalization'][0]], [1234, 1234])

    def test_code_and_other_metadata_changes_are_not_hidden(self):
        original = pe_fixture(1234)
        for offset in (800, 0x98+64, 512+12):
            altered = bytearray(pe_fixture(5678))
            altered[offset] ^= 1
            with self.subTest(offset=offset):
                self.assertFalse(compare_native(original, bytes(altered))['normalized_equal'])

    def test_elf_requires_exact_bytes(self):
        original = b'\x7fELFcode'
        self.assertEqual(normalize_native(original), (original, []))
        self.assertFalse(compare_native(original,b'\x7fELFchanged')['normalized_equal'])

    def test_malformed_or_truncated_pe_is_rejected(self):
        for content in (b'MZ', pe_fixture(1)[:600], b'not a native binary'):
            with self.subTest(length=len(content)), self.assertRaises(ValueError):
                normalize_native(content)
        content = bytearray(pe_fixture(1))
        struct.pack_into('<II', content, 0x98+112+6*8, 0x9000, 29)
        with self.assertRaises(ValueError):
            normalize_native(bytes(content))

    def fixture(self):
        expected = {str(i): ['test_error', 'test_semantics'] for i in (1,2,3)}
        records = [{'stage':i,'case':case,'status':'passed'} for i in (1,2,3) for case in expected[str(i)]]
        return expected, records

    def test_every_stage_must_run_the_same_nonempty_suite(self):
        expected, records = self.fixture()
        self.assertTrue(all(regression_gates(expected,records).values()))
        expected['2'] = ['test_semantics']
        self.assertFalse(regression_gates(expected,records)['same_nonempty_suite_for_each_stage'])
        self.assertFalse(all(regression_gates({str(i):[] for i in (1,2,3)},[]).values()))

    def test_missing_or_duplicate_stage_cases_cannot_pass(self):
        expected, records = self.fixture()
        self.assertFalse(regression_gates(expected,records[1:])['every_planned_case_ran'])
        self.assertFalse(regression_gates(expected,records+[records[0]])['every_planned_case_ran'])

    def test_failure_error_skip_and_unfinished_cases_cannot_pass(self):
        for status in ('failed','error','skipped','running'):
            expected, records = self.fixture()
            records[0]['status'] = status
            with self.subTest(status=status):
                self.assertFalse(regression_gates(expected,records)['every_case_passed_without_skips'])


if __name__ == '__main__':
    unittest.main()
