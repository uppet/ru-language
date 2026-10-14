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

MAX_SAVE_DEPTH = 64
MAX_CLIPS = 32
IDENTITY = (1, 0, 0, 1, 0, 0)
MAX_COMMANDS = 2048
MAX_FRAME_BYTES = 262144
MAX_CALLBACK_LINES = 500000
MAX_CALLBACK_SECONDS = 1.0
MAX_GRAPHICS_MEMORY = 64 * 1024 * 1024
_COLOR = re.compile(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?\Z")
_TEXT_ALIGNS = MappingProxyType({"左": "left", "中": "center", "右": "right"})
_TEXT_BASELINES = MappingProxyType({"上": "top", "中": "middle", "下": "bottom", "基线": "alphabetic"})
_TYPES = None
EVENT_PARAMS = {"frame": ("每帧", ["帧"]), "mouse_down": ("鼠标按下", ["横", "纵", "键"]),
                "mouse_up": ("鼠标松开", ["横", "纵", "键"]),
                "mouse_move": ("鼠标移动", ["横", "纵"]),
                "key_down": ("按键", ["键"]), "key_up": ("松键", ["键"])}
CALLBACK_NAMES = {name: kind for kind, (name, _) in EVENT_PARAMS.items()}


CANVAS_PARAMS = MappingProxyType({"背景": ("色",), "填色": ("色",), "描边": ("色",), "线宽": ("粗",), "字号": ("大小",), "文字对齐": ("横向", "纵向"),
              "矩形": ("横", "纵", "宽", "高"), "椭圆": ("横", "纵", "宽", "高"),
              "弧": ("横", "纵", "宽", "高", "始角", "转角"),
              "扇形": ("横", "纵", "宽", "高", "始角", "转角"),
              "线": ("横一", "纵一", "横二", "纵二"), "文字": ("文", "横", "纵"),
              "三角形": ("横一", "纵一", "横二", "纵二", "横三", "纵三"), "多边形": ("点阵",), "折线": ("点阵",),
              "平移": ("横", "纵"), "旋转": ("弧度",), "缩放": ("横倍率", "纵倍率"),
              "保存": (), "恢复": (), "变换": ("a", "b", "c", "d", "e", "f"), "重置变换": (),
              "裁剪": ("横", "纵", "宽", "高"), "取消裁剪": (),
              "帧率": ("率",), "停": (), "继续": (), "关闭": (), "宽": (), "高": (), "帧": (),
              "经过秒": (), "间隔秒": (),
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
    def __init__(self, host, width, height, origin):
        self.host, self.width, self.height = host, width, height
        self.id = secrets.token_hex(16)
        self.callbacks = {}
        self.commands = []
        self.command_bytes = 2
        self.fill, self.stroke = "#4677ff", "#202530"
        self.line_width, self.text_size = 1, 16
        self.text_align, self.text_baseline = "left", "top"
        self.fps, self.frame = 30, 0
        self.running, self.closed = False, False
        self._origin = origin
        self._previous_frame = None
        self._elapsed, self._delta = 0.0, 0.0
        self.dirty = True
        self.reset_geometry()

    def set_running(self, running):
        if running and not self.running:
            self._previous_frame = None
        self.running = running

    def reset_geometry(self):
        self.transform, self.clips, self.stack = IDENTITY, (), []

    def check_balanced(self):
        if self.stack:
            self.host.close()
            raise RuError("如观保存与恢复须成对；尚有未恢复的状态，已关闭交互", category="运行错误")

    def compose(self, matrix, fail):
        a, b, c, d, e, f = self.transform
        g, h, i, j, k, l = matrix
        result = (a*g+c*h, b*g+d*h, a*i+c*j, b*i+d*j, a*k+c*l+e, b*k+d*l+f)
        if any(not math.isfinite(value) or abs(value) > 100000 for value in result):
            fail("如观累积变换须为绝对值不超过 100000 的有限数")
        self.transform = result

    def close(self):
        if self.closed:
            return
        self.closed, self.running = True, False
        self.callbacks.clear()
        self.commands.clear()
        self.reset_geometry()
        self.host.emit({"type": "graphics_closed", "canvas_id": self.id})
        if self.host.canvas is self:
            self.host.canvas = None

    def command(self, command, fail):
        if command["op"] != "background":
            if self.transform != IDENTITY:
                command["transform"] = list(self.transform)
            if self.clips:
                command["clips"] = [dict(clip, transform=list(clip["transform"])) for clip in self.clips]
        size = len(json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
        if len(self.commands) >= MAX_COMMANDS or self.command_bytes + size > MAX_FRAME_BYTES - 1024:
            fail("如观每帧最多 2048 个绘制命令、256 KiB 数据；请减少图形或文字")
        self.commands.append(command)
        self.command_bytes += size
        self.dirty = True


class GraphicsHost:
    def __init__(self, interpreter, emit, *, now_seconds=None):
        self.interpreter, self.emit = interpreter, emit
        self.canvas = None
        self.memory_start = 0
        self.owns_tracing = False
        # This host-only hook never enters Ru or the event protocol. Capture the
        # default separately: callback budget checks keep reading their live clock.
        self._now_seconds = time.monotonic if now_seconds is None else now_seconds
        self._last_clock_sample = None
        interpreter.graphics_host = self

    def _sample_time(self, *, close_on_error=True):
        try:
            sample = self._now_seconds()
            if isinstance(sample, bool) or not isinstance(sample, (int, float)):
                raise ValueError
            sample = float(sample)
            if (not math.isfinite(sample) or sample < 0
                    or self._last_clock_sample is not None and sample < self._last_clock_sample):
                raise ValueError
        except Exception:
            if close_on_error:
                self.close()
            raise RuError("如观宿主单调时钟无效；请重新运行", category="运行错误") from None
        self._last_clock_sample = sample
        return sample

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
        origin = self._sample_time(close_on_error=False)
        self.close()
        if not tracemalloc.is_tracing():
            tracemalloc.start(1)
            self.owns_tracing = True
        self.memory_start = tracemalloc.get_traced_memory()[0]
        self.canvas = Canvas(self, width, height, origin)
        instance = Instance(_TYPES["canvas"], {})
        instance.graphics_canvas = self.canvas
        return instance

    def flush(self):
        canvas = self.canvas
        if canvas:
            canvas.check_balanced()
        if canvas and canvas.dirty:
            event = dict(self.snapshot(), type="graphics", commands=list(canvas.commands))
            self.emit(event)
            canvas.dirty = False

    def handle(self, event, *, canvas_id=None):
        canvas = self.canvas
        if canvas is None:
            raise RuError("如观画布已关闭", category="运行错误")
        if canvas_id is not None and canvas_id != canvas.id:
            raise RuError("如观事件已失效", category="运行错误")
        if (not isinstance(event, dict) or not isinstance(event.get("type"), str)
                or event["type"] not in (*EVENT_PARAMS, "close")):
            raise RuError("无效如观事件", category="运行错误")
        kind = event["type"]
        allowed = {"type"}
        if kind.startswith("mouse_"):
            allowed |= {"x", "y", "button"}
            for key in ("x", "y"):
                value = event.get(key)
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not -100000 <= value <= 100000 or not math.isfinite(value)):
                    raise RuError("无效如观鼠标坐标", category="运行错误")
            button = event.get("button", 0)
            if isinstance(button, bool) or not isinstance(button, int) or not 0 <= button <= 4:
                raise RuError("无效如观鼠标键", category="运行错误")
        elif kind.startswith("key_"):
            allowed.add("key")
            if not isinstance(event.get("key"), str) or len(event["key"]) > 64:
                raise RuError("无效如观按键", category="运行错误")
        if set(event) - allowed:
            raise RuError("如观事件含未知字段", category="运行错误")
        if kind == "close":
            self.close()
            return
        callback = canvas.callbacks.get(kind)
        if callback is None or (kind == "frame" and not canvas.running):
            raise RuError("如观事件未启用", category="运行错误")
        fn, node = callback
        now = self._sample_time()
        canvas._elapsed = now - canvas._origin
        canvas._delta = (now - canvas._previous_frame
                         if kind == "frame" and canvas._previous_frame is not None else 0.0)
        if kind == "frame":
            canvas._previous_frame = now
            canvas.frame += 1
            values = [float(canvas.frame)]
        elif kind.startswith("mouse"):
            values = [float(event["x"]), float(event["y"])]
            if kind != "mouse_move":
                values.append(float(event.get("button", 0)))
        else:
            values = [event["key"]]
        # Frames are complete scenes. Input callbacks can change style/data;
        # if they draw, their drawing replaces the previous scene as well.
        canvas.reset_geometry()
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
        callback_error = False
        try:
            sys.settrace(trace)
            self.interpreter.invoke_value(node, fn, [(None, value) for value in values])
            check()
            if self.canvas:
                self.canvas.check_balanced()
        except BaseException:
            callback_error = True
            self.close()
            raise
        finally:
            sys.settrace(old_trace)
            if old_limit is not None:
                try:
                    resource.setrlimit(resource.RLIMIT_AS, old_limit)
                except (OSError, ValueError):
                    # Some hosts permit lowering a soft limit but reject raising
                    # it again. Keep the protective ceiling, never hide the
                    # original callback error, and report an actionable failure.
                    self.close()
                    if not callback_error:
                        self.interpreter.fail(node, "如观无法恢复系统内存上限；保护性限制仍生效，已关闭交互，请重启会话")
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
            fail("颜色须为 #RRGGBB 或 #RRGGBBAA 文字" + ("，空表示不绘制" if optional else ""))
        return value.lower()
    if kind == "helpers":
        if name == "颜色":
            params = ("红", "绿", "蓝", "不透明度")
            bound = bind_arguments(name, args, params, fail)
            channels = [number(bound[key], key, 0, 255, True) for key in params]
            owner.last_member_procedure = False
            return True, "#" + "".join(f"{value:02x}" for value in channels)
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
    owner.last_member_procedure = name not in ("宽", "高", "帧", "经过秒", "间隔秒")
    if name in CALLBACK_NAMES:
        fn = bound["回调"]
        event = CALLBACK_NAMES[name]
        if not isinstance(fn, Function) or len(fn.node.data["params"]) != len(EVENT_PARAMS[event][1]):
            fail(name + "需要接受 " + str(len(EVENT_PARAMS[event][1])) + " 个参数的算／作回调")
        canvas.callbacks[event] = fn, n
        if event == "frame":
            canvas.set_running(True)
    elif name in ("宽", "高", "帧"):
        return True, float({"宽": canvas.width, "高": canvas.height, "帧": canvas.frame}[name])
    elif name in ("经过秒", "间隔秒"):
        return True, canvas._elapsed if name == "经过秒" else canvas._delta
    elif name == "关闭":
        # Explicit close is cleanup and may discard an unfinished saved state.
        canvas.stack.clear()
        canvas.host.flush()
        canvas.host.close()
    elif name in ("停", "继续"):
        canvas.set_running(name == "继续" and "frame" in canvas.callbacks)
    elif name == "帧率":
        canvas.fps = number(bound["率"], "帧率", 1, 30, True)
    elif name in ("填色", "描边"):
        setattr(canvas, "fill" if name == "填色" else "stroke", color(bound["色"], True))
    elif name in ("线宽", "字号"):
        setattr(canvas, "line_width" if name == "线宽" else "text_size", number(next(iter(bound.values())), name, 1, 256))
    elif name == "文字对齐":
        horizontal, vertical = bound["横向"], bound["纵向"]
        if not isinstance(horizontal, str) or horizontal not in _TEXT_ALIGNS:
            fail("文字对齐横向须为 '左'、'中' 或 '右' 的句")
        if not isinstance(vertical, str) or vertical not in _TEXT_BASELINES:
            fail("文字对齐纵向须为 '上'、'中'、'下' 或 '基线' 的句")
        # Validate both arguments before changing either persistent style.
        canvas.text_align, canvas.text_baseline = _TEXT_ALIGNS[horizontal], _TEXT_BASELINES[vertical]
    elif name == "保存":
        if len(canvas.stack) >= MAX_SAVE_DEPTH:
            fail("如观最多保存 64 层状态")
        canvas.stack.append((canvas.fill, canvas.stroke, canvas.line_width, canvas.text_size,
                             canvas.text_align, canvas.text_baseline,
                             canvas.transform, canvas.clips))
    elif name == "恢复":
        if not canvas.stack:
            fail("如观恢复没有对应的保存")
        (canvas.fill, canvas.stroke, canvas.line_width, canvas.text_size,
         canvas.text_align, canvas.text_baseline, canvas.transform, canvas.clips) = canvas.stack.pop()
    elif name == "重置变换":
        canvas.transform = IDENTITY
    elif name == "取消裁剪":
        canvas.clips = ()
    elif name in ("平移", "旋转", "缩放", "变换"):
        values = [number(bound[key], key) for key in params[name]]
        if name == "平移":
            matrix = (1, 0, 0, 1, *values)
        elif name == "旋转":
            cosine, sine = math.cos(values[0]), math.sin(values[0])
            matrix = (cosine, sine, -sine, cosine, 0, 0)
        elif name == "缩放":
            matrix = (values[0], 0, 0, values[1], 0, 0)
        else:
            matrix = values
        canvas.compose(matrix, fail)
    elif name == "裁剪":
        if len(canvas.clips) >= MAX_CLIPS:
            fail("如观最多叠加 32 个裁剪区域")
        clip = {"x": number(bound["横"], "横"), "y": number(bound["纵"], "纵"),
                "width": number(bound["宽"], "宽", 0), "height": number(bound["高"], "高", 0),
                "transform": canvas.transform}
        canvas.clips += (clip,)
    elif name in ("三角形", "多边形", "折线"):
        if name == "三角形":
            values = [number(bound[key], key) for key in params[name]]
            points = [values[index:index+2] for index in range(0, 6, 2)]
        else:
            source = bound["点阵"]
            minimum = 2 if name == "折线" else 3
            if not isinstance(source, list) or not minimum <= len(source) <= 256:
                fail(name + f"点阵须为包含 {minimum} 至 256 个点的阵")
            points = []
            for point in source:
                if not isinstance(point, list) or len(point) != 2:
                    fail(name + "每个点须为恰含两个坐标的阵")
                points.append([number(point[0], "横坐标"), number(point[1], "纵坐标")])
        canvas.command({"op": "polyline" if name == "折线" else "polygon", "points": points,
                        "fill": "" if name == "折线" else canvas.fill,
                        "stroke": canvas.stroke, "stroke_width": canvas.line_width}, fail)
    elif name == "背景":
        background = color(bound["色"])
        # A new background makes preceding drawing invisible; release it only
        # after validation so a caught argument error cannot erase the scene.
        canvas.commands, canvas.command_bytes = [], 2
        canvas.command({"op": "background", "color": background}, fail)
    elif name in ("弧", "扇形"):
        # Keep signed angles and even invisible/zero-sweep commands. A drawing
        # call still replaces the scene in an input callback and spends budget.
        x, y = number(bound["横"], "横"), number(bound["纵"], "纵")
        width, height = number(bound["宽"], "宽", 0), number(bound["高"], "高", 0)
        start, sweep = number(bound["始角"], "始角"), number(bound["转角"], "转角")
        canvas.command({"op": "arc" if name == "弧" else "sector", "x": x, "y": y,
                        "width": width, "height": height, "start": start, "sweep": sweep,
                        "fill": "" if name == "弧" else canvas.fill, "stroke": canvas.stroke,
                        "stroke_width": canvas.line_width}, fail)
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
        command = {"op": "text", "x": number(bound["横"], "横"), "y": number(bound["纵"], "纵"),
                   "text": text, "color": canvas.fill, "size": canvas.text_size}
        # Missing fields are frozen left/top defaults, including in old scenes.
        if canvas.text_align != "left":
            command["align"] = canvas.text_align
        if canvas.text_baseline != "top":
            command["baseline"] = canvas.text_baseline
        canvas.command(command, fail)
    canvas.dirty = True
    return True, None
