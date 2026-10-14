"""Real-time graphics still use authenticated, clock-free event messages."""
import math
import time
import unittest
from unittest.mock import Mock, patch

import test_rushu_graphics_bridge as bridge
from rushu.kernel import KernelError, Session

SOURCE = """观 取 外言 '如:观'. 图 取 观 其 画布 160 100.
图 其 矩形 (图 其 经过秒) (图 其 间隔秒) 0 1.
作 绘 帧: 图 其 矩形 (图 其 经过秒) (图 其 间隔秒) 帧 1. 为
图 其 每帧 作 绘.
图 其 按键 (作 键:
 图 其 矩形 (图 其 经过秒) (图 其 间隔秒) 99 1.
 若 键 == 'p' 则 图 其 停. 然
 若 键 == 'r' 则 图 其 继续. 然
 若 键 == 'c' 则 图 其 继续. 图 其 继续. 然
 若 键 == 'b' 则 图 其 每帧 作 绘. 然
为).
"""
CLOCK_FIELDS = ('time', 'timestamp', 'elapsed', 'delta', 'now', 'nowSeconds',
                'now_seconds', '经过秒', '间隔秒')


class GraphicsTimeProtocolTests(unittest.TestCase):
    def test_clock_fields_and_stale_identity_never_reach_child(self):
        with patch.object(Session, '_start'):
            session = Session()
        session.connection = Mock()
        self.addCleanup(session._cancel_graphics_timer)
        session.cell_id, session.execution_count = 'timing', 1
        session._accept_graphics({'type': 'graphics', 'canvas_id': 'c', 'width': 10,
                                 'height': 10, 'fps': 30, 'running': True,
                                 'handlers': ['frame', 'key_down'], 'commands': []})
        args = dict(canvas_id='c', cell_id='timing', execution_count=1, expected_generation=1)
        for field in CLOCK_FIELDS:
            for kind in ('frame', 'key_down'):
                event = {'type': kind, field: 1e99}
                if kind == 'key_down':
                    event['key'] = 'x'
                with self.subTest(field=field, kind=kind), self.assertRaises(KernelError) as caught:
                    session.dispatch_graphics(**args, event=event)
                self.assertEqual(caught.exception.status, 400)
        for field, value in [('canvas_id', 'old'), ('cell_id', 'old'),
                             ('execution_count', 0), ('expected_generation', 0)]:
            with self.subTest(field=field), self.assertRaises(KernelError) as caught:
                session.dispatch_graphics(**dict(args, **{field: value}), event={'type': 'frame'})
            self.assertEqual(caught.exception.status, 409)
        session.connection.send.assert_not_called()
        self.assertFalse(session.graphics_busy)
        self.assertEqual(list(session.graphics_times), [])


