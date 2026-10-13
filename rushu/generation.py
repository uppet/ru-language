"""Explicit notebook generation, isolated from sessions and filesystem imports."""
import math
import re
import threading
from urllib.parse import urlsplit

from rulang.browser_compiler import compile_browser
from rulang.frontend import RuError, parse, validate
from rulang.generation import (DEFAULT_TIMEOUT, GenerationError,
                               clean_generated_source, generation_diagnostic,
                               load_config, request_response)
from rulang.modules import generation_intent

from .kernel import KernelError, MAX_SOURCE

# Process-wide, including separate NotebookServer instances. The worker retains
# this lock after a client disconnect or response deadline until the paid call
# actually finishes. Browser cancellation cannot start a duplicate paid request.
_GENERATION_SLOT = threading.Lock()
CONFIG_HELP = "请在启动如书前配置 RU_LLM_API_KEY 或 RU_LLM_API_KEY_FILE，或 ~/.ru-lang.json 的 api-key，并检查提供方配置。"


def validate_generation_timeout(timeout):
    if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
            or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("生成超时须为有限且大于 0 的秒数")
    return timeout


def _host(config):
    host = urlsplit(config.base_url).hostname or ""
    return "已配置提供方" if config.api_key in host else host


def configuration():
    try:
        config = load_config()
        return {"configured": True, "provider_host": _host(config),
                "message": "仅在明确点击生成后发送所选提示与草稿。"}
    except Exception:
        # Configuration may include secrets in URLs, models, filenames or keys.
        return {"configured": False, "provider_host": None, "message": CONFIG_HELP}


def _validate(source, runtime_target="python"):
    try:
        program = parse(source)
        if not program:
            return {"valid": False, "message": "生成源码没有可检查的语句；尚未执行。"}
        validate(program)
        if runtime_target == "browser-js":
            # Compile and discard: reuse every browser graph/capability/lowering
            # check without starting a runtime or reading external imports.
            compile_browser(source)
            return {"valid": True, "message": "已通过浏览器 JS 编译与能力检查；仅检查内置标准外言，尚未执行。"}
        return {"valid": True, "message": "已通过语法与结构检查；未读取或检查外言依赖，尚未执行。"}
    except RuError as error:
        # Never echo arbitrary source text, import paths or exception details.
        # Locations in bundled modules must not masquerade as generated source.
        from rulang.browser_compiler import ROOT
        in_source = getattr(error, "source_name", ROOT) == ROOT
        browser = runtime_target == "browser-js"
        message = "生成源码未通过语法或结构检查；尚未执行。"
        if browser:
            message = {
                "能力错误": "生成源码使用浏览器 JS 不支持的能力或超过编译上限；请修改源码或选择 Python，尚未执行。",
                "模块错误": "生成源码的外言不符合浏览器 JS 导入规则；请检查标准外言名称，尚未执行。",
                "编译错误": "生成源码未通过浏览器 JS 编译检查；请检查定义与调用，尚未执行。",
            }.get(error.category, "生成源码未通过浏览器 JS 语法或结构检查；尚未执行。")
        return {"valid": False,
                "message": message,
                "category": error.category if error.category in ("语法错误", "结构错误", "能力错误", "模块错误", "编译错误") else "源码检查错误",
                "source": "generated" if in_source else "bundled-module",
                "line": error.line if in_source else None,
                "col": error.col if in_source else None}
    except RecursionError:
        return {"valid": False, "message": "生成源码结构过深，无法完成检查；尚未执行。"}


def generate_source(body, timeout=DEFAULT_TIMEOUT, trace_store=None):
    trace = None
    identifier = body.get("generation_id")
    if identifier is not None:
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise KernelError("generation_id 须为 32 位小写十六进制文本")
        if trace_store is None:
            from rulang.generation_trace import GenerationTrace
            trace = GenerationTrace(identifier)
        else:
            try:
                trace = trace_store.create(identifier)
            except ValueError:
                raise KernelError("生成日志编号已使用或日志容量已满，请使用新编号并稍后重试。", 409) from None
    try:
        value = _generate_source(body, timeout, trace)
        if trace:
            trace.emit("final_success" if value["valid"] else "final_failure",
                       "生成与目标检查完成；尚未执行。" if value["valid"] else "目标检查失败；保留文本供检查，尚未执行。")
            value["trace"] = trace.snapshot()
        return value
    except KernelError as error:
        if trace:
            trace.emit("final_failure", str(error))
            error.trace = trace.snapshot()
        raise


