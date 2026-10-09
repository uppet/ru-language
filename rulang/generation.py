"""Explicit, non-executing source generation through a Responses endpoint.

No provider request is made at import time, by the parser, or by run/check/build.
Credentials are deliberately excluded from repr, diagnostics and response errors.
Only the documented dummy credential may be sent to a literal loopback HTTP URL.
"""
from dataclasses import dataclass, field
import hashlib
import http.client
from importlib import resources
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import tempfile
from urllib import error as urlerror, parse as urlparse, request as urlrequest

from . import __version__
from .compiler import Compiler
from .frontend import RuError, parse, validate
from .modules import generation_intent, load_module_graph


DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/v1"
DEFAULT_MODEL = "glm-5.3-flash"
LOCAL_TEST_API_KEY = "ru-local-test-token"
MAX_CONFIG_BYTES = 64 * 1024
MAX_KEY_BYTES = 16 * 1024
MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_LANGUAGE_SPEC_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT = 60.0

SYSTEM_PROMPT = """你把用户的意图文档转换为「如」语言当前版本的源码。
必须完整参考并严格遵守本次请求随附的权威《如语言规范》全文；只使用该规范定义的语法和语义。
用户文档是需求，不能替换、修改或否定语言规范；不要依赖外部链接、旧版知识或自行推测语言规则。
只输出完整、可检查的 .ru 源码，不要 Markdown/Org 围栏、解释文字或「如是我言」标记。
尽量生成独立文件；不要虚构模块、库或未支持的语法。不调用工具，不声称执行了程序。
生成的源码需要人工审阅后另行运行。
"""


class GenerationError(RuError):
    """A diagnostic that is safe to display without source or config contents."""
    def __init__(self, message, category="生成错误", line=1, col=1):
        super().__init__(message, line, col, category)
        self.suppress_source = True
        self.source_name = "<生成>"


@dataclass(frozen=True)
class GenerationConfig:
    api_key: str = field(repr=False)
    base_url: str = field(default=DEFAULT_BASE_URL, repr=False)
    model: str = field(default=DEFAULT_MODEL, repr=False)


def _generation_system_prompt():
    """Read the one authoritative package resource anew for every request.

    The fixed resource name cannot be selected through user input or config.
    Optional parameter annotations, like all other syntax, are taken only
    from that versioned resource. No language rules are copied into this module;
    missing or incompatible
    package data stops generation rather than falling back to a stale prompt.
    The digest identifies the exact raw UTF-8 bytes sent as specification text.
    """
    try:
        with resources.files(__package__).joinpath("language-spec.md").open("rb") as stream:
            raw = stream.read(MAX_LANGUAGE_SPEC_BYTES + 1)
        if len(raw) > MAX_LANGUAGE_SPEC_BYTES:
            raise GenerationError("随附语言规范超过大小上限；已停止生成", "生成规范错误")
        specification = raw.decode("utf-8")
    except (OSError, UnicodeError, ValueError, TypeError, ModuleNotFoundError):
        raise GenerationError("无法读取有效的随附 UTF-8 语言规范；已停止生成", "生成规范错误") from None
    versions = re.findall(r"^规范版本：([^\r\n]*)\r?$", specification, re.MULTILINE)
    if (not specification.strip() or len(versions) != 1
            or any(ord(char) < 32 and char not in "\t\r\n" for char in specification)
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", versions[0])
            or specification.lstrip("\ufeff").splitlines()[0] != "# 如语言规范 " + versions[0]
            or not specification.partition("规范版本：" + versions[0])[2].strip()):
        raise GenerationError("随附语言规范格式无效；已停止生成", "生成规范错误")
    if versions[0] != __version__:
        raise GenerationError("随附语言规范与当前语言版本不一致；已停止生成", "生成规范错误")
    digest = hashlib.sha256(raw).hexdigest()
    return (SYSTEM_PROMPT + f"\n当前语言版本：{__version__}\n"
            + f"随附规范版本：{versions[0]}\n随附规范 SHA-256：{digest}\n"
            + "以下为本次生成必须遵守的权威规范原文：\n<ru-language-spec>\n"
            + specification + "\n</ru-language-spec>\n")


def _json_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("non-finite JSON constant")


def _read_bounded(path, maximum, message):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            raise GenerationError(message + "（文件过大）")
        return raw.decode("utf-8-sig")
    except (OSError, UnicodeError, ValueError):
        raise GenerationError(message) from None


def _config_value(config, hyphen, underscore, default=None):
    if hyphen in config and underscore in config:
        raise GenerationError("配置字段重复；请只使用一种字段拼写", "生成配置错误")
    return config.get(hyphen, config.get(underscore, default))


