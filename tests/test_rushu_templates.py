"""Run the actual starting-point sources, without stdin or model requests."""
import http.client
import io
import json
from pathlib import Path
import shutil
import subprocess
import threading
import unittest

from rulang.frontend import parse
from rulang.interpreter import Interpreter
from rulang.graphics_runtime import GraphicsHost
from rushu.server import make_server

ROOT = Path(__file__).resolve().parents[1]


class NoInput(io.StringIO):
    def read(self, *args, **kwargs):
        raise AssertionError('Starting templates must not read stdin')

    def readline(self, *args, **kwargs):
        raise AssertionError('Starting templates must not wait for input')


class StartingTemplateExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = shutil.which('node')
        if not node:
            raise unittest.SkipTest('Node.js is required to load the actual template sources')
        script = """
import {templates,createTemplateBook} from './rushu/static/templates.mjs';
console.log(JSON.stringify(Object.fromEntries(templates.map(t=>[t.id,createTemplateBook(t.id)]))));
"""
        result = subprocess.run([node, '--input-type=module', '-e', script],
                                cwd=ROOT, capture_output=True, text=True,
                                encoding='utf-8', timeout=15, check=True)
        cls.books = json.loads(result.stdout)

    def execute_twice(self, name, expected, check_graphics=False):
        output = io.StringIO()
        events = []
        interpreter = Interpreter(stdout=output, stdin=NoInput())
        host = GraphicsHost(interpreter, events.append)
        try:
            for repeat in range(2):
                with self.subTest(template=name, repeat=repeat):
                    start = len(output.getvalue())
                    for cell in self.books[name]['cells']:
                        if cell['type'] == 'code' and cell['source']:
                            host.begin_execution()
                            interpreter.execute(parse(cell['source']))
                            host.flush()
                    self.assertEqual(output.getvalue()[start:], expected)
                    if check_graphics:
                        scene = host.snapshot()
                        self.assertEqual((scene['width'], scene['height']), (360, 200))
                        self.assertEqual([c['op'] for c in events[-1]['commands']],
                                         ['background', 'ellipse'])
                        host.handle({'type': 'mouse_down', 'x': 90, 'y': 70, 'button': 0})
                        commands = events[-1]['commands']
                        self.assertEqual([c['op'] for c in commands], ['background', 'ellipse'])
                        self.assertEqual((commands[1]['x'], commands[1]['y']), (74, 54))
                        host.handle({'type': 'key_down', 'key': 'r'})
                        self.assertEqual([c['op'] for c in events[-1]['commands']], ['background'])
        finally:
            host.close()

    def test_templates_use_canonical_imports_and_keep_product_titles(self):
        for book in self.books.values():
            for cell in book['cells']:
                if cell['type'] == 'code':
                    self.assertNotIn("外言 '如观'", cell['source'])
                    self.assertNotIn("外言 '如竞'", cell['source'])
        self.assertTrue(any("外言 '如:竞'" in c['source']
                            for c in self.books['contest']['cells']))
        self.assertTrue(any("外言 '如:观'" in c['source']
                            for c in self.books['graphics']['cells']))
        templates = (ROOT / 'rushu/static/templates.mjs').read_text(encoding='utf-8')
        self.assertIn("title:'如竞题解'", templates)
        self.assertIn("title:'如观互动'", templates)

    def test_basics_repeat_in_one_session(self):
        self.execute_twice('basics', '你好，如书\n今天开始写如言\n')

    def test_text_repeat_in_one_session(self):
        self.execute_twice('text', '你好，如书\n小明喜欢梨\n')

    def test_contest_repeat_without_stdin(self):
        self.execute_twice('contest', '8\n')

    def test_graphics_repeat_and_mouse_keyboard_callbacks(self):
        self.execute_twice('graphics', '', check_graphics=True)

    def test_generation_and_blank_have_no_executable_source(self):
        for name in ('generation', 'blank'):
            with self.subTest(template=name):
                self.assertTrue(all(not cell['source'] for cell in self.books[name]['cells']
                                    if cell['type'] == 'code'))
                self.execute_twice(name, '')


class StartingTemplateHTTPTests(unittest.TestCase):
    def test_templates_module_is_served_without_authentication(self):
        server = make_server(token='templates-test-abcdefghijklmnop')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        try:
            connection.request('GET', '/templates.mjs')
            response = connection.getresponse()
            content = response.read().decode('utf-8')
            self.assertEqual(response.status, 200, content)
            self.assertIn('text/javascript', response.getheader('Content-Type'))
            self.assertIn('createTemplateBook', content)
            self.assertEqual(content, (ROOT / 'rushu/static/templates.mjs').read_text(encoding='utf-8'))
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
