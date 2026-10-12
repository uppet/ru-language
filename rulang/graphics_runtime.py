"""Bounded, declarative 2D graphics for the persistent Rushu interpreter.

No browser code, network, image loading or host object is exposed to Ru. The
host retains real Ru Function values; the ordinary interpreter owns closures.
This is resource accounting for trusted local code, not a security sandbox.
"""
import json
import math
import re
import secrets
import sys
import time
import tracemalloc
from types import MappingProxyType

from .frontend import Node, Token, RuError, bind_arguments
from .contest_runtime import _BUILTIN_OWNER

MAX_COMMANDS = 2048
MAX_FRAME_BYTES = 262144
MAX_CALLBACK_LINES = 500000
MAX_CALLBACK_SECONDS = 1.0
MAX_GRAPHICS_MEMORY = 64 * 1024 * 1024
_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
_TYPES = None
EVENT_PARAMS = {"frame": ("每帧", ["帧"]), "mouse_down": ("鼠标按下", ["横", "纵", "键"]),
                "mouse_up": ("鼠标松开", ["横", "纵", "键"]),
                "mouse_move": ("鼠标移动", ["横", "纵"]),
                "key_down": ("按键", ["键"]), "key_up": ("松键", ["键"])}
CALLBACK_NAMES = {name: kind for kind, (name, _) in EVENT_PARAMS.items()}


CANVAS_PARAMS = MappingProxyType({"背景": ("色",), "填色": ("色",), "描边": ("色",), "线宽": ("粗",), "字号": ("大小",),
              "矩形": ("横", "纵", "宽", "高"), "椭圆": ("横", "纵", "宽", "高"),
              "线": ("横一", "纵一", "横二", "纵二"), "文字": ("文", "横", "纵"),
              "帧率": ("率",), "停": (), "继续": (), "关闭": (), "宽": (), "高": (), "帧": (),
              **{key: ("回调",) for key in CALLBACK_NAMES}})

def install_graphics(owner):
    from .interpreter import Instance, RuType, Scope
    global _TYPES
    if _TYPES is None:
        _TYPES = {}
        for kind, name in (("helpers", "如观工具"), ("canvas", "如观画布")):
            node = Node("type", Token("IDENT", name, 0, 0),
                        {"name": name, "parent": None, "fields": [], "methods": []})
            typ = RuType(_BUILTIN_OWNER, node, fields={}, methods={}, state=2)
            typ.graphics_kind = kind
            _TYPES[kind] = typ
    parent = Scope(owner.global_scope.parent)
    parent.values["__如观"] = Instance(_TYPES["helpers"], {})
    owner.global_scope.parent = parent
    owner.graphics_host = None


