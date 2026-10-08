"""Requests already in flight must not start code after a notebook reset."""
import http.client
import json
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rushu.server import make_server


class GenerationGuardTests(unittest.TestCase):
    def setUp(self):
        self.server = make_server()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, path, body):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request("POST", path, json.dumps(body),
                {"X-Rushu-Token": self.server.token, "Origin": self.server.origin,
                 "Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_api_rejects_execute_issued_before_stop_or_restart(self):
        for operation in ("stop", "restart"):
            with self.subTest(operation=operation):
                status, before = self.request("/api/sessions", {})
                self.assertEqual(status, 201)
                path = "/api/sessions/" + before["id"]
                status, after = self.request(path + "/" + operation, {})
                self.assertEqual(status, 200)
                self.assertGreater(after["generation"], before["generation"])
                status, error = self.request(path + "/execute", {
                    "code": "循 环", "cell_id": "delayed", "expected_generation": before["generation"]})
                self.assertEqual(status, 409, error)
                session = self.server.sessions.get(before["id"])
                snapshot = session.snapshot()
                self.assertEqual(snapshot["state"], "idle")
                self.assertEqual(snapshot["execution_count"], 0)
                self.assertEqual(snapshot["cursor"], after["cursor"])
                status, current = self.request(path + "/execute", {
                    "code": "显 42.", "cell_id": "current", "expected_generation": after["generation"]})
                self.assertEqual(status, 202, current)
                self.assertEqual(current["execution_count"], 1)


if __name__ == "__main__":
    unittest.main()
