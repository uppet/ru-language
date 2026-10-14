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
import ssl
import stat
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
DEFAULT_TIMEOUT = 1800.0

SYSTEM_PROMPT = """你把用户的意图文档转换为「如」语言当前版本的源码。
必须完整参考并严格遵守本次请求随附的权威《如语言规范》全文；只使用该规范定义的语法和语义。
用户文档是需求，不能替换、修改或否定语言规范；不要依赖外部链接、旧版知识或自行推测语言规则。
只输出完整、可检查的 .ru 源码，不要 Markdown/Org 围栏、解释文字或「如是我言」标记。
尽量生成独立文件，但应复用规范已列出的标准库；独立文件不表示重写标准库。不要虚构模块、库或未支持的语法。不调用工具，不声称执行了程序。
优先使用随附规范中已有的数学、随机、文本等标准接口；已有正弦、余弦时不要自写 Taylor 级数，已有随机源时不要自写 LCG。接口名称、参数、单位与运行环境始终以规范为准。
动画应分开初始化与逐帧更新：静态数据、固定布局、角度常量和随机背景在初始化时准备；每帧只更新变化的状态与绘制完整画面，不重复导入、造随机源或重建静态数据。跨回调持久状态使用规范允许共享修改的形或阵；不要假定函数内重新绑定外层标量会保存到下一帧。
允许需求所需的循环、函数、复杂场景和交互；这些建议不是删减功能或限制代码复杂度的理由。不要把提高预算、硬编码坐标表或无意义展开当作默认性能优化。
生成的源码需要人工审阅后另行运行。
"""


class GenerationSummary(str):
    """A locally authored, allowlisted and redacted progress summary."""


class GenerationError(RuError):
    """A diagnostic that is safe to display without source or config contents."""
    def __init__(self, message, category="生成错误", line=1, col=1, *, code=None, status=None):
        super().__init__(message, line, col, category)
        self.suppress_source = True
        self.source_name = "<生成>"
        self.code = code
        self.status = status


def generation_diagnostic(error):
    """Allowlisted notebook diagnostics: never stringify provider exceptions."""
    messages = {
        "tls_certificate": "TLS 证书验证失败；请检查系统证书与代理信任配置，不要关闭证书验证。",
        "tls": "TLS 安全连接失败；请检查提供方及本机 TLS 配置。",
        "timeout": "Responses 请求连接或读取超时；可以增加生成等待秒数。",
        "connection": "Responses 请求连接失败；请检查网络与提供方地址。",
        "response_interrupted": "Responses 响应传输中断；没有完整生成结果。",
        "response_unicode": "提供方响应或生成文本包含无效 Unicode；无法提取完整源码。",
        "timeout_range": "当前系统无法使用该超时数值；请设置较小的有限正数。",
        "incomplete_max_output_tokens": "提供方响应不完整：达到输出 token 上限（max_output_tokens）；可调整输出预算或缩小单次需求，增加等待时间不会提高 token 上限。",
        "incomplete_content_filter": "提供方响应不完整：content_filter（内容过滤）。",
        "incomplete": "提供方响应不完整；未提供可识别的具体原因。",
        "response_failed": "提供方 Responses 状态为 failed（失败）。",
        "response_cancelled": "提供方 Responses 状态为 cancelled（已取消）。",
        "response_pending": "提供方 Responses 尚未完成（queued 或 in_progress）。",
        "response_status": "提供方 Responses 未返回可识别的完成状态。",
        "response_no_text": "提供方未返回可识别的非空助手文本；不能据此判断隐藏推理或 token 使用情况。",
    }
    if error.code == "http":
        status = error.status
        message = f"Responses 请求失败（HTTP {status}）。" if type(status) is int and 100 <= status <= 599 else "Responses 请求失败（HTTP 错误）。"
    else:
        message = messages.get(error.code, "生成请求失败或结果无效；请检查提示、提供方权限及额度。")
    return message + "未自动重试，提供方可能已经计费；未保存或执行。"


def _communication_error(code, status=None):
    error = GenerationError("", "生成通讯错误", code=code, status=status)
    error.message = generation_diagnostic(error)
    error.args = (error.message,)
    return error


