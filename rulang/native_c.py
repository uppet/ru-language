"""Finite, ahead-of-time native ABI plans for standalone Windows x64 C.

This module only inspects the parsed module graph.  It never evaluates Ru code,
loads a DLL, imports ctypes, or synthesizes executable memory.  Native calls and
callbacks are ordinary, exactly typed C functions generated for declared shapes.
Unknown signature components are a compilation error, not a runtime ABI guess.
"""
from collections import OrderedDict, deque
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from time import perf_counter

from .frontend import Node, RuError, bind_arguments, validate


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
SCALAR_LITERAL_PRECISION = 128  # Widening threshold; never rejects data candidates.
# Expression visits are diagnostics, never a whole-program admission quota.
MAX_CALL_SUMMARIES = 4096
MAX_EXPRESSION_SUMMARIES = 16384
MAX_EXPRESSION_DEPENDENCIES = 256
MAX_LITERAL_ARRAYS = 1024
_STATEMENT_CHUNK_SIZE = 3
MAX_SUMMARY_FUNCTIONS = 256
MAX_SUMMARY_DEPENDENCIES = 256


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
# Analysis-only numeric top: unlike UNKNOWN it absorbs later numeric constants
# in joins, so widening a large data table remains a monotone fixed point.
NUMBER = _Unknown()
# Unknown string literal history; never a proven ABI name/convention.
STRING = _Unknown()
NATIVE = object()
LIBRARY = object()


class _Array:
    def __init__(self, items):
        self.items = tuple(items)
        # Losing positional/ABI knowledge must not lose aliases. Once invalid,
        # retain one monotone reachability value per original initializer slot.
        self.reachable = ()
        self.assigned = ()
        self.projection = None
        self._version = 0


class _Opaque:
    """Reachable values in an object whose member semantics are not modeled."""
    def __init__(self, values):
        self.values = tuple(values)
        self.assigned = ()
        self._version = 0


class _Binding:
    """A live name token, including absence before a later shadowing bind."""
    def __init__(self, owner, name):
        self.owner, self.name = owner, name

    @property
    def _version(self):
        return self.owner._binding_versions.get(self.name, 0)


class _Env:
    def __init__(self, changed, observed, parent=None, kind="module", fixed=(), private=False, read=None):
        self._changed = changed
        self._observed = observed
        self._read = read or (lambda owner, name: observed(owner))
        self._binding_versions = {}
        self._bindings = {}
        self._version = 0
        self.values = {}
        self.local_origins = {}
        self.parent = parent
        self.kind = kind
        self.fixed_locals = frozenset(fixed)
        self.private = private

    def get(self, name):
        # A missing name is a dependency too: a later local binding can shadow
        # the parent value that this lookup currently returns.
        self._read(self, name)
        if name in self.values:
            value = self.values[name]
            if self.kind != 'module' and name not in self.fixed_locals:
                # Abstract scopes are reused; runtime function/block scopes are
                # fresh. Before a local's bind runs on another entry, this read
                # may still resolve to an ancestor. Preserve that live alias,
                # including reads first discovered through a later callable.
                outer = self.parent
                while outer is not None:
                    self._read(outer, name)
                    if name in outer.values:
                        return _merge(value, outer.get(name))
                    outer = outer.parent
                if name == '__密':
                    return _merge(value, NATIVE)
            return value
        if self.parent is not None:
            return self.parent.get(name)
        return NATIVE if name == '__密' else UNKNOWN

    def put(self, name, value, join=False):
        self._observed(self)
        if name in self.values:
            old = self.values[name]
            if join:
                value = _merge(old, value)
            if _same(old, value):
                return
        self.values[name] = value
        self._binding_versions[name] = self._binding_versions.get(name, 0) + 1
        self._changed(self)

    def bind(self, name, value, node=None):
        # Match env_bind: a function updates captured local cells, while a
        # block/rescue shadows and module bindings are never rebound by a
        # function. Join old/new possibilities conservatively; source-order
        # overwrites alone are insufficient for loops and reentrant closures.
        target = self
        self._observed(self)
        if name not in self.values and self.kind == 'function':
            outer = self.parent
            while outer is not None and outer.kind != 'module':
                self._observed(outer)
                if name in outer.values:
                    target = outer
                    break
                outer = outer.parent
            if target is self:
                # A future invocation has a fresh runtime scope. Retaining this
                # abstract local is safe only while it cannot become a capture.
                # This metadata accompanies the versioned insertion below.
                self.local_origins[name] = node
        target.put(name, value, join=True)


class _Function:
    def __init__(self, node, env, path, declared=True):
        self.node, self.env, self.path = node, env, path
        self.declared = declared


class _Module:
    def __init__(self, env):
        self.env = env


