"""Reference interpreter with shared mutable values and cached local modules.

Python's tracing collector owns object graphs, including arrays and objects
which refer to themselves. Rebinding a name never copies a mutable value.
"""
from .execution_budget import checked_operation
from dataclasses import dataclass
import math
from itertools import repeat
from types import GeneratorType
from pathlib import Path
import re
import sys
from .execution_budget import charge, bulk, check_budget, guard_budget, current_budget, items as budget_items
from .diagnostics import at_token
from .frontend import BUILTIN_NAMES, RuError, bind_arguments, validate
from .io_runtime import install_io, io_member, io_new_defaults, read_stream_line, _write_stream
from .contest_runtime import install_contest, contest_member
from .practical_runtime import install_practical, practical_member
from .graphics_runtime import install_graphics, graphics_member
from .native_runtime import install_native, native_member, check_native_imports, NativeFault

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
        bulk(self.size)
        result = [entry for bucket in self.buckets.values() for entry in bucket]
        check_budget()
        return result


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
        bulk(len(owner.global_scope.values) + len(owner.types) + len(owner.function_values))
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
        charge("helper_item")
        if current is None:
            output.append("空")
        elif isinstance(current, bool):
            output.append("真" if current else "假")
        elif isinstance(current, float):
            output.append(format(current, ".15g"))
        elif isinstance(current, str):
            bulk(len(current))
            output.append(current)
        elif isinstance(current, Instance):
            bulk(len(current.type.name))
            output.append(f"<形 {current.type.name}>")
        elif isinstance(current, RuType):
            bulk(len(current.name))
            output.append(f"<形 {current.name}>")
        elif isinstance(current, Module):
            output.append("<外言>")
        elif isinstance(current, Function):
            bulk(len(current.node.data["name"]))
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
                    charge("helper_item")
                    key, value = entries[i]
                    stack.extend([("value", value), ("text", ": "), ("value", key)])
                    if i:
                        stack.append(("text", ", "))
            else:
                output.append("[")
                stack.append(("text", "]"))
                for i in range(len(current)-1, -1, -1):
                    charge("helper_item")
                    stack.append(("value", current[i]))
                    if i:
                        stack.append(("text", ", "))
        else:
            raise TypeError(f"unknown 如 value: {type(current).__name__}")
    bulk(sum(map(len, output)))
    result = "".join(output)
    check_budget()
    return result


def truth(value):
    return value is not None and value is not False


def equal(left, right, instance_equal=None):
    pending, compared = [(left, right)], set()
    while pending:
        charge("helper_item")
        left, right = pending.pop()
        if type(left) is not type(right):
            return False
        if isinstance(left, str):
            # Logical input cost must not depend on CPython string interning.
            bulk(len(left) + len(right))
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
        else:
            different = left != right
            check_budget()
            if different:
                return False
    return True


class Scope:
    def __init__(self, parent=None, kind="module"):
        self.values, self.parent, self.kind = {}, parent, kind
        self.declarations = {}

    def find(self, name):
        current = self
        while current is not None:
            charge("helper_item")
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
            charge("helper_item")
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


class Continue(Exception):
    """Skip one loop iteration, never a callable or recoverable panic."""
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


# Combined logical expression/statement nesting budget. The evaluator stores
# continuations on an explicit stack, so this is a language resource bound,
# not a promise about Python's recursion limit or the operating-system C stack.
STRUCTURE_DEPTH_LIMIT = 8000


class _Value:
    """A completed leaf task; avoids a generator/frame for pure scalar work."""
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


def _drive(frame):
    """Drive suspended tasks iteratively; never recursively delegate/send.

    Errors are thrown into each parent to preserve its rescue/finally boundary.
    Host/native re-entry owns another local stack without resetting Ru state.
    """
    guard_budget()
    if isinstance(frame, _Value):
        return frame.value
    stack = [frame]
    value, error = None, None
    try:
        while stack:
            try:
                if error is None:
                    child = stack[-1].send(value)
                else:
                    current_error, error = error, None
                    try:
                        child = stack[-1].throw(current_error)
                    finally:
                        # Do not retain rescued error scopes for the rest of
                        # a long-running execution after its handler resumes.
                        current_error = None
            except StopIteration as finished:
                stack.pop()
                value, error = finished.value, None
            except BaseException as failed:
                stack.pop()
                value, error = None, failed
            else:
                if isinstance(child, _Value):
                    value = child.value
                elif isinstance(child, GeneratorType):
                    value = None
                    stack.append(child)
                else:
                    value = None
                    error = AssertionError("invalid interpreter continuation")
        if error is not None:
            raise error
        return value
    finally:
        # Also cover asynchronous interruption between send/throw operations.
        # Only our still-suspended frames are closed, never a host caller's
        # independent re-entry stack. Keep closing even if one finalizer fails.
        cleanup_error = None
        while stack:
            abandoned = stack.pop()
            try:
                abandoned.close()
            except BaseException as failed:
                if cleanup_error is None:
                    cleanup_error = failed
        if cleanup_error is not None:
            raise cleanup_error


def _type_resolution(typ):
    owner = typ.owner
    if isinstance(owner, Interpreter):
        return owner._resolve_type_step(typ)
    # IO/contest builtin types have a small already-resolved host owner, not
    # an Interpreter. Its original synchronous contract is still supported.
    return _Value(owner.resolve_type(typ))


def _same_type_identity(left, right):
    """Compare nested array identities without recursive tuple comparison."""
    pending = [(left, right)]
    while pending:
        charge("helper_item")
        left, right = pending.pop()
        if left is right:
            continue
        if isinstance(left, tuple) and isinstance(right, tuple):
            if len(left) != len(right):
                return False
            pending.extend(reversed(list(zip(left, right))))
        elif left != right:
            return False
    return True


