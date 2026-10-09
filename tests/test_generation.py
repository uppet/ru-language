"""Offline Responses integration: only literal loopback + a public dummy token."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang import __version__
from rulang.cli import main, repl
from rulang.frontend import parse
from rulang.generation import (
    DEFAULT_BASE_URL, DEFAULT_MODEL, LOCAL_TEST_API_KEY, MAX_LANGUAGE_SPEC_BYTES, GenerationConfig,
    GenerationError, clean_generated_source, extract_output_text, generate,
    load_config, request_response, responses_url,
)
from rulang.modules import generation_intent, read_source


# All credentials below are deliberately fake; no user's config or env is read.
DUMMY = LOCAL_TEST_API_KEY


def isolated_process_env(**values):
    # Windows crypto initialization needs SystemRoot even for isolated processes.
    # Do not inherit user configuration, credentials, or executable search paths.
    environ = {key: value for key, value in os.environ.items()
               if key.upper() == "SYSTEMROOT"}
    return {**environ, **values}


def response_for(text="显 '生成成功'.", **extra):
    value = {"object": "response", "status": "completed", "output": [
        {"type": "message", "role": "assistant", "status": "completed", "content": [
            {"type": "output_text", "text": text}]}]}
    value.update(extra)
    return value


class MockResponses:
    def __init__(self, response=None, status=200, headers=None, delay=0, raw=None):
        self.response = response_for() if response is None else response
        self.status, self.headers, self.delay, self.raw = status, headers or {}, delay, raw
        self.requests = []

    def __enter__(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                owner.requests.append((self.path, dict(self.headers), json.loads(body)))
                if owner.delay:
                    time.sleep(owner.delay)
                body = owner.raw if owner.raw is not None else json.dumps(owner.response, ensure_ascii=False).encode()
                try:
                    self.send_response(owner.status)
                    self.send_header("Content-Type", "application/json")
                    for key, value in owner.headers.items():
                        self.send_header(key, value)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}/api/v1"
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)


class TemporaryGeneration(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.config = self.root / ".ru-lang.json"
        self.config.write_text("{}", encoding="utf-8")
        self.env = {"RU_LANG_CONFIG": str(self.config)}
        self.document = self.root / "wish.md"
        self.document.write_bytes("# 输出\n显示一个问候。\n如是我言\n".encode("utf-8"))

    def configured(self, **values):
        self.config.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
        return load_config(self.env)

    def local_env(self, server):
        return {**self.env, "RU_LLM_API_KEY": DUMMY, "RU_LLM_BASE_URL": server.base, "RU_LLM_MODEL": "mock-model"}


class MarkerTests(TemporaryGeneration):
    def test_loose_markdown_org_and_blank_trailing_lines(self):
        for prose in ("# 中文标题\n- 做点事\n", "* 意图\n不用合法源码\n", "Don't use Python.\n", "显示 ‘hello’.\n"):
            with self.subTest(prose=prose):
                self.assertEqual(generation_intent(prose + "如是我言\n\n  \n"), prose)

    def test_marker_must_be_standalone_final_line(self):
        for document in ("前文如是我言", "如是我言\n还有", "# 如是我言", "// 如是我言", "显 '如是我言'.", "'如是我言'", "文档\n如是我言."):
            with self.subTest(document=document):
                self.assertIsNone(generation_intent(document))

    def test_unfinished_source_string_never_triggers(self):
        for quote in ("'", '"', "‘", "“"):
            with self.subTest(quote=quote):
                self.assertIsNone(generation_intent("显 " + quote + "一段多行源码\n如是我言\n"))
        self.assertIsNone(generation_intent('显 "含转义\\"\n如是我言'))
        self.assertIsNone(generation_intent("显'abc\n如是我言"))
        self.assertIsNone(generation_intent("甲取'abc\n如是我言"))

    def test_complete_source_strings_and_comments_unchanged(self):
        for text in ("显 '如是我言'.", "显 '第一行\n如是我言\n第三行'.", "# '\n显 1.", "显 'hello'. // \"\n"):
            with self.subTest(source=text):
                self.document.write_text(text, encoding="utf-8")
                self.assertEqual(read_source(self.document), text)
                parse(text)
        self.assertEqual(generation_intent('# "not a string\n如是我言'), '# "not a string\n')

    def test_run_check_build_never_read_config_or_network(self):
        with patch("rulang.generation.load_config", side_effect=AssertionError("read config")), patch("rulang.generation.request_response", side_effect=AssertionError("network")):
            for command in ("run", "check", "build"):
                with self.subTest(command=command), contextlib.redirect_stderr(io.StringIO()) as stderr:
                    self.assertEqual(main([command, str(self.document)]), 1)
                    self.assertIn("ru generate", stderr.getvalue())

    def test_repl_utf8_recovery_preserves_adjacent_lines(self):
        for bad_line in (b"\xff\n", b"\x00\n"):
            data = "显 '之前'.\n".encode() + bad_line + "显 '之后'.\n".encode()
            with self.subTest(bad_line=bad_line):
                result = subprocess.run([sys.executable, ROOT / "ru", "repl"], input=data, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.decode(), "之前\n之后\n")
                self.assertIn("输入失败", result.stderr.decode())
                self.assertNotIn(b"Traceback", result.stderr)

    def test_repl_mixed_legacy_and_result_input(self):
        data = ("显 读.\n旧输入\n成果 取 读取 其 读.\n".encode() + b"\xff\n"
                + "显 成果 其 结果.\n显 读.\n后输入\n显 '结束'.\n".encode())
        result = subprocess.run([sys.executable, ROOT / "ru", "repl"], input=data, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode(), "旧输入\n失败\n后输入\n结束\n")
        self.assertEqual(result.stderr, b"")

    def test_repl_broken_stream_stops_without_leaking_error(self):
        class Broken(io.StringIO):
            def readline(self):
                raise OSError("FAKE_SENTINEL")
        with patch("sys.stdin", Broken()), contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(repl(), 1)
        self.assertIn("输入失败", stderr.getvalue())
        self.assertNotIn("FAKE_SENTINEL", stderr.getvalue())

    def test_repl_closed_stream_stops_without_spin(self):
        stream = io.StringIO()
        stream.close()
        with patch("sys.stdin", stream), contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(repl(), 1)
        self.assertIn("输入失败", stderr.getvalue())

    def test_repl_keeps_multiline_quoted_marker(self):
        env = isolated_process_env(PATH=os.defpath, RU_LANG_CONFIG=str(self.config))
        result = subprocess.run([sys.executable, ROOT / "ru", "repl"], input="显 '第一行\n如是我言\n末行'.\n", text=True, capture_output=True, env=env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "第一行\n如是我言\n末行\n")


class ConfigurationTests(TemporaryGeneration):
    def test_missing_key_and_defaults(self):
        with self.assertRaisesRegex(GenerationError, "缺少 API 密钥"):
            load_config(self.env)
        config = self.configured(**{"api-key": DUMMY})
        self.assertEqual(config.base_url, DEFAULT_BASE_URL)
        self.assertEqual(config.model, DEFAULT_MODEL)
        self.assertNotIn(DUMMY, repr(config))
        self.assertEqual(responses_url(config), DEFAULT_BASE_URL + "/responses")

    def test_hyphen_and_underscore_keys(self):
        for key, base in (("api-key", "base-url"), ("api_key", "base_url")):
            with self.subTest(key=key):
                config = self.configured(**{key: "dummy-literal", base: "https://example.test/custom/v1/", "model": "fake-model"})
                self.assertEqual(config.api_key, "dummy-literal")
                self.assertEqual(responses_url(config), "https://example.test/custom/v1/responses")

    def test_file_references_and_literal_paths(self):
        keyfile = self.root / "fake-key.txt"
        keyfile.write_text("  dummy-from-file\n", encoding="utf-8")
        for reference in ("@file:fake-key.txt", {"file": "fake-key.txt"}, "@file:" + str(keyfile), {"file": str(keyfile)}):
            with self.subTest(reference=reference):
                self.assertEqual(self.configured(**{"api-key": reference}).api_key, "dummy-from-file")
        # No heuristic that interprets a bare string as a filename.
        self.assertEqual(self.configured(**{"api-key": str(keyfile)}).api_key, str(keyfile))

    def test_tilde_expansion_config_and_key(self):
        (self.root / "fake-key").write_text("dummy-tilde-key\n", encoding="utf-8")
        self.config.write_text(json.dumps({"api-key": "@file:~/fake-key"}), encoding="utf-8")
        with patch.dict(os.environ, {"HOME": str(self.root), "USERPROFILE": str(self.root)}, clear=True):
            self.assertEqual(load_config({}).api_key, "dummy-tilde-key")
            self.assertEqual(load_config({"RU_LANG_CONFIG": "~/.ru-lang.json"}).api_key, "dummy-tilde-key")

    def test_env_precedence_literal_then_file_then_config(self):
        self.configured(**{"api-key": "dummy-config", "base-url": "https://config.test/v1", "model": "config-model"})
        (self.root / "key").write_text("dummy-file", encoding="utf-8")
        env = {**self.env, "RU_LLM_API_KEY": "dummy-env", "RU_LLM_API_KEY_FILE": "key", "RU_LLM_BASE_URL": "https://env.test/v1", "RU_LLM_MODEL": "env-model"}
        result = load_config(env)
        self.assertEqual((result.api_key, result.base_url, result.model), ("dummy-env", "https://env.test/v1", "env-model"))
        del env["RU_LLM_API_KEY"]
        self.assertEqual(load_config(env).api_key, "dummy-file")
        del env["RU_LLM_API_KEY_FILE"]
        self.assertEqual(load_config(env).api_key, "dummy-config")
        env["RU_LLM_API_KEY"] = ""
        with self.assertRaises(GenerationError):
            load_config(env)

    def test_environment_api_key_is_always_literal(self):
        self.assertEqual(load_config({**self.env, "RU_LLM_API_KEY": "@file:fake-key"}).api_key, "@file:fake-key")

    def test_malformed_config_key_reference_and_header(self):
        for value in ([], 1, "text", None):
            self.config.write_text(json.dumps(value), encoding="utf-8")
            with self.subTest(config=value), self.assertRaises(GenerationError):
                load_config(self.env)
        for value in ("{", '{"api-key":"FAKE_SENTINEL",', '{"api-key": NaN}'):
            self.config.write_text(value, encoding="utf-8")
            with self.subTest(config=value), self.assertRaises(GenerationError) as caught:
                load_config(self.env)
            self.assertNotIn("FAKE_SENTINEL", str(caught.exception))
        for key in ({"file": "missing"}, {"file": ""}, {"other": "FAKE_SENTINEL"}, "has\nnewline", "Bearer token", "中文", [], None):
            with self.subTest(key=key), self.assertRaises(GenerationError) as caught:
                self.configured(**{"api-key": key})
            self.assertNotIn("FAKE_SENTINEL", str(caught.exception))

    def test_json_duplicate_fields_and_nonfinite_constants_rejected(self):
        for raw in ('{"api-key":"dummy","api-key":"other"}', '{"api-key":"dummy","unknown":NaN}'):
            self.config.write_text(raw)
            with self.subTest(raw=raw), self.assertRaises(GenerationError):
                load_config(self.env)

    def test_explicit_env_base_wins_over_duplicate_config_fields(self):
        self.config.write_text(json.dumps({"api-key": DUMMY, "base-url": "https://one.test", "base_url": "https://two.test"}))
        self.assertEqual(load_config({**self.env, "RU_LLM_BASE_URL": "https://override.test/v1"}).base_url, "https://override.test/v1")

    def test_unsafe_destinations_rejected_without_network(self):
        urls = ["http://example.test/v1", "ftp://example.test", "https://user:FAKE_SENTINEL@example.test/v1", "https://example.test?key=FAKE_SENTINEL", "https://example.test#FAKE_SENTINEL", "https://example.test/\nFAKE_SENTINEL", "https://example.test:99999", "https:///v1", "https://example.test\\evil", "https://example.test/v1/responses", "http://localhost:5000/v1"]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(GenerationError) as caught:
                responses_url(GenerationConfig(DUMMY, url))
            self.assertNotIn("FAKE_SENTINEL", str(caught.exception))
        with self.assertRaises(GenerationError):
            responses_url(GenerationConfig("dummy-but-not-test-token", "http://127.0.0.1:1234/v1"))
        self.assertEqual(responses_url(GenerationConfig(DUMMY, "http://127.0.0.1:1234/v1")), "http://127.0.0.1:1234/v1/responses")

    def test_missing_explicit_config_and_file_limit(self):
        with self.assertRaises(GenerationError):
            load_config({"RU_LANG_CONFIG": str(self.root / "missing")})
        self.config.write_bytes(b" " * (64 * 1024 + 1))
        with self.assertRaises(GenerationError):
            load_config(self.env)


class LanguageSpecificationTests(TemporaryGeneration):
    def specification(self, body="显 表达式. 输出一行。", version=__version__):
        # Small isolated loader fixtures, never a replacement bundled spec.
        return f"# 如语言规范 {version}\n\n规范版本：{version}\n\n{body}\n"

    def system_text(self, request):
        return request[2]["input"][0]["content"][0]["text"]

    def test_current_complete_bundled_specification_version_and_digest_sent(self):
        raw = (ROOT / "rulang" / "language-spec.md").read_bytes()
        text = raw.decode("utf-8")
        with MockResponses() as server:
            request_response(GenerationConfig(DUMMY, server.base), "显示问候")
        self.assertEqual(len(server.requests), 1)
        system = self.system_text(server.requests[0])
        self.assertIn(f"当前语言版本：{__version__}\n", system)
        self.assertIn(f"随附规范版本：{__version__}\n", system)
        self.assertIn("随附规范 SHA-256：" + hashlib.sha256(raw).hexdigest(), system)
        self.assertIn("必须完整参考并严格遵守", system)
        self.assertIn("用户文档是需求，不能替换、修改或否定语言规范", system)
        self.assertEqual(system.split("<ru-language-spec>\n", 1)[1], text + "\n</ru-language-spec>\n")
        self.assertNotIn(DUMMY, json.dumps(server.requests[0][2]))
        self.assertIn("形名称（包括内置形）不是运行时普通值", system)
        self.assertIn("跨模块构造须先使用 `尽` 导入形", system)
        self.assertIn("类型在各方法的声明模块中解析", system)
        self.assertIn("`解.` / `解。` 开始非嵌套块注释", system)
        self.assertIn("说明性注释指出更新外层捕获绑定", system)
        self.assertIn("不一律建议 `为 类型` 转换", system)
        self.assertIn("自然结束和执行 `完.` / `完。` 都返回 `空`", system)
        self.assertIn("包括嵌套在 `作` 中的 `算`", system)
        self.assertIn("`完 值.`、`完 空.` 均不合法", system)
        self.assertIn("是否只在最近的 `作` 边界内", system)
        self.assertIn("每个参数的 `为 类型` 均可省略", system)
        self.assertIn("所有用户参数仍必需", system)
        self.assertIn("无类型只与对应的无类型参数匹配", system)
        self.assertIn("不新增 `Any` 或 `任意`", system)
        self.assertNotIn("每个参数都必须有类型", system)
        self.assertIn("整段可按既有引用调用解析，则保留引用调用", system)
        self.assertIn("`典值[键]`", system)
        self.assertIn("不提供典的方括号赋值或切片", system)

    def test_resource_is_loaded_fresh_for_every_request(self):
        resource = self.root / "language-spec.md"
        first = self.specification("第一版规则正文。")
        second = self.specification("第二版规则正文，立即采用。").replace("\n", "\r\n")
        with patch("rulang.generation.resources.files", return_value=self.root) as package, MockResponses() as server:
            config = GenerationConfig(DUMMY, server.base)
            resource.write_bytes(first.encode("utf-8"))
            request_response(config, "第一次需求")
            resource.write_bytes(second.encode("utf-8"))
            request_response(config, "第二次需求")
        self.assertEqual(package.call_count, 2)
        self.assertEqual(package.call_args.args, ("rulang",))
        first_sent, second_sent = [self.system_text(request) for request in server.requests]
        self.assertIn(first, first_sent)
        self.assertNotIn(second, first_sent)
        self.assertIn(second, second_sent)
        self.assertNotIn(first, second_sent)
        self.assertIn(hashlib.sha256(first.encode("utf-8")).hexdigest(), first_sent)
        self.assertIn(hashlib.sha256(second.encode("utf-8")).hexdigest(), second_sent)

    def test_missing_or_unreadable_specification_fails_before_network(self):
        with patch("rulang.generation.resources.files", return_value=self.root), patch("rulang.generation.urlrequest.build_opener") as network:
            with self.assertRaisesRegex(GenerationError, "语言规范"):
                request_response(GenerationConfig(DUMMY), "需求")
            (self.root / "language-spec.md").mkdir()
            with self.assertRaisesRegex(GenerationError, "语言规范"):
                request_response(GenerationConfig(DUMMY), "需求")
            network.assert_not_called()

    def test_invalid_specification_fails_closed_without_content_disclosure(self):
        resource = self.root / "language-spec.md"
        invalid = [
            b"", b" \n", b"FAKE_SENTINEL", b"\xffFAKE_SENTINEL",
            self.specification("FAKE_SENTINEL\x00").encode("utf-8"),
            self.specification("FAKE_SENTINEL\x1b").encode("utf-8"),
            self.specification("FAKE_SENTINEL", "bad-version").encode("utf-8"),
            self.specification("FAKE_SENTINEL\n规范版本：" + __version__).encode("utf-8"),
            self.specification("FAKE_SENTINEL").replace("规范版本：", "错误版本：").encode("utf-8"),
            self.specification("FAKE_SENTINEL").replace("# 如语言规范", "# 其他文档").encode("utf-8"),
            self.specification("").encode("utf-8"),
            b"x" * (MAX_LANGUAGE_SPEC_BYTES + 1),
        ]
        with patch("rulang.generation.resources.files", return_value=self.root), patch("rulang.generation.urlrequest.build_opener") as network:
            for raw in invalid:
                resource.write_bytes(raw)
                with self.subTest(length=len(raw)), self.assertRaises(GenerationError) as caught:
                    request_response(GenerationConfig(DUMMY), "需求")
                self.assertTrue(caught.exception.suppress_source)
                self.assertNotIn("FAKE_SENTINEL", str(caught.exception))
                self.assertNotIn(str(resource), str(caught.exception))
            network.assert_not_called()

    def test_mismatched_specification_version_fails_before_network(self):
        resource = self.root / "language-spec.md"
        resource.write_text(self.specification("FAKE_SENTINEL", "0.0.0"), encoding="utf-8")
        with patch("rulang.generation.resources.files", return_value=self.root), patch("rulang.generation.urlrequest.build_opener") as network:
            with self.assertRaisesRegex(GenerationError, "版本不一致") as caught:
                request_response(GenerationConfig(DUMMY), "需求")
            network.assert_not_called()
        self.assertNotIn("FAKE_SENTINEL", str(caught.exception))

    def test_specification_cannot_leak_configured_key(self):
        resource = self.root / "language-spec.md"
        resource.write_text(self.specification(DUMMY), encoding="utf-8")
        with patch("rulang.generation.resources.files", return_value=self.root), patch("rulang.generation.urlrequest.build_opener") as network:
            with self.assertRaises(GenerationError) as caught:
                request_response(GenerationConfig(DUMMY), "需求")
            network.assert_not_called()
        self.assertNotIn(DUMMY, str(caught.exception))

    def test_run_check_build_do_not_read_language_specification(self):
        with patch("rulang.generation.resources.files", side_effect=AssertionError("read generation spec")):
            for command in ("run", "check", "build"):
                with self.subTest(command=command), contextlib.redirect_stderr(io.StringIO()) as stderr:
                    self.assertEqual(main([command, str(self.document)]), 1)
                    self.assertIn("ru generate", stderr.getvalue())


class ExtractionTests(unittest.TestCase):
    def test_reasoning_and_multiple_text_fragments(self):
        result = response_for("显 ")
        result["output"].insert(0, {"type": "reasoning", "summary": [{"text": "not code"}]})
        result["output"][1]["content"].append({"type": "output_text", "text": "'你好'."})
        result["output_text"] = "ignored duplicate"
        self.assertEqual(extract_output_text(result), "显 '你好'.")
        self.assertEqual(extract_output_text({"status": "completed", "output_text": "显 1."}), "显 1.")

    def test_unfinished_empty_error_and_tool_responses(self):
        responses = [None, [], {}, {"status": "completed"}, response_for(""), response_for("  "), response_for(error={"message": "FAKE_SENTINEL"}), response_for(incomplete_details={"reason": "FAKE_SENTINEL"}), response_for(object="chat.completion"), response_for(output="bad"), response_for(output=[None])]
        responses += [response_for(status=status) for status in ("failed", "in_progress", "cancelled", "queued", "incomplete", None)]
        responses.append(response_for(output=[{"type": "reasoning", "status": "in_progress"}], output_text="显 1."))
        for kind in ("function_call", "web_search_call", "computer_call", "shell_call", "unknown"):
            responses.append(response_for(output=[{"type": kind, "arguments": "FAKE_SENTINEL"}], output_text="显 1."))
        for result in responses:
            with self.subTest(response=result), self.assertRaises(GenerationError) as caught:
                extract_output_text(result)
            self.assertNotIn("FAKE_SENTINEL", str(caught.exception))

    def test_malformed_message_and_refusal(self):
        for change in ({"role": "user"}, {"status": "in_progress"}, {"content": "bad"}, {"content": [{"type": "refusal", "refusal": "FAKE_SENTINEL"}]}, {"content": [{"type": "output_text", "text": None}]}):
            result = response_for()
            result["output"][0].update(change)
            with self.subTest(change=change), self.assertRaises(GenerationError):
                extract_output_text(result)

    def test_single_fences(self):
        for text in ("显 1.", "```ru\n显 1.\n```", "```\n显 1.\n```", "#+begin_src ru\n显 1.\n#+end_src"):
            with self.subTest(text=text):
                self.assertEqual(clean_generated_source(text), "显 1.\n")
        for text in ("```python\nprint(1)\n```", "```ru\n显 1.\n```\n解释", "```ru\n显 1.", "#+begin_src ru\n显 1.", "文档\n如是我言", ""):
            with self.subTest(text=text), self.assertRaises(GenerationError):
                clean_generated_source(text)


class LocalResponsesTests(TemporaryGeneration):
    def test_generated_optional_parameter_source_is_checked_without_execution(self):
        source = (ROOT / "examples" / "optional_parameters.ru").read_text(encoding="utf-8")
        # This failure would be observable if generation executed model output.
        source += "显 1/0.\n"
        for target, suffix in (("ru", ".ru"), ("js", ".js")):
            with self.subTest(target=target), MockResponses(response_for(source)) as server:
                output = generate(self.document, output=self.root / ("optional" + suffix),
                                  environ=self.local_env(server), target=target)
                self.assertTrue(output.is_file())
                self.assertEqual(len(server.requests), 1)
                if target == "ru":
                    self.assertEqual(output.read_text(encoding="utf-8"), source)
                else:
                    self.assertIn("use strict", output.read_text(encoding="utf-8"))

    def test_real_local_http_request_and_atomic_new_output(self):
        original = self.document.read_bytes()
        # A side effect would fail the test if the code were ever executed.
        with MockResponses(response_for("显 1/0.")) as server:
            output = generate(self.document, environ=self.local_env(server))
        self.assertEqual(output, self.root / "wish.generated.ru")
        self.assertEqual(output.read_text(encoding="utf-8"), "显 1/0.\n")
        self.assertEqual(self.document.read_bytes(), original)
        self.assertEqual(list(self.root.glob(".ru-generate-*")), [])
        self.assertEqual(len(server.requests), 1)
        path, headers, payload = server.requests[0]
        self.assertEqual(path, "/api/v1/responses")
        self.assertEqual(headers["Authorization"], "Bearer " + DUMMY)
        self.assertEqual(payload["model"], "mock-model")
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["store"])
        self.assertEqual(payload["tools"], [])
        self.assertEqual(payload["tool_choice"], "none")
        self.assertEqual(payload["input"][1]["content"][0]["text"], "# 输出\n显示一个问候。\n")
        self.assertNotIn(DUMMY, json.dumps(payload))

    def test_cli_success_no_automatic_execution(self):
        with MockResponses(response_for("显 1/0.")) as server:
            env = isolated_process_env(PATH=os.defpath, **self.local_env(server))
            result = subprocess.run([sys.executable, ROOT / "ru", "generate", self.document, "--timeout", "10"], env=env, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("未执行", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_output_collision_source_symlink_dependency_before_network(self):
        dependency = self.root / "dependency.ru"
        dependency.write_text("显 '保留'.", encoding="utf-8")
        link = self.root / "link.ru"
        link.symlink_to(dependency)
        broken = self.root / "broken.ru"
        broken.symlink_to(self.root / "absent.ru")
        with patch("rulang.generation.request_response", side_effect=AssertionError("network")):
            for output in (self.document, dependency, link, broken):
                with self.subTest(output=output), self.assertRaises(GenerationError):
                    generate(self.document, output, environ=self.env)
        self.assertEqual(dependency.read_text(), "显 '保留'.")
        self.assertTrue(broken.is_symlink())

    def test_publish_race_cannot_overwrite(self):
        output = self.root / "out.ru"
        original_link = os.link
        def race(source, target):
            output.write_text("先写入者", encoding="utf-8")
            return original_link(source, target)
        with MockResponses() as server, patch("rulang.generation.os.link", side_effect=race):
            with self.assertRaises(GenerationError):
                generate(self.document, output, environ=self.local_env(server))
        self.assertEqual(output.read_text(), "先写入者")
        self.assertEqual(list(self.root.glob(".ru-generate-*")), [])

    def test_invalid_code_structure_call_and_dependencies_not_saved(self):
        for code in ("显 ).", "破.", "得 1.", "算 平方 根 为 数: 得 根*根. 法 显 平方 1 2.", "模 取 外言 'missing.ru'.", "解释：\n```ru\n显 1.\n```", "# only comment"):
            with self.subTest(code=code), MockResponses(response_for(code)) as server:
                with self.assertRaises(GenerationError):
                    generate(self.document, environ=self.local_env(server))
            self.assertFalse((self.root / "wish.generated.ru").exists())
            self.assertEqual(list(self.root.glob(".ru-generate-*")), [])

    def test_dependencies_checked_relative_to_output_without_execution(self):
        (self.root / "lib.ru").write_text("显 1/0. 值 取 2.", encoding="utf-8")
        with MockResponses(response_for("模 取 外言 'lib.ru'. 显 模 其 值.")) as server:
            output = generate(self.document, environ=self.local_env(server))
        self.assertTrue(output.exists())
        self.assertEqual((self.root / "lib.ru").read_text(), "显 1/0. 值 取 2.")

    def test_http_errors_never_expose_body_or_retry(self):
        for status in (400, 401, 403, 404, 429, 500, 503):
            with self.subTest(status=status), MockResponses(status=status, raw=("FAKE_SENTINEL " + DUMMY).encode()) as server:
                with self.assertRaises(GenerationError) as caught:
                    generate(self.document, environ=self.local_env(server))
                self.assertEqual(len(server.requests), 1)
            self.assertIn(str(status), str(caught.exception))
            self.assertNotIn("FAKE_SENTINEL", str(caught.exception))
            self.assertNotIn(DUMMY, str(caught.exception))
            self.assertFalse((self.root / "wish.generated.ru").exists())

    def test_redirect_is_never_followed(self):
        with MockResponses() as target:
            with MockResponses(status=307, headers={"Location": target.base + "/responses"}) as server:
                with self.assertRaises(GenerationError):
                    generate(self.document, environ=self.local_env(server))
            self.assertEqual(target.requests, [])
            self.assertEqual(len(server.requests), 1)

    def test_malformed_json_utf8_and_response_size(self):
        for raw in (b"{FAKE_SENTINEL", b"\xff", b"[]", b'{"status":"completed","extra":NaN,"output_text":"fake"}', b'{"status":"completed","status":"failed"}', b"x" * (2 * 1024 * 1024 + 1)):
            with self.subTest(length=len(raw)), MockResponses(raw=raw) as server:
                with self.assertRaises(GenerationError) as caught:
                    generate(self.document, environ=self.local_env(server))
            self.assertNotIn("FAKE_SENTINEL", str(caught.exception))
            self.assertFalse((self.root / "wish.generated.ru").exists())

    def test_timeout_no_retry_and_no_partial_output(self):
        with MockResponses(delay=0.15) as server:
            with self.assertRaisesRegex(GenerationError, "超时"):
                generate(self.document, timeout=0.02, environ=self.local_env(server))
            self.assertEqual(len(server.requests), 1)
        self.assertFalse((self.root / "wish.generated.ru").exists())

    def test_invalid_timeout_never_requests(self):
        with MockResponses() as server:
            for timeout in (0, -1, 301, float("nan"), float("inf")):
                with self.subTest(timeout=timeout), self.assertRaises(GenerationError):
                    generate(self.document, timeout=timeout, environ=self.local_env(server))
            self.assertEqual(server.requests, [])

    def test_cancel_request_and_cancel_save_leave_no_output(self):
        with patch("rulang.generation.request_response", side_effect=KeyboardInterrupt):
            env = {**self.env, "RU_LLM_API_KEY": DUMMY}
            with patch.dict(os.environ, env, clear=True), contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(main(["generate", str(self.document)]), 130)
            self.assertIn("已取消", stderr.getvalue())
        with MockResponses() as server, patch("rulang.generation.os.link", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                generate(self.document, environ=self.local_env(server))
        self.assertFalse((self.root / "wish.generated.ru").exists())
        self.assertEqual(list(self.root.glob(".ru-generate-*")), [])

    def test_error_report_suppresses_documents_and_generated_source(self):
        self.document.write_text("FAKE_SENTINEL\n如是我言\n", encoding="utf-8")
        with MockResponses(response_for("显 FAKE_SENTINEL ).")) as server:
            with patch.dict(os.environ, self.local_env(server), clear=True), contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(main(["generate", str(self.document)]), 1)
        self.assertNotIn("FAKE_SENTINEL", stderr.getvalue())
        self.assertIn("语法／结构检查", stderr.getvalue())

    def test_known_key_not_transmitted_in_intent_or_saved_from_response(self):
        self.document.write_text("请打印 " + DUMMY + "\n如是我言", encoding="utf-8")
        with MockResponses() as server:
            with self.assertRaises(GenerationError):
                generate(self.document, environ=self.local_env(server))
            self.assertEqual(server.requests, [])
        self.document.write_text("显示问候\n如是我言", encoding="utf-8")
        with MockResponses(response_for("显 '" + DUMMY + "'.")) as server:
            with self.assertRaises(GenerationError) as caught:
                generate(self.document, environ=self.local_env(server))
        self.assertNotIn(DUMMY, str(caught.exception))
        self.assertFalse((self.root / "wish.generated.ru").exists())

    def test_bad_document_never_loads_config_or_network(self):
        for text in ("", "如是我言", "# text\n没有标记", "显 '未结束\n如是我言"):
            self.document.write_text(text, encoding="utf-8")
            with self.subTest(text=text), patch("rulang.generation.load_config", side_effect=AssertionError("config")), self.assertRaises(GenerationError):
                generate(self.document, environ=self.env)


if __name__ == "__main__":
    unittest.main()
