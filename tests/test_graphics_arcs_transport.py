"""Arc/sector payload guards and real spawned graphics transport."""
import copy
import math
import time
import unittest
from unittest.mock import patch

from rushu.kernel import Session
import test_rushu_graphics_bridge as bridge

SOURCE = """观 取 外言 '如:观'. 图 取 观 其 画布 160 120.
图 其 填色 '#FF000080'. 图 其 描边 '#0000FFFF'.
图 其 平移 10 20. 图 其 裁剪 0 0 50 60.
图 其 弧 0 0 20 30 5.8 1. 图 其 扇形 0 0 20 30 0 (-6.283185307179586).
图 其 每帧 (作 帧: 图 其 扇形 0 0 20 30 0 帧. 为).
图 其 按键 (作 键: 图 其 弧 0 0 20 30 0 0. 为).
"""


class GraphicsArcIPCTests(unittest.TestCase):
    def setUp(self):
        with patch.object(Session, '_start'):
            self.session = Session()
        self.scene = {'type': 'graphics', 'canvas_id': 'arcs', 'width': 20, 'height': 20,
                      'fps': 30, 'running': False, 'handlers': [], 'commands': []}
        self.arc = {'op': 'arc', 'x': 0, 'y': 0, 'width': 20, 'height': 20,
                    'start': 0, 'sweep': 1, 'fill': '', 'stroke': '#ABCDEF80', 'stroke_width': 1}

    def accept(self, command):
        self.session._accept_graphics(dict(self.scene, commands=[command]))

    def test_valid_raw_geometry_and_styles(self):
        for op in ('arc', 'sector'):
            for sweep in (0, -0., math.tau, -math.tau, -100000, 100000):
                self.accept(dict(self.arc, op=op, width=0, start=-100000, sweep=sweep))
            for color in ('', '#ABCDEF', '#12345600', '#AABBCC80'):
                self.accept(dict(self.arc, op=op, stroke=color, fill=color if op == 'sector' else ''))
        self.accept(dict(self.arc, transform=[-1, 0, 0, 0, 20, 30],
                         clips=[{'x': 0, 'y': 0, 'width': 0, 'height': 30, 'transform': [1, 0, 0, 1, 0, 0]}]))

    def test_invalid_geometry_styles_and_missing_fields_reject_atomically(self):
        self.accept(self.arc)
        previous = self.session.graphics
        geometry_fields = ('x', 'y', 'width', 'height', 'start', 'sweep', 'stroke_width')
        for op in ('arc', 'sector'):
            for field in geometry_fields:
                for bad in (None, True, False, '1', [], {}, math.inf, -math.inf, math.nan, 100001, -100001):
                    with self.subTest(op=op, field=field, bad=bad), self.assertRaises(ValueError):
                        self.accept(dict(self.arc, op=op, **{field: bad}))
                    self.assertIs(self.session.graphics, previous)
                missing = dict(self.arc, op=op)
                del missing[field]
                with self.assertRaises(ValueError):
                    self.accept(missing)
            for fields in ({'width': -1}, {'height': -1}, {'stroke_width': 0}, {'stroke_width': 257},
                           {'stroke': None}, {'stroke': 'red'}, {'fill': None}, {'fill': '#fff'},
                           {'align': 'left'}, {'baseline': 'top'}):
                with self.subTest(op=op, fields=fields), self.assertRaises(ValueError):
                    self.accept(dict(self.arc, op=op, **fields))
                self.assertIs(self.session.graphics, previous)
        with self.assertRaises(ValueError):
            self.accept(dict(self.arc, fill='#123456'))
        with self.assertRaises(ValueError):
            self.accept(dict(self.arc, op='chord'))
        for malformed_op in (['arc'], ['sector'], ['ellipse'], ['text'], {}, None, True, 1):
            with self.subTest(op=malformed_op), self.assertRaises(ValueError):
                self.accept(dict(self.arc, op=malformed_op))
        for field in ('fill', 'stroke'):
            command = dict(self.arc)
            del command[field]
            with self.assertRaises(ValueError):
                self.accept(command)
        self.assertIs(self.session.graphics, previous)

    def test_transform_and_clip_guards_reject_atomically(self):
        self.accept(self.arc)
        previous = self.session.graphics
        clip = {'x': 0, 'y': 0, 'width': 2, 'height': 3, 'transform': [1, 0, 0, 1, 0, 0]}
        invalid_matrices = (None, [], [1] * 5, [1] * 7, [True, 0, 0, 1, 0, 0], [1, 0, 0, 1, math.nan, 0], [1, 0, 0, 1, 100001, 0])
        for matrix in invalid_matrices:
            for fields in ({'transform': matrix}, {'clips': [dict(clip, transform=matrix)]}):
                with self.subTest(fields=fields), self.assertRaises(ValueError):
                    self.accept(dict(self.arc, **fields))
                self.assertIs(self.session.graphics, previous)
        for clips in (None, {}, [None], [clip] * 33, [dict(clip, width=-1)], [dict(clip, x=True)],
                      [dict(clip, height=math.inf)], [{key: value for key, value in clip.items() if key != 'transform'}]):
            with self.subTest(clips=clips), self.assertRaises(ValueError):
                self.accept(dict(self.arc, clips=clips))
            self.assertIs(self.session.graphics, previous)

    def test_frames_retain_count_and_byte_caps(self):
        self.accept(self.arc)
        previous = self.session.graphics
        with self.assertRaises(ValueError):
            self.session._accept_graphics(dict(self.scene, commands=[self.arc] * 2049))
        large = copy.deepcopy(self.arc)
        large['clips'] = [{'x': 0, 'y': 0, 'width': 2, 'height': 3, 'transform': [1, 0, 0, 1, 0, 0]}] * 32
        with self.assertRaises(ValueError):
            self.session._accept_graphics(dict(self.scene, commands=[large] * 160))
        self.assertIs(self.session.graphics, previous)


