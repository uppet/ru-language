"""Authored Responses fixtures, not an evaluation of real LLM generation quality.

Exercises real loopback HTTP -> Rushu generation -> explicit GraphicsHost and
spawned Rushu session execution. Never contacts a model or changes budgets.
"""
import http.client
import json
import math
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_generation import MockResponses, response_for
from rulang.frontend import parse
from rulang.interpreter import Interpreter
from rulang.graphics_runtime import GraphicsHost
from rulang.generation import GenerationConfig, LOCAL_TEST_API_KEY
from rushu import generation
from rushu.kernel import Session
from rushu.server import make_server

EXAMPLES = ROOT / 'rushu/examples'


class AnimationGenerationExamplesTests(unittest.TestCase):
    def test_authored_mock_response_then_explicit_host_execution(self):
        server = make_server()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for name in ('circle-motion', 'seeded-stars', 'solar-system-math'):
                with self.subTest(name=name):
                    source = (EXAMPLES / 'ruguan' / (name + '.ru')).read_text()
                    book = json.loads((EXAMPLES / (name + '.rushu.json')).read_text())
                    self.assertEqual(book['cells'][1]['source'], source)
                    with MockResponses(response_for(source)) as mock:
                        config = GenerationConfig(LOCAL_TEST_API_KEY, mock.base, 'authored-fixture')
                        with patch.object(generation, 'load_config', return_value=config), \
                             patch.object(server.sessions, 'create', side_effect=AssertionError('generation executed')):
                            connection = http.client.HTTPConnection(*server.server_address, timeout=10)
                            connection.request('POST', '/api/generate', json.dumps({'prompt': '用标准数学与随机库画可互动动画。\n如是我言'}),
                                {'Content-Type': 'application/json', 'X-Rushu-Token': server.token, 'Origin': server.origin})
                            response = connection.getresponse()
                            result = json.loads(response.read())
                            connection.close()
                            self.assertEqual(response.status, 200, result)
                            self.assertTrue(result['valid'], result)
                            self.assertEqual(result['source'], source)
                        prompt = mock.requests[0][2]['input'][0]['content'][0]['text']
                        for text in ('复用规范已列出的标准库', 'Taylor', 'LCG', '形或阵', '不是删减功能', '本次运行环境：如书'):
                            self.assertIn(text, prompt)
                    interpreter, events = Interpreter(), []
                    host = GraphicsHost(interpreter, events.append)
                    try:
                        interpreter.execute(parse(result['source']))
                        host.flush()
                        for _ in range(3):
                            host.handle({'type': 'frame'})
                        self.assertEqual(events[-1]['commands'][0]['op'], 'background')
                        if name == 'circle-motion':
                            self.assertAlmostEqual(interpreter.global_scope.values['状态'][0], math.pi / 20)
                        if name == 'seeded-stars':
                            stars = interpreter.global_scope.values['星']
                            self.assertEqual(len(stars), 24)
                            original = [list(point) for point in stars]
                            host.handle({'type': 'frame'})
                            self.assertEqual(stars, original)
                        if name == 'solar-system-math':
                            state = interpreter.global_scope.values['状态']
                            for index in range(10):
                                x, y = (370, 390) if index == 9 else (state[4][index], state[5][index])
                                step = state[3]
                                host.handle({'type': 'mouse_move', 'x': x, 'y': y})
                                self.assertEqual(state[0], index)
                                self.assertFalse(host.snapshot()['running'])
                                self.assertEqual(state[3], step)
                                self.assertTrue(any(c.get('text') == interpreter.global_scope.values['介绍'][index][0] for c in events[-1]['commands']))
                                host.handle({'type': 'mouse_move', 'x': 740, 'y': 700})
                                self.assertTrue(host.snapshot()['running'])
                            for _ in range(717):
                                host.handle({'type': 'frame'})
                            self.assertEqual(state[3], 720)
                            self.assertAlmostEqual(state[4][0], 430)
                            self.assertAlmostEqual(state[5][0], 390)
                    finally:
                        host.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)

    def test_solar_book_runs_in_real_spawned_rushu_session(self):
        def ready(session):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                snapshot = session.poll()
                if snapshot['state'] == 'idle' and not snapshot['graphics_busy']:
                    self.assertFalse(any(event['type'] == 'error' for event in snapshot['events']), snapshot)
                    return snapshot
                time.sleep(.01)
            self.fail('session did not become ready')
        session = Session()
        try:
            source = (EXAMPLES / 'ruguan/solar-system-math.ru').read_text()
            session.execute(source, 'solar')
            snapshot = ready(session)
            self.assertIsNotNone(snapshot['graphics'], snapshot)
            canvas = snapshot['graphics']['canvas_id']
            for event in ({'type': 'frame'}, {'type': 'mouse_move', 'x': 370, 'y': 390}, {'type': 'mouse_move', 'x': 740, 'y': 700}, {'type': 'frame'}):
                time.sleep(.06)
                session.dispatch_graphics(canvas, 'solar', 1, 1, event)
                snapshot = ready(session)
                if event.get('x') == 370:
                    self.assertFalse(snapshot['graphics']['running'])
                else:
                    self.assertTrue(snapshot['graphics']['running'])
            session.dispatch_graphics(canvas, 'solar', 1, 1, {'type': 'close'})
            self.assertIsNone(ready(session)['graphics'])
        finally:
            session.close()


if __name__ == '__main__':
    unittest.main()