class _SummaryFrame:
    """Bounded evidence for one transfer, never truncated into a usable proof.

    Expressions retain precise private binding dependencies. Whole functions
    may elide private scopes only after proving their first-read versions are
    stable, or using the original unchanged-global-revision proof. Ephemeral
    private evidence also crosses nested evaluations and converged loops.
    """
    def __init__(self, function=None, *, track_private=None):
        self.functions = {id(function.node)} if function is not None else set()
        self.track_private = function is None if track_private is None else track_private
        self.dependency_limit = (MAX_EXPRESSION_DEPENDENCIES if self.track_private
                                 else MAX_SUMMARY_DEPENDENCIES)
        self.dependencies = {}
        self.path_sensitive = False
        self.complete = True
        self.private_reads = {}
        self.replay_complete = True

    def read(self, owner, name, version=None):
        """Keep the first private read, never a post-write replacement."""
        key = (owner, name)
        if not self.replay_complete or key in self.private_reads:
            return
        if len(self.private_reads) >= MAX_SUMMARY_DEPENDENCIES:
            self.replay_complete = False
            return
        self.private_reads[key] = owner._binding_versions.get(name, 0) if version is None else version

    def replay_stable(self):
        """Interned allocations and private initialization are now idempotent."""
        return (self.replay_complete and
                all(owner._version == version for owner, version in self.dependencies.items()) and
                all(owner._binding_versions.get(name, 0) == version
                    for (owner, name), version in self.private_reads.items()))

    def observe(self, owner, version=None):
        if isinstance(owner, _Binding) and not self.track_private:
            if owner.owner.private:
                self.read(owner.owner, owner.name, version)
                return
            if (owner.owner in self.dependencies and
                    (version is None or owner._version == version)):
                return
        # A scope with no nested function/literal/method anywhere in its body
        # cannot escape to a child callable that writes it independently. Its
        # contents on re-entry are determined by this call context and external
        # owners still tracked below. Keeping every such child scope creates
        # false fanout overflow.
        # Initial private writes need the separate first-read/replay proof;
        # unchanged global revision remains the conservative fallback. Arrays,
        # objects, captures and modules are never elided.
        if isinstance(owner, _Env) and owner.private:
            return
        if not self.complete or owner in self.dependencies:
            return
        if len(self.dependencies) >= self.dependency_limit:
            self.complete = False
            return
        # Retain the first read, even if a later write changes this owner.
        self.dependencies[owner] = owner._version if version is None else version

    def add_function(self, function):
        if function not in self.functions:
            if len(self.functions) >= MAX_SUMMARY_FUNCTIONS:
                self.complete = False
            else:
                self.functions.add(function)

    def absorb(self, frame):
        self.include(frame.dependencies.items(), frame.functions, frame.complete)
        self.replay_complete = self.replay_complete and frame.replay_complete
        for key, version in frame.private_reads.items():
            if key not in self.private_reads:
                if len(self.private_reads) >= MAX_SUMMARY_DEPENDENCIES:
                    self.replay_complete = False
                    break
                self.private_reads[key] = version

    def include(self, dependencies, functions, complete=True):
        self.complete = self.complete and complete
        for owner, version in dependencies:
            self.observe(owner, version)
        for function in functions:
            self.add_function(function)


def _alternatives(value):
    return value.values if isinstance(value, _Choice) else (value,)


def _same(left, right):
    # Python equates True/1 and False/0, but facts are not numeric candidates.
    # Keep their identity before a later numeric widening can erase constants.
    if ((type(left) is bool and type(right) in (int, float)) or
            (type(right) is bool and type(left) in (int, float))):
        return False
    if isinstance(left, _Choice) and isinstance(right, _Choice):
        return len(left.values) == len(right.values) and all(
            _same(a, b) for a, b in zip(left.values, right.values))
    if isinstance(left, _Function) and isinstance(right, _Function):
        return (left.node is right.node and left.env is right.env and
                left.declared == right.declared)
    return left is right or left == right


def _merge_key(value):
    """Keys equivalent to _same for the recognized, closed analysis domain.

    Unknown/extension values use the original comparator, including against
    keyed values. Nested choices likewise retain the recursive comparator.
    """
    kind = type(value)
    if kind is bool:
        return ('bool', value)
    if kind in (int, float):
        return ('number', value)
    if kind is str:
        return ('string', value)
    if value is None:
        return ('none',)
    if kind in (_Array, _Opaque, _Module, _Env, _Binding, _Unknown, object):
        return ('identity', id(value))
    if kind is _Function and type(value.declared) is bool:
        return ('function', id(value.node), id(value.env), value.declared)
    if kind is _Type and type(value.name) is str:
        return ('type', value.name)
    if (kind is NativeCSignature and type(value.result) is str
            and type(value.params) is tuple and all(type(x) is str for x in value.params)):
        return ('signature', value.result, value.params)
    if (kind is _Operation and type(value.name) is str
            and (value.receiver is None or type(value.receiver) in
                 (_Array, _Opaque, _Module, _Env, _Binding, _Unknown, object))):
        return ('operation', value.name, id(value.receiver))
    return None


def _merge(*values):
    result = []
    keys = set()
    fallback = []
    numeric = False
    string = False
    numeric_count = 0
    string_count = 0

    def remove_literals(kinds):
        nonlocal result, keys, fallback, numeric_count, string_count
        result = [item for item in result if type(item) not in kinds]
        keys = set()
        fallback = []
        numeric_count = string_count = 0
        for item in result:
            key = _merge_key(item)
            if key is None:
                fallback.append(item)
            else:
                keys.add(key)
            numeric_count += type(item) in (int, float)
            string_count += type(item) is str

    def append_unique(alternative):
        nonlocal numeric_count, string_count
        key = _merge_key(alternative)
        if key is None or fallback:
            # Preserve comparator direction/order for extension values.
            duplicate = any(_same(alternative, item) for item in result)
        else:
            duplicate = key in keys
        if duplicate:
            return
        result.append(alternative)
        if key is None:
            fallback.append(alternative)
        else:
            keys.add(key)
        numeric_count += type(alternative) in (int, float)
        string_count += type(alternative) is str

    for value in values:
        for alternative in _alternatives(value):
            if alternative is NUMBER:
                if numeric_count:
                    remove_literals((int, float))
                numeric = True
            elif alternative is STRING:
                if string_count:
                    remove_literals((str,))
                string = True
            elif string and type(alternative) is str:
                continue
            elif numeric and type(alternative) in (int, float):
                continue
            append_unique(alternative)
            if len(result) > SCALAR_LITERAL_PRECISION:
                if numeric_count:
                    remove_literals((int, float))
                    if not numeric:
                        result.append(NUMBER)
                        keys.add(_merge_key(NUMBER))
                    numeric = True
                if string_count:
                    remove_literals((str,))
                    if not string:
                        result.append(STRING)
                        keys.add(_merge_key(STRING))
                    string = True
    if not result:
        return UNKNOWN
    return result[0] if len(result) == 1 else _Choice(tuple(result))


def _reachable_values(*values):
    # An invalid array cannot supply scalar/type information. Keep every owner,
    # callable and descriptor constructor that an unknown operation can affect,
    # but do not accumulate irrelevant scalar histories after invalidation.
    return _merge(*(item for value in values for item in _alternatives(value)
                    if isinstance(item, (_Array, _Opaque, _Function, _Module, _Operation))))


def _same_returns(accumulated, final):
    # A failed optimization proof must not move an error before a later body
    # statement; the ordinary return join remains the semantic evaluation site.
    try:
        return _same(_merge(*accumulated), _merge(*final))
    except RuError:
        return False


