"""Exact RGBA bytes, legacy colors and Python transport color boundaries."""
import io
import time
import unittest
from unittest.mock import patch

from rulang.frontend import RuError, parse
from rulang.graphics_runtime import GraphicsHost
from rulang.interpreter import Interpreter
from rushu.kernel import Session


class GraphicsAlphaTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.events = []
        self.interpreter = Interpreter(stdout=self.output)
        self.host = GraphicsHost(self.interpreter, self.events.append)
        self.addCleanup(self.host.close)
        self.run_ru("观 取 外言 '如:观'.")

    def run_ru(self, source):
        self.interpreter.execute(parse(source))
        self.host.flush()

    def canvas(self):
        self.run_ru('图 取 观 其 画布 80 60.')

    def test_exact_rgba_helper_without_canvas_and_named_arguments(self):
        self.run_ru("显 (观 其 颜色 0 0 0 0). 显 (观 其 颜色 255 255 255 255). "
                    "显 (观 其 颜色 不透明度: 128 蓝: 16 绿: 2 红: 255). "
                    "配 取 算 观 其 颜色. 显 (配 1 2 3 4).")
        self.assertEqual(self.output.getvalue(), '#00000000\n#ffffffff\n#ff021080\n#01020304\n')
        self.assertIsNone(self.host.canvas)
        # The pure helper needs no graphics host, unlike canvas creation.
        output = io.StringIO()
        Interpreter(stdout=output).execute(parse("尽 取 外言 '如:观'. 显 (颜色 1 2 3 255)."))
        self.assertEqual(output.getvalue(), '#010203ff\n')

    def test_every_byte_has_two_lowercase_hex_digits(self):
        for byte in range(256):
            self.run_ru(f'色 取 观 其 颜色 {byte} {byte} {byte} {byte}.')
            self.assertEqual(self.interpreter.global_scope.values['色'], '#' + f'{byte:02x}' * 4)
        self.assertIsNone(self.host.canvas)

    def test_helper_rejects_each_invalid_channel_and_arguments(self):
        for value in (-1., 256., .5, float('nan'), float('inf'), float('-inf'), True, False, None, '1', []):
            self.interpreter.global_scope.values['坏'] = value
            for position in range(4):
                values = ['0'] * 4
                values[position] = '坏'
                # Direct builtin tests are independent of stdlib type guards.
                with self.subTest(value=value, position=position), self.assertRaises(RuError):
                    self.run_ru('__如观 其 颜色 ' + ' '.join(values) + '.')
        for args in ('', '0 0 0', '0 0 0 0 0', '红: 0 红: 0 绿: 0 蓝: 0 不透明度: 0',
                     '红: 0 绿: 0 蓝: 0 透明: 0', '真 0 0 0', '0 0 0 空'):
            with self.subTest(args=args), self.assertRaises(RuError):
                self.run_ru('观 其 颜色 ' + args + '.')

    def test_legacy_and_alpha_styles_all_shapes_and_null(self):
        self.canvas()
        self.run_ru("图 其 背景 '#AABBCC00'. 图 其 填色 '#AbCdEf80'. 图 其 描边 '#AABBCC'. "
                    "图 其 矩形 0 0 10 10. 图 其 椭圆 0 0 10 10. 图 其 三角形 0 0 10 0 0 10. "
                    "图 其 文字 '甲' 0 0. 图 其 线 0 0 10 10. 图 其 填色 空. 图 其 描边 空. "
                    "图 其 多边形 [[0,0],[10,0],[0,10]]. 图 其 文字 '乙' 0 0. 图 其 线 0 0 10 10.")
        commands = self.events[-1]['commands']
        self.assertEqual(commands[0], {'op': 'background', 'color': '#aabbcc00'})
        for command in commands[1:4]:
            self.assertEqual(command['fill'], '#abcdef80')
            self.assertEqual(command['stroke'], '#aabbcc')
        self.assertEqual(commands[4]['color'], '#abcdef80')
        self.assertEqual(commands[5]['color'], '#aabbcc')
        self.assertEqual((commands[6]['fill'], commands[6]['stroke']), ('', ''))
        self.assertEqual(commands[7]['color'], '')
        self.assertEqual(commands[8]['color'], '')

    def test_strict_color_strings_and_invalid_background_preserve_state(self):
        self.canvas()
        self.run_ru("图 其 填色 '#12345678'. 图 其 描边 '#87654321'. 图 其 矩形 0 0 10 10.")
        invalid = ('', '#fff', '#ffff', '#12345', '#1234567', '#123456789', '#gg000000',
                   '#１２３４５６', 'red', 'transparent', 'rgba(0,0,0,0)', 'url(https://example.invalid)',
                   '#123456\n', '#12345678\r', '#12345678\u2028', '#12345678\u2029',
                   ' #12345678', '#12345678 ', '#12345678\x00', True, 0., [])
        for value in invalid:
            self.interpreter.global_scope.values['坏'] = value
            for member in ('背景', '填色', '描边'):
                commands, size = list(self.host.canvas.commands), self.host.canvas.command_bytes
                with self.subTest(value=value, member=member), self.assertRaises(RuError):
                    self.run_ru('图 其 ' + member + ' 坏.')
                self.assertEqual(self.host.canvas.commands, commands)
                self.assertEqual(self.host.canvas.command_bytes, size)
                self.assertEqual(self.host.canvas.fill, '#12345678')
                self.assertEqual(self.host.canvas.stroke, '#87654321')
        with self.assertRaises(RuError):
            self.run_ru('图 其 背景 空.')

    def test_alpha_save_restore_background_and_fresh_frames(self):
        self.canvas()
        self.run_ru("图 其 填色 '#11223300'. 图 其 描边 '#44556680'. 图 其 保存. "
                    "图 其 填色 '#abcdef'. 图 其 平移 5 6. 图 其 裁剪 0 0 2 2. "
                    "图 其 矩形 0 0 4 4. 图 其 背景 '#00000000'. 图 其 矩形 0 0 4 4. "
                    "图 其 恢复. 图 其 矩形 0 0 4 4.")
        commands = self.events[-1]['commands']
        self.assertEqual(len(commands), 3)
        self.assertEqual(commands[0], {'op': 'background', 'color': '#00000000'})
        self.assertEqual(commands[1]['transform'], [1, 0, 0, 1, 5, 6])
        self.assertEqual(len(commands[1]['clips']), 1)
        self.assertEqual(commands[2]['fill'], '#11223300')
        self.assertEqual(commands[2]['stroke'], '#44556680')
        self.run_ru("图 其 每帧 (作 帧: 图 其 背景 '#11223380'. 图 其 矩形 帧 0 4 4. 为).")
        for index in (1, 2):
            self.host.handle({'type': 'frame'})
            commands = self.events[-1]['commands']
            self.assertEqual(len(commands), 2)
            self.assertEqual(commands[1]['x'], index)
            self.assertEqual(commands[1]['fill'], '#11223300')


