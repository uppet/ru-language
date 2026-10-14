"""Signed, bounded arc/sector commands in the Python graphics runtime."""
import io
import math
import unittest
from unittest.mock import patch

from rulang.frontend import RuError, parse
from rulang.graphics_runtime import GraphicsHost
from rulang.interpreter import Interpreter

PREFIX = "观 取 外言 '如:观'. 图 取 观 其 画布 160 120. "


class GraphicsArcTests(unittest.TestCase):
    def setUp(self):
        self.events, self.output = [], io.StringIO()
        self.interpreter = Interpreter(stdout=self.output)
        self.host = GraphicsHost(self.interpreter, self.events.append)
        self.addCleanup(self.host.close)
        self.run_ru(PREFIX)

    def run_ru(self, source):
        self.interpreter.execute(parse(source))
        self.host.flush()

    def test_signatures_return_empty_and_open_arcs_ignore_fill(self):
        self.run_ru("图 其 填色 '#ABCDEF80'. 图 其 描边 '#12345678'. 图 其 线宽 3. "
                    "显 (图 其 弧 1 2 30 40 5.8 1). "
                    "显 (图 其 扇形 转角: (-2) 高: 40 始角: (-1) 宽: 30 纵: 2 横: 1).")
        self.assertEqual(self.output.getvalue(), '空\n空\n')
        arc, sector = self.host.canvas.commands
        self.assertEqual(arc, {'op': 'arc', 'x': 1, 'y': 2, 'width': 30, 'height': 40,
                              'start': 5.8, 'sweep': 1, 'fill': '', 'stroke': '#12345678', 'stroke_width': 3})
        self.assertEqual((sector['op'], sector['start'], sector['sweep'], sector['fill']),
                         ('sector', -1, -2, '#abcdef80'))
        self.assertEqual(self.host.canvas.fill, '#abcdef80')

    def test_raw_angles_zero_dimensions_and_empty_styles_are_retained(self):
        self.run_ru('图 其 填色 空. 图 其 描边 空.')
        for name in ('弧', '扇形'):
            for sweep in (0., -0., 1e-12, -1e-12, math.tau, -math.tau, 100000., -100000.):
                self.interpreter.global_scope.values['角'] = sweep
                self.run_ru(f'图 其 {name} (-100000) 100000 0 0 100000 角.')
                command = self.host.canvas.commands[-1]
                self.assertEqual(command['start'], 100000)
                self.assertEqual(command['sweep'], sweep)
                self.assertEqual((command['width'], command['height'], command['fill'], command['stroke']), (0, 0, '', ''))
        self.assertEqual(len(self.host.canvas.commands), 16)

    def test_invalid_arguments_preserve_commands_bytes_and_state(self):
        self.run_ru("图 其 平移 7 9. 图 其 裁剪 0 0 20 30. 图 其 填色 '#11223380'. 图 其 弧 1 2 30 40 0 1.")
        canvas = self.host.canvas
        before = (list(canvas.commands), canvas.command_bytes, canvas.transform, canvas.clips, canvas.fill, canvas.stroke, canvas.dirty)
        for name in ('弧', '扇形'):
            for bad in (True, False, None, '1', [], {}, float('nan'), float('inf'), float('-inf'), 100001., -100001.):
                self.interpreter.global_scope.values['坏'] = bad
                for index in range(6):
                    args = ['1'] * 6
                    args[index] = '坏'
                    with self.subTest(name=name, bad=bad, index=index), self.assertRaises(RuError):
                        self.run_ru(f'图 其 {name} ' + ' '.join(args) + '.')
                    self.assertEqual((canvas.commands, canvas.command_bytes, canvas.transform, canvas.clips,
                                      canvas.fill, canvas.stroke, canvas.dirty), before)
            for args in ('', '0 0 1 1 0', '0 0 1 1 0 1 2', '0 0 (-1) 1 0 1', '0 0 1 (-1) 0 1',
                         '横:0 纵:0 宽:1 高:1 始角:0 终角:1', '横:0 纵:0 宽:1 高:1 始角:0',
                         '横:0 纵:0 宽:1 高:1 始角:0 转角:1 横:0', '0 纵:0 宽:1 高:1 始角:0 转角:1'):
                with self.subTest(name=name, args=args), self.assertRaises(RuError):
                    self.run_ru(f'图 其 {name} ' + args + '.')
                self.assertEqual(canvas.commands, before[0])

    def test_matrix_clip_style_snapshots_and_callback_reset(self):
        self.run_ru("图 其 填色 '#FF000080'. 图 其 描边 '#0000FFFF'. 图 其 保存. "
                    "图 其 平移 10 20. 图 其 裁剪 0 0 60 70. 图 其 缩放 (-2) 0. "
                    "图 其 扇形 0 0 20 30 0 1. 图 其 弧 0 0 20 30 0 (-1). 图 其 恢复. "
                    "图 其 扇形 0 0 20 30 0 1. 图 其 填色 '#FFFFFF'. "
                    "图 其 每帧 (作 帧: 图 其 扇形 0 0 20 30 0 1. 图 其 平移 1 2. 为).")
        first, arc, restored = self.host.canvas.commands
        self.assertEqual(first['transform'], [-2, 0, 0, 0, 10, 20])
        self.assertEqual(first['clips'][0]['transform'], [1, 0, 0, 1, 10, 20])
        self.assertEqual(arc['fill'], '')
        self.assertEqual(first['fill'], '#ff000080')
        self.assertNotIn('transform', restored)
        self.assertNotIn('clips', restored)
        for _ in range(2):
            self.host.handle({'type': 'frame'})
            command = self.host.canvas.commands[0]
            self.assertEqual(command['fill'], '#ffffff')
            self.assertNotIn('transform', command)
            self.assertNotIn('clips', command)

    def test_zero_sweep_input_drawing_replaces_scene(self):
        self.run_ru('图 其 矩形 0 0 100 100. 图 其 按键 (作 键: 图 其 弧 0 0 10 10 0 0. 为).')
        self.host.handle({'type': 'key_down', 'key': 'x'})
        self.assertEqual(len(self.host.canvas.commands), 1)
        self.assertEqual(self.host.canvas.commands[0]['op'], 'arc')
        self.assertEqual(self.host.canvas.commands[0]['sweep'], 0)

    def test_invisible_arcs_obey_command_and_byte_limits_atomically(self):
        self.run_ru('图 其 描边 空.')
        # Isolate the 2048-count boundary; production byte limits stay unchanged.
        with patch('rulang.graphics_runtime.MAX_FRAME_BYTES', 1000000):
            self.run_ru('循 2048 次 图 其 弧 0 0 0 0 0 0. 环')
            before = self.host.canvas.command_bytes
            with self.assertRaisesRegex(RuError, '2048'):
                self.run_ru('图 其 扇形 0 0 0 0 0 0.')
            self.assertEqual(len(self.host.canvas.commands), 2048)
            self.assertEqual(self.host.canvas.command_bytes, before)
        self.run_ru('图 取 观 其 画布 160 120. 图 其 平移 1 2. 图 其 裁剪 0 0 2 3.')
        with patch('rulang.graphics_runtime.MAX_FRAME_BYTES', 1200):
            with self.assertRaisesRegex(RuError, '256 KiB'):
                self.run_ru('图 其 弧 0 0 0 0 0 0.')
        self.assertEqual(self.host.canvas.commands, [])
        self.assertEqual(self.host.canvas.command_bytes, 2)

    def test_names_are_ordinary_and_helpers_do_not_expose_drawing(self):
        self.run_ru('弧 取 3. 扇形 取 4. 始角 取 5. 转角 取 6. 显 弧 + 扇形 + 始角 + 转角.')
        self.assertEqual(self.output.getvalue(), '18\n')
        with self.assertRaisesRegex(RuError, '未知成员'):
            self.run_ru('观 其 弧 0 0 1 1 0 1.')


if __name__ == '__main__':
    unittest.main()