@dataclass(frozen=True)
class GenerationConfig:
    api_key: str = field(repr=False)
    base_url: str = field(default=DEFAULT_BASE_URL, repr=False)
    model: str = field(default=DEFAULT_MODEL, repr=False)
    max_output_tokens: int | None = field(default=None, repr=False)


def validate_max_output_tokens(value):
    """An explicit budget is a positive bounded integer, never a bool/float."""
    if type(value) is not int or not 1 <= value <= 2147483647:
        raise GenerationError("输出 token 预算须为 1 至 2147483647 的整数；提供方可能有更低上限", "生成配置错误", code="max_output_tokens_config")
    return value


def parse_max_output_tokens(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,10}", value):
        raise GenerationError("输出 token 预算须为 ASCII 十进制正整数", "生成配置错误", code="max_output_tokens_config")
    return validate_max_output_tokens(int(value))


def max_output_tokens_argument(value):
    import argparse
    try:
        return parse_max_output_tokens(value)
    except GenerationError as error:
        raise argparse.ArgumentTypeError(error.message) from None


def generation_system_prompt(target="cli"):
    """Read the one authoritative package resource anew for every request.

    The fixed resource name cannot be selected through user input or config.
    Scoped statement blocks, assignment aliases, and all other syntax are
    taken only from that versioned resource. No language rules are copied into this module;
    missing or incompatible
    package data stops generation rather than falling back to a stale prompt.
    The digest identifies the exact raw UTF-8 bytes sent as specification text.
    """
    if target not in ("cli", "rushu", "ruguan", "rushu-browser-js", "ruguan-browser-js"):
        raise GenerationError("未知生成运行环境", "生成配置错误")
    if target in ("rushu-browser-js", "ruguan-browser-js"):
        environment = ("本次运行环境：如书显式 JS 加速代码格（browser-js）。如源码由本机编译为 JavaScript，"
                       "在每次新建的独立浏览器 Worker 中执行；支持如观和 1～60 FPS 的帧率请求，"
                       "实际帧率须实测。所有变量、导入、初始化与回调必须放在同一格；"
                       "不读取或共享 Python 会话及其他 JS 格的状态。不得使用交互输入、文件、网络或命令行能力。"
                       "浏览器无可强制的 64 MiB Worker 堆内存限制，不得宣称安全沙箱或固定性能。")
    elif target in ("rushu", "ruguan"):
        environment = ("本次运行环境：如书 Python 代码格（默认）。需要绘图或交互时可使用如观；"
                       "创建画布与注册回调须在同一格。Python 图形帧率为 1～30；除非用户明确选择"
                       "「JS 加速」，不要使用浏览器 JS 专属的 31～60 FPS，也不要假定独立 Worker 状态。"
                       "可选 browser-js 的能力与限制见完整规范；CLI --target js 不提供如观宿主。")
    else:
        environment = ("本次运行环境：普通命令行（含 C／JavaScript 编译）。不提供如观画布宿主，"
                       "不得生成依赖如观的程序；可用文本呈现结果。")

    if target in ("ruguan", "ruguan-browser-js"):
        environment += ("\n本次任务聚焦如观图形与交互。请重点阅读下方规范的「如观二维图形」及"
                        "「文本、数学、随机与阵实用成员」章节，使用其中完整接口与示例。"
                        "创建画布、初始化共享状态及注册回调放在同一代码格；每帧绘制完整画面。"
                        "文字居中优先使用规范中的文字对齐与锚点，不靠字符数猜宽度；不要虚构文字测量接口。"
                        "时间驱动动画使用经过秒／间隔秒，不把帧数除目标帧率当真实时间；每帧回调仍只有帧序号一参。"
                        "时间读取在回调内冻结，不用忙循环等待；跨帧状态写入共享形或阵，暂停进度需记录相对起点。"
                        "物理积分可显式限制自己的步长，原始间隔秒仍保留真实间隔。"
                        "形状旋转与缩放优先使用规范中的画布变换，填充多边形使用原生接口；"
                        "圆弧与份额图优先使用原生弧／扇形，六个参数均必需，外接框加始角与带符号转角，角度为弧度。"
                        "弧只描边；部分扇形含两条半径边；零转角保留命令，绝对转角至少一周只画无辐条的整椭圆。"
                        "不要用折线近似或虚构弦形、贝塞尔曲线、路径构造器；非圆椭圆使用参数角，负缩放会镜像方向。"
                        "轨道与角度计算复用数学库，按规范处理弧度和画布坐标；"
                        "随机场景复用独立随机源，并区分初始化采样与逐帧更新。"
                        "全部语法、接口签名、回调参数、生命周期与预算仍以下方同一份规范为准。")
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
    return (SYSTEM_PROMPT + environment + "\n" + f"\n当前语言版本：{__version__}\n"
            + f"随附规范版本：{versions[0]}\n随附规范 SHA-256：{digest}\n"
            + "以下为本次生成必须遵守的权威规范原文：\n<ru-language-spec>\n"
            + specification + "\n</ru-language-spec>\n")


