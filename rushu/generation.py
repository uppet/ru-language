"""Explicit notebook generation, isolated from sessions and filesystem imports."""
import threading
from urllib.parse import urlsplit

from rulang.frontend import RuError, parse, validate
from rulang.generation import (GenerationError, clean_generated_source, load_config,
                               request_response)
from rulang.modules import generation_intent

from .kernel import KernelError, MAX_SOURCE

GENERATION_TIMEOUT = 60.0
# Process-wide, including separate NotebookServer instances. The worker retains
# this lock after a client disconnect or response deadline until the paid call
# actually finishes. Browser cancellation cannot start a duplicate paid request.
_GENERATION_SLOT = threading.Lock()
CONFIG_HELP = "请在启动如书前配置 RU_LLM_API_KEY 或 RU_LLM_API_KEY_FILE，或 ~/.ru-lang.json 的 api-key，并检查提供方配置。"


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


def _validate(source):
    try:
        program = parse(source)
        if not program:
            return {"valid": False, "message": "生成源码没有可检查的语句；尚未执行。"}
        validate(program)
        return {"valid": True, "message": "已通过语法与结构检查；未读取或检查外言依赖，尚未执行。"}
    except RuError as error:
        return {"valid": False, "message": "生成源码未通过语法或结构检查；尚未执行。",
                "line": error.line, "col": error.col}
    except RecursionError:
        return {"valid": False, "message": "生成源码结构过深，无法完成检查；尚未执行。"}


def generate_source(body):
    if set(body) - {"prompt", "draft"}:
        raise KernelError("生成请求只接受 prompt 与可选 draft")
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
            selected = intent if not draft else intent + "\n\n以下是用户明确选择随提示发送的草稿：\n<ru-draft>\n" + draft + "\n</ru-draft>\n"
            # request_response supplies the exact packaged specification/hash,
            # token cap, no-tool policy and credential-input checks.
            try:
                generated = request_response(config, selected, timeout=GENERATION_TIMEOUT)
                if not isinstance(generated, str) or config.api_key in generated:
                    raise KernelError("提供方输出无效或含有密钥，已拒绝返回。", 502)
                if len(generated) > MAX_SOURCE:
                    raise KernelError("生成源码超过 200000 字符上限；未保存或执行。", 502)
                source = clean_generated_source(generated)
                if len(source) > MAX_SOURCE:
                    raise KernelError("生成源码超过 200000 字符上限；未保存或执行。", 502)
                validation = _validate(source)
            except GenerationError:
                raise KernelError("生成请求失败或结果无效；请检查提示、提供方权限及额度后手动重试。未自动重试，提供方可能已经计费。", 502) from None
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
    if not finished.wait(GENERATION_TIMEOUT):
        raise KernelError("生成等待已超时；提供方可能仍在处理并计费，当前请求结束前不能再次生成。", 504)
    if "error" in result:
        raise result["error"]
    return result["value"]
