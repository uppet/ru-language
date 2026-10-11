"""Unicode lexer, recursive-descent/Pratt parser and structural validation."""
from dataclasses import dataclass
import math
import re


class RuError(Exception):
    def __init__(self, message, line=1, col=1, category="语法错误"):
        self.message, self.line, self.col, self.category = message, line, col, category
        super().__init__(message)


class Incomplete(RuError):
    pass


@dataclass
class Token:
    kind: str
    value: str
    line: int
    col: int


@dataclass
class Node:
    kind: str
    token: Token
    data: dict


def node(kind, token, **data):
    return Node(kind, token, data)


BUILTIN_TYPES = {"件", "录", "件作成果"}
BUILTIN_NAMES = BUILTIN_TYPES | {"读", "读取", "显出", "错误", "__如竞", "__实用", "__如观"}


MEMBER_PARAMS = {"含": ["句"], "位": ["位"], "段": ["始", "终"], "增": ["值"],
                 "量": [], "囫": [], "囵": [], "删": ["位"], "弹": [], "查": ["值"]}

KEYWORDS = set("显 取 为 得 完 破 若 则 另 然 循 次 环 算 作 法 其 且 或 非 空 真 假 典 成 对 形 象 如 新 外言 尽 试 救 卒".split())
NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def comment_marker(source, index, name):
    """Adjacent punctuation only; an opener must not split a whole name."""
    return (source.startswith(name, index) and index + 1 < len(source)
            and source[index + 1] in ".。"
            and (index == 0 or not (source[index - 1] == "_" or source[index - 1].isalnum())))


BLOCK_COMMENT_CLOSE = re.compile(r"释[.。]")


def block_comment_end(source, index):
    """First exact closer wins, including inside quoted-looking comment text."""
    match = BLOCK_COMMENT_CLOSE.search(source, index + 2)
    return None if match is None else match.end()


def lex(source):
    tokens, i, line, col = [], 0, 1, 1
    punct = {"。": ".", "：": ":", "（": "(", "）": ")", "，": ",", "［": "[", "］": "]", "｛": "{", "｝": "}"}
    quotes = {"'": "'", '"': '"', "‘": "’", "“": "”"}

    def advance(text):
        nonlocal i, line, col
        i += len(text)
        if "\n" in text:
            line += text.count("\n")
            col = len(text.rsplit("\n", 1)[1]) + 1
        else:
            col += len(text)

    while i < len(source):
        ch, startline, startcol = source[i], line, col
        if ch.isspace() or (i == 0 and ch == "\ufeff"):
            advance(ch)
            continue
        if ch == "#" or source.startswith("//", i) or comment_marker(source, i, "批"):
            end = source.find("\n", i)
            advance(source[i:len(source) if end < 0 else end])
            continue
        if comment_marker(source, i, "解"):
            end = block_comment_end(source, i)
            if end is None:
                raise Incomplete("块注释尚未结束（需要 释.）", startline, startcol)
            advance(source[i:end])
            continue
        if ch in quotes:
            endquote = quotes[ch]
            advance(ch)
            value = []
            while i < len(source) and source[i] != endquote:
                c = source[i]
                if c == "\\":
                    advance(c)
                    if i >= len(source):
                        raise Incomplete("字符串尚未结束", startline, startcol)
                    esc = source[i]
                    mapping = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", "'": "'", '"': '"', "’": "’", "”": "”"}
                    if esc not in mapping:
                        raise RuError("未知转义：\\" + esc, line, col)
                    value.append(mapping[esc])
                    advance(esc)
                else:
                    if c == "\x00":
                        raise RuError("字符串不能含 NUL", line, col)
                    value.append(c)
                    advance(c)
            if i >= len(source):
                raise Incomplete("字符串尚未结束", startline, startcol)
            advance(endquote)
            tokens.append(Token("STRING", "".join(value), startline, startcol))
            continue
        if ch.isascii() and (ch.isdigit() or (ch == "." and i+1 < len(source) and source[i+1].isdigit())):
            match = NUMBER.match(source, i)
            if match:
                raw = match.group()
                if not math.isfinite(float(raw)):
                    raise RuError("数字超出有限双精度范围", line, col)
                tokens.append(Token("NUMBER", raw, line, col))
                advance(raw)
                continue
        pair = source[i:i+2]
        if pair in (":=", "：="):
            tokens.append(Token("OP", ":=", line, col))
            advance(pair)
            continue
        if pair in ("==", "!=", "<=", ">="):
            tokens.append(Token("OP", pair, line, col))
            advance(pair)
            continue
        if ch in ".:(),[]{}@+-*/%<>=!" or ch in punct:
            tokens.append(Token("OP", punct.get(ch, ch), line, col))
            advance(ch)
            continue
        if ch == "_" or ch.isalpha():
            end = i+1
            while end < len(source) and (source[end] == "_" or source[end].isalnum()):
                end += 1
            raw = source[i:end]
            tokens.append(Token("NAME", raw, line, col))
            advance(raw)
            continue
        raise RuError(f"无法识别字符 {ch!r}", line, col)
    tokens.append(Token("EOF", "<文件尾>", line, col))
    return tokens