class Canvas:
    def __init__(self, host, width, height):
        self.host, self.width, self.height = host, width, height
        self.id = secrets.token_hex(16)
        self.callbacks = {}
        self.commands = []
        self.command_bytes = 2
        self.fill, self.stroke = "#4677ff", "#202530"
        self.line_width, self.text_size = 1, 16
        self.fps, self.frame = 30, 0
        self.running, self.closed = False, False
        self.dirty = True

    def close(self):
        if self.closed:
            return
        self.closed, self.running = True, False
        self.callbacks.clear()
        self.commands.clear()
        self.host.emit({"type": "graphics_closed", "canvas_id": self.id})
        if self.host.canvas is self:
            self.host.canvas = None

    def command(self, command, fail):
        size = len(json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
        if len(self.commands) >= MAX_COMMANDS or self.command_bytes + size > MAX_FRAME_BYTES - 1024:
            fail("如观每帧最多 2048 个绘制命令、256 KiB 数据；请减少图形或文字")
        self.commands.append(command)
        self.command_bytes += size
        self.dirty = True


class GraphicsHost:
    def __init__(self, interpreter, emit):
        self.interpreter, self.emit = interpreter, emit
        self.canvas = None
        self.memory_start = 0
        self.owns_tracing = False
        interpreter.graphics_host = self

    @property
    def canvas_id(self):
        return self.canvas.id if self.canvas else None

    @property
    def active(self):
        return self.canvas is not None

    def snapshot(self):
        canvas = self.canvas
        if not canvas:
            return None
        return {"canvas_id": canvas.id, "width": canvas.width, "height": canvas.height,
                "fps": canvas.fps, "running": canvas.running, "handlers": list(canvas.callbacks)}

    def close(self):
        if self.canvas:
            self.canvas.close()
        if self.owns_tracing:
            tracemalloc.stop()
            self.owns_tracing = False

    def begin_execution(self):
        self.close()

    def create(self, width, height):
        from .interpreter import Instance
        self.close()
        if not tracemalloc.is_tracing():
            tracemalloc.start(1)
            self.owns_tracing = True
        self.memory_start = tracemalloc.get_traced_memory()[0]
        self.canvas = Canvas(self, width, height)
        instance = Instance(_TYPES["canvas"], {})
        instance.graphics_canvas = self.canvas
        return instance

    def flush(self):
        canvas = self.canvas
        if canvas and canvas.dirty:
            event = dict(self.snapshot(), type="graphics", commands=list(canvas.commands))
            self.emit(event)
            canvas.dirty = False

    def handle(self, event):
        canvas = self.canvas
        if canvas is None:
            raise RuError("如观画布已关闭", category="运行错误")
        kind = event["type"]
        if kind == "close":
            self.close()
            return
        callback = canvas.callbacks.get(kind)
        if callback is None or (kind == "frame" and not canvas.running):
            raise RuError("如观事件未启用", category="运行错误")
        fn, node = callback
        if kind == "frame":
            canvas.frame += 1
            values = [float(canvas.frame)]
        elif kind.startswith("mouse"):
            values = [float(event["x"]), float(event["y"])]
            if kind != "mouse_move":
                values.append(float(event["button"]))
        else:
            values = [event["key"]]
        # Frames are complete scenes. Input callbacks can change style/data;
        # if they draw, their drawing replaces the previous scene as well.
        previous = canvas.commands
        previous_bytes = canvas.command_bytes
        canvas.commands, canvas.command_bytes = [], 2
        deadline, lines = time.monotonic() + MAX_CALLBACK_SECONDS, 0
        remaining = 128
        def check():
            if lines + (128 - remaining) > MAX_CALLBACK_LINES or time.monotonic() > deadline:
                self.interpreter.fail(node, "如观回调超过 1 秒或 500000 行执行预算；已关闭交互，请简化回调后重跑")
            if tracemalloc.get_traced_memory()[0] - self.memory_start > MAX_GRAPHICS_MEMORY:
                self.interpreter.fail(node, "如观新增内存超过 64 MiB；已关闭交互，请减少数据后重跑")
        def trace(frame, action, arg):
            nonlocal lines, remaining
            if action == "line":
                # Keep the exact line budget and 128-line check cadence, but
                # use cached small integers between checks. This avoids one
                # allocation per traced line while tracemalloc is active.
                remaining -= 1
                if remaining == 0:
                    lines += 128
                    remaining = 128
                    check()
            return trace
        old_trace = sys.gettrace()
        old_limit = None
        # A single host operation may allocate before Python's next trace line.
        # POSIX's address-space ceiling complements the portable allocation
        # budget. Restore the caller's setting after this callback.
        try:
            import resource
            if hasattr(resource, "RLIMIT_AS"):
                old_limit = resource.getrlimit(resource.RLIMIT_AS)
                finite = [value for value in old_limit if value != resource.RLIM_INFINITY]
                ceiling = min([512 * 1024 * 1024] + finite)
                resource.setrlimit(resource.RLIMIT_AS, (ceiling, old_limit[1]))
        except (ImportError, OSError, ValueError):
            old_limit = None
        try:
            sys.settrace(trace)
            self.interpreter.invoke_value(node, fn, [(None, value) for value in values])
            check()
        except BaseException:
            self.close()
            raise
        finally:
            sys.settrace(old_trace)
            if old_limit is not None:
                resource.setrlimit(resource.RLIMIT_AS, old_limit)
        if self.canvas is canvas:
            if not canvas.commands and kind != "frame":
                canvas.commands, canvas.command_bytes = previous, previous_bytes
            canvas.dirty = True
        self.flush()


def graphics_member(owner, n, receiver, name, args):
    from .interpreter import Instance, Function
    if not isinstance(receiver, Instance):
        return False, None
    kind = getattr(receiver.type, "graphics_kind", None)
    if kind is None:
        return False, None
    fail = lambda message: owner.fail(n, message)
    def number(value, label, low=-100000, high=100000, integer=False):
        if not isinstance(value, float) or not math.isfinite(value) or not low <= value <= high or (integer and value != int(value)):
            fail(label + "须为范围内" + ("整数" if integer else "有限数"))
        return int(value) if integer else value
    def color(value, optional=False):
        if optional and value is None:
            return ""
        if not isinstance(value, str) or not _COLOR.fullmatch(value):
            fail("颜色须为 #RRGGBB 文字" + ("，空表示不绘制" if optional else ""))
        return value.lower()
    if kind == "helpers":
        if name != "画布":
            fail("未知如观工具成员：" + name)
        bound = bind_arguments(name, args, ["宽", "高"], fail)
        width = number(bound["宽"], "宽", 1, 2048, True)
        height = number(bound["高"], "高", 1, 2048, True)
        if owner.graphics_host is None:
            fail("如观画布仅在如书 Python 会话中可用；命令行和 C／JavaScript 后端尚不支持图形")
        owner.last_member_procedure = False
        return True, owner.graphics_host.create(width, height)
    canvas = receiver.graphics_canvas
    if canvas.closed or canvas.host.canvas is not canvas:
        fail("如观画布已关闭；运行新代码格、停止或重启会话后，请重新创建画布")
    params = CANVAS_PARAMS
    if name not in params:
        fail("未知如观画布成员：" + name)
    bound = bind_arguments(name, args, params[name], fail)
    owner.last_member_procedure = name not in ("宽", "高", "帧")
    if name in CALLBACK_NAMES:
        fn = bound["回调"]
        event = CALLBACK_NAMES[name]
        if not isinstance(fn, Function) or len(fn.node.data["params"]) != len(EVENT_PARAMS[event][1]):
            fail(name + "需要接受 " + str(len(EVENT_PARAMS[event][1])) + " 个参数的算／作回调")
        canvas.callbacks[event] = fn, n
        if event == "frame":
            canvas.running = True
    elif name in ("宽", "高", "帧"):
        return True, float({"宽": canvas.width, "高": canvas.height, "帧": canvas.frame}[name])
    elif name == "关闭":
        canvas.host.flush()
        canvas.host.close()
    elif name in ("停", "继续"):
        canvas.running = name == "继续" and "frame" in canvas.callbacks
    elif name == "帧率":
        canvas.fps = number(bound["率"], "帧率", 1, 30, True)
    elif name in ("填色", "描边"):
        setattr(canvas, "fill" if name == "填色" else "stroke", color(bound["色"], True))
    elif name in ("线宽", "字号"):
        setattr(canvas, "line_width" if name == "线宽" else "text_size", number(next(iter(bound.values())), name, 1, 256))
    elif name == "背景":
        # A new background makes preceding drawing invisible; release it.
        canvas.commands, canvas.command_bytes = [], 2
        canvas.command({"op": "background", "color": color(bound["色"])}, fail)
    elif name in ("矩形", "椭圆"):
        x, y = number(bound["横"], "横"), number(bound["纵"], "纵")
        width, height = number(bound["宽"], "宽", 0), number(bound["高"], "高", 0)
        canvas.command({"op": "rect" if name == "矩形" else "ellipse", "x": x, "y": y,
                        "width": width, "height": height, "fill": canvas.fill, "stroke": canvas.stroke,
                        "stroke_width": canvas.line_width}, fail)
    elif name == "线":
        values = [number(bound[key], key) for key in params[name]]
        canvas.command(dict(zip(("x1", "y1", "x2", "y2"), values), op="line", color=canvas.stroke, width=canvas.line_width), fail)
    elif name == "文字":
        text = bound["文"]
        if not isinstance(text, str) or len(text) > 4096:
            fail("文字须为不超过 4096 字符的句")
        try:
            text.encode("utf-8")
        except UnicodeError:
            fail("文字须为有效 Unicode")
        canvas.command({"op": "text", "x": number(bound["横"], "横"), "y": number(bound["纵"], "纵"),
                        "text": text, "color": canvas.fill, "size": canvas.text_size}, fail)
    canvas.dirty = True
    return True, None
