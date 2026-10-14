"""Self-contained immutable drawing resources at the kernel IPC boundary."""
import copy
import math
import unittest
from unittest.mock import Mock, patch

from rushu.kernel import MAX_GRAPHICS_BYTES, Session


class GraphicsCacheTransportTests(unittest.TestCase):
    def setUp(self):
        with patch.object(Session, '_start'):
            self.session = Session()
        self.session.cell_id = '缓存格'
        self.session.connection = Mock()
        self.scene = dict(type='graphics', canvas_id='canvas', width=20, height=20,
                          fps=30, running=False, handlers=[], commands=[])
        self.resource = dict(id='cache-1', kind='drawing', width=20, height=20, commands=[])
        self.image = dict(op='image', resource='cache-1', x=0, y=0)
        self.frame = dict(self.scene, resources=[self.resource], commands=[self.image])
        self.clip = dict(x=0, y=0, width=1, height=1, transform=[1, 0, 0, 1, 0, 0])
        self.primitives = [dict(op='background', color='#00000000'),
            dict(op='line', x1=0, y1=0, x2=1, y2=1, width=1, color='#ABCDEF80'),
            dict(op='text', x=0, y=0, size=12, text='星🌟', color='#ABCDEF', align='center', baseline='middle'),
            *[dict(op=op, x=0, y=0, width=1, height=1, stroke_width=1,
                   fill='', stroke='#12345680', **({'start': 0, 'sweep': -math.pi} if op in ('arc', 'sector') else {}))
              for op in ('rect', 'ellipse', 'arc', 'sector')],
            *[dict(op=op, points=[[0, 0], [1, 1], [2, 2]], fill='', stroke='', stroke_width=1)
              for op in ('polygon', 'polyline')],
            dict(op='bezier', x1=0, y1=0, cx1=1, cy1=1, cx2=2, cy2=2, x2=3, y2=3,
                 fill='', stroke='#000000', stroke_width=1)]

    def accept(self, frame=None):
        self.session._accept_graphics(self.frame if frame is None else frame)

    def reject(self, frame):
        previous = self.session.graphics
        with self.assertRaises((ValueError, TypeError)):
            self.accept(frame)
        self.assertIs(self.session.graphics, previous)

    def recipe(self, commands):
        return dict(self.frame, resources=[dict(self.resource, commands=commands)])

    def test_all_primitives_alpha_text_and_drawing_state(self):
        self.accept(self.recipe(self.primitives))
        for command in self.primitives[1:]:
            self.accept(self.recipe([dict(command, transform=[-1, 0, 0, 1, 0, 0], clips=[self.clip])]))
        self.accept(dict(self.frame, commands=[dict(self.image, clips=[self.clip], transform=[1, 0, 0, 1, 1, 2])]))

    def test_strict_resource_definition_ids_dimensions_and_fields(self):
        self.accept()
        mutations = [dict(self.resource, **{key: value})
            for key, values in {
                'id': ['', '画', 'a' * 129, 'cache/1', None, True],
                'kind': ['url', 'image', None],
                'width': [True, 0, -1, 2049, 1.5, '1'],
                'height': [False, 0, math.nan, math.inf],
                'commands': [None, {}, ''],
                'url': ['https://example.com/a'], 'resources': [[]], 'script': ['x']}.items()
            for value in values]
        for key in self.resource:
            missing = dict(self.resource)
            del missing[key]
            mutations.append(missing)
        for resource in mutations:
            with self.subTest(resource=resource):
                self.reject(dict(self.frame, resources=[resource]))
        for resources in (None, {}, [self.resource, self.resource], [None]):
            self.reject(dict(self.frame, resources=resources))
        for name in ('__proto__', 'constructor', 'a-b_0'):
            self.accept(dict(self.frame, resources=[dict(self.resource, id=name)], commands=[dict(self.image, resource=name)]))

    def test_exact_reference_closure_no_nesting_and_image_whitelist(self):
        self.reject(dict(self.frame, resources=[]))
        self.reject(dict(self.frame, commands=[]))
        self.reject(self.recipe([self.image]))
        for key, value in [('width', 20), ('height', 20), ('color', '#000000'), ('alpha', .5),
                           ('url', 'x'), ('resources', []), ('fill', ''), ('align', 'left'),
                           ('x', True), ('y', math.inf), ('resource', 'missing')]:
            self.reject(dict(self.frame, commands=[dict(self.image, **{key: value})]))
        for key in self.image:
            command = dict(self.image)
            del command[key]
            self.reject(dict(self.frame, commands=[command]))
        self.accept(dict(self.frame, commands=[self.image] * 2048))
        self.reject(dict(self.frame, commands=[self.image] * 2049))

    def test_deep_recipe_field_geometry_color_and_state_validation(self):
        for command in self.primitives:
            for key in command:
                if key in ('align', 'baseline'):
                    continue
                missing = dict(command)
                del missing[key]
                self.reject(self.recipe([missing]))
            for extra in ('url', 'path', 'script', 'resources', 'alpha'):
                self.reject(self.recipe([dict(command, **{extra: 'x'})]))
            for key, value in command.items():
                if isinstance(value, (int, float)):
                    for invalid in (True, None, '0', math.nan, math.inf, -100001, 100001):
                        self.reject(self.recipe([dict(command, **{key: invalid})]))
                if key in ('color', 'fill', 'stroke'):
                    for invalid in (None, [], '#123', '#123456\n', 'red'):
                        self.reject(self.recipe([dict(command, **{key: invalid})]))
            if command['op'] == 'background':
                continue
            for state in ({'transform': [1] * 5}, {'transform': [True, 0, 0, 1, 0, 0]},
                          {'clips': [self.clip] * 33}, {'clips': [dict(self.clip, width=-1)]},
                          {'clips': [dict(self.clip, path='x')]}, {'clips': [dict(self.clip, transform=None)]}):
                self.reject(self.recipe([dict(command, **state)]))
        for command in self.primitives:
            if command['op'] in ('polygon', 'polyline'):
                for points in ([], [[0, 0]] * 257, [[0, True]] * 3, [[0]] * 3):
                    self.reject(self.recipe([dict(command, points=points)]))
            if command['op'] in ('arc', 'polyline', 'bezier'):
                self.reject(self.recipe([dict(command, fill='#000000')]))
        text = self.primitives[2]
        for change in ({'size': 0}, {'size': 257}, {'text': 'x' * 4097}, {'align': 'start'}, {'baseline': None}):
            self.reject(self.recipe([dict(text, **change)]))

    def test_malformed_json_and_style_boundaries(self):
        cyclic = copy.deepcopy(self.frame)
        cyclic['resources'].append(cyclic)
        self.reject(cyclic)
        self.reject(self.recipe([dict(self.primitives[2], text=object())]))
        self.reject(self.recipe([dict(self.primitives[2], text='\ud800')]))
        for command in self.primitives:
            if 'stroke_width' in command:
                for width in (0, .5, 257):
                    self.reject(self.recipe([dict(command, stroke_width=width)]))
            if command['op'] in ('rect', 'ellipse', 'arc', 'sector'):
                self.reject(self.recipe([dict(command, width=-1)]))
            if command['op'] == 'line':
                self.reject(self.recipe([dict(command, width=0)]))
            if command['op'] == 'background':
                self.reject(self.recipe([dict(command, color='')]))
        self.reject(dict(self.frame, commands=[dict(self.image, clips=[dict(self.clip, path='x')])]))

    def test_unique_recipe_command_pixels_and_resource_count_limits(self):
        background = self.primitives[0]
        self.accept(self.recipe([background] * 2047))
        self.reject(self.recipe([background] * 2048))
        self.reject(dict(self.recipe([background] * 2047), commands=[self.image, self.image]))
        for count in (8, 9):
            resources = [dict(self.resource, id=f'r{i}') for i in range(count)]
            frame = dict(self.frame, resources=resources, commands=[dict(self.image, resource=r['id']) for r in resources])
            (self.accept if count == 8 else self.reject)(frame)
        self.accept(dict(self.frame, resources=[dict(self.resource, width=2048, height=2048)]))
        self.reject(dict(self.frame, resources=[dict(self.resource, width=2048, height=2048), dict(self.resource, id='r2', width=1, height=1)],
                         commands=[self.image, dict(self.image, resource='r2')]))

    def test_actual_resource_array_utf8_byte_boundary(self):
        # Valid text chunks, with a UTF-8 multi-byte character in the measured array.
        commands = [dict(self.primitives[2], text='星' * 1000) for _ in range(42)]
        frame = self.recipe(commands)
        remainder = 131072 - self.session._event_size(frame['resources'])
        self.assertGreater(remainder, 0)
        commands[-1]['text'] += 'x' * remainder
        self.assertEqual(self.session._event_size(frame['resources']), 131072)
        self.accept(frame)
        commands[-1]['text'] += 'x'
        self.reject(frame)

    def test_actual_wrapped_frame_boundary_and_atomic_append(self):
        # Legacy root extras remain compatible; no resources field is injected.
        frame = dict(self.scene, padding='星')
        remainder = MAX_GRAPHICS_BYTES - self.session._event_size(self.session._graphics_record(frame))
        frame['padding'] += 'x' * remainder
        self.accept(frame)
        self.session._append(frame)
        old = self.session.events[-1]
        self.assertNotIn('resources', old)
        self.assertEqual(self.session._event_size(old), MAX_GRAPHICS_BYTES)
        bad = dict(frame, padding=frame['padding'] + 'x')
        self.reject(bad)
        cursor, size = self.session.cursor, self.session.event_text
        with self.assertRaises(ValueError):
            self.session._append(bad)
        self.assertEqual((self.session.cursor, self.session.event_text), (cursor, size))
        self.assertIs(self.session.events[-1], old)
        try:
            self.accept(bad)
        except ValueError as error:
            self.session._reject_graphics_frame(bad, error)
        self.assertIsNone(self.session.graphics)
        self.assertEqual(self.session.state, 'idle')
        self.assertIn(old, self.session.events)
        self.session.connection.send.assert_called_once_with({'kind': 'graphics_rejected', 'canvas_id': 'canvas'})

    def test_coalesced_later_frame_is_self_contained_and_legacy_stays_absent(self):
        for x in range(100):
            frame = copy.deepcopy(self.recipe(self.primitives))
            frame['commands'][0]['x'] = x
            self.accept(frame)
            self.session._append(frame)
        events = list(self.session.events)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['commands'][0]['x'], 99)
        with patch.object(Session, '_start'):
            fresh = Session()
        fresh._accept_graphics(events[0])
        self.accept(self.scene)
        self.session._append(self.scene)
        self.assertNotIn('resources', self.session.events[-1])