def _generation_system_prompt(target="cli"):
    """Compatibility wrapper; generation and exports share the public builder."""
    return generation_system_prompt(target)


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


def load_config(environ=None, max_output_tokens=None):
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
        if max_output_tokens is not None:
            budget = validate_max_output_tokens(max_output_tokens)
        elif "RU_LLM_MAX_OUTPUT_TOKENS" in env:
            budget = parse_max_output_tokens(env["RU_LLM_MAX_OUTPUT_TOKENS"])
        elif "max-output-tokens" in config or "max_output_tokens" in config:
            budget = validate_max_output_tokens(_config_value(config, "max-output-tokens", "max_output_tokens"))
        else:
            budget = None
        result = GenerationConfig(key, base, model, budget)
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


def request_response(config, intent, timeout=DEFAULT_TIMEOUT, progress=None, *, runtime_target="cli", trace=None):
    """Make exactly one bounded non-streaming Responses request; never run tools."""
    if trace:
        trace.protect(config.api_key)
        trace.emit("preparation", "准备非流式 Responses 请求；不记录请求正文、配置或隐藏推理。")
    endpoint = responses_url(config)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or not timeout > 0:
        raise GenerationError("超时应为有限且大于 0 的秒数", "生成配置错误")
    if config.api_key in intent:
        raise GenerationError("意图文档含有已配置密钥，已停止发送；请先移除密钥")
    system_prompt = _generation_system_prompt(runtime_target)
    if config.api_key in system_prompt:
        raise GenerationError("随附语言规范含有已配置密钥，已停止发送；请检查规范文件")
    budget = config.max_output_tokens
    if budget is not None:
        validate_max_output_tokens(budget)
    # CLI summaries use the same secret redactor as notebook diagnostics.
    from .generation_trace import GenerationTrace
    diagnostic_trace = GenerationTrace("request")
    diagnostic_trace.protect(config.api_key)
    def report(stage, detail):
        if trace:
            trace.emit(stage, detail)
        if progress:
            progress(GenerationSummary(diagnostic_trace.redact(detail)))
    report("request_budget", "请求输出预算：max_output_tokens=" + str(budget) if budget is not None
           else "请求输出预算：未发送 max_output_tokens；提供方默认值未知，并非无限。")
    payload = {
        "model": config.model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": intent}]},
        ],
        "stream": False,
        "store": False,
        "tools": [],
        "tool_choice": "none",
    }
    if budget is not None:
        payload["max_output_tokens"] = budget
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
        if progress:
            progress("发送生成请求")
            progress("等待提供方响应")
        if trace:
            trace.emit("request_sent", "开始一次 HTTP POST 请求；未启用自动重试。")
            trace.emit("waiting", "等待完整非流式响应；此阶段没有可见的逐词输出。")
        with opener.open(request, timeout=timeout) as response:
            if trace:
                _trace_http(trace, response.status, response.headers)
            if response.status != 200:
                raise _communication_error("http", response.status)
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if progress:
            progress("收到提供方响应")
        if len(raw) > MAX_RESPONSE_BYTES:
            raise GenerationError("提供方响应超过大小上限；未保存或执行")
        try:
            result = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_object, parse_constant=_invalid_constant)
        except UnicodeError:
            raise GenerationError("提供方响应不是有效 UTF-8；未保存或执行", code="response_unicode") from None
        except (ValueError, RecursionError):
            if trace:
                trace.emit("response_parse", "响应不是有效 UTF-8 JSON；不保留不透明原始正文。")
            raise GenerationError("提供方未返回有效 JSON 响应；未保存或执行") from None
        if trace:
            trace.emit("response_parse", "已解析 JSON；继续检查 Responses 结构。")
        for stage, detail in response_metadata(result):
            report(stage, detail)
        if trace:
            _trace_response(trace, result)
        return extract_output_text(result)
    except GenerationError as error:
        if trace:
            trace.emit("response_validation", str(error))
        raise
    except urlerror.HTTPError as exc:
        status = exc.code if isinstance(exc.code, int) else 0
        if trace:
            _trace_http(trace, status, exc.headers)
            try:
                raw_error = exc.read(65537)
                if len(raw_error) <= 65536:
                    _trace_error(trace, json.loads(raw_error.decode("utf-8")))
            except (ValueError, UnicodeError, OSError, RecursionError, http.client.HTTPException):
                trace.emit("response_parse", "HTTP 错误正文无法安全解析；未记录原始正文。")
        exc.close()
        # Exception text remains fixed; optional trace has allowlisted fields only.
        raise _communication_error("http", status) from None
    except ssl.SSLCertVerificationError:
        raise _communication_error("tls_certificate") from None
    except ssl.SSLError:
        raise _communication_error("tls") from None
    except urlerror.URLError as exc:
        reason = exc.reason
        code = ("tls_certificate" if isinstance(reason, ssl.SSLCertVerificationError)
                else "tls" if isinstance(reason, ssl.SSLError)
                else "timeout" if isinstance(reason, TimeoutError)
                else "connection")
        raise _communication_error(code) from None
    except TimeoutError:
        raise _communication_error("timeout") from None
    except (http.client.HTTPException, ConnectionResetError, ConnectionAbortedError):
        raise _communication_error("response_interrupted") from None
    except OverflowError:
        raise _communication_error("timeout_range") from None
    except (OSError, ValueError, UnicodeError):
        raise _communication_error("connection") from None




