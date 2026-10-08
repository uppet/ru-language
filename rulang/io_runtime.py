"""Checked UTF-8 file and standard-stream operations shared by the interpreter.

Paths are used as supplied (relative to the process working directory). Normal
OS permissions and umask apply. Read/write/stat/list follow symlinks; delete
unlinks a symlink itself and never removes a directory. Listing includes only
regular files, including symlinks to regular files, sorted by Unicode name.
Every ordinary I/O failure is a 件作成果, never a language panic.
"""
import errno
import _io
import math
import os
import stat
import sys

from .frontend import Node, Token

IO_TYPE_NAMES = ("件", "录", "件作成果")
IO_BUILTIN_NAMES = IO_TYPE_NAMES + ("读取", "显出", "错误")
_BUILTIN_TYPES = None


class _BuiltinOwner:
    """Primitive builtin field typing without retaining an Interpreter/session."""
    def resolve_type(self, typ):
        return typ

    def type_matches(self, value, typ):
        return typ == "" or (typ == "句" and isinstance(value, str))


_BUILTIN_OWNER = _BuiltinOwner()


def install_io(owner):
    """Install builtins in a parent scope, keeping module exports user-only."""
    from .interpreter import RuType, Instance, Scope
    global _BUILTIN_TYPES
    if _BUILTIN_TYPES is None:
        _BUILTIN_TYPES = {}
        for name, fields in (("件", [("路径", "句")]), ("录", [("路径", "句")]),
                             ("件作成果", [("结果", "句"), ("值", ""), ("错误信息", "句")]),
                             ("输入流", []), ("输出流", [])):
            node = Node("type", Token("IDENT", name, 0, 0),
                        {"name": name, "parent": None, "fields": fields, "methods": []})
            typ = RuType(_BUILTIN_OWNER, node, fields={key: (kind, _BUILTIN_OWNER) for key, kind in fields},
                         methods={}, state=2)
            typ.io_kind = name
            _BUILTIN_TYPES[name] = typ
    owner.builtin_types = {key: _BUILTIN_TYPES[key] for key in IO_TYPE_NAMES}
    parent = Scope(owner.global_scope.parent)
    parent.values.update(owner.builtin_types)
    for name, kind, stream in (("读取", "输入流", owner.stdin),
                              ("显出", "输出流", owner.stdout),
                              ("错误", "输出流", getattr(owner, "stderr", sys.stderr))):
        value = Instance(_BUILTIN_TYPES[kind], {})
        value.io_stream = stream
        parent.values[name] = value
    owner.global_scope.parent = parent


def io_new_defaults(typ):
    kind = getattr(typ, "io_kind", None)
    if kind == "件":
        return {"路径": ""}
    if kind == "录":
        return {"路径": "."}
    if kind == "件作成果":
        return {"结果": "成功", "值": None, "错误信息": ""}
    return None


def _result(value=None, error=None, operation="I/O"):
    from .interpreter import Instance
    diagnostic = ""
    if error is not None:
        if isinstance(error, OSError):
            number = error.errno or errno.EIO
            diagnostic = f"{operation}: [errno {number}] {error.strerror or str(error)}"
        elif isinstance(error, UnicodeError):
            diagnostic = f"{operation}: [errno {errno.EILSEQ}] 文本不是有效的 UTF-8"
        else:
            diagnostic = f"{operation}: [errno {errno.EIO}] {str(error) or 'I/O 失败'}"
    return Instance(_BUILTIN_TYPES["件作成果"],
                    {"结果": "失败" if error is not None else "成功",
                     "值": None if error is not None else value, "错误信息": diagnostic})


def _invalid(message, number=errno.EINVAL):
    return OSError(number, message)


def _text(value, label):
    if not isinstance(value, str):
        raise _invalid(label + "须为句")
    if "\x00" in value:
        raise _invalid(label + "不能含 NUL")
    value.encode("utf-8", "strict")
    return value


def _path(receiver):
    value = _text(receiver.fields["路径"], "路径")
    if not value:
        raise _invalid("路径不能为空")
    return value


