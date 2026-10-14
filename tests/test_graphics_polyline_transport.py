"""Strict polyline IPC points and real spawned/HTTP callback transport."""
import math
import time
import unittest
from unittest.mock import patch

from rushu.kernel import Session
import test_rushu_graphics_bridge as bridge

SOURCE = """观 取 外言 '如:观'. 图 取 观 其 画布 180 120.
图 其 填色 '#FF000080'. 图 其 描边 '#ABCDEF80'. 图 其 线宽 4.
图 其 平移 10 20. 图 其 裁剪 0 0 50 60.
点 取 [[0,0],[10,20],[20,0]]. 图 其 折线 点阵:点. 点[0][0] 取 99.
图 其 每帧 (作 帧: 图 其 折线 [[0,0],[帧,1],[10,0]]. 为).
图 其 按键 (作 键: 图 其 描边 空. 图 其 折线 [[0,0],[0,0]]. 为).
"""


class GraphicsPolylineIPCTests(unittest.TestCase):
    def setUp(self):
        with patch.object(Session, '_start'):
            self.session = Session()
        self.scene = {'type': 'graphics', 'canvas_id': 'polyline', 'width': 20, 'height': 20,
                      'fps': 30, 'running': False, 'handlers': [], 'commands': []}
        self.command = {'op': 'polyline', 'points': [[0, 0], [10, 20]],
                        'fill': '', 'stroke': '#ABCDEF80', 'stroke_width': 1}

    def accept(self, command):
        self.session._accept_graphics(dict(self.scene, commands=[command]))

    def test_valid_limits_repetition_and_styles(self):
        for count in (2, 3, 256):
            for stroke in ('', '#ABCDEF', '#12345600', '#AABBCC80'):
                self.accept(dict(self.command, points=[[-100000, 100000]] * count, stroke=stroke, stroke_width=256))
        self.accept(dict(self.command, transform=[-1, 0, 0, 0, 20, 30],
                         clips=[{'x': 0, 'y': 0, 'width': 0, 'height': 30, 'transform': [1, 0, 0, 1, 0, 0]}]))

    def test_invalid_point_arrays_reject_atomically(self):
        self.accept(self.command)
        previous = self.session.graphics
        invalid = [None, True, 'points', {}, (), [], [[0, 0]], [[0, 0]] * 257, [0, 1],
                   [None, [1, 1]], [[0], [1, 1]], [[0, 0, 0], [1, 1]], [(0, 0), [1, 1]]]
        for bad in (None, True, False, '1', [], {}, math.nan, math.inf, -math.inf, 100001, -100001):
            invalid.extend([[[bad, 0], [1, 1]], [[0, 0], [1, bad]]])
        for points in invalid:
            with self.subTest(points=points), self.assertRaises(ValueError):
                self.accept(dict(self.command, points=points))
            self.assertIs(self.session.graphics, previous)
        command = dict(self.command)
        del command['points']
        with self.assertRaises(ValueError):
            self.accept(command)
        self.assertIs(self.session.graphics, previous)

    def test_invalid_styles_and_op_types_reject_atomically(self):
        self.accept(self.command)
        previous = self.session.graphics
        patches = [{'fill': x} for x in (None, True, 0, [], {}, '#000000', '#00000000')]
        patches += [{'stroke': x} for x in (None, True, 0, [], {}, 'red', '#fff', '#123456\n')]
        patches += [{'stroke_width': x} for x in (None, True, False, '1', [], {}, math.nan, math.inf, 0, .5, 257)]
        patches += [{'op': x} for x in (['polyline'], {}, None, True, 1, 'constructor', 'path')]
        patches += [{'align': 'left'}, {'baseline': 'top'}]
        for fields in patches:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.accept(dict(self.command, **fields))
            self.assertIs(self.session.graphics, previous)
        for field in ('fill', 'stroke', 'stroke_width'):
            command = dict(self.command)
            del command[field]
            with self.assertRaises(ValueError):
                self.accept(command)

    def test_geometry_state_and_size_caps_reject_without_replacing_live_state(self):
        self.accept(self.command)
        previous = self.session.graphics
        clip = {'x': 0, 'y': 0, 'width': 2, 'height': 3, 'transform': [1, 0, 0, 1, 0, 0]}
        patches = [{'transform': x} for x in (None, [], [1] * 5, [1] * 7, [True, 0, 0, 1, 0, 0], [1, 0, 0, 1, math.inf, 0])]
        patches += [{'clips': x} for x in (None, {}, [None], [clip] * 33, [dict(clip, width=-1)],
                    [dict(clip, x=True)], [dict(clip, transform=None)], [[0, 0, 2, 3]])]
        for fields in patches:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.accept(dict(self.command, **fields))
            self.assertIs(self.session.graphics, previous)
        for commands in ([self.command] * 2049,
                         [dict(self.command, points=[[100000, 100000]] * 256)] * 100):
            with self.assertRaises(ValueError):
                self.session._accept_graphics(dict(self.scene, commands=commands))
            self.assertIs(self.session.graphics, previous)