class Parser:
    PRECEDENCE = {"对": 7, "或": 10, "且": 20, "==": 30, "!=": 30,
                  "<": 40, "<=": 40, ">": 40, ">=": 40,
                  "+": 50, "-": 50, "*": 60, "/": 60, "%": 60}

    def __init__(self, source):
        self.tokens, self.i = lex(source), 0
        self.depth = 0
        self.call_allowed = True
        self.callable_cache = {}

    @property
    def current(self):
        return self.tokens[self.i]

    def peek(self, n=1):
        return self.tokens[min(self.i+n, len(self.tokens)-1)]

    def isv(self, value):
        return self.current.kind != "STRING" and self.current.value == value

    def pop(self):
        token = self.current
        if token.kind != "EOF":
            self.i += 1
        return token

    def accept(self, value):
        return self.pop() if self.isv(value) else None

    def fail(self, message, token=None):
        t = token or self.current
        cls = Incomplete if t.kind == "EOF" else RuError
        raise cls(message, t.line, t.col)

    def expect(self, value):
        if not self.isv(value):
            self.fail(f"期待「{value}」，却遇到「{self.current.value}」")
        return self.pop()

    def name(self):
        t = self.current
        if t.kind != "NAME" or t.value in KEYWORDS:
            self.fail("此处需要名称", t)
        return self.pop()

    def type_name(self):
        t = self.current
        if t.kind != "NAME" or (t.value in KEYWORDS and t.value not in ("空", "对", "算", "作", "典")):
            self.fail("此处需要类型名称", t)
        value = self.pop().value
        while self.accept("阵"):
            value += " 阵"
        return value

    def parse(self, stops=()):
        self.depth += 1
        try:
            if self.depth > 128:
                self.fail("源码嵌套过深（原型上限 128 层）")
            return self._parse(stops)
        finally:
            self.depth -= 1

    def _parse(self, stops=()):
        out = []
        while self.current.kind != "EOF" and not any(self.isv(s) and (s != "落" or (self.peek().kind == "OP" and self.peek().value == ".")) for s in stops):
            if self.accept("."):
                continue
            out.append(self.statement())
        return out

    def callable_parse(self, kind, parse_body):
        # Header/reference ambiguity can revisit the same body via several
        # alternatives. Memoize those attempts instead of exponential reparsing.
        key = (kind, self.i, self.call_allowed)
        cached = self.callable_cache.get(key)
        if cached is not None:
            result, end, depth = cached
            if isinstance(result, RuError):
                if "嵌套过深" not in result.message or self.depth >= depth:
                    self.i = end
                    raise result
            # A result parsed with a smaller remaining nesting budget is safe
            # here. Recheck at deeper positions so caching cannot bypass limits.
            elif self.depth <= depth:
                self.i = end
                return result
        try:
            result = parse_body()
        except RuError as error:
            self.callable_cache[key] = (error, self.i, self.depth)
            raise
        self.callable_cache[key] = (result, self.i, self.depth)
        return result

    def function(self):
        return self.callable_parse("named", self._function)

    def _function(self):
        t = self.pop()
        kind, name, params = t.value, self.name().value, []
        while not self.isv(":"):
            param = self.name()
            params.append((param.value, self.type_name() if self.accept("为") else ""))
            self.accept(",")
        self.expect(":")
        end = "法" if kind == "算" else "为"
        body = self.parse((end,))
        self.expect(end)
        self.accept(".")
        return node("function", t, name=name, params=params, body=body, procedure=kind == "作")

    def literal(self, token):
        return self.callable_parse("literal", lambda: self._literal(token))

    def _literal(self, token):
        """A literal owns its body delimiter, never its enclosing statement dot."""
        params = []
        while not self.isv(":"):
            if self.current.kind != "NAME" or self.current.value in KEYWORDS:
                self.fail("匿名算／作的参数后必须有「:」")
            param = self.name()
            params.append((param.value, self.type_name() if self.accept("为") else ""))
            self.accept(",")
        self.expect(":")
        end = "法" if token.value == "算" else "为"
        previous = self.call_allowed
        self.call_allowed = True
        try:
            body = self.parse((end,))
            self.expect(end)
        finally:
            self.call_allowed = previous
        return node("function_literal", token, name="<匿名>", params=params,
                    body=body, procedure=token.value == "作")

    def type_definition(self):
        t = self.expect("形")
        name = self.name().value
        parent = self.name().value if self.accept("如") else None
        self.accept(":")
        fields, methods = [], []
        while not self.isv("象"):
            if self.accept("."):
                continue
            if self.isv("算") or self.isv("作"):
                methods.append(self.function())
            else:
                field = self.name().value
                self.expect("为")
                fields.append((field, self.type_name()))
                self.expect(".")
        self.expect("象")
        self.accept(".")
        return node("type", t, name=name, parent=parent, fields=fields, methods=methods)

    def statement(self):
        t = self.current
        # These delimiters are contextual: 段/落 remain ordinary names elsewhere,
        # notably the established 其 段 member and bindings named 段 or 落.
        if self.isv("段") and self.peek().kind == "OP" and self.peek().value == ":":
            self.pop()
            self.expect(":")
            body = self.parse(("落",))
            self.expect("落")
            self.expect(".")
            return node("scope", t, body=body)
        if self.accept("{"):
            body = self.parse(("}",))
            self.expect("}")
            self.accept(".")
            return node("scope", t, body=body)
        if self.accept("试"):
            self.accept(":")
            body = self.parse(("救", "终"))
            self.expect("救")
            reason = self.name().value
            self.accept(":")
            rescue = self.parse(("终",))
            self.expect("终")
            self.accept(".")
            return node("try", t, body=body, reason=reason, rescue=rescue)
        if self.accept("卒"):
            expr = self.expression()
            self.expect(".")
            return node("panic", t, expr=expr)
        if self.accept("显"):
            expr = self.expression()
            self.expect(".")
            return node("print", t, expr=expr)
        if self.accept("得"):
            expr = self.expression()
            self.expect(".")
            return node("return", t, expr=expr)
        if self.accept("完"):
            self.expect(".")
            return node("finish", t)
        if self.accept("破"):
            self.expect(".")
            return node("break", t)
        if self.accept("若"):
            condition = self.expression()
            self.expect("则")
            yes = self.parse(("另", "然"))
            no = self.parse(("然",)) if self.accept("另") else []
            self.expect("然")
            self.accept(".")
            return node("if", t, condition=condition, yes=yes, no=no)
        if self.accept("循"):
            save, count = self.i, None
            try:
                candidate = self.expression()
                if self.accept("次"):
                    count = candidate
                else:
                    self.i = save
            except RuError:
                self.i = save
            body = self.parse(("环",))
            self.expect("环")
            self.accept(".")
            return node("loop", t, count=count, body=body)
        if (self.isv("算") or self.isv("作")) and self.definition_ahead():
            start = self.i
            try:
                return self.function()
            except RuError as declaration_error:
                # An untyped header overlaps a reference's named call:
                # `算 回 值:1.`. Prefer a complete declaration, but preserve
                # an existing complete reference expression when no body closes.
                self.i = start
                try:
                    expr = self.expression()
                    self.expect(".")
                    return node("expr", t, expr=expr)
                except RuError:
                    raise declaration_error
        if self.isv("形"):
            return self.type_definition()
        if self.accept("尽"):
            self.expect("取")
            expr = self.expression()
            if expr.kind != "import":
                self.fail("「尽 取」需要「外言 '文件.ru'」", t)
            self.expect(".")
            return node("import_all", t, expr=expr)
        if t.kind == "NAME" and ((self.peek().kind == "NAME" and self.peek().value == "取") or
                                 (self.peek().kind == "OP" and self.peek().value == ":=")):
            name = self.name().value
            self.pop()  # 取 or its := statement-only alias
            expr = self.expression()
            self.expect(".")
            return node("bind", t, name=name, expr=expr)
        expr = self.expression()
        if self.accept("取") or self.accept(":="):
            if expr.kind not in ("index", "member") or (expr.kind == "member" and expr.data["args"] and expr.data["name"] != "位"):
                self.fail("「取」左侧须为名称、对象字段或阵元素", expr.token)
            value = self.expression()
            self.expect(".")
            return node("assign", t, target=expr, expr=value)
        self.expect(".")
        return node("expr", t, expr=expr)

    def expression(self, minimum=0, allow_call=None):
        self.depth += 1
        previous = self.call_allowed
        if allow_call is not None:
            self.call_allowed = allow_call
        try:
            if self.depth > 128:
                self.fail("源码嵌套过深（原型上限 128 层）")
            return self._expression(minimum)
        finally:
            self.depth -= 1
            self.call_allowed = previous

    def starts_argument(self):
        t = self.current
        return (t.kind in ("NUMBER", "STRING") or self.isv("(") or
                self.isv("[") or self.isv("{") or self.isv("非") or self.isv("空") or
                self.isv("新") or self.isv("外言") or self.isv("其") or
                self.isv("算") or self.isv("作") or self.isv("典") or
                self.isv("真") or self.isv("假") or
                (t.kind == "NAME" and t.value not in KEYWORDS))

    def definition_ahead(self):
        """Distinguish a declaration header from a standalone callable ref."""
        name, after_name = self.peek(), self.peek(2)
        if name.kind != "NAME" or name.value in KEYWORDS:
            return False
        return ((after_name.kind == "OP" and after_name.value == ":") or (
            after_name.kind == "NAME" and after_name.value not in KEYWORDS)) and self.literal_ahead(2)

    def literal_ahead(self, offset=0, require_colon=False):
        """Recognize optional-type headers without stealing reference conversions.

        A colon completes the header. Viable EOF prefixes request REPL
        continuation, including when the colon starts the next input line.
        Empty annotations are an internal sentinel, never a source type name.
        """
        while True:
            token = self.peek(offset)
            if token.kind == "EOF":
                return not require_colon
            if token.kind == "OP" and token.value == ":":
                return True
            if token.kind != "NAME" or token.value in KEYWORDS:
                return False
            offset += 1
            marker = self.peek(offset)
            if marker.kind == "NAME" and marker.value == "为":
                offset += 1
                typ = self.peek(offset)
                if typ.kind == "EOF":
                    return not require_colon
                if (typ.kind != "NAME" or
                        (typ.value in KEYWORDS and typ.value not in ("空", "对", "算", "作", "典"))):
                    return False
                offset += 1
                while self.peek(offset).kind == "NAME" and self.peek(offset).value == "阵":
                    offset += 1
            token = self.peek(offset)
            if token.kind == "OP" and token.value == ",":
                offset += 1

    def empty_call_ahead(self):
        return self.isv("(") and self.peek().kind == "OP" and self.peek().value == ")"

    def reference(self, token):
        """Select a name/member without invoking the selected callable."""
        t = self.pop()
        if t.kind == "NAME" and t.value not in KEYWORDS:
            target = node("name", t, name=t.value)
        elif t.value == "其" and t.kind == "NAME":
            target = node("self", t)
            if self.current.kind == "NAME" and self.current.value not in KEYWORDS:
                member = self.name()
                target = node("member", t, receiver=target, name=member.value, args=[])
        elif t.value == "(" and t.kind == "OP":
            target = self.expression(allow_call=True)
            self.expect(")")
        else:
            self.fail("算／作引用需要名称、成员或括号表达式", t)
        while True:
            if self.isv("其") or self.isv("@"):
                separator = self.pop()
                member = self.name()
                target = node("member", separator, receiver=target, name=member.value, args=[])
            elif self.isv("["):
                bracket = self.pop()
                index = self.expression(allow_call=True)
                self.expect("]")
                target = node("index", bracket, receiver=target, index=index)
            else:
                break
        return node("function_ref", token, expr=target, procedure=token.value == "作")

    def call_arguments(self, allow=None):
        args, style, separated = [], None, False
        enabled = self.call_allowed if allow is None else allow
        while enabled and (self.starts_argument() or
                           (separated and (self.isv("+") or self.isv("-")))):
            named = (self.current.kind == "NAME" and self.current.value not in KEYWORDS and
                     self.peek().kind == "OP" and
                     self.peek().value == ":")
            current_style = "named" if named else "positional"
            if style is not None and style != current_style:
                self.fail("同一次调用不能混用位置实参与命名实参；嵌套调用请加括号")
            style = current_style
            key = self.pop().value if named else None
            if named:
                self.expect(":")
            args.append((key, self.expression(allow_call=False)))
            separated = self.accept(",") is not None
        return args

    def member(self, receiver, token):
        name_token = self.name()
        name = name_token.value
        # Member names have no global arity: dispatch belongs to the receiver.
        adjacent = self.isv("[") and self.current.line == name_token.line and self.current.col == name_token.col + len(name)
        args = [] if adjacent or self.isv("其") or self.isv("@") or self.empty_call_ahead() else self.call_arguments()
        return node("member", token, receiver=receiver, name=name, args=args)

    def _expression(self, minimum=0, reference_only=False):
        start = self.i
        t = self.pop()
        grouped = False
        if t.kind == "NUMBER":
            left = node("number", t, value=float(t.value))
        elif t.kind == "STRING":
            left = node("string", t, value=t.value)
        elif t.value in ("真", "假"):
            left = node("fact", t, value=t.value == "真")
        elif t.value == "典":
            self.expect(":")
            entries = []
            while not self.isv("成"):
                key = self.expression(8, allow_call=True)
                self.expect("对")
                value = self.expression(allow_call=True)
                self.expect(".")
                entries.append((key, value))
            self.expect("成")
            left = node("map", t, entries=entries)
        elif t.value == "{" and t.kind == "OP":
            entries = []
            while not self.isv("}"):
                key = self.expression(allow_call=True)
                self.expect(":")
                value = self.expression(allow_call=True)
                entries.append((key, value))
                if not self.accept(","):
                    break
            self.expect("}")
            left = node("map", t, entries=entries)
        elif t.value == "空":
            left = node("null", t)
        elif t.value in ("算", "作") and t.kind == "NAME":
            # The mandatory colon distinguishes a literal header from
            # existing references followed by conversions (算 名 为 句).
            if not reference_only and self.literal_ahead():
                complete_header = self.literal_ahead(require_colon=True)
                try:
                    left = self.literal(t)
                except RuError as literal_error:
                    if not complete_header:
                        raise
                    # `算 回 值:1.` is also a viable untyped header prefix.
                    # A complete literal wins; otherwise preserve reference
                    # calls with named arguments in every expression context.
                    self.i = start
                    try:
                        result = self._expression(minimum, reference_only=True)
                        if self.isv(":"):
                            raise literal_error
                        return result
                    except RuError:
                        raise literal_error
            else:
                left = self.reference(t)
        elif t.value == "外言":
            path = self.pop()
            if path.kind != "STRING":
                self.fail("「外言」后须为文件路径字符串字面量", path)
            left = node("import", t, path=path.value)
        elif t.value == "新":
            name = self.name().value
            args = self.call_arguments(allow=True)
            if any(key is None for key, _ in args):
                self.fail("「新」只接受命名字段实参", t)
            left = node("new", t, name=name, args=args)
        elif t.value == "其":
            left = node("self", t)
            if self.current.kind == "NAME" and self.current.value not in KEYWORDS:
                left = self.member(left, t)
        elif t.value == "[" and t.kind == "OP":
            items = []
            while not self.isv("]"):
                items.append(self.expression(allow_call=True))
                if not self.accept(","):
                    break
            self.expect("]")
            left = node("array", t, items=items)
        elif t.value == "(" and t.kind == "OP":
            left = self.expression(allow_call=True)
            self.expect(")")
            grouped = True
        elif t.value in ("+", "-", "非"):
            left = node("unary", t, op=t.value, expr=self.expression(70))
        elif t.kind == "NAME" and t.value not in KEYWORDS:
            # Adjacency distinguishes name[index] from f [array literal].
            adjacent = self.isv("[") and self.current.line == t.line and self.current.col == t.col + len(t.value)
            args = [] if adjacent or self.isv("其") or self.isv("@") or self.empty_call_ahead() else self.call_arguments()
            left = node("call", t, name=t.value, args=args) if args else node("name", t, name=t.value)
        else:
            self.fail(f"此处需要表达式，却遇到「{t.value}」", t)
        while True:
            if self.empty_call_ahead() and 80 >= minimum:
                opening = self.pop()
                self.expect(")")
                left = node("invoke", opening, callee=left, args=[])
                grouped = False
                continue
            if self.isv("[") and 80 >= minimum:
                bracket = self.pop()
                first = None if self.isv(":") else self.expression(allow_call=True)
                if self.accept(":"):
                    end = None if self.isv("]") else self.expression(allow_call=True)
                    self.expect("]")
                    left = node("slice", bracket, receiver=left, start=first, end=end)
                else:
                    self.expect("]")
                    left = node("index", bracket, receiver=left, index=first)
                continue
            if self.isv("为") and self.peek().kind == "NAME" and self.peek().value in ("数", "句", "阵", "事实") and 5 >= minimum:
                cast = self.pop()
                typ = self.pop()
                left = node("convert", cast, expr=left, target=typ.value)
                continue
            if (self.isv("@") or self.isv("其")) and 75 >= minimum:
                left = self.member(left, self.pop())
                continue
            if (self.call_allowed and minimum <= 75 and self.starts_argument()
                    and (grouped or left.kind in ("index", "function_ref", "invoke"))):
                args = self.call_arguments()
                left = node("invoke", left.token, callee=left, args=args)
                grouped = False
                continue
            op = self.current.value
            prec = self.PRECEDENCE.get(op, -1) if self.current.kind != "STRING" else -1
            if prec < minimum:
                break
            token = self.pop()
            right = self.expression(prec if op == "对" else prec+1)
            left = node("binary", token, op=op, left=left, right=right)
            grouped = False
        return left


