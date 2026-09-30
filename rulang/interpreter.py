"""Reference interpreter; the REPL retains this state between submissions."""
import math
import re
import sys
from .frontend import RuError, bind_arguments, validate

DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


def display(value):
    return format(value, ".15g") if isinstance(value, float) else value


def truth(value):
    return value != 0 if isinstance(value, float) else len(value) != 0


class Scope:
    def __init__(self, parent=None):
        self.values, self.parent = {}, parent

    def get(self, name, token):
        if name in self.values:
            return self.values[name]
        if self.parent is not None:
            return self.parent.get(name, token)
        raise RuError(f"未定义名称：{name}", token.line, token.col, "运行错误")


class Return(Exception):
    def __init__(self, value):
        self.value = value


class Break(Exception):
    pass


class Interpreter:
    def __init__(self, stdin=None, stdout=None):
        self.stdin, self.stdout = stdin or sys.stdin, stdout or sys.stdout
        self.global_scope, self.functions, self.depth = Scope(), {}, 0
        if sys.getrecursionlimit() < 10000:
            sys.setrecursionlimit(10000)

    def fail(self, node, message):
        raise RuError(message, node.token.line, node.token.col, "运行错误")

    def execute(self, program, echo=False):
        validate(program, self.functions)
        for n in program:
            if n.kind == "function":
                self.functions[n.data["name"]] = n
        self.block(program, self.global_scope, echo)

    def block(self, statements, scope, echo=False):
        for n in statements:
            d = n.data
            if n.kind == "function":
                continue
            if n.kind == "bind":
                scope.values[d["name"]] = self.expr(d["expr"], scope)
            elif n.kind == "print":
                print(display(self.expr(d["expr"], scope)), file=self.stdout, flush=True)
            elif n.kind == "expr":
                value = self.expr(d["expr"], scope)
                if echo and not (d["expr"].kind in ("name", "call") and
                                 self.functions.get(d["expr"].data.get("name")) and
                                 self.functions[d["expr"].data["name"]].data["procedure"]):
                    print(display(value), file=self.stdout, flush=True)
            elif n.kind == "return":
                raise Return(self.expr(d["expr"], scope))
            elif n.kind == "break":
                raise Break()
            elif n.kind == "if":
                self.block(d["yes"] if truth(self.expr(d["condition"], scope)) else d["no"], scope)
            elif n.kind == "loop":
                count = None
                if d["count"] is not None:
                    value = self.expr(d["count"], scope)
                    if not isinstance(value, float) or not math.isfinite(value) or value < 0 or value > 9007199254740991 or value != int(value):
                        self.fail(n, "循环次数须为 0 至 9007199254740991 之间的整数")
                    count = int(value)
                i = 0
                while count is None or i < count:
                    try:
                        self.block(d["body"], scope)
                    except Break:
                        break
                    i += 1

    def expr(self, n, scope):
        d = n.data
        if n.kind in ("number", "string"):
            return d["value"]
        if n.kind == "name":
            name = d["name"]
            if name == "读" or name in self.functions:
                return self.call(n, name, [])
            return scope.get(name, n.token)
        if n.kind == "call":
            return self.call(n, d["name"], [(name, self.expr(expr, scope)) for name, expr in d["args"]])
        if n.kind == "convert":
            value = self.expr(d["expr"], scope)
            if d["target"] == "句":
                return display(value)
            if isinstance(value, float):
                return value
            stripped = value.strip(" \t\r\n\v\f")
            if not DECIMAL.fullmatch(stripped):
                self.fail(n, f"无法转换为数：{value}")
            result = float(stripped)
            if not math.isfinite(result):
                self.fail(n, "转换结果不是有限数")
            return result
        if n.kind == "unary":
            value = self.expr(d["expr"], scope)
            if d["op"] == "非":
                return float(not truth(value))
            if not isinstance(value, float):
                self.fail(n, "正负号只能用于数")
            return value if d["op"] == "+" else -value
        if n.kind == "binary":
            op = d["op"]
            left = self.expr(d["left"], scope)
            if op == "且":
                return float(truth(left) and truth(self.expr(d["right"], scope)))
            if op == "或":
                return float(truth(left) or truth(self.expr(d["right"], scope)))
            right = self.expr(d["right"], scope)
            if op in ("==", "!="):
                equal = type(left) is type(right) and left == right
                return float(equal if op == "==" else not equal)
            if op == "含":
                if not isinstance(left, str) or not isinstance(right, str):
                    self.fail(n, "「含」需要两个句")
                return float(right in left)
            if op in ("<", "<=", ">", ">="):
                if type(left) is not type(right):
                    self.fail(n, "比较需要相同类型")
                return float({"<": lambda: left < right, "<=": lambda: left <= right,
                              ">": lambda: left > right, ">=": lambda: left >= right}[op]())
            if op == "+" and isinstance(left, str) and isinstance(right, str):
                return left + right
            if not isinstance(left, float) or not isinstance(right, float):
                self.fail(n, "算术运算需要两个数；「+」也可连接两个句")
            if op in ("/", "%") and right == 0:
                self.fail(n, "除数不能为零")
            result = {"+": lambda: left + right, "-": lambda: left - right,
                      "*": lambda: left * right, "/": lambda: left / right,
                      "%": lambda: math.fmod(left, right)}[op]()
            if not math.isfinite(result):
                self.fail(n, "运算结果不是有限数")
            return result
        raise AssertionError(n.kind)

    def call(self, n, name, args):
        fail = lambda message: self.fail(n, message)
        if name == "读":
            kwargs = bind_arguments(name, args, ["提示"], fail, optional=True)
            prompt = kwargs.get("提示", "")
            if not isinstance(prompt, str):
                self.fail(n, "输入提示须为句")
            self.stdout.write(prompt)
            self.stdout.flush()
            value = self.stdin.readline()
            if value == "":
                self.fail(n, "输入结束（EOF）")
            if "\x00" in value:
                self.fail(n, "输入不能含 NUL")
            return value.removesuffix("\n").removesuffix("\r")
        if name not in self.functions:
            self.fail(n, f"未定义函数：{name}")
        function = self.functions[name]
        params = function.data["params"]
        kwargs = bind_arguments(name, args, [p[0] for p in params], fail)
        local = Scope(self.global_scope)
        for key, typ in params:
            value = kwargs[key]
            if (typ == "数") != isinstance(value, float):
                self.fail(n, f"实参「{key}」须为{typ}，请显式使用「为 {typ}」转换")
            local.values[key] = value
        if self.depth >= 128:
            self.fail(n, "函数调用层数超过 128")
        self.depth += 1
        try:
            try:
                self.block(function.data["body"], local)
            except Return as result:
                return result.value
            if function.data["procedure"]:
                return ""
            self.fail(n, f"函数「{name}」没有执行「得」")
        finally:
            self.depth -= 1
