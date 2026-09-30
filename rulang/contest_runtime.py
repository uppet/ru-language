"""Native primitives behind the ordinary Ru functions in ``如:竞赛``.

Scanner cursors only move forward. The opaque values are ordinary Instances,
but their state and types are not exposed as fields or module exports. Writers
retain at most 64 KiB of UTF-8 output and require an explicit final 清.
"""
from functools import cmp_to_key
import math

from .frontend import Node, Token, bind_arguments
from .io_runtime import _write_stream


ASCII_WHITESPACE = " \t\r\n\v\f"
OUTPUT_LIMIT = 65536
_TEXT_CHUNK = OUTPUT_LIMIT // 4
_BUILTIN_TYPES = None


class _BuiltinOwner:
    def resolve_type(self, typ):
        return typ

    def type_matches(self, value, typ):
        return typ == ""


_BUILTIN_OWNER = _BuiltinOwner()


def install_contest(owner):
    """Keep the implementation object outside the module's export scope."""
    from .interpreter import Instance, RuType, Scope
    global _BUILTIN_TYPES
    if _BUILTIN_TYPES is None:
        _BUILTIN_TYPES = {}
        for kind, name in (("helpers", "竞赛工具"), ("scanner", "竞赛读流"),
                           ("writer", "竞赛出流")):
            node = Node("type", Token("IDENT", name, 0, 0),
                        {"name": name, "parent": None, "fields": [], "methods": []})
            typ = RuType(_BUILTIN_OWNER, node, fields={}, methods={}, state=2)
            typ.contest_kind = kind
            _BUILTIN_TYPES[kind] = typ
    parent = Scope(owner.global_scope.parent)
    parent.values["__竞赛"] = Instance(_BUILTIN_TYPES["helpers"], {})
    owner.global_scope.parent = parent


def _text(owner, n, value, label):
    if not isinstance(value, str):
        owner.fail(n, label + "须为句")
    if "\x00" in value:
        owner.fail(n, label + "不能含 NUL")
    # A host-supplied text stream can contain lone surrogates. Validate once
    # on entry, without a second full-size encoded copy of a large string.
    try:
        for offset in range(0, len(value), _TEXT_CHUNK):
            value[offset:offset + _TEXT_CHUNK].encode("utf-8", "strict")
    except UnicodeError:
        owner.fail(n, label + "不是有效的 UTF-8")
    return value


class _Scanner:
    def __init__(self, text):
        self.text, self.cursor = text, 0

    def token(self):
        text, cursor, size = self.text, self.cursor, len(self.text)
        while cursor < size and text[cursor] in ASCII_WHITESPACE:
            cursor += 1
        start = cursor
        while cursor < size and text[cursor] not in ASCII_WHITESPACE:
            cursor += 1
        self.cursor = cursor
        return None if start == size else text[start:cursor]

    def line(self):
        text, start = self.text, self.cursor
        if start == len(text):
            return None
        end = text.find("\n", start)
        if end < 0:
            self.cursor = len(text)
            return text[start:]
        self.cursor = end + 1
        if end > start and text[end - 1] == "\r":
            end -= 1
        return text[start:end]


def _scanner(text):
    from .interpreter import Instance
    value = Instance(_BUILTIN_TYPES["scanner"], {})
    value.contest_state = _Scanner(text)
    return value


class _Writer:
    def __init__(self, stream):
        self.stream, self.pending = stream, bytearray()

    def flush(self, force=False):
        if self.pending:
            _write_stream(self.stream, self.pending.decode("utf-8"))
            self.pending.clear()
        elif force:
            self.stream.flush()

    def write(self, text):
        # Encode bounded pieces, preserving whole codepoints at every flush.
        # Even a single enormous 写 call never becomes an enormous buffer.
        for start in range(0, len(text), _TEXT_CHUNK):
            encoded = text[start:start + _TEXT_CHUNK].encode("utf-8")
            offset = 0
            while offset < len(encoded):
                end = min(len(encoded), offset + OUTPUT_LIMIT - len(self.pending))
                while end < len(encoded) and end > offset and encoded[end] & 0xC0 == 0x80:
                    end -= 1
                if end == offset:
                    self.flush()
                    continue
                self.pending.extend(memoryview(encoded)[offset:end])
                offset = end
                if len(self.pending) == OUTPUT_LIMIT:
                    self.flush()


