"""Affine graphics state, geometry snapshots and resource-failure semantics."""
import io
import sys
import unittest
from unittest.mock import patch

from rulang.frontend import RuError, parse
from rulang.graphics_runtime import GraphicsHost, IDENTITY
from rulang.interpreter import Interpreter


class GraphicsTransformTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.interpreter = Interpreter(stdout=io.StringIO())
        self.host = GraphicsHost(self.interpreter, self.events.append)
        self.run_ru("观 取 外言 '如:观'. 图 取 观 其 画布 320 200.")

    def tearDown(self):
        self.host.close()

    def run_ru(self, source):
        self.interpreter.execute(parse(source))
        self.host.flush()

    def test_polygons_snapshot_points_and_styles(self):
        self.run_ru("点 取 [[0,1],[2,3],[4,5]]. 图 其 多边形 点. 点[0][0] 取 99. 图 其 填色 空. 图 其 三角形 1 2 3 4 5 6.")
        first, second = self.events[-1]['commands']
        self.assertEqual(first['op'], 'polygon')
        self.assertEqual(first['points'], [[0, 1], [2, 3], [4, 5]])
        self.assertNotIn('transform', first)
        self.assertNotIn('clips', first)
        self.assertEqual(second['points'], [[1, 2], [3, 4], [5, 6]])
        self.assertEqual(second['fill'], '')

    def test_postmultiplication_and_all_drawables(self):
        self.run_ru("图 其 平移 10 20. 图 其 缩放 2 3. 图 其 变换 1 2 3 4 5 6. 图 其 矩形 1 2 3 4. 图 其 椭圆 1 2 3 4. 图 其 线 1 2 3 4. 图 其 文字 '文' 1 2. 图 其 三角形 0 0 1 1 2 2.")
        for command in self.events[-1]['commands']:
            self.assertEqual(command['transform'], [2, 6, 6, 12, 20, 38])
        self.run_ru('图 其 重置变换. 图 其 旋转 1.5707963267948966. 图 其 线 0 0 1 1.')
        matrix = self.events[-1]['commands'][-1]['transform']
        for actual, expected in zip(matrix, [0, 1, -1, 0, 0, 0]):
            self.assertAlmostEqual(actual, expected)

    def test_save_restore_styles_clips_and_matrix(self):
        self.run_ru("图 其 平移 10 20. 图 其 裁剪 0 0 50 60. 图 其 保存. 图 其 填色 空. 图 其 描边 空. 图 其 线宽 4. 图 其 字号 20. 图 其 平移 30 40. 图 其 裁剪 1 2 3 4. 图 其 矩形 1 2 3 4. 图 其 恢复. 图 其 矩形 1 2 3 4. 图 其 文字 '文' 0 0. 图 其 取消裁剪. 图 其 重置变换. 图 其 线 0 0 1 1.")
        first, second, text, line = self.events[-1]['commands']
        self.assertEqual(first['transform'], [1, 0, 0, 1, 40, 60])
        self.assertEqual(len(first['clips']), 2)
        self.assertEqual(first['clips'][0]['transform'], [1, 0, 0, 1, 10, 20])
        self.assertEqual(first['clips'][1]['transform'], [1, 0, 0, 1, 40, 60])
        self.assertEqual(first['fill'], '')
        self.assertEqual(second['fill'], '#4677ff')
        self.assertEqual(second['stroke'], '#202530')
        self.assertEqual(second['stroke_width'], 1)
        self.assertEqual(len(second['clips']), 1)
        self.assertEqual(text['size'], 16)
        self.assertNotIn('transform', line)
        self.assertNotIn('clips', line)

    def test_background_ignores_geometry_without_changing_it(self):
        self.run_ru("图 其 平移 10 20. 图 其 裁剪 0 0 1 2. 图 其 矩形 0 0 1 2. 图 其 背景 '#ffffff'. 图 其 线 0 0 1 1.")
        background, line = self.events[-1]['commands']
        self.assertEqual(background, {'op': 'background', 'color': '#ffffff'})
        self.assertEqual(line['transform'], [1, 0, 0, 1, 10, 20])
        self.assertEqual(len(line['clips']), 1)

    def test_callback_resets_geometry_but_preserves_style(self):
        self.run_ru("图 其 平移 10 20. 图 其 裁剪 0 0 1 1. 图 其 填色 '#112233'. 图 其 每帧 (作 帧: 图 其 矩形 0 0 1 1. 图 其 平移 20 30. 图 其 裁剪 0 0 2 2. 为).")
        for _ in range(2):
            self.host.handle({'type': 'frame'})
            command = self.events[-1]['commands'][0]
            self.assertNotIn('transform', command)
            self.assertNotIn('clips', command)
            self.assertEqual(command['fill'], '#112233')

    def test_unbalanced_initial_and_callback_close_and_recover(self):
        with self.assertRaisesRegex(RuError, '须成对'):
            self.run_ru('图 其 保存.')
        self.assertIsNone(self.host.canvas)
        self.run_ru("图 取 观 其 画布 10 10. 图 其 每帧 (作 帧: 图 其 保存. 为).")
        with self.assertRaisesRegex(RuError, '须成对'):
            self.host.handle({'type': 'frame'})
        self.assertIsNone(self.host.canvas)
        self.run_ru('图 取 观 其 画布 10 10. 图 其 线 0 0 1 1.')
        self.assertEqual(self.events[-1]['commands'][0]['op'], 'line')

    def test_stack_and_clip_limits_restore_underflow(self):
        with self.assertRaisesRegex(RuError, '对应的保存'):
            self.run_ru('图 其 恢复.')
        self.run_ru('循 64 次 图 其 保存. 环 循 64 次 图 其 恢复. 环')
        with self.assertRaisesRegex(RuError, '64'):
            self.run_ru('循 65 次 图 其 保存. 环')
        self.host.canvas.reset_geometry()
        self.run_ru('循 32 次 图 其 裁剪 0 0 1 1. 环')
        with self.assertRaisesRegex(RuError, '32'):
            self.run_ru('图 其 裁剪 0 0 1 1.')

    def test_invalid_polygons_dimensions_and_matrices(self):
        for code in ("图 其 多边形 [].", "图 其 多边形 [1,2,3].", "图 其 多边形 [[0,0],[1,1],[2,2,2]].",
                     "图 其 多边形 [[0,0],[1,1],['2',2]].", "图 其 裁剪 0 0 (-1) 2.",
                     "图 其 平移 100001 0.", "图 其 旋转 '1'.", "图 其 缩放 1 100001.",
                     "图 其 变换 1 0 0 1 0 100001."):
            with self.subTest(code=code), self.assertRaises(RuError):
                self.run_ru(code)
        self.interpreter.global_scope.values['过多'] = [[0., 0.]] * 257
        with self.assertRaisesRegex(RuError, '256'):
            self.run_ru('图 其 多边形 过多.')
        self.interpreter.global_scope.values['非数'] = float('nan')
        with self.assertRaisesRegex(RuError, '有限数'):
            self.run_ru('图 其 平移 非数 0.')
        self.run_ru('图 其 平移 100000 0.')
        before = self.host.canvas.transform
        with self.assertRaisesRegex(RuError, '累积变换'):
            self.run_ru('图 其 平移 1 0.')
        self.assertEqual(self.host.canvas.transform, before)
        self.run_ru('图 其 重置变换. 图 其 缩放 0 (-1). 图 其 矩形 0 0 1 1.')
        self.assertEqual(self.events[-1]['commands'][-1]['transform'], [0, 0, 0, -1, 0, 0])

    def test_explicit_close_and_replacement_discard_unfinished_stack(self):
        self.run_ru('图 其 保存. 图 其 线 0 0 1 1. 图 其 关闭.')
        self.assertIsNone(self.host.canvas)
        self.assertEqual(self.events[-2]['commands'][0]['op'], 'line')
        self.run_ru('图 取 观 其 画布 10 10. 图 其 保存. 图 取 观 其 画布 20 20.')
        self.assertEqual(self.host.canvas.stack, [])
        self.assertEqual(self.host.canvas.width, 20)

    def test_invalid_background_and_clip_preserve_existing_state(self):
        self.run_ru('图 其 裁剪 0 0 1 1. 图 其 线 0 0 1 1.')
        commands = list(self.host.canvas.commands)
        clips = self.host.canvas.clips
        command_bytes = self.host.canvas.command_bytes
        with self.assertRaisesRegex(RuError, '颜色'):
            self.run_ru("图 其 背景 'red'.")
        self.assertEqual(self.host.canvas.commands, commands)
        self.assertEqual(self.host.canvas.command_bytes, command_bytes)
        with self.assertRaisesRegex(RuError, '有限数'):
            self.run_ru('图 其 裁剪 0 0 (-1) 1.')
        self.assertEqual(self.host.canvas.clips, clips)

    def test_maximum_polygon_and_nonfinite_inputs(self):
        self.interpreter.global_scope.values['顶点'] = [[0., 0.]] * 256
        self.run_ru('图 其 多边形 顶点.')
        self.assertEqual(len(self.events[-1]['commands'][0]['points']), 256)
        for value in (float('inf'), float('-inf'), float('nan'), True, None, '1'):
            self.interpreter.global_scope.values['无效'] = value
            self.interpreter.global_scope.values['顶点'] = [[0., 0.], [1., 1.], [value, 2.]]
            for code in ('图 其 多边形 顶点.', '图 其 变换 1 0 0 1 无效 0.', '图 其 旋转 无效.'):
                with self.subTest(value=value, code=code), self.assertRaises(RuError):
                    self.run_ru(code)

    def test_matrix_and_clip_snapshots_count_toward_byte_budget(self):
        self.run_ru('图 其 平移 1 2. 图 其 裁剪 0 0 1 1.')
        with patch('rulang.graphics_runtime.MAX_FRAME_BYTES', 1200):
            with self.assertRaisesRegex(RuError, '256 KiB'):
                self.run_ru('图 其 矩形 0 0 1 1.')
        self.assertEqual(self.host.canvas.commands, [])

    def test_limit_restoration_failure_is_friendly_and_keeps_original_error(self):
        try:
            import resource
        except ImportError:
            self.skipTest('POSIX resource limits unavailable')
        if not hasattr(resource, 'RLIMIT_AS'):
            self.skipTest('RLIMIT_AS unavailable')
        for callback, expected in [('图 其 线 0 0 1 1.', '无法恢复系统内存上限'), ('显 未定义.', '未定义')]:
            self.run_ru('图 取 观 其 画布 10 10. 图 其 每帧 (作 帧: ' + callback + ' 为).')
            old_trace = sys.gettrace()
            with patch.object(resource, 'getrlimit', return_value=(-1, -1)), \
                 patch.object(resource, 'setrlimit', side_effect=[None, ValueError('not allowed')]) as setter:
                with self.assertRaisesRegex(RuError, expected):
                    self.host.handle({'type': 'frame'})
                self.assertEqual(setter.call_count, 2)
                self.assertEqual(setter.call_args_list[0].args[1], (512 * 1024 * 1024, -1))
            self.assertIs(sys.gettrace(), old_trace)
            self.assertIsNone(self.host.canvas)


if __name__ == '__main__':
    unittest.main()
