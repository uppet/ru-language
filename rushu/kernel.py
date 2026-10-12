"""Spawn-based, interruptible interpreter sessions; no notebook filesystem API."""
from collections import deque
import multiprocessing
import json
import math
import time
from multiprocessing.connection import wait
import secrets
import threading

MAX_SOURCE = 200_000
MAX_INPUT = 65_536
MAX_OUTPUT = 2 * 1024 * 1024  # UTF-8 bytes per execution
MAX_OUTPUT_EVENTS = 16_384
MAX_EVENTS = 20_000
MAX_EVENT_TEXT = 16 * 1024 * 1024
MAX_POLL_BYTES = 1024 * 1024
MAX_SESSIONS = 16
# Keep the hard watchdog at 10x the runtime soft callback deadline (1 second).
GRAPHICS_TIMEOUT = 10.0
MAX_GRAPHICS_COMMANDS = 2048
MAX_GRAPHICS_BYTES = 262_144
GRAPHICS_EVENTS = {"frame", "mouse_down", "mouse_up", "mouse_move", "key_down", "key_up", "close"}


class KernelError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class _Output:
    encoding = "utf-8"

    def __init__(self, connection, stream, budget):
        self.connection, self.stream, self.budget = connection, stream, budget
        budget.setdefault("lock", threading.RLock())

    def write(self, text):
        with self.budget["lock"]:
            result = self._write(text)
            # Flush a final small write even if the program then computes forever
            # or sleeps without producing another write or protocol boundary.
            if self.budget.get("pending") and not self.budget.get("timer"):
                timer = threading.Timer(.05, self._timed_flush)
                timer.daemon = True
                self.budget["timer"] = timer
                timer.start()
            return result

    def _timed_flush(self):
        try:
            self.flush(force=True)
        except (OSError, EOFError):
            pass

    def _write(self, text):
        length = len(text)
        if not length:
            return 0
        budget = self.budget
        if budget["truncated"]:
            return length
        if budget.get("stream") != self.stream:
            self.flush(force=True)
        if budget["events"] >= MAX_OUTPUT_EVENTS:
            budget["truncated"] = True
            self.connection.send({"type": "output", "stream": "stderr",
                "text": f"\n[输出已截断：达到事件数量上限，保留 {budget['chars']:,} UTF-8 字节；后续输出丢弃，程序仍可运行。]\n",
                "truncated": True})
            return length
        budget["stream"] = self.stream
        # Encode bounded chunks, never duplicate an arbitrarily large write.
        for start in range(0, length, 2048):
            data = text[start:start + 2048].encode("utf-8", errors="replace")
            remaining = MAX_OUTPUT - budget["chars"]
            kept = data[:remaining].decode("utf-8", errors="ignore")
            budget.setdefault("parts", []).append(kept)
            size = len(kept.encode("utf-8"))
            budget["chars"] += size
            budget["pending"] = budget.get("pending", 0) + size
            if (budget["pending"] >= 8192 or
                    time.monotonic() - budget.get("last_flush", 0) >= .05):
                self.flush(force=True)
            if size < len(data) or budget["events"] >= MAX_OUTPUT_EVENTS:
                self.flush(force=True)
                budget["truncated"] = True
                self.connection.send({"type": "output", "stream": "stderr",
                    "text": f"\n[输出已截断：保留前 {budget['chars']:,} UTF-8 字节；后续输出丢弃，程序仍可运行。]\n",
                    "truncated": True})
                break
        return length

    def flush(self, force=False):
        with self.budget["lock"]:
            self._flush(force)

    def _flush(self, force=False):
        budget = self.budget
        # Language print helpers call flush after every line. Coalesce those
        # routine calls; protocol boundaries below always force a real flush.
        if not force and budget.get("pending", 0) < 8192 and time.monotonic() - budget.get("last_flush", 0) < .05:
            return
        timer = budget.pop("timer", None)
        if timer:
            timer.cancel()
        if budget.get("pending"):
            self.connection.send({"type": "output", "stream": budget["stream"],
                                  "text": "".join(budget["parts"])})
            budget["events"] += 1
        budget.update(parts=[], pending=0, last_flush=time.monotonic())

    def isatty(self):
        return False