def _generate_source(body, timeout=DEFAULT_TIMEOUT, trace=None):
    timeout = validate_generation_timeout(timeout)
    if set(body) - {"prompt", "draft", "runtime_target", "generation_id"}:
        raise KernelError("生成请求只接受 prompt、可选 draft 与 runtime_target")
    runtime_target = body.get("runtime_target", "python")
    if runtime_target not in ("python", "browser-js"):
        raise KernelError("生成运行环境须为 python 或 browser-js")
    prompt, draft = body.get("prompt"), body.get("draft", "")
    for name, value in (("提示", prompt), ("草稿", draft)):
        if not isinstance(value, str):
            raise KernelError(name + "须为文本")
        if len(value) > MAX_SOURCE:
            raise KernelError(name + "超过 200000 字符上限", 413)
    intent = generation_intent(prompt)
    if intent is None or not intent.strip():
        raise KernelError("提示最后一个非空行必须单独写「如是我言」，且标记不在字符串或注释中")
    if not _GENERATION_SLOT.acquire(blocking=False):
        raise KernelError("已有生成请求正在处理中；取消页面等待不会取消提供方请求，请稍后手动重试。", 429)
    finished = threading.Event()
    result = {}

    def work():
        try:
            try:
                config = load_config()
            except Exception:
                raise KernelError(CONFIG_HELP, 503) from None
            if trace:
                trace.protect(config.api_key)
                trace.emit("preparation", "配置已读取；目标：" + runtime_target + "；只生成并检查，不执行。")
            selected = intent if not draft else intent + "\n\n以下是用户明确选择随提示发送的草稿：\n<ru-draft>\n" + draft + "\n</ru-draft>\n"
            # request_response supplies the exact packaged specification/hash,
            # token cap, no-tool policy and credential-input checks.
            try:
                generated = request_response(config, selected, timeout=timeout, runtime_target="rushu-browser-js" if runtime_target == "browser-js" else "rushu", **({"trace": trace} if trace else {}))
                if not isinstance(generated, str) or config.api_key in generated:
                    raise KernelError("提供方输出无效或含有密钥，已拒绝返回。", 502)
                if len(generated) > MAX_SOURCE:
                    raise KernelError("生成源码超过 200000 字符上限；未保存或执行。", 502)
                if trace:
                    trace.emit("source_extraction", "提取单段如源码；若提取失败，请查看上方提供方原始文本。")
                try:
                    source = clean_generated_source(generated)
                except GenerationError as error:
                    if trace:
                        trace.emit("source_extraction", str(error))
                    raise
                if trace:
                    trace.emit("extracted_source", "实际提取的如源码（已脱敏；尚未执行）", source)
                if len(source) > MAX_SOURCE:
                    raise KernelError("生成源码超过 200000 字符上限；未保存或执行。", 502)
                validation = _validate(source, runtime_target)
                if trace:
                    location = ""
                    if validation.get("line") is not None:
                        location = " 第 %s 行，第 %s 列。" % (validation["line"], validation.get("col"))
                    trace.emit("target_validation", validation["message"] + location)
            except GenerationError as error:
                # Only allowlisted categories are exposed, never arbitrary
                # provider exception text, response bodies or credentials.
                raise KernelError(generation_diagnostic(error), 502) from None
            result["value"] = {"source": source, "valid": validation["valid"],
                               "validation": validation, "provider_host": _host(config)}
        except KernelError as error:
            result["error"] = error
        except Exception:
            result["error"] = KernelError("生成服务无法完成请求；未自动重试，提供方可能已经计费。", 502)
        finally:
            _GENERATION_SLOT.release()
            finished.set()

    worker = threading.Thread(target=work, name="rushu-generation", daemon=True)
    try:
        worker.start()
    except Exception:
        _GENERATION_SLOT.release()
        raise KernelError("无法启动生成请求；请稍后手动重试。", 503) from None
    try:
        completed = finished.wait(timeout)
    except OverflowError:
        # Some platforms cannot represent extremely large finite timeouts.
        # The worker still owns the process-wide slot until its request ends.
        raise KernelError(generation_diagnostic(GenerationError("", code="timeout_range")), 502) from None
    if not completed:
        raise KernelError("生成等待已超时；提供方可能仍在处理并计费，当前请求结束前不能再次生成。", 504)
    if "error" in result:
        raise result["error"]
    return result["value"]