class SpawnedGraphicsPolylineTests(unittest.TestCase):
    wait_ready = bridge.SpawnedGraphicsBridgeTests.wait_ready

    def test_real_spawn_snapshots_callbacks_and_empty_input_scene(self):
        session = Session()
        self.addCleanup(session.close)
        session.execute(SOURCE, 'polyline')
        result = self.wait_ready(session)
        canvas_id = result['graphics']['canvas_id']

        def commands(result):
            self.assertFalse([e for e in result['events'] if e['type'] == 'error'], result)
            return next(e for e in reversed(result['events']) if e['type'] == 'graphics')['commands']

        initial = commands(result)[0]
        self.assertEqual(initial['points'], [[0, 0], [10, 20], [20, 0]])
        self.assertEqual((initial['fill'], initial['stroke'], initial['stroke_width']), ('', '#abcdef80', 4))
        self.assertEqual(initial['transform'], [1, 0, 0, 1, 10, 20])
        self.assertEqual(len(initial['clips']), 1)
        for frame in (1, 2):
            time.sleep(.05)
            session.dispatch_graphics(canvas_id, 'polyline', 1, 1, {'type': 'frame'})
            current = commands(self.wait_ready(session))
            self.assertEqual(len(current), 1)
            self.assertEqual(current[0]['points'], [[0, 0], [frame, 1], [10, 0]])
            self.assertNotIn('transform', current[0])
            self.assertNotIn('clips', current[0])
        time.sleep(.05)
        session.dispatch_graphics(canvas_id, 'polyline', 1, 1, {'type': 'key_down', 'key': 'x'})
        current = commands(self.wait_ready(session))
        self.assertEqual(len(current), 1)
        self.assertEqual((current[0]['op'], current[0]['stroke']), ('polyline', ''))
        session.execute('显 42.', 'after-polyline')
        result = self.wait_ready(session)
        self.assertIsNone(result['graphics'])
        self.assertTrue(any(e.get('text') == '42\n' for e in result['events']))


class GraphicsPolylineHTTPTests(unittest.TestCase):
    setUp = bridge.GraphicsHTTPTests.setUp
    tearDown = bridge.GraphicsHTTPTests.tearDown
    request = bridge.GraphicsHTTPTests.request
    wait_ready = bridge.GraphicsHTTPTests.wait_ready

    def test_http_native_command_and_stale_identity_guards(self):
        status, created = self.request('/api/sessions', {})
        self.assertEqual(status, 201)
        sid = created['id']
        self.assertEqual(self.request(f'/api/sessions/{sid}/execute', {'code': SOURCE, 'cell_id': 'polyline'})[0], 202)
        ready = self.wait_ready(sid)
        scene = next(e for e in reversed(ready['events']) if e['type'] == 'graphics')
        self.assertEqual(scene['commands'][0]['points'], [[0, 0], [10, 20], [20, 0]])
        args = {'canvas_id': ready['graphics']['canvas_id'], 'cell_id': 'polyline', 'execution_count': 1, 'expected_generation': 1}
        path = f'/api/sessions/{sid}/graphics'
        for field, value in [('canvas_id', 'old'), ('cell_id', 'old'), ('execution_count', 0), ('expected_generation', 0)]:
            self.assertEqual(self.request(path, dict(args, **{field: value}, event={'type': 'frame'}))[0], 409)
        self.assertEqual(self.request(path, dict(args, event={'type': 'key_down', 'key': 'x'}))[0], 202)
        ready = self.wait_ready(sid)
        commands = next(e for e in reversed(ready['events']) if e['type'] == 'graphics')['commands']
        self.assertEqual(len(commands), 1)
        self.assertEqual((commands[0]['op'], commands[0]['stroke']), ('polyline', ''))