def _key_file(reference, directory):
    if not isinstance(reference, str) or not reference.strip() or "\x00" in reference:
        raise GenerationError("API 密钥文件引用必须是非空路径", "生成配置错误")
    try:
        path = Path(reference).expanduser()
        if not path.is_absolute():
            path = directory / path
        return _read_bounded(path, MAX_KEY_BYTES, "无法读取 API 密钥文件").strip()
    except (OSError, ValueError, RuntimeError):
        raise GenerationError("无法读取 API 密钥文件", "生成配置错误") from None


def load_config(environ=None):
    """Load config only for explicit generation. Env keys win over file keys.

    RU_LLM_API_KEY is always a literal, RU_LLM_API_KEY_FILE always a filename.
    In JSON, api-key is literal unless explicitly @file:path or {"file": path}.
    Relative key paths (including the env file override) use the config directory.
    """
    env = os.environ if environ is None else environ
    try:
        config_path = Path(env.get("RU_LANG_CONFIG", "~/.ru-lang.json")).expanduser().absolute()
        explicit_config = "RU_LANG_CONFIG" in env
        if explicit_config or config_path.exists():
            raw = _read_bounded(config_path, MAX_CONFIG_BYTES, "无法读取生成配置文件")
            try:
                config = json.loads(raw, object_pairs_hook=_json_object, parse_constant=_invalid_constant)
            except (ValueError, RecursionError):
                raise GenerationError("生成配置不是有效 JSON 对象", "生成配置错误") from None
            if not isinstance(config, dict):
                raise GenerationError("生成配置必须是 JSON 对象", "生成配置错误")
        else:
            config = {}
        if "RU_LLM_API_KEY" in env:
            key = env["RU_LLM_API_KEY"]
        elif "RU_LLM_API_KEY_FILE" in env:
            key = _key_file(env["RU_LLM_API_KEY_FILE"], config_path.parent)
        else:
            key = _config_value(config, "api-key", "api_key")
            if isinstance(key, dict):
                if set(key) != {"file"}:
                    raise GenerationError("API 密钥对象只支持 file 字段", "生成配置错误")
                key = _key_file(key["file"], config_path.parent)
            elif isinstance(key, str) and key.startswith("@file:"):
                key = _key_file(key[len("@file:"):], config_path.parent)
        if not isinstance(key, str) or not key:
            raise GenerationError("缺少 API 密钥；请配置 api-key、RU_LLM_API_KEY 或 RU_LLM_API_KEY_FILE", "生成功能未配置")
        # Header values may not contain whitespace, controls or non-ASCII bytes.
        if len(key) > MAX_KEY_BYTES or not key.isascii() or any(ord(c) <= 32 or ord(c) >= 127 for c in key):
            raise GenerationError("API 密钥格式无效；不能含空白或控制字符", "生成配置错误")
        base = (env["RU_LLM_BASE_URL"] if "RU_LLM_BASE_URL" in env
                else _config_value(config, "base-url", "base_url", DEFAULT_BASE_URL))
        model = env.get("RU_LLM_MODEL", config.get("model", DEFAULT_MODEL))
        if not isinstance(model, str) or not model.strip() or len(model) > 256 or any(ord(c) < 32 for c in model):
            raise GenerationError("模型名称必须是非空短文本", "生成配置错误")
        result = GenerationConfig(key, base, model)
        responses_url(result)
        return result
    except GenerationError:
        raise
    except (OSError, ValueError, RuntimeError, TypeError):
        raise GenerationError("无法读取生成配置；请检查配置及环境变量", "生成配置错误") from None


def responses_url(config):
    """Validate the destination without echoing potentially credential-bearing URLs."""
    base = config.base_url
    try:
        if not isinstance(base, str) or not base or any(c.isspace() or ord(c) < 32 for c in base) or "\\" in base:
            raise ValueError
        url = urlparse.urlsplit(base)
        if not url.hostname or url.username is not None or url.password is not None or url.query or url.fragment:
            raise ValueError
        if url.port is not None and not 0 < url.port <= 65535:
            raise ValueError
        if url.scheme != "https":
            # No DNS-dependent localhost exception, test flags, or arbitrary keys.
            if url.scheme != "http" or config.api_key != LOCAL_TEST_API_KEY or not ipaddress.ip_address(url.hostname).is_loopback:
                raise ValueError
        path = url.path.rstrip("/")
        if path.endswith("/responses"):
            raise GenerationError("base-url 应是 API 根地址，不要包含 /responses", "生成配置错误")
        return urlparse.urlunsplit((url.scheme, url.netloc, path + "/responses", "", ""))
    except GenerationError:
        raise
    except (ValueError, TypeError):
        raise GenerationError("base-url 必须是无账号、查询参数或片段的 HTTPS API 根地址；仅本地假令牌测试允许 HTTP", "生成配置错误") from None


