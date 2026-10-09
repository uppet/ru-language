"""Explicit notebook generation uses fake providers only, never live APIs."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import io
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from rulang import __version__
from rulang.generation import (DEFAULT_TIMEOUT, GenerationConfig, GenerationError,
                               LOCAL_TEST_API_KEY)
from rushu import generation
from rushu.kernel import KernelError
from rushu.server import main, make_server

ROOT = Path(__file__).resolve().parents[1]
CONFIG = GenerationConfig("private-secret", "https://provider.example/secret-path", "secret-model")
PROMPT = "请显示数字四十二。\n如是我言"


class GenerationTimeoutOptionsTests(unittest.TestCase):
    def test_server_default_and_custom_generation_timeout(self):
        self.assertEqual(DEFAULT_TIMEOUT, 1800)
        for options, expected in (({}, 1800), ({"generation_timeout": 3600}, 3600),
                                  ({"generation_timeout": .125}, .125)):
            with self.subTest(options=options):
                server = make_server(**options)
                try:
                    self.assertEqual(server.generation_timeout, expected)
                finally:
                    server.server_close()

    def test_invalid_timeout_rejected_before_creating_server_or_worker(self):
        for value in (0, -1, float("nan"), float("inf"), -float("inf"), True, None, "3600"):
            with self.subTest(value=value), \
                 patch.object(generation, "request_response") as provider, \
                 patch("rushu.server.SessionManager") as sessions:
                with self.assertRaisesRegex(ValueError, "有限且大于 0"):
                    make_server(generation_timeout=value)
                with self.assertRaisesRegex(ValueError, "有限且大于 0"):
                    generation.generate_source({"prompt": PROMPT}, timeout=value)
                sessions.assert_not_called()
                provider.assert_not_called()

    def test_startup_option_reaches_server(self):
        for options, expected in (([], 1800), (["--generation-timeout", "3600"], 3600),
                                  (["--generation-timeout", "0.25"], .25)):
            with self.subTest(options=options), \
                 patch("rushu.server.make_server") as create, \
                 patch("rushu.server.signal.signal"), \
                 patch("rushu.server.sys.stdout", new_callable=io.StringIO):
                create.return_value.url = "http://127.0.0.1:1234/#token=test"
                create.return_value.serve_forever.side_effect = KeyboardInterrupt
                self.assertEqual(main(["--no-browser", *options]), 0)
                create.assert_called_once_with(0, generation_timeout=expected)
                create.return_value.server_close.assert_called_once_with()

    def test_startup_rejects_nonpositive_and_nonfinite_timeout(self):
        for value in ("0", "-1", "nan", "inf", "-inf", "1e999", "invalid"):
            with self.subTest(value=value), \
                 patch("rushu.server.make_server") as create, \
                 patch("rushu.server.sys.stdout", new_callable=io.StringIO), \
                 patch("rushu.server.sys.stderr", new_callable=io.StringIO) as errors:
                with self.assertRaises(SystemExit) as caught:
                    main(["--no-browser", "--generation-timeout=" + value])
                self.assertEqual(caught.exception.code, 2)
                self.assertIn("error:", errors.getvalue())
                create.assert_not_called()

    def test_frontend_leaves_generation_deadline_to_server(self):
        source = (ROOT / "rushu/static/app.js").read_text(encoding="utf-8")
        flow = source.split("async function generateCell(cell){", 1)[1].split("function buildHistory", 1)[0]
        self.assertIn("fetch('/api/generate'", flow)
        self.assertNotIn("setTimeout", flow)
        self.assertNotIn("request.timer", source)
        # Manual cancellation is still wired to the generation fetch signal.
        self.assertIn("pending.controller.abort()", source)
        self.assertIn("signal:request.controller.signal", flow)


class SourceGenerationTests(unittest.TestCase):
    def setUp(self):
        self.server = make_server()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.config = patch.object(generation, "load_config", return_value=CONFIG)
        self.config.start()

    def tearDown(self):
        self.config.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def request(self, path, body=None, method=None, authenticated=True, origin=None):
        headers = {"Content-Type": "application/json", "Origin": origin or self.server.origin}
        if authenticated:
            headers["X-Rushu-Token"] = self.server.token
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request(method or ("POST" if body is not None else "GET"), path,
                               None if body is None else json.dumps(body), headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_history_module_is_served_as_javascript(self):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            # Static modules need the correct Host, but no bearer token.
            connection.request("GET", "/history.mjs")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), "text/javascript; charset=utf-8")
            self.assertEqual(response.read(), (ROOT / "rushu/static/history.mjs").read_bytes())
            connection.close()
            connection.request("GET", "/app.js")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn("./history.mjs", response.read().decode("utf-8"))
        finally:
            connection.close()

    def test_config_is_authenticated_and_displays_only_host(self):
        status, value = self.request("/api/generation/config")
        self.assertEqual(status, 200)
        self.assertEqual(value["provider_host"], "provider.example")
        self.assertTrue(value["configured"])
        for secret in ("private-secret", "secret-path", "secret-model"):
            self.assertNotIn(secret, json.dumps(value))
        self.assertEqual(self.request("/api/generation/config", authenticated=False)[0], 401)
        with patch.object(generation, "load_config", side_effect=GenerationError("private-secret")):
            status, value = self.request("/api/generation/config")
            self.assertFalse(value["configured"])
            self.assertIn("RU_LLM_API_KEY", value["message"])
            self.assertNotIn("private-secret", json.dumps(value))

    def test_security_and_input_rejected_before_provider(self):
        with patch.object(generation, "request_response") as provider:
            self.assertEqual(self.request("/api/generate", method="POST", authenticated=False)[0], 401)
            self.assertEqual(self.request("/api/generate", method="POST", origin="https://evil.example")[0], 403)
            self.assertEqual(self.request("/api/generate")[0], 405)
            self.assertEqual(self.request("/api/generate?x=1", {"prompt": PROMPT})[0], 400)
            for body in ({}, {"prompt": None}, {"prompt": "如是我言"},
                         {"prompt": "显 '没有结束\n如是我言"}, {"prompt": "内容\n如是我言 后文"},
                         {"prompt": PROMPT, "draft": []}, {"prompt": PROMPT, "session_id": "unused"}):
                self.assertEqual(self.request("/api/generate", body)[0], 400, body)
            self.assertEqual(self.request("/api/generate", {"prompt": "x" * 200001})[0], 413)
            self.assertEqual(self.request("/api/generate", {"prompt": PROMPT, "draft": "x" * 200001})[0], 413)
            # Oversized framing is rejected before reading any body. Sending
            # the whole body races the server's deliberate connection close.
            connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
            try:
                connection.putrequest("POST", "/api/generate")
                connection.putheader("X-Rushu-Token", self.server.token)
                connection.putheader("Origin", self.server.origin)
                connection.putheader("Content-Type", "application/json")
                connection.putheader("Content-Length", "1048577")
                connection.endheaders()
                response = connection.getresponse()
                self.assertEqual(response.status, 413)
                self.assertIn("error", json.loads(response.read()))
            finally:
                connection.close()
            provider.assert_not_called()

    def test_only_chosen_text_sent_without_execution_or_import_loading(self):
        code = "模 取 外言 '/must/not/be/read.ru'. 显 'not executed'."
        with patch.object(generation, "request_response", return_value=code) as provider, \
             patch("rulang.modules.load_module_graph", side_effect=AssertionError("loaded imports")), \
             patch.object(self.server.sessions, "create", side_effect=AssertionError("created session")):
            status, value = self.request("/api/generate", {"prompt": PROMPT, "draft": "显 1."})
        self.assertEqual(status, 200, value)
        self.assertTrue(value["valid"])
        self.assertEqual(value["source"], code + "\n")
        selected = provider.call_args.args[1]
        self.assertIn("请显示数字四十二", selected)
        self.assertIn("显 1.", selected)
        self.assertNotIn("如是我言", selected)
        self.assertEqual(provider.call_args.kwargs, {"timeout": DEFAULT_TIMEOUT})

    def test_configured_timeout_reaches_provider_and_worker_wait(self):
        for timeout in (1800, 3600, .125):
            self.server.generation_timeout = timeout
            finished = threading.Event()
            with self.subTest(timeout=timeout), \
                 patch.object(generation, "threading", wraps=threading) as threads, \
                 patch.object(finished, "wait", wraps=finished.wait) as wait, \
                 patch.object(generation, "request_response", return_value="显 42.") as provider:
                threads.Event.return_value = finished
                status, value = self.request("/api/generate", {"prompt": PROMPT})
                self.assertEqual(status, 200, value)
                self.assertEqual(provider.call_args.kwargs, {"timeout": timeout})
                wait.assert_called_once_with(timeout)

    def test_current_maps_and_facts_are_generated_but_not_executed(self):
        code = "资料 取 典: '就绪' 对 真. '缺失' 对 假. 成. 显 资料['就绪']. 显 非 假."
        with patch.object(generation, "request_response", return_value=code), \
             patch.object(self.server.sessions, "create", side_effect=AssertionError("executed")):
            status, value = self.request("/api/generate", {"prompt": "创建含真与假的典。\n如是我言"})
        self.assertEqual(status, 200, value)
        self.assertTrue(value["valid"])
        self.assertEqual(value["source"], code + "\n")
        # Deliberately execute only here, outside the generation API, to check
        # this educational fixture against the current language semantics.
        import io
        from rulang.interpreter import Interpreter
        from rulang.frontend import parse
        output = io.StringIO()
        Interpreter(stdout=output).execute(parse(value["source"]))
        self.assertEqual(output.getvalue(), "真\n真\n")

    def test_invalid_source_has_safe_validation_without_source_echo(self):
        with patch.object(generation, "request_response", return_value="显 'private source"):
            status, value = self.request("/api/generate", {"prompt": PROMPT})
        self.assertEqual(status, 200)
        self.assertFalse(value["valid"])
        self.assertNotIn("private source", json.dumps(value["validation"]))
        self.assertIn("line", value["validation"])

    def test_errors_and_secret_outputs_are_sanitized_and_release_slot(self):
        for outcome in (GenerationError("private-secret raw error"), RuntimeError("private-secret"),
                        "显 'private-secret'.", "x" * 200001, "如是我言"):
            with self.subTest(outcome=type(outcome).__name__), patch.object(generation, "request_response") as provider:
                if isinstance(outcome, Exception):
                    provider.side_effect = outcome
                else:
                    provider.return_value = outcome
                status, value = self.request("/api/generate", {"prompt": PROMPT})
                self.assertEqual(status, 502)
                self.assertNotIn("private-secret", json.dumps(value))
        with patch.object(generation, "request_response", return_value="显 42."):
            self.assertEqual(self.request("/api/generate", {"prompt": PROMPT})[0], 200)

    def test_provider_diagnostics_allowlist_categories_without_secret_text(self):
        cases = (("tls_certificate", None, "TLS 证书验证失败"),
                 ("tls", None, "TLS 安全连接失败"),
                 ("timeout", None, "超时"),
                 ("connection", None, "连接失败"),
                 ("response_interrupted", None, "传输中断"),
                 ("http", 429, "HTTP 429"),
                 ("http", "private-secret", "HTTP 错误"),
                 ("private-secret", None, "生成请求失败"))
        for code, status, expected in cases:
            error = GenerationError("private-secret raw response body", code=code, status=status)
            with self.subTest(code=code, status=status), \
                 patch.object(generation, "request_response", side_effect=error) as provider:
                response_status, value = self.request("/api/generate", {"prompt": PROMPT})
                self.assertEqual(response_status, 502)
                self.assertIn(expected, value["error"])
                self.assertIn("未自动重试", value["error"])
                self.assertNotIn("private-secret", json.dumps(value))
                self.assertNotIn("raw response body", json.dumps(value))
                provider.assert_called_once()

    def test_global_busy_guard_survives_response_timeout(self):
        entered, release, exited = threading.Event(), threading.Event(), threading.Event()
        def blocked(*args, **kwargs):
            entered.set()
            release.wait(5)
            exited.set()
            return "显 42."
        self.server.generation_timeout = .1
        with patch.object(generation, "request_response", side_effect=blocked) as provider:
            try:
                self.assertEqual(self.request("/api/generate", {"prompt": PROMPT})[0], 504)
                self.assertTrue(entered.is_set())
                # Direct helper is shared by all NotebookServer instances.
                with self.assertRaises(KernelError) as caught:
                    generation.generate_source({"prompt": PROMPT})
                self.assertEqual(caught.exception.status, 429)
                self.assertEqual(provider.call_count, 1)
                self.assertEqual(provider.call_args.kwargs, {"timeout": .1})
            finally:
                release.set()
                self.assertTrue(exited.wait(5))
                # Wait for the worker's finally block, not an arbitrary sleep.
                self.assertTrue(generation._GENERATION_SLOT.acquire(timeout=5))
                generation._GENERATION_SLOT.release()

    def test_os_wait_timeout_range_error_is_safe_and_keeps_busy_guard(self):
        entered, release, exited, finished = (threading.Event() for _ in range(4))

        def blocked(*args, **kwargs):
            entered.set()
            release.wait(5)
            exited.set()
            return "显 42."

        with patch.object(generation, "threading", wraps=threading) as threads, \
             patch.object(finished, "wait", side_effect=OverflowError("private-secret")), \
             patch.object(generation, "request_response", side_effect=blocked) as provider:
            threads.Event.return_value = finished
            try:
                status, value = self.request("/api/generate", {"prompt": PROMPT})
                self.assertEqual(status, 502)
                self.assertIn("当前系统无法使用该超时数值", value["error"])
                self.assertNotIn("private-secret", value["error"])
                self.assertTrue(entered.wait(5))
                with self.assertRaises(KernelError) as caught:
                    generation.generate_source({"prompt": PROMPT})
                self.assertEqual(caught.exception.status, 429)
                provider.assert_called_once()
            finally:
                release.set()
                self.assertTrue(exited.wait(5))
                self.assertTrue(generation._GENERATION_SLOT.acquire(timeout=5))
                generation._GENERATION_SLOT.release()

    def test_real_request_to_local_fake_preserves_spec_hash_and_caps(self):
        captured = []
        class Fake(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                captured.append((self.path, self.headers.get("Authorization"),
                                 json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                raw = json.dumps({"status": "completed", "output_text": "显 42."}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        thread = threading.Thread(target=fake.serve_forever, daemon=True)
        thread.start()
        try:
            config = GenerationConfig(LOCAL_TEST_API_KEY, "http://127.0.0.1:" + str(fake.server_port) + "/v1")
            with patch.object(generation, "load_config", return_value=config):
                status, value = self.request("/api/generate", {"prompt": PROMPT})
            self.assertEqual(status, 200, value)
            path, authorization, payload = captured[0]
            self.assertEqual(path, "/v1/responses")
            self.assertEqual(authorization, "Bearer " + LOCAL_TEST_API_KEY)
            self.assertEqual(payload["max_output_tokens"], 16384)
            self.assertEqual(payload["tools"], [])
            self.assertEqual(payload["tool_choice"], "none")
            self.assertIs(payload["store"], False)
            specification = (ROOT / "rulang/language-spec.md").read_bytes()
            system = payload["input"][0]["content"][0]["text"]
            self.assertIn(specification.decode(), system)
            self.assertIn(hashlib.sha256(specification).hexdigest(), system)
            self.assertIn("当前语言版本：" + __version__, system)
            self.assertIn("事实", system)
            self.assertIn("典", system)
            self.assertEqual(payload["input"][1]["content"][0]["text"], "请显示数字四十二。\n")
            self.assertNotIn(LOCAL_TEST_API_KEY, json.dumps(value))
        finally:
            fake.shutdown()
            fake.server_close()
            thread.join(5)


if __name__ == "__main__":
    unittest.main()
