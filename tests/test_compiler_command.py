"""Compiler paths must survive Windows spaces and backslashes."""
from pathlib import Path
import tempfile
import unittest

from rulang.cli import compiler_command
from rulang.frontend import RuError


class CompilerCommandTests(unittest.TestCase):
    def test_existing_path_with_spaces_is_one_argument(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'compiler with spaces.exe'
            path.write_text('fixture')
            self.assertEqual(compiler_command(str(path)), [str(path)])

    def test_windows_quoted_path_keeps_backslashes(self):
        self.assertEqual(compiler_command(r'"C:\Program Files\Compiler\gcc.exe" -g', windows=True),
                         [r'C:\Program Files\Compiler\gcc.exe', '-g'])

    def test_posix_command_flags(self):
        self.assertEqual(compiler_command('gcc -g -DNAME="hello world"', windows=False),
                         ['gcc', '-g', '-DNAME=hello world'])

    def test_unclosed_quote_is_language_error(self):
        with self.assertRaises(RuError):
            compiler_command('"unfinished', windows=True)
