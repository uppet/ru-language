"""Single native cubic commands in the Python graphics runtime."""
import copy
import io
import unittest
from unittest.mock import patch

from rulang.frontend import RuError, parse
from rulang.graphics_runtime import GraphicsHost
from rulang.interpreter import Interpreter

PREFIX = "观 取 外言 '如:观'. 图 取 观 其 画布 180 120. "
FIELDS = ('x1', 'y1', 'cx1', 'cy1', 'cx2', 'cy2', 'x2', 'y2')


class GraphicsBezierTests(unittest.TestCase):
    def setUp(self):
        self.events, self.output = [], io.StringIO()
        self.interpreter = Interpreter(stdout=self.output)
        self.host = GraphicsHost(self.interpreter, self.events.append)
        self.addCleanup(self.host.close)
        self.run_ru(PREFIX)

    def run_ru(self, source):
        self.interpreter.execute(parse(source))
        self.host.flush()

    def test_exact_signature_named_order_return_and_fill_unchanged(self):
        self.run_ru("图 其 填色 '#FF000080'. 图 其 描边 '#ABCDEF80'. 图 其 线宽 3. "
                    "显 (图 其 贝塞尔 1 2 3 4 5 6 7 8). "
                    "显 (图 其 贝塞尔 终纵:8 控二横:5 起横:1 控一纵:4 终横:7 起纵:2 控二纵:6 控一横:3).")
        self.assertEqual(self.output.getvalue(), '空\n空\n')
        expected = dict(zip(FIELDS, range(1, 9)), op='bezier', fill='', stroke='#abcdef80', stroke_width=3)
        self.assertEqual(self.host.canvas.commands, [expected, expected])
        self.assertEqual(self.host.canvas.fill, '#ff000080')

    def test_extreme_fractional_coincident_and_empty_strokes_retained(self):
        for values in ((-100000., 100000.) * 4, (0.,) * 8, (1., 2.) * 4,
                       (1e-12, -1e-12, .25, -.25, .5, -.5, 0., -0.)):
            for key, value in zip(FIELDS, values):
                self.interpreter.global_scope.values[key] = value
            self.run_ru('图 其 贝塞尔 ' + ' '.join(FIELDS) + '.')
            self.assertEqual([self.host.canvas.commands[-1][key] for key in FIELDS], list(values))
        self.run_ru('图 其 描边 空. 图 其 贝塞尔 0 0 0 0 0 0 0 0.')
        self.assertEqual(self.host.canvas.commands[-1]['stroke'], '')
        self.assertEqual(len(self.host.canvas.commands), 5)

    def test_every_invalid_coordinate_is_atomic(self):
        self.run_ru('图 其 平移 4 5. 图 其 裁剪 0 0 10 20. 图 其 贝塞尔 1 2 3 4 5 6 7 8.')
        canvas = self.host.canvas
        before = copy.deepcopy((canvas.commands, canvas.command_bytes, canvas.transform, canvas.clips,
                                canvas.fill, canvas.stroke, canvas.line_width, canvas.dirty))
        for value in (None, True, False, '1', [], {}, float('nan'), float('inf'), float('-inf'), 100001., -100001.):
            self.interpreter.global_scope.values['坏'] = value
            for index in range(8):
                arguments = ['1'] * 8
                arguments[index] = '坏'
                with self.subTest(value=value, index=index), self.assertRaises(RuError):
                    self.run_ru('图 其 贝塞尔 ' + ' '.join(arguments) + '.')
                self.assertEqual((canvas.commands, canvas.command_bytes, canvas.transform, canvas.clips,
                                  canvas.fill, canvas.stroke, canvas.line_width, canvas.dirty), before)

    def test_exact_arity_names_and_ordinary_identifiers(self):
        cases = ['', '0 0 1 1 2 2 3', '0 0 1 1 2 2 3 3 4',
                 '起横:0 起纵:0 控一横:1 控一纵:1 控二横:2 控二纵:2 终横:3',
                 '起横:0 起纵:0 控一横:1 控一纵:1 控二横:2 控二纵:2 终横:3 终纵:3 起横:4',
                 '起横:0 起纵:0 控一横:1 控一纵:1 控二横:2 控二纵:2 终横:3 半径:3',
                 '0 起纵:0 控一横:1 控一纵:1 控二横:2 控二纵:2 终横:3 终纵:3']
        for args in cases:
            with self.subTest(args=args), self.assertRaises(RuError):
                self.run_ru('图 其 贝塞尔 ' + args + '.')
        with self.assertRaises(RuError):
            self.run_ru('观 其 贝塞尔 0 0 1 1 2 2 3 3.')
        self.assertEqual(self.host.canvas.commands, [])
        self.run_ru('贝塞尔 取 3. 起横 取 4. 控一横 取 5. 控二纵 取 6. 终纵 取 7. 显 贝塞尔 + 起横 + 控一横 + 控二纵 + 终纵.')
        self.assertEqual(self.output.getvalue(), '25\n')

    def test_style_geometry_and_coordinate_snapshots_reset_between_callbacks(self):
        self.run_ru("图 其 描边 '#FF000080'. 图 其 线宽 4. 图 其 保存. 图 其 平移 10 20. "
                    "图 其 裁剪 0 0 40 50. 图 其 缩放 (-2) 0. 控 取 30. "
                    "图 其 贝塞尔 0 0 控 20 40 20 50 0. 控 取 99. "
                    "图 其 恢复. 图 其 贝塞尔 0 0 控 20 40 20 50 0. 图 其 描边 '#FFFFFF'. "
                    "图 其 每帧 (作 帧: 图 其 贝塞尔 0 0 帧 1 10 1 20 0. 图 其 平移 1 2. 为).")
        first, restored = self.host.canvas.commands
        self.assertEqual(first['cx1'], 30)
        self.assertEqual(first['transform'], [-2, 0, 0, 0, 10, 20])
        self.assertEqual(first['clips'][0]['transform'], [1, 0, 0, 1, 10, 20])
        self.assertEqual(first['stroke'], '#ff000080')
        self.assertEqual(restored['cx1'], 99)
        self.assertNotIn('transform', restored)
        self.assertNotIn('clips', restored)
        for frame in (1, 2):
            self.host.handle({'type': 'frame'})
            command = self.host.canvas.commands[0]
            self.assertEqual(command['cx1'], frame)
            self.assertEqual(command['stroke'], '#ffffff')
            self.assertNotIn('transform', command)
            self.assertNotIn('clips', command)

    def test_invisible_degenerate_input_replaces_old_scene(self):
        self.run_ru('图 其 矩形 0 0 100 100. 图 其 描边 空. '
                    '图 其 按键 (作 键: 图 其 贝塞尔 0 0 0 0 0 0 0 0. 为).')
        self.host.handle({'type': 'key_down', 'key': 'x'})
        self.assertEqual(len(self.host.canvas.commands), 1)
        self.assertEqual(self.host.canvas.commands[0]['op'], 'bezier')
        self.assertEqual(self.host.canvas.commands[0]['stroke'], '')

    def test_degenerate_commands_spend_command_and_exact_byte_budget(self):
        self.run_ru('图 其 描边 空.')
        with patch('rulang.graphics_runtime.MAX_FRAME_BYTES', 1000000):
            self.run_ru('循 2048 次 图 其 贝塞尔 0 0 0 0 0 0 0 0. 环')
            size = self.host.canvas.command_bytes
            with self.assertRaisesRegex(RuError, '2048'):
                self.run_ru('图 其 贝塞尔 0 0 0 0 0 0 0 0.')
            self.assertEqual(len(self.host.canvas.commands), 2048)
            self.assertEqual(self.host.canvas.command_bytes, size)
        self.run_ru('图 取 观 其 画布 180 120. 图 其 平移 1 2. 图 其 裁剪 0 0 2 3. 图 其 贝塞尔 0 0 0 0 0 0 0 0.')
        canvas = self.host.canvas
        size = canvas.command_bytes - 2
        canvas.commands, canvas.command_bytes = [], 2
        with patch('rulang.graphics_runtime.MAX_FRAME_BYTES', 1024 + 2 + size):
            self.run_ru('图 其 贝塞尔 0 0 0 0 0 0 0 0.')
            self.assertEqual(canvas.command_bytes, 2 + size)
        canvas.commands, canvas.command_bytes = [], 2
        with patch('rulang.graphics_runtime.MAX_FRAME_BYTES', 1024 + 1 + size):
            with self.assertRaisesRegex(RuError, '256 KiB'):
                self.run_ru('图 其 贝塞尔 0 0 0 0 0 0 0 0.')
        self.assertEqual((canvas.commands, canvas.command_bytes), ([], 2))


if __name__ == '__main__':
    unittest.main()
