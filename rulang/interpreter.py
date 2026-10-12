"""Reference interpreter with shared mutable values and cached local modules.

Python's tracing collector owns object graphs, including arrays and objects
which refer to themselves. Rebinding a name never copies a mutable value.
"""
from dataclasses import dataclass
import math
from pathlib import Path
import re
import sys
from .diagnostics import at_token
from .frontend import BUILTIN_NAMES, RuError, bind_arguments, validate
from .io_runtime import install_io, io_member, io_new_defaults, read_stream_line, _write_stream
from .contest_runtime import install_contest, contest_member
from .practical_runtime import install_practical, practical_member
from .graphics_runtime import install_graphics, graphics_member

DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


@dataclass(frozen=True, eq=False)
class Pair:
    left: object
    right: object


class RuMap:
    """Hash-indexed buckets; entries hold shared keys/values, never host equality."""
    def __init__(self):
        self.buckets = {}
        self.size = 0
        self.version = 0

    def snapshot(self):
        return [entry for bucket in self.buckets.values() for entry in bucket]


@dataclass(eq=False)
class Function:
    owner: object
    node: object
    environment: object = None
    receiver: object = None
    parameter_types: object = None


@dataclass(eq=False)
class RuType:
    owner: object
    node: object
    parent: object = None
    fields: object = None
    methods: object = None
    state: int = 0

    @property
    def name(self):
        return self.node.data["name"]


@dataclass(eq=False)
class Instance:
    type: RuType
    fields: dict


@dataclass(eq=False)
class Module:
    interpreter: object

    def exports(self):
        owner = self.interpreter
        values = dict(owner.global_scope.values)
        values.update(owner.types)
        values.update(owner.function_values)
        return values



def value_type_name(value):
    """Describe the received value without suggesting unsupported conversions."""
    if value is None:
        return "空"
    if isinstance(value, bool):
        return "事实"
    if isinstance(value, RuMap):
        return "典"
    if isinstance(value, float):
        return "数"
    if isinstance(value, str):
        return "句"
    if isinstance(value, list):
        return "阵"
    if isinstance(value, Pair):
        return "对"
    if isinstance(value, Instance):
        return value.type.name
    if isinstance(value, Function):
        return "作" if value.node.data["procedure"] else "算"
    if isinstance(value, Module):
        return "外言"
    if isinstance(value, RuType):
        return "形声明"
    raise TypeError(f"unknown 如 value: {type(value).__name__}")


def display(value, active=None):
    """Format arbitrarily long pair chains without Python recursion."""
    active = set() if active is None else active
    output, stack = [], [("value", value)]
    while stack:
        operation, current = stack.pop()
        if operation == "text":
            output.append(current)
            continue
        if operation == "leave":
            active.remove(current)
            continue
        if current is None:
            output.append("空")
        elif isinstance(current, bool):
            output.append("真" if current else "假")
        elif isinstance(current, float):
            output.append(format(current, ".15g"))
        elif isinstance(current, str):
            output.append(current)
        elif isinstance(current, Instance):
            output.append(f"<形 {current.type.name}>")
        elif isinstance(current, RuType):
            output.append(f"<形 {current.name}>")
        elif isinstance(current, Module):
            output.append("<外言>")
        elif isinstance(current, Function):
            kind = "作" if current.node.data["procedure"] else "算"
            output.append(f"<{kind} {current.node.data['name']}>")
        elif isinstance(current, (Pair, list, RuMap)):
            identity = id(current)
            if identity in active:
                output.append("<循环>")
                continue
            active.add(identity)
            stack.append(("leave", identity))
            if isinstance(current, Pair):
                output.append("(")
                stack.extend([("text", ")"), ("value", current.right),
                              ("text", " 对 "), ("value", current.left)])
            elif isinstance(current, RuMap):
                entries = current.snapshot()
                output.append("{")
                stack.append(("text", "}"))
                for i in range(len(entries)-1, -1, -1):
                    key, value = entries[i]
                    stack.extend([("value", value), ("text", ": "), ("value", key)])
                    if i:
                        stack.append(("text", ", "))
            else:
                output.append("[")
                stack.append(("text", "]"))
                for i in range(len(current)-1, -1, -1):
                    stack.append(("value", current[i]))
                    if i:
                        stack.append(("text", ", "))
        else:
            raise TypeError(f"unknown 如 value: {type(current).__name__}")
    return "".join(output)


def truth(value):
    return value is not None and value is not False


def equal(left, right, instance_equal=None):
    pending, compared = [(left, right)], set()
    while pending:
        left, right = pending.pop()
        if type(left) is not type(right):
            return False
        if isinstance(left, Instance) and instance_equal is not None:
            if not instance_equal(left, right):
                return False
            continue
        if left is right:
            continue
        if isinstance(left, Pair):
            identities = (id(left), id(right))
            if identities in compared:
                continue
            compared.add(identities)
            pending.extend(((left.right, right.right), (left.left, right.left)))
        elif isinstance(left, (list, RuMap, Instance, Module, RuType, Function)):
            return False
        elif left != right:
            return False
    return True


