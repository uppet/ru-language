"""Spawn-based, interruptible interpreter sessions; no notebook filesystem API."""
from collections import deque
import multiprocessing
import secrets
import threading

MAX_SOURCE = 200_000
MAX_INPUT = 65_536
MAX_OUTPUT = 262_144
MAX_OUTPUT_EVENTS = 1024
MAX_EVENTS = 4096
MAX_EVENT_TEXT = 1_048_576
MAX_SESSIONS = 16


class KernelError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class _Output:
    encoding = "utf-8"

    def __init__(self, connection, stream, budget):
        self.connection, self.stream, self.budget = connection, stream, budget

    def write(self, text):
        length = len(text)
        if not length:
            return 0
        budget = self.budget
        remaining = MAX_OUTPUT - budget["chars"]
        # Chunk large individual writes so no event can dominate retained history.
        offset = 0
        while offset < min(length, remaining) and budget["events"] < MAX_OUTPUT_EVENTS:
            part = text[offset:min(length, remaining, offset + 8192)]
            self.connection.send({"type": "output", "stream": self.stream, "text": part})
            budget["chars"] += len(part)
            budget["events"] += 1
            offset += len(part)
        if offset < length and not budget["truncated"]:
            budget["truncated"] = True
            self.connection.send({"type": "output", "stream": "stderr",
                                  "text": "\n[输出已达上限，后续输出已截断；程序仍在运行。]\n",
                                  "truncated": True})
        return length

    def flush(self):
        pass

    def isatty(self):
        return False


class _Input:
    encoding = "utf-8"

    def __init__(self, connection):
        self.connection = connection
        self.eof = False
        self.pending = ""

    def reset(self):
        self.eof = False
        self.pending = ""

    def _fill(self):
        if not self.pending and not self.eof:
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
        # 竞赛's 读入 consumes the complete input stream, so keep requesting
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
    from rulang.modules import reject_generation_document

    budget = {"chars": 0, "events": 0, "truncated": False}
    stdin = _Input(connection)
    stdout, stderr = (_Output(connection, name, budget) for name in ("stdout", "stderr"))
    interpreter = Interpreter(stdin, stdout, stderr=stderr)
    try:
        while True:
            command = connection.recv()
            if command.get("kind") == "close":
                break
            if command.get("kind") != "execute":
                continue
            budget.update(chars=0, events=0, truncated=False)
            stdin.reset()
            status = "ok"
            try:
                source = command["code"]
                reject_generation_document(source)
                interpreter.execute(parse(source), echo=True)
            except RuError as error:
                status = "error"
                connection.send({"type": "error", "category": error.category,
                                 "message": error.message[:16384], "line": error.line,
                                 "col": error.col,
                                 "source_name": str(getattr(error, "source_name", ""))[:4096]})
            except RecursionError:
                status = "error"
                connection.send({"type": "error", "category": "运行错误",
                                 "message": "调用或表达式结构过深，请拆分为较小的步骤。", "line": 1, "col": 1})
            except Exception as error:
                status = "error"
                connection.send({"type": "error", "category": "运行错误",
                                 "message": (type(error).__name__ + ": " + str(error))[:16384],
                                 "line": 1, "col": 1})
            connection.send({"type": "done", "status": status})
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
        self.execution_count = 0
        self.generation = 1
        self.state = "idle"
        self.cell_id = None
        self.request_id = None
        self.closed = False
        self.process = None
        self.connection = None
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
        threading.Thread(target=self._collect, args=(parent, process, self.generation),
                         name="rushu-events-" + self.id[:8], daemon=True).start()

    def _append(self, event):
        self.cursor += 1
        record = dict(event, seq=self.cursor, cell_id=self.cell_id,
                      execution_count=self.execution_count, generation=self.generation)
        self.events.append(record)
        self.event_text += len(record.get("text", "")) + len(record.get("message", ""))
        while len(self.events) > MAX_EVENTS or self.event_text > MAX_EVENT_TEXT:
            removed = self.events.popleft()
            self.event_text -= len(removed.get("text", "")) + len(removed.get("message", ""))

    def _collect(self, connection, process, generation):
        try:
            while True:
                event = connection.recv()
                with self.lock:
                    if self.closed or generation != self.generation:
                        return
                    if event["type"] == "input_request":
                        self.state, self.request_id = "waiting_input", event["request_id"]
                    elif event["type"] == "done":
                        self.state, self.request_id = "idle", None
                    self._append(event)
        except (EOFError, OSError, TypeError):
            with self.lock:
                if not self.closed and generation == self.generation:
                    self.state, self.request_id = "dead", None
                    self._append({"type": "error", "category": "会话错误",
                                  "message": "执行进程已退出，请重启会话。", "line": 1, "col": 1})
                    self._append({"type": "done", "status": "error"})

    def _snapshot(self):
        return {"id": self.id, "state": self.state, "execution_count": self.execution_count,
                "generation": self.generation, "cursor": self.cursor, "cell_id": self.cell_id,
                "request_id": self.request_id}

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
            if self.state != "idle":
                raise KernelError("会话正在运行、等待输入或已退出；请先停止或重启", 409)
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
            result["events"] = [event.copy() for event in self.events if event["seq"] > after]
            result["truncated"] = bool(self.events and after < self.events[0]["seq"] - 1)
            return result

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
        process, connection = self.process, self.connection
        self.process = self.connection = None
        if process is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            process.close()
        if connection is not None:
            connection.close()

    def reset(self, reason="restart"):
        with self.lock:
            self._check_open()
            self.generation += 1
            self._terminate()
            self.state, self.cell_id, self.request_id = "idle", None, None
            self.execution_count = 0
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
                self._terminate()
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
