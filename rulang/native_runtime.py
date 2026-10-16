"""Generic opt-in native ABI facilities for the local Windows x64 interpreter.

This is a trusted-code bridge, NOT a sandbox. Incorrect declarations or native
code can corrupt or terminate the process. No Win32 application policy lives here.
"""
from dataclasses import dataclass
import ctypes as C
import math
from pathlib import Path
import re
import struct
import threading
import weakref

from .frontend import Node, Token, RuError, bind_arguments
from .contest_runtime import _BUILTIN_OWNER

NATIVE_MODULE = "如:密"
SAFE_INTEGER = (1 << 53) - 1
MAX_BUFFER = 16 * 1024 * 1024
MAX_CALLBACKS = 1024
MAX_CALLBACK_RETURN_OWNERS = 128
_TYPES = {}
# Never release a trampoline whose address may still be held by foreign code.
# Closed entries detach Ru closures, host owners and failure hooks. This bounded
# process registry trades a small tombstone for a dangling executable pointer.
_CALLBACK_TOMBSTONES = []
_CALLBACK_LOCK = threading.Lock()


@dataclass(frozen=True)
class NativeCapability:
    allowed: bool = False


class NativeFault(Exception):
    pass


def _fault(message):
    raise NativeFault(message)


def _supported():
    import sys
    return sys.platform == "win32" and C.sizeof(C.c_void_p) == 8 and __import__('platform').machine().lower() in ('amd64', 'x86_64')


class NativeContext:
    def __init__(self, capability):
        self._capability = capability
        self.thread = threading.current_thread()
        self.depth = 0
        self.callback_depth = 0
        self.errors = []
        self.containment_failure = False
        self.handling_failure = False
        self.callbacks = set()

    @property
    def capability(self):
        return self._capability

    def check(self):
        if not self.capability.allowed:
            _fault("原生能力默认关闭；仅受信任的本地程序可用 ru run --allow-native 文件.ru 显式开启；如书不可开启")
        if not _supported():
            _fault("如:密／如见目前仅支持本地 Python 解释器的 Windows x64；此平台不支持原生能力")
        if threading.current_thread() is not self.thread:
            _fault("原生对象只能在所属解释器线程使用")

    def error(self, text):
        # Keep the first failure, bounded even if foreign code repeatedly calls.
        if not self.errors:
            self.errors.append(text[:4096])


@dataclass(frozen=True)
class NativeType:
    name: str
    ctype: object
    kind: str
    bits: int = 0
    signed: bool = False
    fields: tuple = ()

    @property
    def size(self):
        return 0 if self.kind == 'void' else C.sizeof(self.ctype)

    @property
    def alignment(self):
        return 1 if self.kind == 'void' else C.alignment(self.ctype)


PRIMITIVES = {}
for _name, _ctype, _bits, _signed in (
    ('i8', C.c_int8, 8, True), ('u8', C.c_uint8, 8, False),
    ('i16', C.c_int16, 16, True), ('u16', C.c_uint16, 16, False),
    ('i32', C.c_int32, 32, True), ('u32', C.c_uint32, 32, False),
    ('i64', C.c_int64, 64, True), ('u64', C.c_uint64, 64, False),
    ('intptr', C.c_int64, 64, True), ('uintptr', C.c_uint64, 64, False)):
    PRIMITIVES[_name] = NativeType(_name, _ctype, 'int', _bits, _signed)
PRIMITIVES.update({
    'f32': NativeType('f32', C.c_float, 'float', 32),
    'f64': NativeType('f64', C.c_double, 'float', 64),
    '指针': NativeType('指针', C.c_void_p, 'pointer', 64),
    '无值': NativeType('无值', None, 'void'),
})


@dataclass(frozen=True)
class NativeScalar:
    typ: NativeType
    value: object
    anchors: tuple = ()

    def __post_init__(self):
        if self.typ.kind == 'float' and not math.isfinite(self.value):
            _fault('原生浮点结果不是有限数')


class NativeMemory:
    def __init__(self, storage, typ=None, parent=None, prefix=()):
        self.storage, self.typ, self.parent = storage, typ, parent
        self.closed = False
        self.prefix = prefix
        self.pins = {} if parent is None else parent.pins

    def check(self):
        if self.closed:
            _fault("原生缓冲已关闭")
        if self.parent is not None:
            self.parent.check()

    @property
    def address(self):
        self.check()
        return C.addressof(self.storage)

    @property
    def size(self):
        return C.sizeof(self.storage)


