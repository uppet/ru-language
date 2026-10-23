"""Bounded, declarative 2D graphics for the persistent Rushu interpreter.

No browser code, network, image loading or host object is exposed to Ru. The
host retains real Ru Function values; the ordinary interpreter owns closures.
This is resource accounting for trusted local code, not a security sandbox.
"""
import json
from collections import deque
from dataclasses import dataclass
import math
import os
import base64
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
MAX_IMAGES = 8
MAX_RESOURCE_PIXELS = 4194304
MAX_RESOURCE_BYTES = 131072
MAX_RECIPE_COMMANDS = MAX_COMMANDS - 1
MAX_CALLBACK_LINES = 500000
MAX_CALLBACK_SECONDS = 1.0
MAX_GRAPHICS_MEMORY = 64 * 1024 * 1024
MAX_IMAGE_FILE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_PIXELS = 4096 * 4096
MAX_FILE_LOAD_BYTES = 4 * 1024 * 1024
MAX_FILE_TEXT_BYTES = 8 * 1024 * 1024
MAX_LOAD_HANDLES = 64
MAX_SOURCE_CHARS = 512
MAX_LOAD_EVENTS_PER_FLUSH = 256
MAX_SERVICE_NAME_CHARS = 64
LOAD_MODES = frozenset(("文", "base64"))
ASYNC_EVENTS = frozenset(("image_ready", "image_failed", "file_ready", "file_failed"))
# 背景重置整帧绘制，但装载管理命令不是绘制：图请求／件请求／图释放须在
# 重置后存活（库可在铺排阶段先于背景发出它们）。
LOAD_MANAGEMENT_OPS = frozenset(("image_request", "file_request", "image_release"))
TEXT_EDIT_KEYS = frozenset(("退格", "删除", "左", "右", "上", "下", "家", "终", "回车", "空格", "跳格", "逃脱"))
MAX_PASTE_CHARS = 4096
MAX_COMPOSITION_CHARS = 256
_COLOR = re.compile(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?\Z")
_TEXT_ALIGNS = MappingProxyType({"左": "left", "中": "center", "右": "right"})
_TEXT_BASELINES = MappingProxyType({"上": "top", "中": "middle", "下": "bottom", "基线": "alphabetic"})
_TYPES = None
EVENT_PARAMS = {"frame": ("每帧", ["帧"]), "mouse_down": ("鼠标按下", ["横", "纵", "键"]),
                "mouse_up": ("鼠标松开", ["横", "纵", "键"]),
                "mouse_move": ("鼠标移动", ["横", "纵"]),
                "key_down": ("按键", ["键"]), "key_up": ("松键", ["键"]),
                "image_ready": ("图就绪", ["号", "宽", "高"]),
                "image_failed": ("图失败", ["号", "错"]),
                "file_ready": ("件就绪", ["号", "文"]),
                "file_failed": ("件失败", ["号", "错"]),
                "text_key": ("键按下", ["键"]), "text_char": ("字符", ["文"]),
                "text_paste": ("剪贴", ["文"]), "text_comp_start": ("组开始", []),
                "text_comp_update": ("组更新", ["组", "光标"]), "text_comp_end": ("组结束", ["文"]),
                "service_response": ("服务回", ["号", "成", "值", "误"]),
                "service_ad": ("服务告", ["表"])}
CALLBACK_NAMES = {name: kind for kind, (name, _) in EVENT_PARAMS.items()}


CANVAS_PARAMS = MappingProxyType({"背景": ("色",), "填色": ("色",), "描边": ("色",), "线宽": ("粗",), "字号": ("大小",), "文字对齐": ("横向", "纵向"),
              "矩形": ("横", "纵", "宽", "高"), "椭圆": ("横", "纵", "宽", "高"),
              "弧": ("横", "纵", "宽", "高", "始角", "转角"),
              "扇形": ("横", "纵", "宽", "高", "始角", "转角"),
              "贝塞尔": ("起横", "起纵", "控一横", "控一纵", "控二横", "控二纵", "终横", "终纵"),
              "线": ("横一", "纵一", "横二", "纵二"), "文字": ("文", "横", "纵"),
              "三角形": ("横一", "纵一", "横二", "纵二", "横三", "纵三"), "多边形": ("点阵",), "折线": ("点阵",),
              "平移": ("横", "纵"), "旋转": ("弧度",), "缩放": ("横倍率", "纵倍率"),
              "保存": (), "恢复": (), "变换": ("a", "b", "c", "d", "e", "f"), "重置变换": (),
              "裁剪": ("横", "纵", "宽", "高"), "取消裁剪": (),
              "缓存": ("宽", "高", "绘制"), "贴图": ("图像", "横", "纵"),
              "图请求": ("号", "源"), "绘图": ("号", "横", "纵", "宽", "高"),
              "图释放": ("号",), "件请求": ("号", "源", "式"),
              "服务请": ("号", "服务", "操作", "径", "文", "旗"),
              "入焦点": ("横", "纵", "宽", "高", "文", "标"), "入失焦": (),
              "入更新": ("文", "标"),
              "帧率": ("率",), "停": (), "继续": (), "关闭": (), "宽": (), "高": (), "帧": (),
              "字度": (), "测文": ("文",),
              "经过秒": (), "间隔秒": (),
              **{key: ("回调",) for key in CALLBACK_NAMES}})

def install_graphics(owner):
    from .interpreter import Instance, RuType, Scope
    global _TYPES
    if _TYPES is None:
        _TYPES = {}
        for kind, name in (("helpers", "如观工具"), ("canvas", "如观画布"),
                           ("recorder", "如观绘图目标"), ("image", "如观图像")):
            node = Node("type", Token("IDENT", name, 0, 0),
                        {"name": name, "parent": None, "fields": [], "methods": []})
            typ = RuType(_BUILTIN_OWNER, node, fields={}, methods={}, state=2)
            typ.graphics_kind = kind
            _TYPES[kind] = typ
    parent = Scope(owner.global_scope.parent)
    parent.values["__如观"] = Instance(_TYPES["helpers"], {})
    owner.global_scope.parent = parent
    owner.graphics_host = None


READ_MEMBERS = frozenset(("宽", "高", "帧", "经过秒", "间隔秒", "字度", "测文"))
RECORDER_MEMBERS = frozenset(CANVAS_PARAMS) - frozenset(CALLBACK_NAMES) - {
    "缓存", "贴图", "帧率", "停", "继续", "关闭", "帧", "经过秒", "间隔秒",
    "图请求", "绘图", "图释放", "件请求", "服务请", "入焦点", "入失焦", "入更新",
    "字度", "测文"}

# 缺省字度（号的倍数）：与如UI 早期近似度量逐位一致，保证不注入时行为不变。
_DEFAULT_TEXT_METRICS = {"全": 1.0, "半": 0.56, "行": 1.5}


def _measure_text(canvas, text, fail):
    """机 其 测文：宿主实测钩优先，否则按字度逐码点回退（半角＝码点 < 一）。"""
    size = canvas.text_size
    measurer = canvas.host.text_measurer
    if measurer is not None:
        width = measurer(text, size)
        if (isinstance(width, bool) or not isinstance(width, (int, float))
                or not math.isfinite(width) or not 0 <= width <= 10000000):
            fail("如观测文宿主返回无效宽度")
        return float(width)
    half, full = canvas.metrics["半"], canvas.metrics["全"]
    return float(sum(half if ord(char) < 0x4E00 else full for char in text) * size)


def _address_space_used():
    """Current virtual address space in bytes, or 0 when unmeasurable."""
    try:
        with open("/proc/self/status", encoding="ascii") as status:
            for line in status:
                if line.startswith("VmSize:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


_ADDRESS_SPACE_LIMIT_ENV = "RULANG_ADDRESS_SPACE_LIMIT"
_LIMIT_SUFFIXES = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}


def _parse_limit_bytes(text):
    """Parse '1048576'／'512M'／'2G' style byte counts (binary suffixes)."""
    match = re.fullmatch(r"\s*(\d+)\s*([A-Za-z]{0,3})\s*", text)
    if not match:
        raise RuError(f"无法解析地址空间上限 {text!r}；示例：512M、2G、1048576", category="能力错误")
    suffix = match.group(2).upper()
    suffix = {"B": "", "KB": "K", "MB": "M", "GB": "G", "KIB": "K", "MIB": "M", "GIB": "G"}.get(suffix, suffix)
    if suffix not in _LIMIT_SUFFIXES:
        raise RuError(f"无法解析地址空间上限 {text!r}；后缀只支持 K／M／G", category="能力错误")
    return int(match.group(1)) * _LIMIT_SUFFIXES[suffix]


def install_address_space_limit(limit_bytes=None):
    """Set a permanent session address-space quota (POSIX ``RLIMIT_AS``).

    Session spawners run one isolated process per session and call this once
    at startup, or set ``RULANG_ADDRESS_SPACE_LIMIT`` (e.g. ``1G``) in its
    environment. The quota covers the whole session process and cannot be
    raised afterwards; exhausting it terminates the session instead of the
    host application. ``GraphicsHost`` callbacks never tighten the process
    limit: their guard is the portable time／line／allocation budget only.
    Returns the quota in bytes, or None when neither argument nor
    environment configures one (a no-op).
    """
    if limit_bytes is None:
        raw = os.environ.get(_ADDRESS_SPACE_LIMIT_ENV)
        if raw is None:
            return None
        limit_bytes = _parse_limit_bytes(raw)
    if isinstance(limit_bytes, bool) or not isinstance(limit_bytes, int) or limit_bytes <= 0:
        raise RuError("地址空间上限须为正整数字节数", category="能力错误")
    try:
        import resource
    except ImportError:
        resource = None
    if resource is None or not hasattr(resource, "RLIMIT_AS"):
        raise RuError("地址空间上限仅在支持 RLIMIT_AS 的 POSIX 系统可用；Windows 会话请改用 Job Object 等进程级机制", category="能力错误")
    used = _address_space_used()
    if used and used >= limit_bytes:
        raise RuError(f"当前进程地址空间约 {used // 1024 // 1024} MiB，已高于请求的上限 {limit_bytes // 1024 // 1024} MiB；请调大配额或先排查异常内存映射", category="能力错误")
    resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
    return limit_bytes


def memory_protection_status():
    """Report which memory-protection tier this process actually has.

    Hosts surface this so users see the real boundary instead of an assumed
    one: either a POSIX ``RLIMIT_AS`` quota configured at session startup,
    or an explicit degraded note (external cgroup／Windows Job Object, or
    RSS 预警 which cannot stop a single large allocation). The portable
    callback budgets are always active regardless.
    """
    try:
        import resource
    except ImportError:
        resource = None
    if resource is None or not hasattr(resource, "RLIMIT_AS"):
        return {"mechanism": None, "quota_bytes": None, "cooperative_budgets": True,
                "degraded": True,
                "detail": "无 POSIX RLIMIT_AS；进程级内存边界请用 Windows Job Object 或 cgroup 配置，"
                          "RSS 轮询只能预警，挡不住瞬时大分配"}
    soft, _hard = resource.getrlimit(resource.RLIMIT_AS)
    if soft != resource.RLIM_INFINITY:
        return {"mechanism": "rlimit_as", "quota_bytes": soft, "cooperative_budgets": True,
                "degraded": False,
                "detail": "POSIX RLIMIT_AS 地址空间配额全程生效；耗尽会终止本会话进程"}
    return {"mechanism": None, "quota_bytes": None, "cooperative_budgets": True,
            "degraded": True,
            "detail": "RLIMIT_AS 未配置；当前只有回调级合作式预算与硬看门狗。"
                      "建议会话启动时设置 RULANG_ADDRESS_SPACE_LIMIT，"
                      "或由外部 cgroup／Job Object 负责进程级配额"}


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _image_head_size(data):
    """Read pixel dimensions from PNG/JPEG headers without decoding."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        if width > 0 and height > 0:
            return width, height
        raise RuError("图像尺寸无效", category="用法错误")
    if data[:2] == b"\xff\xd8":
        index = 2
        while index + 9 <= len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height = int.from_bytes(data[index + 5:index + 7], "big")
                width = int.from_bytes(data[index + 7:index + 9], "big")
                if width > 0 and height > 0:
                    return width, height
                raise RuError("图像尺寸无效", category="用法错误")
            segment = int.from_bytes(data[index + 2:index + 4], "big")
            if segment < 2:
                break
            index += 2 + segment
    raise RuError("不识别的图像格式", category="用法错误")


@dataclass(frozen=True, slots=True)
class ImageHandle:
    owner: object
    token: object
    resource_id: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class DrawingResource:
    # Immutable serialized recipe; escaped language values never own its data.
    definition: str
    count: int
    pixels: int

    @property
    def byte_size(self):
        return len(self.definition.encode("utf-8"))


class Canvas:
    def __init__(self, host, width, height, origin):
        self.host, self.width, self.height = host, width, height
        self.id = secrets.token_hex(16)
        self.callbacks = {}
        self.token = object()
        self.resources = {}
        self.resource_bytes = 2
        self.resource_pixels = 0
        self.commands = []
        self.command_bytes = 2
        self.fill, self.stroke = "#4677ff", "#202530"
        self.line_width, self.text_size = 1, 16
        self.text_align, self.text_baseline = "left", "top"
        self.fps, self.frame = 30, 0
        self.metrics = dict(_DEFAULT_TEXT_METRICS)
        self.running, self.closed = False, False
        self.image_loads = set()
        self.file_loads = set()
        self.load_started = set()
        self.load_done = set()
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
        self.resources.clear()
        self.resource_bytes, self.resource_pixels = 2, 0
        self.commands.clear()
        self.image_loads.clear()
        self.file_loads.clear()
        self.load_started.clear()
        self.load_done.clear()
        self.reset_geometry()
        self.host.emit({"type": "graphics_closed", "canvas_id": self.id})
        if self.host.canvas is self:
            self.host.canvas = None

    def scene(self, commands=None):
        commands = self.commands if commands is None else commands
        event = {"canvas_id": self.id, "width": self.width, "height": self.height,
                 "fps": self.fps, "running": self.running, "handlers": list(self.callbacks),
                 "type": "graphics", "commands": list(commands)}
        refs = dict.fromkeys(command["resource"] for command in commands if command["op"] == "image")
        if refs:
            event["resources"] = [json.loads(self.resources[key].definition) for key in refs]
        return event

    def command(self, command, fail):
        if command["op"] != "background":
            if self.transform != IDENTITY:
                command["transform"] = list(self.transform)
            if self.clips:
                command["clips"] = [dict(clip, transform=list(clip["transform"])) for clip in self.clips]
        size = len(json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
        if len(self.commands) >= MAX_COMMANDS or self.command_bytes + size > MAX_FRAME_BYTES - 1024:
            fail("如观每帧最多 2048 个绘制命令、256 KiB 数据；请减少图形或文字")
        refs = ({item["resource"] for item in self.commands if item["op"] == "image"}
                if self.resources else set())
        if command["op"] == "image":
            refs.add(command["resource"])
        if len(self.commands) + 1 + sum(self.resources[key].count for key in refs) > MAX_COMMANDS:
            fail("如观每帧根命令与引用缓存配方合计最多 2048 个命令")
        if refs:
            # Account exact serialized boundaries without decoding/copying every
            # cached recipe again for each dynamic primitive in a warm frame.
            frame_size = len(_json(self.scene([])).encode("utf-8")) + self.command_bytes + size - 3
            frame_size += len(',"resources":') + 2 + len(refs) - 1
            frame_size += sum(self.resources[key].byte_size for key in refs)
            if frame_size > MAX_FRAME_BYTES:
                fail("如观完整绘图帧超过 256 KiB UTF-8 数据；请减少图形或文字")
        self.commands.append(command)
        self.command_bytes += size
        self.dirty = True


class DrawingRecorder(Canvas):
    """A short-lived drawing target, never installed as the host's canvas."""
    def __init__(self, host, width, height, resource_id, owner):
        super().__init__(host, width, height, 0)
        self.resource_id, self.owner = resource_id, owner
        self.definition_overhead = len(self.definition([]).encode("utf-8"))

    def definition(self, commands=None):
        return _json({"id": self.resource_id, "kind": "drawing", "width": self.width,
                      "height": self.height, "commands": self.commands if commands is None else commands})

    def check_balanced(self):
        if self.stack:
            raise RuError("如观缓存保存与恢复须成对", category="运行错误")

    def command(self, command, fail):
        if len(self.commands) >= MAX_RECIPE_COMMANDS:
            fail("如观单张缓存最多 2047 个命令；须为贴图保留一个命令")
        # Use the common geometry snapshot and ordinary command validation.
        super().command(command, fail)
        size = self.definition_overhead + self.command_bytes - 2 - bool(self.commands)
        if self.owner.resource_bytes + size + bool(self.owner.resources) > MAX_RESOURCE_BYTES:
            self.commands.pop()
            fail("如观全部缓存定义最多 128 KiB UTF-8 数据；请减少图形或文字")

    def invalidate(self):
        self.closed = True
        self.commands.clear()
        self.callbacks.clear()
        self.reset_geometry()
        self.owner = None


class GraphicsHost:
    def __init__(self, interpreter, emit, *, now_seconds=None, auto_load=True,
                 auto_services=True, services=None):
        self.interpreter, self.emit = interpreter, emit
        self.canvas = None
        self.phase = "initialization"
        self.recording = None
        self.memory_start = 0
        self.owns_tracing = False
        # This host-only hook never enters Ru or the event protocol. Capture the
        # default separately: callback budget checks keep reading their live clock.
        self._now_seconds = time.monotonic if now_seconds is None else now_seconds
        self._last_clock_sample = None
        # Phase 3a: the Python host resolves 图请求／件请求 itself unless a test
        # driver opts out (auto_load=False) and injects readiness events by hand.
        self.auto_load = bool(auto_load)
        self.load_queue = deque()
        self._draining = False
        # 宿主服务通道：宿主声明所供服务（默认 档），画布创建后投递一次
        # 服务告；服务请求排队、帧外迭代执行，与装载管线同节奏。
        self.auto_services = bool(auto_services)
        self.services = ("档",) if services is None else tuple(services)
        self.service_queue = deque()
        self._draining_services = False
        # 测文协议：下游渲染宿主可注入真实字度表与实测钩（如书前端等）。
        self.text_metrics = None
        self.text_measurer = None
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
        self.phase = "initialization"
        self.load_queue.clear()

    def create(self, width, height):
        from .interpreter import Instance
        if self.recording is not None:
            raise RuError("如观缓存录制期间不能创建主画布", category="运行错误")
        origin = self._sample_time(close_on_error=False)
        self.close()
        if not tracemalloc.is_tracing():
            tracemalloc.start(1)
            self.owns_tracing = True
        self.canvas = Canvas(self, width, height, origin)
        self.canvas.metrics = self._resolve_text_metrics()
        if self.services:
            self.service_queue.append({"kind": "ad", "canvas_id": self.canvas.id,
                                       "services": " ".join(self.services)})
        instance = Instance(_TYPES["canvas"], {})
        instance.graphics_canvas = self.canvas
        return instance

    def _resolve_text_metrics(self):
        metrics = self.text_metrics
        if metrics is None:
            return dict(_DEFAULT_TEXT_METRICS)
        if not isinstance(metrics, dict):
            raise RuError("如观字度须为含全／半／行的典", category="用法错误")
        resolved = {}
        for key in ("全", "半", "行"):
            value = metrics.get(key)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0.1 <= value <= 10):
                raise RuError("如观字度须为含全／半／行的典，三个数各为 0.1 至 10 之间有限数",
                              category="用法错误")
            resolved[key] = float(value)
        return resolved

    def flush(self):
        canvas = self.canvas
        if canvas:
            canvas.check_balanced()
        if canvas and canvas.dirty:
            event = canvas.scene()
            if len(_json(event).encode("utf-8")) > MAX_FRAME_BYTES:
                raise RuError("如观完整绘图帧超过 256 KiB UTF-8 数据；请减少图形或文字", category="运行错误")
            self.emit(event)
            canvas.dirty = False
        self._drain_loads()
        self._drain_services()

    def _drain_loads(self):
        # Load jobs queue host-issued readiness events. Deliver them iteratively
        # (not through nested handle→flush recursion) so chained requests stay
        # shallow; each event still passes the ordinary callback budgets.
        if self._draining:
            return
        self._draining = True
        try:
            delivered = 0
            while self.load_queue and delivered < MAX_LOAD_EVENTS_PER_FLUSH:
                job = self.load_queue.popleft()
                delivered += 1
                canvas = self.canvas
                if canvas is None or canvas.closed or canvas.id != job["canvas_id"]:
                    continue
                canvas.load_started.add(job["handle"])
                if job["kind"] == "image":
                    event = self._load_image_job(job)
                else:
                    event = self._load_file_job(job)
                if event is not None:
                    self.handle(event)
        finally:
            self._draining = False

    def _drain_services(self):
        # 服务邮件排队、帧外迭代投递（同装载管线）：执行期回调再入队的
        # 链式请求保持浅层。广告在 服务告 未绑定时留在队首，等库注册后再送。
        if self._draining_services:
            return
        self._draining_services = True
        try:
            delivered = 0
            while self.service_queue and delivered < MAX_LOAD_EVENTS_PER_FLUSH:
                job = self.service_queue.popleft()
                delivered += 1
                canvas = self.canvas
                if canvas is None or canvas.closed or canvas.id != job["canvas_id"]:
                    continue
                if job.get("kind") == "ad":
                    if "service_ad" in canvas.callbacks:
                        self.handle({"type": "service_ad", "services": job["services"]})
                    else:
                        self.service_queue.appendleft(job)
                        break
                    continue
                self.handle(self._run_service_job(job))
        finally:
            self._draining_services = False

    def _run_service_job(self, job):
        handle_id = job["handle"]

        def ok(value=""):
            return {"type": "service_response", "id": handle_id, "ok": True,
                    "value": value, "error": None}

        def bad(message):
            return {"type": "service_response", "id": handle_id, "ok": False,
                    "value": None, "error": message[:512] or "服务失败"}

        if job["service"] != "档":
            return bad("宿主无此服务：" + job["service"])
        path = job["path"]
        if not path:
            return bad("档 路径不可为空")
        if job["action"] == "写":
            try:
                with open(path, "a" if job["flag"] else "w", encoding="utf-8", newline="") as stream:
                    stream.write(job["text"])
                return ok()
            except OSError as error:
                return bad("[errno %s] %s" % (error.errno, error.strerror or "写档失败"))
        if job["action"] == "列":
            try:
                names = sorted(os.listdir(path))
            except OSError as error:
                return bad("[errno %s] %s" % (error.errno, error.strerror or "列档失败"))
            value = "\n".join(names)
            if len(value.encode("utf-8")) > MAX_FILE_LOAD_BYTES:
                return bad("列档结果超过配额")
            return ok(value)
        return bad("档 不识此操作：" + job["action"])

    def _load_image_job(self, job):
        try:
            if os.path.getsize(job["source"]) > MAX_IMAGE_FILE_BYTES:
                raise ValueError("图像超过配额")
            with open(job["source"], "rb") as stream:
                head = stream.read(65536)
            width, height = _image_head_size(head)
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError("图像超过配额")
            return {"type": "image_ready", "id": job["handle"], "width": width, "height": height}
        except OSError:
            return {"type": "image_failed", "id": job["handle"], "error": "读不到文件"}
        except ValueError as exc:
            return {"type": "image_failed", "id": job["handle"], "error": str(exc)[:512] or "装载失败"}

    def _load_file_job(self, job):
        try:
            if os.path.getsize(job["source"]) > MAX_FILE_LOAD_BYTES:
                raise ValueError("文件超过配额")
            with open(job["source"], "rb") as stream:
                raw = stream.read(MAX_FILE_LOAD_BYTES + 1)
            if len(raw) > MAX_FILE_LOAD_BYTES:
                raise ValueError("文件超过配额")
            if job["mode"] == "文":
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    raise ValueError("不是有效 UTF-8 文本")
            else:
                text = base64.b64encode(raw).decode("ascii")
                if len(text) > MAX_FILE_LOAD_BYTES:
                    raise ValueError("文件超过配额")
            return {"type": "file_ready", "id": job["handle"], "text": text}
        except OSError:
            return {"type": "file_failed", "id": job["handle"], "error": "读不到文件"}
        except ValueError as exc:
            return {"type": "file_failed", "id": job["handle"], "error": str(exc)[:512] or "装载失败"}

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
        elif kind == "image_ready":
            allowed |= {"id", "width", "height"}
        elif kind == "image_failed":
            allowed |= {"id", "error"}
        elif kind == "file_ready":
            allowed |= {"id", "text"}
        elif kind == "file_failed":
            allowed |= {"id", "error"}
        elif kind == "text_key":
            allowed.add("key")
            if not isinstance(event.get("key"), str) or event["key"] not in TEXT_EDIT_KEYS:
                raise RuError("无效如观文入键（须为附录 A 编辑键名）", category="运行错误")
        elif kind in ("text_char", "text_paste"):
            allowed.add("text")
            text = event.get("text")
            if (not isinstance(text, str) or (kind == "text_char" and len(text) != 1)
                    or (kind == "text_paste" and (not text or len(text) > MAX_PASTE_CHARS))):
                raise RuError("无效如观文入文本", category="运行错误")
        elif kind == "text_comp_start":
            pass
        elif kind == "text_comp_update":
            allowed |= {"text", "cursor"}
            text = event.get("text")
            cursor = event.get("cursor")
            if not isinstance(text, str) or len(text) > MAX_COMPOSITION_CHARS:
                raise RuError("无效如观输入法组合", category="运行错误")
            if (isinstance(cursor, bool) or not isinstance(cursor, (int, float))
                    or not 0 <= cursor <= MAX_COMPOSITION_CHARS or not math.isfinite(cursor)):
                raise RuError("无效如观输入法光标", category="运行错误")
        elif kind == "text_comp_end":
            allowed.add("text")
            if not isinstance(event.get("text"), str) or len(event["text"]) > MAX_COMPOSITION_CHARS:
                raise RuError("无效如观输入法定字", category="运行错误")
        elif kind == "service_response":
            allowed |= {"id", "ok", "value", "error"}
            ok_flag = event.get("ok")
            value, error = event.get("value"), event.get("error")
            if (not isinstance(ok_flag, bool)
                    or (value is not None and not isinstance(value, str))
                    or (value is not None and len(value.encode("utf-8")) > MAX_FILE_TEXT_BYTES)
                    or (error is not None and (not isinstance(error, str)
                                               or not 1 <= len(error.encode("utf-8")) <= 512))):
                raise RuError("无效如观服务响应", category="运行错误")
        elif kind == "service_ad":
            allowed.add("services")
            if (not isinstance(event.get("services"), str)
                    or len(event["services"].encode("utf-8")) > 4096):
                raise RuError("无效如观服务广告", category="运行错误")
        if set(event) - allowed:
            raise RuError("如观事件含未知字段", category="运行错误")
        if kind == "close":
            self.close()
            return
        callback = canvas.callbacks.get(kind)
        if kind in ASYNC_EVENTS or kind in ("service_response", "service_ad"):
            if callback is None:
                # 未绑定的装载就绪与服务邮件按清理噪音静默忽略。
                return
        if kind != "frame" and callback is None:
            raise RuError("如观事件未启用", category="运行错误")
        if kind == "frame" and not canvas.running:
            raise RuError("如观事件未启用", category="运行错误")
        if kind == "image_ready":
            handle_id = event["id"]
            width, height = event["width"], event["height"]
            if (isinstance(handle_id, bool) or not isinstance(handle_id, int)
                    or not 0 <= handle_id <= 10000000):
                raise RuError("无效如观装载句柄", category="运行错误")
            if (isinstance(width, bool) or not isinstance(width, int)
                    or isinstance(height, bool) or not isinstance(height, int)
                    or not 1 <= width <= 4096 or not 1 <= height <= 4096):
                raise RuError("无效如观图像尺寸", category="运行错误")
            event = {"type": kind, "id": handle_id, "width": width, "height": height}
        elif kind == "image_failed":
            handle_id = event["id"]
            error = event["error"]
            if (isinstance(handle_id, bool) or not isinstance(handle_id, int)
                    or not 0 <= handle_id <= 10000000):
                raise RuError("无效如观装载句柄", category="运行错误")
            if not isinstance(error, str) or not 1 <= len(error.encode("utf-8")) <= 512:
                raise RuError("无效如观装载错误", category="运行错误")
            event = {"type": kind, "id": handle_id, "error": error}
        elif kind == "file_ready":
            handle_id = event["id"]
            text = event["text"]
            if (isinstance(handle_id, bool) or not isinstance(handle_id, int)
                    or not 0 <= handle_id <= 10000000):
                raise RuError("无效如观装载句柄", category="运行错误")
            if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_FILE_TEXT_BYTES:
                raise RuError("无效如观文件内容", category="运行错误")
            event = {"type": kind, "id": handle_id, "text": text}
        elif kind == "file_failed":
            handle_id = event["id"]
            error = event["error"]
            if (isinstance(handle_id, bool) or not isinstance(handle_id, int)
                    or not 0 <= handle_id <= 10000000):
                raise RuError("无效如观装载句柄", category="运行错误")
            if not isinstance(error, str) or not 1 <= len(error.encode("utf-8")) <= 512:
                raise RuError("无效如观装载错误", category="运行错误")
            event = {"type": kind, "id": handle_id, "error": error}
        elif kind == "service_response":
            handle_id = event["id"]
            if (isinstance(handle_id, bool) or not isinstance(handle_id, int)
                    or not 0 <= handle_id <= 10000000):
                raise RuError("无效如观服务句柄", category="运行错误")
            event = {"type": kind, "id": handle_id, "ok": event["ok"],
                     "value": event.get("value"), "error": event.get("error")}
        elif kind == "service_ad":
            event = {"type": kind, "services": event["services"]}
        if kind in ASYNC_EVENTS:
            # 只对真正在途的装载句柄送就绪：未知句柄（从未请求或已释放）
            # 与重复就绪都按噪音忽略，帧数保持确定。校验先行，坏事件仍须报错。
            outstanding = canvas.image_loads if kind.startswith("image") else canvas.file_loads
            if (handle_id not in outstanding or handle_id not in canvas.load_started
                    or handle_id in canvas.load_done):
                return
            canvas.load_done.add(handle_id)
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
        elif kind == "image_ready":
            values = [float(event["id"]), float(event["width"]), float(event["height"])]
        elif kind in ("image_failed", "file_failed"):
            values = [float(event["id"]), event["error"]]
        elif kind == "file_ready":
            values = [float(event["id"]), event["text"]]
        elif kind in ("text_char", "text_paste", "text_comp_end"):
            values = [event["text"]]
        elif kind == "text_comp_update":
            values = [event["text"], float(event["cursor"])]
        elif kind == "text_comp_start":
            values = []
        elif kind == "service_response":
            values = [float(event["id"]), event["ok"],
                      event["value"] if event["value"] is not None else "",
                      event["error"] if event["error"] is not None else ""]
        elif kind == "service_ad":
            values = [event["services"]]
        else:
            values = [event["key"]]
        # Frames are complete scenes. Input callbacks can change style/data;
        # if they draw, their drawing replaces the previous scene as well.
        canvas.reset_geometry()
        previous = canvas.commands
        previous_bytes = canvas.command_bytes
        canvas.commands, canvas.command_bytes = [], 2
        started = time.monotonic()
        # Sample the allocation baseline per callback so the budget measures
        # this callback's net growth. Slow growth across many callbacks is
        # covered by the session-level address-space quota instead.
        self.memory_start = tracemalloc.get_traced_memory()[0]
        deadline, lines = started + MAX_CALLBACK_SECONDS, 0
        remaining = 128
        def check():
            # Preserve the original short-circuit priority and strict boundaries.
            # A diagnostic uses the exact sample that tripped its budget; do not
            # sample again after cleanup or round a just-over-limit value away.
            executed_lines = lines + (128 - remaining)
            if executed_lines > MAX_CALLBACK_LINES:
                self.interpreter.fail(node, f"如观回调超过执行行预算（实际 {executed_lines} Python 跟踪行，阈值 {MAX_CALLBACK_LINES} 行）；已关闭交互，请简化回调后重跑")
            sampled = time.monotonic()
            if sampled > deadline:
                elapsed = sampled - started
                # Subtraction can itself round a strict deadline overrun to the
                # limit. Explain that edge without exposing absolute host times.
                comparison = ("；微小超限差额经浮点运算舍入"
                              if elapsed <= MAX_CALLBACK_SECONDS else "")
                self.interpreter.fail(node, f"如观回调超过时间预算（实际约 {elapsed!r} 秒墙钟耗时，阈值 {MAX_CALLBACK_SECONDS:g} 秒{comparison}）；已关闭交互，请简化回调后重跑")
            allocated = tracemalloc.get_traced_memory()[0] - self.memory_start
            if allocated > MAX_GRAPHICS_MEMORY:
                self.interpreter.fail(node, f"如观新增内存超过分配预算（实际 {allocated} 字节，阈值 {MAX_GRAPHICS_MEMORY} 字节／{MAX_GRAPHICS_MEMORY / (1024 * 1024):g} MiB）；已关闭交互，请减少数据后重跑")
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
        # The callback layer guards time, work and allocation with the
        # portable trace budget above. Process-wide resource quotas belong
        # at the session boundary: session spawners set them once at process
        # startup via install_address_space_limit, never per callback here.
        old_trace = sys.gettrace()
        previous_phase, self.phase = self.phase, "event"
        try:
            sys.settrace(trace)
            self.interpreter.invoke_value(node, fn, [(None, value) for value in values])
            check()
            if self.canvas:
                self.canvas.check_balanced()
        except BaseException:
            self.close()
            raise
        finally:
            self.phase = previous_phase
            sys.settrace(old_trace)
        if self.canvas is canvas:
            if kind in ASYNC_EVENTS:
                # 装载就绪：旧装帧已作废（源可能已换或行已消失），不恢复不
                # 重发；随后的补帧会全量重绘最新场景。
                pass
            else:
                if not canvas.commands and kind != "frame":
                    # Ignored inputs retain the previous complete scene (phase-2
                    # contract: re-publish the restored frame).
                    canvas.commands, canvas.command_bytes = previous, previous_bytes
                canvas.dirty = True
        try:
            self.flush()
        except BaseException:
            self.close()
            raise
        if (kind in ASYNC_EVENTS and self.canvas is canvas and canvas.running
                and "frame" in canvas.callbacks):
            # 装载就绪视同一次帧推进：库只在每帧回调里绘制，宿主补一帧
            # 重渲染，与浏览器宿主在就绪后下一拍 rAF 重绘对齐。
            self.handle({"type": "frame"})


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
    if kind == "image":
        if name not in ("宽", "高"):
            fail("如观图像只提供只读宽、高")
        bind_arguments(name, args, (), fail)
        owner.last_member_procedure = False
        return True, float(receiver.graphics_image.width if name == "宽" else receiver.graphics_image.height)
    canvas = receiver.graphics_canvas
    if canvas.closed or (kind == "recorder" and canvas.host.recording is not canvas) or (kind != "recorder" and canvas.host.canvas is not canvas):
        fail("如观画布已关闭；运行新代码格、停止或重启会话后，请重新创建画布")
    if kind == "recorder" and name not in RECORDER_MEMBERS:
        fail("如观缓存绘图目标不支持成员：" + name)
    if kind != "recorder" and canvas.host.recording is not None and name not in READ_MEMBERS:
        fail("如观缓存录制期间不能修改主画布或嵌套缓存")
    params = CANVAS_PARAMS
    if name not in params:
        fail("未知如观画布成员：" + name)
    bound = bind_arguments(name, args, params[name], fail)
    owner.last_member_procedure = name not in READ_MEMBERS and name != "缓存"
    if name == "缓存":
        host = canvas.host
        if host.phase != "initialization":
            fail("如观缓存仅可在初始化执行时创建，不能在事件回调中创建")
        width = number(bound["宽"], "宽", 1, 2048, True)
        height = number(bound["高"], "高", 1, 2048, True)
        fn = bound["绘制"]
        if not isinstance(fn, Function) or len(fn.node.data["params"]) != 1:
            fail("缓存绘制需要接受 1 个参数的算／作回调")
        if len(canvas.resources) >= MAX_IMAGES:
            fail("如观每画布最多 8 张缓存图像")
        if canvas.resource_pixels + width * height > MAX_RESOURCE_PIXELS:
            fail("如观全部缓存最多 4194304 像素")
        resource_id = "cache-" + str(len(canvas.resources) + 1)
        recorder = DrawingRecorder(host, width, height, resource_id, canvas)
        target = Instance(_TYPES["recorder"], {})
        target.graphics_canvas = recorder
        host.recording = recorder
        try:
            owner.invoke_value(n, fn, [(None, target)])
            recorder.check_balanced()
            definition = recorder.definition()
            size = len(definition.encode("utf-8")) + bool(canvas.resources)
            if canvas.resource_bytes + size > MAX_RESOURCE_BYTES:
                fail("如观全部缓存定义最多 128 KiB UTF-8 数据")
            canvas.resources[resource_id] = DrawingResource(definition, len(recorder.commands), width * height)
            canvas.resource_bytes += size
            canvas.resource_pixels += width * height
        finally:
            host.recording = None
            recorder.invalidate()
        result = Instance(_TYPES["image"], {})
        result.graphics_image = ImageHandle(canvas, canvas.token, resource_id, width, height)
        owner.last_member_procedure = False
        return True, result
    elif name == "贴图":
        image = bound["图像"]
        if not isinstance(image, Instance) or getattr(image.type, "graphics_kind", None) != "image":
            fail("贴图需要如观图像")
        handle = image.graphics_image
        if handle.owner is not canvas or handle.token is not canvas.token or handle.resource_id not in canvas.resources:
            fail("如观图像已失效或属于另一画布；请重新创建缓存")
        canvas.command({"op": "image", "resource": handle.resource_id,
                        "x": number(bound["横"], "横"), "y": number(bound["纵"], "纵")}, fail)
    elif name == "图请求":
        handle_id = number(bound["号"], "号", 1, 10000000, True)
        source = bound["源"]
        if not isinstance(source, str) or not source or len(source.encode("utf-8")) > MAX_SOURCE_CHARS:
            fail("如观图像源 须为非空句，最长 512 字节")
        if handle_id not in canvas.image_loads and len(canvas.image_loads) >= MAX_LOAD_HANDLES:
            fail("如观图像装载最多 64 项；请用 图释放 归还句柄")
        canvas.image_loads.add(handle_id)
        canvas.command({"op": "image_request", "id": handle_id, "source": source}, fail)
        if canvas.host.auto_load:
            canvas.host.load_queue.append({"kind": "image", "canvas_id": canvas.id,
                                           "handle": handle_id, "source": source})
    elif name == "绘图":
        handle_id = number(bound["号"], "号", 1, 10000000, True)
        canvas.command({"op": "draw_image", "id": handle_id,
                        "x": number(bound["横"], "横"), "y": number(bound["纵"], "纵"),
                        "width": number(bound["宽"], "宽", 0, 100000),
                        "height": number(bound["高"], "高", 0, 100000)}, fail)
    elif name == "图释放":
        handle_id = number(bound["号"], "号", 1, 10000000, True)
        canvas.image_loads.discard(handle_id)
        canvas.command({"op": "image_release", "id": handle_id}, fail)
    elif name == "件请求":
        handle_id = number(bound["号"], "号", 1, 10000000, True)
        source = bound["源"]
        if not isinstance(source, str) or not source or len(source.encode("utf-8")) > MAX_SOURCE_CHARS:
            fail("如观文件源 须为非空句，最长 512 字节")
        mode = bound["式"]
        if mode not in LOAD_MODES:
            fail("如观文件模式 只支持 '文' 或 'base64'")
        if handle_id not in canvas.file_loads and len(canvas.file_loads) >= MAX_LOAD_HANDLES:
            fail("如观文件装载最多 64 项")
        canvas.file_loads.add(handle_id)
        canvas.command({"op": "file_request", "id": handle_id, "source": source, "mode": mode}, fail)
        if canvas.host.auto_load:
            canvas.host.load_queue.append({"kind": "file", "canvas_id": canvas.id, "handle": handle_id,
                                           "source": source, "mode": mode})
    elif name == "服务请":
        handle_id = number(bound["号"], "号", 1, 10000000, True)
        service = bound["服务"]
        action = bound["操作"]
        if (not isinstance(service, str) or not service
                or len(service.encode("utf-8")) > MAX_SERVICE_NAME_CHARS):
            fail("如观服务名 须为非空句，最长 64 字节")
        if (not isinstance(action, str) or not action
                or len(action.encode("utf-8")) > MAX_SERVICE_NAME_CHARS):
            fail("如观服务操作 须为非空句，最长 64 字节")
        path = bound["径"]
        if not isinstance(path, str) or len(path.encode("utf-8")) > MAX_SOURCE_CHARS:
            fail("如观服务径 最长 512 字节")
        text = bound["文"]
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_FILE_TEXT_BYTES:
            fail("如观服务文 最长 8 MiB")
        flag = bound["旗"]
        if not isinstance(flag, bool):
            fail("如观服务旗 须为真假")
        canvas.command({"op": "service_request", "id": handle_id, "service": service,
                        "action": action, "path": path, "text": text, "flag": flag}, fail)
        if canvas.host.auto_services:
            canvas.host.service_queue.append({"canvas_id": canvas.id, "handle": handle_id,
                                              "service": service, "action": action,
                                              "path": path, "text": text, "flag": flag})
    elif name == "入焦点":
        text = bound["文"]
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_FILE_TEXT_BYTES:
            fail("如观文入文本 须为句，最长 8 MiB")
        canvas.command({"op": "text_focus", "x": number(bound["横"], "横"),
                        "y": number(bound["纵"], "纵"),
                        "width": number(bound["宽"], "宽", 0, 100000),
                        "height": number(bound["高"], "高", 0, 100000),
                        "text": text,
                        "cursor": number(bound["标"], "标", 0, MAX_PASTE_CHARS, True)}, fail)
    elif name == "入失焦":
        canvas.command({"op": "text_blur"}, fail)
    elif name == "入更新":
        text = bound["文"]
        if not isinstance(text, str) or len(text) > MAX_PASTE_CHARS:
            fail("如观文入文本 最长 " + str(MAX_PASTE_CHARS) + " 字")
        canvas.command({"op": "text_update", "text": text,
                        "cursor": number(bound["标"], "标", 0, MAX_PASTE_CHARS, True),
                        "sel": ""}, fail)
    elif name in CALLBACK_NAMES:
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
    elif name == "字度":
        from .interpreter import RuMap
        result = RuMap()
        for key in ("全", "半", "行"):
            owner.map_put(n, result, key, canvas.metrics[key])
        return True, result
    elif name == "测文":
        text = bound["文"]
        if not isinstance(text, str) or len(text) > 4096:
            fail("测文须为不超过 4096 字符的句")
        return True, _measure_text(canvas, text, fail)
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
        # A new background makes preceding drawing invisible; load-management
        # commands are not drawing and survive the reset so a layout walk may
        # issue them before the background is painted.
        kept = [item for item in canvas.commands if item["op"] in LOAD_MANAGEMENT_OPS]
        canvas.commands, canvas.command_bytes = [], 2
        for item in kept:
            canvas.command(item, fail)
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
    elif name == "贝塞尔":
        values = [number(bound[key], key) for key in params[name]]
        canvas.command(dict(zip(("x1", "y1", "cx1", "cy1", "cx2", "cy2", "x2", "y2"), values),
                            op="bezier", fill="", stroke=canvas.stroke, stroke_width=canvas.line_width), fail)
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