class Scope:
    def __init__(self, parent=None, kind="module"):
        self.values, self.parent, self.kind = {}, parent, kind
        self.declarations = {}

    def find(self, name):
        current = self
        while current is not None:
            if name in current.values:
                return current.values[name], False
            if name in current.declarations:
                return current.declarations[name], True
            current = current.parent
        return _MISSING, False

    def get(self, name, token):
        value, _ = self.find(name)
        if value is not _MISSING:
            return value
        raise at_token(RuError(f"未定义名称：{name}", token.line, token.col, "运行错误"), token)

    def bind(self, name, value):
        # Block/rescue assignments remain local. Function assignments may update
        # a captured local cell, but never rebind a module or builtin global.
        if name in self.values or self.kind != "function":
            self.values[name] = value
            return
        current = self.parent
        while current is not None and current.kind != "module":
            if name in current.values:
                current.values[name] = value
                return
            current = current.parent
        self.values[name] = value

    def protected(self, name):
        current = self
        while current is not None:
            if name in current.declarations:
                return True
            current = current.parent
        return False


class Return(Exception):
    def __init__(self, value):
        self.value = value


class Finish(Exception):
    """Normal procedure completion, distinct from recoverable 卒."""
    pass


class Break(Exception):
    pass


class Panic(RuError):
    """Only explicit 卒 is recoverable; ordinary RuError remains fatal."""
    def __init__(self, reason, token):
        self.reason = reason
        super().__init__(reason, token.line, token.col, "未救之卒")
        at_token(self, token)


@dataclass(eq=False)
class FailedModule:
    """Keep escaped values' owner alive, without retaining exception tracebacks."""
    interpreter: object
    reason: str
    line: int
    col: int
    source_name: object = None
    source_text: str = ""

    def rethrow(self):
        error = Panic(self.reason, self)
        if self.source_name is not None:
            error.source_name = self.source_name
            error.source_text = self.source_text
        raise error