@dataclass(frozen=True)
class NativeSignature:
    result: NativeType
    params: tuple
    convention: str

    def prototype(self):
        factory = C.WINFUNCTYPE if self.convention == 'win64' else C.CFUNCTYPE
        return factory(self.result.ctype, *(p.ctype for p in self.params), use_last_error=True)


class NativeLibrary:
    def __init__(self, handle):
        self.handle, self.closed = handle, False

    def check(self):
        if self.closed:
            _fault("动态库已关闭")


@dataclass(frozen=True)
class NativeFunction:
    library: NativeLibrary
    signature: NativeSignature
    function: object


@dataclass(frozen=True)
class NativeOutcome:
    value: object
    error_code: int
    callback_error: object


class NativeCallback:
    def __init__(self, context, owner, node, signature, function, fallback):
        self.context = weakref.ref(context)
        self.thread = context.thread
        self.owner, self.node, self.function = owner, node, function
        self.signature, self.fallback = signature, fallback
        self.failure_hook = None
        self.return_owners = {}
        self.closed, self.active = False, 0
        reference = weakref.ref(self)
        # The process-pinned trampoline captures no interpreter/closure graph.
        def trampoline(*args):
            # This final boundary also contains failures while formatting or
            # recording another failure, and failures in dispatch's finally.
            callback = None
            try:
                callback = reference()
                if callback is None:
                    return fallback
                return callback.dispatch(*args)
            except BaseException:
                try:
                    active_context = callback.context() if callback is not None else None
                    if active_context is not None:
                        active_context.containment_failure = True
                except BaseException:
                    pass
                return fallback
        self.trampoline = signature.prototype()(trampoline)

    def detach(self):
        self.owner = self.node = self.function = self.failure_hook = None
        self.return_owners.clear()

    def close(self):
        self.closed = True
        context = self.context()
        if context is not None:
            context.callbacks.discard(self)
        if self.active == 0:
            self.detach()

    def dispatch(self, *args):
        context = self.context()
        owner_thread = threading.current_thread() is self.thread
        self.active += 1
        counted = context is not None and owner_thread
        if counted:
            context.callback_depth += 1
        entry_error = None
        try:
            entry_error = C.get_last_error() if hasattr(C, 'get_last_error') else 0
            if self.closed:
                _fault("原生回调已关闭；外部代码仍持有其地址")
            if context is None or not owner_thread or context.depth == 0:
                _fault("只支持原生调用期间、所属解释器线程上的同步回调")
            values = [_wrap(NativeScalar(t, 0 if v is None else v), context) for t, v in zip(self.signature.params, args)]
            result = self.owner.invoke_value(self.node, self.function, [(None, v) for v in values])
            _check_context(result, context)
            raw = _marshal(self.signature.result, result)
            if self.signature.result.kind == 'pointer' and raw:
                value = _unwrap(result)
                anchors = value.anchors if isinstance(value, NativeScalar) else (value,)
                if self.closed and anchors:
                    _fault('关闭中的回调不能返回拥有型指针')
                additions = {id(anchor): anchor for anchor in anchors}
                if len(set(self.return_owners) | set(additions)) > MAX_CALLBACK_RETURN_OWNERS:
                    _fault('单个回调返回的拥有型指针资源超过 128 个上限')
                self.return_owners.update(additions)
            return raw
        except BaseException as error:
            if context is not None:
                message = getattr(error, 'message', str(error)) or type(error).__name__
                if isinstance(error, RuError):
                    message = f"{getattr(error, 'source_name', '<回调>')}:{error.line}:{error.col}: {message}"
                context.error("原生回调失败：" + message)
                # A generic owner-thread wake action lets a blocking native call
                # return. Never invoke Ru, or post to the wrong thread, here.
                if owner_thread and context.depth > 0 and self.failure_hook and not context.handling_failure:
                    context.handling_failure = True
                    saved_error = C.get_last_error() if hasattr(C, 'get_last_error') else 0
                    try:
                        function, values = self.failure_hook
                        _invoke(context, function, values)
                    except BaseException:
                        pass  # Preserve the original callback error.
                    finally:
                        context.handling_failure = False
                        if hasattr(C, 'set_last_error'):
                            C.set_last_error(saved_error)
            return self.fallback
        finally:
            # Activity survives logical close, and unwinds before optional
            # reporting/LastError cleanup can itself fail at the ABI boundary.
            self.active -= 1
            if counted:
                context.callback_depth -= 1
            try:
                if self.closed and self.active == 0:
                    self.detach()
            finally:
                if entry_error is not None and hasattr(C, 'set_last_error'):
                    C.set_last_error(entry_error)