def _decode(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8", "strict")
    return _text(value, "文本")


def _open_regular(path, write=False, append=False):
    flags = os.O_WRONLY | os.O_CREAT if write else os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    if append:
        flags |= os.O_APPEND
    fd = os.open(path, flags, 0o666)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise _invalid("路径不是普通文件")
        if write and not append:
            os.ftruncate(fd, 0)
        return os.fdopen(fd, "wb" if write else "rb")
    except BaseException:
        os.close(fd)
        raise


def _with_file(path, operation, content=None, append=False):
    stream, value, error = None, None, None
    try:
        stream = _open_regular(path, operation == "写", append)
        if operation == "读":
            value = _decode(stream.read())
        else:
            encoded = _text(content, "内容").encode("utf-8")
            written = stream.write(encoded)
            if written != len(encoded):
                raise _invalid("写入不完整", errno.EIO)
            stream.flush()
    except (OSError, ValueError, UnicodeError) as caught:
        error = caught
    finally:
        if stream is not None:
            try:
                stream.close()
            except (OSError, ValueError, UnicodeError) as caught:
                if error is None:
                    error = caught
    return _result(value, error, operation)


def read_stream_line(stream):
    """Read/decode exactly one byte line, shared by 读, 读取 and the REPL.

    TextIOWrapper may decode a whole block ahead of the requested line. Reading
    its binary buffer prevents one malformed UTF-8 line losing adjacent lines.
    A single shared reader also avoids mixing decoded and binary read-ahead.
    """
    raw = (stream.buffer if hasattr(stream, "buffer") else stream).readline()
    try:
        return _decode(raw)
    except (OSError, ValueError, UnicodeError) as error:
        error.input_line_consumed = True
        raise


def _write_stream(stream, content):
    # TextIOWrapper can keep bytes after a failed flush, then fail again at
    # Python shutdown (exit 120). Actual process output uses checked raw writes
    # after flushing preceding output; injected/in-memory streams keep their
    # ordinary write/flush protocol. No descriptor is closed or replaced.
    if (stream is sys.stdout or stream is sys.stderr) and hasattr(stream, "buffer"):
        stream.flush()
        encoded = content.encode("utf-8")
        raw = getattr(stream.buffer, "raw", stream.buffer)
        console_type = getattr(_io, "_WindowsConsoleIO", ())
        if isinstance(raw, console_type):
            # WindowsConsoleIO converts UTF-8 to WriteConsoleW. os.write would
            # bypass it and decode these bytes using the console's code page.
            # Write the raw object, not BufferedWriter: retain immediate errors
            # without leaving failed output to be retried during shutdown.
            written = raw.write(encoded)
        else:
            written = os.write(stream.fileno(), encoded)
        if written != len(encoded):
            raise _invalid("写入不完整", errno.EIO)
        return
    written = stream.write(content)
    if written != len(content):
        raise _invalid("写入不完整", errno.EIO)
    stream.flush()


def _bind(owner, n, name, args, params, optional=0):
    """Allow a trailing optional argument without reserving common identifiers."""
    fail = lambda message: owner.fail(n, message)
    minimum = len(params) - optional
    positional = any(key is None for key, _ in args)
    if positional:
        if any(key is not None for key, _ in args):
            fail("同一次调用不能混用位置实参与命名实参")
        if not minimum <= len(args) <= len(params):
            fail(f"方法「{name}」需要 {minimum} 至 {len(params)} 个实参")
        return {key: value for key, (_, value) in zip(params, args)}
    bound = {}
    for key, value in args:
        if key not in params:
            fail(f"方法「{name}」未知实参：{key}")
        if key in bound:
            fail(f"重复的实参：{key}")
        bound[key] = value
    for key in params[:minimum]:
        if key not in bound:
            fail(f"方法「{name}」缺少实参：{key}")
    return bound


def io_member(owner, n, receiver, name, args):
    """Return (handled, value); malformed call shapes remain language errors."""
    from .interpreter import Instance
    if not isinstance(receiver, Instance):
        return False, None
    kind = getattr(receiver.type, "io_kind", None)
    methods = {"件": ("读", "写", "在", "除"), "录": ("列",),
               "输入流": ("读",), "输出流": ("写",)}
    if name not in methods.get(kind, ()):
        return False, None
    params = ["内容", "追加"] if kind == "件" and name == "写" else ["内容"] if name == "写" else []
    bound = _bind(owner, n, name, args, params, optional=int(kind == "件" and name == "写"))
    try:
        if name == "写":
            content = _text(bound["内容"], "内容")
            append = bound.get("追加", 0.0)
            if not isinstance(append, float) or not math.isfinite(append) or append not in (0.0, 1.0):
                raise _invalid("追加须为数 0 或 1")
        if kind == "件":
            path = _path(receiver)
            if name in ("读", "写"):
                return True, _with_file(path, name, content if name == "写" else None,
                                        bool(append) if name == "写" else False)
            if name == "在":
                try:
                    value = float(stat.S_ISREG(os.stat(path).st_mode))
                except OSError as caught:
                    if caught.errno not in (errno.ENOENT, errno.ENOTDIR):
                        raise
                    value = 0.0
                return True, _result(value)
            # unlink refuses directories and removes the symlink itself.
            mode = os.lstat(path).st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
                raise _invalid("路径不是普通文件")
            os.unlink(path)
            return True, _result()
        if kind == "录":
            path = _path(receiver)
            entries = []
            with os.scandir(path) as directory:
                for entry in directory:
                    _text(entry.name, "文件名")
                    try:
                        mode = entry.stat(follow_symlinks=True).st_mode
                    except OSError as caught:
                        # A vanished entry / dangling symlink is not a file.
                        if caught.errno in (errno.ENOENT, errno.ENOTDIR):
                            continue
                        raise
                    if stat.S_ISREG(mode):
                        entries.append(entry.name)
            values = [Instance(_BUILTIN_TYPES["件"], {"路径": os.path.join(path, entry)})
                      for entry in sorted(entries)]
            return True, _result(values)
        stream = receiver.io_stream
        if name == "读":
            value = read_stream_line(stream)
            if value == "":
                return True, _result()
            return True, _result(value.removesuffix("\n").removesuffix("\r"))
        _write_stream(stream, content)
        return True, _result()
    except (OSError, ValueError, UnicodeError) as caught:
        return True, _result(error=caught, operation=name)