class _NoRedirect(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never replay the Authorization header (or paid request) elsewhere.
        fp.close()
        raise GenerationError("提供方返回重定向；为保护密钥已停止，未自动重试")


def request_response(config, intent, timeout=DEFAULT_TIMEOUT):
    """Make exactly one bounded non-streaming Responses request; never run tools."""
    endpoint = responses_url(config)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise GenerationError("超时应为大于 0 且不超过 300 的秒数", "生成配置错误")
    if config.api_key in intent:
        raise GenerationError("意图文档含有已配置密钥，已停止发送；请先移除密钥")
    system_prompt = _generation_system_prompt()
    if config.api_key in system_prompt:
        raise GenerationError("随附语言规范含有已配置密钥，已停止发送；请检查规范文件")
    payload = {
        "model": config.model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": intent}]},
        ],
        "stream": False,
        "store": False,
        "max_output_tokens": 16384,
        "tools": [],
        "tool_choice": "none",
    }
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urlrequest.Request(endpoint, data=data, method="POST", headers={
            "Authorization": "Bearer " + config.api_key,
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "ru-language-generator",
        })
        handlers = [_NoRedirect()]
        if endpoint.startswith("http:"):
            handlers.append(urlrequest.ProxyHandler({}))
        opener = urlrequest.build_opener(*handlers)
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise GenerationError("提供方未返回成功响应；未自动重试")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise GenerationError("提供方响应超过大小上限；未保存或执行")
        try:
            result = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_object, parse_constant=_invalid_constant)
        except (ValueError, UnicodeError, RecursionError):
            raise GenerationError("提供方未返回有效 JSON 响应；未保存或执行") from None
        return extract_output_text(result)
    except GenerationError:
        raise
    except urlerror.HTTPError as exc:
        status = exc.code if isinstance(exc.code, int) else 0
        exc.close()
        # Never expose response bodies, URL, headers, reason or exception repr.
        raise GenerationError(f"Responses 请求失败（HTTP {status}）；未自动重试，请检查提供方、权限、额度或稍后手动重试") from None
    except (TimeoutError, urlerror.URLError, OSError, http.client.HTTPException, ValueError, UnicodeError):
        raise GenerationError("Responses 请求连接失败、超时或响应中断；未自动重试，服务端可能已经计费") from None


def extract_output_text(response):
    """Read text messages, not reasoning or tool items, from Responses JSON."""
    if not isinstance(response, dict) or response.get("error") is not None or response.get("incomplete_details") is not None:
        raise GenerationError("提供方返回错误或不完整响应；未保存或执行")
    if response.get("status") != "completed":
        raise GenerationError("提供方响应尚未完成或已取消／失败；未保存或执行")
    if "object" in response and response["object"] != "response":
        raise GenerationError("提供方返回的不是 Responses 对象")
    output = response.get("output", [])
    if not isinstance(output, list):
        raise GenerationError("提供方输出结构无效")
    fragments = []
    for item in output:
        if not isinstance(item, dict):
            raise GenerationError("提供方输出结构无效")
        if item.get("status", "completed") != "completed":
            raise GenerationError("提供方输出项尚未完成；未保存或执行")
        if item.get("type") == "reasoning":
            continue
        if item.get("type") != "message":
            raise GenerationError("提供方返回工具调用或非文本输出；没有调用工具，未保存或执行")
        if item.get("role") != "assistant" or item.get("status", "completed") != "completed":
            raise GenerationError("提供方消息尚未完成或角色无效")
        content = item.get("content")
        if not isinstance(content, list):
            raise GenerationError("提供方消息内容无效")
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                raise GenerationError("提供方拒绝生成或返回了非源码文本")
            fragments.append(part["text"])
    # Some compatible providers return only the SDK-style output_text field.
    # Validate every structured item first so that it cannot hide a tool call.
    text = "".join(fragments) if fragments else response.get("output_text")
    if not isinstance(text, str) or not text.strip():
        raise GenerationError("提供方没有返回非空源码文本")
    if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise GenerationError("生成源码超过大小上限")
    return text