_HELPER_PARAMS = {
    "读入": [], "扫句": ["文"], "拆词": ["文"], "拆行": ["文"],
    "字列": ["文"], "合句": ["列", "隔"], "排序": ["列", "比较"],
    "取整": ["值"], "蓄出": [],
}
_SCANNER_PARAMS = {"词": [], "数": [], "行": []}
_WRITER_PARAMS = {"写": ["内容"], "行": ["值"], "清": []}


def contest_member(owner, n, receiver, name, args):
    """Return (handled, value), using normal fatal errors rather than 卒."""
    from .interpreter import Function, Instance, display
    if not isinstance(receiver, Instance):
        return False, None
    kind = getattr(receiver.type, "contest_kind", None)
    params = {"helpers": _HELPER_PARAMS, "scanner": _SCANNER_PARAMS,
              "writer": _WRITER_PARAMS}.get(kind, {})
    if name not in params:
        return False, None
    bound = bind_arguments(name, args, params[name], lambda message: owner.fail(n, message))
    if kind == "scanner":
        scanner = receiver.contest_state
        if name == "行":
            return True, scanner.line()
        token = scanner.token()
        return True, owner.number_value(n, token) if name == "数" and token is not None else token
    if kind == "writer":
        if name == "写":
            text = _text(owner, n, bound["内容"], "内容")
        elif name == "行":
            value = bound["值"]
            if isinstance(value, str):
                text = _text(owner, n, value, "值")
            elif isinstance(value, float) and math.isfinite(value):
                text = display(value)
            else:
                owner.fail(n, "值须为句或有限数")
        try:
            if name == "清":
                receiver.contest_state.flush(force=True)
            else:
                receiver.contest_state.write(text)
                if name == "行":
                    receiver.contest_state.write("\n")
        except (OSError, ValueError, UnicodeError) as error:
            owner.fail(n, "输出失败：" + str(error))
        owner.last_member_procedure = True
        return True, None
    if name == "读入":
        try:
            stream = owner.stdin.buffer if hasattr(owner.stdin, "buffer") else owner.stdin
            text = stream.read()
            if isinstance(text, bytes):
                text = text.decode("utf-8", "strict")
                if "\x00" in text:
                    owner.fail(n, "输入不能含 NUL")
            else:
                text = _text(owner, n, text, "输入")
        except (OSError, ValueError, UnicodeError) as error:
            owner.fail(n, "读取输入失败：" + str(error))
        return True, _scanner(text)
    if name in ("扫句", "拆词", "拆行", "字列"):
        text = _text(owner, n, bound["文"], "文")
        if name == "扫句":
            return True, _scanner(text)
        if name == "字列":
            return True, list(text)
        scanner, result = _Scanner(text), []
        read = scanner.token if name == "拆词" else scanner.line
        while True:
            item = read()
            if item is None:
                return True, result
            result.append(item)
    if name == "合句":
        values = bound["列"]
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            owner.fail(n, "列须为句 阵")
        separator = _text(owner, n, bound["隔"], "隔")
        for value in values:
            _text(owner, n, value, "列中元素")
        return True, separator.join(values)
    if name == "取整":
        value = bound["值"]
        if not isinstance(value, float) or not math.isfinite(value):
            owner.fail(n, "值须为有限数")
        return True, math.modf(value)[1]
    if name == "排序":
        values, comparator = bound["列"], bound["比较"]
        if not isinstance(values, list):
            owner.fail(n, "列须为阵")
        if not isinstance(comparator, Function) or comparator.node.data["procedure"]:
            owner.fail(n, "比较须为算")
        snapshot = list(values)

        def compare(left, right):
            result = owner.invoke_value(n, comparator, [(None, left), (None, right)])
            if not isinstance(result, float) or not math.isfinite(result):
                owner.fail(n, "比较结果须为有限数")
            return (result > 0) - (result < 0)

        # Sorting a separate snapshot leaves the source order unchanged on
        # success or error, and comparator mutations cannot resize our input.
        result = sorted(snapshot, key=cmp_to_key(compare))
        owner.last_member_procedure = False
        return True, result
    if name == "蓄出":
        value = Instance(_BUILTIN_TYPES["writer"], {})
        value.contest_state = _Writer(owner.stdout)
        return True, value
    raise AssertionError(name)