class _Input:
    encoding = "utf-8"

    def __init__(self, connection, flush=lambda: None):
        self.connection = connection
        self.flush = flush
        self.eof = False
        self.pending = ""
        self.graphics_callback = False

    def reset(self):
        self.eof = False
        self.pending = ""

    def _fill(self):
        if self.graphics_callback:
            raise OSError("如观回调不能请求交互输入；请先在普通代码格读取")
        if not self.pending and not self.eof:
            self.flush()
            request_id = secrets.token_hex(12)
            self.connection.send({"type": "input_request", "request_id": request_id})
            reply = self.connection.recv()
            if reply.get("kind") != "input" or reply.get("request_id") != request_id:
                raise OSError("输入请求已失效")
            if reply.get("eof"):
                self.eof = True
                return
            self.pending = reply["text"] + "\n"

    def readline(self, size=-1):
        if size == 0:
            return ""
        self._fill()
        if not self.pending:
            return ""
        end = self.pending.find("\n") + 1
        if size >= 0:
            end = min(end, size)
        value, self.pending = self.pending[:end], self.pending[end:]
        return value

    def read(self, size=-1):
        # 如竞's 读入 consumes the complete input stream, so keep requesting
        # lines until the user explicitly supplies EOF. Sized reads preserve
        # unused input for a later read/readline on the same shared stream.
        if size == 0:
            return ""
        parts, count = [], 0
        while size < 0 or count < size:
            self._fill()
            if not self.pending:
                break
            length = len(self.pending) if size < 0 else min(len(self.pending), size - count)
            parts.append(self.pending[:length])
            self.pending = self.pending[length:]
            count += length
        return "".join(parts)

    def isatty(self):
        return False


def _worker(connection):
    # Top-level target and explicit spawn context work on Windows/macOS/Linux.
    # Console Ctrl-C belongs to the server, which then terminates every kernel.
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    from rulang.frontend import RuError, parse
    from rulang.interpreter import Interpreter
    from rulang.graphics_runtime import GraphicsHost
    from rulang.modules import reject_generation_document

    budget = {"chars": 0, "events": 0, "truncated": False}
    stdout, stderr = (_Output(connection, name, budget) for name in ("stdout", "stderr"))
    stdin = _Input(connection, lambda: stdout.flush(force=True))
    def send(event):
        stdout.flush(force=True)
        connection.send(event)
    interpreter = Interpreter(stdin, stdout, stderr=stderr)
    host = GraphicsHost(interpreter, send)
    interpreter.graphics_host = host
    try:
        while True:
            command = connection.recv()
            if command.get("kind") == "close":
                break
            kind = command.get("kind")
            if kind not in ("execute", "graphics"):
                continue
            budget.update(chars=0, events=0, truncated=False, parts=[], pending=0, last_flush=0)
            stdin.reset()
            status = "ok"
            try:
                if kind == "graphics":
                    stdin.graphics_callback = True
                    try:
                        host.handle(command["event"])
                    finally:
                        stdin.graphics_callback = False
                else:
                    host.begin_execution()
                    source = command["code"]
                    reject_generation_document(source)
                    interpreter.execute(parse(source), echo=True)
                    host.flush()
            except RuError as error:
                status = "error"
                send({"type": "error", "category": error.category,
                                 "message": error.message[:16384], "line": error.line,
                                 "col": error.col,
                                 "source_name": str(getattr(error, "source_name", ""))[:4096]})
            except RecursionError:
                status = "error"
                send({"type": "error", "category": "运行错误",
                                 "message": "调用或表达式结构过深，请拆分为较小的步骤。", "line": 1, "col": 1})
            except Exception as error:
                status = "error"
                send({"type": "error", "category": "运行错误",
                                 "message": (type(error).__name__ + ": " + str(error))[:16384],
                                 "line": 1, "col": 1})
            if status == "error":
                host.close()
            if kind == "graphics":
                send({"type": "graphics_done", "canvas_id": command["canvas_id"], "status": status})
            else:
                send({"type": "done", "status": status})
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        connection.close()


