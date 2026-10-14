"""Strict cubic IPC validation and real spawned/HTTP callbacks."""
import math
import time
import unittest
from unittest.mock import patch

from rushu.kernel import Session
import test_rushu_graphics_bridge as bridge

FIELDS = ('x1', 'y1', 'cx1', 'cy1', 'cx2', 'cy2', 'x2', 'y2')
SOURCE = """观 取 外言 '如:观'. 图 取 观 其 画布 180 120.
图 其 填色 '#FF000080'. 图 其 描边 '#ABCDEF80'. 图 其 线宽 4.
图 其 平移 10 20. 图 其 裁剪 0 0 50 60.
图 其 贝塞尔 终纵:8 控二横:5 起横:1 控一纵:4 终横:7 起纵:2 控二纵:6 控一横:3.
图 其 每帧 (作 帧: 图 其 贝塞尔 0 0 帧 1 10 1 20 0. 为).
图 其 按键 (作 键: 图 其 描边 空. 图 其 贝塞尔 0 0 0 0 0 0 0 0. 为).
"""


class GraphicsBezierIPCTests(unittest.TestCase):
    def setUp(self):
        with patch.object(Session, '_start'):
            self.session = Session()
        self.scene = {'type': 'graphics', 'canvas_id': 'bezier', 'width': 20, 'height': 20,
                      'fps': 30, 'running': False, 'handlers': [], 'commands': []}
        self.command = dict(zip(FIELDS, range(1, 9)), op='bezier', fill='', stroke='#ABCDEF80', stroke_width=1)

    def accept(self, command):
        self.session._accept_graphics(dict(self.scene, commands=[command]))

    def test_valid_coordinate_limits_degeneracy_and_styles(self):
        for values in ((-100000, 100000) * 4, (0,) * 8, (1.25, -1.25) * 4):
            for stroke in ('', '#ABCDEF', '#12345600', '#AABBCC80'):
                self.accept(dict(self.command, **dict(zip(FIELDS, values)), stroke=stroke, stroke_width=256))
        self.accept(dict(self.command, transform=[-1, 0, 0, 0, 20, 30],
                         clips=[{'x': 0, 'y': 0, 'width': 0, 'height': 30, 'transform': [1, 0, 0, 1, 0, 0]}]))

    def test_every_invalid_or_missing_coordinate_rejects_atomically(self):
        self.accept(self.command)
        previous = self.session.graphics
        for field in FIELDS:
            for bad in (None, True, False, '1', [], {}, math.nan, math.inf, -math.inf, 100001, -100001):
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    self.accept(dict(self.command, **{field: bad}))
                self.assertIs(self.session.graphics, previous)
            command = dict(self.command)
            del command[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                self.accept(command)
            self.assertIs(self.session.graphics, previous)

    def test_invalid_styles_and_op_types_reject_atomically(self):
        self.accept(self.command)
        previous = self.session.graphics
        patches = [{'fill': x} for x in (None, True, 0, [], {}, '#000000', '#00000000')]
        patches += [{'stroke': x} for x in (None, True, 0, [], {}, 'red', '#fff', '#123456\n')]
        patches += [{'stroke_width': x} for x in (None, True, False, '1', [], {}, math.nan, math.inf, 0, .5, 257)]
        patches += [{'op': x} for x in (['bezier'], {}, None, True, 1, 'constructor', 'path')]
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
            self.assertIs(self.session.graphics, previous)

    def test_geometry_state_caps_and_bad_later_command_preserve_live_state(self):
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
                         [dict(self.command, **dict.fromkeys(FIELDS, -99999.12345678))] * 1500,
                         [self.command, dict(self.command, cy2=True)]):
            with self.assertRaises(ValueError):
                self.session._accept_graphics(dict(self.scene, commands=commands))
            self.assertIs(self.session.graphics, previous)


class SpawnedGraphicsBezierTests(unittest.TestCase):
    wait_ready = bridge.SpawnedGraphicsBridgeTests.wait_ready

    def test_real_spawn_snapshots_callbacks_degenerate_scene_and_recovery(self):
        session = Session()
        self.addCleanup(session.close)
        session.execute(SOURCE, 'bezier')
        result = self.wait_ready(session)
        canvas_id = result['graphics']['canvas_id']

        def commands(result):
            self.assertFalse([e for e in result['events'] if e['type'] == 'error'], result)
            return next(e for e in reversed(result['events']) if e['type'] == 'graphics')['commands']

        initial = commands(result)[0]
        self.assertEqual([initial[key] for key in FIELDS], list(range(1, 9)))
        self.assertEqual((initial['fill'], initial['stroke'], initial['stroke_width']), ('', '#abcdef80', 4))
        self.assertEqual(initial['transform'], [1, 0, 0, 1, 10, 20])
        self.assertEqual(len(initial['clips']), 1)
        for frame in (1, 2):
            time.sleep(.05)
            session.dispatch_graphics(canvas_id, 'bezier', 1, 1, {'type': 'frame'})
            current = commands(self.wait_ready(session))
            self.assertEqual(len(current), 1)
            self.assertEqual(current[0]['cx1'], frame)
            self.assertNotIn('transform', current[0])
            self.assertNotIn('clips', current[0])
        time.sleep(.05)
        session.dispatch_graphics(canvas_id, 'bezier', 1, 1, {'type': 'key_down', 'key': 'x'})
        current = commands(self.wait_ready(session))
        self.assertEqual(len(current), 1)
        self.assertEqual((current[0]['op'], current[0]['stroke']), ('bezier', ''))
        session.execute('显 42.', 'after-bezier')
        result = self.wait_ready(session)
        self.assertIsNone(result['graphics'])
        self.assertTrue(any(e.get('text') == '42\n' for e in result['events']))


class GraphicsBezierHTTPTests(unittest.TestCase):
    setUp = bridge.GraphicsHTTPTests.setUp
    tearDown = bridge.GraphicsHTTPTests.tearDown
    request = bridge.GraphicsHTTPTests.request
    wait_ready = bridge.GraphicsHTTPTests.wait_ready

    def test_http_native_cubic_and_stale_identity_guards(self):
        status, created = self.request('/api/sessions', {})
        self.assertEqual(status, 201)
        sid = created['id']
        self.assertEqual(self.request(f'/api/sessions/{sid}/execute', {'code': SOURCE, 'cell_id': 'bezier'})[0], 202)
        ready = self.wait_ready(sid)
        scene = next(e for e in reversed(ready['events']) if e['type'] == 'graphics')
        self.assertEqual([scene['commands'][0][key] for key in FIELDS], list(range(1, 9)))
        args = {'canvas_id': ready['graphics']['canvas_id'], 'cell_id': 'bezier', 'execution_count': 1, 'expected_generation': 1}
        path = f'/api/sessions/{sid}/graphics'
        for field, value in [('canvas_id', 'old'), ('cell_id', 'old'), ('execution_count', 0), ('expected_generation', 0)]:
            self.assertEqual(self.request(path, dict(args, **{field: value}, event={'type': 'frame'}))[0], 409)
        self.assertEqual(self.request(path, dict(args, event={'type': 'key_down', 'key': 'x'}))[0], 202)
        ready = self.wait_ready(sid)
        commands = next(e for e in reversed(ready['events']) if e['type'] == 'graphics')['commands']
        self.assertEqual(len(commands), 1)
        self.assertEqual((commands[0]['op'], commands[0]['stroke']), ('bezier', ''))
