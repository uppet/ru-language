"""Chinese comments share a lexer across all engines and generation entry checks."""
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.frontend import Incomplete, lex, parse
from rulang.interpreter import Interpreter
from rulang.cli import build
from rulang.modules import generation_intent

SOURCE = '''批. 作 假: 显 999. 为
批评 取 2. 解释 取 3. 总批 取 4.
解。 若 1 则 " unmatched quote
解. nested opener is plain text; foo释.
显 批评 + 解释 + 总批. 批。 inline comment
显 解. discarded 释。 7.
显 "批. 解。 释. # //".
# old comment
// old comment
'''
EXPECTED = '9\n7\n批. 解。 释. # //\n'


class ChineseComments(unittest.TestCase):
    def test_interpreter_and_crlf(self):
        for source in (SOURCE, SOURCE.replace('\n', '\r\n')):
            output = io.StringIO()
            Interpreter(io.StringIO(), output).execute(parse(source))
            self.assertEqual(output.getvalue(), EXPECTED)

    def test_marker_punctuation_is_not_statement_terminator(self):
        self.assertEqual([t.value for t in lex('显 1 批. text\n+2.')],
                         ['显', '1', '+', '2', '.', '<文件尾>'])
        self.assertEqual([t.value for t in lex('显 1 解. text 释. +2.')],
                         ['显', '1', '+', '2', '.', '<文件尾>'])

    def test_whole_names_and_marker_adjacency(self):
        source = '批评 解释 总批 总解 _批 批2 批 . 解 。 1批. 𐐀批.'
        self.assertEqual([t.value for t in lex(source)][:-1],
                         ['批评', '解释', '总批', '总解', '_批', '批2', '批', '.', '解', '.', '1', '批', '.', '𐐀批', '.'])

    def test_strings_are_literal(self):
        for opening, closing in [("'", "'"), ('"', '"'), ('‘', '’'), ('“', '”')]:
            value = '批. 解。 释. # //'
            self.assertEqual(lex(opening + value + closing)[0].value, value)

    def test_first_closer_wins_no_nesting_or_string_rules(self):
        self.assertEqual([t.value for t in lex('解. 解. "quoted foo释。 显 1.')],
                         ['显', '1', '.', '<文件尾>'])

    def test_unfinished_comment_location_and_post_comment_location(self):
        with self.assertRaises(Incomplete) as caught:
            parse('显 1.\r\n  解。 unfinished\n')
        self.assertEqual((caught.exception.line, caught.exception.col), (2, 3))
        token = lex('解.\r\n text\r\n释。显')[0]
        self.assertEqual((token.value, token.line, token.col), ('显', 3, 3))

    def test_generation_marker_is_never_inside_comment(self):
        for prefix in ('解.\n', '解。 "\n', '解. 解.\n'):
            self.assertIsNone(generation_intent(prefix + '如是我言\n'))
        for prefix in ('批. "\n', '批。 解.\n', '解. " 如是我言 释。\n', '总批.\n'):
            self.assertEqual(generation_intent(prefix + '如是我言\n'), prefix)
        self.assertIsNone(generation_intent('批. 如是我言\n'))

    def test_repl_waits_for_comment_and_reports_unfinished_at_eof(self):
        result = subprocess.run([sys.executable, str(ROOT/'ru'), 'repl'],
                                input='解.\n显 999.\n释. 显 7.\n', capture_output=True, text=True, timeout=10)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '7\n', ''))
        result = subprocess.run([sys.executable, str(ROOT/'ru'), 'repl'],
                                input='解.\n', capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertIn('<repl>:1:1: 语法错误', result.stderr)

    def test_file_diagnostic_and_all_backends(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'comment.ru'
            path.write_text(SOURCE, encoding='utf-8')
            for target, runner in [('c', None), ('js', shutil.which('node'))]:
                if target == 'c' and not any(shutil.which(c) for c in ('cc', 'gcc', 'clang')):
                    continue
                if target == 'js' and not runner:
                    continue
                output = Path(tmp)/('program.js' if target == 'js' else 'program')
                build(parse(SOURCE), path, output, target=target)
                command = [runner, str(output)] if runner else [str(output)]
                result = subprocess.run(command, capture_output=True, text=True, timeout=10)
                self.assertEqual((result.returncode, result.stdout), (0, EXPECTED), result.stderr)
            path.write_text('批. first\n  解. missing', encoding='utf-8')
            result = subprocess.run([sys.executable, str(ROOT/'ru'), 'check', str(path)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn(':2:3: 语法错误', result.stderr)


if __name__ == '__main__':
    unittest.main()