class GraphicsAlphaIPCTests(unittest.TestCase):
    def setUp(self):
        with patch.object(Session, '_start'):
            self.session = Session()
        self.scene = {'type': 'graphics', 'canvas_id': 'canvas', 'width': 20, 'height': 20,
                      'fps': 30, 'running': False, 'handlers': [], 'commands': []}

    def test_ipc_accepts_exact_legacy_and_alpha_colors_and_empty_styles(self):
        for value in ('#123456', '#ABCDEF', '#12345600', '#ABCDEFff', ''):
            for op in ('rect', 'ellipse', 'polygon', 'line', 'text', 'background'):
                if op == 'background' and value == '':
                    continue
                fields = {'fill': value, 'stroke': value} if op in ('rect', 'ellipse', 'polygon') else {'color': value}
                self.session._accept_graphics(dict(self.scene, commands=[dict(op=op, **fields)]))

    def test_ipc_rejects_invalid_missing_and_wrongly_typed_colors(self):
        for value in (None, True, 0, [], {}, '#fff', '#1234567', '#123456789', '#１２３４５６',
                      'red', 'transparent', 'rgba(0,0,0,0)', '#123456\n', '#12345678\r',
                      '#12345678\u2028', '#12345678\u2029', '#12345678\x00'):
            for op in ('rect', 'ellipse', 'polygon', 'line', 'text', 'background'):
                fields = {'fill': value, 'stroke': '#000000'} if op in ('rect', 'ellipse', 'polygon') else {'color': value}
                with self.subTest(value=value, op=op), self.assertRaises(ValueError):
                    self.session._accept_graphics(dict(self.scene, commands=[dict(op=op, **fields)]))
        for command in ({'op': 'background', 'color': ''}, {'op': 'line'},
                        {'op': 'rect', 'fill': '#000000'}, {'op': 'polygon', 'fill': '#000000', 'stroke': None}):
            with self.subTest(command=command), self.assertRaises(ValueError):
                self.session._accept_graphics(dict(self.scene, commands=[command]))


class GraphicsAlphaSpawnTests(unittest.TestCase):
    def test_alpha_commands_survive_real_spawn_transport_and_callbacks(self):
        session = Session()
        self.addCleanup(session.close)
        def ready():
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                result = session.poll()
                self.assertFalse([e for e in result['events'] if e['type'] == 'error'], result)
                if result['state'] == 'idle' and not result['graphics_busy']:
                    return result
                self.assertNotEqual(result['state'], 'dead', result)
                time.sleep(.01)
            self.fail('alpha graphics did not become ready')
        session.execute("观 取 外言 '如:观'. 图 取 观 其 画布 20 20. "
                        "图 其 背景 '#00000000'. 图 其 描边 空. 图 其 填色 (观 其 颜色 255 0 16 128). "
                        "图 其 三角形 0 0 10 0 0 10. "
                        "图 其 每帧 (作 帧: 图 其 背景 '#11223380'. 图 其 矩形 帧 0 2 2. 为).", 'alpha')
        result = ready()
        canvas_id = result['graphics']['canvas_id']
        scene = next(e for e in reversed(result['events']) if e['type'] == 'graphics')
        self.assertEqual(scene['commands'][0]['color'], '#00000000')
        self.assertEqual(scene['commands'][1]['fill'], '#ff001080')
        for _ in range(2):
            time.sleep(.05)
            session.dispatch_graphics(canvas_id, 'alpha', 1, 1, {'type': 'frame'})
            result = ready()
            scene = next(e for e in reversed(result['events']) if e['type'] == 'graphics')
            self.assertEqual(scene['commands'][0]['color'], '#11223380')
            self.assertEqual(scene['commands'][1]['fill'], '#ff001080')
            self.assertEqual(scene['commands'][1]['stroke'], '')