class NativeCPlan:
    """Analyze a resolved ``{source_path: [Node, ...]}`` module graph.

    Supported static dataflow includes primitive/module/function aliases,
    import-all, named arguments, local declarations, closure captures and finite
    conditional alternatives. Descriptor cells use conservative monotone joins;
    loops iterate to a monotone fixed point and unsupported mutable/callable
    escapes are rejected when they prevent ABI resolution. Functions are analyzed
    with their static actuals. Recursion is accepted only for a proven pure
    scalar self-recursive subset; other recursive paths are rejected;
    otherwise their bodies are checked with unknown inputs. Runtime-produced
    types, parameter arrays and conventions are deliberately rejected.

    ``emit_c()`` goes after native_runtime.h.  The runtime owns marshalling,
    callback lifetime/containment and the process-wide 1024 non-reused slots.
    """
    def __init__(self, modules, *, diagnostics=None):
        self._diagnostics = diagnostics
        self._module_steps = {}
        self._function_counts = {}
        self.modules = dict(modules)
        self.sources = getattr(modules, 'sources', {})
        self.signatures = []
        self._signature_index = {}
        self.callback_signatures = set()
        self._revision = 0
        self._call_summaries = {}
        self._expression_summaries = OrderedDict()
        # AST-only slices are shared by every environment, never per-context.
        self._block_chunks = {}
        self._block_hits = 0
        self._expression_hits = 0
        self._literal_array_items = {}
        self._literal_array_hits = 0
        self._summary_frames = []
        self._summary_hits = 0
        self._function_evaluations = 0
        self._module_values = {}
        self._loading = set()
        self._functions = []
        self._function_cache = {}
        self._scope_cache = {}
        self._private_body_cache = {}
        self._array_cache = {}
        self._opaque_cache = {}
        self._envs = []
        self._called = set()
        self._active = set()
        self._call_sites = []
        self._heap_context = ()
        self._capture_contexts = {}
        self._deferred_functions = {}
        self._deferred_queue = deque()
        self._deferred_pending = set()
        self._deferred_dependencies = {}
        self._deferred_watchers = {}
        self._deferred_untracked = {}
        self._signature_inputs = {}
        self._steps = 0
        self._path = next(iter(self.modules), '<源码>')
        self._native_path = str((Path(__file__).parent / 'stdlib' / '密.ru').resolve())
        started = perf_counter()
        self._analysis_completed = False
        failure_kind = None
        try:
            self._analyze()
            self._analysis_completed = True
        except (MemoryError, RecursionError) as error:
            # Finite source may still require expensive context-sensitive work.
            # Report actual host exhaustion, not a fixed project-size quota or
            # an unresolved ABI guess. Never expose a partial native plan.
            failure_kind = 'memory' if isinstance(error, MemoryError) else 'host-stack'
            self.signatures = ()
            self._signature_index.clear()
            self.callback_signatures = frozenset()
            detail = '宿主内存不足' if failure_kind == 'memory' else '宿主分析调用栈耗尽'
            raise RuError('原生签名静态分析未完成：' + detail +
                          '；未生成原生 ABI 计划。可使用 --native-analysis 查看统计',
                          category='资源错误') from None
        finally:
            if diagnostics is not None:
                try:
                    diagnostics({
                        'schema': 2, 'phase': 'native-signatures',
                        'completed': self._analysis_completed, 'seconds': perf_counter() - started,
                        'resource_failure': failure_kind,
                        'modules': len(self.modules), 'signatures': len(self.signatures),
                        'steps': self._steps, 'step_limit': None,
                        'function_evaluations': self._function_evaluations,
                        'summary_hits': self._summary_hits,
                        'expression_hits': self._expression_hits,
                        'block_hits': self._block_hits,
                        'literal_array_hits': self._literal_array_hits,
                        'module_steps': dict(self._module_steps),
                        'function_evaluations_by_site': dict(self._function_counts),
                    })
                except Exception:
                    # Diagnostic output is best-effort while another failure or
                    # cancellation is propagating. It must not replace that
                    # cause, especially after an allocation failure.
                    if self._analysis_completed:
                        raise


    def _analyze(self):
        # Termination relies on the language's declaration/binding rules.
        # Internal callers may supply AST dictionaries without the module
        # loader; reject illegal strong hoist/rebind cycles before inference.
        for body in self.modules.values():
            validate(body)
        for path in self.modules:
            self._module(path)
        # Check dormant functions as well. Native standard-library forwarding
        # functions are templates; their real call sites provide the ABI values.
        index = 0
        # Propagate only after an observed owner changes. A long acyclic chain
        # is ordinary project size, not evidence of nonconvergence: it must not
        # consume a fixed global number of passes. New escaped functions are
        # queued once; the existing conservative call/loop/value rules apply
        # inside every transfer, including synchronous callback registration.
        while index < len(self._functions) or self._deferred_queue:
            while index < len(self._functions):
                fn = self._functions[index]
                index += 1
                if id(fn.node) not in self._called and fn.path != self._native_path:
                    self._invoke(fn, [(None, UNKNOWN) for _ in fn.node.data['params']], fn.node)
            if self._deferred_queue:
                key = self._deferred_queue.popleft()
                self._deferred_pending.discard(key)
                self._revisit_deferred(key)
        # Late-discovered methods/callbacks may invalidate aliases that fed an
        # earlier constructor. The static subset requires those descriptor arrays
        # to remain provable after all effect summaries have settled.
        for params, result, path, origin in self._signature_inputs.values():
            self._path = path
            if params.items is None:
                self._unresolved(origin, '被后续作用影响的原生签名参数阵')
            self._before_signature_revalidation(params, result, origin)
            possibilities = [_alternatives(item) for item in params.items]
            # Reject unknown late aliases before a potentially large product.
            if any(not isinstance(item, _Type) for choices in possibilities for item in choices):
                self._unresolved(origin, '被后续作用影响的原生参数类型')
            for items in product(*possibilities):
                signature = NativeCSignature(result, tuple(item.name for item in items))
                if signature not in self._signature_index:
                    self._unresolved(origin, '被后续作用改变的原生签名')
        self.signatures = tuple(self.signatures)
        self.callback_signatures = frozenset(self.callback_signatures)

    def _before_signature_revalidation(self, params, result, origin):
        pass

    def _changed(self, owner=None):
        # All abstract mutations (including new scopes/containers/functions,
        # descriptor inputs and signatures) advance this monotone generation.
        # An unchanged generation proves a fixed point without repeatedly
        # serializing the complete module graph. A changed generation may cause
        # conservative extra passes for newly allocated unreachable values;
        # it can never stop earlier than structural equality would.
        # The global stamp proves zero effects for expression summaries and
        # loop convergence. Whole-function first-call reuse additionally uses
        # observed owner versions and private binding-read evidence.
        if owner is not None:
            owner._version += 1
        self._revision += 1
        # Incomplete dependency evidence never licenses a skipped transfer.
        # Such tasks subscribe to all changes, including newly allocated owners.
        for key in tuple(self._deferred_untracked):
            self._queue_deferred(key)
        if owner is not None:
            for key in tuple(self._deferred_watchers.get(owner, ())):
                self._queue_deferred(key)

    def _observe(self, owner):
        if self._summary_frames:
            self._summary_frames[-1].observe(owner)

    def _read(self, owner, name):
        if not self._summary_frames:
            return
        frame = self._summary_frames[-1]
        if owner.private:
            frame.read(owner, name)
        if frame.track_private:
            if name not in owner._bindings:
                owner._bindings[name] = _Binding(owner, name)
            frame.observe(owner._bindings[name])
        else:
            frame.observe(owner)

    def _observe_value(self, value):
        """Keep live alias owners, without freezing a closure's whole graph.

        Function/module values retain their live environments. Their eventual
        reads and escapes record the cells they actually inspect; merely
        returning a function must not depend on every unrelated module value.
        """
        if not self._summary_frames:
            return
        frame = self._summary_frames[-1]
        pending, visited = [value], set()
        while pending and frame.complete:
            item = pending.pop()
            if isinstance(item, _Choice):
                pending.extend(item.values)
                continue
            if not isinstance(item, (_Array, _Opaque, _Function, _Module, _Env)):
                continue
            if item in visited:
                continue
            if len(visited) >= frame.dependency_limit:
                frame.complete = False
                break
            visited.add(item)
            if isinstance(item, _Function):
                pending.append(item.env)
            elif isinstance(item, _Module):
                pending.append(item.env)
            else:
                self._observe(item)
                if isinstance(item, _Env):
                    if item.parent is not None:
                        pending.append(item.parent)
                elif isinstance(item, _Array):
                    pending.extend(item.items if item.items is not None else item.reachable)
                    pending.extend(item.assigned)
                else:
                    pending.extend(item.values)
                    pending.extend(item.assigned)

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

    def _environment(self, parent=None, kind='module', site=None, body=(), fixed=()):
        key = (site, id(parent), kind)
        if site is not None and key in self._scope_cache:
            return self._scope_cache[key]
        fixed = set(fixed) | {node.data['name'] for node in body if node.kind == 'function'}
        env = _Env(self._changed, self._observe, parent, kind, fixed,
                   kind != 'module' and self._private_body(body), read=self._read)
        self._envs.append(env)
        self._changed()
        if site is not None:
            self._scope_cache[key] = env
        return env

    def _private_body(self, body):
        """Prove that no callable can retain this scope or a descendant scope."""
        key = id(body)
        if key not in self._private_body_cache:
            pending = [body]
            private = True
            while pending:
                value = pending.pop()
                if isinstance(value, Node):
                    if value.kind in ('function', 'function_literal', 'type'):
                        private = False
                        break
                    pending.append(value.data)
                elif isinstance(value, dict):
                    pending.extend(value.values())
                elif isinstance(value, (tuple, list)):
                    pending.extend(value)
            self._private_body_cache[key] = private
        return self._private_body_cache[key]

    def _function(self, node, env, declared=True):
        self._path_dependent()
        key = (id(node), id(env))
        if key not in self._function_cache:
            value = _Function(node, env, self._path, declared)
            self._function_cache[key] = value
            self._functions.append(value)
            self._changed()
        return self._function_cache[key]

    def _fixed_point_state(self):
        return self._revision

    def _state(self):
        # Snapshot the reachable graph, not its expansion along every path.
        # Shared containers can form diamonds/cycles; their identity and each
        # ordered edge are recorded once, without discarding any leaf value.
        pending, owners, choices = [], {}, {}

        def value_key(value):
            if value is STRING:
                return ('string-top',)
            if type(value) is bool:
                return ('fact', value)
            if type(value) in (int, float):
                return ('number', value)
            if isinstance(value, _Choice):
                # Choices are immutable value unions, not identity-bearing
                # owners. _merge keeps their alternatives flat; sharing an
                # equal wrapper must not change fixed-point equality.
                key = id(value)
                if key not in choices:
                    choices[key] = ('choice', tuple(value_key(v) for v in value.values))
                return choices[key]
            if isinstance(value, (_Array, _Opaque)):
                key = id(value)
                if key not in owners:
                    owners[key] = value
                    pending.append(value)
                return ('array' if isinstance(value, _Array) else 'object', key)
            if isinstance(value, _Function):
                return ('function', id(value.node), id(value.env), value.declared)
            return value

        roots = tuple((id(env), tuple((key, value_key(value))
                      for key, value in env.values.items())) for env in self._envs)
        records = []
        for owner in pending:
            if isinstance(owner, _Array):
                values = (None, tuple(value_key(v) for v in owner.reachable)) if owner.items is None else (
                    tuple(value_key(v) for v in owner.items), ())
                kind = 'array'
            else:
                values = tuple(value_key(v) for v in owner.values)
                kind = 'object'
            if owner.assigned:
                values = (values, ('assigned', tuple(value_key(v) for v in owner.assigned)))
            records.append((id(owner), kind, values))
        return roots, tuple(sorted(records))

    def _block(self, body, env, *, hoisted=False):
        # Summarize bounded statement transfers as well as expressions. A
        # large function can exceed the dependency bound while small ordered
        # regions are independently stable. Keep their original environment,
        # return order, full first-read evidence and recursive-call footprint.
        # These entries compete in the existing expression LRU, not a new
        # capacity. A hit still consumes a step; misses charge their expressions.
        if not hoisted:
            # Hoist exactly once over the entire original body. Re-hoisting
            # a later chunk would overwrite an earlier statement's rebinding.
            for node in body:
                if node.kind == 'function':
                    env.put(node.data['name'], self._function(node, env))
        if len(body) > _STATEMENT_CHUNK_SIZE and MAX_EXPRESSION_SUMMARIES > 0:
            chunks = self._block_chunks.get(id(body))
            if chunks is None:
                chunks = tuple(body[start:start + _STATEMENT_CHUNK_SIZE]
                               for start in range(0, len(body), _STATEMENT_CHUNK_SIZE))
                self._block_chunks[id(body)] = chunks
            return [value for chunk in chunks for value in self._block(chunk, env, hoisted=True)]
        if not body or MAX_EXPRESSION_SUMMARIES <= 0:
            return self._block_body(body, env)
        key = ('block', id(body), id(env))
        summary_key = key
        summary = self._expression_summaries.get(summary_key)
        if summary is None:
            summary_key = ('closed-block', id(body))
            summary = self._expression_summaries.get(summary_key)
        if (summary is not None and
                all(owner._version == version for owner, version in summary[0]) and
                not self._active.intersection(summary[2])):
            if summary[3]:
                self._path_dependent()
            self._charge(body[0])
            if self._summary_frames:
                self._summary_frames[-1].include(summary[0], summary[2])
            self._expression_summaries.move_to_end(summary_key)
            self._block_hits += 1
            return summary[1]
        revision = self._revision
        frame = _SummaryFrame()
        self._summary_frames.append(frame)
        try:
            result = self._block_body(body, env)
            # A hit is charged one step, so it may contribute at most one
            # return item. Replaying an accumulated loop-return list could
            # otherwise multiply duplicate items exponentially without visits.
            # Do not merge here: that could move a candidate-validation error
            # ahead of later statements. Multi-return blocks simply run again.
            if len(result) <= 1 and frame.complete and (revision == self._revision or frame.replay_stable()):
                # Only literal primitive expression statements may cross envs.
                # Empty version evidence alone is not sufficient: an idempotent
                # private binding write still initializes a fresh environment.
                if (not result and self._closed_primitive_block(body)
                        and revision == self._revision and frame.replay_complete
                        and not frame.dependencies and not frame.private_reads
                        and not frame.functions and not frame.path_sensitive):
                    key = ('closed-block', id(body))
                if key not in self._expression_summaries and len(self._expression_summaries) >= MAX_EXPRESSION_SUMMARIES:
                    self._expression_summaries.popitem(last=False)
                self._expression_summaries[key] = (tuple(frame.dependencies.items()), result, frozenset(frame.functions), frame.path_sensitive)
                self._expression_summaries.move_to_end(key)
            return result
        finally:
            self._summary_frames.pop()
            if self._summary_frames:
                self._summary_frames[-1].absorb(frame)

    @staticmethod
    def _closed_primitive_block(body):
        pending = []
        for statement in body:
            if statement.kind != 'expr':
                return False
            pending.append(statement.data['expr'])
        while pending:
            node = pending.pop()
            if node.kind in ('number', 'string', 'fact', 'null'):
                continue
            if node.kind == 'unary':
                pending.append(node.data['expr'])
            elif node.kind == 'binary' and node.data['op'] != '对':
                pending.extend((node.data['left'], node.data['right']))
            else:
                return False
        return True

    def _block_body(self, body, env):
        returns = []
        for node in body:
            d, kind = node.data, node.kind
            if kind == 'bind':
                env.bind(d['name'], self._expr(d['expr'], env), node)
            elif kind == 'import_all':
                imported = self._expr(d['expr'], env)
                if isinstance(imported, _Module):
                    self._observe(imported.env)
                    for name, value in imported.env.values.items():
                        env.put(name, value)
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
                rescue = self._environment(env, 'block', (id(node), 'rescue'),
                                           d['rescue'], (d['reason'],))
                rescue.bind(d['reason'], UNKNOWN)
                returns.extend(self._block(d['rescue'], rescue))
            elif kind == 'loop':
                self._expr(d.get('count'), env)
                # A final zero-change iteration witnesses idempotent private
                # state. Preserve all external observations and all returns;
                # only transient private reads may be replaced by that witness.
                loop_frame = _SummaryFrame(track_private=False)
                loop_returns = []
                while True:
                    before = self._fixed_point_state()
                    frame = _SummaryFrame(track_private=False)
                    self._summary_frames.append(frame)
                    try:
                        iteration_returns = self._block(d['body'], env)
                        for value in iteration_returns:
                            self._observe_value(value)
                    finally:
                        self._summary_frames.pop()
                    loop_returns.extend(iteration_returns)
                    loop_frame.absorb(frame)
                    if self._fixed_point_state() == before:
                        if (loop_frame.complete and frame.replay_complete and
                                _same_returns(loop_returns, iteration_returns)):
                            loop_frame.private_reads = dict(frame.private_reads)
                            loop_frame.replay_complete = True
                        break
                returns.extend(loop_returns)
                if self._summary_frames:
                    self._summary_frames[-1].absorb(loop_frame)
            elif kind == 'scope':
                scope = self._environment(env, 'block', id(node), d['body'])
                returns.extend(self._block(d['body'], scope))
            elif kind == 'assign':
                # Runtime selects receiver/index before evaluating the RHS.
                # Member-style 位 stores its index expressions in args.
                target = d['target']
                receiver = self._expr(target.data.get('receiver'), env)
                self._children(target.data.get('index'), env)
                self._children(target.data.get('args'), env)
                value = self._expr(d['expr'], env)
                self._invalidate(receiver, node)
                self._retain_assignment(receiver, value, target, node)
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

    def _charge(self, node):
        self._steps += 1
        if self._diagnostics is not None:
            self._module_steps[self._path] = self._module_steps.get(self._path, 0) + 1

    def _expr(self, node, env, reference=False):
        if node is None:
            return None
        self._charge(node)
        if MAX_EXPRESSION_SUMMARIES <= 0 or node.kind not in ('call', 'invoke', 'member', 'index', 'binary', 'unary', 'convert',
                             'array', 'slice', 'map', 'new', 'function_ref'):
            return self._expr_body(node, env, reference)
        # Lookup itself already consumed one expression step. A hit avoids
        # the actual descendant traversal; visit accounting remains exact.
        key = (id(node), id(env), reference)
        summary = self._expression_summaries.get(key)
        if (summary is not None and
                all(owner._version == version for owner, version in summary[0]) and
                not self._active.intersection(summary[2])):
            if summary[3]:
                self._path_dependent()
            if self._summary_frames:
                self._summary_frames[-1].include(summary[0], summary[2])
            self._expression_summaries.move_to_end(key)
            self._expression_hits += 1
            return summary[1]
        revision = self._revision
        frame = _SummaryFrame()
        self._summary_frames.append(frame)
        try:
            result = self._expr_body(node, env, reference)
            if revision == self._revision and frame.complete:
                if key not in self._expression_summaries and len(self._expression_summaries) >= MAX_EXPRESSION_SUMMARIES:
                    self._expression_summaries.popitem(last=False)
                self._expression_summaries[key] = (tuple(frame.dependencies.items()), result, frozenset(frame.functions), frame.path_sensitive)
                self._expression_summaries.move_to_end(key)
            return result
        finally:
            self._summary_frames.pop()
            if self._summary_frames:
                self._summary_frames[-1].absorb(frame)

    def _expr_body(self, node, env, reference=False):
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
            return value if reference else self._implicit(value, node)
        if kind == 'array':
            self._path_dependent()
            # Only immutable primitive items are shared across call contexts.
            # Each finite allocation context still owns its mutable _Array.
            # The first visit evaluates/charges every literal before caching.
            literal_items = self._literal_array_items.get(id(node))
            if literal_items is not None:
                items = literal_items
                self._literal_array_hits += 1
            else:
                items = tuple(self._expr(item, env) for item in d['items'])
                if (MAX_LITERAL_ARRAYS > 0 and
                        all(item.kind in ('string', 'number', 'fact', 'null') for item in d['items'])):
                    if len(self._literal_array_items) >= MAX_LITERAL_ARRAYS:
                        del self._literal_array_items[next(iter(self._literal_array_items))]
                    self._literal_array_items[id(node)] = items
            key = (id(node), self._heap_context or id(env))
            if key not in self._array_cache:
                self._array_cache[key] = _Array(items)
                self._changed()
            else:
                value = self._array_cache[key]
                self._observe(value)
                if value.items is None:
                    merged = tuple(_reachable_values(old, new)
                                   for old, new in zip(value.reachable, items))
                    if not all(_same(old, new) for old, new in zip(value.reachable, merged)):
                        value.reachable = merged
                        self._changed(value)
                    # This allocation site was already exposed to an unknown
                    # effect. A fresh initializer can introduce a new alias,
                    # or an older opaque child can gain new reachable owners.
                    self._invalidate(value, node)
                else:
                    merged = tuple(_merge(old, new) for old, new in zip(value.items, items))
                    if not all(_same(old, new) for old, new in zip(value.items, merged)):
                        value.items = merged
                        self._changed(value)
            self._observe(self._array_cache[key])
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
            if isinstance(item, _Array):
                self._observe(item)
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
                    if isinstance(item, _Array):
                        # An unknown child can have different member semantics
                        # from this array. Keep its live alias graph in an opaque
                        # projection instead of applying array-only shortcuts.
                        if item.projection is None:
                            item.projection = _Opaque((item,))
                            self._changed()
                        values.append(item.projection)
                    else:
                        values.append(item if isinstance(item, _Opaque) else UNKNOWN)
        return _merge(*values)

    def _opaque(self, node, env, values):
        self._path_dependent()
        key = (id(node), self._heap_context or id(env))
        if key not in self._opaque_cache:
            self._opaque_cache[key] = _Opaque(values)
            self._changed()
        else:
            value = self._opaque_cache[key]
            self._observe(value)
            merged = tuple(_merge(old, new) for old, new in zip(value.values, values))
            if not all(_same(old, new) for old, new in zip(value.values, merged)):
                value.values = merged
                self._changed(value)
        self._observe(self._opaque_cache[key])
        return self._opaque_cache[key]

    def _arguments(self, args, env):
        return [(key, self._expr(value, env)) for key, value in args]

    def _bind(self, name, args, names, node):
        return bind_arguments(name, args, names, lambda text: self._error(node, text))

    def _implicit(self, value, node):
        # An ancestor/local union may contain declared functions alongside
        # ordinary values. Each declaration still has its zero-argument call
        # semantics; references and returned callable aliases remain values.
        if isinstance(value, _Choice):
            return _merge(*(self._implicit(item, node) for item in value.values))
        if isinstance(value, _Function) and value.declared:
            return self._invoke(value, [], node)
        return value

    def _member(self, receiver, name, args, node, reference):
        if isinstance(receiver, _Module):
            value = receiver.env.get(name)
            if reference:
                return value
            if args:
                return self._invoke(value, args, node)
            return self._implicit(value, node)
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

    def _retain_assignment(self, receiver, value, target, node):
        # Losing the receiver's old positional knowledge must not lose the new
        # RHS alias. Record it after invalidating OLD contents: a plain store
        # does not itself mutate the newly stored value. Future unknown uses
        # traverse this separate monotone edge set, including literal re-entry.
        for owner in _alternatives(receiver):
            if isinstance(owner, (_Array, _Opaque)):
                self._observe(owner)
                retained = tuple(item for item in _alternatives(_reachable_values(*owner.assigned, value))
                                 if isinstance(item, (_Array, _Opaque, _Function, _Module, _Operation)))
                if not _same(_Choice(owner.assigned), _Choice(retained)):
                    owner.assigned = retained
                    self._changed(owner)
            else:
                # An untracked destination may retain or mutate the RHS; no
                # concrete owner exists on which a future read can find it.
                self._invalidate(value, node)

    def _invalidate(self, value, node, visited=None):
        # Walk the owner graph, not its expansion along every path. Retained
        # aliases may form deep diamonds/cycles after their ABI shape is lost.
        def captures(env):
            # A child callable may change an ancestor. Snapshot each scope only
            # after processing the preceding scope, matching depth-first effects.
            while env is not None and env.kind != 'module':
                self._observe(env)
                yield from tuple(env.values.values())
                env = env.parent

        visited = set() if visited is None else visited
        pending = [iter(_alternatives(value))]
        exhausted = object()
        while pending:
            item = next(pending[-1], exhausted)
            if item is exhausted:
                pending.pop()
                continue
            if id(item) in visited:
                continue
            visited.add(id(item))
            children = ()
            if isinstance(item, _Array):
                self._observe(item)
                if item.items is not None:
                    item.reachable = tuple(_reachable_values(child) for child in item.items)
                    item.items = None
                    self._changed(item)
                children = item.reachable + item.assigned
            elif isinstance(item, _Opaque):
                self._observe(item)
                children = item.values + item.assigned
            elif isinstance(item, _Module):
                self._observe(item.env)
                children = tuple(item.env.values.values())
            elif isinstance(item, _Operation) and item.name in ('签名', '回调', '类型'):
                self._unresolved(node, '传给未知调用的原生描述符构造器')
            elif isinstance(item, _Function):
                self._defer(item)
                self._invoke(item, [(None, UNKNOWN) for _ in item.node.data['params']], node)
                children = captures(item.env)
            pending.append(iter(child for value in children for child in _alternatives(value)))

    def _queue_deferred(self, key):
        if key not in self._deferred_pending:
            self._deferred_pending.add(key)
            self._deferred_queue.append(key)

    def _defer(self, function):
        key = (id(function.node), id(function.env))
        if key not in self._deferred_functions:
            self._deferred_functions[key] = function
            self._queue_deferred(key)
            self._changed()

    def _revisit_deferred(self, key):
        function = self._deferred_functions[key]
        for owner in self._deferred_dependencies.pop(key, ()):
            watchers = self._deferred_watchers[owner]
            watchers.pop(key, None)
            if not watchers:
                del self._deferred_watchers[owner]
        self._deferred_untracked.pop(key, None)
        frame = _SummaryFrame()
        revision = self._revision
        self._summary_frames.append(frame)
        try:
            self._invoke(function, [(None, UNKNOWN) for _ in function.node.data['params']], function.node)
        finally:
            self._summary_frames.pop()
        # A missing or shadowed binding is an owner dependency too. Waking on
        # any write to that environment is conservative, even for a name read.
        owners = {owner.owner if isinstance(owner, _Binding) else owner
                  for owner in frame.dependencies}
        owners.update(owner for owner, _ in frame.private_reads)
        self._deferred_dependencies[key] = owners
        for owner in owners:
            self._deferred_watchers.setdefault(owner, {})[key] = None
        if not frame.complete or not frame.replay_complete:
            self._deferred_untracked[key] = None
            if self._revision != revision:
                self._queue_deferred(key)
        elif self._revision != revision and not frame.replay_stable():
            # A read-then-write transfer must be revisited at its new input,
            # never summarized by replacing first-read versions with exit ones.
            self._queue_deferred(key)

    def _context_key(self, value):
        self._observe_value(value)
        if value is STRING:
            return ('string-top',)
        if type(value) is bool:
            return ('fact', value)
        if type(value) in (int, float):
            return ('number', value)
        if isinstance(value, _Choice):
            return ('choice', tuple(self._context_key(v) for v in value.values))
        if isinstance(value, _Function):
            return ('function', id(value.node), id(value.env), value.declared)
        if isinstance(value, (_Array, _Opaque, _Module)):
            return (type(value).__name__, id(value))
        return value

    def _check_capture_targets(self, function, context):
        # Module bindings are never captured write targets of a function.
        # Do not observe unrelated historical private scopes for this check.
        # Actual body reads and escaped closure environments remain observed.
        if function.env.kind == 'module':
            return
        key = ((id(function.node), context), id(function.env), 'function')
        env = self._scope_cache.get(key)
        if env is None:
            return
        self._observe(env)
        if not env.local_origins:
            return
        # Parameters and direct declarations establish local cells on every
        # entry. Other source-created function locals come from bind: import-all
        # is top-level-only, and nested declaration blocks have their own envs.
        outer = env.parent
        while outer is not None and outer.kind != 'module':
            self._observe(outer)
            for name, origin in env.local_origins.items():
                if name not in env.fixed_locals and name in outer.values:
                    previous = self._path
                    self._path = function.path
                    try:
                        self._error(origin or function.node,
                                    f'C 原生后端无法静态确定随调用改变的捕获绑定「{name}」；'
                                    '请在首次调用前初始化外层同名变量，或为局部变量使用不同名字')
                    finally:
                        self._path = previous
            outer = outer.parent

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
            self._observe(outer)
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
                elif kind not in ('break', 'continue'):
                    return False
            return True
        return statements(data['body']) and bool(returns)

    def _path_dependent(self):
        for frame in self._summary_frames:
            frame.path_sensitive = True

    def _invoke(self, function, args, node):
        previous = self._heap_context
        if isinstance(function, _Function):
            self._heap_context += ((id(node), id(function.node)),)
        try:
            return self._invoke_heap_body(function, args, node)
        finally:
            self._heap_context = previous

    def _invoke_heap_body(self, function, args, node):
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
        if self._summary_frames:
            self._summary_frames[-1].add_function(id(function.node))
        if id(function.node) in self._active:
            if self._pure_scalar_recursion(function):
                # Even a proven scalar body must not erase argument provenance
                # at a skipped recursive edge. Conservatively retain its effects.
                for _, value in args:
                    self._invalidate(value, node)
                return UNKNOWN
            self._error(node, 'C 原生后端无法证明此递归路径与原生描述符无关；仅支持无捕获、无容器或成员访问、仅有标量运算与直接自调用的递归函数；请将其他递归改为迭代')
        actual_context = tuple(self._context_key(actuals[name]) for name in names)
        context = (self._heap_context, actual_context)
        scope_context = (self._heap_context, actual_context if self._private_body(function.node.data['body']) else ())
        if function.env.kind != 'module':
            capture_key = (id(function.node), id(function.env), actual_context)
            previous_contexts = self._capture_contexts.setdefault(capture_key, set())
            for previous_context in previous_contexts:
                self._check_capture_targets(function, previous_context)
            previous_contexts.add(scope_context)
        # Reusing a historical local after a parent introduces the same name
        # could hide a newly captured write or a read before that write. Reject
        # this unsupported scope transition before any cached body can skip it.
        self._check_capture_targets(function, scope_context)
        key = (self._context_key(function), context)
        portable_key = (self._context_key(function), actual_context)
        summary = self._call_summaries.get(key) or self._call_summaries.get(portable_key)
        if (summary is not None and
                all(owner._version == version for owner, version in summary[0]) and
                not self._active.intersection(summary[2])):
            if summary[3]:
                self._path_dependent()
            # The body's observed state is unchanged. Its effects and discovered
            # signatures already persist in the shared analysis.
            # Descendant calls must not hide a newly active recursive edge.
            if self._summary_frames:
                self._summary_frames[-1].include(summary[0], summary[2])
            self._summary_hits += 1
            return summary[1]
        self._active.add(id(function.node))
        env = self._environment(function.env, 'function', (id(function.node), scope_context),
                                function.node.data['body'], names)
        for name, value in actuals.items():
            # Parameters always create local cells, even when a captured
            # binding has the same name. Calls share a conservative summary.
            env.put(name, value, join=True)
        previous = self._path
        self._call_sites.append((previous, node))
        self._path = function.path
        revision = self._revision
        frame = _SummaryFrame(function)
        self._summary_frames.append(frame)
        # The cached scope can also be reached by an escaped closure. Observe
        # it even if this particular body never reads any of its own bindings.
        self._observe(env)
        self._observe_value(function)
        for value in actuals.values():
            self._observe_value(value)
        self._function_evaluations += 1
        if self._diagnostics is not None:
            site = f'{function.path}:{function.node.token.line}:{function.node.token.col}'
            self._function_counts[site] = self._function_counts.get(site, 0) + 1
        try:
            values = self._block(function.node.data['body'], env)
            result = _merge(*values) if values else UNKNOWN
            self._observe_value(result)
            # A read-then-write capture (or private local) cannot summarize
            # its exit state. Keep first versions through nested evaluations.
            # Interned allocations/private writes can be reused on the first
            # call only when that stricter replay evidence remains stable.
            # Bound each retained recursion footprint as well as entry count.
            # A larger footprint may still be analyzed, but never truncated
            # into an unsound reusable summary.
            if frame.complete and (self._revision == revision or frame.replay_stable()):
                if not frame.path_sensitive:
                    key = portable_key
                if key not in self._call_summaries and len(self._call_summaries) >= MAX_CALL_SUMMARIES:
                    del self._call_summaries[next(iter(self._call_summaries))]
                self._call_summaries[key] = (tuple(frame.dependencies.items()), result,
                                             frozenset(frame.functions), frame.path_sensitive)
            return result
        finally:
            self._summary_frames.pop()
            if self._summary_frames:
                self._summary_frames[-1].absorb(frame)
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
            if UNKNOWN in conventions or STRING in conventions:
                self._unresolved(node, '原生调用约定')
            if any(c not in ('win64', 'cdecl') for c in conventions):
                self._error(node, '调用约定只支持 win64 或 cdecl；不支持变参')
            result_types = _alternatives(values['返回'])
            parameter_arrays = _alternatives(values['参数'])
            # Validate every alternative before enumerating any ABI product.
            # In particular, a last-slot UNKNOWN must not trigger exponential
            # work over earlier valid slots before it is rejected.
            if any(not isinstance(result, _Type) for result in result_types):
                self._unresolved(node, '原生签名的返回类型或参数阵')
            prepared = []
            for params in parameter_arrays:
                if isinstance(params, _Array):
                    self._observe(params)
                if not isinstance(params, _Array) or params.items is None:
                    self._unresolved(node, '原生签名的返回类型或参数阵')
                if len(params.items) > 64:
                    self._error(node, '签名参数须为不超过 64 项的阵')
                possibilities = tuple(_alternatives(item) for item in params.items)
                if any(not isinstance(item, _Type) for choices in possibilities for item in choices):
                    self._unresolved(node, '原生签名的参数类型')
                if (any(result.name == '结构' for result in result_types) or
                        any(item.name in ('结构', '无值') for choices in possibilities for item in choices)):
                    self._error(node, '首版不支持按值传递结构或无值参数；请显式传结构地址')
                prepared.append((params, possibilities))
            results = {}
            for result in result_types:
                for params, possibilities in prepared:
                    origin_path, origin = self._path, node
                    if origin_path == self._native_path:
                        for candidate_path, candidate in reversed(self._call_sites):
                            if candidate_path != self._native_path:
                                origin_path, origin = candidate_path, candidate
                                break
                    input_key = (id(params), result.name, id(node))
                    if input_key not in self._signature_inputs:
                        self._changed()
                    self._signature_inputs[input_key] = (params, result.name, origin_path, origin)
                    for parameters in product(*possibilities):
                        signature = NativeCSignature(result.name, tuple(item.name for item in parameters))
                        if signature not in self._signature_index:
                            self._signature_index[signature] = len(self.signatures)
                            self.signatures.append(signature)
                            self._changed()
                        results[signature] = None
            alternatives = tuple(results)
            return alternatives[0] if len(alternatives) == 1 else _Choice(alternatives) if alternatives else UNKNOWN
        if name == '回调':
            values = self._bind(name, args, ['签名', '算', '失败值'], node)
            signatures = self._require_signatures(values['签名'], node, '原生回调签名')
            if not self.callback_signatures.issuperset(signatures):
                self.callback_signatures.update(signatures)
                self._changed()
            # Callback bodies can themselves contain native signature sites.
            callback = values['算']
            for signature in signatures:
                for fn in _alternatives(callback):
                    if isinstance(fn, _Function):
                        self._defer(fn)
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
        try:
            return self._emit_c_complete()
        except (MemoryError, RecursionError) as error:
            detail = '宿主内存不足' if isinstance(error, MemoryError) else '宿主生成调用栈耗尽'
            raise RuError('原生 C 代码生成未完成：' + detail + '；未返回部分 C 源码',
                          category='资源错误') from None

    def _emit_c_complete(self):
        """Emit exact typed thunks. No libffi, Python, executable allocation or JIT."""
        if not getattr(self, '_analysis_completed', False):
            raise RuError('原生签名分析未完成；禁止生成部分 ABI 计划', category='原生编译错误')
        # Generated/runtime signature IDs are Windows x64 C signed int.
        # This is representability, not a project-size admission quota.
        if len(self.signatures) - 1 > 0x7fffffff:
            raise RuError('原生 ABI 计划超出 C signature ID 的 signed int 可表示范围；未生成代码', category='资源错误')
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
