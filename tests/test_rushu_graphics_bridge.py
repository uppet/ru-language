"""Graphics transport identity, lifecycle, quotas and bounded scene history."""
from collections import deque
from pathlib import Path
import sys
import http.client
import json
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rushu.kernel import GRAPHICS_TIMEOUT, KernelError, MAX_EVENT_TEXT, Session, _Input
from rushu.server import SESSION_PATH, STATIC_FILES, make_server


class GraphicsBridgeTests(unittest.TestCase):
    def setUp(self):
        # Isolate protocol validation from process startup and language semantics.
        with patch.object(Session, "_start"):
            self.session = Session()
        self.session.connection = Mock()
        self.addCleanup(self.session._cancel_graphics_timer)
        self.session.cell_id = "cell"
        self.session.execution_count = 1
        self.scene = {"type": "graphics", "canvas_id": "canvas", "width": 400,
                      "height": 300, "fps": 30, "running": True,
                      "handlers": ["frame", "mouse_down", "key_down"], "commands": []}
        self.session._accept_graphics(self.scene)

    def send(self, event=None, **identity):
        args = dict(canvas_id="canvas", cell_id="cell", execution_count=1,
                    expected_generation=1, event=event or {"type": "frame"})
        args.update(identity)
        return self.session.dispatch_graphics(**args)

    def test_exact_execution_identity(self):
        for identity in ({"canvas_id": "old"}, {"cell_id": "old"},
                         {"execution_count": 2}, {"expected_generation": 2}):
            with self.assertRaises(KernelError) as caught:
                self.send(**identity)
            self.assertEqual(caught.exception.status, 409)
        self.assertFalse(self.session.connection.send.called)
        result = self.send()
        self.assertEqual(result["state"], "idle")
        self.assertTrue(result["graphics_busy"])
        self.assertEqual(self.session.execution_count, 1)
        with self.assertRaises(KernelError):
            self.send()
        with self.assertRaises(KernelError):
            self.session.execute("显 1.", "next")

    def test_payload_and_enabled_handler_validation(self):
        for event in ({"type": "bogus"}, {"type": []},
                      {"type": "mouse_down", "x": 10 ** 1000, "y": 1}, {"type": "mouse_down", "x": float("nan"), "y": 1},
                      {"type": "mouse_down", "x": 1, "y": 2, "button": True},
                      {"type": "mouse_down", "x": 100001, "y": 2},
                      {"type": "key_down", "key": "x" * 65},
                      {"type": "frame", "code": "anything"}):
            with self.assertRaises(KernelError) as caught:
                self.send(event)
            self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(KernelError):
            self.send({"type": "key_up", "key": "a"})
        self.session.graphics["running"] = False
        with self.assertRaises(KernelError):
            self.send()
        self.send({"type": "close"})

    def test_rate_limit_and_close_escape(self):
        with patch("rushu.kernel.time.monotonic", return_value=100):
            self.send()
            self.session.graphics_busy = False
            with self.assertRaises(KernelError) as caught:
                self.send()
            self.assertEqual(caught.exception.status, 429)
            self.session.graphics_times = deque([100] * 30)
            with self.assertRaises(KernelError) as caught:
                self.send({"type": "key_down", "key": "a"})
            self.assertEqual(caught.exception.status, 429)
            self.send({"type": "close"})

    def test_history_coalesces_without_false_truncation(self):
        for index in range(1000):
            self.session._append(dict(self.scene, commands=[{"op": "text", "text": "画" * 2000}]))
            self.session._append({"type": "graphics_done", "canvas_id": "canvas", "status": "ok"})
        result = self.session.poll()
        self.assertEqual(len(result["events"]), 2)
        self.assertFalse(result["truncated"])
        self.assertLess(self.session.event_text, MAX_EVENT_TEXT)
        self.assertEqual(self.session.event_text,
                         sum(self.session._event_size(event) for event in self.session.events))
        for index in range(1000):
            self.session._append({"type": "output", "text": "a" * 20000})
        self.assertTrue(self.session.poll()["truncated"])
        self.assertLessEqual(self.session.event_text, MAX_EVENT_TEXT)

    def test_command_payload_boundaries(self):
        for scene in (dict(self.scene, commands=[{"op": "eval"}]),
                      dict(self.scene, commands=[{"op": "rect"}] * 2049),
                      dict(self.scene, commands=[{"op": "text", "text": "x" * 262144}])):
            with self.assertRaises(ValueError):
                self.session._accept_graphics(scene)

    def test_new_execution_detaches_old_canvas(self):
        result = self.session.execute("显 1.", "next", 1)
        self.assertIsNone(result["graphics"])
        with self.assertRaises(KernelError):
            self.send({"type": "close"})

    def test_close_during_callback_is_single_pending_request(self):
        self.send()
        timer = self.session.graphics_timer
        for _ in range(3):
            result = self.send({"type": "close"})
            self.assertTrue(result["graphics_close_pending"])
            self.assertTrue(result["graphics_busy"])
            self.assertIs(self.session.graphics_timer, timer)
        self.assertEqual(self.session.connection.send.call_count, 1)
        with self.assertRaises(KernelError):
            self.send({"type": "key_down", "key": "a"})

    def test_frame_rate_respects_canvas_fps(self):
        self.session.graphics["fps"] = 10
        with patch("rushu.kernel.time.monotonic", return_value=100):
            self.send()
        self.session.graphics_busy = False
        with patch("rushu.kernel.time.monotonic", return_value=100.05):
            with self.assertRaises(KernelError) as caught:
                self.send()
            self.assertEqual(caught.exception.status, 429)

    def test_callback_input_is_rejected_without_waiting(self):
        connection = Mock()
        stream = _Input(connection)
        stream.graphics_callback = True
        with self.assertRaisesRegex(OSError, "如观回调不能请求交互输入"):
            stream.readline()
        connection.recv.assert_not_called()
        connection.send.assert_not_called()

    def test_watchdog_resets_only_matching_inflight_callback(self):
        self.send()
        token = self.session.graphics_token
        with patch.object(self.session, "_terminate"), patch.object(self.session, "_start"):
            self.session._graphics_timeout("old", 1, "canvas")
            self.assertEqual(self.session.generation, 1)
            self.session._graphics_timeout(token, 0, "canvas")
            self.assertEqual(self.session.generation, 1)
            self.session._graphics_timeout(token, 1, "canvas")
        self.assertEqual(self.session.generation, 2)
        self.assertEqual(self.session.execution_count, 0)
        self.assertFalse(self.session.graphics_busy)
        self.assertIsNone(self.session.graphics)
        events = self.session.poll()["events"]
        self.assertTrue(any("上下文已清空" in event.get("message", "") for event in events))
        self.assertEqual(events[-1]["reason"], "graphics_timeout")
        self.assertIsNone(self.session.graphics_timer)

    def test_route_and_static_allowlist(self):
        self.assertIsNotNone(SESSION_PATH.fullmatch("/api/sessions/" + "a" * 32 + "/graphics"))
        self.assertEqual(STATIC_FILES["/scene.mjs"][1], "text/javascript; charset=utf-8")