class SpawnedGraphicsArcTests(unittest.TestCase):
    wait_ready = bridge.SpawnedGraphicsBridgeTests.wait_ready

    def test_arc_sector_transport_callbacks_and_zero_scene_replacement(self):
        session = Session()
        self.addCleanup(session.close)
        session.execute(SOURCE, 'arcs')
        result = self.wait_ready(session)
        canvas_id = result['graphics']['canvas_id']

        def commands(result):
            self.assertFalse([e for e in result['events'] if e['type'] == 'error'], result)
            return next(e for e in reversed(result['events']) if e['type'] == 'graphics')['commands']

        initial = commands(result)
        self.assertEqual([c['op'] for c in initial], ['arc', 'sector'])
        self.assertEqual(initial[0]['fill'], '')
        self.assertEqual(initial[1]['fill'], '#ff000080')
        self.assertEqual(initial[1]['sweep'], -math.tau)
        self.assertEqual(initial[0]['transform'], [1, 0, 0, 1, 10, 20])
        self.assertEqual(len(initial[0]['clips']), 1)
        for frame in (1, 2):
            time.sleep(.05)
            session.dispatch_graphics(canvas_id, 'arcs', 1, 1, {'type': 'frame'})
            current = commands(self.wait_ready(session))
            self.assertEqual(len(current), 1)
            self.assertEqual((current[0]['op'], current[0]['sweep']), ('sector', frame))
            self.assertNotIn('transform', current[0])
            self.assertNotIn('clips', current[0])
        time.sleep(.05)
        session.dispatch_graphics(canvas_id, 'arcs', 1, 1, {'type': 'key_down', 'key': 'x'})
        current = commands(self.wait_ready(session))
        self.assertEqual(len(current), 1)
        self.assertEqual((current[0]['op'], current[0]['sweep']), ('arc', 0))
        session.execute('显 42.', 'after-arcs')
        result = self.wait_ready(session)
        self.assertIsNone(result['graphics'])
        self.assertTrue(any(e.get('text') == '42\n' for e in result['events']))


class GraphicsArcHTTPTests(unittest.TestCase):
    setUp = bridge.GraphicsHTTPTests.setUp
    tearDown = bridge.GraphicsHTTPTests.tearDown
    request = bridge.GraphicsHTTPTests.request
    wait_ready = bridge.GraphicsHTTPTests.wait_ready

    def test_real_http_delivers_signed_commands_and_rejects_stale_identity(self):
        status, created = self.request('/api/sessions', {})
        self.assertEqual(status, 201)
        sid = created['id']
        self.assertEqual(self.request(f'/api/sessions/{sid}/execute', {'code': SOURCE, 'cell_id': 'arcs'})[0], 202)
        ready = self.wait_ready(sid)
        scene = next(e for e in reversed(ready['events']) if e['type'] == 'graphics')
        self.assertEqual(scene['commands'][1]['sweep'], -math.tau)
        args = {'canvas_id': ready['graphics']['canvas_id'], 'cell_id': 'arcs', 'execution_count': 1, 'expected_generation': 1}
        path = f'/api/sessions/{sid}/graphics'
        for field, value in [('canvas_id', 'old'), ('cell_id', 'old'), ('execution_count', 0), ('expected_generation', 0)]:
            self.assertEqual(self.request(path, dict(args, **{field: value}, event={'type': 'frame'}))[0], 409)
        self.assertEqual(self.request(path, dict(args, event={'type': 'key_down', 'key': 'x'}))[0], 202)
        ready = self.wait_ready(sid)
        commands = next(e for e in reversed(ready['events']) if e['type'] == 'graphics')['commands']
        self.assertEqual(len(commands), 1)
        self.assertEqual((commands[0]['op'], commands[0]['sweep']), ('arc', 0))
