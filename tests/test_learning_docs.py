"""Execute every documented ru/output pair on the three existing backends."""
from pathlib import Path
import re
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LearningDocsTests(unittest.TestCase):
    def test_examples(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, 'example.ru')
            for document in ('getting-started.md', 'calls-and-scope.md'):
                text = (ROOT / 'docs' / document).read_text(encoding='utf-8')
                pairs = re.findall(r'```ru\n(.*?)```\s*```output\n(.*?)```', text, re.S)
                self.assertEqual(len(pairs), text.count('```ru\n'))
                self.assertEqual(len(pairs), 7 if document == 'getting-started.md' else 3)
                for index, (code, expected) in enumerate(pairs):
                    source.write_text(code, encoding='utf-8')
                    commands = [[sys.executable, str(ROOT / 'ru'), 'run', str(source)]]
                    for target, runner in [('c', []), ('js', ['node'])]:
                        if not (any(shutil.which(name) for name in ('clang', 'gcc', 'cc')) if target == 'c' else shutil.which('node')):
                            continue
                        output = Path(directory, 'program' + ('.js' if target == 'js' else '.exe' if os.name == 'nt' else ''))
                        build = subprocess.run([sys.executable, str(ROOT / 'ru'), 'build', str(source), '--target', target, '-o', str(output)], capture_output=True, text=True, timeout=60)
                        self.assertEqual(build.returncode, 0, build.stderr)
                        commands.append(runner + [str(output)])
                    for command in commands:
                        with self.subTest(document=document, example=index + 1, command=command):
                            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertEqual(result.stdout, expected)