def _blocking_graphics_worker(connection):
    """Real spawned process simulating a callback blocked in an OS call."""
    connection.recv()
    connection.send({"type": "graphics", "canvas_id": "blocking", "width": 10,
                     "height": 10, "fps": 30, "running": True,
                     "handlers": ["frame"], "commands": []})
    connection.send({"type": "done", "status": "ok"})
    connection.recv()
    time.sleep(60)


class SpawnedGraphicsBridgeTests(unittest.TestCase):
    def wait_ready(self, session, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = session.poll()
            if result["state"] == "idle" and not result["graphics_busy"]:
                return result
            if result["state"] == "dead":
                self.fail(str(result))
            time.sleep(.01)
        self.fail("graphics callback did not complete: " + str(session.poll()))

    def test_actual_ru_callback_lifecycle_and_session_state(self):
        session = Session()
        self.addCleanup(session.close)
        session.execute("观 取 外言 '如:观'. 布 取 观 其 画布 400 300. 值 取 7. "
                        "作 绘 帧: 布 其 背景 '#ffffff'. 布 其 矩形 帧 20 30 40. 为 "
                        "布 其 每帧 作 绘.", "scene")
        result = self.wait_ready(session)
        canvas = result["graphics"]["canvas_id"]
        for frame in (1, 2):
            time.sleep(.04)
            session.dispatch_graphics(canvas, "scene", 1, 1, {"type": "frame"})
            result = self.wait_ready(session)
            scene = [event for event in result["events"] if event["type"] == "graphics"][-1]
            self.assertEqual(scene["commands"][-1]["x"], frame)
            self.assertEqual(result["execution_count"], 1)
            self.assertEqual(result["generation"], 1)
        session.dispatch_graphics(canvas, "scene", 1, 1, {"type": "close"})
        self.assertIsNone(self.wait_ready(session)["graphics"])
        session.execute("显 值.", "next")
        result = self.wait_ready(session)
        self.assertEqual([e["text"] for e in result["events"] if e["type"] == "output"], ["7\n"])
        with self.assertRaises(KernelError):
            session.dispatch_graphics(canvas, "scene", 1, 1, {"type": "close"})

    def test_close_racing_real_callback(self):
        session = Session()
        self.addCleanup(session.close)
        session.execute("观 取 外言 '如:观'. 布 取 观 其 画布 10 10. "
                        "作 绘 帧: 布 其 矩形 帧 1 2 3. 为 布 其 每帧 作 绘.", "scene")
        canvas = self.wait_ready(session)["graphics"]["canvas_id"]
        # Hold ingestion so close deterministically races an in-flight callback.
        with session.lock:
            session.dispatch_graphics(canvas, "scene", 1, 1, {"type": "frame"})
            pending = session.dispatch_graphics(canvas, "scene", 1, 1, {"type": "close"})
            self.assertTrue(pending["graphics_close_pending"])
        result = self.wait_ready(session)
        self.assertIsNone(result["graphics"])
        self.assertFalse(result["graphics_close_pending"])
        self.assertEqual(result["generation"], 1)
        self.assertTrue(any(e["type"] == "graphics_closed" for e in result["events"]))

    def test_callback_input_cannot_block_session(self):
        session = Session()
        self.addCleanup(session.close)
        session.execute("观 取 外言 '如:观'. 布 取 观 其 画布 10 10. "
                        "作 绘 帧: 显 读. 为 布 其 每帧 作 绘.", "scene")
        canvas = self.wait_ready(session)["graphics"]["canvas_id"]
        session.dispatch_graphics(canvas, "scene", 1, 1, {"type": "frame"})
        result = self.wait_ready(session)
        self.assertIsNone(result["graphics"])
        self.assertFalse(any(e["type"] == "input_request" for e in result["events"]))
        self.assertEqual(result["generation"], 1)
        self.assertTrue(any("如观回调不能请求交互输入" in e.get("message", "") for e in result["events"]))

    def test_hard_watchdog_kills_blocked_worker_and_restarts(self):
        with patch("rushu.kernel._worker", _blocking_graphics_worker):
            session = Session()
        self.addCleanup(session.close)
        session.execute("", "scene")
        self.wait_ready(session)
        old_pid = session.process.pid
        started = time.monotonic()
        session.dispatch_graphics("blocking", "scene", 1, 1, {"type": "frame"})
        result = self.wait_ready(session, timeout=GRAPHICS_TIMEOUT + 8)
        self.assertEqual(result["generation"], 2)
        self.assertEqual(result["execution_count"], 0)
        self.assertNotEqual(session.process.pid, old_pid)
        self.assertGreaterEqual(time.monotonic() - started, GRAPHICS_TIMEOUT)
        self.assertTrue(any("超过 10 秒" in e.get("message", "") for e in result["events"]))
        self.assertIsNone(result["graphics"])
        session.execute("显 42.", "recovered", 2)
        result = self.wait_ready(session)
        self.assertTrue(any(e.get("text") == "42\n" for e in result["events"]))


    def test_stop_blocked_callback_before_watchdog_and_recover(self):
        with patch("rushu.kernel._worker", _blocking_graphics_worker):
            session = Session()
        self.addCleanup(session.close)
        session.execute("", "scene")
        self.wait_ready(session)
        session.dispatch_graphics("blocking", "scene", 1, 1, {"type": "frame"})
        started = time.monotonic()
        session.reset("stop")
        self.assertLess(time.monotonic() - started, GRAPHICS_TIMEOUT)
        self.assertIsNone(session.graphics_timer)
        session.execute("显 42.", "recovered", 2)
        result = self.wait_ready(session)
        self.assertEqual(result["generation"], 2)
        self.assertTrue(any(e.get("text") == "42\n" for e in result["events"]))


class GraphicsHTTPTests(unittest.TestCase):
    def setUp(self):
        self.server = make_server(token="graphics-test-abcdefghijklmnop")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, path, data=None, method="POST", **headers):
        values = {"Origin": self.server.origin, "X-Rushu-Token": self.server.token,
                  "Content-Type": "application/json"}
        values.update(headers)
        values = {key: value for key, value in values.items() if value is not None}
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request(method, path, body=None if data is None else json.dumps(data), headers=values)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def wait_ready(self, identifier):
        for _ in range(500):
            status, result = self.request(f"/api/sessions/{identifier}/events", method="GET")
            self.assertEqual(status, 200)
            if result["state"] == "idle" and not result["graphics_busy"]:
                return result
            self.assertNotEqual(result["state"], "dead", result)
            time.sleep(.01)
        self.fail("HTTP graphics did not finish")

    def canvas(self):
        status, result = self.request("/api/sessions", {})
        self.assertEqual(status, 201)
        identifier = result["id"]
        code = ("观 取 外言 '如:观'. 布 取 观 其 画布 20 20. "
                "作 点击 横 纵 键: 布 其 矩形 横 纵 2 3. 为 布 其 鼠标按下 作 点击.")
        self.assertEqual(self.request(f"/api/sessions/{identifier}/execute",
                                     {"code": code, "cell_id": "scene"})[0], 202)
        result = self.wait_ready(identifier)
        payload = {"canvas_id": result["graphics"]["canvas_id"], "cell_id": "scene",
                   "execution_count": 1, "expected_generation": 1,
                   "event": {"type": "mouse_down", "x": 3, "y": 4}}
        return identifier, payload

    def test_graphics_route_requires_token_and_same_origin(self):
        identifier, payload = self.canvas()
        path = f"/api/sessions/{identifier}/graphics"
        for token in (None, "bad-token"):
            self.assertEqual(self.request(path, **{"X-Rushu-Token": token})[0], 401)
        for origin in (None, "null", "https://evil.example"):
            self.assertEqual(self.request(path, Origin=origin)[0], 403)
        self.assertEqual(self.request(path, **{"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.request(path, Host="evil.example")[0], 403)
        self.assertIsNotNone(self.wait_ready(identifier)["graphics"])

    def test_graphics_malicious_payloads_are_rejected_without_crash(self):
        identifier, payload = self.canvas()
        path = f"/api/sessions/{identifier}/graphics"
        for event in ({"type": []}, {"type": "mouse_down", "x": 10 ** 1000, "y": 0},
                      {"type": "mouse_down", "x": float("nan"), "y": 0},
                      {"type": "mouse_down", "x": 1, "y": 1, "button": True},
                      {"type": "mouse_down", "x": 1, "y": 1, "code": "bad"}):
            self.assertEqual(self.request(path, dict(payload, event=event))[0], 400)
        for field in ("canvas_id", "cell_id", "execution_count", "expected_generation"):
            incomplete = dict(payload)
            del incomplete[field]
            self.assertEqual(self.request(path, incomplete)[0], 400)
        self.assertIsNotNone(self.wait_ready(identifier)["graphics"])

    def test_cross_session_and_stale_identity_rejected_valid_mouse_defaults_button(self):
        identifier, payload = self.canvas()
        other, other_payload = self.canvas()
        path = f"/api/sessions/{identifier}/graphics"
        self.assertEqual(self.request(f"/api/sessions/{other}/graphics", payload)[0], 409)
        self.assertEqual(self.request(path, dict(payload, expected_generation=2))[0], 409)
        self.assertEqual(self.request(path, payload)[0], 202)
        result = self.wait_ready(identifier)
        self.assertIsNotNone(result["graphics"])
        frame = [e for e in result["events"] if e["type"] == "graphics"][-1]
        self.assertEqual(frame["commands"][-1]["x"], 3)
        self.assertEqual(self.request(f"/api/sessions/{identifier}/execute",
                                     {"code": "显 1.", "cell_id": "new"})[0], 202)
        self.wait_ready(identifier)
        self.assertEqual(self.request(path, payload)[0], 409)
        self.assertIsNotNone(self.wait_ready(other)["graphics"])


if __name__ == "__main__":
    unittest.main()