class SpawnedGraphicsTimeTests(unittest.TestCase):
    wait_ready = bridge.SpawnedGraphicsBridgeTests.wait_ready

    def test_real_spawn_elapsed_frames_input_pause_resume_and_gap(self):
        session = Session()
        self.addCleanup(session.close)
        session.execute(SOURCE, 'timing')
        result = self.wait_ready(session)
        canvas_id = result['graphics']['canvas_id']

        def scene(result):
            value = next(e for e in reversed(result['events']) if e['type'] == 'graphics')
            # Runtime timing is never serialized as a live replay field.
            for field in CLOCK_FIELDS:
                self.assertNotIn(field, value)
                self.assertNotIn(field, result['graphics'])
            command = value['commands'][0]
            self.assertTrue(math.isfinite(command['x']) and math.isfinite(command['y']))
            return command

        def send(event, wait=.05):
            time.sleep(wait)
            session.dispatch_graphics(canvas_id, 'timing', 1, 1, event)
            result = self.wait_ready(session)
            self.assertFalse([e for e in result['events'] if e['type'] == 'error'], result)
            return result, scene(result)

        initial = scene(result)
        self.assertEqual((initial['x'], initial['y'], initial['width']), (0, 0, 0))
        _, first = send({'type': 'frame'})
        self.assertGreater(first['x'], 0)
        self.assertEqual((first['y'], first['width']), (0, 1))
        _, key = send({'type': 'key_down', 'key': 'x'})
        self.assertEqual((key['y'], key['width']), (0, 99))
        self.assertGreater(key['x'], first['x'])
        _, second = send({'type': 'frame'})
        self.assertEqual(second['width'], 2)
        self.assertAlmostEqual(second['y'], second['x'] - first['x'], places=8)
        self.assertGreater(second['y'], second['x'] - key['x'])
        for key_name in ('c', 'b'):
            _, key = send({'type': 'key_down', 'key': key_name})
            _, frame = send({'type': 'frame'})
            self.assertEqual(key['y'], 0)
            self.assertGreater(frame['y'], 0)
            self.assertAlmostEqual(frame['y'], frame['x'] - second['x'], places=8)
            second = frame
        result, paused = send({'type': 'key_down', 'key': 'p'})
        self.assertFalse(result['graphics']['running'])
        with self.assertRaises(KernelError):
            session.dispatch_graphics(canvas_id, 'timing', 1, 1, {'type': 'frame'})
        _, resumed = send({'type': 'key_down', 'key': 'r'}, .15)
        self.assertEqual(resumed['y'], 0)
        self.assertGreaterEqual(resumed['x'] - paused['x'], .14)
        _, restart = send({'type': 'frame'})
        self.assertEqual(restart['y'], 0)
        _, gap = send({'type': 'frame'}, .2)
        self.assertGreaterEqual(gap['y'], .19)
        self.assertAlmostEqual(gap['y'], gap['x'] - restart['x'], places=8)
        self.assertEqual(gap['width'], restart['width'] + 1)
        session.execute("观 取 外言 '如:观'. 新图 取 观 其 画布 20 20. 新图 其 矩形 (新图 其 经过秒) (新图 其 间隔秒) 0 1.", 'reset')
        reset = scene(self.wait_ready(session))
        self.assertEqual((reset['x'], reset['y']), (0, 0))
        with self.assertRaises(KernelError):
            session.dispatch_graphics(canvas_id, 'timing', 1, 1, {'type': 'frame'})


class GraphicsTimeHTTPTests(unittest.TestCase):
    setUp = bridge.GraphicsHTTPTests.setUp
    tearDown = bridge.GraphicsHTTPTests.tearDown
    request = bridge.GraphicsHTTPTests.request
    wait_ready = bridge.GraphicsHTTPTests.wait_ready

    def test_real_http_rejects_client_time_and_preserves_first_frame(self):
        status, created = self.request('/api/sessions', {})
        self.assertEqual(status, 201)
        sid = created['id']
        self.assertEqual(self.request(f'/api/sessions/{sid}/execute',
                                     {'code': SOURCE, 'cell_id': 'timing'})[0], 202)
        ready = self.wait_ready(sid)
        args = {'canvas_id': ready['graphics']['canvas_id'], 'cell_id': 'timing',
                'execution_count': 1, 'expected_generation': 1}
        path = f'/api/sessions/{sid}/graphics'
        for field in CLOCK_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(self.request(path, dict(args, event={'type': 'frame', field: 1e99}))[0], 400)
        for field, value in [('canvas_id', 'old'), ('cell_id', 'old'),
                             ('execution_count', 0), ('expected_generation', 0)]:
            with self.subTest(field=field):
                self.assertEqual(self.request(path, dict(args, **{field: value}, event={'type': 'frame'}))[0], 409)
        self.assertEqual(self.request(path, dict(args, event={'type': 'frame'}))[0], 202)
        ready = self.wait_ready(sid)
        command = next(e for e in reversed(ready['events']) if e['type'] == 'graphics')['commands'][0]
        self.assertEqual((command['width'], command['y']), (1, 0))
        self.assertGreaterEqual(command['x'], 0)
        self.assertLess(command['x'], 30)