def _trace_http(trace, status, headers):
    detail = "HTTP " + (str(status) if isinstance(status, int) else "未知状态")
    # Never copy arbitrary headers, URLs or provider reason phrases.
    request_id = headers.get("x-request-id", "") if headers else ""
    if isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id):
        detail += "; request_id=" + request_id
    trace.emit("http_response", detail)


def _trace_error(trace, response):
    if not isinstance(response, dict):
        return
    error = response.get("error")
    if isinstance(error, dict):
        fields = [name + ": " + error[name] for name in ("type", "code", "message")
                  if isinstance(error.get(name), str)]
        if fields:
            trace.emit("provider_error", "提供方返回的错误字段（已脱敏）", "\n".join(fields))


def _visible_response_parts(response):
    fragments, refusals = [], []
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message" or item.get("role") != "assistant":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    fragments.append(part["text"])
                elif part.get("type") == "refusal" and isinstance(part.get("refusal"), str):
                    refusals.append(part["refusal"])
    if not fragments and isinstance(response.get("output_text"), str):
        fragments.append(response["output_text"])
    return fragments, refusals


def response_metadata(response):
    """Only fixed labels and safe integer counts; never provider text/reasoning."""
    if not isinstance(response, dict):
        return []
    fields = []
    usage = response.get("usage")
    if isinstance(usage, dict):
        for name in ("input_tokens", "output_tokens", "total_tokens"):
            value = usage.get(name)
            if type(value) is int and 0 <= value <= 9007199254740991:
                fields.append(name + "=" + str(value))
        for container, name in (("input_tokens_details", "cached_tokens"), ("output_tokens_details", "reasoning_tokens")):
            details = usage.get(container)
            value = details.get(name) if isinstance(details, dict) else None
            if type(value) is int and 0 <= value <= 9007199254740991:
                fields.append(name + "=" + str(value))
    usage_detail = "提供方 usage：" + (", ".join(fields) if fields else "未提供可识别的安全数值计数。")
    counts = {}
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            kind = item.get("type") if isinstance(item, dict) else None
            kind = kind if isinstance(kind, str) and kind in ("message", "reasoning", "function_call", "web_search_call", "file_search_call", "computer_call", "image_generation_call", "code_interpreter_call", "mcp_call") else "other"
            counts[kind] = counts.get(kind, 0) + 1
    summary = ", ".join(name + "=" + str(counts[name]) for name in sorted(counts)) or "无可识别输出项"
    fragments, _ = _visible_response_parts(response)
    visible = any(text.strip() for text in fragments)
    return [("response_usage", usage_detail), ("output_summary", "输出项类型：" + summary + "；" +
             ("已返回可识别助手文本。" if visible else "未返回可识别的非空助手文本；不能据此判断隐藏推理或 token 使用情况。"))]


