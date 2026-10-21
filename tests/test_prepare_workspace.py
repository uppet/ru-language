"""Opt-in network use, package integrity and project-local tool publication."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import prepare_workspace as prepare


class WorkspacePreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def package(self, entries=None):
        stream = io.BytesIO()
        entries = entries or {**{'Library/bin/'+name+'.exe': b'executable' for name in prepare.TOOLS},
                              'Library/lib/clang/14.0.6/include/stddef.h': b'header',
                              'info/licenses/LICENSE.TXT': b'license',
                              'Library/bin/unneeded.exe': b'not installed'}
        with tarfile.open(fileobj=stream, mode='w:bz2') as bundle:
            for name, content in entries.items():
                item = tarfile.TarInfo(name)
                item.size = len(content)
                bundle.addfile(item, io.BytesIO(content))
        content = stream.getvalue()
        manifest = [{'name': 'fixture', 'filename': 'fixture.tar.bz2',
                     'url': 'https://example.invalid/fixture.tar.bz2',
                     'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content), 'license': 'fixture'}]
        return content, manifest

    def test_default_preparation_does_not_download(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('network')), \
                patch.object(prepare, 'prepare_llvm', side_effect=AssertionError('download')), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(prepare.main([]), 0)

    def test_corrupt_download_keeps_existing_cache_and_removes_partial(self):
        content, manifest = self.package()
        archive = self.root/'fixture.tar.bz2'
        archive.write_bytes(b'previous cached file')
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'x'*len(content))), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(prepare.PreparationError, 'SHA-256'):
            prepare.download(manifest[0], self.root)
        self.assertEqual(archive.read_bytes(), b'previous cached file')
        self.assertEqual(list(self.root.glob('.download-*')), [])

    def test_successful_installation_is_cached_and_preserves_licenses(self):
        content, manifest = self.package()
        with patch('urllib.request.urlopen', return_value=io.BytesIO(content)) as request, \
                patch.object(prepare, 'check_toolchain'), patch.object(prepare, 'smoke_test') as smoke, \
                contextlib.redirect_stdout(io.StringIO()):
            installed = prepare.prepare_llvm(self.root, manifest)
            self.assertEqual(prepare.prepare_llvm(self.root, manifest), installed)
        request.assert_called_once()
        self.assertEqual(smoke.call_count, 2)
        self.assertEqual((installed/'bin/clang.exe').read_bytes(), b'executable')
        self.assertFalse((installed/'bin/unneeded.exe').exists())
        self.assertEqual((installed/'share/licenses/fixture/LICENSE.TXT').read_bytes(), b'license')
        self.assertEqual(json.loads((installed/'packages.json').read_text()), manifest)

    def test_unsafe_archive_does_not_publish_installation(self):
        content, manifest = self.package({'../../escaped': b'escape'})
        with patch('urllib.request.urlopen', return_value=io.BytesIO(content)), \
                patch.object(prepare, 'check_toolchain', side_effect=AssertionError('tools')), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(prepare.PreparationError):
            prepare.prepare_llvm(self.root, manifest)
        self.assertFalse((self.root/'.build_tools'/prepare.INSTALL).exists())
        self.assertFalse((self.root/'escaped').exists())
        self.assertEqual(list((self.root/'.build_tools').glob('.prepare-llvm-*')), [])

    def test_existing_unowned_directory_is_preserved_without_network(self):
        installed = self.root/'.build_tools'/prepare.INSTALL
        installed.mkdir(parents=True)
        (installed/'user.txt').write_text('keep')
        _, manifest = self.package()
        with patch('urllib.request.urlopen', side_effect=AssertionError('network')), \
                self.assertRaisesRegex(prepare.PreparationError, '已有工具目录'):
            prepare.prepare_llvm(self.root, manifest)
        self.assertEqual((installed/'user.txt').read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
