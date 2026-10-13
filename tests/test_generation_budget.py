"""Output budgets and safe diagnostics, using only authored loopback providers."""
import contextlib
import http.client
import io
import json
import os
import threading
import unittest
from unittest.mock import patch

from rulang.cli import main as cli_main
from rulang.generation import (
    GenerationConfig, GenerationError, LOCAL_TEST_API_KEY, extract_output_text,
    generate, generation_diagnostic, load_config, request_response,
)
from rulang.generation_trace import GenerationTrace
from rushu import generation as notebook_generation
from rushu.kernel import KernelError
from rushu.server import main as notebook_main, make_server
from test_generation import MockResponses, TemporaryGeneration, response_for


PROMPT = "请显示数字四十二。\n如是我言"
SECRET = "DO_NOT_LOG_PRIVATE_VALUE"
ID = "e" * 32


def serialized(value):
    return json.dumps(value, ensure_ascii=False)


def event_detail(trace, stage):
    events = [event for event in trace.snapshot()["events"] if event["stage"] == stage]
    if len(events) != 1:
        raise AssertionError(f"Expected one {stage} event; got {events!r}")
    return events[0]["detail"]


@contextlib.contextmanager
def notebook_server(**options):
    server = make_server(**options)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    worker.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        worker.join(5)


def post_generation(server, body):
    connection = http.client.HTTPConnection(*server.server_address, timeout=5)
    try:
        connection.request("POST", "/api/generate", json.dumps(body), {
            "Content-Type": "application/json", "Origin": server.origin,
            "X-Rushu-Token": server.token,
        })
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