def _trace_response(trace, response):
    if not isinstance(response, dict):
        return
    _trace_error(trace, response)
    status = response.get("status")
    if status in ("completed", "incomplete", "failed", "cancelled", "queued", "in_progress"):
        trace.emit("response_status", "Responses 状态：" + status)
    if response.get("incomplete_details") is not None or status == "incomplete":
        details = response.get("incomplete_details")
        reason = details.get("reason") if isinstance(details, dict) else None
        trace.emit("incomplete", "提供方响应不完整" + ("：" + reason if reason in ("max_output_tokens", "content_filter") else "。"))
    fragments, refusals = _visible_response_parts(response)
    if fragments:
        trace.emit("model_text", "提供方实际返回的助手文本（已脱敏；尚未提取或检查）", "".join(fragments))
    if refusals:
        trace.emit("refusal", "提供方实际返回的拒绝说明（已脱敏）", "\n".join(refusals))


def extract_output_text(response):
    """Read text messages, not reasoning or tool items, from Responses JSON."""
    if not isinstance(response, dict):
        raise GenerationError("提供方响应结构无效；未保存或执行")
    status = response.get("status")
    if response.get("incomplete_details") is not None or status == "incomplete":
        details = response.get("incomplete_details")
        reason = details.get("reason") if isinstance(details, dict) else None
        code = "incomplete_" + reason if reason in ("max_output_tokens", "content_filter") else "incomplete"
        raise _communication_error(code)
    if status != "completed":
        code = ("response_" + status if status in ("failed", "cancelled") else
                "response_pending" if status in ("queued", "in_progress") else "response_status")
        raise _communication_error(code)
    if response.get("error") is not None:
        raise GenerationError("提供方返回错误响应；未保存或执行")
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
        raise _communication_error("response_no_text")
    try:
        encoded = text.encode("utf-8")
    except UnicodeError:
        raise GenerationError("提供方生成文本包含无效 Unicode；未保存或执行", code="response_unicode") from None
    if len(encoded) > MAX_DOCUMENT_BYTES:
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


def _destination_format(path, target):
    extensions = (".js", ".cjs") if target == "js" else (".ru",)
    if path.suffix.lower() not in extensions:
        raise GenerationError("生成输出路径须使用 " + " 或 ".join(extensions) + " 扩展名")
    if not path.parent.is_dir():
        raise GenerationError("生成输出目录不存在；请先创建目录")


def _unused_destination(path, document, target="ru"):
    # lexists detects broken symlinks too; never replace even an existing output.
    if path == document or os.path.lexists(path):
        raise GenerationError(f"输出路径已存在或与意图文档相同；请选择新的 .{target} 路径，不能覆盖源文件或依赖")
    _destination_format(path, target)


def _file_identity(status):
    return status.st_dev, status.st_ino


def _replaceable_destination(path, protected_paths, protected_identities, target):
    """Permit only a regular artifact, never an input, dependency, or symlink.

    Check both current identities and identities captured before the request or
    after graph loading. This also protects hard links if a protected pathname
    changes while generation is in progress. lstat never follows the output.
    """
    if path in protected_paths:
        raise GenerationError("不能覆盖意图文档或本地依赖；请为生成产物选择其他路径")
    _destination_format(path, target)
    try:
        status = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(status.st_mode):
        raise GenerationError("--force 只允许替换普通产物文件，不能覆盖符号链接、目录或特殊文件")
    identity = _file_identity(status)
    if (identity in protected_identities
            or any(identity == _file_identity(protected.stat()) for protected in protected_paths)):
        raise GenerationError("不能覆盖意图文档或本地依赖的硬链接；请为生成产物选择其他路径")


