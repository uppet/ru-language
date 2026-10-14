"""Bounded, open, stroke-only point arrays in the Python graphics runtime."""
import copy
import io
import unittest
from unittest.mock import patch

from rulang.frontend import RuError, parse
from rulang.graphics_runtime import GraphicsHost
from rulang.interpreter import Interpreter

PREFIX = "观 取 外言 '如:观'. 图 取 观 其 画布 180 120. "


class GraphicsPolylineTests(unittest.TestCase):
    def setUp(self):
        self.events, self.output = [], io.StringIO()
        self.interpreter = Interpreter(stdout=self.output)
        self.host = GraphicsHost(self.interpreter, self.events.append)
        self.addCleanup(self.host.close)
        self.run_ru(PREFIX)

    def run_ru(self, source):
        self.interpreter.execute(parse(source))
        self.host.flush()

    def test_exact_signature_return_empty_and_deep_copy(self):
        self.run_ru("图 其 填色 '#FF000080'. 图 其 描边 '#ABCDEF80'. 图 其 线宽 3. "
                    "点 取 [[1,2],[3,4],[5,6]]. 显 (图 其 折线 点阵:点). "
                    "点[0][0] 取 99. 点[1] 取 [7,8]. 点 其 增 [9,10]. 图 其 折线 [[0,0],[0,0]].")
        self.assertEqual(self.output.getvalue(), '空\n')
        self.assertEqual(self.host.canvas.commands[0], {'op': 'polyline', 'points': [[1, 2], [3, 4], [5, 6]],
                         'fill': '', 'stroke': '#abcdef80', 'stroke_width': 3})
        self.assertEqual(self.host.canvas.commands[1]['points'], [[0, 0], [0, 0]])
        self.assertEqual(self.host.canvas.fill, '#ff000080')

    def test_minimum_maximum_extremes_and_repeated_points(self):
        for count in (2, 3, 256):
            points = [[-100000., 100000.]] * count
            self.interpreter.global_scope.values['点'] = points
            self.run_ru('图 其 折线 点.')
            command = self.host.canvas.commands[-1]
            self.assertEqual(command['points'], points)
            self.assertIsNot(command['points'], points)
            self.assertIsNot(command['points'][0], points[0])
            self.assertIsNot(command['points'][0], command['points'][1])
        self.run_ru('图 其 描边 空. 图 其 折线 [[0,0],[0,0]].')
        self.assertEqual(self.host.canvas.commands[-1]['stroke'], '')
        self.assertEqual(len(self.host.canvas.commands), 4)

    def test_invalid_points_are_atomic(self):
        self.run_ru('图 其 平移 4 5. 图 其 裁剪 0 0 10 20. 图 其 折线 [[0,0],[1,1]].')
        canvas = self.host.canvas
        before = (copy.deepcopy(canvas.commands), canvas.command_bytes, canvas.transform, canvas.clips, canvas.fill, canvas.stroke, canvas.dirty)
        invalid = [None, True, 'points', {}, (), [], [[0., 0.]], [[0., 0.]] * 257,
                   [None, [1., 1.]], [[0.], [1., 1.]], [[0., 0., 0.], [1., 1.]],
                   [(0., 0.), [1., 1.]], [0., 1.]]
        for value in (None, True, False, '1', [], {}, float('nan'), float('inf'), float('-inf'), 100001., -100001.):
            invalid.extend([[[value, 0.], [1., 1.]], [[0., 0.], [1., value]]])
        for points in invalid:
            self.interpreter.global_scope.values['坏'] = points
            with self.subTest(points=points), self.assertRaises(RuError):
                self.run_ru('图 其 折线 坏.')
            self.assertEqual((canvas.commands, canvas.command_bytes, canvas.transform, canvas.clips,
                              canvas.fill, canvas.stroke, canvas.dirty), before)

    def test_exact_arity_names_and_ordinary_identifiers(self):
        for call in ('图 其 折线.', '点 取 [[0,0],[1,1]]. 图 其 折线 点 点.',
                     '图 其 折线 点:[[0,0],[1,1]].', '图 其 折线 点阵:[[0,0],[1,1]] 点阵:[[0,0],[1,1]].',
                     '图 其 折线 [[0,0],[1,1]] 点阵:[[0,0],[1,1]].', '观 其 折线 [[0,0],[1,1]].'):
            with self.subTest(call=call), self.assertRaises(RuError):
                self.run_ru(call)
        self.assertEqual(self.host.canvas.commands, [])
        self.run_ru('折线 取 3. 点阵 取 4. 显 折线 + 点阵.')
        self.assertEqual(self.output.getvalue(), '7\n')

    def test_geometry_and_style_snapshots_reset_between_callbacks(self):
        self.run_ru("图 其 描边 '#FF000080'. 图 其 线宽 4. 图 其 保存. 图 其 平移 10 20. "
                    "图 其 裁剪 0 0 40 50. 图 其 缩放 (-2) 0. 图 其 折线 [[0,0],[10,20],[20,0]]. "
                    "图 其 恢复. 图 其 折线 [[0,0],[1,1]]. 图 其 描边 '#FFFFFF'. "
                    "图 其 每帧 (作 帧: 图 其 折线 [[0,0],[帧,1]]. 图 其 平移 1 2. 为).")
        first, restored = self.host.canvas.commands
        self.assertEqual(first['transform'], [-2, 0, 0, 0, 10, 20])
        self.assertEqual(first['clips'][0]['transform'], [1, 0, 0, 1, 10, 20])
        self.assertEqual(first['stroke'], '#ff000080')
        self.assertNotIn('transform', restored)
        self.assertNotIn('clips', restored)
        for frame in (1, 2):
            self.host.handle({'type': 'frame'})
            command = self.host.canvas.commands[0]
            self.assertEqual(command['points'], [[0, 0], [frame, 1]])
            self.assertEqual(command['stroke'], '#ffffff')
            self.assertNotIn('transform', command)
            self.assertNotIn('clips', command)

    def test_invisible_degenerate_input_replaces_old_scene(self):
        self.run_ru('图 其 矩形 0 0 100 100. 图 其 描边 空. '
                    '图 其 按键 (作 键: 图 其 折线 [[0,0],[0,0]]. 为).')
        self.host.handle({'type': 'key_down', 'key': 'x'})
        self.assertEqual(len(self.host.canvas.commands), 1)
        self.assertEqual(self.host.canvas.commands[0]['op'], 'polyline')
        self.assertEqual(self.host.canvas.commands[0]['stroke'], '')

    def test_point_data_snapshots_and_invisible_commands_spend_budget(self):
        self.run_ru('图 其 描边 空.')
        with patch('rulang.graphics_runtime.MAX_FRAME_BYTES', 1000000):
            self.run_ru('循 2048 次 图 其 折线 [[0,0],[0,0]]. 环')
            size = self.host.canvas.command_bytes
            with self.assertRaisesRegex(RuError, '2048'):
                self.run_ru('图 其 折线 [[0,0],[0,0]].')
            self.assertEqual(len(self.host.canvas.commands), 2048)
            self.assertEqual(self.host.canvas.command_bytes, size)
        self.run_ru('图 取 观 其 画布 180 120. 图 其 平移 1 2. 图 其 裁剪 0 0 2 3.')
        with patch('rulang.graphics_runtime.MAX_FRAME_BYTES', 1200):
            with self.assertRaisesRegex(RuError, '256 KiB'):
                self.run_ru('图 其 折线 [[0,0],[0,0]].')
        self.assertEqual(self.host.canvas.commands, [])
        self.assertEqual(self.host.canvas.command_bytes, 2)


if __name__ == '__main__':
    unittest.main()
