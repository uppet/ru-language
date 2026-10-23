"""如UI 网服务（机 其 服务 '网'）：取/投 双端 parity 与诚实失败测试。"""
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import http.server
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
sys.path.insert(0, str(ROOT))

from rulang.browser_compiler import compile_browser
from rulang.frontend import parse
from rulang.graphics_runtime import GraphicsHost
from rulang.interpreter import Interpreter


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/hello':
            body = '你好网'.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
        else:
            body = b'not here'
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length)
        self.server.last_post = (self.path, self.headers.get('Content-Type'),
                                 body.decode('utf-8', errors='replace'))
        payload = ('echo:' + body.decode('utf-8', errors='replace')).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def find_rect(commands, color):
    for command in commands:
        if command.get('op') == 'rect' and command.get('fill') == color:
            return command
    raise AssertionError('rect %s not found: %r' % (color, commands[:12]))


def center(rect):
    return rect['x'] + rect['width'] / 2, rect['y'] + rect['height'] / 2


def texts(frame):
    return [c['text'] for c in frame['commands'] if c.get('op') == 'text']


@unittest.skipUnless(NODE, 'node not found')
class RuUINetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        cls.server.last_post = None
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:%d' % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def program(self, path, action='拉', text='', flag='假'):
        if action == '拉':
            call = "网 其 拉 '%s' (作 果 值 误:" % path
        elif action == '投':
            call = "网 其 投 '%s' '%s' %s (作 果 值 误:" % (path, text, flag)
        else:
            # 未知操作走底层 _网请（门面只导 拉/投），宿主须能力诚实回败。
            call = ("机 其 _网请 操作: '%s' 追加: 假 网址: '%s' 内容: '' 遇成: (作 果 值 误:" % (action, path))
        return """
尽取 外言 '如UI'.

状 取 [''].
机 取 新 应用 宽: 360 高: 640 构: (算:
    得 列 [
        (文 (状[0])),
        (钮 '走' (作:
            网 取 (机 其 服务 '网').
            %s
                若 果 则 状[0] 取 ('网:' + 值). 另 状[0] 取 ('败:' + 误). 然.
                为).
            为))
    ].
法).
机 其 运行.
""" % call

    def first_frame_python(self, source):
        events = []
        host = GraphicsHost(Interpreter(), events.append)
        try:
            host.interpreter.execute(parse(source))
            host.flush()
            return [e for e in events if e['type'] == 'graphics']
        finally:
            host.close()

    def first_frame_javascript(self, source):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'program.mjs').write_text(compile_browser(source), encoding='utf-8')
            (path / 'run.mjs').write_text(
                "import create from './program.mjs';const events=[];"
                "const runtime=create({emit:e=>events.push(e)});"
                "console.log(JSON.stringify(events.filter(e=>e.type==='graphics')));",
                encoding='utf-8')
            result = subprocess.run([NODE, str(path / 'run.mjs')], text=True,
                                    capture_output=True, timeout=30)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        return json.loads(result.stdout)

    def run_python(self, source):
        frames = self.first_frame_python(source)
        x, y = center(find_rect(frames[-1]['commands'], '#4677ff'))
        events = []
        host = GraphicsHost(Interpreter(), events.append)
        try:
            host.interpreter.execute(parse(source))
            host.flush()
            for event in ({'type': 'mouse_down', 'x': x, 'y': y, 'button': 0},
                          {'type': 'mouse_up', 'x': x, 'y': y, 'button': 0},
                          {'type': 'frame'}):
                host.handle(event)
            frames = [e for e in events if e['type'] == 'graphics']
            return frames
        finally:
            host.close()

    def run_javascript(self, source):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'program.mjs').write_text(compile_browser(source), encoding='utf-8')
            (path / 'run.mjs').write_text(
                "import create from './program.mjs';const events=[];"
                "const runtime=create({emit:e=>events.push(e)});"
                "const first=events.find(e=>e.type==='graphics');"
                "const canvas_id=first.canvas_id;"
                "const frames=events.filter(e=>e.type==='graphics');"
                "const btn=frames[frames.length-1].commands.find("
                "c=>c.op==='rect'\u0026\u0026c.fill==='#4677ff');"
                "runtime.dispatch({canvas_id,event:{type:'mouse_down',button:0,"
                "x:btn.x+btn.width/2,y:btn.y+btn.height/2}});"
                "runtime.dispatch({canvas_id,event:{type:'mouse_up',button:0,x:btn.x+btn.width/2,y:btn.y+btn.height/2}});"
                "runtime.dispatch({canvas_id,event:{type:'frame'}});"
                "await new Promise(r=>setTimeout(r,500));"
                "runtime.dispatch({canvas_id,event:{type:'frame'}});"
                "console.log(JSON.stringify(events.filter(e=>e.type==='graphics')));",
                encoding='utf-8')
            result = subprocess.run([NODE, str(path / 'run.mjs')], text=True,
                                    capture_output=True, timeout=30)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        return json.loads(result.stdout)

    def assert_both(self, source, expected_text):
        # 断言首个文 op（状态行）；按钮标签等同帧其余文不入断言。
        self.assertEqual(texts(self.run_python(source)[-1])[0], expected_text)
        self.assertEqual(texts(self.run_javascript(source)[-1])[0], expected_text)

    def test_get_returns_body(self):
        self.assert_both(self.program(self.base + '/hello'), '网:你好网')

    def test_post_echoes_body(self):
        self.assert_both(self.program(self.base + '/echo', '投', '你好'), '网:echo:你好')
        self.assertEqual(self.server.last_post[0], '/echo')
        self.assertIn('text/plain', self.server.last_post[1])
        self.assertEqual(self.server.last_post[2], '你好')

    def test_post_json_content_type_with_flag(self):
        self.assert_both(self.program(self.base + '/echo', '投', '{"a":1}', '真'),
                         '网:echo:{"a":1}')
        self.assertEqual(self.server.last_post[1], 'application/json')

    def test_http_error_reported_honestly(self):
        self.assert_both(self.program(self.base + '/missing'), '败:网 HTTP 404')

    def test_scheme_restricted_to_http(self):
        self.assert_both(self.program('ftp://example.com/x'), '败:网 只识 http/https')

    def test_unknown_action_rejected(self):
        self.assert_both(self.program(self.base + '/hello', '删'), '败:网 不识此操作：删')

    def test_advertises_net_on_both_backends(self):
        source = """
尽取 外言 '如UI'.

状 取 [''].
机 取 新 应用 宽: 360 高: 640 构: (算:
    得 列 [
        (文 (状[0])),
        (钮 '查' (作:
            若 (机 其 能 '网') 则 状[0] 取 '有网'. 另 状[0] 取 '无网'. 然.
            为))
    ].
法).
机 其 运行.
"""
        self.assert_both(source, '有网')


if __name__ == '__main__':
    unittest.main()