class Interpreter:
    def __init__(self, stdin=None, stdout=None, stderr=None):
        self.stdin, self.stdout = stdin or sys.stdin, stdout or sys.stdout
        self.stderr = sys.stderr if stderr is None else stderr
        self.global_scope, self.functions, self.depth = Scope(), {}, 0
        self.function_values = self.global_scope.declarations
        self.types, self.function_owners = {}, {}
        self.source_path, self.modules, self.module_cache = None, {}, {}
        self.loading = set()
        self.call_state = [0]
        self.last_member_procedure = False
        self.last_call_procedure = False
        install_io(self)
        install_contest(self)
        install_practical(self)
        install_graphics(self)
        if sys.getrecursionlimit() < 10000:
            sys.setrecursionlimit(10000)

    def fail(self, node, message):
        error = at_token(RuError(message, node.token.line, node.token.col, "运行错误"), node.token)
        if self.source_path and not getattr(error, "source_name", None):
            error.source_name = str(self.source_path)
            error.source_text = getattr(self.modules, "sources", {}).get(str(self.source_path), "")
        raise error

    def execute(self, program, echo=False, source_path=None, modules=None, module_cache=None):
        validate(program, self.functions, self.types)
        if source_path is not None:
            self.source_path = str(Path(source_path).resolve())
        if modules is not None:
            self.modules = modules
        if module_cache is not None:
            self.module_cache = module_cache
        for n in program:
            if n.kind == "function":
                if n.data["name"] in self.types or n.data["name"] in self.global_scope.values:
                    self.fail(n, f"名称冲突：{n.data['name']}")
                self.functions[n.data["name"]] = n
                self.function_owners[n.data["name"]] = self
                self.function_values[n.data["name"]] = Function(self, n, self.global_scope)
            elif n.kind == "type":
                if n.data["name"] in self.functions or n.data["name"] in self.global_scope.values:
                    self.fail(n, f"名称冲突：{n.data['name']}")
                self.types[n.data["name"]] = RuType(self, n)
        # Declarations are registered for forward references. Resolve parents
        # lazily (or at their statement), after any preceding imports execute.
        try:
            self.block(program, self.global_scope, echo)
        except RuError as error:
            self.locate_error(error)
            raise

    def locate_error(self, error):
        if self.source_path and not hasattr(error, "source_name"):
            error.source_name = self.source_path
            error.source_text = getattr(self.modules, "sources", {}).get(self.source_path, "")

    def execute_entry(self, args):
        fn = self.functions.get("元初")
        if fn is None or self.function_owners.get("元初", self) is not self:
            return 0
        params = fn.data["params"]
        if fn.data["procedure"] or len(params) != 1 or params[0][1] != "句 阵":
            self.fail(fn, "入口须声明为「算 元初 外参 为 句 阵」")
        result = self.call(fn, "元初", [(None, list(args))])
        if not isinstance(result, float) or result != int(result) or not 0 <= result <= 255:
            self.fail(fn, "元初须返回 0 至 255 的整数退出码")
        return int(result)

    def resolve_type(self, typ):
        if typ.state == 2:
            return typ
        if typ.state == 1:
            self.fail(typ.node, "形的继承形成循环")
        typ.state = 1
        try:
            parent_name = typ.node.data["parent"]
            if parent_name:
                parent = typ.owner.types.get(parent_name)
                if not isinstance(parent, RuType):
                    typ.owner.fail(typ.node, f"未定义父形：{parent_name}")
                parent.owner.resolve_type(parent)
                typ.parent = parent
                typ.fields, typ.methods = dict(parent.fields), dict(parent.methods)
            else:
                typ.fields, typ.methods = {}, {}
            for name, field_type in typ.node.data["fields"]:
                if name in typ.fields or name in typ.methods:
                    typ.owner.fail(typ.node, f"继承字段／方法重名：{name}")
                typ.owner.type_identity(field_type, typ.node)
                typ.fields[name] = (field_type, typ.owner)
            for fn in typ.node.data["methods"]:
                name = fn.data["name"]
                if name in typ.fields:
                    typ.owner.fail(fn, f"方法与字段重名：{name}")
                signature = [(key, typ.owner.type_identity(annotation, fn)) for key, annotation in fn.data["params"]]
                if name in typ.methods:
                    previous = typ.methods[name]
                    old = previous.node.data
                    old_signature = list(previous.parameter_types.items()) if previous.parameter_types is not None else [(key, previous.owner.type_identity(annotation, fn)) for key, annotation in old["params"]]
                    if (old_signature != signature
                            or old["procedure"] != fn.data["procedure"]):
                        typ.owner.fail(fn, f"覆写方法「{name}」须保持参数名称、类型及算／作种类")
                typ.methods[name] = Function(typ.owner, fn, typ.owner.global_scope, parameter_types=dict(signature))
            typ.state = 2
            return typ
        except Exception:
            typ.state = 0
            raise

    def type_identity(self, annotation, n):
        """Resolve in the declaration's module; empty annotations mean any value."""
        if annotation.endswith(" 阵"):
            return ("array", self.type_identity(annotation[:-2], n))
        if annotation in ("", "数", "句", "空", "阵", "对", "算", "作", "事实", "典"):
            return annotation
        typ = self.types.get(annotation) or self.builtin_types.get(annotation)
        if not isinstance(typ, RuType):
            self.fail(n, f"未定义类型：{annotation}；类型注解须使用已声明或已尽取导入的形名")
        return typ

    def type_detail(self, value, annotation, identity=None):
        """Describe only types and the first failing index, never payload values."""
        typ = annotation if identity is None else identity
        path = ""
        while annotation.endswith(" 阵") and isinstance(value, list):
            item_annotation = annotation[:-2]
            item_type = typ[1] if isinstance(typ, tuple) else item_annotation
            bad = next(((i, item) for i, item in enumerate(value)
                        if not self.type_matches(item, item_type)), None)
            if bad is None:
                break
            i, value = bad
            path += f"[{i}]"
            annotation, typ = item_annotation, item_type
        detail = f"；元素{path}须为{annotation}，实际收到{value_type_name(value)}" if path else ""
        if isinstance(value, Instance) and value.type.name == annotation:
            detail += "；同名但不同形身份：期望形与实际形来自不同声明；请核对所用形声明，若曾重定义，请按需重建相关实例或函数"
        return detail

    def ordinary_value(self, n, value):
        if isinstance(value, RuType):
            self.fail(n, f"形名「{value.name}」不能作为普通值；创建实例请用「新 {value.name}」，类型注解请直接使用形名")
        return value

    def type_matches(self, value, typ):
        if isinstance(typ, tuple):
            return isinstance(value, list) and all(self.type_matches(item, typ[1]) for item in value)
        if isinstance(typ, RuType):
            current = value.type if isinstance(value, Instance) else None
            while current is not None:
                if current is typ:
                    return True
                current = current.parent
            return False
        if typ == "":
            return True
        if typ.endswith(" 阵"):
            return isinstance(value, list) and all(self.type_matches(item, typ[:-2]) for item in value)
        if typ == "事实":
            return isinstance(value, bool)
        if typ == "典":
            return isinstance(value, RuMap)
        if typ == "数":
            return isinstance(value, float)
        if typ == "句":
            return isinstance(value, str)
        if typ == "空":
            return value is None
        if typ == "阵":
            return isinstance(value, list)
        if typ == "对":
            return isinstance(value, Pair)
        if typ in ("算", "作"):
            return isinstance(value, Function) and value.node.data["procedure"] == (typ == "作")
        expected = self.types.get(typ) or self.builtin_types.get(typ)
        if not isinstance(expected, RuType) or not isinstance(value, Instance):
            return False
        current = value.type
        while current is not None:
            if current is expected:
                return True
            current = current.parent
        return False

    def block(self, statements, scope, echo=False):
        for n in statements:
            d = n.data
            if n.kind == "function":
                continue
            if n.kind == "type":
                self.resolve_type(self.types[d["name"]])
            elif n.kind == "scope":
                local = Scope(scope, "block")
                self.hoist(d["body"], local)
                # A lexical block is not a call boundary: enclosing control
                # flow and REPL echo pass through unchanged.
                self.block(d["body"], local, echo)
            elif n.kind == "bind":
                if scope.protected(d["name"]) or d["name"] in self.types or d["name"] in BUILTIN_NAMES:
                    self.fail(n, "变量名不能与函数名、形名或内置名称重名")
                scope.bind(d["name"], self.expr(d["expr"], scope))
            elif n.kind == "assign":
                self.assign(n, scope)
            elif n.kind == "import_all":
                module = self.expr(d["expr"], scope)
                exports = module.exports()
                conflicts = set(exports) & (set(scope.values) | set(self.functions) | set(self.types) | BUILTIN_NAMES)
                if conflicts:
                    self.fail(n, "导入名称冲突：" + "、".join(sorted(conflicts)))
                for name, value in exports.items():
                    if name in module.interpreter.functions:
                        self.functions[name] = value.node
                        self.function_owners[name] = value.owner
                        self.function_values[name] = value
                    elif name in module.interpreter.types:
                        self.types[name] = value
                    else:
                        scope.values[name] = value
            elif n.kind == "print":
                value = self.expr(d["expr"], scope)
                try:
                    _write_stream(self.stdout, display(value) + "\n")
                except (OSError, ValueError) as error:
                    self.fail(n, "输出失败：" + str(error))
            elif n.kind == "expr":
                value = self.expr(d["expr"], scope)
                if echo and not self.is_procedure(d["expr"], scope):
                    try:
                        _write_stream(self.stdout, display(value) + "\n")
                    except (OSError, ValueError) as error:
                        self.fail(n, "输出失败：" + str(error))
            elif n.kind == "panic":
                reason = self.expr(d["expr"], scope)
                if not isinstance(reason, str):
                    self.fail(n, "「卒」的原因须为句")
                error = Panic(reason, n.token)
                self.locate_error(error)
                raise error
            elif n.kind == "try":
                try:
                    self.block(d["body"], scope)
                except Panic as error:
                    if scope.protected(d["reason"]) or d["reason"] in self.types or d["reason"] in BUILTIN_NAMES:
                        self.fail(n, "救的原因名称不能与函数名、形名或内置名称重名")
                    handler = Scope(scope, "rescue")
                    handler.values[d["reason"]] = error.reason
                    self.hoist(d["rescue"], handler)
                    # Outside the protected suite: a new 卒 here propagates
                    # to an enclosing dynamically active 试.
                    self.block(d["rescue"], handler)
            elif n.kind == "return":
                raise Return(self.expr(d["expr"], scope))
            elif n.kind == "finish":
                raise Finish()
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

    def is_procedure(self, expr, scope):
        # Do not re-evaluate member receivers merely to decide REPL echo.
        if expr.kind == "name":
            value, declared = scope.find(expr.data["name"])
            return declared and isinstance(value, Function) and value.node.data["procedure"]
        if expr.kind in ("call", "invoke"):
            return self.last_call_procedure
        return (expr.kind == "member" or (expr.kind == "binary" and expr.data["op"] == "含")) and self.last_member_procedure

    def hoist(self, statements, scope):
        for statement in statements:
            if statement.kind == "function":
                name = statement.data["name"]
                if name in scope.values or name in scope.declarations or name in self.types or name in BUILTIN_NAMES:
                    self.fail(statement, "重复或保留的函数名称：" + name)
                scope.declarations[name] = Function(self, statement, scope)

    def resolve_name(self, n, scope):
        value, declared = scope.find(n.data["name"])
        if value is _MISSING and n.data["name"] in self.types:
            return self.ordinary_value(n, self.types[n.data["name"]]), False
        if value is _MISSING:
            self.fail(n, ("未定义函数：" if n.kind == "call" else "未定义名称：") + n.data["name"])
        return self.ordinary_value(n, value), declared

    def callable_target(self, n, scope):
        """Evaluate a call/ref target once without auto-invoking its last selector."""
        if n.kind == "name":
            if n.data["name"] == "读":
                self.fail(n, "当前仅支持用户定义算／作的引用；内置「读」不能取引用")
            return self.resolve_name(n, scope)[0]
        if n.kind == "member" and not n.data["args"]:
            receiver = self.expr(n.data["receiver"], scope)
            return self.member_reference(n, receiver, n.data["name"])
        return self.expr(n, scope)

    def invoke_value(self, n, value, args):
        if not isinstance(value, Function):
            self.fail(n, "值不是算／作" + ("；若要索引，请让方括号紧邻接收者，如 列[0]；列 [0] 会被解析为调用" if isinstance(value, (list, str, RuMap)) and len(args) == 1 and isinstance(args[0][1], list) else ""))
        result = value.owner.invoke(n, value.node, args, value.receiver,
                                    caller=self, environment=value.environment, parameter_types=value.parameter_types)
        self.last_call_procedure = value.node.data["procedure"]
        return result

    def member_reference(self, n, receiver, name):
        if isinstance(receiver, Module):
            value = self.ordinary_value(n, receiver.exports().get(name, _MISSING))
            if value is not _MISSING:
                return self.ordinary_value(n, value)
        elif isinstance(receiver, Instance):
            if name in receiver.type.fields:
                return receiver.fields[name]
            method = receiver.type.methods.get(name)
            if method:
                return Function(method.owner, method.node, method.environment, receiver, method.parameter_types)
        elif isinstance(receiver, Pair) and name in ("囫", "囵"):
            return receiver.left if name == "囫" else receiver.right
        elif isinstance(receiver, (list, str)) and name == "量":
            return float(len(receiver))
        self.fail(n, "无法取得用户定义算／作成员引用：" + name)

    def bounded_index(self, n, value, size, endpoint=False):
        maximum = size if endpoint else size - 1
        if not isinstance(value, float) or not math.isfinite(value) or value != int(value):
            self.fail(n, "索引须为整数")
        if value < 0 or value > maximum:
            self.fail(n, f"索引越界：{display(value)}（长度 {size}）")
        return int(value)

    def get_index(self, n, receiver, index):
        if isinstance(receiver, RuMap):
            return self.map_member(n, receiver, "查", [(None, index)])
        if not isinstance(receiver, (list, str)):
            self.fail(n, "「位」／索引只适用于阵或句")
        return receiver[self.bounded_index(n, index, len(receiver))]

    def get_slice(self, n, receiver, start, end):
        if not isinstance(receiver, (list, str)):
            self.fail(n, "「段」／切片只适用于阵或句")
        first = 0 if start is None else self.bounded_index(n, start, len(receiver), True)
        last = len(receiver) if end is None else self.bounded_index(n, end, len(receiver), True)
        if first > last:
            self.fail(n, "切片起点不能大于终点")
        return receiver[first:last]

    def assign(self, n, scope):
        target, d = n.data["target"], n.data["target"].data
        receiver = self.expr(d["receiver"], scope)
        if target.kind == "index":
            index = self.expr(d["index"], scope)
        elif d["name"] == "位" and isinstance(receiver, list):
            args = [(key, self.expr(expr, scope)) for key, expr in d["args"]]
            bound = bind_arguments("位", args, ["位"], lambda message: self.fail(n, message))
            index = bound["位"]
        else:
            if not isinstance(receiver, Instance) or d["args"] or d["name"] not in receiver.type.fields:
                self.fail(n, f"不可赋值的字段：{d['name']}")
            value = self.expr(n.data["expr"], scope)
            field_type, owner = receiver.type.fields[d["name"]]
            if value is not None and not owner.type_matches(value, field_type):
                self.fail(n, f"字段「{d['name']}」须为{field_type}，实际收到{value_type_name(value)}" + owner.type_detail(value, field_type))
            receiver.fields[d["name"]] = value
            return
        if not isinstance(receiver, list):
            self.fail(n, "只有阵元素可赋值；句不可变")
        offset = self.bounded_index(n, index, len(receiver))
        receiver[offset] = self.expr(n.data["expr"], scope)

    def import_module(self, n):
        path = n.data.get("resolved")
        if path is None:
            from .modules import resolve_import
            try:
                path = resolve_import(n.data["path"], self.source_path or str(Path.cwd() / "<REPL>"))
            except RuError as error:
                error.line, error.col = n.token.line, n.token.col
                raise
        if path in self.loading:
            self.fail(n, "外言导入形成循环：" + path)
        if path in self.module_cache:
            cached = self.module_cache[path]
            if isinstance(cached, FailedModule):
                cached.rethrow()
            return cached
        if path not in self.modules:
            from .modules import load_module_graph
            self.modules.update(load_module_graph(path))
        child = Interpreter(self.stdin, self.stdout, self.stderr)
        child.loading, child.call_state = self.loading, self.call_state
        child.graphics_host = self.graphics_host
        self.loading.add(path)
        try:
            child.execute(self.modules[path], source_path=path, modules=self.modules, module_cache=self.module_cache)
        except Panic as error:
            self.module_cache[path] = FailedModule(child, error.reason, error.line, error.col,
                getattr(error, "source_name", None), getattr(error, "source_text", ""))
            raise
        finally:
            self.loading.remove(path)
        module = Module(child)
        self.module_cache[path] = module
        return module

    def expr(self, n, scope):
        d = n.data
        if n.kind in ("number", "string", "fact"):
            return d["value"]
        if n.kind == "name":
            name = d["name"]
            if name == "读":
                return self.call(n, name, [])
            value, declared = self.resolve_name(n, scope)
            return self.invoke_value(n, value, []) if declared else value
        if n.kind == "binary":
            op = d["op"]
            left = self.expr(d["left"], scope)
            if op == "且":
                return truth(left) and truth(self.expr(d["right"], scope))
            if op == "或":
                return truth(left) or truth(self.expr(d["right"], scope))
            right = self.expr(d["right"], scope)
            if op == "对":
                return Pair(left, right)
            if op in ("==", "!="):
                same = self.equals(n, left, right)
                return same if op == "==" else not same
            if op == "含":
                if isinstance(left, (Instance, Module)):
                    return self.member(n, left, "含", [(None, right)])
                self.last_member_procedure = False
                if not isinstance(left, str) or not isinstance(right, str):
                    self.fail(n, "「含」需要两个句")
                return right in left
            if op in ("<", "<=", ">", ">="):
                if type(left) is not type(right) or not isinstance(left, (str, float)):
                    self.fail(n, "大小比较需要两个数或两个句" + ("；比较结果为事实，若要连续比较，请拆成两个比较并用「且」连接" if isinstance(left, bool) or isinstance(right, bool) else ""))
                if op == "<":
                    return left < right
                if op == "<=":
                    return left <= right
                if op == ">":
                    return left > right
                return left >= right
            if op == "+" and isinstance(left, str) and isinstance(right, str):
                return left + right
            if not isinstance(left, float) or not isinstance(right, float):
                self.fail(n, "算术运算需要两个数；「+」也可连接两个句")
            if op in ("/", "%") and right == 0:
                self.fail(n, "除数不能为零")
            if op == "+":
                result = left + right
            elif op == "-":
                result = left - right
            elif op == "*":
                result = left * right
            elif op == "/":
                result = left / right
            elif op == "%":
                result = math.fmod(left, right)
            else:
                raise KeyError(op)
            if not math.isfinite(result):
                self.fail(n, "运算结果不是有限数")
            return result
        if n.kind == "index":
            return self.get_index(n, self.expr(d["receiver"], scope), self.expr(d["index"], scope))
        if n.kind == "member":
            receiver = self.expr(d["receiver"], scope)
            # A callable field/export may be rebound by an argument. Capture
            # its value (or bound method) before evaluating those arguments.
            if isinstance(receiver, Instance):
                if d["name"] in receiver.type.fields and d["args"]:
                    value = receiver.fields[d["name"]]
                    args = [(key, self.expr(expr, scope)) for key, expr in d["args"]]
                    result = self.invoke_value(n, value, args)
                    self.last_member_procedure = value.node.data["procedure"]
                    return result
                if d["name"] in receiver.type.methods:
                    value = self.member_reference(n, receiver, d["name"])
                    args = [(key, self.expr(expr, scope)) for key, expr in d["args"]]
                    result = self.invoke_value(n, value, args)
                    self.last_member_procedure = value.node.data["procedure"]
                    return result
            elif isinstance(receiver, Module):
                value = self.ordinary_value(n, receiver.exports().get(d["name"], _MISSING))
                if value is not _MISSING and (d["args"] or d["name"] in receiver.interpreter.functions):
                    args = [(key, self.expr(expr, scope)) for key, expr in d["args"]]
                    result = self.invoke_value(n, value, args)
                    self.last_member_procedure = value.node.data["procedure"]
                    return result
            args = [(key, self.expr(expr, scope)) for key, expr in d["args"]]
            return self.member(n, receiver, d["name"], args)
        if n.kind == "null":
            return None
        if n.kind == "map":
            result = RuMap()
            for key_node, value_node in d["entries"]:
                key = self.expr(key_node, scope)
                value = self.expr(value_node, scope)
                self.map_put(n, result, key, value)
            return result
        if n.kind == "array":
            return [self.expr(item, scope) for item in d["items"]]
        if n.kind == "self":
            return scope.get("其", n.token)
        if n.kind == "import":
            return self.import_module(n)
        if n.kind == "call":
            if d["name"] == "读":
                return self.call(n, "读", [(name, self.expr(expr, scope)) for name, expr in d["args"]])
            # Resolve the callee before arguments can mutate a captured binding.
            value = self.resolve_name(n, scope)[0]
            args = [(name, self.expr(expr, scope)) for name, expr in d["args"]]
            return self.invoke_value(n, value, args)
        if n.kind == "function_literal":
            return Function(self, n, scope)
        if n.kind == "function_ref":
            value = self.callable_target(d["expr"], scope)
            if not isinstance(value, Function) or value.node.data["procedure"] != d["procedure"]:
                self.fail(n, "引用的算／作种类不匹配")
            return value
        if n.kind == "invoke":
            if d["callee"].kind == "name" and d["callee"].data["name"] == "读":
                return self.call(n, "读", [(name, self.expr(expr, scope)) for name, expr in d["args"]])
            value = self.callable_target(d["callee"], scope)
            args = [(name, self.expr(expr, scope)) for name, expr in d["args"]]
            return self.invoke_value(n, value, args)
        if n.kind == "new":
            typ = self.types.get(d["name"]) or self.builtin_types.get(d["name"])
            if typ is None:
                self.fail(n, f"未定义形：{d['name']}；新 后须使用已声明或已尽取导入的形名")
            if not isinstance(typ, RuType):
                self.fail(n, f"「{d['name']}」不是形")
            typ.owner.resolve_type(typ)
            fields = io_new_defaults(typ)
            if fields is None:
                fields = {name: None for name in typ.fields}
            provided = set()
            for key, expr in d["args"]:
                if key in provided:
                    self.fail(n, f"重复的字段实参：{key}")
                if key not in fields:
                    self.fail(n, f"未知字段：{key}")
                value = self.expr(expr, scope)
                field_type, owner = typ.fields[key]
                if value is not None and not owner.type_matches(value, field_type):
                    self.fail(n, f"字段「{key}」须为{field_type}，实际收到{value_type_name(value)}" + owner.type_detail(value, field_type))
                fields[key] = value
                provided.add(key)
            return Instance(typ, fields)
        if n.kind == "slice":
            receiver = self.expr(d["receiver"], scope)
            start = None if d["start"] is None else self.expr(d["start"], scope)
            end = None if d["end"] is None else self.expr(d["end"], scope)
            return self.get_slice(n, receiver, start, end)
        if n.kind == "convert":
            value = self.expr(d["expr"], scope)
            if d["target"] == "事实":
                return truth(value)
            if d["target"] == "阵":
                return [value]
            if d["target"] == "句":
                return display(value)
            return self.number_value(n, value)
        if n.kind == "unary":
            value = self.expr(d["expr"], scope)
            if d["op"] == "非":
                return not truth(value)
            if not isinstance(value, float):
                self.fail(n, "正负号只能用于数")
            return value if d["op"] == "+" else -value
        raise AssertionError(n.kind)

    def special_method(self, n, value, name, arity):
        method = value.type.methods.get(name)
        if method is None or method.node.data["procedure"] or len(method.node.data["params"]) != arity:
            self.fail(n, f"形的「{name}」须为接受 {arity} 个参数的算")
        return Function(method.owner, method.node, method.environment, value, method.parameter_types)

    def equals(self, n, left, right):
        def instance_equal(a, b):
            if a.type is not b.type:
                return False
            if "同" not in a.type.methods:
                return a is b
            method = self.special_method(n, a, "同", 1)
            result = self.invoke_value(n, method, [(None, b)])
            if not isinstance(result, bool):
                self.fail(n, "「同」须返回事实")
            return result
        return equal(left, right, instance_equal)

    def map_hash(self, n, key):
        if isinstance(key, bool):
            return ("事实", key)
        if isinstance(key, float):
            if not math.isfinite(key):
                self.fail(n, "典的数键须为有限数")
            return ("数", key)
        if isinstance(key, str):
            return ("句", key)
        if isinstance(key, Instance):
            self.special_method(n, key, "同", 1)
            method = self.special_method(n, key, "印", 0)
            value = self.invoke_value(n, method, [])
            if not isinstance(value, float) or not math.isfinite(value) or value != math.trunc(value) or abs(value) > 9007199254740991:
                self.fail(n, "「印」须返回安全整数范围内的数")
            return ("形", id(key.type), value)
        self.fail(n, "典的键须为数、句、事实或提供同与印的形实例；实际收到" + value_type_name(key))

    def map_find(self, n, receiver, key):
        version = receiver.version
        hashed = self.map_hash(n, key)
        if receiver.version != version:
            self.fail(n, "典在键的印／同比较期间被修改")
        bucket = receiver.buckets.get(hashed, [])
        for index, (stored, _) in enumerate(bucket):
            same = self.equals(n, stored, key)
            if receiver.version != version:
                self.fail(n, "典在键的印／同比较期间被修改")
            if same:
                return hashed, bucket, index
        return hashed, bucket, -1

    def map_put(self, n, receiver, key, value):
        hashed, bucket, index = self.map_find(n, receiver, key)
        if index < 0:
            receiver.buckets.setdefault(hashed, bucket).append((key, value))
            receiver.size += 1
        else:
            bucket[index] = (bucket[index][0], value)
        receiver.version += 1
        return receiver

    def map_member(self, n, receiver, name, args):
        params = {"查": ["目"], "增": ["目", "相"], "除": ["目"], "列": ["回调"], "量": []}
        if name not in params:
            self.fail(n, f"未知成员：{name}")
        bound = bind_arguments(name, args, params[name], lambda message: self.fail(n, message))
        if name == "量":
            return float(receiver.size)
        if name == "增":
            return self.map_put(n, receiver, bound["目"], bound["相"])
        if name == "列":
            callback = bound["回调"]
            if not isinstance(callback, Function) or len(callback.node.data["params"]) != 2:
                self.fail(n, "典的列回调须为接受两个参数的算或作")
            for key, value in receiver.snapshot():
                self.invoke_value(n, callback, [(None, key), (None, value)])
            self.last_member_procedure = False
            return None
        hashed, bucket, index = self.map_find(n, receiver, bound["目"])
        if name == "查":
            return None if index < 0 else bucket[index][1]
        if index < 0:
            return False
        del bucket[index]
        if not bucket:
            del receiver.buckets[hashed]
        receiver.size -= 1
        receiver.version += 1
        return True

    def number_value(self, n, value):
        """One strict numeric conversion shared by 为 数 and contest input."""
        if isinstance(value, float):
            return value
        if not isinstance(value, str):
            self.fail(n, "只有数或句可转换为数")
        stripped = value.strip(" \t\r\n\v\f")
        if not DECIMAL.fullmatch(stripped):
            self.fail(n, f"无法转换为数：{value}")
        result = float(stripped)
        if not math.isfinite(result):
            self.fail(n, "转换结果不是有限数")
        return result

    def member(self, n, receiver, name, args):
        fail = lambda message: self.fail(n, message)
        self.last_member_procedure = False
        if isinstance(receiver, RuMap):
            return self.map_member(n, receiver, name, args)
        handled, result = graphics_member(self, n, receiver, name, args)
        if handled:
            return result
        handled, result = practical_member(self, n, receiver, name, args)
        if handled:
            return result
        handled, result = contest_member(self, n, receiver, name, args)
        if handled:
            return result
        handled, result = io_member(self, n, receiver, name, args)
        if handled:
            return result
        if isinstance(receiver, Instance):
            if name in receiver.type.fields:
                bind_arguments(name, args, [], fail)
                return receiver.fields[name]
            method = receiver.type.methods.get(name)
            if method:
                result = method.owner.invoke(n, method.node, args, receiver, caller=self, parameter_types=method.parameter_types)
                self.last_member_procedure = method.node.data["procedure"]
                return result
        elif isinstance(receiver, Module):
            value = self.ordinary_value(n, receiver.exports().get(name, _MISSING))
            if value is not _MISSING:
                if isinstance(value, Function) and (args or name in receiver.interpreter.functions):
                    result = self.invoke_value(n, value, args)
                    self.last_member_procedure = value.node.data["procedure"]
                    return result
                bind_arguments(name, args, [], fail)
                return value
        elif isinstance(receiver, Pair) and name in ("囫", "囵"):
            bind_arguments(name, args, [], fail)
            return receiver.left if name == "囫" else receiver.right
        elif isinstance(receiver, (str, list)):
            if name == "量":
                bind_arguments(name, args, [], fail)
                return float(len(receiver))
            if name == "位":
                bound = bind_arguments(name, args, ["位"], fail)
                return self.get_index(n, receiver, bound["位"])
            if name == "段":
                bound = bind_arguments(name, args, ["始", "终"], fail)
                return self.get_slice(n, receiver, bound["始"], bound["终"])
            if name == "含" and isinstance(receiver, str):
                bound = bind_arguments(name, args, ["句"], fail)
                if not isinstance(bound["句"], str):
                    self.fail(n, "「含」需要两个句")
                return bound["句"] in receiver
            if isinstance(receiver, list) and name in ("删", "弹", "查"):
                parameters = {"删": ["位"], "弹": [], "查": ["值"]}[name]
                bound = bind_arguments(name, args, parameters, fail)
                if name == "查":
                    for index, value in enumerate(receiver[:]):
                        if self.equals(n, value, bound["值"]):
                            self.last_member_procedure = False
                            return float(index)
                    self.last_member_procedure = False
                    return None
                position = bound["位"] if name == "删" else float(len(receiver) - 1)
                self.get_index(n, receiver, position)
                return receiver.pop(int(position))
            if name == "增" and isinstance(receiver, list):
                bound = bind_arguments(name, args, ["值"], fail)
                receiver.append(bound["值"])
                return receiver
        self.fail(n, f"未知成员：{name}")

    def call(self, n, name, args):
        fail = lambda message: self.fail(n, message)
        if name == "读":
            kwargs = bind_arguments(name, args, ["提示"], fail, optional=True)
            prompt = kwargs.get("提示", "")
            if not isinstance(prompt, str):
                self.fail(n, "输入提示须为句")
            try:
                _write_stream(self.stdout, prompt)
            except (OSError, ValueError) as error:
                self.fail(n, "输出失败：" + str(error))
            try:
                value = read_stream_line(self.stdin)
            except (OSError, UnicodeError, ValueError) as error:
                self.fail(n, "读取输入失败：" + str(error))
            if value == "":
                self.fail(n, "输入结束（EOF）")
            if "\x00" in value:
                self.fail(n, "输入不能含 NUL")
            self.last_call_procedure = False
            return value.removesuffix("\n").removesuffix("\r")
        if name not in self.functions:
            self.fail(n, f"未定义函数：{name}")
        return self.invoke_value(n, self.function_values[name], args)

    def invoke(self, n, function, args, receiver=None, caller=None, environment=None, parameter_types=None):
        caller = self if caller is None else caller
        name, params = function.data["name"], function.data["params"]
        # Imports execute lazily. Validate against the function owner's names
        # at invocation, without rejecting calls before an import has run or
        # treating ordinary imported bindings/type aliases as declarations.
        environment = self.global_scope if environment is None else environment
        if any(environment.protected(key) or key in self.types for key, _ in params):
            self.fail(function, "参数名不能与函数名、形名或内置名称重名")
        kwargs = bind_arguments(name, args, [p[0] for p in params], lambda message: caller.fail(n, message))
        local = Scope(environment, "function")
        if receiver is not None:
            local.values["其"] = receiver
        for key, typ in params:
            value = kwargs[key]
            if not self.type_matches(value, parameter_types[key] if parameter_types is not None else self.type_identity(typ, function)):
                caller.fail(n, f"函数「{name}」的实参「{key}」须为{typ}，实际收到{value_type_name(value)}" + self.type_detail(value, typ, parameter_types[key] if parameter_types is not None else self.type_identity(typ, function)))
            local.values[key] = value
        self.hoist(function.data["body"], local)
        if self.call_state[0] >= 128:
            caller.fail(n, "函数调用层数超过 128")
        self.call_state[0] += 1
        self.depth += 1
        try:
            try:
                self.block(function.data["body"], local)
            except Return as result:
                return result.value
            except Finish:
                return None
            if function.data["procedure"]:
                return None
            caller.fail(n, f"函数「{name}」没有执行「得」")
        except RuError as error:
            at_token(error, function.token)
            self.locate_error(error)
            raise
        finally:
            self.call_state[0] -= 1
            self.depth -= 1


_MISSING = object()