def _wrap(payload, context=None):
    from .interpreter import Instance, RuType
    kind = type(payload).__name__
    if kind not in _TYPES:
        node = Node('type', Token('IDENT', '密' + kind.removeprefix('Native'), 0, 0),
                    {'name': '密' + kind.removeprefix('Native'), 'parent': None, 'fields': [], 'methods': []})
        typ = RuType(_BUILTIN_OWNER, node, fields={}, methods={}, state=2)
        typ.native_kind = kind
        _TYPES[kind] = typ
    value = Instance(_TYPES[kind], {})
    value.native_payload = payload
    value.native_context = context
    return value


def _unwrap(value):
    return getattr(value, 'native_payload', value)


def _expect(value, cls, message):
    value = _unwrap(value)
    if not isinstance(value, cls):
        _fault(message)
    return value


def _integer(value):
    value = _unwrap(value)
    if isinstance(value, NativeScalar):
        _check_anchors(value)
        if value.typ.kind not in ('int', 'pointer'):
            _fault("整数转换需要原生整数或指针")
        return value.value
    if isinstance(value, float):
        if not math.isfinite(value) or value != math.trunc(value) or abs(value) > SAFE_INTEGER:
            _fault("数转原生整数须为安全整数；大整数请使用精确十进制句")
        return int(value)
    if isinstance(value, str) and re.fullmatch(r'[+-]?[0-9]+', value) and len(value) <= 128:
        return int(value)
    _fault("原生整数需要安全整数数、精确十进制句或原生整数")


def _bounded(value, low, high, label):
    value = _integer(value)
    if not low <= value <= high:
        _fault(label + "超出范围")
    return value


def _check_anchors(value, active=None):
    active = set() if active is None else active
    value = _unwrap(value)
    if id(value) in active:
        return
    active.add(id(value))
    if isinstance(value, NativeScalar):
        for anchor in value.anchors:
            _check_anchors(anchor, active)
    elif isinstance(value, NativeMemory):
        value.check()
        for anchor in value.pins.values():
            _check_anchors(anchor, active)
    elif isinstance(value, NativeCallback) and value.closed:
        _fault("原生回调已关闭")


def _convert(typ, value, reinterpret=False):
    value = _unwrap(value)
    _check_anchors(value)
    anchors = value.anchors if isinstance(value, NativeScalar) else ()
    if reinterpret:
        if not isinstance(value, NativeScalar) or typ.kind not in ('int', 'pointer') or value.typ.kind not in ('int', 'pointer') or typ.bits != value.typ.bits:
            _fault("重释只支持等宽原生整数与指针")
        _check_anchors(value)
        raw = value.value & ((1 << typ.bits) - 1)
        if typ.signed and raw >= (1 << (typ.bits - 1)):
            raw -= 1 << typ.bits
        return NativeScalar(typ, raw, anchors)
    if typ.kind in ('int', 'pointer'):
        raw = 0 if value is None and typ.kind == 'pointer' else _integer(value)
        low = -(1 << (typ.bits - 1)) if typ.signed else 0
        high = (1 << (typ.bits - (1 if typ.signed else 0))) - 1
        if not low <= raw <= high:
            _fault(typ.name + "转换溢出")
        return NativeScalar(typ, raw, anchors)
    if typ.kind == 'float':
        if isinstance(value, NativeScalar) and (value.typ.kind == 'pointer' or value.anchors):
            _fault('指针或携带资源所有权的值不能转换为浮点')
        raw = value.value if isinstance(value, NativeScalar) else value
        if isinstance(raw, bool) or not isinstance(raw, (float, int)) or not math.isfinite(raw):
            _fault("原生浮点需要有限数")
        narrowed = typ.ctype(raw).value
        if not math.isfinite(narrowed):
            _fault(typ.name + "转换溢出")
        return NativeScalar(typ, narrowed)
    _fault("此类型不支持标量转换")