class Session:
    """One stateful Interpreter in a disposable spawned process.

    Lock serializes requests and event ingestion. Generation checks prevent late
    events from an interrupted process contaminating its replacement.
    """
    def __init__(self):
        self.id = secrets.token_hex(16)
        self.lock = threading.RLock()
        self.events = deque()
        self.event_text = 0
        self.cursor = 0
        self.evicted_through = 0
        self.graphics = None
        self.graphics_busy = False
        self.graphics_close_pending = False
        self.graphics_timer = None
        self.graphics_token = None
        self.graphics_times = deque()
        self.graphics_frame_time = 0.0
        self.execution_count = 0
        self.generation = 1
        self.state = "idle"
        self.cell_id = None
        self.request_id = None
        self.closed = False
        self.process = None
        self.connection = None
        self.collector = None
        self._start()

    def _start(self):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=_worker, args=(child,), daemon=True,
                                  name="rushu-" + self.id[:8])
        try:
            process.start()
        except BaseException:
            parent.close()
            child.close()
            raise
        child.close()
        self.connection, self.process = parent, process
        # Capture the handle before another request can stop/close the Process.
        # On Windows a child killed during spawn bootstrap can leave a duplicate
        # pipe writer alive in the parent. EOF alone is not a death notification.
        self.collector = threading.Thread(target=self._collect,
            args=(parent, process.sentinel, self.generation),
            name="rushu-events-" + self.id[:8], daemon=True)
        self.collector.start()

    @staticmethod
    def _event_size(event):
        # Count complete serialized records, including graphics command payloads.
        return len(json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def _append(self, event):
        self.cursor += 1
        record = dict(event, seq=self.cursor, cell_id=self.cell_id,
                      execution_count=self.execution_count, generation=self.generation)
        if record["type"] in ("graphics", "graphics_done"):
            # Frames are complete scene snapshots; keep only the newest per canvas.
            retained = deque()
            for previous in self.events:
                if (previous["type"] == record["type"]
                        and previous.get("canvas_id") == record.get("canvas_id")
                        and previous["generation"] == record["generation"]):
                    self.event_text -= self._event_size(previous)
                else:
                    retained.append(previous)
            self.events = retained
        self.events.append(record)
        self.event_text += self._event_size(record)
        while len(self.events) > MAX_EVENTS or self.event_text > MAX_EVENT_TEXT:
            removed = self.events.popleft()
            self.evicted_through = max(self.evicted_through, removed["seq"])
            self.event_text -= self._event_size(removed)

    def _accept_graphics(self, event):
        commands = event.get("commands", [])
        if (not isinstance(commands, list) or len(commands) > MAX_GRAPHICS_COMMANDS
                or self._event_size(event) > MAX_GRAPHICS_BYTES
                or any(not isinstance(command, dict) or command.get("op") not in
                       {"rect", "ellipse", "line", "text", "background"} for command in commands)):
            raise ValueError("invalid graphics payload")
        self.graphics = {key: event.get(key) for key in
                         ("canvas_id", "width", "height", "fps", "running", "handlers")}

    def _collect(self, connection, sentinel, generation):
        try:
            while True:
                ready = wait((connection, sentinel))
                # Drain every already-ready event before reporting process exit.
                # Never wait for pipe EOF after the process sentinel has fired.
                if connection not in ready:
                    break
                event = connection.recv()
                with self.lock:
                    if self.closed or generation != self.generation:
                        return
                    if event["type"] == "graphics":
                        self._accept_graphics(event)
                    elif event["type"] == "graphics_closed":
                        if self.graphics and event.get("canvas_id") == self.graphics["canvas_id"]:
                            self.graphics = None
                    elif event["type"] == "graphics_done":
                        self._cancel_graphics_timer()
                        self.graphics_busy = False
                        pending = self.graphics_close_pending
                        self.graphics_close_pending = False
                        if pending and self.graphics:
                            self.dispatch_graphics(self.graphics["canvas_id"], self.cell_id,
                                                   self.execution_count, self.generation, {"type": "close"})
                    elif event["type"] == "input_request":
                        self.state, self.request_id = "waiting_input", event["request_id"]
                    elif event["type"] == "done":
                        self.state, self.request_id = "idle", None
                    self._append(event)
        except (EOFError, OSError, TypeError, ValueError):
            pass
        finally:
            with self.lock:
                if not self.closed and generation == self.generation:
                    self.state, self.request_id = "dead", None
                    self.graphics, self.graphics_busy = None, False
                    self.graphics_close_pending = False
                    self._cancel_graphics_timer()
                    self._append({"type": "error", "category": "会话错误",
                                  "message": "执行进程已退出，请重启会话。", "line": 1, "col": 1})
                    self._append({"type": "done", "status": "error"})
            connection.close()

    def _snapshot(self):
        return {"id": self.id, "state": self.state, "execution_count": self.execution_count,
                "generation": self.generation, "cursor": self.cursor, "cell_id": self.cell_id,
                "request_id": self.request_id, "graphics": (dict(self.graphics) if self.graphics else None),
                "graphics_busy": self.graphics_busy,
                "graphics_close_pending": self.graphics_close_pending}

    def snapshot(self):
        with self.lock:
            self._check_open()
            return self._snapshot()

    def _check_open(self):
        if self.closed:
            raise KernelError("会话已关闭", 404)

    def execute(self, code, cell_id, expected_generation=None):
        if not isinstance(code, str) or len(code) > MAX_SOURCE:
            raise KernelError("代码须为文字，且不超过 200000 字符")
        if not isinstance(cell_id, str) or not 1 <= len(cell_id) <= 128:
            raise KernelError("cell_id 须为 1 至 128 字符的文字")
        if expected_generation is not None and (isinstance(expected_generation, bool)
                or not isinstance(expected_generation, int) or expected_generation < 1):
            raise KernelError("expected_generation 须为正整数")
        with self.lock:
            self._check_open()
            # A browser may stop while an execute request is still in flight.
            # Check under the same lock as reset so old requests cannot launch
            # code in the replacement worker or consume its execution counter.
            if expected_generation is not None and expected_generation != self.generation:
                raise KernelError("会话已重置，此次运行请求已失效", 409)
            if self.state != "idle" or self.graphics_busy:
                raise KernelError("会话正在运行、等待输入或已退出；请先停止或重启", 409)
            self.graphics = None
            self.graphics_times.clear()
            self.graphics_frame_time = 0.0
            self.execution_count += 1
            self.cell_id, self.state, self.request_id = cell_id, "running", None
            try:
                self.connection.send({"kind": "execute", "code": code})
            except (OSError, BrokenPipeError):
                self.state = "dead"
                raise KernelError("执行进程已退出，请重启会话", 409) from None
            return self._snapshot()

    def poll(self, after=0):
        if isinstance(after, bool) or not isinstance(after, int) or after < 0:
            raise KernelError("after 须为非负整数")
        with self.lock:
            self._check_open()
            if after > self.cursor:
                raise KernelError("after 超出当前事件序号")
            result = self._snapshot()
            batch, size = [], 0
            for event in self.events:
                if event["seq"] <= after:
                    continue
                event_size = self._event_size(event)
                if batch and size + event_size > MAX_POLL_BYTES:
                    break
                batch.append(event.copy())
                size += event_size
            result["events"] = batch
            result["more"] = bool(batch and batch[-1]["seq"] < self.cursor)
            # A page cursor must never skip undispatched events.
            result["cursor"] = batch[-1]["seq"] if batch else after
            result["truncated"] = after < self.evicted_through
            return result

    def _cancel_graphics_timer(self):
        if getattr(self, "graphics_timer", None) is not None:
            self.graphics_timer.cancel()
        self.graphics_timer = self.graphics_token = None

    def _graphics_timeout(self, token, generation, canvas_id):
        with self.lock:
            if (self.closed or generation != self.generation
                    or token != self.graphics_token or not self.graphics_busy):
                return
            self._append({"type": "error", "category": "图形错误",
                          "message": "如观回调超过 10 秒，执行进程已终止并重启；会话变量和图形上下文已清空。",
                          "line": 1, "col": 1})
            self._append({"type": "graphics_done", "canvas_id": canvas_id, "status": "error"})
            try:
                self.reset("graphics_timeout")
            except KernelError:
                self._append({"type": "error", "category": "会话错误",
                              "message": "回调超时后无法重启执行进程，请重启会话。", "line": 1, "col": 1})

    def dispatch_graphics(self, canvas_id, cell_id, execution_count, expected_generation, event):
        if (not isinstance(canvas_id, str) or not 1 <= len(canvas_id) <= 128
                or not isinstance(cell_id, str) or not 1 <= len(cell_id) <= 128
                or isinstance(execution_count, bool) or not isinstance(execution_count, int)
                or isinstance(expected_generation, bool) or not isinstance(expected_generation, int)):
            raise KernelError("图形请求须提供完整执行标识")
        if (not isinstance(event, dict) or not isinstance(event.get("type"), str)
                or event["type"] not in GRAPHICS_EVENTS):
            raise KernelError("无效图形事件")
        kind = event["type"]
        allowed = {"type"}
        if kind.startswith("mouse_"):
            allowed |= {"x", "y", "button"}
            for key in ("x", "y"):
                value = event.get(key)
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or abs(value) > 100000 or not math.isfinite(value)):
                    raise KernelError("图形坐标须为有限数值")
            value = event.get("button", 0)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 4:
                raise KernelError("无效鼠标按钮")
        elif kind.startswith("key_"):
            allowed.add("key")
            if not isinstance(event.get("key"), str) or len(event["key"]) > 64:
                raise KernelError("按键须为不超过 64 字符的文字")
        if set(event) - allowed:
            raise KernelError("图形事件含未知字段")
        with self.lock:
            self._check_open()
            if (expected_generation != self.generation or cell_id != self.cell_id
                    or execution_count != self.execution_count or not self.graphics
                    or canvas_id != self.graphics["canvas_id"]):
                raise KernelError("图形请求已失效", 409)
            if self.state != "idle":
                raise KernelError("单元正在运行，请稍后重试", 409)
            if self.graphics_busy:
                if kind == "close":
                    self.graphics_close_pending = True
                    return self._snapshot()
                raise KernelError("图形正在运行或等待关闭，请稍后重试", 409)
            if kind != "close":
                if (kind not in (self.graphics.get("handlers") or [])
                        or kind == "frame" and not self.graphics.get("running")):
                    raise KernelError("此图形事件未启用", 409)
                now = time.monotonic()
                while self.graphics_times and now - self.graphics_times[0] >= 1:
                    self.graphics_times.popleft()
                if (len(self.graphics_times) >= 30
                        or kind == "frame" and now - self.graphics_frame_time < 1 / max(1, min(30, self.graphics.get("fps", 30)))):
                    raise KernelError("图形事件过于频繁，请稍后重试", 429)
                self.graphics_times.append(now)
                if kind == "frame":
                    self.graphics_frame_time = now
            self.graphics_busy = True
            try:
                normalized = dict(event)
                if kind in ("mouse_down", "mouse_up"):
                    normalized.setdefault("button", 0)
                self.connection.send({"kind": "graphics", "canvas_id": canvas_id, "event": normalized})
            except (OSError, BrokenPipeError):
                self.graphics, self.graphics_busy, self.state = None, False, "dead"
                raise KernelError("执行进程已退出，请重启会话", 409) from None
            token = secrets.token_hex(12)
            self.graphics_token = token
            timer = threading.Timer(GRAPHICS_TIMEOUT, self._graphics_timeout,
                                    args=(token, self.generation, canvas_id))
            timer.daemon = True
            self.graphics_timer = timer
            timer.start()
            return self._snapshot()

    def provide_input(self, request_id, text="", eof=False):
        if not isinstance(request_id, str) or not isinstance(text, str) or len(text) > MAX_INPUT:
            raise KernelError("无效输入；文字不能超过 65536 字符")
        if not isinstance(eof, bool):
            raise KernelError("eof 须为布尔值")
        with self.lock:
            self._check_open()
            if self.state != "waiting_input" or request_id != self.request_id:
                raise KernelError("输入请求已失效", 409)
            self.connection.send({"kind": "input", "request_id": request_id, "text": text, "eof": eof})
            self.state, self.request_id = "running", None
            return self._snapshot()

    def _terminate(self):
        process, connection, collector = self.process, self.connection, self.collector
        self.process = self.connection = self.collector = None
        if process is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
        # Do not close a Windows HANDLE while another thread is waiting on it.
        # This method runs under the session lock; joining the collector here
        # could deadlock its final generation/state check. Let it release that
        # lock first, then close the exited Process and transport exactly once.
        def release():
            if collector is not None:
                collector.join()
            if connection is not None:
                connection.close()
            if process is not None:
                process.close()

        if collector is not None and collector.is_alive():
            threading.Thread(target=release, name="rushu-reap-" + self.id[:8], daemon=True).start()
        else:
            release()

    def reset(self, reason="restart"):
        with self.lock:
            self._check_open()
            self.generation += 1
            self._cancel_graphics_timer()
            self._terminate()
            self.state, self.cell_id, self.request_id = "idle", None, None
            self.execution_count = 0
            self.graphics, self.graphics_busy = None, False
            self.graphics_close_pending = False
            self.graphics_times.clear()
            self.graphics_frame_time = 0.0
            try:
                self._start()
            except Exception:
                self.state = "dead"
                raise KernelError("无法重启执行进程", 503) from None
            self._append({"type": "reset", "reason": reason})
            return self._snapshot()

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                self._cancel_graphics_timer()
                self._terminate()
                self.graphics, self.graphics_busy = None, False
                self.graphics_close_pending = False
                self.events.clear()
                self.event_text = 0


class SessionManager:
    def __init__(self, limit=MAX_SESSIONS):
        self.sessions, self.lock, self.limit = {}, threading.RLock(), limit
        self.closed = False

    def create(self):
        with self.lock:
            if self.closed:
                raise KernelError("服务已关闭", 503)
            if len(self.sessions) >= self.limit:
                raise KernelError("最多同时打开 16 个执行会话，请关闭不用的笔记本", 429)
            session = Session()
            self.sessions[session.id] = session
            return session

    def get(self, identifier):
        with self.lock:
            session = self.sessions.get(identifier)
            if session is None:
                raise KernelError("会话不存在", 404)
            return session

    def delete(self, identifier):
        with self.lock:
            session = self.sessions.pop(identifier, None)
            if session is None:
                raise KernelError("会话不存在", 404)
        session.close()

    def close(self):
        with self.lock:
            self.closed = True
            sessions = list(self.sessions.values())
            self.sessions.clear()
        for session in sessions:
            session.close()