class BudgetConfigurationTests(TemporaryGeneration):
    def config_with(self, value, spelling="max-output-tokens"):
        self.config.write_text(json.dumps({"api-key": LOCAL_TEST_API_KEY, spelling: value}), encoding="utf-8")

    def test_absent_budget_is_none_in_config_and_direct_constructor(self):
        self.assertIsNone(self.configured(**{"api-key": LOCAL_TEST_API_KEY}).max_output_tokens)
        self.assertIsNone(GenerationConfig(LOCAL_TEST_API_KEY).max_output_tokens)

    def test_both_json_spellings_accept_positive_integer(self):
        for spelling in ("max-output-tokens", "max_output_tokens"):
            for value in (1, 16384, 262144):
                with self.subTest(spelling=spelling, value=value):
                    self.config_with(value, spelling)
                    self.assertEqual(load_config(self.env).max_output_tokens, value)

    def test_override_then_environment_then_json_precedence(self):
        self.config_with(4096)
        env = {**self.env, "RU_LLM_MAX_OUTPUT_TOKENS": "32768"}
        self.assertEqual(load_config(self.env).max_output_tokens, 4096)
        self.assertEqual(load_config(env).max_output_tokens, 32768)
        self.assertEqual(load_config(env, max_output_tokens=16384).max_output_tokens, 16384)
        self.assertEqual(load_config(env, max_output_tokens=None).max_output_tokens, 32768)

    def test_only_selected_budget_source_is_validated(self):
        self.config_with(SECRET)
        env = {**self.env, "RU_LLM_MAX_OUTPUT_TOKENS": "32768"}
        self.assertEqual(load_config(env).max_output_tokens, 32768)
        env["RU_LLM_MAX_OUTPUT_TOKENS"] = SECRET
        self.assertEqual(load_config(env, max_output_tokens=16384).max_output_tokens, 16384)

    def test_json_budget_rejects_null_bool_float_string_and_nonpositive(self):
        for value in (None, True, False, 1.0, 16384.5, "16384", "", SECRET, 0, -0.0, -1, [], {}):
            with self.subTest(value=value):
                self.config_with(value)
                with self.assertRaises(GenerationError) as raised:
                    load_config(self.env)
                self.assertEqual(raised.exception.code, "max_output_tokens_config")
                self.assertNotIn(SECRET, str(raised.exception))

    def test_environment_budget_accepts_ascii_decimal_only(self):
        self.configured(**{"api-key": LOCAL_TEST_API_KEY})
        for value, expected in (("1", 1), ("16384", 16384), ("0007", 7)):
            with self.subTest(value=value):
                self.assertEqual(load_config({**self.env, "RU_LLM_MAX_OUTPUT_TOKENS": value}).max_output_tokens, expected)
        for value in ("", "0", "000", "-0", "+1", "-1", "1.0", "1e4", "1_000", " 1", "1 ",
                      "1\n", "１", "١", "²", SECRET, True, 1, None):
            with self.subTest(value=value), self.assertRaises(GenerationError) as raised:
                load_config({**self.env, "RU_LLM_MAX_OUTPUT_TOKENS": value})
            self.assertNotIn(SECRET, str(raised.exception))

    def test_explicit_override_rejects_invalid_types_and_values_without_fallback(self):
        self.config_with(4096)
        env = {**self.env, "RU_LLM_MAX_OUTPUT_TOKENS": "8192"}
        for value in (True, False, 0, -1, 1.0, "16384", "", [], {}, float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(GenerationError):
                load_config(env, max_output_tokens=value)

    def test_budget_parser_enforces_integer_boundary_and_bounded_input(self):
        self.config_with(2147483647)
        self.assertEqual(load_config(self.env).max_output_tokens, 2147483647)
        self.assertEqual(load_config({**self.env, "RU_LLM_MAX_OUTPUT_TOKENS": "2147483647"}).max_output_tokens, 2147483647)
        self.assertEqual(load_config(self.env, max_output_tokens=2147483647).max_output_tokens, 2147483647)
        for value in (2147483648, 10 ** 100):
            self.config_with(value)
            with self.subTest(value=value), self.assertRaises(GenerationError):
                load_config(self.env)
        for value in ("2147483648", "9" * 10000, "0" * 10000 + "1"):
            with self.subTest(length=len(value)), self.assertRaises(GenerationError):
                load_config({**self.env, "RU_LLM_MAX_OUTPUT_TOKENS": value})

    def test_conflicting_json_spellings_are_rejected(self):
        self.config.write_text(json.dumps({"api-key": LOCAL_TEST_API_KEY,
            "max-output-tokens": 4096, "max_output_tokens": 8192}), encoding="utf-8")
        with self.assertRaises(GenerationError):
            load_config(self.env)

    def test_override_does_not_hide_malformed_configuration(self):
        for raw in ('{"api-key":"ru-local-test-token","max-output-tokens":1,"max-output-tokens":2}',
                    '{"api-key":"ru-local-test-token","max-output-tokens":NaN}', "not JSON"):
            self.config.write_text(raw, encoding="utf-8")
            with self.subTest(raw=raw), self.assertRaises(GenerationError):
                load_config(self.env, max_output_tokens=16384)


class BudgetRequestTests(unittest.TestCase):
    def test_default_request_omits_budget_but_preserves_other_safety_options(self):
        with MockResponses() as provider:
            request_response(GenerationConfig(LOCAL_TEST_API_KEY, provider.base), "测试")
        self.assertEqual(len(provider.requests), 1)
        payload = provider.requests[0][2]
        self.assertNotIn("max_output_tokens", payload)
        self.assertIs(payload["stream"], False)
        self.assertIs(payload["store"], False)
        self.assertEqual(payload["tools"], [])
        self.assertEqual(payload["tool_choice"], "none")

    def test_explicit_budget_reaches_provider_unchanged_once(self):
        for cap in (1, 16384, 32768, 262144):
            with self.subTest(cap=cap), MockResponses() as provider:
                config = GenerationConfig(LOCAL_TEST_API_KEY, provider.base, "mock", cap)
                request_response(config, "测试")
            self.assertEqual(len(provider.requests), 1)
            self.assertEqual(provider.requests[0][2]["max_output_tokens"], cap)

    def test_invalid_direct_budget_fails_before_network(self):
        for value in (True, False, 0, -1, 1.0, "16384", "", SECRET, [], {}):
            with self.subTest(value=value), patch("rulang.generation.urlrequest.build_opener") as network:
                with self.assertRaises((GenerationError, ValueError)) as raised:
                    request_response(GenerationConfig(LOCAL_TEST_API_KEY, max_output_tokens=value), "测试")
                self.assertNotIn(SECRET, str(raised.exception))
                network.assert_not_called()

    def test_trace_distinguishes_unknown_provider_default_and_explicit_budget(self):
        for budget in (None, 16384):
            trace = GenerationTrace(ID)
            with self.subTest(budget=budget), MockResponses() as provider:
                request_response(GenerationConfig(LOCAL_TEST_API_KEY, provider.base, "mock", budget),
                                 "测试", trace=trace)
            detail = event_detail(trace, "request_budget")
            if budget is None:
                self.assertIn("提供方", detail)
                self.assertIn("默认", detail)
                self.assertIn("未知", detail)
                self.assertNotIn("16384", detail)
            else:
                self.assertIn("16384", detail)
            stages = [event["stage"] for event in trace.snapshot()["events"]]
            self.assertLess(stages.index("request_budget"), stages.index("request_sent"))

    def test_usage_and_output_summaries_are_allowlisted_and_do_not_leak_content(self):
        trace = GenerationTrace(ID)
        result = response_for("显 42.", usage={
            "input_tokens": 501, "output_tokens": 83, "total_tokens": 584,
            "input_tokens_details": {"cached_tokens": 17, "secret": SECRET},
            "output_tokens_details": {"reasoning_tokens": 79, "secret": SECRET},
            SECRET: SECRET, "description": SECRET,
        })
        result["output"].insert(0, {"type": "reasoning", "summary": [{"text": SECRET}],
                                   "content": SECRET, "encrypted_content": SECRET})
        result["arbitrary"] = SECRET
        with MockResponses(result) as provider:
            self.assertEqual(request_response(GenerationConfig(LOCAL_TEST_API_KEY, provider.base),
                                              "测试", trace=trace), "显 42.")
        usage = event_detail(trace, "response_usage")
        for name, value in (("input_tokens", 501), ("output_tokens", 83), ("total_tokens", 584), ("reasoning_tokens", 79)):
            self.assertIn(name, usage)
            self.assertIn(str(value), usage)
        summary = event_detail(trace, "output_summary")
        self.assertIn("reasoning", summary)
        self.assertIn("message", summary)
        self.assertNotIn(SECRET, serialized(trace.snapshot()))

    def test_malformed_usage_values_are_never_stringified(self):
        bad_values = [SECRET, {"secret": SECRET}, [SECRET], True, False, -1, 1.25, None]
        for value in bad_values:
            trace = GenerationTrace(ID)
            response = response_for("显 42.", usage={
                "input_tokens": value, "output_tokens": value, "total_tokens": value,
                "input_tokens_details": {"cached_tokens": value},
                "output_tokens_details": {"reasoning_tokens": value},
            })
            with self.subTest(value=value), MockResponses(response) as provider:
                request_response(GenerationConfig(LOCAL_TEST_API_KEY, provider.base), "测试", trace=trace)
            detail = event_detail(trace, "response_usage")
            for unsafe in (SECRET, "True", "False", "-1", "1.25"):
                self.assertNotIn(unsafe, detail)

    def test_usage_counter_boundary_prevents_unbounded_diagnostic_numbers(self):
        trace = GenerationTrace(ID)
        maximum = 9007199254740991
        response = response_for(usage={"input_tokens": maximum, "output_tokens": maximum + 1,
            "total_tokens": 10 ** 100, "output_tokens_details": {"reasoning_tokens": maximum + 1}})
        with MockResponses(response) as provider:
            request_response(GenerationConfig(LOCAL_TEST_API_KEY, provider.base), "测试", trace=trace)
        detail = event_detail(trace, "response_usage")
        self.assertIn("input_tokens=" + str(maximum), detail)
        for name in ("output_tokens", "total_tokens", "reasoning_tokens"):
            self.assertNotIn(name, detail)

    def test_zero_usage_counters_are_retained(self):
        trace = GenerationTrace(ID)
        with MockResponses(response_for(usage={"input_tokens": 0, "output_tokens": 0,
                "total_tokens": 0, "output_tokens_details": {"reasoning_tokens": 0}})) as provider:
            request_response(GenerationConfig(LOCAL_TEST_API_KEY, provider.base), "测试", trace=trace)
        detail = event_detail(trace, "response_usage")
        for name in ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens"):
            self.assertRegex(detail, name + r"\s*[=:：]\s*0")

    def test_unknown_output_and_content_types_use_other_not_provider_strings(self):
        trace = GenerationTrace(ID)
        result = response_for()
        result["output"].extend([{"type": SECRET, SECRET: SECRET}, {"type": [SECRET]}, None])
        result["output"][0]["content"].append({"type": SECRET, "text": SECRET})
        with MockResponses(result) as provider:
            with self.assertRaises(GenerationError):
                request_response(GenerationConfig(LOCAL_TEST_API_KEY, provider.base), "测试", trace=trace)
        self.assertIn("other", event_detail(trace, "output_summary"))
        self.assertNotIn(SECRET, serialized(trace.snapshot()))

    def test_reasoning_only_output_explicitly_reports_no_visible_assistant_text(self):
        trace = GenerationTrace(ID)
        result = response_for(output=[{"type": "reasoning", "summary": [{"text": SECRET}]}],
                              usage={"output_tokens": 16384, "output_tokens_details": {"reasoning_tokens": 16384}})
        with MockResponses(result) as provider:
            with self.assertRaises(GenerationError):
                request_response(GenerationConfig(LOCAL_TEST_API_KEY, provider.base), "测试", trace=trace)
        events = trace.snapshot()["events"]
        self.assertNotIn("model_text", [event["stage"] for event in events])
        self.assertRegex(event_detail(trace, "output_summary"), r"未返回可识别.*助手文本")
        self.assertNotIn(SECRET, serialized(events))

    def test_incomplete_reason_is_classified_and_partial_text_is_preserved_before_rejection(self):
        for reason in ("max_output_tokens", "content_filter"):
            trace = GenerationTrace(ID)
            response = response_for("显 '部分源码", status="incomplete", incomplete_details={"reason": reason, "private": SECRET})
            with self.subTest(reason=reason), MockResponses(response) as provider:
                with self.assertRaises(GenerationError) as raised:
                    request_response(GenerationConfig(LOCAL_TEST_API_KEY, provider.base), "测试", trace=trace)
                self.assertEqual(len(provider.requests), 1)
            self.assertEqual(raised.exception.code, "incomplete_" + reason)
            self.assertIn(reason, generation_diagnostic(raised.exception))
            self.assertIn("未自动重试", generation_diagnostic(raised.exception))
            if reason == "content_filter":
                self.assertNotIn("预算", generation_diagnostic(raised.exception))
                self.assertNotIn("max_output_tokens", generation_diagnostic(raised.exception))
            events = trace.snapshot()["events"]
            self.assertEqual(next(event["text"] for event in events if event["stage"] == "model_text"), "显 '部分源码")
            stages = [event["stage"] for event in events]
            self.assertLess(stages.index("model_text"), stages.index("response_validation"))
            self.assertNotIn(SECRET, serialized(events) + str(raised.exception))

    def test_unknown_or_malformed_incomplete_reason_is_safe(self):
        for reason in (SECRET, [SECRET], {"secret": SECRET}, None, True):
            response = response_for(status="incomplete", incomplete_details={"reason": reason})
            trace = GenerationTrace(ID)
            with self.subTest(reason=reason), MockResponses(response) as provider:
                with self.assertRaises(GenerationError) as raised:
                    request_response(GenerationConfig(LOCAL_TEST_API_KEY, provider.base), "测试", trace=trace)
            self.assertNotIn(SECRET, str(raised.exception) + generation_diagnostic(raised.exception) + serialized(trace.snapshot()))

    def test_extraction_classifies_incomplete_even_without_trace(self):
        for reason in ("max_output_tokens", "content_filter"):
            with self.subTest(reason=reason), self.assertRaises(GenerationError) as raised:
                extract_output_text(response_for(status="incomplete", incomplete_details={"reason": reason}))
            self.assertEqual(raised.exception.code, "incomplete_" + reason)


class BudgetCLIIntegrationTests(TemporaryGeneration):
    def invoke(self, options):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = cli_main(["generate", str(self.document), *options])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_cli_option_reaches_generate_unchanged(self):
        with patch("rulang.cli.generate", return_value="显 42.\n") as call:
            status, stdout, stderr = self.invoke(["--stdout", "--max-output-tokens", "32768"])
        self.assertEqual(status, 0, stderr)
        self.assertEqual(call.call_args.kwargs["max_output_tokens"], 32768)
        self.assertEqual(stdout, "显 42.\n")

    def test_cli_rejects_invalid_budget_before_any_generation(self):
        for value in ("0", "-0", "-1", "1.5", "nan", "inf", "true", "", SECRET, "１", "1e4"):
            with self.subTest(value=value), patch("rulang.cli.generate") as call, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                cli_main(["generate", str(self.document), "--max-output-tokens=" + value])
            self.assertEqual(raised.exception.code, 2)
            call.assert_not_called()

    def test_generate_override_and_cli_override_reach_loopback_payload(self):
        self.config.write_text(json.dumps({"api-key": LOCAL_TEST_API_KEY, "max-output-tokens": 4096}), encoding="utf-8")
        with MockResponses(response_for("显 1/0.")) as provider:
            env = {**self.local_env(provider), "RU_LLM_MAX_OUTPUT_TOKENS": "8192"}
            with patch("rulang.interpreter.Interpreter.execute", side_effect=AssertionError("executed")):
                self.assertEqual(generate(self.document, environ=env, stdout=True, max_output_tokens=16384), "显 1/0.\n")
                with patch.dict(os.environ, env, clear=True):
                    status, stdout, stderr = self.invoke(["--stdout", "--max-output-tokens", "32768"])
        self.assertEqual(status, 0, stderr)
        self.assertEqual(stdout, "显 1/0.\n")
        self.assertEqual([request[2]["max_output_tokens"] for request in provider.requests], [16384, 32768])
        self.assertEqual(list(self.root.glob("*.generated.*")), [])

    def test_verbose_default_budget_usage_summary_and_no_reasoning_leak(self):
        result = response_for("显 1/0.", usage={"input_tokens": 401, "output_tokens": 19,
            "total_tokens": 420, "output_tokens_details": {"reasoning_tokens": 11}, "private": SECRET})
        result["output"].insert(0, {"type": "reasoning", "summary": [{"text": SECRET}]})
        with MockResponses(result) as provider, patch.dict(os.environ, self.local_env(provider), clear=True):
            status, stdout, stderr = self.invoke(["--stdout", "--verbose"])
        self.assertEqual(status, 0, stderr)
        self.assertEqual(stdout, "显 1/0.\n")
        for expected in ("提供方", "默认", "未知", "input_tokens", "401", "reasoning_tokens", "11", "reasoning", "message"):
            self.assertIn(expected, stderr)
        self.assertNotIn(SECRET, stdout + stderr)
        self.assertNotIn("max_output_tokens", provider.requests[0][2])
        self.assertEqual(len(provider.requests), 1)

    def test_non_verbose_cli_never_emits_usage_or_budget_summary(self):
        response = response_for("显 42.", usage={"output_tokens": 5, "private": SECRET})
        with MockResponses(response) as provider, patch.dict(os.environ, self.local_env(provider), clear=True):
            status, stdout, stderr = self.invoke(["--stdout", "--max-output-tokens", "16384"])
        self.assertEqual(status, 0)
        self.assertEqual(stdout, "显 42.\n")
        self.assertEqual(stderr, "已生成并检查；未执行，请先审阅源码。\n")
        self.assertNotIn(SECRET, stdout + stderr)
        self.assertEqual(provider.requests[0][2]["max_output_tokens"], 16384)

    def test_incomplete_force_preserves_existing_file_and_original_document(self):
        destination = self.root / "existing.ru"
        old = b"# authored existing source\n"
        destination.write_bytes(old)
        original = self.document.read_bytes()
        response = response_for("显 '未完成", status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        with MockResponses(response) as provider, patch.dict(os.environ, self.local_env(provider), clear=True):
            status, stdout, stderr = self.invoke(["-o", str(destination), "--force"])
        self.assertEqual(status, 1)
        self.assertEqual(stdout, "")
        self.assertIn("max_output_tokens", stderr)
        self.assertEqual(destination.read_bytes(), old)
        self.assertEqual(self.document.read_bytes(), original)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(list(self.root.glob(".ru-generate-*")), [])

    def test_incomplete_cli_does_not_publish_retry_or_execute(self):
        response = response_for("显 '未完成", status="incomplete", incomplete_details={"reason": "max_output_tokens"},
            usage={"output_tokens": 16384, "output_tokens_details": {"reasoning_tokens": 16000}})
        with MockResponses(response) as provider, patch.dict(os.environ, self.local_env(provider), clear=True), \
                patch("rulang.interpreter.Interpreter.execute", side_effect=AssertionError("executed")):
            status, stdout, stderr = self.invoke(["--verbose", "--max-output-tokens", "16384"])
        self.assertEqual(status, 1)
        self.assertEqual(stdout, "")
        self.assertIn("max_output_tokens", stderr)
        self.assertIn("reasoning_tokens", stderr)
        self.assertNotIn("显 '未完成", stderr)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(list(self.root.glob("*.generated.*")), [])
        self.assertEqual(list(self.root.glob(".ru-generate-*")), [])


class NotebookBudgetTests(TemporaryGeneration):
    def test_server_accepts_default_and_explicit_budget(self):
        for cap in (None, 1, 16384, 262144):
            with self.subTest(cap=cap):
                server = make_server(max_output_tokens=cap)
                try:
                    self.assertEqual(server.max_output_tokens, cap)
                finally:
                    server.server_close()

    def test_invalid_server_or_worker_budget_stops_before_resources_or_provider(self):
        for value in (True, False, 0, -1, 1.0, "16384", "", [], {}):
            with self.subTest(value=value), patch("rushu.server.SessionManager") as sessions, \
                    patch.object(notebook_generation, "request_response") as provider, \
                    patch.object(notebook_generation, "threading", wraps=threading) as threads, \
                    patch.object(notebook_generation, "_GENERATION_SLOT") as slot:
                with self.assertRaises((GenerationError, ValueError)):
                    make_server(max_output_tokens=value)
                with self.assertRaises(KernelError) as raised:
                    notebook_generation.generate_source({"prompt": PROMPT}, max_output_tokens=value)
                self.assertEqual(raised.exception.status, 503)
                sessions.assert_not_called()
                threads.Thread.assert_not_called()
                slot.acquire.assert_not_called()
                provider.assert_not_called()

    def test_notebook_startup_option_reaches_make_server(self):
        with patch("rushu.server.make_server") as create, patch("rushu.server.signal.signal"), \
                patch("rushu.server.sys.stdout", new_callable=io.StringIO):
            create.return_value.url = "http://127.0.0.1:1234/#token=test"
            create.return_value.serve_forever.side_effect = KeyboardInterrupt
            self.assertEqual(notebook_main(["--no-browser", "--max-output-tokens", "32768"]), 0)
        self.assertEqual(create.call_args.kwargs["max_output_tokens"], 32768)
        create.return_value.server_close.assert_called_once_with()

    def test_notebook_startup_rejects_invalid_budget_before_server(self):
        for value in ("0", "-0", "-1", "1.5", "nan", "inf", "true", "", SECRET, "１", "1e4"):
            with self.subTest(value=value), patch("rushu.server.make_server") as create, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                notebook_main(["--no-browser", "--max-output-tokens=" + value])
            self.assertEqual(raised.exception.code, 2)
            create.assert_not_called()

    def test_configuration_uses_server_override_and_reports_budget_errors_safely(self):
        env = {**self.env, "RU_LLM_API_KEY": LOCAL_TEST_API_KEY, "RU_LLM_MAX_OUTPUT_TOKENS": SECRET}
        with patch.dict(os.environ, env, clear=True):
            bad = notebook_generation.configuration()
            overridden = notebook_generation.configuration(max_output_tokens=16384)
        self.assertFalse(bad["configured"])
        self.assertIn("预算", bad["message"])
        self.assertNotIn("RU_LLM_API_KEY", bad["message"])
        self.assertTrue(overridden["configured"])
        self.assertNotIn(SECRET, serialized([bad, overridden]))

    def test_direct_generate_source_override_reaches_provider_without_execution(self):
        with MockResponses(response_for("显 1/0.")) as provider, \
                patch.dict(os.environ, {**self.local_env(provider), "RU_LLM_MAX_OUTPUT_TOKENS": "4096"}, clear=True), \
                patch("rulang.interpreter.Interpreter.execute", side_effect=AssertionError("executed")):
            result = notebook_generation.generate_source({"prompt": PROMPT, "generation_id": ID}, max_output_tokens=16384)
        self.assertTrue(result["valid"])
        self.assertEqual(result["source"], "显 1/0.\n")
        self.assertEqual(provider.requests[0][2]["max_output_tokens"], 16384)
        self.assertEqual(len(provider.requests), 1)
        self.assertTrue(result["trace"]["complete"])

    def test_http_default_budget_and_server_override_take_precedence(self):
        for server_cap, env_cap, expected in ((None, None, None), (None, "8192", 8192), (16384, "8192", 16384)):
            with self.subTest(server_cap=server_cap, env_cap=env_cap), \
                    MockResponses(response_for("显 1/0.")) as provider:
                env = self.local_env(provider)
                if env_cap is not None:
                    env["RU_LLM_MAX_OUTPUT_TOKENS"] = env_cap
                with patch.dict(os.environ, env, clear=True), notebook_server(max_output_tokens=server_cap) as server, \
                        patch.object(server.sessions, "create", side_effect=AssertionError("executed")):
                    status, result = post_generation(server, {"prompt": PROMPT, "generation_id": ID})
                self.assertEqual(status, 200, result)
                self.assertTrue(result["valid"])
                self.assertEqual(len(provider.requests), 1)
                payload = provider.requests[0][2]
                if expected is None:
                    self.assertNotIn("max_output_tokens", payload)
                else:
                    self.assertEqual(payload["max_output_tokens"], expected)

    def test_http_reasoning_only_budget_exhaustion_has_truthful_safe_diagnostics(self):
        response = {
            "object": "response", "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{"type": "reasoning", "summary": [{"text": SECRET}],
                        "encrypted_content": SECRET, "content": SECRET}],
            "usage": {"input_tokens": 6200, "output_tokens": 16384, "total_tokens": 22584,
                      "output_tokens_details": {"reasoning_tokens": 16384}, "private": SECRET},
        }
        with MockResponses(response) as provider, patch.dict(os.environ, self.local_env(provider), clear=True), \
                notebook_server() as server, patch.object(server.sessions, "create", side_effect=AssertionError("executed")):
            status, result = post_generation(server, {"prompt": PROMPT, "generation_id": ID})
        self.assertEqual(status, 502, result)
        self.assertIn("max_output_tokens", result["error"])
        self.assertIn("上限", result["error"])
        self.assertIn("未自动重试", result["error"])
        self.assertNotIn("source", result)
        self.assertEqual(len(provider.requests), 1)
        self.assertNotIn("max_output_tokens", provider.requests[0][2])
        self.assertNotIn(SECRET, serialized(result))
        trace = result["trace"]
        self.assertTrue(trace["complete"])
        stages = [event["stage"] for event in trace["events"]]
        self.assertNotIn("model_text", stages)
        self.assertNotIn("extracted_source", stages)
        details = {event["stage"]: event["detail"] for event in trace["events"]}
        self.assertIn("提供方默认值未知", details["request_budget"])
        self.assertIn("reasoning_tokens=16384", details["response_usage"])
        self.assertIn("reasoning=1", details["output_summary"])
        self.assertRegex(details["output_summary"], r"未返回可识别.*助手文本")
        self.assertEqual(stages[-1], "final_failure")

    def test_http_bad_config_budget_is_actionable_and_never_requests_provider(self):
        env = {**self.env, "RU_LLM_API_KEY": LOCAL_TEST_API_KEY, "RU_LLM_MAX_OUTPUT_TOKENS": SECRET}
        with patch.dict(os.environ, env, clear=True), notebook_server() as server, \
                patch.object(notebook_generation, "request_response") as provider:
            status, result = post_generation(server, {"prompt": PROMPT, "generation_id": ID})
        self.assertEqual(status, 503, result)
        self.assertIn("预算配置无效", result["error"])
        self.assertIn("整数", result["error"])
        self.assertNotIn("RU_LLM_API_KEY", result["error"])
        self.assertNotIn(SECRET, serialized(result))
        self.assertTrue(result["trace"]["complete"])
        provider.assert_not_called()

    def test_http_incomplete_retains_partial_trace_and_safe_diagnosis(self):
        for reason in ("max_output_tokens", "content_filter"):
            response = response_for("显 '未完成", status="incomplete", incomplete_details={"reason": reason, "private": SECRET},
                usage={"output_tokens": 16384, "output_tokens_details": {"reasoning_tokens": 16000}, "private": SECRET})
            response["output"].insert(0, {"type": "reasoning", "summary": [{"text": SECRET}]})
            with self.subTest(reason=reason), MockResponses(response) as provider, \
                    patch.dict(os.environ, self.local_env(provider), clear=True), notebook_server() as server, \
                    patch.object(server.sessions, "create", side_effect=AssertionError("executed")):
                status, result = post_generation(server, {"prompt": PROMPT, "generation_id": ID})
            self.assertEqual(status, 502, result)
            self.assertIn(reason, result["error"])
            self.assertNotIn("source", result)
            self.assertNotIn(SECRET, serialized(result))
            self.assertTrue(result["trace"]["complete"])
            events = result["trace"]["events"]
            self.assertEqual(events[-1]["stage"], "final_failure")
            self.assertEqual(next(event["text"] for event in events if event["stage"] == "model_text"), "显 '未完成")
            for stage in ("request_budget", "response_usage", "output_summary"):
                self.assertIn(stage, [event["stage"] for event in events])
            self.assertEqual(len(provider.requests), 1)


if __name__ == "__main__":
    unittest.main()
