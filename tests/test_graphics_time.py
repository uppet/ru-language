"""Private monotonic canvas timing, independent of callback resource budgets."""
import io
import unittest
from unittest.mock import patch

from rulang.frontend import RuError, parse
from rulang.graphics_runtime import GraphicsHost
from rulang.interpreter import Interpreter

PREFIX = "观 取 外言 '如:观'. 图 取 观 其 画布 100 80. "
READ = "[图 其 经过秒, 图 其 间隔秒, 图 其 经过秒, 图 其 间隔秒, 图 其 帧]"
FRAME = f"图 其 每帧 (作 帧: 显 {READ}. 为). "
KEY = f"图 其 按键 (作 键: 显 {READ}. 为). "
MOUSE = f"图 其 鼠标移动 (作 横 纵: 显 {READ}. 为). "


class Clock:
    def __init__(self, value=100.):
        self.value, self.calls = value, 0

    def __call__(self):
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class GraphicsTimeTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.events, self.output = Clock(), [], io.StringIO()
        self.interpreter = Interpreter(stdout=self.output)
        self.host = GraphicsHost(self.interpreter, self.events.append, now_seconds=self.clock)
        self.addCleanup(self.host.close)

    def run_ru(self, source):
        self.interpreter.execute(parse(source))
        self.host.flush()

    def canvas(self, code=''):
        self.run_ru(PREFIX + code)

    def read(self):
        self.run_ru('快照 取 ' + READ + '.')
        return self.interpreter.global_scope.values['快照']

    def frame(self, now):
        self.clock.value = now
        self.host.handle({'type': 'frame'})
        return self.read()

    def test_initial_zero_and_frozen_repeated_reads_do_not_sample(self):
        self.canvas(FRAME)
        self.assertEqual(self.clock.calls, 1)
        self.clock.value = 200
        self.assertEqual(self.read(), [0, 0, 0, 0, 0])
        self.assertEqual(self.read(), [0, 0, 0, 0, 0])
        self.assertEqual(self.clock.calls, 1)
        self.assertEqual(self.frame(202.5), [102.5, 0, 102.5, 0, 1])
        self.assertEqual(self.frame(203.25), [103.25, .75, 103.25, .75, 2])
        self.assertEqual(self.clock.calls, 3)
        self.assertEqual(self.output.getvalue(), '[102.5, 0, 102.5, 0, 1]\n[103.25, 0.75, 103.25, 0.75, 2]\n')

    def test_input_delta_zero_without_advancing_previous_frame(self):
        self.canvas(FRAME + KEY + MOUSE)
        self.assertEqual(self.frame(101), [1, 0, 1, 0, 1])
        self.clock.value = 102
        self.host.handle({'type': 'key_down', 'key': 'A'})
        self.assertEqual(self.read(), [2, 0, 2, 0, 1])
        self.clock.value = 103
        self.host.handle({'type': 'mouse_move', 'x': 2, 'y': 3})
        self.assertEqual(self.read(), [3, 0, 3, 0, 1])
        self.assertEqual(self.frame(110), [10, 9, 10, 9, 2])
        self.assertEqual(self.clock.calls, 5)

    def test_static_inputs_advance_elapsed_but_never_frames(self):
        self.canvas(KEY)
        for now in (102, 110, 1000):
            self.clock.value = now
            self.host.handle({'type': 'key_down', 'key': 'A'})
            self.assertEqual(self.read(), [now - 100, 0, now - 100, 0, 0])

    def test_pause_resume_idempotence_and_replacement(self):
        self.canvas(FRAME + KEY)
        self.frame(101)
        self.run_ru('图 其 继续. 图 其 继续. ' + FRAME)
        self.assertEqual(self.frame(102), [2, 1, 2, 1, 2])
        self.run_ru('图 其 停.')
        self.clock.value = 120
        self.host.handle({'type': 'key_down', 'key': 'A'})
        self.run_ru('图 其 继续. 图 其 继续.')
        self.assertEqual(self.frame(150), [50, 0, 50, 0, 3])
        self.assertEqual(self.frame(151), [51, 1, 51, 1, 4])
        self.run_ru('图 其 停. ' + FRAME)
        self.assertEqual(self.frame(200), [100, 0, 100, 0, 5])
        # A hidden/background gap is raw host time: no clamp or catch-up frames.
        self.assertEqual(self.frame(1200), [1100, 1000, 1100, 1000, 6])

    def test_stop_resume_inside_frame_does_not_rewrite_frozen_snapshot(self):
        self.canvas(f'图 其 每帧 (作 帧: 显 {READ}. 图 其 停. 图 其 继续. 显 {READ}. 为).')
        self.frame(101)
        self.assertEqual(self.frame(200), [100, 0, 100, 0, 2])
        lines = self.output.getvalue().splitlines()
        self.assertEqual(lines[0], lines[1])
        self.assertEqual(lines[2], lines[3])

    def test_replacement_canvas_resets_origin_and_public_values(self):
        self.canvas(FRAME)
        old = self.host.canvas
        self.frame(102)
        self.clock.value = 110
        self.run_ru('图 取 观 其 画布 20 20. ' + FRAME)
        self.assertTrue(old.closed)
        self.assertEqual(self.read(), [0, 0, 0, 0, 0])
        self.assertEqual(self.frame(112), [2, 0, 2, 0, 1])

    def test_getters_are_numeric_zero_argument_read_only_members(self):
        self.canvas()
        self.run_ru('显 (图 其 经过秒) + (图 其 间隔秒) + 1.')
        self.assertEqual(self.output.getvalue(), '1\n')
        for name in ('经过秒', '间隔秒'):
            for source in (f'图 其 {name} 1.', f'图 其 {name} 秒: 1.',
                           f'图 其 {name} 取 1.', f'观 其 {name}.'):
                with self.subTest(source=source), self.assertRaises(RuError):
                    self.run_ru(source)
        self.assertEqual(self.clock.calls, 1)

    def test_invalid_disabled_stale_and_closed_events_never_sample(self):
        self.canvas(FRAME + KEY + MOUSE)
        for event in (None, [], {}, {'type': 'unknown'}, {'type': []},
                      {'type': 'key_down'}, {'type': 'key_down', 'key': 3},
                      {'type': 'key_down', 'key': 'a' * 65},
                      {'type': 'mouse_move', 'x': float('nan'), 'y': 2},
                      {'type': 'mouse_move', 'x': True, 'y': 2},
                      {'type': 'mouse_move', 'x': 0, 'y': 0, 'button': True},
                      {'type': 'mouse_up', 'x': 0, 'y': 0, 'button': 0},
                      *({'type': 'frame', key: 123} for key in
                        ('time', 'timestamp', 'elapsed', 'delta', 'nowSeconds', '经过秒', '间隔秒'))):
            with self.subTest(event=event), self.assertRaises(RuError):
                self.host.handle(event)
        with self.assertRaisesRegex(RuError, '失效'):
            self.host.handle({'type': 'frame'}, canvas_id='old-canvas')
        self.run_ru('图 其 停.')
        with self.assertRaisesRegex(RuError, '未启用'):
            self.host.handle({'type': 'frame'})
        self.assertEqual(self.clock.calls, 1)
        self.assertEqual(self.read(), [0, 0, 0, 0, 0])
        self.host.handle({'type': 'close'})
        with self.assertRaisesRegex(RuError, '已关闭'):
            self.host.handle({'type': 'frame'})
        self.assertEqual(self.clock.calls, 1)

    def test_invalid_clock_closes_before_frame_or_scene_mutation(self):
        invalid = (True, None, '101', [], {}, float('nan'), float('inf'),
                   -float('inf'), -1, 99, 10 ** 400, RuntimeError('secret clock detail'))
        for value in invalid:
            with self.subTest(value=type(value).__name__):
                self.host.close()
                self.clock.value = 100
                self.canvas(FRAME + "图 其 线 0 0 1 1.")
                canvas, event_count = self.host.canvas, len(self.events)
                self.clock.value = value
                with self.assertRaisesRegex(RuError, '宿主单调时钟无效') as caught:
                    self.host.handle({'type': 'frame'})
                self.assertNotIn('secret', str(caught.exception))
                self.assertEqual(canvas.frame, 0)
                self.assertEqual((canvas._elapsed, canvas._delta), (0, 0))
                self.assertIsNone(self.host.canvas)
                self.assertEqual([e['type'] for e in self.events[event_count:]], ['graphics_closed'])

    def test_clock_is_nondecreasing_across_input_and_frame_samples(self):
        self.canvas(FRAME + KEY)
        self.frame(101)
        self.clock.value = 120
        self.host.handle({'type': 'key_down', 'key': 'A'})
        self.clock.value = 119
        with self.assertRaisesRegex(RuError, '宿主单调时钟无效'):
            self.host.handle({'type': 'frame'})
        self.assertIsNone(self.host.canvas)

    def test_bad_initial_clock_is_atomic_and_does_not_leak_tracing(self):
        self.clock.value = float('nan')
        with self.assertRaisesRegex(RuError, '宿主单调时钟无效'):
            self.canvas()
        self.assertIsNone(self.host.canvas)
        self.assertFalse(self.host.owns_tracing)
        self.clock.value = 100
        self.canvas(FRAME)
        canvas, previous_events = self.host.canvas, list(self.events)
        self.clock.value = RuntimeError('secret')
        with self.assertRaisesRegex(RuError, '宿主单调时钟无效'):
            self.run_ru('新图 取 观 其 画布 20 20.')
        self.assertIs(self.host.canvas, canvas)
        self.assertFalse(canvas.closed)
        self.assertEqual(self.events, previous_events)

    def test_equal_samples_and_large_finite_host_times_are_valid(self):
        self.clock.value = 0
        self.canvas(FRAME)
        self.assertEqual(self.frame(0), [0, 0, 0, 0, 1])
        self.assertEqual(self.frame(1e308), [1e308, 1e308, 1e308, 1e308, 2])
        self.assertEqual(self.frame(1e308), [1e308, 0, 1e308, 0, 3])

    def test_frozen_time_cannot_bypass_live_wall_or_work_budget(self):
        self.canvas(f'图 其 每帧 (作 帧: 循 若 (图 其 经过秒) > 0 则 破. 然 环 为).')
        # The public elapsed sample stays zero; budget clock still advances.
        budget = iter([0., 2.])
        with patch('rulang.graphics_runtime.time.monotonic', side_effect=lambda: next(budget, 2.)):
            with self.assertRaisesRegex(RuError, '时间预算.*阈值 1 秒'):
                self.host.handle({'type': 'frame'})
        self.assertIsNone(self.host.canvas)
        self.canvas(f'图 其 每帧 (作 帧: 循 若 (图 其 经过秒) > 0 则 破. 然 环 为).')
        from rulang.execution_budget import BudgetPolicy
        with patch('rulang.graphics_runtime.time.monotonic', return_value=0), \
             patch.object(self.host, 'budget_policy', BudgetPolicy(128, 256, calibration_only=False)):
            with self.assertRaisesRegex(RuError, '逻辑工作预算.*阈值 128 工作单位'):
                self.host.handle({'type': 'frame'})
        self.assertIsNone(self.host.canvas)
        self.assertEqual(self.clock.calls, 4)
