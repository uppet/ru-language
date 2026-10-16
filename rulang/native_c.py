"""Finite, ahead-of-time native ABI plans for standalone Windows x64 C.

This module only inspects the parsed module graph.  It never evaluates Ru code,
loads a DLL, imports ctypes, or synthesizes executable memory.  Native calls and
callbacks are ordinary, exactly typed C functions generated for declared shapes.
Unknown signature components are a compilation error, not a runtime ABI guess.
"""
from dataclasses import dataclass
from itertools import product
from pathlib import Path

from .frontend import Node, RuError, bind_arguments


# These IDs are the ABI between generated code and native_runtime.h.
PRIMITIVE_IDS = {name: i for i, name in enumerate((
    '无值', 'i8', 'u8', 'i16', 'u16', 'i32', 'u32', 'i64', 'u64',
    'intptr', 'uintptr', 'f32', 'f64', '指针'))}
C_TYPES = {
    '无值': 'void', 'i8': 'int8_t', 'u8': 'uint8_t',
    'i16': 'int16_t', 'u16': 'uint16_t', 'i32': 'int32_t',
    'u32': 'uint32_t', 'i64': 'int64_t', 'u64': 'uint64_t',
    'intptr': 'intptr_t', 'uintptr': 'uintptr_t', 'f32': 'float',
    'f64': 'double', '指针': 'void *',
}
RAW_FIELDS = {name: ('p' if name == '指针' else name if name in ('f32', 'f64')
                    else 'u' if name.startswith('u') else 'i')
              for name in C_TYPES if name != '无值'}
MAX_CALLBACKS = 1024
MAX_SIGNATURES = 1024
MAX_STATIC_ALTERNATIVES = 128


@dataclass(frozen=True)
class NativeCSignature:
    """A primitive C shape. win64 and cdecl have the same x64 ABI."""
    result: str
    params: tuple


@dataclass(frozen=True)
class _Type:
    name: str


@dataclass(frozen=True)
class _Operation:
    name: str
    receiver: object = None


@dataclass(frozen=True)
class _Choice:
    values: tuple


class _Unknown:
    pass


UNKNOWN = _Unknown()
NATIVE = object()
LIBRARY = object()


class _Array:
    def __init__(self, items):
        self.items = tuple(items)


class _Opaque:
    """Reachable values in an object whose member semantics are not modeled."""
    def __init__(self, values):
        self.values = tuple(values)


class _Env:
    def __init__(self, parent=None, kind="module"):
        self.values = {}
        self.parent = parent
        self.kind = kind

    def get(self, name):
        if name in self.values:
            return self.values[name]
        if self.parent is not None:
            return self.parent.get(name)
        return NATIVE if name == '__密' else UNKNOWN

    def bind(self, name, value):
        # Match env_bind: a function updates captured local cells, while a
        # block/rescue shadows and module bindings are never rebound by a
        # function. Join old/new possibilities conservatively; source-order
        # overwrites alone are insufficient for loops and reentrant closures.
        target = self
        if name not in self.values and self.kind == 'function':
            outer = self.parent
            while outer is not None and outer.kind != 'module':
                if name in outer.values:
                    target = outer
                    break
                outer = outer.parent
        target.values[name] = (_merge(target.values[name], value)
                               if name in target.values else value)


class _Function:
    def __init__(self, node, env, path, declared=True):
        self.node, self.env, self.path = node, env, path
        self.declared = declared


class _Module:
    def __init__(self, env):
        self.env = env


def _alternatives(value):
    return value.values if isinstance(value, _Choice) else (value,)


def _same(left, right):
    if isinstance(left, _Function) and isinstance(right, _Function):
        return (left.node is right.node and left.env is right.env and
                left.declared == right.declared)
    return left is right or left == right


def _merge(*values):
    result = []
    for value in values:
        for alternative in _alternatives(value):
            if not any(_same(alternative, item) for item in result):
                result.append(alternative)
            if len(result) > MAX_STATIC_ALTERNATIVES:
                raise RuError('原生签名静态分析的候选值超过 128 上限；请简化描述符数据流', category='原生编译错误')
    if not result:
        return UNKNOWN
    return result[0] if len(result) == 1 else _Choice(tuple(result))