def parse(source):
    parser = Parser(source)
    result = parser.parse()
    if parser.current.kind != "EOF":
        parser.fail("出现多余内容")
    return result


def bind_arguments(name, args, params, fail, optional=False):
    """Match both call styles without changing source evaluation order.

    Values can be AST expressions (compiler) or evaluated values (interpreter).
    `optional` is only used for the built-in input prompt.
    """
    positional = any(key is None for key, _ in args)
    if positional:
        if any(key is not None for key, _ in args):
            fail("同一次调用不能混用位置实参与命名实参")
        if len(args) != len(params):
            fail(f"函数「{name}」需要 {len(params)} 个位置实参（" +
                 "、".join(params) + f"），收到 {len(args)} 个")
        return {key: value for key, (_, value) in zip(params, args)}
    values = {}
    for key, value in args:
        if key in values:
            fail(f"重复的实参：{key}")
        values[key] = value
    if optional and not values:
        return values
    missing = [key for key in params if key not in values]
    unknown = [key for key in values if key not in params]
    if missing or unknown:
        detail = []
        if missing:
            detail.append("缺少「" + "、".join(missing) + "」")
        if unknown:
            detail.append("未知「" + "、".join(unknown) + "」")
        fail(f"函数「{name}」实参不匹配：" + "；".join(detail))
    return values


