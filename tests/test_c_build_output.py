"""C build publication does not infer target filenames from the build host."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from rulang.cli import build
from rulang.frontend import RuError, parse


class CBuildOutputTests(unittest.TestCase):
    def test_compiler_that_appends_exe_publishes_exact_requested_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'entry.ru'
            source.write_text('显 7.', encoding='utf-8')
            for name in ('result', 'result.exe'):
                with self.subTest(output=name):
                    output = root / name
                    output.write_bytes(b'previous output')

                    def compile_executable(command, **options):
                        requested = Path(command[command.index('-o') + 1])
                        # Model MinGW's target suffix behavior independently of
                        # the host running this portable build-publication test.
                        actual = requested if requested.suffix == '.exe' else Path(str(requested) + '.exe')
                        actual.write_bytes(b'compiled executable')
                        return subprocess.CompletedProcess(command, 0, '', '')

                    with patch('rulang.cli.subprocess.run', side_effect=compile_executable) as compiler:
                        result, _ = build(parse(source.read_text(encoding='utf-8')),
                                          source, output, cc='fixture-cc')
                    self.assertEqual(result, output.resolve())
                    self.assertEqual(output.read_bytes(), b'compiled executable')
                    self.assertEqual(compiler.call_count, 1)
                    self.assertEqual(list(root.glob('.ru-build-*')), [])

    def test_failed_compiler_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / 'entry.ru', root / 'result.exe'
            source.write_text('显 7.', encoding='utf-8')
            output.write_bytes(b'previous output')
            with patch('rulang.cli.subprocess.run', return_value=subprocess.CompletedProcess(
                    ['fixture-cc'], 1, '', 'fixture compilation failure')), \
                    self.assertRaisesRegex(RuError, 'fixture compilation failure'):
                build(parse(source.read_text(encoding='utf-8')), source, output, cc='fixture-cc')
            self.assertEqual(output.read_bytes(), b'previous output')
            self.assertEqual(list(root.glob('.ru-build-*')), [])


if __name__ == '__main__':
    unittest.main()