class NativeCPlan:
    """Analyze a resolved ``{source_path: [Node, ...]}`` module graph.

    Supported static dataflow includes primitive/module/function aliases,
    import-all, named arguments, local declarations, closure captures and finite
    conditional alternatives. Descriptor cells use conservative monotone joins;
    loops iterate to a bounded fixed point and unsupported mutable/callable
    escapes are rejected when they prevent ABI resolution. Functions are analyzed
    with their static actuals. Recursion is accepted only for a proven pure
    scalar self-recursive subset; other recursive paths are rejected;
    otherwise their bodies are checked with unknown inputs. Runtime-produced
    types, parameter arrays and conventions are deliberately rejected.

    ``emit_c()`` goes after native_runtime.h.  The runtime owns marshalling,
    callback lifetime/containment and the process-wide 1024 non-reused slots.
    """
    def __init__(self, modules):
        self.modules = dict(modules)
        self.sources = getattr(modules, 'sources', {})
        self.signatures = []
        self.callback_signatures = set()
        self._module_values = {}
        self._loading = set()
        self._functions = []
        self._function_cache = {}
        self._scope_cache = {}
        self._array_cache = {}
        self._opaque_cache = {}
        self._envs = []
        self._called = set()
        self._active = set()
        self._call_sites = []
        self._deferred_functions = {}
        self._signature_inputs = {}
        self._steps = 0
        self._path = next(iter(self.modules), '<源码>')
        self._native_path = str((Path(__file__).parent / 'stdlib' / '密.ru').resolve())
        for path in self.modules:
            self._module(path)
        # Check dormant functions as well. Native standard-library forwarding
        # functions are templates; their real call sites provide the ABI values.
        index = 0
        for _ in range(MAX_STATIC_ALTERNATIVES):
            before = (self._state(), tuple(self.signatures))
            while index < len(self._functions):
                fn = self._functions[index]
                index += 1
                if id(fn.node) not in self._called and fn.path != self._native_path:
                    self._invoke(fn, [(None, UNKNOWN) for _ in fn.node.data['params']], fn.node)
            # A callback or escaped callable may run after registration, when
            # captured descriptor cells have changed. Revisit these summaries
            # after all later joins; never trust registration-time state alone.
            for fn in tuple(self._deferred_functions.values()):
                self._invoke(fn, [(None, UNKNOWN) for _ in fn.node.data['params']], fn.node)
            if before == (self._state(), tuple(self.signatures)) and index == len(self._functions):
                break
        else:
            raise RuError('无法静态确定延迟回调捕获的原生描述符；请使用不变的原生签名', category='原生编译错误')
        # Late-discovered methods/callbacks may invalidate aliases that fed an
        # earlier constructor. The static subset requires those descriptor arrays
        # to remain provable after all effect summaries have settled.
        for params, result, path, origin in self._signature_inputs.values():
            self._path = path
            if params.items is None:
                self._unresolved(origin, '被后续作用影响的原生签名参数阵')
            possibilities = [_alternatives(item) for item in params.items]
            count = 1
            for choices in possibilities:
                count *= len(choices)
            if count > MAX_STATIC_ALTERNATIVES:
                self._unresolved(origin, '被后续作用影响的原生参数类型组合')
            for items in product(*possibilities):
                if any(not isinstance(item, _Type) for item in items):
                    self._unresolved(origin, '被后续作用影响的原生参数类型')
                signature = NativeCSignature(result, tuple(item.name for item in items))
                if signature not in self.signatures:
                    self._unresolved(origin, '被后续作用改变的原生签名')
        self.signatures = tuple(self.signatures)
        self.callback_signatures = frozenset(self.callback_signatures)

    def _error(self, node, message):
        path = self._path
        if path == self._native_path:
            for caller_path, caller_node in reversed(self._call_sites):
                if caller_path != self._native_path:
                    path, node = caller_path, caller_node
                    break
        error = RuError(message, node.token.line, node.token.col, '原生编译错误')
        error.source_name = path
        error.source_text = self.sources.get(path, '')
        raise error

    def _unresolved(self, node, what):
        self._error(node, 'C 原生后端无法静态确定' + what +
                    '；请使用已声明的原生类型、有限参数阵和 win64／cdecl 字面量约定，'
                    '不要在运行时生成原生签名')

    def _module(self, path):
        if path in self._module_values:
            return self._module_values[path]
        if path not in self.modules or path in self._loading:
            return UNKNOWN
        self._loading.add(path)
        env = self._environment()
        module = _Module(env)
        self._module_values[path] = module
        previous = self._path
        self._path = path
        try:
            self._block(self.modules[path], env)
        finally:
            self._path = previous
            self._loading.remove(path)
        return module

    def _environment(self, parent=None, kind='module', site=None):
        key = (site, id(parent), kind)
        if site is not None and key in self._scope_cache:
            return self._scope_cache[key]
        env = _Env(parent, kind)
        self._envs.append(env)
        if site is not None:
            self._scope_cache[key] = env
        return env

    def _function(self, node, env, declared=True):
        key = (id(node), id(env))
        if key not in self._function_cache:
            value = _Function(node, env, self._path, declared)
            self._function_cache[key] = value
            self._functions.append(value)
        return self._function_cache[key]

    def _state(self):
        def value_key(value, active=()):
            if isinstance(value, _Choice):
                return ('choice', tuple(value_key(v, active) for v in value.values))
            if isinstance(value, _Array):
                if id(value) in active:
                    return ('array-cycle', id(value))
                items = None if value.items is None else tuple(
                    value_key(v, (*active, id(value))) for v in value.items)
                return ('array', id(value), items)
            if isinstance(value, _Opaque):
                if id(value) in active:
                    return ('object-cycle', id(value))
                return ('object', id(value), tuple(value_key(v, (*active, id(value))) for v in value.values))
            if isinstance(value, _Function):
                return ('function', id(value.node), id(value.env), value.declared)
            return value
        return tuple((id(env), tuple((key, value_key(value))
                     for key, value in env.values.items())) for env in self._envs)

    def _block(self, body, env):
        for node in body:
            if node.kind == 'function':
                env.values[node.data['name']] = self._function(node, env)
        returns = []
        for node in body:
            d, kind = node.data, node.kind
            if kind == 'bind':
                env.bind(d['name'], self._expr(d['expr'], env))
            elif kind == 'import_all':
                imported = self._expr(d['expr'], env)
                if isinstance(imported, _Module):
                    env.values.update(imported.env.values)
            elif kind == 'return':
                returns.append(self._expr(d.get('expr'), env))
            elif kind == 'function':
                pass
            elif kind == 'type':
                for method in d['methods']:
                    self._function(method, env)
            elif kind == 'if':
                self._expr(d['condition'], env)
                # Monotone cells combine both paths, including writes through
                # closures. Copying only the current dict loses capture effects.
                returns.extend(self._block(d['yes'], env))
                returns.extend(self._block(d['no'], env))
            elif kind == 'try':
                returns.extend(self._block(d['body'], env))
                rescue = self._environment(env, 'block', (id(node), 'rescue'))
                rescue.bind(d['reason'], UNKNOWN)
                returns.extend(self._block(d['rescue'], rescue))
            elif kind == 'loop':
                self._expr(d.get('count'), env)
                for _ in range(MAX_STATIC_ALTERNATIVES):
                    before = self._state()
                    returns.extend(self._block(d['body'], env))
                    if self._state() == before:
                        break
                else:
                    self._unresolved(node, '循环携带的原生描述符（静态数据流未收敛）')
            elif kind == 'scope':
                scope = self._environment(env, 'block', id(node))
                returns.extend(self._block(d['body'], scope))
            elif kind == 'assign':
                self._expr(d['expr'], env)
                target = d['target']
                receiver = self._expr(target.data.get('receiver'), env)
                self._invalidate(receiver, node)
                self._children(target.data.get('index'), env)
            else:
                self._children(d, env)
        return returns

    def _children(self, value, env):
        if isinstance(value, Node):
            self._expr(value, env)
        elif isinstance(value, dict):
            for child in value.values():
                self._children(child, env)
        elif isinstance(value, (tuple, list)):
            for child in value:
                self._children(child, env)

    def _expr(self, node, env, reference=False):
        if node is None:
            return None
        self._steps += 1
        if self._steps > 200000:
            self._error(node, '原生签名静态分析超过复杂度上限；请简化签名构造和包装函数')
        d, kind = node.data, node.kind
        if kind in ('string', 'number', 'fact'):
            return d['value']
        if kind == 'null':
            return None
        if kind == 'import':
            return self._module(d.get('resolved'))
        if kind in ('name', 'call'):
            value = env.get(d['name'])
            if kind == 'call':
                return self._invoke(value, self._arguments(d['args'], env), node)
            if not reference and isinstance(value, _Function) and value.declared:
                return self._invoke(value, [], node)
            return value
        if kind == 'array':
            items = tuple(self._expr(item, env) for item in d['items'])
            key = (id(node), id(env))
            if key not in self._array_cache:
                self._array_cache[key] = _Array(items)
            else:
                value = self._array_cache[key]
                if value.items is not None:
                    value.items = tuple(_merge(old, new) for old, new in zip(value.items, items))
            return self._array_cache[key]
        if kind == 'function_literal':
            return self._function(node, env, False)
        if kind == 'function_ref':
            selected = self._expr(d['expr'], env, True)
            # References remain ordinary callable values after aliasing; only
            # declaration names have the language's implicit zero-arg call.
            return _merge(*(_Function(item.node, item.env, item.path, False)
                            if isinstance(item, _Function) else item
                            for item in _alternatives(selected)))
        if kind == 'invoke':
            return self._invoke(self._expr(d['callee'], env, True),
                                self._arguments(d['args'], env), node)
        if kind == 'member':
            receiver = self._expr(d['receiver'], env)
            args = self._arguments(d['args'], env)
            return _merge(*(self._member(item, d['name'], args, node, reference)
                            for item in _alternatives(receiver)))
        if kind == 'index':
            receiver = self._expr(d['receiver'], env)
            index = self._expr(d['index'], env)
            return self._index(receiver, index)
        if kind == 'slice':
            receiver = self._expr(d['receiver'], env)
            self._expr(d.get('start'), env)
            self._expr(d.get('end'), env)
            return self._opaque(node, env, [receiver])
        if kind == 'convert':
            value = self._expr(d['expr'], env)
            if d['target'] == '阵':
                # Ru conversion wraps the operand in a singleton array. Keep
                # all reachable aliases, even when the operand is already an array.
                return self._opaque(node, env, [value])
            return UNKNOWN
        if kind == 'binary' and d['op'] == '对':
            return self._opaque(node, env, [self._expr(d['left'], env), self._expr(d['right'], env)])
        if kind == 'map':
            return self._opaque(node, env, [self._expr(item, env) for pair in d['entries'] for item in pair])
        if kind == 'new':
            # The unmodeled instance may retain and subsequently mutate fields.
            values = [value for _, value in self._arguments(d['args'], env)]
            for value in values:
                self._invalidate(value, node)
            return self._opaque(node, env, values)
        # Inspect all subexpressions but never run arbitrary operators, casts,
        # input, native functions or user effects to obtain static ABI values.
        self._children(d, env)
        return UNKNOWN

    def _index(self, receiver, index):
        values = []
        for item in _alternatives(receiver):
            for position in _alternatives(index):
                if isinstance(item, _Array) and item.items is not None:
                    if isinstance(position, (int, float)):
                        if int(position) == position and 0 <= position < len(item.items):
                            values.append(item.items[int(position)])
                        else:
                            values.append(UNKNOWN)
                    else:
                        values.extend(item.items)
                else:
                    values.append(item if isinstance(item, _Opaque) else UNKNOWN)
        return _merge(*values)

    def _opaque(self, node, env, values):
        key = (id(node), id(env))
        if key not in self._opaque_cache:
            self._opaque_cache[key] = _Opaque(values)
        else:
            value = self._opaque_cache[key]
            value.values = tuple(_merge(old, new) for old, new in zip(value.values, values))
        return self._opaque_cache[key]

    def _arguments(self, args, env):
        return [(key, self._expr(value, env)) for key, value in args]

    def _bind(self, name, args, names, node):
        return bind_arguments(name, args, names, lambda text: self._error(node, text))

    def _member(self, receiver, name, args, node, reference):
        if isinstance(receiver, _Module):
            value = receiver.env.get(name)
            if reference:
                return value
            if args or (isinstance(value, _Function) and value.declared):
                return self._invoke(value, args, node)
            return value
        if receiver is NATIVE or receiver is LIBRARY:
            operation = _Operation(name, receiver)
            return operation if reference else self._invoke(operation, args, node)
        if isinstance(receiver, _Array):
            if name == '位':
                values = self._bind(name, args, ['位'], node)
                return self._index(receiver, values['位'])
            if name == '段':
                return self._opaque(node, receiver, [receiver])
            if name in ('量', '含'):
                return UNKNOWN
        # Unknown user methods may mutate arguments, objects reachable through
        # them, or captured cells of callable arguments. Never keep stale ABI
        # arrays merely because dispatch itself could not be resolved.
        self._invalidate(receiver, node)
        for _, value in args:
            self._invalidate(value, node)
        return UNKNOWN

    def _invalidate(self, value, node, visited=None):
        visited = set() if visited is None else visited
        for item in _alternatives(value):
            if id(item) in visited:
                continue
            visited.add(id(item))
            if isinstance(item, _Array):
                children = item.items or ()
                item.items = None
                for child in children:
                    self._invalidate(child, node, visited)
            elif isinstance(item, _Opaque):
                for child in item.values:
                    self._invalidate(child, node, visited)
            elif isinstance(item, _Module):
                for child in tuple(item.env.values.values()):
                    self._invalidate(child, node, visited)
            elif isinstance(item, _Operation) and item.name in ('签名', '回调', '类型'):
                self._unresolved(node, '传给未知调用的原生描述符构造器')
            elif isinstance(item, _Function):
                self._deferred_functions[(id(item.node), id(item.env))] = item
                self._invoke(item, [(None, UNKNOWN) for _ in item.node.data['params']], node)
                outer = item.env
                while outer is not None and outer.kind != 'module':
                    for child in tuple(outer.values.values()):
                        self._invalidate(child, node, visited)
                    outer = outer.parent

    def _context_key(self, value):
        if isinstance(value, _Choice):
            return ('choice', tuple(self._context_key(v) for v in value.values))
        if isinstance(value, _Function):
            return ('function', id(value.node), id(value.env), value.declared)
        if isinstance(value, (_Array, _Opaque, _Module)):
            return (type(value).__name__, id(value))
        return value

    def _pure_scalar_recursion(self, function):
        """Prove a narrow self-recursive body cannot affect native ABI flow.

        No general recursive inference: operands may be parameters, but every
        returned/bound value must be scalar-producing. There are no external
        calls, native members, containers, references or free-variable reads.
        """
        data = function.node.data
        if data.get('procedure'):
            return False
        parameters = {name for name, _ in data['params']}
        scalar_parameters = {name for name, typ in data['params'] if typ in ('数', '事实', '句')}
        local_names = set()
        returns = []

        def collect(body):
            for statement in body:
                detail = statement.data
                if statement.kind == 'bind':
                    local_names.add(detail['name'])
                elif statement.kind == 'if':
                    collect(detail['yes'])
                    collect(detail['no'])
                elif statement.kind in ('loop', 'scope'):
                    collect(detail['body'])
        collect(data['body'])
        # An apparent local bind could target an enclosing captured cell.
        outer = function.env
        while outer is not None and outer.kind != 'module':
            if (local_names - parameters) & outer.values.keys():
                return False
            outer = outer.parent
        allowed_names = set(parameters)
        scalar_names = set(scalar_parameters)
        name = data.get('name')
        if not name or name in parameters or name in local_names:
            return False

        def expression(value, scalar=False):
            if value is None:
                return False
            kind, detail = value.kind, value.data
            if kind in ('number', 'fact', 'string'):
                return True
            if kind == 'name':
                return detail['name'] in (scalar_names if scalar else allowed_names)
            if kind == 'binary' and detail['op'] in ('==', '!='):
                # Object equality can invoke the user-defined 同 method.
                return expression(detail['left'], True) and expression(detail['right'], True)
            if kind == 'binary' and detail['op'] in (
                    '+', '-', '*', '/', '%', '<', '<=', '>', '>=', '且', '或'):
                return expression(detail['left']) and expression(detail['right'])
            if kind == 'unary' and detail['op'] in ('+', '-', '非'):
                return expression(detail['expr'])
            if kind == 'convert' and detail['target'] in ('数', '事实'):
                return expression(detail['expr'])
            if kind == 'call' and detail['name'] == name:
                return all(expression(arg) for _, arg in detail['args'])
            if kind == 'invoke' and detail['callee'].kind == 'name' and detail['callee'].data['name'] == name:
                return all(expression(arg) for _, arg in detail['args'])
            return False

        def statements(body):
            nonlocal allowed_names, scalar_names
            for statement in body:
                kind, detail = statement.kind, statement.data
                if kind in ('bind', 'return'):
                    if not expression(detail['expr'], True):
                        return False
                    if kind == 'return':
                        returns.append(statement)
                    else:
                        allowed_names.add(detail['name'])
                        scalar_names.add(detail['name'])
                elif kind == 'expr':
                    if not expression(detail['expr']):
                        return False
                elif kind == 'if':
                    if not expression(detail['condition']):
                        return False
                    initial = (set(allowed_names), set(scalar_names))
                    if not statements(detail['yes']):
                        return False
                    yes = (set(allowed_names), set(scalar_names))
                    allowed_names, scalar_names = initial
                    if not statements(detail['no']):
                        return False
                    allowed_names &= yes[0]
                    scalar_names &= yes[1]
                elif kind in ('loop', 'scope'):
                    if kind == 'loop' and detail['count'] is not None and not expression(detail['count']):
                        return False
                    initial = (set(allowed_names), set(scalar_names))
                    if not statements(detail['body']):
                        return False
                    # A loop may not run; block locals do not escape their scope.
                    allowed_names, scalar_names = initial
                elif kind != 'break':
                    return False
            return True
        return statements(data['body']) and bool(returns)

    def _invoke(self, function, args, node):
        if isinstance(function, _Choice):
            return _merge(*(self._invoke(value, args, node) for value in function.values))
        if isinstance(function, _Operation):
            return self._native(function, args, node)
        if not isinstance(function, _Function):
            self._invalidate(function, node)
            for _, value in args:
                self._invalidate(value, node)
            return UNKNOWN
        names = [name for name, _ in function.node.data['params']]
        actuals = self._bind(function.node.data.get('name', '<匿名>'), args, names, node)
        self._called.add(id(function.node))
        if id(function.node) in self._active:
            if self._pure_scalar_recursion(function):
                # Even a proven scalar body must not erase argument provenance
                # at a skipped recursive edge. Conservatively retain its effects.
                for _, value in args:
                    self._invalidate(value, node)
                return UNKNOWN
            self._error(node, 'C 原生后端无法证明此递归路径与原生描述符无关；仅支持无捕获、无容器或成员访问、仅有标量运算与直接自调用的递归函数；请将其他递归改为迭代')
        self._active.add(id(function.node))
        context = tuple(self._context_key(actuals[name]) for name in names)
        env = self._environment(function.env, 'function', (id(function.node), context))
        for name, value in actuals.items():
            # Parameters always create local cells, even when a captured
            # binding has the same name. Calls share a conservative summary.
            env.values[name] = _merge(env.values[name], value) if name in env.values else value
        previous = self._path
        self._call_sites.append((previous, node))
        self._path = function.path
        try:
            values = self._block(function.node.data['body'], env)
            return _merge(*values) if values else UNKNOWN
        finally:
            self._path = previous
            self._call_sites.pop()
            self._active.remove(id(function.node))

    def _native(self, operation, args, node):
        name = operation.name
        if operation.receiver is LIBRARY:
            if name == '绑定':
                values = self._bind(name, args, ['名称', '签名'], node)
                self._require_signatures(values['签名'], node, '绑定签名')
            return UNKNOWN
        if name == '类型':
            value = self._bind(name, args, ['名称'], node)['名称']
            names = _alternatives(value)
            if any(not isinstance(n, str) or n not in PRIMITIVE_IDS for n in names):
                self._unresolved(node, '原生类型')
            return _merge(*(_Type(n) for n in names))
        if name == '结构':
            return _Type('结构')
        if name in ('系统库', '动态库'):
            return LIBRARY
        if name == '签名':
            values = self._bind(name, args, ['返回', '参数', '约定'], node)
            conventions = _alternatives(values['约定'])
            if UNKNOWN in conventions:
                self._unresolved(node, '原生调用约定')
            if any(c not in ('win64', 'cdecl') for c in conventions):
                self._error(node, '调用约定只支持 win64 或 cdecl；不支持变参')
            result_types = _alternatives(values['返回'])
            results = []
            for result, params in product(result_types, _alternatives(values['参数'])):
                if not isinstance(result, _Type) or not isinstance(params, _Array) or params.items is None:
                    self._unresolved(node, '原生签名的返回类型或参数阵')
                origin_path, origin = self._path, node
                if origin_path == self._native_path:
                    for candidate_path, candidate in reversed(self._call_sites):
                        if candidate_path != self._native_path:
                            origin_path, origin = candidate_path, candidate
                            break
                self._signature_inputs[(id(params), result.name, id(node))] = (params, result.name, origin_path, origin)
                if len(params.items) > 64:
                    self._error(node, '签名参数须为不超过 64 项的阵')
                possibilities = [_alternatives(item) for item in params.items]
                count = 1
                for choices in possibilities:
                    count *= len(choices)
                if count > MAX_STATIC_ALTERNATIVES:
                    self._unresolved(node, '有限原生参数类型组合')
                for parameters in product(*possibilities):
                    if any(not isinstance(item, _Type) for item in parameters):
                        self._unresolved(node, '原生签名的参数类型')
                    if result.name == '结构' or any(item.name in ('结构', '无值') for item in parameters):
                        self._error(node, '首版不支持按值传递结构或无值参数；请显式传结构地址')
                    signature = NativeCSignature(result.name, tuple(item.name for item in parameters))
                    if signature not in self.signatures:
                        if len(self.signatures) >= MAX_SIGNATURES:
                            self._error(node, 'C 原生签名数量超过 1024 上限')
                        self.signatures.append(signature)
                    results.append(signature)
            return _merge(*results)
        if name == '回调':
            values = self._bind(name, args, ['签名', '算', '失败值'], node)
            signatures = self._require_signatures(values['签名'], node, '原生回调签名')
            self.callback_signatures.update(signatures)
            # Callback bodies can themselves contain native signature sites.
            callback = values['算']
            for signature in signatures:
                for fn in _alternatives(callback):
                    if isinstance(fn, _Function):
                        self._deferred_functions[(id(fn.node), id(fn.env))] = fn
                        self._invoke(fn, [(None, UNKNOWN) for _ in signature.params], node)
            return UNKNOWN
        return UNKNOWN

    def _require_signatures(self, value, node, what):
        signatures = _alternatives(value)
        if any(not isinstance(item, NativeCSignature) for item in signatures):
            self._unresolved(node, what)
        return signatures

    @staticmethod
    def declarations():
        return ('static int ru_native_generated_signature(int, int, const int *, int);\n'
                'static RuNativeRaw ru_native_generated_call(int, void *, const RuNativeRaw *);\n'
                'static void *ru_native_generated_callback(int, unsigned);\n')

    def emit_c(self):
        """Emit exact typed thunks. No libffi, Python, executable allocation or JIT."""
        lines = [
            '/* Ahead-of-time primitive ABI thunks: Windows x64 only. */',
            '#if !defined(_WIN32) || defined(_M_ARM64) || defined(_M_ARM64EC) || (!defined(_M_X64) && !defined(__x86_64__))',
            '#error "Ru native C requires Windows x64"',
            '#endif',
        ]
        for index, signature in enumerate(self.signatures):
            result = C_TYPES[signature.result]
            parameters = ', '.join(C_TYPES[item] for item in signature.params) or 'void'
            lines.append(f'typedef {result} (*RuNativeCall_{index})({parameters});')
            lines.append(f'static RuNativeRaw ru_native_call_{index}(void *address, const RuNativeRaw *args) {{')
            lines.append(f'    union {{ void *address; RuNativeCall_{index} function; }} target;')
            lines.append('    RuNativeRaw result = {0}; target.address = address; (void)args;')
            arguments = ', '.join(f'({C_TYPES[item]})args[{i}].{RAW_FIELDS[item]}'
                                  for i, item in enumerate(signature.params))
            call = f'target.function({arguments})'
            if signature.result == '无值':
                lines.append(f'    {call};')
            else:
                lines.append(f'    result.{RAW_FIELDS[signature.result]} = {call};')
            lines.extend(('    return result;', '}'))
            if signature not in self.callback_signatures:
                continue
            callback_params = ', '.join(f'{C_TYPES[item]} a{i}' for i, item in enumerate(signature.params)) or 'void'
            for slot in range(MAX_CALLBACKS):
                lines.append(f'static {result} ru_native_callback_{index}_{slot}({callback_params}) {{')
                if signature.params:
                    lines.append(f'    RuNativeRaw args[{len(signature.params)}] = {{0}};')
                    for i, item in enumerate(signature.params):
                        lines.append(f'    args[{i}].{RAW_FIELDS[item]} = a{i};')
                call = f'ru_native_callback_dispatch({slot}, {index}, ' + ('args)' if signature.params else 'NULL)')
                if signature.result == '无值':
                    lines.append(f'    (void){call};')
                else:
                    lines.append(f'    return ({result}){call}.{RAW_FIELDS[signature.result]};')
                lines.append('}')
            lines.append(f'static RuNativeCall_{index} const ru_native_callbacks_{index}[{MAX_CALLBACKS}] = {{')
            for start in range(0, MAX_CALLBACKS, 8):
                lines.append('    ' + ', '.join(f'ru_native_callback_{index}_{slot}' for slot in range(start, start + 8)) + ',')
            lines.append('};')
        lines.extend(('static int ru_native_generated_signature(int result, int argc, const int *params, int convention) {',
                      '    if (convention != 0 && convention != 1) return -1;',
                      '    (void)result; (void)argc; (void)params;'))
        for index, signature in enumerate(self.signatures):
            tests = [f'result == {PRIMITIVE_IDS[signature.result]}', f'argc == {len(signature.params)}']
            if signature.params:
                tests.append('params != NULL')
            tests.extend(f'params[{i}] == {PRIMITIVE_IDS[item]}' for i, item in enumerate(signature.params))
            lines.append(f'    if ({" && ".join(tests)}) return {index};')
        lines.extend(('    return -1;', '}',
                      'static RuNativeRaw ru_native_generated_call(int signature, void *address, const RuNativeRaw *args) {',
                      '    (void)address; (void)args;', '    switch (signature) {'))
        for index in range(len(self.signatures)):
            lines.append(f'    case {index}: return ru_native_call_{index}(address, args);')
        lines.extend(('    default: { RuNativeRaw zero = {0}; return zero; }', '    }', '}',
                      'static void *ru_native_generated_callback(int signature, unsigned slot) {',
                      f'    if (slot >= {MAX_CALLBACKS}) return NULL;', '    switch (signature) {'))
        for index, signature in enumerate(self.signatures):
            if signature in self.callback_signatures:
                lines.append(f'    case {index}: {{ union {{ RuNativeCall_{index} function; void *address; }} value;')
                lines.append(f'        value.function = ru_native_callbacks_{index}[slot]; return value.address; }}')
        lines.extend(('    default: return NULL;', '    }', '}'))
        return '\n'.join(lines) + '\n'

    source = emit_c