def _marshal(typ, value):
    value = _unwrap(value)
    if typ.kind == 'void':
        if value is not None:
            _fault("无值回调须返回空")
        return None
    if typ.kind == 'pointer':
        if value is None:
            return None
        if isinstance(value, NativeMemory):
            _check_anchors(value)
            return value.address
        if isinstance(value, NativeCallback):
            _check_anchors(value)
            return C.cast(value.trampoline, C.c_void_p).value
        if isinstance(value, NativeScalar) and value.typ.kind == 'pointer':
            _check_anchors(value)
            return value.value
        _fault("指针参数须为空、原生指针、拥有的缓冲或回调；数值请先显式转换为指针")
    if isinstance(value, NativeScalar) and value.typ.kind == 'pointer':
        _fault("指针转整数须先用 intptr／uintptr 的重释显式转换")
    if not isinstance(value, (float, NativeScalar)):
        _fault('原生标量实参须为数或原生值；精确十进制句请先用类型的值转换')
    return _convert(typ, value).value



def _retain(value, keepalive, active):
    value = _unwrap(value)
    if id(value) in active:
        return
    active.add(id(value))
    keepalive.append(value)
    if isinstance(value, list):
        for child in value:
            _retain(child, keepalive, active)
    elif isinstance(value, NativeScalar):
        for child in value.anchors:
            _retain(child, keepalive, active)
    elif isinstance(value, NativeMemory):
        if value.parent is not None:
            _retain(value.parent, keepalive, active)
        for child in list(value.pins.values()):
            _retain(child, keepalive, active)


def _invoke(context, function, values):
    context.check()
    function.library.check()
    if not isinstance(values, list) or len(values) != len(function.signature.params):
        _fault("原生调用实参数量与签名不符")
    keepalive = []
    _retain(values, keepalive, set())
    converted = [_marshal(t, v) for t, v in zip(function.signature.params, values)]
    # Snapshot all ownership anchors: a reentrant callback may close a resource
    # or overwrite a struct field, but its in-flight storage must stay allocated.
    context.depth += 1
    outer = context.depth == 1
    try:
        if hasattr(C, 'set_last_error'):
            C.set_last_error(0)
        raw = function.function(*converted)
        code = C.get_last_error() if hasattr(C, 'get_last_error') else 0
        typ = function.signature.result
        result = None if typ.kind == 'void' else _wrap(NativeScalar(typ, 0 if raw is None else raw), context)
        error = context.errors[0] if context.errors else ('原生回调失败：错误报告或收束异常' if context.containment_failure else None)
        return NativeOutcome(result, code, error)
    except (OSError, ValueError, TypeError, C.ArgumentError) as error:
        _fault("原生调用失败：" + str(error))
    finally:
        context.depth -= 1
        if outer:
            context.errors.clear()
            context.containment_failure = False


def install_native(owner, context=None, allow_native=False):
    from .interpreter import Scope
    if context is None:
        context = NativeContext(NativeCapability(bool(allow_native)))
    owner._native_context = context
    parent = Scope(owner.global_scope.parent)
    parent.values['__密'] = _wrap(context, context)
    owner.global_scope.parent = parent


def native_import(requested, resolved):
    path = Path(__file__).parent / 'stdlib' / '密.ru'
    return requested == NATIVE_MODULE or (resolved and Path(resolved).resolve() == path.resolve())


def check_native_imports(owner, program, modules=None):
    for node in _native_nodes((program, modules)):
        try:
            owner._native_context.check()
        except NativeFault as error:
            owner.fail(node, str(error))



def _check_context(value, context, active=None):
    active = set() if active is None else active
    if id(value) in active:
        return
    active.add(id(value))
    if hasattr(value, 'native_payload'):
        if value.native_context is not context:
            _fault('原生值不能跨解释器能力上下文传递')
    elif isinstance(value, list):
        for item in value:
            _check_context(item, context, active)


