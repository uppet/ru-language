"""Shared editor diagnostics and persistent notebook source identities."""
import contextlib
import hashlib
import io
import unittest

from rulang.cli import report
from rulang.diagnostics import SourceOrigin, diagnostic
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter
from rulang.graphics_runtime import GraphicsHost
from rushu.kernel import KernelError, Session
from test_rushu_kernel import wait_for, output


class DiagnosticTests(unittest.TestCase):
    def test_real_paths_and_single_line_header(self):
        for path in ('/tmp/中文 file.ru', r'C:\项目 空间\测试.ru'):
            error = RuError('期待名称\n第二行', 51, 5)
            detail = diagnostic(error, path)
            self.assertEqual(detail['formatted'], path + ':51:5: error: 语法错误：期待名称\\n第二行')
            self.assertEqual(detail['source'], {'kind': 'file'})

    def test_control_characters_escape_only_display_fields(self):
        controls = '\r\n\t\x1b\u061c\u200e\u200f\u2028\u2029\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069'
        path = 'C:\\项目 空间\\' + controls + '.ru'
        detail = diagnostic(RuError('说明' + controls, 2, 3), path)
        self.assertEqual(detail['source_name'], path)
        self.assertEqual(detail['message'], '说明' + controls)
        self.assertTrue(detail['formatted'].startswith('C:\\项目 空间\\'))
        for char in controls:
            self.assertNotIn(char, detail['formatted'])
        for escaped in ('\\r', '\\n', '\\t', '\\u001b', '\\u202e', '\\u2069'):
            self.assertIn(escaped, detail['formatted'])

    def test_unknown_location_is_not_fabricated(self):
        error = RuError('宿主错误', category='运行错误')
        error.location_known = False
        detail = diagnostic(error, '<如书>')
        self.assertIsNone(detail['line'])
        self.assertIsNone(detail['col'])
        self.assertEqual(detail['formatted'], '<如书>: error: 运行错误：宿主错误')

    def test_report_only_stderr(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            report(RuError('错误', 2, 3), '中文 空间.ru', '首行\n  源码')
        self.assertEqual(stdout.getvalue(), '')
        self.assertTrue(stderr.getvalue().startswith('中文 空间.ru:2:3: error: 语法错误：错误\n'))

    def test_parser_unicode_columns_and_origin_without_text(self):
        code = "显 '😀'. @"
        origin = SourceOrigin.cell('session', '中文 /格', 2, 1, code)
        with self.assertRaises(RuError) as caught:
            parse(code, origin)
        detail = diagnostic(caught.exception)
        self.assertEqual(detail['col'], 8)
        self.assertEqual(detail['source']['source_version'], hashlib.sha256(code.encode()).hexdigest())
        self.assertIn('%2F', detail['source_name'])
        self.assertNotIn('source_text', vars(origin))
        self.assertNotIn(code, repr(origin))

    def test_old_function_and_panic_keep_defining_cell(self):
        for body in ('显 1/0.', "卒 '原因'."):
            interpreter = Interpreter(stdout=io.StringIO())
            definition = '作 旧:\n  ' + body + '\n为'
            first = SourceOrigin.cell('s', 'definition', 1, 1, definition)
            interpreter.execute(parse(definition, first))
            second = SourceOrigin.cell('s', 'caller', 2, 1, '旧.')
            with self.assertRaises(RuError) as caught:
                interpreter.execute(parse('旧.', second))
            detail = diagnostic(caught.exception, origin=second)
            self.assertEqual(detail['source'], first.metadata())
            self.assertEqual(detail['line'], 2)

    def test_old_graphics_callback_keeps_definition_origin(self):
        interpreter = Interpreter(stdout=io.StringIO())
        host = GraphicsHost(interpreter, lambda event: None)
        interpreter.graphics_host = host
        self.addCleanup(host.close)
        code = '作 绘 帧:\n 显 1/0.\n为'
        origin = SourceOrigin.cell('s', 'callback-definition', 1, 1, code)
        interpreter.execute(parse(code, origin))
        setup = "观 取 外言 '如观'. 布 取 观 其 画布 400 300. 布 其 每帧 作 绘."
        interpreter.execute(parse(setup, SourceOrigin.cell('s', 'canvas', 2, 1, setup)))
        with self.assertRaises(RuError) as caught:
            host.handle({'type': 'frame'})
        self.assertEqual(diagnostic(caught.exception)['source'], origin.metadata())


class NotebookDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.addCleanup(self.session.close)

    def run_cell(self, code, cell):
        after = self.session.snapshot()['cursor']
        reply = self.session.execute(code, cell)
        self.assertEqual(reply['source_version'], hashlib.sha256(code.encode()).hexdigest())
        return wait_for(self.session, after=after)

    def test_structured_error_and_program_output_separated(self):
        self.run_cell('作 旧:\n 显 1/0.\n为', 'definition')
        result = self.run_cell("显 '输出'. 旧.", 'caller')
        self.assertEqual(output(result), '输出\n')
        event = next(e for e in result['events'] if e['type'] == 'error')
        self.assertEqual((event['cell_id'], event['execution_count']), ('caller', 2))
        detail = event['diagnostic']
        self.assertEqual((detail['source']['cell_id'], detail['source']['execution_count']), ('definition', 1))
        self.assertEqual(detail['severity'], 'error')
        self.assertIn(':2:5: error:', detail['formatted'])
        self.assertTrue(detail['source_name'].startswith('rushu://'))
        self.session.reset()
        self.assertIsNone(self.session.snapshot()['source_version'])

    def test_invalid_unicode_identity_rejected_before_execution(self):
        for code, cell in (("显 '\ud800'.", 'cell'), ('显 1.', '\ud800')):
            with self.assertRaises(KernelError):
                self.session.execute(code, cell)
        self.assertEqual(self.session.snapshot()['execution_count'], 0)
        self.assertEqual(self.session.snapshot()['state'], 'idle')

    def test_syntax_error_has_current_cell_origin(self):
        result = self.run_cell('显 @.', 'bad')
        event = next(e for e in result['events'] if e['type'] == 'error')
        self.assertEqual(event['diagnostic']['source']['cell_id'], 'bad')
        self.assertEqual((event['line'], event['col']), (1, 3))
        self.assertEqual(output(result), '')


if __name__ == '__main__':
    unittest.main()