class SpawnedGraphicsCacheTransportTests(unittest.TestCase):
    def test_real_worker_later_snapshot_is_portable_and_close_is_recoverable(self):
        import time
        from test_rushu_graphics_bridge import SpawnedGraphicsBridgeTests
        session = Session()
        self.addCleanup(session.close)
        session.execute("观 取 外言 '如:观'. 图 取 观 其 画布 20 20. "
                        "图像 取 图 其 缓存 10 10 (作 层: 层 其 背景 '#12345680'. 为). "
                        "图 其 贴图 图像 0 0. 图 其 每帧 (作 帧: 图 其 贴图 图像 帧 0. 为).", 'cache')
        ready = SpawnedGraphicsBridgeTests.wait_ready(self, session)
        self.assertFalse([e for e in ready['events'] if e['type'] == 'error'], ready)
        canvas_id = ready['graphics']['canvas_id']
        for _ in range(3):
            time.sleep(.04)
            session.dispatch_graphics(canvas_id, 'cache', 1, 1, {'type': 'frame'})
            ready = SpawnedGraphicsBridgeTests.wait_ready(self, session)
        frames = [e for e in ready['events'] if e['type'] == 'graphics']
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]['commands'][0]['x'], 3)
        self.assertEqual(frames[0]['resources'][0]['commands'], [{'op': 'background', 'color': '#12345680'}])
        # Exercise the same internal rejection cleanup without a user callback.
        session.connection.send({'kind': 'graphics_rejected', 'canvas_id': canvas_id})
        deadline = time.monotonic() + 5
        while session.snapshot()['graphics'] is not None and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertIsNone(session.snapshot()['graphics'])
        session.execute('显 图像 其 宽.', 'next')
        ready = SpawnedGraphicsBridgeTests.wait_ready(self, session)
        self.assertEqual(ready['state'], 'idle')
        self.assertTrue(any(e.get('text') == '10\n' for e in ready['events']), ready)
