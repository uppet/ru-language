"""Safe transport diagnostics and genuine stage signals, with no live requests."""
import http.client
import io
import json
import ssl
import unittest
from unittest.mock import MagicMock, patch
from urllib import error as urlerror

from rulang.generation import GenerationConfig, GenerationError, GenerationSummary, generation_diagnostic, request_response
from test_generation import MockResponses, response_for


class TransportDiagnosticsTests(unittest.TestCase):
    def test_errors_are_classified_without_sensitive_details_or_retry(self):
        config = GenerationConfig("fake-secret", "https://provider.example/private", "model")
        cert = ssl.SSLCertVerificationError(1, "SECRET CERTIFICATE_VERIFY_FAILED")
        cases = [(cert, "tls_certificate"), (urlerror.URLError(cert), "tls_certificate"),
                 (ssl.SSLError("SECRET"), "tls"), (urlerror.URLError(ssl.SSLError("SECRET")), "tls"),
                 (TimeoutError("SECRET"), "timeout"), (urlerror.URLError(TimeoutError("SECRET")), "timeout"),
                 (urlerror.URLError("SECRET"), "connection"), (OSError("SECRET"), "connection"),
                 (http.client.IncompleteRead(b"SECRET"), "response_interrupted"),
                 (ConnectionResetError("SECRET"), "response_interrupted"),
                 (urlerror.HTTPError("https://SECRET", 429, "SECRET", {}, io.BytesIO(b"SECRET")), "http")]
        for exception, code in cases:
            with self.subTest(code=code, kind=type(exception)), patch("rulang.generation.urlrequest.build_opener") as factory:
                factory.return_value.open.side_effect = exception
                with self.assertRaises(GenerationError) as raised:
                    request_response(config, "生成测试")
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(factory.return_value.open.call_count, 1)
                self.assertNotIn("SECRET", str(raised.exception))
                self.assertNotIn(config.api_key, str(raised.exception))
                self.assertIn("未自动重试", str(raised.exception))
                if code == "http":
                    self.assertIn("429", str(raised.exception))

    def test_invalid_response_unicode_is_not_reported_as_connection_failure(self):
        from rulang.generation import LOCAL_TEST_API_KEY
        from rulang.generation_trace import GenerationTrace
        for raw, has_text in ((b"\xff", False),
                              (json.dumps(response_for("visible text \ud800")).encode(), True)):
            trace = GenerationTrace("b" * 32)
            with self.subTest(raw=raw), MockResponses(raw=raw) as server:
                with self.assertRaises(GenerationError) as raised:
                    request_response(GenerationConfig(LOCAL_TEST_API_KEY, server.base), "测试", trace=trace)
                self.assertEqual(len(server.requests), 1)
            self.assertEqual(raised.exception.code, "response_unicode")
            self.assertIn("无效 Unicode", generation_diagnostic(raised.exception))
            self.assertNotIn("连接失败", generation_diagnostic(raised.exception))
            events = trace.snapshot()["events"]
            self.assertTrue(any(e["stage"] == "response_validation" for e in events))
            self.assertEqual(any(e["stage"] == "model_text" for e in events), has_text)
            if has_text:
                self.assertIn("visible text", next(e["text"] for e in events if e["stage"] == "model_text"))

    def test_unknown_error_and_invalid_status_never_echo_raw_details(self):
        for error in (GenerationError("SECRET"), GenerationError("SECRET", code="SECRET"),
                      GenerationError("SECRET", code="http", status="SECRET")):
            self.assertNotIn("SECRET", generation_diagnostic(error))

    def test_progress_reports_fixed_phases_and_allowlisted_summaries(self):
        stages = []
        with MockResponses(response_for("显 1/0.")) as server:
            from rulang.generation import LOCAL_TEST_API_KEY
            result = request_response(GenerationConfig(LOCAL_TEST_API_KEY, server.base), "测试", progress=stages.append)
        self.assertEqual(result, "显 1/0.")
        self.assertEqual([stage for stage in stages if not isinstance(stage, GenerationSummary)],
                         ["发送生成请求", "等待提供方响应", "收到提供方响应"])
        summaries = [stage for stage in stages if isinstance(stage, GenerationSummary)]
        self.assertEqual(len(summaries), 3)
        self.assertIn("提供方默认值未知", summaries[0])
        self.assertIn("usage", summaries[1])
        self.assertIn("message=1", summaries[2])
