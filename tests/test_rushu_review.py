"""Independent adversarial HTTP and state/lifecycle regression coverage."""
import http.client
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rushu.server import MAX_BODY, make_server
from rushu.kernel import MAX_INPUT, MAX_SOURCE


class NotebookReviewTests(unittest.TestCase):
    def setUp(self):
        self.static = tempfile.TemporaryDirectory()
        Path(self.static.name, "index.html").write_text("<!doctype html><title>如书测试</title>", encoding="utf-8")
        self.server = make_server(token="review-token-abcdefghijklmnop", static_dir=self.static.name)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.static.cleanup()

    def request(self, method, path, data=None, headers=None, authenticated=True):
        supplied = {"Origin": self.server.origin, "Content-Type": "application/json"}
        if authenticated:
            supplied["X-Rushu-Token"] = self.server.token
        supplied.update(headers or {})
        supplied = {key: value for key, value in supplied.items() if value is not None}
        body = None if data is None else json.dumps(data, ensure_ascii=True).encode("ascii")
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request(method, path, body=body, headers=supplied)
            response = connection.getresponse()
            result = response.read()
            content = json.loads(result) if result and response.getheader("Content-Type", "").startswith("application/json") else result
            return response.status, dict(response.getheaders()), content
        finally:
            connection.close()

    def raw(self, headers, path="/api/sessions", method="POST", body=b"{}"):
        wire = (f"{method} {path} HTTP/1.1\r\n" + "\r\n".join(headers) + "\r\n\r\n").encode("ascii") + body
        with socket.create_connection(self.server.server_address, timeout=5) as client:
            client.sendall(wire)
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                piece = client.recv(65536)
                if not piece:
                    break
                chunks.append(piece)
        response = b"".join(chunks)
        return int(response.split(b" ", 2)[1]), response

    def standard_headers(self):
        return [f"Host: {self.server.host}", f"Origin: {self.server.origin}",
                f"X-Rushu-Token: {self.server.token}", "Content-Type: application/json", "Content-Length: 2"]

    def create(self):
        status, _, session = self.request("POST", "/api/sessions", {})
        self.assertEqual(status, 201, session)
        self.assertEqual(session["state"], "idle")
        return session["id"]

    def execute(self, identifier, code, cell="review-cell"):
        status, _, result = self.request("POST", f"/api/sessions/{identifier}/execute", {"code": code, "cell_id": cell})
        self.assertEqual(status, 202, result)
        return result

    def wait(self, identifier, state="idle", after=0):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status, _, result = self.request("GET", f"/api/sessions/{identifier}/events?after={after}")
            self.assertEqual(status, 200, result)
            if result["state"] == state:
                return result
            if state != "dead":
                self.assertNotEqual(result["state"], "dead", result)
            time.sleep(0.01)
        self.fail(f"session did not enter {state}: {result}")

    def stdout(self, result):
        return "".join(event["text"] for event in result["events"] if event["type"] == "output" and event["stream"] == "stdout")

    def test_static_has_defensive_headers_and_no_token(self):
        status, headers, body = self.request("GET", "/", authenticated=False, headers={"Origin": None})
        self.assertEqual(status, 200)
        self.assertNotIn(self.server.token.encode(), body)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_head_has_no_response_body(self):
        status, headers, body = self.request("HEAD", "/", authenticated=False)
        self.assertEqual(status, 200)
        self.assertGreater(int(headers["Content-Length"]), 0)
        self.assertEqual(body, b"")

    def test_missing_or_wrong_token_cannot_create_session(self):
        for token in (None, "", "wrong", self.server.token + "x"):
            with self.subTest(token=token):
                status, _, _ = self.request("POST", "/api/sessions", {}, {"X-Rushu-Token": token})
                self.assertEqual(status, 401)
        self.assertEqual(len(self.server.sessions.sessions), 0)

    def test_origin_and_rebinding_host_are_rejected_even_with_token(self):
        for origin in (None, "null", "https://evil.example", self.server.origin + "/", self.server.origin + ".evil.example"):
            with self.subTest(origin=origin):
                self.assertEqual(self.request("POST", "/api/sessions", {}, {"Origin": origin})[0], 403)
        for host in ("evil.example", "localhost", "127.0.0.1", self.server.host + ".evil.example"):
            with self.subTest(host=host):
                self.assertEqual(self.request("POST", "/api/sessions", {}, {"Host": host})[0], 403)
        self.assertEqual(len(self.server.sessions.sessions), 0)

    def test_cross_origin_static_read_and_preflight_rejected(self):
        self.assertEqual(self.request("GET", "/", headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.request("OPTIONS", "/api/sessions", headers={"Origin": "http://evil.example"})[0], 403)
        for value in ("cross-site", "same-site"):
            self.assertEqual(self.request("GET", "/", headers={"Sec-Fetch-Site": value})[0], 403)

    def test_duplicate_security_and_framing_headers_rejected(self):
        for header in (f"Host: {self.server.host}", f"Origin: {self.server.origin}",
                       f"X-Rushu-Token: {self.server.token}", "Content-Length: 2", "Content-Type: application/json"):
            with self.subTest(header=header.split(":", 1)[0]):
                status, _ = self.raw(self.standard_headers() + [header])
                self.assertEqual(status, 400)
        self.assertEqual(len(self.server.sessions.sessions), 0)

    def test_invalid_body_and_framing_are_bounded(self):
        status, _ = self.raw(self.standard_headers() + ["Transfer-Encoding: chunked"])
        self.assertEqual(status, 400)
        for length in ("-1", "NaN", "1,2", str(MAX_BODY + 1)):
            headers = [line for line in self.standard_headers() if not line.startswith("Content-Length:")]
            status, _ = self.raw(headers + ["Content-Length: " + length])
            self.assertIn(status, (400, 413))
        self.assertEqual(self.request("POST", "/api/sessions", {}, {"Content-Type": "text/plain"})[0], 415)
        for data in ([], None, "not an object", {"bad": "\ud800"}):
            self.assertGreaterEqual(self.request("POST", "/api/sessions", data)[0], 400)

    def test_static_paths_and_query_tokens_cannot_read_files(self):
        for path in ("/README.md", "/../README.md", "/%2e%2e/README.md", "/rushu/server.py", "/.git/config", "/?token=" + self.server.token, "/index.html?token=" + self.server.token):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)

    def test_static_symlink_escape_is_rejected(self):
        target = Path(self.static.name, "app.js")
        try:
            target.symlink_to(ROOT / "README.md")
        except (NotImplementedError, OSError):
            self.skipTest("OS does not permit test symlinks")
        self.assertEqual(self.request("GET", "/app.js")[0], 404)

    def test_request_target_ambiguity_is_rejected(self):
        for path in (self.server.origin + "/api/sessions", "/api/sessions#fragment", "//evil.example/api/sessions"):
            self.assertIn(self.raw(self.standard_headers(), path=path)[0], (400, 405))
        self.assertEqual(len(self.server.sessions.sessions), 0)

    def test_execution_preserves_state_and_checked_streams(self):
        identifier = self.create()
        self.execute(identifier, "值 取 41. 应 取 显出 其 写 内容:'甲'.")
        first = self.wait(identifier)
        self.assertEqual(self.stdout(first), "甲")
        self.execute(identifier, "值 取 值+1. 应 取 错误 其 写 内容:'诊断'. 值.")
        second = self.wait(identifier, after=first["cursor"])
        self.assertEqual(self.stdout(second), "42\n")
        self.assertTrue(any(e.get("stream") == "stderr" and e["text"] == "诊断" for e in second["events"]))
        self.assertEqual(second["execution_count"], 2)

    def test_input_replay_rejected_and_multiline_checked_reader_works(self):
        identifier = self.create()
        self.execute(identifier, "显 读. 显 (读取 其 读) 其 值.")
        pending = self.wait(identifier, "waiting_input")
        body = {"request_id": pending["request_id"], "text": "甲\n乙"}
        self.assertEqual(self.request("POST", f"/api/sessions/{identifier}/input", body)[0], 200)
        result = self.wait(identifier)
        self.assertEqual(self.stdout(result), "甲\n乙\n")
        self.assertEqual(self.request("POST", f"/api/sessions/{identifier}/input", body)[0], 409)

    def test_stop_during_input_invalidates_old_request_and_state(self):
        identifier = self.create()
        self.execute(identifier, "值 取 5. 显 读.")
        pending = self.wait(identifier, "waiting_input")
        status, _, reset = self.request("POST", f"/api/sessions/{identifier}/stop", {})
        self.assertEqual(status, 200)
        self.assertGreater(reset["generation"], pending["generation"])
        self.assertEqual(reset["execution_count"], 0)
        self.assertEqual(self.request("POST", f"/api/sessions/{identifier}/input", {"request_id": pending["request_id"], "text": "late"})[0], 409)
        self.execute(identifier, "显 值.")
        result = self.wait(identifier, after=reset["cursor"])
        self.assertTrue(any(event["type"] == "error" and "未定义" in event["message"] for event in result["events"]))
        self.assertTrue(all(event["generation"] == reset["generation"] for event in result["events"]))

    def test_infinite_run_can_stop_and_busy_run_is_not_queued(self):
        identifier = self.create()
        self.execute(identifier, "循 环")
        duplicate = self.request("POST", f"/api/sessions/{identifier}/execute", {"code": "显 99.", "cell_id": "late"})
        self.assertEqual(duplicate[0], 409)
        start = time.monotonic()
        status, _, reset = self.request("POST", f"/api/sessions/{identifier}/stop", {})
        self.assertEqual(status, 200)
        self.assertLess(time.monotonic() - start, 5)
        self.execute(identifier, "显 7.")
        result = self.wait(identifier, after=reset["cursor"])
        self.assertEqual(self.stdout(result), "7\n")

    def test_source_and_input_limits_reject_without_consuming_state(self):
        identifier = self.create()
        self.assertEqual(self.request("POST", f"/api/sessions/{identifier}/execute", {"code": "a" * (MAX_SOURCE + 1), "cell_id": "x"})[0], 400)
        self.execute(identifier, "显 读.")
        pending = self.wait(identifier, "waiting_input")
        self.assertEqual(self.request("POST", f"/api/sessions/{identifier}/input", {"request_id": pending["request_id"], "text": "a" * (MAX_INPUT + 1)})[0], 400)
        self.assertEqual(self.wait(identifier, "waiting_input")["request_id"], pending["request_id"])

    def test_generation_document_not_executed(self):
        identifier = self.create()
        self.execute(identifier, "显 '不该执行'.\n如是我言\n")
        result = self.wait(identifier)
        self.assertEqual(self.stdout(result), "")
        self.assertTrue(any(event.get("category") == "生成入口错误" for event in result["events"]))

    def test_events_require_token_and_strict_cursor(self):
        identifier = self.create()
        base = f"/api/sessions/{identifier}/events"
        self.assertEqual(self.request("GET", base, authenticated=False)[0], 401)
        for suffix in ("?after=-1", "?after=0&after=1", "?after=0&x=1", "?after=999999", "?after="):
            self.assertEqual(self.request("GET", base + suffix)[0], 400)

    def test_delete_removes_session_and_worker(self):
        identifier = self.create()
        process = self.server.sessions.get(identifier).process
        self.assertTrue(process.is_alive())
        self.assertEqual(self.request("DELETE", f"/api/sessions/{identifier}", {})[0], 200)
        self.assertEqual(self.request("GET", f"/api/sessions/{identifier}/events")[0], 404)
        with self.assertRaises(ValueError):
            process.is_alive()  # joined and closed, not merely forgotten


if __name__ == "__main__":
    unittest.main()