def validate(program, existing_functions=(), existing_types=()):
    """Check declaration/control-flow structure without executing user code."""
    functions = set(existing_functions)
    declared = set()
    type_nodes = {}
    for n in program:
        if n.kind in ("function", "type"):
            name = n.data["name"]
            if name in BUILTIN_NAMES or name in declared:
                raise RuError(f"重复或保留的名称：{name}", n.token.line, n.token.col)
            declared.add(name)
            if n.kind == "function":
                functions.add(name)
            else:
                type_nodes[name] = n

    def error(n, message):
        raise RuError(message, n.token.line, n.token.col)

    has_imports = any(n.kind == "import_all" for n in program)
    known_types = set(type_nodes) | set(existing_types) | BUILTIN_TYPES | {"数", "句", "阵", "对", "空", "算", "作", "典", "事实"}
    known_bindings = {n.data["name"] for n in program if n.kind == "bind"}

    def check_type(n, typ):
        base = typ.split()[0]
        if base not in known_types and not has_imports:
            error(n, f"未定义类型：{base}")

    def local_bindings(stmts):
        result = set()
        for n in stmts:
            if n.kind == "bind":
                result.add(n.data["name"])
            elif n.kind == "if":
                result.update(local_bindings(n.data["yes"]))
                result.update(local_bindings(n.data["no"]))
            elif n.kind in ("loop", "try"):
                result.update(local_bindings(n.data["body"]))
        return result

    def declarations(stmts, inherited_names, params=()):
        own = set()
        for n in stmts:
            if n.kind != "function":
                continue
            name = n.data["name"]
            if name in own or name in BUILTIN_NAMES or name in type_nodes or name in params:
                error(n, "重复或保留的函数名称：" + name)
            own.add(name)
        return inherited_names | own

    def expressions(value, method=False, visible_functions=None, bindings=None):
        if isinstance(value, Node):
            if value.kind == "function_literal":
                check_function(value, method, visible_functions, bindings)
                return
            if value.kind in ("name", "call") and value.data["name"] in (set(type_nodes) | set(existing_types) | BUILTIN_TYPES):
                name = value.data["name"]
                error(value, f"形名「{name}」不能作为普通值；创建实例请用「新 {name}」，类型注解请直接使用形名")
            if value.kind == "self" and not method:
                error(value, "「其」自身引用只能用于形的方法内或其闭包")
            if value.kind == "function_ref":
                target = value.data["expr"]
                if target.kind == "name" and target.data["name"] == "读":
                    error(value, "当前仅支持用户定义算／作的引用；内置「读」不能取引用")
                # A selected member is not invoked and need not have the
                # built-in member call's fixed arity (e.g. 算 对象 其 含).
                if target.kind == "member":
                    expressions(target.data["receiver"], method, visible_functions, bindings)
                    return
            if value.kind == "member" and value.data["receiver"].kind in ("string", "number", "null", "array"):
                if value.data["name"] not in MEMBER_PARAMS:
                    error(value, f"未知成员：{value.data['name']}")
            for child in value.data.values():
                expressions(child, method, visible_functions, bindings)
        elif isinstance(value, dict):
            for child in value.values():
                expressions(child, method, visible_functions, bindings)
        elif isinstance(value, (list, tuple)):
            for child in value:
                expressions(child, method, visible_functions, bindings)

    def check_function(n, method, visible_functions, bindings, method_definitions=False):
        d = n.data
        visible_functions = functions if visible_functions is None else visible_functions
        bindings = known_bindings if bindings is None else bindings
        for _, typ in d["params"]:
            if not typ:  # Omitted parameter annotation accepts any ordinary value.
                continue
            base = typ.split()[0]
            if base not in known_types and not has_imports:
                error(n, f"未定义类型：{base}")
        names = [p[0] for p in d["params"]]
        if len(names) != len(set(names)):
            error(n, "参数名重复")
        protected = declarations(d["body"], visible_functions, names)
        if any(p in protected or p in BUILTIN_NAMES or p in type_nodes for p in names):
            error(n, "参数名不能与函数名、形名或内置名称重名")
        walk(d["body"], 0, n, False, method, True, protected,
             bindings | set(names), False)

    def walk(stmts, depth=0, function=None, top=True, method=False,
             declaration_scope=True, visible_functions=None, bindings=None,
             method_definitions=False):
        visible_functions = functions if visible_functions is None else visible_functions
        bindings = known_bindings if bindings is None else bindings
        if declaration_scope and not method_definitions:
            visible_functions = declarations(stmts, visible_functions)
            bindings = bindings | local_bindings(stmts)
        for n in stmts:
            d = n.data
            if n.kind == "function":
                if not declaration_scope:
                    error(n, "函数／过程只能直接定义在模块、函数、方法、段或救的正文中")
                check_function(n, method, visible_functions, bindings, method_definitions)
            elif n.kind == "type":
                if not top:
                    error(n, "形只能定义在顶层")
                if d["name"] in ("数", "句", "阵", "事实", "典"):
                    error(n, "形名不能与内置类型重名")
                for field, typ in d["fields"]:
                    check_type(n, typ)
                members = [f[0] for f in d["fields"]] + [m.data["name"] for m in d["methods"]]
                if len(members) != len(set(members)):
                    error(n, "字段／方法名称重复")
                walk(d["methods"], method=True, visible_functions=visible_functions,
                     bindings=bindings, method_definitions=True)
            elif n.kind == "import_all" and not top:
                error(n, "「尽 取 外言」只能用于顶层")
            elif n.kind == "break" and depth == 0:
                error(n, "「破」只能出现在当前函数的循环内")
            elif n.kind == "return" and (function is None or function.data["procedure"]):
                error(n, "「得」只能出现在「算」定义内")
            elif n.kind == "finish" and (function is None or not function.data["procedure"]):
                error(n, "「完」只能出现在「作」定义内")
            elif n.kind == "bind" and (d["name"] in visible_functions or d["name"] in BUILTIN_NAMES or d["name"] in type_nodes):
                error(n, "变量名不能与函数名、形名或内置名称重名")
            elif n.kind == "scope":
                walk(d["body"], depth, function, False, method, True,
                     visible_functions, bindings)
            elif n.kind == "if":
                expressions(d["condition"], method, visible_functions, bindings)
                walk(d["yes"], depth, function, False, method, False, visible_functions, bindings)
                walk(d["no"], depth, function, False, method, False, visible_functions, bindings)
            elif n.kind == "try":
                rescue_functions = declarations(d["rescue"], visible_functions, (d["reason"],))
                if d["reason"] in visible_functions or d["reason"] in BUILTIN_NAMES or d["reason"] in type_nodes:
                    error(n, "救的原因名称不能与函数名、形名或内置名称重名")
                walk(d["body"], depth, function, False, method, False, visible_functions, bindings)
                walk(d["rescue"], depth, function, False, method, True, rescue_functions,
                     bindings | {d["reason"]})
            elif n.kind == "loop":
                expressions(d["count"], method, visible_functions, bindings)
                walk(d["body"], depth+1, function, False, method, False, visible_functions, bindings)
            else:
                expressions(d, method, visible_functions, bindings)

    inherited = {}

    def ancestry(name, seen):
        if len(seen) >= 128:
            error(type_nodes[name], "形的继承嵌套超过 128 层")
        if name in seen:
            error(type_nodes[name], "形的继承形成循环")
        if name in inherited:
            return inherited[name]
        definition = type_nodes[name]
        parent = definition.data["parent"]
        fields, methods = {}, {}
        if parent in type_nodes:
            parent_fields, parent_methods = ancestry(parent, seen | {name})
            fields, methods = dict(parent_fields), dict(parent_methods)
        elif parent and parent not in existing_types and not has_imports:
            error(definition, f"未定义父形：{parent}")
        for field, typ in definition.data["fields"]:
            if field in fields or field in methods:
                error(definition, f"继承字段／方法重名：{field}")
            fields[field] = typ
        for method in definition.data["methods"]:
            key, data = method.data["name"], method.data
            if key in fields:
                error(method, f"方法与字段重名：{key}")
            if key in methods:
                original = methods[key].data
                if data["params"] != original["params"] or data["procedure"] != original["procedure"]:
                    error(method, f"覆写方法「{key}」须保持参数名称、类型及算／作种类")
            methods[key] = method
        inherited[name] = fields, methods
        return fields, methods

    for name in type_nodes:
        ancestry(name, set())
    walk(program)
    return functions
