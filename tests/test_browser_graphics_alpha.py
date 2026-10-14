"""Browser helper validation and Python/JS alpha command contract."""
import io
import json
import unittest

import test_browser_js
import test_graphics_state_parity
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter


@unittest.skipUnless(test_browser_js.NODE, 'Node required for browser/Python alpha parity')
class BrowserGraphicsAlphaTests(unittest.TestCase):
    run_js = test_browser_js.BrowserCompilerTests.run_js
    compare = test_graphics_state_parity.GraphicsStateParityTests.compare
    prefix = "观 取 外言 '如:观'. 图 取 观 其 画布 100 80. "

    def assert_failure(self, source):
        events = self.run_js(source)
        self.assertEqual(events[-1]['type'], 'error', events)
        self.assertIn('diagnostic', events[-1])
        return events[-1]

    def test_color_helper_needs_no_canvas_and_returns_lowercase_eight_digits(self):
        source = """观 取 外言 '如:观'.
显 __如观 其 颜色 0 0 0 0.
显 观 其 颜色 255 255 255 255.
显 观 其 颜色 1 16 171 128.
显 观 其 颜色 不透明度: 1 蓝: 255 红: 0 绿: 127.
显 __如观 其 颜色 255 0 128 254.
"""
        events = self.run_js(source)
        self.assertTrue(all(event['type'] == 'output' for event in events), events)
        expected = '#00000000\n#ffffffff\n#0110ab80\n#007fff01\n#ff0080fe\n'
        self.assertEqual(''.join(event['text'] for event in events), expected)
        output = io.StringIO()
        Interpreter(stdout=output).execute(parse(source))
        self.assertEqual(output.getvalue(), expected)

    def test_all_four_channels_reject_invalid_values_on_both_backends(self):
        for member in ['__如观', '观']:
            for index in range(4):
                for value in ['(-1)', '256', '0.5', '真', '空', "'0'", '([])']:
                    args = ['0'] * 4
                    args[index] = value
                    source = "观 取 外言 '如:观'. 显 " + member + ' 其 颜色 ' + ' '.join(args) + '.'
                    with self.subTest(member=member, index=index, value=value):
                        self.assert_failure(source)
                        with self.assertRaises(RuError):
                            Interpreter().execute(parse(source))

    def test_helper_requires_exact_four_arguments_and_opacity_name(self):
        for source in [
            '__如观 其 颜色.', '__如观 其 颜色 0 0 0.', '__如观 其 颜色 0 0 0 0 0.',
            '__如观 其 颜色 红: 0 绿: 0 蓝: 0.',
            '__如观 其 颜色 红: 0 绿: 0 蓝: 0 透明: 0.',
            '__如观 其 颜色 红: 0 绿: 0 蓝: 0 不透明度: 0 多: 1.',
            "观 取 外言 '如:观'. 观 其 颜色 0 0 0.",
        ]:
            with self.subTest(source=source):
                self.assert_failure(source)
                with self.assertRaises(RuError):
                    Interpreter().execute(parse(source))
        self.assertIn('画布成员', self.assert_failure(self.prefix + '图 其 颜色 0 0 0 0.')['message'])

    def test_literal_colors_normalize_and_null_styles_match_python(self):
        frames = self.compare(self.prefix + """
图 其 背景 '#AABBCC00'. 图 其 填色 '#FF000080'. 图 其 描边 '#00FF00FF'.
图 其 矩形 1 2 20 30. 图 其 椭圆 1 2 20 30.
图 其 三角形 0 0 10 0 5 10. 图 其 多边形 [[0,0],[10,0],[5,10]].
图 其 线 0 0 10 10. 图 其 文字 '透明' 0 0.
图 其 保存. 图 其 填色 空. 图 其 描边 空.
图 其 矩形 1 2 3 4. 图 其 椭圆 1 2 3 4.
图 其 三角形 0 0 10 0 5 10. 图 其 多边形 [[0,0],[10,0],[5,10]].
图 其 线 0 0 10 10. 图 其 文字 '不画' 0 0. 图 其 恢复.
图 其 矩形 0 0 10 10.
""")
        commands = frames[-1]['commands']
        self.assertEqual(commands[0], {'op': 'background', 'color': '#aabbcc00'})
        for command in commands[1:5] + commands[-1:]:
            self.assertEqual(command['fill'], '#ff000080')
            self.assertEqual(command['stroke'], '#00ff00ff')
        for command in commands[7:11]:
            self.assertEqual(command['fill'], '')
            self.assertEqual(command['stroke'], '')
        self.assertEqual(commands[11]['color'], '')
        self.assertEqual(commands[12]['color'], '')

    def test_generated_alpha_background_replaces_commands_and_keeps_geometry(self):
        frames = self.compare(self.prefix + """
图 其 背景 '#FFFFFF'. 图 其 矩形 0 0 10 10.
图 其 平移 10 20. 图 其 裁剪 0 0 5 5.
图 其 背景 (观 其 颜色 0 0 255 128).
图 其 填色 (观 其 颜色 255 0 0 0). 图 其 描边 空. 图 其 矩形 0 0 20 20.
图 其 每帧 (作 帧:
 图 其 背景 (观 其 颜色 0 0 0 0). 图 其 矩形 帧 0 10 10.
为).
""", [{'type': 'frame'}, {'type': 'frame'}])
        first = frames[0]['commands']
        self.assertEqual(len(first), 2)
        self.assertEqual(first[0], {'op': 'background', 'color': '#0000ff80'})
        self.assertEqual(first[1]['fill'], '#ff000000')
        self.assertEqual(first[1]['transform'], [1, 0, 0, 1, 10, 20])
        self.assertEqual(len(first[1]['clips']), 1)
        for frame in frames[1:]:
            self.assertEqual(frame['commands'][0], {'op': 'background', 'color': '#00000000'})
            self.assertEqual(len(frame['commands']), 2)
            self.assertNotIn('transform', frame['commands'][1])
            self.assertNotIn('clips', frame['commands'][1])

    def test_unsafe_color_values_fail_in_all_style_entrypoints(self):
        invalid = ['red', 'transparent', '#fff', '#ffff', '#12345', '#1234567', '#123456789',
                   '#GG000080', '#１２３４５６', '#ａｂｃｄｅｆ', 'rgba(0,0,0,0)', 'url(x)', 'var(--x)',
                   ' #123456', '#123456 ', '#12345680\t']
        for suffix in ['\n', '\r', '\r\n', '\u2028', '\u2029']:
            for color in ['#123456', '#1234567', '#12345678']:
                invalid.append(color + suffix)
        for setter in ['背景', '填色', '描边']:
            for value in invalid:
                with self.subTest(setter=setter, value=value):
                    error = self.assert_failure(self.prefix + f'图 其 {setter} {json.dumps(value, ensure_ascii=False)}.')
                    self.assertIn('颜色', error['message'])
        self.assert_failure(self.prefix + '图 其 背景 空.')
