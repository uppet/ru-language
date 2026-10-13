"""Browser graphics state and frozen command parity without a live browser."""
import unittest
import test_browser_js


class BrowserGraphicsUpgradeTests(unittest.TestCase):
    run_js = test_browser_js.BrowserCompilerTests.run_js
    prefix = "观 取 外言 '如:观'. 图 取 观 其 画布 100 100. "

    def graphics(self, source, tail=''):
        events = self.run_js(self.prefix + source, tail)
        self.assertFalse(any(e['type'] == 'error' for e in events), events[-1])
        return [e for e in events if e['type'] == 'graphics']

    def test_polygon_snapshot_and_composition(self):
        frames = self.graphics("""
点 取 [[0, 0], [10, 0], [0, 10]].
图 其 平移 10 20. 图 其 缩放 2 3.
图 其 多边形 点. 点[0][0] 取 99.
图 其 三角形 1 2 3 4 5 6.
""")
        a, b = frames[-1]['commands']
        self.assertEqual(a['transform'], [2, 0, 0, 3, 10, 20])
        self.assertEqual(a['points'], [[0, 0], [10, 0], [0, 10]])
        self.assertEqual(b['points'], [[1, 2], [3, 4], [5, 6]])

    def test_state_restore_clips_and_background(self):
        commands = self.graphics("""
图 其 平移 10 20. 图 其 裁剪 0 0 30 40.
图 其 保存. 图 其 平移 3 4. 图 其 填色 '#ff0000'.
图 其 裁剪 1 2 3 4. 图 其 背景 '#ffffff'. 图 其 矩形 0 0 5 5.
图 其 恢复. 图 其 椭圆 0 0 5 5.
图 其 重置变换. 图 其 取消裁剪. 图 其 文字 '好' 1 2.
""")[-1]['commands']
        self.assertEqual(commands[0], {'op': 'background', 'color': '#ffffff'})
        self.assertEqual(commands[1]['transform'], [1, 0, 0, 1, 13, 24])
        self.assertEqual(len(commands[1]['clips']), 2)
        self.assertEqual(commands[1]['clips'][0]['transform'], [1, 0, 0, 1, 10, 20])
        self.assertEqual(commands[2]['fill'], '#4677ff')
        self.assertEqual(len(commands[2]['clips']), 1)
        self.assertNotIn('transform', commands[3])
        self.assertNotIn('clips', commands[3])

    def test_callback_resets_geometry_but_retains_styles(self):
        frames = self.graphics("""
图 其 平移 10 20. 图 其 裁剪 0 0 1 1. 图 其 填色 '#abcdef'.
图 其 每帧 (作 帧: 图 其 矩形 0 0 10 10. 图 其 平移 5 6. 图 其 裁剪 0 0 1 1. 为).
""", "const canvas_id=events.at(-1).canvas_id;runtime.dispatch({canvas_id,event:{type:'frame'}});runtime.dispatch({canvas_id,event:{type:'frame'}});")
        for frame in frames[1:]:
            self.assertEqual(frame['commands'][0]['fill'], '#abcdef')
            self.assertNotIn('transform', frame['commands'][0])
            self.assertNotIn('clips', frame['commands'][0])

    def test_rotation_general_matrix_and_degenerate_scale(self):
        commands = self.graphics("图 其 旋转 0. 图 其 变换 1 2 3 4 5 6. 图 其 缩放 0 (-1). 图 其 线 0 0 2 3.")[-1]['commands']
        self.assertEqual(commands[0]['transform'], [0, 0, -3, -4, 5, 6])

    def test_bad_points_state_limits_and_accumulated_matrix(self):
        for source, message in [
            ('图 其 多边形 [[0, 0], [1, 1]].', '3 至 256'),
            ('图 其 多边形 [[0, 0], [1, 1], [2, 2, 2]].', '两个坐标'),
            ('图 其 多边形 [[0, 0], [1, 1], [真, 2]].', '有限数'),
            ('图 其 恢复.', '保存'),
            ('循 65 次 图 其 保存. 环', '64'),
            ('循 33 次 图 其 裁剪 0 0 1 1. 环', '32'),
            ('图 其 缩放 100000 1. 图 其 缩放 2 1.', '累计变换'),
            ('图 其 裁剪 0 0 (-1) 1.', '有限数'),
        ]:
            with self.subTest(source=source):
                events = self.run_js(self.prefix + source)
                self.assertEqual(events[-1]['type'], 'error')
                self.assertIn(message, events[-1]['message'])

    def test_unbalanced_initial_and_callback_close(self):
        for source, tail in [('图 其 保存.', ''),
            ('图 其 每帧 (作 帧: 图 其 保存. 为).', "runtime.dispatch({canvas_id:events.at(-1).canvas_id,event:{type:'frame'}});")]:
            events = self.run_js(self.prefix + source, tail)
            self.assertEqual(events[-2]['type'], 'graphics_closed')
            self.assertIn('保存与恢复', events[-1]['message'])
            self.assertEqual(events[-1]['diagnostic']['line'], 1)

    def test_explicit_close_and_replacement_discard_stack(self):
        self.graphics('图 其 保存. 图 其 关闭.')
        self.graphics('图 其 保存. 新图 取 观 其 画布 20 20.')
