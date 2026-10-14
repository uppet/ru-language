"""Generated immutable images: language API, lifetime, and exact budgets."""
import io
import json
import unittest
from unittest.mock import patch

from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter
from rulang.graphics_runtime import GraphicsHost, MAX_RESOURCE_BYTES

PREFIX = "观 取 外言 '如:观'. 图 取 观 其 画布 100 80. "
CACHE = "像 取 图 其 缓存 宽:20 高:10 绘制:(作 层: 层 其 矩形 1 2 3 4. 为). "


class GraphicsCacheTests(unittest.TestCase):
    def setUp(self):
        self.events, self.output = [], io.StringIO()
        self.interpreter = Interpreter(stdout=self.output)
        self.host = GraphicsHost(self.interpreter, self.events.append)
        self.addCleanup(self.host.close)

    def run_ru(self, source):
        self.interpreter.execute(parse(source))
        self.host.flush()

    def test_build_once_repeat_reference_and_self_contained_frames(self):
        self.run_ru(PREFIX + "次数 取 [0]. 像 取 图 其 缓存 20 10 (作 层: 次数[0] 取 次数[0]+1. 层 其 矩形 1 2 3 4. 为). "
                    "图 其 每帧 (作 帧: 图 其 贴图 像 0 0. 图 其 贴图 像 帧 2. 为).")
        self.assertNotIn('resources', self.events[-1])
        for _ in range(3):
            self.host.handle({'type': 'frame'})
            event = self.events[-1]
            self.assertEqual(len(event['resources']), 1)
            self.assertEqual(event['commands'][0], {'op': 'image', 'resource': 'cache-1', 'x': 0, 'y': 0})
        self.assertEqual(self.interpreter.global_scope.values['次数'], [1.])
        self.run_ru('宽度 取 像 其 宽. 高度 取 像 其 高.')
        self.assertEqual(self.interpreter.global_scope.values['宽度'], 20.)
        self.assertEqual(self.interpreter.global_scope.values['高度'], 10.)

    def test_recorder_defaults_freeze_geometry_points_and_escape(self):
        self.run_ru(PREFIX + "逃逸 取 [空]. 点 取 [[1,2],[3,4],[5,6]]. 图 其 填色 '#ffffff'. 图 其 平移 9 9. "
                    "像 取 图 其 缓存 20 10 (作 层: 逃逸[0] 取 层. 层 其 保存. 层 其 平移 2 3. 层 其 裁剪 0 0 8 8. 层 其 多边形 点. 层 其 恢复. 为). "
                    "点[0][0] 取 99. 图 其 贴图 像 0 0.")
        event = self.events[-1]
        recipe = event['resources'][0]['commands'][0]
        self.assertEqual(recipe['fill'], '#4677ff')
        self.assertEqual(recipe['points'][0], [1,2])
        self.assertEqual(recipe['transform'], [1,0,0,1,2,3])
        self.assertEqual(event['commands'][0]['transform'], [1,0,0,1,9,9])
        target = self.interpreter.global_scope.values['逃逸'][0].graphics_canvas
        self.assertEqual(target.commands, [])
        self.assertEqual(target.stack, [])
        self.assertIsNone(target.owner)
        with self.assertRaisesRegex(RuError, '已关闭'):
            self.run_ru('逃逸[0] 其 宽.')

    def test_failed_build_preserves_main_and_releases_reservation(self):
        self.run_ru(PREFIX + "图 其 背景 '#123456'.")
        canvas = self.host.canvas
        for body in ("图 其 填色 '#ffffff'.", "图 其 缓存 1 1 (作 层: 为).", "观 其 画布 1 1.",
                     "层 其 保存.", "层 其 帧率 1.", "层 其 缓存 1 1 (作 子: 为).", "层 其 贴图 空 0 0."):
            with self.subTest(body=body), self.assertRaises(RuError):
                self.run_ru('图 其 缓存 2048 2048 (作 层: ' + body + ' 为).')
            self.assertIs(self.host.canvas, canvas)
            self.assertFalse(canvas.closed)
            self.assertEqual(canvas.commands, [{'op': 'background', 'color': '#123456'}])
            self.assertEqual(canvas.fill, '#4677ff')
            self.assertEqual(canvas.resources, {})
            self.assertEqual(canvas.resource_pixels, 0)
            self.assertIsNone(self.host.recording)
        self.run_ru(CACHE)
        self.assertEqual(len(canvas.resources), 1)

    def test_event_phase_blocks_cache_even_on_replacement_canvas(self):
        for event, registration, body in (
            ({'type': 'frame'}, '每帧 (作 帧:', ''),
            ({'type': 'key_down', 'key': 'x'}, '按键 (作 键:', ''),
            ({'type': 'key_down', 'key': 'x'}, '按键 (作 键:', '另图 取 观 其 画布 10 10. ')):
            with self.subTest(body=body, event=event):
                target = '另图' if body else '图'
                self.run_ru(PREFIX + '图 其 ' + registration + body + target + ' 其 缓存 1 1 (作 层: 为). 为).')
                with self.assertRaisesRegex(RuError, '初始化'):
                    self.host.handle(event)
                self.assertIsNone(self.host.canvas)
                self.assertEqual(self.host.phase, 'initialization')

    def test_lifetime_cleanup_and_old_dimensions_remain_readable(self):
        self.run_ru(PREFIX + CACHE + '图 其 贴图 像 0 0.')
        event = self.events[-1]
        image = self.interpreter.global_scope.values['像'].graphics_image
        old = self.host.canvas
        self.host.begin_execution()
        self.assertEqual(old.resources, {})
        self.assertFalse(hasattr(image, 'commands'))
        self.assertEqual(event['resources'][0]['commands'][0]['op'], 'rect')
        self.run_ru('显 像 其 宽. 另图 取 观 其 画布 20 20.')
        with self.assertRaisesRegex(RuError, '失效|另一画布'):
            self.run_ru('另图 其 贴图 像 0 0.')

    def test_input_preserves_resources_background_discards_and_frame_clears(self):
        self.run_ru(PREFIX + CACHE + "图 其 贴图 像 0 0. 图 其 按键 (作 键: 图 其 填色 '#ffffff'. 为). 图 其 每帧 (作 帧: 为).")
        self.host.handle({'type': 'key_down', 'key': 'x'})
        self.assertEqual(len(self.events[-1]['resources']), 1)
        self.run_ru("图 其 背景 '#000000'.")
        self.assertNotIn('resources', self.events[-1])
        self.run_ru('图 其 贴图 像 0 0.')
        self.host.handle({'type': 'frame'})
        self.assertEqual(self.events[-1]['commands'], [])
        self.assertNotIn('resources', self.events[-1])

    def test_image_count_pixel_and_dimension_budgets(self):
        self.run_ru(PREFIX)
        for i in range(8):
            self.run_ru(f'像{i} 取 图 其 缓存 1 1 (作 层: 为).')
        with self.assertRaisesRegex(RuError, '8 张'):
            self.run_ru('图 其 缓存 1 1 (作 层: 为).')
        self.run_ru(PREFIX + '像 取 图 其 缓存 2048 2048 (作 层: 为).')
        with self.assertRaisesRegex(RuError, '4194304'):
            self.run_ru('图 其 缓存 1 1 (作 层: 为).')
        for arguments in ('0 1', '2049 1', '1.5 1', '真 1'):
            with self.subTest(arguments=arguments), self.assertRaises(RuError):
                self.run_ru('图 其 缓存 ' + arguments + ' (作 层: 为).')

    def test_recipe_and_frame_unique_command_budgets_no_registry_command_cap(self):
        # Background commands are intentionally tiny to isolate command budgets
        # from the independent 128 KiB registry limit.
        self.run_ru(PREFIX)
        from rulang.graphics_runtime import DrawingResource
        c = self.host.canvas
        definition = json.dumps({'id':'cache-1','kind':'drawing','width':1,'height':1,'commands':[{'op':'background','color':'#000000'}]*2047}, separators=(',',':'))
        c.resources['cache-1'] = DrawingResource(definition, 2047, 1)
        bad = lambda text: (_ for _ in ()).throw(RuError(text))
        c.command({'op':'image','resource':'cache-1','x':0,'y':0}, bad)
        with self.assertRaisesRegex(RuError, '合计'):
            c.command({'op':'image','resource':'cache-1','x':1,'y':0}, bad)
        self.assertEqual(len(c.commands), 1)
        c.commands=[]; c.command_bytes=2
        c.resources['cache-2'] = DrawingResource(definition.replace('cache-1','cache-2'), 2047, 1)
        c.command({'op':'image','resource':'cache-2','x':0,'y':0}, bad)
        self.host.flush()
        self.assertEqual(len(self.events[-1]['resources']), 1)

    def test_registry_byte_budget_includes_exact_wrappers_utf8(self):
        self.run_ru(PREFIX + "像 取 图 其 缓存 1 1 (作 层: 层 其 文字 '中文' 0 0. 为).")
        c = self.host.canvas
        actual = len(('[' + ','.join(r.definition for r in c.resources.values()) + ']').encode('utf-8'))
        self.assertEqual(actual, c.resource_bytes)
        self.run_ru(PREFIX)
        with patch('rulang.graphics_runtime.MAX_RESOURCE_BYTES', actual):
            self.run_ru("像 取 图 其 缓存 1 1 (作 层: 层 其 文字 '中文' 0 0. 为).")
        self.run_ru(PREFIX)
        with patch('rulang.graphics_runtime.MAX_RESOURCE_BYTES', actual-1), self.assertRaisesRegex(RuError, '128 KiB'):
            self.run_ru("像 取 图 其 缓存 1 1 (作 层: 层 其 文字 '中文' 0 0. 为).")
        self.assertEqual(self.host.canvas.resources, {})

    def test_recipe_command_limit_reserves_image_slot(self):
        from rulang.graphics_runtime import DrawingRecorder
        self.run_ru(PREFIX)
        recorder = DrawingRecorder(self.host, 1, 1, 'cache-1', self.host.canvas)
        bad = lambda text: (_ for _ in ()).throw(RuError(text))
        for _ in range(2047):
            recorder.command({'op': 'background', 'color': '#000000'}, bad)
        with self.assertRaisesRegex(RuError, '2047'):
            recorder.command({'op': 'background', 'color': '#000000'}, bad)
        self.assertEqual(len(recorder.commands), 2047)
        recorder.invalidate()

    def test_full_frame_exact_bytes_preflight_preserves_commands(self):
        self.run_ru(PREFIX + "像 取 图 其 缓存 1 1 (作 层: 层 其 文字 '" + '字' * 1000 + "' 0 0. 为). 图 其 贴图 像 0 0.")
        actual = len(json.dumps(self.events[-1], ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        c = self.host.canvas
        with patch('rulang.graphics_runtime.MAX_FRAME_BYTES', actual):
            c.dirty = True
            self.host.flush()
        prior = self.events[-1]
        c.commands, c.command_bytes = [], 2
        with patch('rulang.graphics_runtime.MAX_FRAME_BYTES', actual - 1), self.assertRaisesRegex(RuError, '256 KiB'):
            self.run_ru('图 其 贴图 像 0 0.')
        self.assertEqual(c.commands, [])
        self.assertIs(self.events[-1], prior)

    def test_return_value_ignored_empty_cache_and_failed_escape(self):
        self.run_ru(PREFIX + '逃逸 取 [空]. 像 取 图 其 缓存 7 9 (算 层: 得 123. 法). 图 其 贴图 像 0 0.')
        self.assertEqual(self.events[-1]['resources'][0]['commands'], [])
        self.run_ru('显 像 其 宽.')
        self.assertEqual(self.output.getvalue(), '7\n')
        with self.assertRaisesRegex(RuError, '成对'):
            self.run_ru('图 其 缓存 2 2 (作 层: 逃逸[0] 取 层. 层 其 保存. 为).')
        target = self.interpreter.global_scope.values['逃逸'][0].graphics_canvas
        self.assertTrue(target.closed)
        self.assertEqual(target.commands, [])
        self.assertEqual(target.stack, [])
        self.assertIsNone(target.owner)
        with self.assertRaises(RuError):
            self.run_ru('逃逸[0] 其 矩形 0 0 1 1.')

    def test_invalid_callback_handles_and_readonly_fields(self):
        self.run_ru(PREFIX + CACHE)
        for source in ('图 其 缓存 1 1 2.', '图 其 缓存 1 1 (作: 为).', '图 其 贴图 1 0 0.',
                       '像 其 宽 1.', '像 其 高 取 4.', '像 其 文字 \'x\' 0 0.'):
            with self.subTest(source=source), self.assertRaises(RuError):
                self.run_ru(source)


if __name__ == '__main__':
    unittest.main()