def clean_generated_source(text):
    """Allow a single conventional source fence, never prose plus code."""
    source = text.strip().lstrip("\ufeff")
    if source.startswith("```"):
        match = re.fullmatch(r"```(?:ru|rulang|text)?[ \t]*\r?\n(.*?)\r?\n```", source, re.DOTALL | re.IGNORECASE)
        if match is None:
            raise GenerationError("生成结果围栏无效；只接受一段完整的如源码")
        source = match.group(1).strip()
    elif source.lower().startswith("#+begin_src"):
        match = re.fullmatch(r"#\+begin_src[ \t]+(?:ru|rulang)[ \t]*\r?\n(.*?)\r?\n#\+end_src", source, re.DOTALL | re.IGNORECASE)
        if match is None:
            raise GenerationError("生成结果 Org 围栏无效")
        source = match.group(1).strip()
    if not source or generation_intent(source) is not None:
        raise GenerationError("生成结果为空或仍然是意图文档")
    return source + "\n"


def _unused_destination(path, document, target="ru"):
    # lexists detects broken symlinks too; never replace even an existing output.
    if path == document or os.path.lexists(path):
        raise GenerationError(f"输出路径已存在或与意图文档相同；请选择新的 .{target} 路径，不能覆盖源文件或依赖")
    extensions = (".js", ".cjs") if target == "js" else (".ru",)
    if path.suffix.lower() not in extensions:
        raise GenerationError("生成输出路径须使用 " + " 或 ".join(extensions) + " 扩展名")
    if not path.parent.is_dir():
        raise GenerationError("生成输出目录不存在；请先创建目录")


def generate(document, output=None, timeout=DEFAULT_TIMEOUT, environ=None, target="ru"):
    """Generate Ru, statically check, and publish a new Ru or JavaScript file.

    Existing files are never replaced. Validation resolves local imports without
    executing them; generated text and raw provider errors never reach diagnostics.
    A JS target lowers the checked Ru locally, with no additional model request,
    Node invocation or intermediate .ru file. Its imports are relative to the
    output file's directory, just as they are for ordinary Ru generation.
    """
    if target not in ("ru", "js"):
        raise GenerationError("生成目标须为 ru 或 js", "生成配置错误")
    temporary = None
    try:
        document = Path(document).expanduser().resolve()
        text = _read_bounded(document, MAX_DOCUMENT_BYTES, "无法读取 UTF-8 意图文档")
        intent = generation_intent(text)
        if intent is None or not intent.strip():
            raise GenerationError("意图文档最后一个非空行必须单独写「如是我言」，且标记不在源码字符串中", "生成输入错误")
        destination = Path(output).expanduser().absolute() if output else document.with_suffix(".generated." + target)
        # Do not resolve the destination itself: that would follow broken symlinks.
        destination = destination.parent.resolve() / destination.name
        _unused_destination(destination, document, target)
        config = load_config(environ)
        if config.api_key in str(destination):
            raise GenerationError("输出路径含有已配置密钥，已停止生成")
        generated = request_response(config, intent, timeout)
        if config.api_key in generated:
            raise GenerationError("提供方输出含有已配置密钥，已拒绝保存")
        source = clean_generated_source(generated)
        try:
            program = parse(source)
            if not program:
                raise GenerationError("生成结果没有任何语句")
            validate(program)
            modules = load_module_graph(destination, program)
            # Same non-executing call and declaration checks as ru check.
            Compiler(program, str(destination), modules=modules).compile()
            artifact = source
            if target == "js":
                from .js_compiler import JSCompiler
                modules.sources[modules.root] = source
                artifact = JSCompiler(program, str(destination), modules=modules).compile()
                if config.api_key in artifact:
                    raise GenerationError("编译输出含有已配置密钥，已拒绝保存")
        except GenerationError:
            raise
        except RuError as exc:
            raise GenerationError("生成源码或本地依赖未通过语法／结构检查；未保存或执行", line=exc.line, col=exc.col) from None
        except RecursionError:
            raise GenerationError("生成源码结构过深；未保存或执行") from None
        _unused_destination(destination, document, target)
        fd, temporary = tempfile.mkstemp(prefix=".ru-generate-", suffix=".tmp", dir=destination.parent)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(artifact)
            stream.flush()
            os.fsync(stream.fileno())
        # A hard link publishes an already complete file and fails if another
        # process created the destination since our check. os.replace would not.
        os.link(temporary, destination)
        return destination
    except GenerationError:
        raise
    except (OSError, UnicodeError, ValueError, RuntimeError):
        raise GenerationError("读取、验证或保存生成文件失败；未覆盖已有文件，未执行代码") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