def generate(document, output=None, timeout=DEFAULT_TIMEOUT, environ=None, target="ru", stdout=False, progress=None, force=False, max_output_tokens=None):
    """Generate Ru, statically check, and atomically publish Ru or JavaScript.

    Existing regular artifacts are replaced only with force=True, after all
    checks succeed; input documents, dependencies and symlinks stay protected.
    Validation resolves local imports without executing them; generated text and
    raw provider errors never reach diagnostics.
    A JS target lowers the checked Ru locally, with no additional model request,
    Node invocation or intermediate .ru file. Its imports are relative to the
    output file's directory, just as they are for ordinary Ru generation.
    stdout=True returns the fully checked artifact without creating any file;
    local imports then resolve relative to the intent document's directory.
    """
    if target not in ("ru", "js"):
        raise GenerationError("生成目标须为 ru 或 js", "生成配置错误")
    if stdout and output is not None:
        raise GenerationError("--stdout 不能与 -o / --output 同时使用", "生成配置错误")
    if stdout and force:
        raise GenerationError("--stdout 不能与 --force 同时使用", "生成配置错误")
    temporary = None
    temporary_fd = None
    try:
        if progress:
            progress("读取意图文档")
        document = Path(document).expanduser().resolve()
        text = _read_bounded(document, MAX_DOCUMENT_BYTES, "无法读取 UTF-8 意图文档")
        intent = generation_intent(text)
        if intent is None or not intent.strip():
            raise GenerationError("意图文档最后一个非空行必须单独写「如是我言」，且标记不在源码字符串中", "生成输入错误")
        destination = (document if stdout else
                       Path(output).expanduser().absolute() if output else document.with_suffix(".generated." + target))
        # Do not resolve the destination itself: that would follow broken symlinks.
        destination = destination.parent.resolve() / destination.name
        protected_paths = {document}
        protected_identities = {_file_identity(document.stat())} if force else set()
        if not stdout:
            if force:
                _replaceable_destination(destination, protected_paths, protected_identities, target)
            else:
                _unused_destination(destination, document, target)
        if progress:
            progress("检查生成配置")
        config = load_config(environ, **({"max_output_tokens": max_output_tokens} if max_output_tokens is not None else {}))
        if config.api_key in str(destination):
            raise GenerationError("输出路径含有已配置密钥，已停止生成")
        generated = request_response(config, intent, timeout, **({"progress": progress} if progress else {}))
        if config.api_key in generated:
            raise GenerationError("提供方输出含有已配置密钥，已拒绝保存")
        if progress:
            progress("检查生成源码")
        source = clean_generated_source(generated)
        try:
            program = parse(source)
            if not program:
                raise GenerationError("生成结果没有任何语句")
            validate(program)
            modules = load_module_graph(destination, program)
            if force:
                dependencies = {Path(path) for path in modules if path != modules.root}
                protected_paths.update(dependencies)
                protected_identities.update(_file_identity(path.stat()) for path in dependencies)
                _replaceable_destination(destination, protected_paths, protected_identities, target)
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
        if progress:
            progress("生成源码检查完成")
        if stdout:
            return artifact
        if force:
            _replaceable_destination(destination, protected_paths, protected_identities, target)
        else:
            _unused_destination(destination, document, target)
        if progress:
            progress("发布生成文件")
        temporary_fd, temporary = tempfile.mkstemp(prefix=".ru-generate-", suffix=".tmp", dir=destination.parent)
        stream = os.fdopen(temporary_fd, "w", encoding="utf-8", newline="\n")
        temporary_fd = None  # The stream owns the descriptor from this point.
        with stream:
            stream.write(artifact)
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            # Recheck after callbacks and temporary-file I/O, immediately before
            # replacing the directory entry. Never truncate the existing file.
            _replaceable_destination(destination, protected_paths, protected_identities, target)
            os.replace(temporary, destination)
        else:
            # A hard link publishes an already complete file and fails if another
            # process created the destination since our check. os.replace would not.
            os.link(temporary, destination)
        return destination
    except GenerationError:
        raise
    except (OSError, UnicodeError, ValueError, RuntimeError):
        raise GenerationError("读取、验证或保存生成文件失败；未覆盖已有文件，未执行代码") from None
    finally:
        if temporary_fd is not None:
            try:
                os.close(temporary_fd)
            except OSError:
                pass
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