def native_member(owner, node, receiver, name, args):
    payload = getattr(receiver, 'native_payload', None)
    if payload is None:
        return False, None
    context = owner._native_context
    if getattr(receiver, 'native_context', context) is not context:
        owner.fail(node, '原生对象不能跨解释器能力上下文使用')
    def bind(params):
        return bind_arguments(name, args, params, lambda message: _fault(message))
    try:
        context.check()
        for _, argument in args:
            _check_context(argument, context)
        result = _member(context, owner, node, payload, name, bind)
        if isinstance(result, (NativeType, NativeScalar, NativeMemory, NativeSignature, NativeLibrary, NativeFunction, NativeCallback, NativeOutcome)):
            result = _wrap(result, context)
        return True, result
    except NativeFault as error:
        owner.fail(node, str(error))
    except (OverflowError, UnicodeError, ValueError, TypeError, OSError) as error:
        owner.fail(node, "原生操作失败：" + str(error))


def _member(context, owner, node, obj, name, bind):
    if isinstance(obj, NativeContext):
        if name == '回调中':
            bind([])
            return context.callback_depth > 0
        if name == '类型':
            b = bind(['名称'])
            if b['名称'] not in PRIMITIVES:
                _fault("未知原生类型")
            return PRIMITIVES[b['名称']]
        if name == '结构':
            b = bind(['字段'])
            if not isinstance(b['字段'], list) or not 1 <= len(b['字段']) <= 128:
                _fault("结构需要 1 至 128 个字段的阵")
            fields, used = [], set()
            for item in b['字段']:
                if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str) or not item[0] or item[0] in used or item[0].startswith('_'):
                    _fault("结构字段须为不重复的 [字段句, 类型]；名称不能以下划线开头")
                typ = _expect(item[1], NativeType, "结构字段需要原生类型")
                if typ.kind == 'void':
                    _fault("结构字段不能为无值")
                fields.append((item[0], typ))
                used.add(item[0])
            ctype = type('RuNativeStruct', (C.Structure,), {'_fields_': [(k, t.ctype) for k, t in fields]})
            if C.sizeof(ctype) > MAX_BUFFER:
                _fault("原生结构超过缓冲上限")
            return NativeType('结构', ctype, 'struct', fields=tuple(fields))
        if name in ('UTF8', 'UTF16'):
            b = bind(['句'])
            text = b['句']
            if not isinstance(text, str) or '\0' in text:
                _fault("原生文本需要不含 NUL 的句")
            encoded = text.encode('utf-8' if name == 'UTF8' else 'utf-16-le') + (b'\0' if name == 'UTF8' else b'\0\0')
            if len(encoded) > MAX_BUFFER:
                _fault("原生文本超过缓冲上限")
            # UTF-16 buffers have explicit 2-byte alignment even on non-Windows tests.
            storage = ((C.c_ubyte * len(encoded)) if name == 'UTF8' else (C.c_uint16 * (len(encoded) // 2))).from_buffer_copy(encoded)
            return NativeMemory(storage)
        if name == '缓冲':
            b = bind(['字节数'])
            size = _bounded(b['字节数'], 1, MAX_BUFFER, '缓冲大小')
            return NativeMemory((C.c_ubyte * size)())
        if name in ('系统库', '动态库'):
            b = bind(['路径'])
            path = b['路径']
            if not isinstance(path, str) or '\0' in path:
                _fault("动态库路径须为不含 NUL 的句")
            if name == '系统库':
                if not re.fullmatch(r'[A-Za-z0-9_-]+\.dll', path, re.IGNORECASE):
                    _fault("系统库只接受 DLL 文件名，并仅从 System32 加载")
                flags = 0x800  # LOAD_LIBRARY_SEARCH_SYSTEM32
            else:
                if not Path(path).is_absolute() or not Path(path).is_file():
                    _fault("动态库只接受现有文件的绝对路径；禁止隐式当前目录搜索")
                path = str(Path(path).resolve())
                flags = 0x100 | 0x800  # DLL_LOAD_DIR | SYSTEM32, no PATH/current directory
            return NativeLibrary(C.WinDLL(path, use_last_error=True, winmode=flags))
        if name == '签名':
            b = bind(['返回', '参数', '约定'])
            result = _expect(b['返回'], NativeType, "签名返回需要原生类型")
            if not isinstance(b['参数'], list) or len(b['参数']) > 64:
                _fault("签名参数须为不超过 64 项的阵")
            params = tuple(_expect(p, NativeType, "签名参数需要原生类型") for p in b['参数'])
            if result.kind == 'struct' or any(p.kind in ('struct', 'void') for p in params):
                _fault("首版不支持按值传递结构或无值参数；请显式传结构地址")
            if b['约定'] not in ('win64', 'cdecl'):
                _fault("调用约定只支持 win64 或 cdecl；不支持变参")
            return NativeSignature(result, params, b['约定'])
        if name == '回调':
            from .interpreter import Function
            b = bind(['签名', '算', '失败值'])
            signature = _expect(b['签名'], NativeSignature, "回调需要原生签名")
            function = b['算']
            if not isinstance(function, Function) or function.node.data['procedure'] or len(function.node.data['params']) != len(signature.params):
                _fault("回调需要与签名参数数量一致的如算")
            if function.owner._native_context is not context:
                _fault('如回调不能跨原生能力上下文注册')
            fallback = _marshal(signature.result, b['失败值'])
            if signature.result.kind == 'pointer' and fallback:
                _fault('指针回调失败值只支持空指针，避免关闭后返回失效地址')
            with _CALLBACK_LOCK:
                if len(_CALLBACK_TOMBSTONES) >= MAX_CALLBACKS:
                    _fault("本进程原生回调总数达到 1024 上限；关闭的安全占位也计入，请重启进程")
                callback = NativeCallback(context, owner, node, signature, function, fallback)
                _CALLBACK_TOMBSTONES.append(callback.trampoline)
                context.callbacks.add(callback)
            return callback
    elif isinstance(obj, NativeType):
        if name in ('大小', '对齐'):
            bind([])
            return float(obj.size if name == '大小' else obj.alignment)
        if name in ('值', '重释'):
            b = bind(['值'])
            return _convert(obj, b['值'], name == '重释')
        if name == '偏移':
            b = bind(['字段'])
            if obj.kind != 'struct' or b['字段'] not in dict(obj.fields):
                _fault("未知结构字段")
            return float(getattr(obj.ctype, b['字段']).offset)
        if name == '新建':
            bind([])
            if obj.kind != 'struct':
                _fault("新建只适用于结构描述符")
            return NativeMemory(obj.ctype(), obj)
    elif isinstance(obj, NativeScalar):
        _check_anchors(obj)
        if name in ('数', '句', '为空'):
            bind([])
            if name == '句':
                return str(obj.value)
            if name == '为空':
                return obj.value == 0
            if obj.typ.kind in ('int', 'pointer') and abs(obj.value) > SAFE_INTEGER:
                _fault("原生整数超出数的安全整数范围；请用其句或保持原生值")
            return float(obj.value)
        if name == '位段':
            b = bind(['起', '宽'])
            if obj.typ.kind not in ('int', 'pointer'):
                _fault("位段只支持原生整数或指针")
            start = _bounded(b['起'], 0, obj.typ.bits - 1, '位段起点')
            width = _bounded(b['宽'], 1, min(53, obj.typ.bits - start), '位段宽度')
            return float((obj.value >> start) & ((1 << width) - 1))
    elif isinstance(obj, NativeMemory):
        if name == '关闭':
            bind([])
            obj.closed = True
            if obj.parent is None:
                obj.pins.clear()
            return None
        obj.check()
        if name == '大小':
            bind([])
            return float(obj.size)
        if name == '地址':
            bind([])
            return NativeScalar(PRIMITIVES['指针'], obj.address, (obj,))
        if name in ('解UTF8', '解UTF16'):
            bind([])
            raw = bytes(obj.storage)
            if name == '解UTF8':
                at = raw.find(b'\0')
                if at < 0:
                    _fault("UTF8 缓冲缺少界内 NUL 终止符")
                return raw[:at].decode('utf-8', 'strict')
            if len(raw) % 2:
                _fault("UTF16 缓冲字节数须为偶数")
            at = next((i for i in range(0, len(raw), 2) if raw[i:i+2] == b'\0\0'), -1)
            if at < 0:
                _fault("UTF16 缓冲缺少界内 NUL 终止符")
            return raw[:at].decode('utf-16-le', 'strict')
        if name in ('读', '写'):
            b = bind(['字段'] if name == '读' else ['字段', '值'])
            fields = dict(obj.typ.fields) if obj.typ else {}
            if b['字段'] not in fields:
                _fault("未知结构字段；不支持解引用外部指针")
            key, typ = b['字段'], fields[b['字段']]
            if name == '读':
                raw = getattr(obj.storage, key)
                if typ.kind == 'struct':
                    return NativeMemory(raw, typ, obj, obj.prefix + (key,))
                pin_key = obj.prefix + (key,)
                anchors = (obj.pins[pin_key],) if pin_key in obj.pins else ()
                return NativeScalar(typ, 0 if raw is None else raw, anchors)
            if typ.kind == 'struct':
                value = _expect(b['值'], NativeMemory, "嵌套结构写入需要同类型缓冲")
                value.check()
                if value.typ is not typ:
                    _fault("嵌套结构类型不匹配")
                # Copy both bytes and a snapshot of pointer ownership. A later
                # write to the source must not drop anchors of the copied bytes.
                prefix = obj.prefix + (key,)
                copied_pins = {prefix + path[len(value.prefix):]: anchor for path, anchor in value.pins.items()
                               if path[:len(value.prefix)] == value.prefix}
                setattr(obj.storage, key, value.storage)
                for path in list(obj.pins):
                    if path[:len(prefix)] == prefix:
                        del obj.pins[path]
                obj.pins.update(copied_pins)
            else:
                setattr(obj.storage, key, _marshal(typ, b['值']))
                obj.pins[obj.prefix + (key,)] = b['值']
            return obj
    elif isinstance(obj, NativeLibrary):
        if name == '关闭':
            bind([])
            obj.closed = True  # Deliberately no FreeLibrary or unsafe unload.
            return None
        obj.check()
        if name == '绑定':
            b = bind(['名称', '签名'])
            symbol = b['名称']
            signature = _expect(b['签名'], NativeSignature, "绑定需要原生签名")
            if not isinstance(symbol, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_@?]*', symbol):
                _fault("原生符号名须为有效 ASCII 名称；不支持序号绑定")
            try:
                function = signature.prototype()((symbol, obj.handle))
            except AttributeError:
                _fault("动态库没有导出符号：" + symbol)
            return NativeFunction(obj, signature, function)
    elif isinstance(obj, NativeFunction):
        if name == '调用':
            b = bind(['参数'])
            return _invoke(context, obj, b['参数'])
    elif isinstance(obj, NativeOutcome):
        bind([])
        if name == '值':
            return obj.value
        if name == '错误码':
            return float(obj.error_code)
        if name == '回调错误':
            return obj.callback_error
    elif isinstance(obj, NativeCallback):
        if name == '关闭':
            bind([])
            obj.close()
            return None
        if obj.closed:
            _fault("原生回调已关闭")
        if name == '地址':
            bind([])
            return NativeScalar(PRIMITIVES['指针'], C.cast(obj.trampoline, C.c_void_p).value, (obj,))
        if name == '失败时':
            b = bind(['函数', '参数'])
            function = _expect(b['函数'], NativeFunction, "回调失败动作需要原生绑定函数")
            if not isinstance(b['参数'], list) or len(b['参数']) != len(function.signature.params):
                _fault("回调失败动作实参数量与签名不符")
            for typ, value in zip(function.signature.params, b['参数']):
                _marshal(typ, value)
            obj.failure_hook = (function, list(b['参数']))
            return obj
    _fault("未知原生成员：" + name)


def _native_nodes(value):
    """Detect native references even in dormant declarations and local aliases."""
    if isinstance(value, Node):
        if (value.kind == 'import' and native_import(value.data.get('path'), value.data.get('resolved'))) or (value.kind in ('name', 'call') and value.data.get('name') == '__密'):
            yield value
        for child in value.data.values():
            yield from _native_nodes(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _native_nodes(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _native_nodes(child)


def reject_native_backend(program):
    for node in _native_nodes(program):
        raise RuError('如:密／如见只支持显式开启原生能力的本地 Windows x64 Python 解释器；C、Node.js 和浏览器后端不支持', node.token.line, node.token.col, '能力错误')