class Interpreter:
    def __init__(self, stdin=None, stdout=None, stderr=None, *, allow_native=False, _native_context=None):
        self.stdin, self.stdout = stdin or sys.stdin, stdout or sys.stdout
        self.stderr = sys.stderr if stderr is None else stderr
        self.global_scope, self.functions, self.depth = Scope(), {}, 0
        self.structure_depth = 0
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
        install_native(self, _native_context, allow_native)
        if sys.getrecursionlimit() < 20000:
            sys.setrecursionlimit(20000)

    def fail(self, node, message):
        error = at_token(RuError(message, node.token.line, node.token.col, "运行错误"), node.token)
        if self.source_path and not getattr(error, "source_name", None):
            error.source_name = str(self.source_path)
            error.source_text = getattr(self.modules, "sources", {}).get(str(self.source_path), "")
        raise error

    def execute(self, program, echo=False, source_path=None, modules=None, module_cache=None):
        return _drive(self._execute_step(program, echo, source_path, modules, module_cache))

    def _execute_step(self, program, echo=False, source_path=None, modules=None, module_cache=None):
        validate(program, self.functions, self.types)
        if modules is None:
            from .modules import import_nodes, load_module_graph
            if any(import_nodes(program)) or (source_path is not None and any(n.kind == "module_decl" for n in budget_items(program))):
                modules = load_module_graph(source_path or self.source_path or str(Path.cwd() / "<REPL>"), program)
        check_native_imports(self, program, modules)
        if source_path is not None:
            self.source_path = str(Path(source_path).resolve())
        if modules is not None:
            self.modules = modules
        if module_cache is not None:
            self.module_cache = module_cache
        for n in program:
            charge("helper_item")
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
            (yield self._block_step(program, self.global_scope, echo))
        except RuError as error:
            guard_budget()
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
        return _drive(self._resolve_type_step(typ))

    def _resolve_type_step(self, typ):
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
                (yield _type_resolution(parent))
                typ.parent = parent
                typ.fields, typ.methods = dict(parent.fields), dict(parent.methods)
            else:
                typ.fields, typ.methods = {}, {}
            for name, field_type in typ.node.data["fields"]:
                charge("helper_item")
                if name in typ.fields or name in typ.methods:
                    typ.owner.fail(typ.node, f"继承字段／方法重名：{name}")
                typ.owner.type_identity(field_type, typ.node)
                typ.fields[name] = (field_type, typ.owner)
            for fn in typ.node.data["methods"]:
                charge("helper_item")
                name = fn.data["name"]
                if name in typ.fields:
                    typ.owner.fail(fn, f"方法与字段重名：{name}")
                signature = [(key, typ.owner.type_identity(annotation, fn)) for key, annotation in budget_items(fn.data["params"])]
                if name in typ.methods:
                    previous = typ.methods[name]
                    old = previous.node.data
                    old_signature = list(previous.parameter_types.items()) if previous.parameter_types is not None else [(key, previous.owner.type_identity(annotation, fn)) for key, annotation in budget_items(old["params"])]
                    if (len(old_signature) != len(signature)
                            or any(old_key != key or not _same_type_identity(old_type, typ)
                                   for (old_key, old_type), (key, typ) in budget_items(zip(old_signature, signature)))
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
        depth = 0
        while annotation.endswith(" 阵"):
            charge("helper_item")
            annotation = annotation[:-2]
            depth += 1
        if annotation in ("", "数", "句", "空", "阵", "对", "算", "作", "事实", "典"):
            result = annotation
        else:
            result = self.types.get(annotation) or self.builtin_types.get(annotation)
            if not isinstance(result, RuType):
                self.fail(n, f"未定义类型：{annotation}；类型注解须使用已声明或已尽取导入的形名")
        for _ in range(depth):
            charge("helper_item")
            result = ("array", result)
        return result

    def type_detail(self, value, annotation, identity=None):
        """Describe only types and the first failing index, never payload values."""
        typ = annotation if identity is None else identity
        path = ""
        while annotation.endswith(" 阵") and isinstance(value, list):
            charge("helper_item")
            item_annotation = annotation[:-2]
            item_type = typ[1] if isinstance(typ, tuple) else item_annotation
            bad = next(((i, item) for i, item in budget_items(enumerate(value))
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
        if not isinstance(typ, tuple) and not (isinstance(typ, str) and typ.endswith(" 阵")):
            return self._scalar_type_matches(value, typ)
        pending = [iter(((value, typ),))]
        while pending:
            try:
                value, typ = next(pending[-1])
            except StopIteration:
                pending.pop()
                continue
            charge("helper_item")
            if isinstance(typ, tuple) or (isinstance(typ, str) and typ.endswith(" 阵")):
                if not isinstance(value, list):
                    return False
                item_type = typ[1] if isinstance(typ, tuple) else typ[:-2]
                pending.append(zip(value, repeat(item_type)))
            elif not self._scalar_type_matches(value, typ):
                return False
        return True

    def _scalar_type_matches(self, value, typ):
        if isinstance(typ, RuType):
            current = value.type if isinstance(value, Instance) else None
            while current is not None:
                charge("helper_item")
                if current is typ:
                    return True
                current = current.parent
            return False
        if typ == "":
            return True
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
            charge("helper_item")
            if current is expected:
                return True
            current = current.parent
        return False

    def block(self, statements, scope, echo=False):
        return _drive(self._block_step(statements, scope, echo))

    def _block_step(self, statements, scope, echo=False):
        if statements and self.structure_depth >= STRUCTURE_DEPTH_LIMIT:
            self.fail(statements[0], f"表达式或语句结构超过 {STRUCTURE_DEPTH_LIMIT} 层，请拆分为较小的步骤")
        self.structure_depth += 1
        try:
            for n in statements:
                charge("stmt")
                d = n.data
                if n.kind in ("function", "module_decl"):
                    continue
                if n.kind == "type":
                    (yield self._resolve_type_step(self.types[d["name"]]))
                elif n.kind == "scope":
                    local = Scope(scope, "block")
                    self.hoist(d["body"], local)
                    # A lexical block is not a call boundary: enclosing control
                    # flow and REPL echo pass through unchanged.
                    (yield self._block_step(d["body"], local, echo))
                elif n.kind == "bind":
                    if scope.protected(d["name"]) or d["name"] in self.types or d["name"] in BUILTIN_NAMES:
                        self.fail(n, "变量名不能与函数名、形名或内置名称重名")
                    scope.bind(d["name"], (yield self._expr_step(d["expr"], scope)))
                elif n.kind == "assign":
                    (yield self._assign_step(n, scope))
                elif n.kind == "import_all":
                    module = (yield self._expr_step(d["expr"], scope))
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
                    value = (yield self._expr_step(d["expr"], scope))
                    try:
                        _write_stream(self.stdout, display(value) + "\n")
                    except (OSError, ValueError) as error:
                        self.fail(n, "输出失败：" + str(error))
                elif n.kind == "expr":
                    value = (yield self._expr_step(d["expr"], scope))
                    if echo and not self.is_procedure(d["expr"], scope):
                        try:
                            _write_stream(self.stdout, display(value) + "\n")
                        except (OSError, ValueError) as error:
                            self.fail(n, "输出失败：" + str(error))
                elif n.kind == "panic":
                    reason = (yield self._expr_step(d["expr"], scope))
                    if not isinstance(reason, str):
                        self.fail(n, "「卒」的原因须为句")
                    error = Panic(reason, n.token)
                    self.locate_error(error)
                    raise error
                elif n.kind == "try":
                    try:
                        (yield self._block_step(d["body"], scope))
                    except Panic as error:
                        if scope.protected(d["reason"]) or d["reason"] in self.types or d["reason"] in BUILTIN_NAMES:
                            self.fail(n, "救的原因名称不能与函数名、形名或内置名称重名")
                        handler = Scope(scope, "rescue")
                        handler.values[d["reason"]] = error.reason
                        self.hoist(d["rescue"], handler)
                        # Outside the protected suite: a new 卒 here propagates
                        # to an enclosing dynamically active 试.
                        (yield self._block_step(d["rescue"], handler))
                elif n.kind == "return":
                    raise Return((yield self._expr_step(d["expr"], scope)))
                elif n.kind == "finish":
                    raise Finish()
                elif n.kind == "continue":
                    raise Continue()
                elif n.kind == "break":
                    raise Break()
                elif n.kind == "if":
                    (yield self._block_step(d["yes"] if truth((yield self._expr_step(d["condition"], scope))) else d["no"], scope))
                elif n.kind == "loop":
                    count = None
                    if d["count"] is not None:
                        value = (yield self._expr_step(d["count"], scope))
                        if not isinstance(value, float) or not math.isfinite(value) or value < 0 or value > 9007199254740991 or value != int(value):
                            self.fail(n, "循环次数须为 0 至 9007199254740991 之间的整数")
                        count = int(value)
                    i = 0
                    while True:
                        charge("loop")
                        if count is not None and i >= count:
                            break
                        try:
                            (yield self._block_step(d["body"], scope))
                        except Break:
                            break
                        except Continue:
                            # Counted loops must advance even when the body exits early.
                            pass
                        i += 1
        finally:
            self.structure_depth -= 1

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
            charge("helper_item")
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
        return _drive(self._callable_target_step(n, scope))

    def _callable_target_step(self, n, scope):
        """Evaluate a call/ref target once without auto-invoking its last selector."""
        if n.kind == "name":
            charge("expr")
            if n.data["name"] == "读":
                self.fail(n, "当前仅支持用户定义算／作的引用；内置「读」不能取引用")
            return self.resolve_name(n, scope)[0]
        if n.kind == "member" and not n.data["args"]:
            charge("expr")
            receiver = (yield self._expr_step(n.data["receiver"], scope))
            return self.member_reference(n, receiver, n.data["name"])
        return (yield self._expr_step(n, scope))

    def invoke_value(self, n, value, args):
        return _drive(self._invoke_value_step(n, value, args))

    def _invoke_value_step(self, n, value, args):
        guard_budget()
        if not isinstance(value, Function):
            self.fail(n, "值不是算／作" + ("；若要索引，请让方括号紧邻接收者，如 列[0]；列 [0] 会被解析为调用" if isinstance(value, (list, str, RuMap)) and len(args) == 1 and isinstance(args[0][1], list) else ""))
        return value.owner._invoke_step(n, value.node, args, value.receiver,
                                       caller=self, environment=value.environment,
                                       parameter_types=value.parameter_types, _result_caller=self)

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
        return _drive(self._get_index_step(n, receiver, index))

    def _get_index_step(self, n, receiver, index):
        if isinstance(receiver, RuMap):
            return self._map_member_step(n, receiver, "查", [(None, index)])
        if not isinstance(receiver, (list, str)):
            self.fail(n, "「位」／索引只适用于阵或句")
        return _Value(receiver[self.bounded_index(n, index, len(receiver))])

    @checked_operation
    def get_slice(self, n, receiver, start, end):
        if not isinstance(receiver, (list, str)):
            self.fail(n, "「段」／切片只适用于阵或句")
        first = 0 if start is None else self.bounded_index(n, start, len(receiver), True)
        last = len(receiver) if end is None else self.bounded_index(n, end, len(receiver), True)
        if first > last:
            self.fail(n, "切片起点不能大于终点")
        bulk(last - first)
        return receiver[first:last]

    def assign(self, n, scope):
        return _drive(self._assign_step(n, scope))

    def _assign_step(self, n, scope):
        target, d = n.data["target"], n.data["target"].data
        receiver = (yield self._expr_step(d["receiver"], scope))
        if target.kind == "index":
            index = (yield self._expr_step(d["index"], scope))
        elif d["name"] == "位" and isinstance(receiver, list):
            args = (yield self._arguments_step(d["args"], scope))
            bound = bind_arguments("位", args, ["位"], lambda message: self.fail(n, message))
            index = bound["位"]
        else:
            if not isinstance(receiver, Instance) or d["args"] or d["name"] not in receiver.type.fields:
                self.fail(n, f"不可赋值的字段：{d['name']}")
            value = (yield self._expr_step(n.data["expr"], scope))
            field_type, owner = receiver.type.fields[d["name"]]
            if value is not None and not owner.type_matches(value, field_type):
                self.fail(n, f"字段「{d['name']}」须为{field_type}，实际收到{value_type_name(value)}" + owner.type_detail(value, field_type))
            receiver.fields[d["name"]] = value
            return
        if not isinstance(receiver, list):
            self.fail(n, "只有阵元素可赋值；句不可变")
        offset = self.bounded_index(n, index, len(receiver))
        receiver[offset] = (yield self._expr_step(n.data["expr"], scope))

    def import_module(self, n):
        return _drive(self._import_module_step(n))

    def _import_module_step(self, n):
        path = n.data.get("resolved")
        if path is None:
            from .modules import resolve_import
            try:
                path = resolve_import(n.data["path"], self.source_path or str(Path.cwd() / "<REPL>"))
            except RuError as error:
                guard_budget()
                error.line, error.col = n.token.line, n.token.col
                raise
        from .native_runtime import native_import
        if native_import(n.data["path"], path):
            try:
                self._native_context.check()
            except NativeFault as error:
                self.fail(n, str(error))
        if path in self.loading:
            self.fail(n, "外言导入形成循环：" + path)
        if path in self.module_cache:
            cached = self.module_cache[path]
            if isinstance(cached, FailedModule):
                cached.rethrow()
            cached_context = cached.interpreter._native_context
            if cached_context is not self._native_context and (cached_context.capability.allowed or self._native_context.capability.allowed):
                self.fail(n, "不能复用不同原生能力上下文的外言缓存")
            return cached
        if path not in self.modules:
            from .modules import load_module_graph
            self.modules.update(load_module_graph(path))
        child = Interpreter(self.stdin, self.stdout, self.stderr, _native_context=self._native_context)
        child.loading, child.call_state = self.loading, self.call_state
        child.graphics_host = self.graphics_host
        self.loading.add(path)
        try:
            (yield child._execute_step(self.modules[path], source_path=path, modules=self.modules, module_cache=self.module_cache))
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
        return _drive(self._expr_step(n, scope))

    def _arguments_step(self, arguments, scope):
        result, remaining = [], iter(arguments)
        for name, expression in remaining:
            task = self._expr_step(expression, scope)
            if not isinstance(task, _Value):
                return self._arguments_resume(task, name, remaining, result, scope)
            result.append((name, task.value))
        return _Value(result)

    def _arguments_resume(self, task, name, remaining, result, scope):
        result.append((name, (yield task)))
        for name, expression in remaining:
            task = self._expr_step(expression, scope)
            result.append((name, task.value if isinstance(task, _Value) else (yield task)))
        return result

    def _items_step(self, expressions, scope):
        result, remaining = [], iter(expressions)
        for expression in remaining:
            task = self._expr_step(expression, scope)
            if not isinstance(task, _Value):
                return self._items_resume(task, remaining, result, scope)
            result.append(task.value)
        return _Value(result)

    def _items_resume(self, task, remaining, result, scope):
        result.append((yield task))
        for expression in remaining:
            task = self._expr_step(expression, scope)
            result.append(task.value if isinstance(task, _Value) else (yield task))
        return result

    @checked_operation
    def _binary_value(self, n, op, left, right):
        if op in ("<", "<=", ">", ">="):
            if type(left) is not type(right) or not isinstance(left, (str, float)):
                self.fail(n, "大小比较需要两个数或两个句" + ("；比较结果为事实，若要连续比较，请拆成两个比较并用「且」连接" if isinstance(left, bool) or isinstance(right, bool) else ""))
            if isinstance(left, str):
                bulk(len(left) + len(right))
            if op == "<":
                return left < right
            if op == "<=":
                return left <= right
            if op == ">":
                return left > right
            return left >= right
        if op == "+" and isinstance(left, str) and isinstance(right, str):
            bulk(len(left) + len(right))
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

    def _expr_step(self, n, scope):
        guard_budget()
        kind = n.kind
        if kind == "name" and current_budget() is not None:
            return self._expr_frame(n, scope)
        if kind not in ("number", "string", "fact", "null", "self", "name"):
            return self._expr_frame(n, scope)
        if self.structure_depth >= STRUCTURE_DEPTH_LIMIT:
            self.fail(n, f"表达式或语句结构超过 {STRUCTURE_DEPTH_LIMIT} 层，请拆分为较小的步骤")
        # A declared bare function name auto-invokes; it is not a leaf.
        found = None
        if kind == "name":
            if n.data["name"] == "读":
                return self._expr_frame(n, scope)
            found, declared = scope.find(n.data["name"])
            if declared:
                return self._expr_frame(n, scope)
        charge("expr")
        self.structure_depth += 1
        try:
            if kind in ("number", "string", "fact"):
                result = n.data["value"]
            elif kind == "null":
                result = None
            elif kind == "self":
                result = scope.get("其", n.token)
            else:
                if found is _MISSING:
                    if n.data["name"] in self.types:
                        found = self.types[n.data["name"]]
                    else:
                        self.fail(n, "未定义名称：" + n.data["name"])
                result = self.ordinary_value(n, found)
            return _Value(result)
        finally:
            self.structure_depth -= 1

    def _expr_frame(self, n, scope):
        """One generator per expression tree, with explicit AST/value stacks.

        AST edges never allocate another generator. Only a real Ru call or
        runtime operation that can call Ru yields to the outer task scheduler.
        entered counts logical expressions still live across those yields.
        """
        actions, values, entered = [("eval", n)], [], 0
        try:
            while actions:
                action = actions.pop()
                operation = action[0]
                if operation == "eval":
                    node = action[1]
                    if self.structure_depth >= STRUCTURE_DEPTH_LIMIT:
                        self.fail(node, f"表达式或语句结构超过 {STRUCTURE_DEPTH_LIMIT} 层，请拆分为较小的步骤")
                    charge("expr")
                    self.structure_depth += 1
                    entered += 1
                    d, kind = node.data, node.kind
                    if kind in ("number", "string", "fact"):
                        result = d["value"]
                    elif kind == "null":
                        result = None
                    elif kind == "self":
                        result = scope.get("其", node.token)
                    elif kind == "name":
                        if d["name"] == "读":
                            result = yield self._call_step(node, "读", [])
                        else:
                            result, declared = self.resolve_name(node, scope)
                            if declared:
                                result = yield self._invoke_value_step(node, result, [])
                    elif kind == "binary":
                        actions.append(("binary_left", node, d["op"], d["right"]))
                        actions.append(("eval", d["left"]))
                        continue
                    elif kind in ("unary", "convert"):
                        actions.append((kind, node))
                        actions.append(("eval", d["expr"]))
                        continue
                    elif kind == "index":
                        actions.append(("index_receiver", node))
                        actions.append(("eval", d["receiver"]))
                        continue
                    elif kind == "slice":
                        actions.append(("slice_receiver", node))
                        actions.append(("eval", d["receiver"]))
                        continue
                    elif kind == "member":
                        actions.append(("member_receiver", node))
                        actions.append(("eval", d["receiver"]))
                        continue
                    elif kind == "array":
                        actions.append(("array_next", node, iter(d["items"]), []))
                        continue
                    elif kind == "map":
                        actions.append(("map_next", node, iter(d["entries"]), RuMap()))
                        continue
                    elif kind == "function_literal":
                        result = Function(self, node, scope)
                    elif kind == "function_ref":
                        actions.append(("function_ref", node))
                        actions.append(("target", d["expr"]))
                        continue
                    elif kind == "call":
                        target = None if d["name"] == "读" else self.resolve_name(node, scope)[0]
                        actions.append(("arguments", node, iter(d["args"]), [], "read" if d["name"] == "读" else "invoke", target))
                        continue
                    elif kind == "invoke":
                        if d["callee"].kind == "name" and d["callee"].data["name"] == "读":
                            actions.append(("arguments", node, iter(d["args"]), [], "read", None))
                        else:
                            actions.append(("invoke_target", node))
                            actions.append(("target", d["callee"]))
                        continue
                    elif kind == "import":
                        result = yield self._import_module_step(node)
                    elif kind == "new":
                        typ = self.types.get(d["name"]) or self.builtin_types.get(d["name"])
                        if typ is None:
                            self.fail(node, f"未定义形：{d['name']}；新 后须使用已声明或已尽取导入的形名")
                        if not isinstance(typ, RuType):
                            self.fail(node, f"「{d['name']}」不是形")
                        task = _type_resolution(typ)
                        if not isinstance(task, _Value):
                            yield task
                        fields = io_new_defaults(typ)
                        if fields is None:
                            bulk(len(typ.fields))
                            fields = {name: None for name in typ.fields}
                        actions.append(("new_next", node, typ, fields, set(), iter(d["args"])))
                        continue
                    else:
                        raise AssertionError(kind)
                elif operation == "binary_left":
                    _, node, op, right = action
                    left = values.pop()
                    if op == "且" and not truth(left):
                        result = False
                    elif op == "或" and truth(left):
                        result = True
                    else:
                        actions.append(("binary_done", node, op, left))
                        actions.append(("eval", right))
                        continue
                elif operation == "binary_done":
                    _, node, op, left = action
                    right = values.pop()
                    if op in ("且", "或"):
                        result = truth(right)
                    elif op == "对":
                        result = Pair(left, right)
                    elif op in ("==", "!="):
                        task = self._equals_step(node, left, right)
                        same = task.value if isinstance(task, _Value) else (yield task)
                        result = same if op == "==" else not same
                    elif op == "含":
                        if isinstance(left, (Instance, Module)):
                            result = yield self._member_step(node, left, "含", [(None, right)])
                        else:
                            self.last_member_procedure = False
                            if not isinstance(left, str) or not isinstance(right, str):
                                self.fail(node, "「含」需要两个句")
                            bulk(len(left) + len(right))
                            result = right in left
                            check_budget()
                    else:
                        result = self._binary_value(node, op, left, right)
                elif operation == "unary":
                    node, value = action[1], values.pop()
                    if node.data["op"] == "非":
                        result = not truth(value)
                    else:
                        if not isinstance(value, float):
                            self.fail(node, "正负号只能用于数")
                        result = value if node.data["op"] == "+" else -value
                elif operation == "convert":
                    node, value = action[1], values.pop()
                    target = node.data["target"]
                    if target == "事实":
                        result = truth(value)
                    elif target == "阵":
                        result = [value]
                    elif target == "句":
                        result = display(value)
                    else:
                        result = self.number_value(node, value)
                elif operation == "index_receiver":
                    node, receiver = action[1], values.pop()
                    actions.append(("index_done", node, receiver))
                    actions.append(("eval", node.data["index"]))
                    continue
                elif operation == "index_done":
                    _, node, receiver = action
                    task = self._get_index_step(node, receiver, values.pop())
                    result = task.value if isinstance(task, _Value) else (yield task)
                elif operation == "slice_receiver":
                    node, receiver = action[1], values.pop()
                    if node.data["start"] is None:
                        values.append(None)
                    else:
                        actions.append(("slice_start", node, receiver))
                        actions.append(("eval", node.data["start"]))
                        continue
                    actions.append(("slice_start", node, receiver))
                    continue
                elif operation == "slice_start":
                    _, node, receiver = action
                    start = values.pop()
                    actions.append(("slice_done", node, receiver, start))
                    if node.data["end"] is None:
                        values.append(None)
                    else:
                        actions.append(("eval", node.data["end"]))
                    continue
                elif operation == "slice_done":
                    _, node, receiver, start = action
                    result = self.get_slice(node, receiver, start, values.pop())
                elif operation == "array_next":
                    _, node, remaining, items = action
                    try:
                        expression = next(remaining)
                    except StopIteration:
                        result = items
                    else:
                        actions.append(("array_item", node, remaining, items))
                        actions.append(("eval", expression))
                        continue
                elif operation == "array_item":
                    _, node, remaining, items = action
                    items.append(values.pop())
                    actions.append(("array_next", node, remaining, items))
                    continue
                elif operation == "map_next":
                    _, node, remaining, mapping = action
                    try:
                        key_node, value_node = next(remaining)
                    except StopIteration:
                        result = mapping
                    else:
                        actions.append(("map_key", node, remaining, mapping, value_node))
                        actions.append(("eval", key_node))
                        continue
                elif operation == "map_key":
                    _, node, remaining, mapping, value_node = action
                    actions.append(("map_value", node, remaining, mapping, values.pop()))
                    actions.append(("eval", value_node))
                    continue
                elif operation == "map_value":
                    _, node, remaining, mapping, key = action
                    yield self._map_put_step(node, mapping, key, values.pop())
                    actions.append(("map_next", node, remaining, mapping))
                    continue
                elif operation == "target":
                    node = action[1]
                    if node.kind == "name":
                        charge("expr")
                        if node.data["name"] == "读":
                            self.fail(node, "当前仅支持用户定义算／作的引用；内置「读」不能取引用")
                        values.append(self.resolve_name(node, scope)[0])
                    elif node.kind == "member" and not node.data["args"]:
                        charge("expr")
                        actions.append(("target_member", node))
                        actions.append(("eval", node.data["receiver"]))
                    else:
                        actions.append(("eval", node))
                    continue
                elif operation == "target_member":
                    node = action[1]
                    values.append(self.member_reference(node, values.pop(), node.data["name"]))
                    continue
                elif operation == "function_ref":
                    node, result = action[1], values.pop()
                    if not isinstance(result, Function) or result.node.data["procedure"] != node.data["procedure"]:
                        self.fail(node, "引用的算／作种类不匹配")
                elif operation == "invoke_target":
                    node, target = action[1], values.pop()
                    actions.append(("arguments", node, iter(node.data["args"]), [], "invoke", target))
                    continue
                elif operation == "member_receiver":
                    node, receiver = action[1], values.pop()
                    d, target = node.data, _MISSING
                    if isinstance(receiver, Instance):
                        if d["name"] in receiver.type.fields and d["args"]:
                            target = receiver.fields[d["name"]]
                        elif d["name"] in receiver.type.methods:
                            target = self.member_reference(node, receiver, d["name"])
                    elif isinstance(receiver, Module):
                        value = self.ordinary_value(node, receiver.exports().get(d["name"], _MISSING))
                        if value is not _MISSING and (d["args"] or d["name"] in receiver.interpreter.functions):
                            target = value
                    mode = "member" if target is _MISSING else "member_invoke"
                    actions.append(("arguments", node, iter(d["args"]), [], mode, receiver if target is _MISSING else target))
                    continue
                elif operation == "arguments":
                    _, node, remaining, arguments, mode, target = action
                    try:
                        name, expression = next(remaining)
                    except StopIteration:
                        if mode == "read":
                            result = yield self._call_step(node, "读", arguments)
                        elif mode == "member":
                            result = yield self._member_step(node, target, node.data["name"], arguments)
                        else:
                            result = yield self._invoke_value_step(node, target, arguments)
                            if mode == "member_invoke":
                                self.last_member_procedure = target.node.data["procedure"]
                    else:
                        actions.append(("argument_value", node, remaining, arguments, mode, target, name))
                        actions.append(("eval", expression))
                        continue
                elif operation == "argument_value":
                    _, node, remaining, arguments, mode, target, name = action
                    arguments.append((name, values.pop()))
                    actions.append(("arguments", node, remaining, arguments, mode, target))
                    continue
                elif operation == "new_next":
                    _, node, typ, fields, provided, remaining = action
                    try:
                        key, expression = next(remaining)
                    except StopIteration:
                        result = Instance(typ, fields)
                    else:
                        if key in provided:
                            self.fail(node, f"重复的字段实参：{key}")
                        if key not in fields:
                            self.fail(node, f"未知字段：{key}")
                        actions.append(("new_value", node, typ, fields, provided, remaining, key))
                        actions.append(("eval", expression))
                        continue
                elif operation == "new_value":
                    _, node, typ, fields, provided, remaining, key = action
                    value = values.pop()
                    field_type, owner = typ.fields[key]
                    if value is not None and not owner.type_matches(value, field_type):
                        self.fail(node, f"字段「{key}」须为{field_type}，实际收到{value_type_name(value)}" + owner.type_detail(value, field_type))
                    fields[key] = value
                    provided.add(key)
                    actions.append(("new_next", node, typ, fields, provided, remaining))
                    continue
                else:
                    raise AssertionError(operation)
                values.append(result)
                self.structure_depth -= 1
                entered -= 1
            assert len(values) == 1 and entered == 0
            return values.pop()
        finally:
            self.structure_depth -= entered

    def special_method(self, n, value, name, arity):
        method = value.type.methods.get(name)
        if method is None or method.node.data["procedure"] or len(method.node.data["params"]) != arity:
            self.fail(n, f"形的「{name}」须为接受 {arity} 个参数的算")
        return Function(method.owner, method.node, method.environment, value, method.parameter_types)

    def equals(self, n, left, right):
        return _drive(self._equals_step(n, left, right))

    def _equals_step(self, n, left, right):
        if not isinstance(left, (Instance, Pair)):
            return _Value(equal(left, right))
        return self._equals_frame(n, left, right)

    def _equals_frame(self, n, left, right):
        # Keep the ordinary Pair cycle/identity rules, but suspend special 同
        # calls rather than entering a synchronous Python callback from equal.
        pending, compared = [(left, right)], set()
        while pending:
            charge("helper_item")
            left, right = pending.pop()
            if type(left) is not type(right):
                return False
            if isinstance(left, str):
                bulk(len(left) + len(right))
            if isinstance(left, Instance):
                if left.type is not right.type:
                    return False
                if "同" not in left.type.methods:
                    if left is not right:
                        return False
                    continue
                method = self.special_method(n, left, "同", 1)
                result = (yield self._invoke_value_step(n, method, [(None, right)]))
                if not isinstance(result, bool):
                    self.fail(n, "「同」须返回事实")
                if not result:
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
            elif isinstance(left, (list, RuMap, Module, RuType, Function)):
                return False
            else:
                different = left != right
                check_budget()
                if different:
                    return False
        return True

    def map_hash(self, n, key):
        return _drive(self._map_hash_step(n, key))

    def _map_hash_step(self, n, key):
        if isinstance(key, Instance):
            return self._map_hash_frame(n, key)
        if isinstance(key, bool):
            return _Value(("事实", key))
        if isinstance(key, float):
            if not math.isfinite(key):
                self.fail(n, "典的数键须为有限数")
            return _Value(("数", key))
        if isinstance(key, str):
            bulk(len(key))
            return _Value(("句", key))
        self.fail(n, "典的键须为数、句、事实或提供同与印的形实例；实际收到" + value_type_name(key))

    def _map_hash_frame(self, n, key):
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
            value = (yield self._invoke_value_step(n, method, []))
            if not isinstance(value, float) or not math.isfinite(value) or value != math.trunc(value) or abs(value) > 9007199254740991:
                self.fail(n, "「印」须返回安全整数范围内的数")
            return ("形", id(key.type), value)
        self.fail(n, "典的键须为数、句、事实或提供同与印的形实例；实际收到" + value_type_name(key))

    def map_find(self, n, receiver, key):
        return _drive(self._map_find_step(n, receiver, key))

    def _map_find_step(self, n, receiver, key):
        version = receiver.version
        hashed = (yield self._map_hash_step(n, key))
        if receiver.version != version:
            self.fail(n, "典在键的印／同比较期间被修改")
        bucket = receiver.buckets.get(hashed, [])
        for index, (stored, _) in enumerate(bucket):
            charge("helper_item")
            same = (yield self._equals_step(n, stored, key))
            if receiver.version != version:
                self.fail(n, "典在键的印／同比较期间被修改")
            if same:
                return hashed, bucket, index
        return hashed, bucket, -1

    def map_put(self, n, receiver, key, value):
        return _drive(self._map_put_step(n, receiver, key, value))

    def _map_put_step(self, n, receiver, key, value):
        hashed, bucket, index = (yield self._map_find_step(n, receiver, key))
        if index < 0:
            receiver.buckets.setdefault(hashed, bucket).append((key, value))
            receiver.size += 1
        else:
            bucket[index] = (bucket[index][0], value)
        receiver.version += 1
        return receiver

    def map_member(self, n, receiver, name, args):
        return _drive(self._map_member_step(n, receiver, name, args))

    def _map_member_step(self, n, receiver, name, args):
        charge("call")
        params = {"查": ["目"], "增": ["目", "相"], "除": ["目"], "逐目": ["回调"], "量": []}
        if name == "列":
            self.fail(n, "典的「列」已改名为「逐目」；请改用「其 逐目」")
        if name not in params:
            self.fail(n, f"未知成员：{name}")
        bound = bind_arguments(name, args, params[name], lambda message: self.fail(n, message))
        if name == "量":
            return float(receiver.size)
        if name == "增":
            return (yield self._map_put_step(n, receiver, bound["目"], bound["相"]))
        if name == "逐目":
            callback = bound["回调"]
            if not isinstance(callback, Function) or len(callback.node.data["params"]) != 2:
                self.fail(n, "典的逐目回调须为接受两个参数的算或作")
            for key, value in receiver.snapshot():
                charge("helper_item")
                (yield self._invoke_value_step(n, callback, [(None, key), (None, value)]))
            self.last_member_procedure = False
            return None
        hashed, bucket, index = (yield self._map_find_step(n, receiver, bound["目"]))
        if name == "查":
            return None if index < 0 else bucket[index][1]
        if index < 0:
            return False
        bulk(len(bucket) - index - 1)
        del bucket[index]
        if not bucket:
            del receiver.buckets[hashed]
        receiver.size -= 1
        receiver.version += 1
        return True

    @checked_operation
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

    def array_algorithm(self, n, value, name, arity):
        if (not isinstance(value, Function) or value.node.data["procedure"]
                or len(value.node.data["params"]) != arity):
            self.fail(n, f"「{name}」须为接受 {arity} 个参数的算")
        return value

    def array_transform(self, n, receiver, name, args):
        return _drive(self._array_transform_step(n, receiver, name, args))

    def _array_transform_step(self, n, receiver, name, args):
        fail = lambda message: self.fail(n, message)
        parameter = "算法" if name == "另成" else "先于"
        bound = bind_arguments(name, args, [parameter], fail, optional=name == "排序")
        # Snapshot the outer array only; contained mutable values retain identity.
        bulk(len(receiver))
        snapshot = list(receiver)
        if name == "另成":
            algorithm = self.array_algorithm(n, bound[parameter], parameter, 1)
            result = []
            for value in snapshot:
                charge("helper_item")
                result.append((yield self._invoke_value_step(n, algorithm, [(None, value)])))
            self.last_member_procedure = False
            return result

        comparator = None
        if parameter in bound:
            comparator = self.array_algorithm(n, bound[parameter], parameter, 2)
        elif snapshot:
            first = snapshot[0]
            if isinstance(first, float):
                valid = all(isinstance(value, float) and math.isfinite(value) for value in budget_items(snapshot))
            elif isinstance(first, str):
                valid = all(isinstance(value, str) for value in budget_items(snapshot))
            elif isinstance(first, Instance):
                valid = all(isinstance(value, Instance) and value.type is first.type for value in budget_items(snapshot))
                if valid:
                    self.special_method(n, first, "先于", 1)
            else:
                valid = False
            if not valid:
                self.fail(n, "默认排序须为同类有限数、句或同一形且具有「先于」算的实例")

        def before(left, right):
            if comparator is not None:
                value = (yield self._invoke_value_step(n, comparator, [(None, left), (None, right)]))
            elif isinstance(left, Instance):
                value = (yield self._invoke_value_step(n, self.special_method(n, left, "先于", 1), [(None, right)]))
            else:
                if isinstance(left, str):
                    bulk(len(left) + len(right))
                result = left < right
                check_budget()
                return result
            if not isinstance(value, bool):
                self.fail(n, "「先于」须返回事实")
            return value

        # Bottom-up stable merge: ties keep their original order without 同.
        width = 1
        while width < len(snapshot):
            merged = []
            for start in range(0, len(snapshot), width * 2):
                middle = min(start + width, len(snapshot))
                end = min(start + width * 2, len(snapshot))
                left, right = start, middle
                while left < middle and right < end:
                    charge("helper_item")
                    if (yield before(snapshot[right], snapshot[left])):
                        merged.append(snapshot[right])
                        right += 1
                    else:
                        merged.append(snapshot[left])
                        left += 1
                bulk(middle - left)
                merged.extend(snapshot[left:middle])
                bulk(end - right)
                merged.extend(snapshot[right:end])
            snapshot = merged
            width *= 2
        self.last_member_procedure = False
        return snapshot

    def member(self, n, receiver, name, args):
        return _drive(self._member_step(n, receiver, name, args))

    def _member_step(self, n, receiver, name, args):
        fail = lambda message: self.fail(n, message)
        self.last_member_procedure = False
        if isinstance(receiver, RuMap):
            return (yield self._map_member_step(n, receiver, name, args))
        # Keep ordinary/graphics member dispatch out of the traced native
        # function. Native receivers still pass every context/lifetime guard.
        if getattr(receiver, 'native_payload', None) is not None:
            handled, result = native_member(self, n, receiver, name, args)
            if handled:
                return result
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
                charge("call")
                bind_arguments(name, args, [], fail)
                return receiver.fields[name]
            method = receiver.type.methods.get(name)
            if method:
                result = (yield method.owner._invoke_step(n, method.node, args, receiver, caller=self, parameter_types=method.parameter_types))
                self.last_member_procedure = method.node.data["procedure"]
                return result
        elif isinstance(receiver, Module):
            value = self.ordinary_value(n, receiver.exports().get(name, _MISSING))
            if value is not _MISSING:
                if isinstance(value, Function) and (args or name in receiver.interpreter.functions):
                    result = (yield self._invoke_value_step(n, value, args))
                    self.last_member_procedure = value.node.data["procedure"]
                    return result
                charge("call")
                bind_arguments(name, args, [], fail)
                return value
        elif isinstance(receiver, Pair) and name in ("囫", "囵"):
            charge("call")
            bind_arguments(name, args, [], fail)
            return receiver.left if name == "囫" else receiver.right
        elif isinstance(receiver, (str, list)):
            charge("call")
            if name == "量":
                bind_arguments(name, args, [], fail)
                return float(len(receiver))
            if name == "位":
                bound = bind_arguments(name, args, ["位"], fail)
                return (yield self._get_index_step(n, receiver, bound["位"]))
            if name == "段":
                bound = bind_arguments(name, args, ["始", "终"], fail)
                return self.get_slice(n, receiver, bound["始"], bound["终"])
            if name == "含" and isinstance(receiver, str):
                bound = bind_arguments(name, args, ["句"], fail)
                if not isinstance(bound["句"], str):
                    self.fail(n, "「含」需要两个句")
                bulk(len(receiver) + len(bound["句"]))
                result = bound["句"] in receiver
                check_budget()
                return result
            if isinstance(receiver, list) and name == "逐位":
                bound = bind_arguments(name, args, ["回调"], fail)
                callback = bound["回调"]
                if not isinstance(callback, Function) or len(callback.node.data["params"]) != 2:
                    self.fail(n, "阵的逐位回调须为接受两个参数的算或作")
                bulk(len(receiver))
                for index, value in enumerate(receiver[:]):
                    charge("helper_item")
                    (yield self._invoke_value_step(n, callback, [(None, float(index)), (None, value)]))
                self.last_member_procedure = False
                return None
            if isinstance(receiver, list) and name in ("排序", "另成"):
                return (yield self._array_transform_step(n, receiver, name, args))
            if isinstance(receiver, list) and name in ("删", "弹", "查"):
                parameters = {"删": ["位"], "弹": [], "查": ["值"]}[name]
                bound = bind_arguments(name, args, parameters, fail)
                if name == "查":
                    bulk(len(receiver))
                    for index, value in enumerate(receiver[:]):
                        charge("helper_item")
                        if (yield self._equals_step(n, value, bound["值"])):
                            self.last_member_procedure = False
                            return float(index)
                    self.last_member_procedure = False
                    return None
                position = bound["位"] if name == "删" else float(len(receiver) - 1)
                (yield self._get_index_step(n, receiver, position))
                bulk(len(receiver) - int(position) - 1)
                return receiver.pop(int(position))
            if name == "增" and isinstance(receiver, list):
                bound = bind_arguments(name, args, ["值"], fail)
                receiver.append(bound["值"])
                return receiver
        self.fail(n, f"未知成员：{name}")

    def call(self, n, name, args):
        return _drive(self._call_step(n, name, args))

    def _call_step(self, n, name, args):
        fail = lambda message: self.fail(n, message)
        if name == "读":
            charge("call")
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
        return (yield self._invoke_value_step(n, self.function_values[name], args))

    def invoke(self, n, function, args, receiver=None, caller=None, environment=None, parameter_types=None):
        return _drive(self._invoke_step(n, function, args, receiver, caller, environment, parameter_types))

    def _invoke_step(self, n, function, args, receiver=None, caller=None, environment=None, parameter_types=None, _result_caller=None):
        guard_budget()
        charge("call")
        caller = self if caller is None else caller
        if caller._native_context is not self._native_context and (caller._native_context.capability.allowed or self._native_context.capability.allowed):
            caller.fail(n, '函数不能跨原生能力上下文调用')
        name, params = function.data["name"], function.data["params"]
        # Imports execute lazily. Validate against the function owner's names
        # at invocation, without rejecting calls before an import has run or
        # treating ordinary imported bindings/type aliases as declarations.
        environment = self.global_scope if environment is None else environment
        if any(environment.protected(key) or key in self.types for key, _ in budget_items(params)):
            self.fail(function, "参数名不能与函数名、形名或内置名称重名")
        kwargs = bind_arguments(name, args, [p[0] for p in budget_items(params)], lambda message: caller.fail(n, message))
        local = Scope(environment, "function")
        if receiver is not None:
            local.values["其"] = receiver
        for key, typ in params:
            charge("helper_item")
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
                (yield self._block_step(function.data["body"], local))
            except Return as result:
                value = result.value
            except Finish:
                value = None
            else:
                if not function.data["procedure"]:
                    caller.fail(n, f"函数「{name}」没有执行「得」")
                value = None
        except RuError as error:
            guard_budget()
            at_token(error, function.token)
            self.locate_error(error)
            raise
        finally:
            self.call_state[0] -= 1
            self.depth -= 1
        # invoke_value's success flag is set only after this owner's call frame
        # has left, exactly as at the original synchronous return boundary.
        if _result_caller is not None:
            _result_caller.last_call_procedure = function.data["procedure"]
        return value


_MISSING = object()
