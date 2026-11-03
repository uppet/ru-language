"""Opt-in planner diagnostics and fixed-point generation equivalence."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rulang.cli import main
from rulang.frontend import RuError, parse
from rulang.modules import load_module_graph
from rulang.native_c import NativeCPlan


class NativeAnalysisProfileTests(unittest.TestCase):
    SOURCE = "密 取 外言 '如:密'. 签 取 密 其 签名 (密 其 i32) ([密 其 i32]) 'cdecl'."

    def graph(self, source=None):
        return load_module_graph('/tmp/native-profile.ru', parse(source or self.SOURCE))

    def test_report_is_opt_in_and_does_not_change_thunks(self):
        graph = self.graph()
        reports = []
        plain = NativeCPlan(graph)
        measured = NativeCPlan(graph, diagnostics=reports.append)
        self.assertEqual(plain.emit_c(), measured.emit_c())
        self.assertEqual(len(reports), 1)
        report = reports[0]
        self.assertTrue(report['completed'])
        self.assertEqual(report['steps'], sum(report['module_steps'].values()))
        self.assertEqual(report['function_evaluations'], sum(report['function_evaluations_by_site'].values()))
        self.assertEqual(report['step_limit'], 200000)
        self.assertGreaterEqual(report['seconds'], 0)

    def test_budget_error_retains_statistics_and_stop_location_caveat(self):
        reports = []
        with patch('rulang.native_c.MAX_ANALYSIS_STEPS', 10):
            with self.assertRaisesRegex(RuError, '此位置仅为停止处'):
                NativeCPlan(self.graph(), diagnostics=reports.append)
        self.assertEqual(len(reports), 1)
        self.assertFalse(reports[0]['completed'])
        self.assertEqual(reports[0]['steps'], 11)
        self.assertEqual(reports[0]['step_limit'], 10)

    def test_abi_error_also_reports_and_is_not_replaced(self):
        reports = []
        with self.assertRaisesRegex(RuError, '无法静态确定'):
            NativeCPlan(self.graph("密 取 外言 '如:密'. 签 取 密 其 签名 (读) ([]) 'cdecl'."), diagnostics=reports.append)
        self.assertFalse(reports[0]['completed'])

    def test_cli_flag_outputs_json_on_stderr_not_program_stdout(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'profile.ru'
            path.write_text(self.SOURCE, encoding='utf-8')
            for enabled in (False, True):
                stdout, stderr = io.StringIO(), io.StringIO()
                args = ['check', str(path), '--allow-native']
                if enabled:
                    args += ['--native-analysis']
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(main(args), 0)
                self.assertIn('检查通过', stdout.getvalue())
                records = [json.loads(line) for line in stderr.getvalue().splitlines() if line.startswith('{')]
                self.assertEqual(bool(records), enabled)
                self.assertTrue(all(record['completed'] for record in records))
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['check', str(path), '--target', 'python', '--native-analysis']), 1)

    def test_generation_does_not_serialize_graph_for_loop_fixed_points(self):
        source = self.SOURCE + ' 位 取 0. 循 10 次 位 取 位+1. 环.'
        with patch.object(NativeCPlan, '_state', side_effect=AssertionError('whole graph scan')):
            NativeCPlan(self.graph(source))

    def test_generation_and_structural_oracle_find_same_signatures(self):
        sources = [self.SOURCE,
                   self.SOURCE + ' 位 取 0. 循 10 次 位 取 位+1. 环.',
                   "密 取 外言 '如:密'. 算 包 值: 得 密 其 签名 值 ([值]) 'cdecl'. 法. 显 包 (密 其 i32). 显 包 (密 其 u8)."]
        for source in sources:
            with self.subTest(source=source):
                graph = self.graph(source)
                actual = NativeCPlan(graph)
                with patch.object(NativeCPlan, '_fixed_point_state', NativeCPlan._state):
                    oracle = NativeCPlan(graph)
                self.assertEqual(actual.emit_c(), oracle.emit_c())
                self.assertEqual(actual.callback_signatures, oracle.callback_signatures)


if __name__ == '__main__':
    unittest.main()
