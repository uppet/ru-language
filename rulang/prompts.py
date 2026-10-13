"""Offline system-prompt exports; no configuration, credentials, or network."""
import os
from pathlib import Path
import stat
import tempfile

from .frontend import RuError
from .generation import generation_system_prompt


def _error(message):
    error = RuError(message, category="提示导出错误")
    error.source_name = "<提示导出>"
    error.suppress_source = True
    return error


def _check_destination(destination, force):
    # The specification is the export's input, never a replaceable artifact.
    specification = Path(__file__).with_name("language-spec.md")
    if destination == specification.resolve():
        raise _error("不能覆盖随附语言规范；请选择其他输出路径")
    try:
        status = destination.lstat()
    except FileNotFoundError:
        return
    if not force:
        raise _error("输出路径已存在；请选择新路径，或用 --force 替换普通文件")
    if not stat.S_ISREG(status.st_mode):
        raise _error("--force 只允许替换普通文件，不能覆盖符号链接、目录或特殊文件")
    if destination.samefile(specification):
        raise _error("不能覆盖随附语言规范的硬链接；请选择其他输出路径")


def export_prompt(target="rushu", output=None, *, force=False, runtime_target="python"):
    """Return prompt text for None/'-', otherwise atomically write a UTF-8 file.

    rushu is exactly the notebook generation system prompt; ruguan adds a
    graphics focus to the same complete specification. No provider is needed.
    Existing files are refused unless force=True; links and the specification
    itself are always protected. File output returns the published Path.
    """
    if target not in ("rushu", "ruguan"):
        raise _error("提示导出目标须为 rushu 或 ruguan")
    if runtime_target not in ("python", "browser-js"):
        raise _error("提示运行环境须为 python 或 browser-js")
    stdout = output is None or str(output) == "-"
    if stdout and force:
        raise _error("--force 需要指定实际输出文件")
    text = generation_system_prompt(target if runtime_target == "python" else target + "-browser-js")
    if stdout:
        return text
    temporary = None
    descriptor = None
    try:
        path = Path(output).expanduser().absolute()
        destination = path.parent.resolve() / path.name
        _check_destination(destination, force)
        descriptor, temporary = tempfile.mkstemp(prefix=".ru-prompt-", suffix=".tmp", dir=destination.parent)
        stream = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
        descriptor = None
        with stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        _check_destination(destination, force)
        if force:
            os.replace(temporary, destination)
        else:
            # Unlike replace(), this never overwrites a concurrently created file.
            os.link(temporary, destination)
        return destination
    except RuError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise _error("无法保存 UTF-8 提示词；请检查输出目录和权限，已有文件未覆盖") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
