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


KEYWORDS = set("显 取 为 得 破 若 则 另 然 循 次 环 算 作 法 其 且 或 非".split())
NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def lex(source):
    tokens, i, line, col = [], 0, 1, 1
    punct = {"。": ".", "：": ":", "（": "(", "）": ")", "，": ","}
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
        if ch == "#" or source.startswith("//", i):
            end = source.find("\n", i)
            advance(source[i:len(source) if end < 0 else end])
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
        if pair in ("==", "!=", "<=", ">="):
            tokens.append(Token("OP", pair, line, col))
            advance(pair)
            continue
        if ch in ".:(),@+-*/%<>=!" or ch in punct:
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
    PRECEDENCE = {"或": 10, "且": 20, "==": 30, "!=": 30, "<": 40, "<=": 40, ">": 40, ">=": 40,
                  "+": 50, "-": 50, "*": 60, "/": 60, "%": 60}

    def __init__(self, source):
        self.tokens, self.i = lex(source), 0
        self.depth = 0
        self.call_allowed = True

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
        while self.current.kind != "EOF" and not any(self.isv(s) for s in stops):
            if self.accept("."):
                continue
            out.append(self.statement())
        return out

    def statement(self):
        t = self.current
        if self.accept("显"):
            expr = self.expression()
            self.expect(".")
            return node("print", t, expr=expr)
        if self.accept("得"):
            expr = self.expression()
            self.expect(".")
            return node("return", t, expr=expr)
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
            # A counted loop has an expression followed by 次. Otherwise its
            # body begins immediately. Backtracking only decides this prefix.
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
        if self.isv("算") or self.isv("作"):
            kind = self.pop().value
            name = self.name().value
            params = []
            while not self.isv(":"):
                param = self.name()
                self.expect("为")
                typ = self.name()
                if typ.value not in ("数", "句"):
                    self.fail("参数类型须为「数」或「句」", typ)
                params.append((param.value, typ.value))
                self.accept(",")
            self.expect(":")
            end = "法" if kind == "算" else "为"
            body = self.parse((end,))
            self.expect(end)
            self.accept(".")
            return node("function", t, name=name, params=params, body=body, procedure=kind == "作")
        if t.kind == "NAME" and self.peek().kind == "NAME" and self.peek().value == "取":
            name = self.name().value
            self.expect("取")
            expr = self.expression()
            self.expect(".")
            return node("bind", t, name=name, expr=expr)
        expr = self.expression()
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
        """An adjacent primary starts an argument; + and - stay binary.

        Each argument is a full expression. Calls inside arguments need
        parentheses, so `f x y` cannot accidentally become `f (x y)`.
        """
        t = self.current
        return (t.kind in ("NUMBER", "STRING") or self.isv("(") or
                self.isv("非") or (t.kind == "NAME" and t.value not in KEYWORDS))

    def call_arguments(self):
        args, style, separated = [], None, False
        while self.call_allowed and (self.starts_argument() or
                                    (separated and (self.isv("+") or self.isv("-")))):
            named = (self.current.kind == "NAME" and self.peek().kind == "OP" and
                     self.peek().value == ":")
            current_style = "named" if named else "positional"
            if style is not None and style != current_style:
                self.fail("同一次调用不能混用位置实参与命名实参；嵌套调用请加括号")
            style = current_style
            key = self.pop().value if named else None
            if named:
                self.expect(":")
            args.append((key, self.expression(allow_call=False)))
            # A comma makes a following + or - unambiguously unary. Without
            # it, `f 1 - 2` means `f (1 - 2)`, just like a named argument.
            separated = self.accept(",") is not None
        return args

    def _expression(self, minimum=0):
        t = self.pop()
        if t.kind == "NUMBER":
            left = node("number", t, value=float(t.value))
        elif t.kind == "STRING":
            left = node("string", t, value=t.value)
        elif t.value == "(" and t.kind == "OP":
            # Parentheses explicitly delimit nested calls. Without this
            # boundary, f a: variable b: value is ambiguous with variable(...).
            left = self.expression(allow_call=True)
            self.expect(")")
        elif t.value in ("+", "-", "非") and t.kind != "STRING":
            left = node("unary", t, op=t.value, expr=self.expression(70))
        elif t.kind == "NAME" and t.value not in KEYWORDS:
            args = self.call_arguments()
            left = node("call", t, name=t.value, args=args) if args else node("name", t, name=t.value)
        else:
            self.fail(f"此处需要表达式，却遇到「{t.value}」", t)
        while True:
            if self.isv("为") and self.peek().kind == "NAME" and self.peek().value in ("数", "句") and 5 >= minimum:
                cast = self.pop()
                typ = self.pop()
                left = node("convert", cast, expr=left, target=typ.value)
                continue
            if (self.isv("@") or self.isv("其")) and 75 >= minimum:
                member = self.pop()
                self.expect("含")
                right = self.expression(76)
                left = node("binary", member, op="含", left=left, right=right)
                continue
            op = self.current.value
            prec = self.PRECEDENCE.get(op, -1) if self.current.kind != "STRING" else -1
            if prec < minimum:
                break
            token = self.pop()
            right = self.expression(prec+1)
            left = node("binary", token, op=op, left=left, right=right)
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


def validate(program, existing_functions=()):
    functions = set(existing_functions)
    declared = set()
    for n in program:
        if n.kind == "function":
            name = n.data["name"]
            if name == "读" or name in declared:
                raise RuError(f"重复或保留的函数名：{name}", n.token.line, n.token.col)
            declared.add(name)
            functions.add(name)
    def walk(stmts, depth=0, function=None, top=True):
        for n in stmts:
            d, t = n.data, n.token
            def error(message):
                raise RuError(message, t.line, t.col)
            if n.kind == "function":
                if not top:
                    error("原型仅支持顶层函数／过程定义")
                names = [p[0] for p in d["params"]]
                if len(names) != len(set(names)):
                    error("参数名重复")
                if any(p in functions or p == "读" for p in names):
                    error("参数名不能与函数名或「读」重名")
                walk(d["body"], 0, n, False)
            elif n.kind == "break" and depth == 0:
                error("「破」只能出现在当前函数的循环内")
            elif n.kind == "return" and (function is None or function.data["procedure"]):
                error("「得」只能出现在「算」定义内")
            elif n.kind == "bind" and (d["name"] in functions or d["name"] == "读"):
                error("变量名不能与函数名或「读」重名")
            elif n.kind == "if":
                walk(d["yes"], depth, function, False)
                walk(d["no"], depth, function, False)
            elif n.kind == "loop":
                walk(d["body"], depth+1, function, False)
    walk(program)
    return functions
