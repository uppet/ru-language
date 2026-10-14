"""Exact resource diagnostics; fake samples, never relaxed production budgets."""
import contextlib
import hashlib
import io
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from rulang.cli import main, report
from rulang.diagnostics import SourceOrigin, diagnostic
from rulang.frontend import RuError, parse
from rulang.graphics_runtime import GraphicsHost
from rulang.generation import generation_system_prompt
from rulang.interpreter import Interpreter
from rulang.prompts import export_prompt


class GraphicsBudgetDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.interpreter = Interpreter(stdout=io.StringIO())
        # Keep the public canvas clock independent from the live budget clock.
        self.host = GraphicsHost(self.interpreter, self.events.append, now_seconds=lambda: 0.)
        self.addCleanup(self.host.close)
        self.code = "观 取 外言 '如:观'.\n图 取 观 其 画布 100 80.\n图 其 每帧 (作 帧: 为)."
        self.origin = SourceOrigin.cell('budget', '定义格', 4, 2, self.code)
        self.interpreter.execute(parse(self.code, self.origin))
        self.host.flush()
        self.node = self.host.canvas.callbacks['frame'][1]

    def handle_samples(self, *, count=0, started=0., sampled=0., allocated=0,
                       clock=None, invoke_error=None):
        """Feed exact line events and measured values through the real guard.

        Only the deterministic tests fake sampling/tracing. Real-example and full
        regression runs use the native unittest entry without any observer.
        """
        self.traces, self.seen = [], 0
        old_trace = sys.gettrace()
        def invoke(*args):
            for self.seen in range(1, count + 1):
                self.traces[0](None, 'line', None)
            if invoke_error is not None:
                raise invoke_error
        if clock is None:
            clock = lambda: started if not self.traces else sampled
        with patch('rulang.graphics_runtime.sys.settrace', side_effect=self.traces.append), \
             patch('rulang.graphics_runtime.time.monotonic', side_effect=clock) as timer, \
             patch('rulang.graphics_runtime.tracemalloc.get_traced_memory',
                   return_value=(self.host.memory_start + allocated, 0)) as memory, \
             patch.object(self.interpreter, 'invoke_value', side_effect=invoke):
            try:
                self.host.handle({'type': 'frame'})
            finally:
                self.timer_calls, self.memory_calls = timer.call_count, memory.call_count
                self.assertEqual(len(self.traces), 2)
                self.assertIs(self.traces[-1], old_trace)

    def assert_closed_with(self, text):
        self.assertIsNone(self.host.canvas)
        self.assertFalse(self.host.owns_tracing)
        self.assertEqual(self.events[-1]['type'], 'graphics_closed')
        self.assertEqual(sum(event['type'] == 'graphics' for event in self.events), 1)
        self.assertIn('已关闭交互', text)

    def test_exact_wall_limit_is_allowed(self):
        self.handle_samples(sampled=1.)
        self.assertIsNotNone(self.host.canvas)
        self.assertEqual((self.timer_calls, self.memory_calls), (2, 1))

    def test_just_below_wall_limit_is_allowed(self):
        self.handle_samples(sampled=math.nextafter(1., 0.))
        self.assertIsNotNone(self.host.canvas)

    def test_just_above_wall_limit_reports_unrounded_sample_once(self):
        sampled = math.nextafter(1., math.inf)
        clock_values = iter((0., sampled))  # A second diagnostic sample is an error.
        with self.assertRaises(RuError) as caught:
            self.handle_samples(clock=lambda: next(clock_values))
        self.assertEqual(caught.exception.message,
                         f'如观回调超过时间预算（实际约 {sampled!r} 秒墙钟耗时，阈值 1 秒）；已关闭交互，请简化回调后重跑')
        self.assertEqual((self.timer_calls, self.memory_calls), (2, 0))
        self.assert_closed_with(caught.exception.message)

    def test_wall_diagnostic_uses_nonzero_start_and_original_deadline_comparison(self):
        with self.assertRaises(RuError) as caught:
            self.handle_samples(started=1000.25, sampled=1001.5)
        self.assertIn('实际约 1.25 秒墙钟耗时，阈值 1 秒', caught.exception.message)
        self.assertEqual(self.timer_calls, 2)

    def test_rounded_elapsed_difference_explains_strict_deadline_overrun(self):
        started = math.nextafter(.5, math.inf)
        deadline = started + 1.
        sampled = math.nextafter(deadline, math.inf)
        self.assertEqual(sampled - started, 1.)
        with self.assertRaises(RuError) as caught:
            self.handle_samples(started=started, sampled=sampled)
        self.assertEqual(caught.exception.message,
                         '如观回调超过时间预算（实际约 1.0 秒墙钟耗时，阈值 1 秒；微小超限差额经浮点运算舍入）；已关闭交互，请简化回调后重跑')
        self.assertEqual(self.timer_calls, 2)

    def test_exact_line_limit_is_allowed(self):
        self.handle_samples(count=500000)
        self.assertEqual(self.seen, 500000)
        self.assertEqual(self.timer_calls, 1 + 500000 // 128 + 1)
        self.assertEqual(self.memory_calls, 500000 // 128 + 1)
        self.assertIsNotNone(self.host.canvas)

    def test_final_check_reports_one_line_over(self):
        with self.assertRaises(RuError) as caught:
            self.handle_samples(count=500001)
        self.assertEqual(caught.exception.message,
                         '如观回调超过执行行预算（实际 500001 Python 跟踪行，阈值 500000 行）；已关闭交互，请简化回调后重跑')
        self.assertEqual(self.seen, 500001)
        # The failing line guard still short-circuits the clock and memory reads.
        self.assertEqual(self.timer_calls, 1 + 500001 // 128)
        self.assertEqual(self.memory_calls, 500001 // 128)
        self.assert_closed_with(caught.exception.message)

    def test_in_callback_line_check_still_occurs_at_500096(self):
        with self.assertRaises(RuError) as caught:
            self.handle_samples(count=500200)
        self.assertEqual(self.seen, 500096)
        self.assertIn('实际 500096 Python 跟踪行，阈值 500000 行', caught.exception.message)

    def test_line_priority_when_time_and_memory_also_exceed_at_final_check(self):
        def clock():
            return 2. if self.seen > 500000 else 0.
        # Earlier checks are within all budgets; all three would be over at the
        # final check, but the original line-first short circuit must still win.
        def memory():
            return self.host.memory_start + (67108865 if self.seen > 500000 else 0), 0
        traces = []
        def invoke(*args):
            for self.seen in range(1, 500002):
                traces[0](None, 'line', None)
        self.seen = 0
        with patch('rulang.graphics_runtime.sys.settrace', side_effect=traces.append), \
             patch('rulang.graphics_runtime.time.monotonic', side_effect=clock) as timer, \
             patch('rulang.graphics_runtime.tracemalloc.get_traced_memory', side_effect=memory) as allocation, \
             patch.object(self.interpreter, 'invoke_value', side_effect=invoke):
            with self.assertRaises(RuError) as caught:
                self.host.handle({'type': 'frame'})
        self.assertIn('执行行预算', caught.exception.message)
        self.assertNotIn('时间预算', caught.exception.message)
        self.assertEqual(timer.call_count, 1 + 500000 // 128)
        self.assertEqual(allocation.call_count, 500000 // 128)
        self.assertEqual(len(traces), 2)

    def test_time_priority_when_memory_also_exceeds(self):
        with self.assertRaises(RuError) as caught:
            self.handle_samples(sampled=1.25, allocated=67108865)
        self.assertIn('时间预算', caught.exception.message)
        self.assertEqual(self.memory_calls, 0)

    def test_exact_allocation_limit_is_allowed(self):
        self.handle_samples(allocated=67108864)
        self.assertIsNotNone(self.host.canvas)
        self.assertEqual(self.memory_calls, 1)

    def test_just_below_allocation_limit_is_allowed(self):
        self.handle_samples(allocated=67108863)
        self.assertIsNotNone(self.host.canvas)

    def test_one_byte_over_reports_exact_delta_and_threshold(self):
        with self.assertRaises(RuError) as caught:
            self.handle_samples(allocated=67108865)
        self.assertEqual(caught.exception.message,
                         '如观新增内存超过分配预算（实际 67108865 字节，阈值 67108864 字节／64 MiB）；已关闭交互，请减少数据后重跑')
        self.assertEqual(self.memory_calls, 1)
        self.assert_closed_with(caught.exception.message)

    def test_callback_error_is_not_replaced_by_final_budget_check(self):
        original = RuError('原有回调错误', 7, 8, category='运行错误')
        with self.assertRaises(RuError) as caught:
            self.handle_samples(sampled=2., allocated=67108865, invoke_error=original)
        self.assertIs(caught.exception, original)
        self.assertEqual((self.timer_calls, self.memory_calls), (1, 0))
        self.assertIsNone(self.host.canvas)

    def test_budget_failure_preserves_provenance_and_cli_header(self):
        with self.assertRaises(RuError) as caught:
            self.handle_samples(sampled=1.25)
        error = caught.exception
        detail = diagnostic(error)
        self.assertEqual(detail['source'], self.origin.metadata())
        self.assertEqual(detail['source_name'], self.origin.source_name)
        self.assertEqual((detail['line'], detail['col']), (self.node.token.line, self.node.token.col))
        self.assertEqual(detail['category'], '运行错误')
        prefix = f'{self.origin.source_name}:{self.node.token.line}:{self.node.token.col}: error: 运行错误：'
        self.assertEqual(detail['formatted'], prefix + error.message)
        self.assertNotIn(self.code, error.message)
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            report(error, '<fallback>')
        self.assertEqual(stdout.getvalue(), '')
        self.assertEqual(stderr.getvalue().splitlines()[0], detail['formatted'])

    def test_resource_restore_failure_preserves_budget_error(self):
        try:
            import resource
        except ImportError:
            self.skipTest('POSIX resource limits unavailable')
        if not hasattr(resource, 'RLIMIT_AS'):
            self.skipTest('RLIMIT_AS unavailable')
        with patch.object(resource, 'getrlimit', return_value=(-1, -1)), \
             patch.object(resource, 'setrlimit', side_effect=[None, ValueError('not allowed')]) as setter:
            with self.assertRaises(RuError) as caught:
                self.handle_samples(sampled=1.25)
        self.assertIn('时间预算', caught.exception.message)
        self.assertNotIn('恢复系统内存', caught.exception.message)
        self.assertEqual(setter.call_count, 2)
        self.assertEqual(setter.call_args_list[0].args[1], (512 * 1024 * 1024, -1))
        self.assertEqual(setter.call_args_list[1].args[1], (-1, -1))
        self.assert_closed_with(caught.exception.message)


class GraphicsBudgetPromptTests(unittest.TestCase):
    def check_prompt(self, kind):
        raw = (Path(__file__).resolve().parents[1] / 'rulang/language-spec.md').read_bytes()
        spec = raw.decode('utf-8')
        self.assertTrue(spec.startswith('# 如语言规范 0.19.8\n'))
        for backend in ('python', 'browser-js'):
            with self.subTest(kind=kind, backend=backend):
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(main([kind + '-prompt', '--target', backend]), 0)
                prompt = stdout.getvalue()
                target = kind if backend == 'python' else kind + '-browser-js'
                self.assertEqual(prompt, generation_system_prompt(target))
                self.assertEqual(prompt, export_prompt(kind, runtime_target=backend))
                self.assertEqual(stderr.getvalue(), '')
                self.assertEqual(prompt.count(spec), 1)
                self.assertIn(hashlib.sha256(raw).hexdigest(), prompt)
                for text in ('预算诊断（0.19.7／如书 0.8.7）',
                             '每 128 个宿主 Python 跟踪行', '执行行不是如源码行',
                             '执行行超限先短路', '不在构造消息时再次读钟',
                             '实际约 1.0000000000000002 秒墙钟耗时，阈值 1 秒',
                             '阈值 67108864 字节／64 MiB', '达到配置的等待上限',
                             '不能伪称观测到了 Worker 实际执行耗时', '根因尚未定位'):
                    self.assertIn(text, prompt)

    def test_rushu_exports_complete_budget_contract_for_both_backends(self):
        self.check_prompt('rushu')

    def test_ruguan_exports_complete_budget_contract_for_both_backends(self):
        self.check_prompt('ruguan')
