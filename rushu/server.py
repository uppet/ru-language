"""Authenticated loopback HTTP transport and an explicit static-file allowlist."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import re
import secrets
import signal
import sys
import threading
from urllib.parse import parse_qs, urlsplit
import webbrowser

from .kernel import KernelError, SessionManager

MAX_BODY = 1_048_576
STATIC_FILES = {"/": ("index.html", "text/html; charset=utf-8"),
                "/index.html": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
                "/editor.mjs": ("editor.mjs", "text/javascript; charset=utf-8"),
                "/notebook.mjs": ("notebook.mjs", "text/javascript; charset=utf-8")}
SESSION_PATH = re.compile(r"/api/sessions/([a-f0-9]{32})(?:/(execute|events|input|stop|restart))?\Z")


class NotebookServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, port=0, token=None, static_dir=None):
        self.token = token if token is not None else secrets.token_urlsafe(32)
        if not isinstance(self.token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,256}", self.token):
            raise ValueError("token must be 16-256 URL-safe ASCII characters")
        self.static_dir = (Path(static_dir) if static_dir else Path(__file__).parent / "static").resolve()
        self.sessions = SessionManager()
        self._request_slots = threading.BoundedSemaphore(64)
        super().__init__(("127.0.0.1", port), NotebookHandler)
        self.host = "127.0.0.1:" + str(self.server_address[1])
        self.origin = "http://" + self.host

    @property
    def url(self):
        return self.origin + "/#token=" + self.token

    def process_request(self, request, client_address):
        if not self._request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()

    def server_close(self):
        self.sessions.close()
        super().server_close()


class NotebookHandler(BaseHTTPRequestHandler):
    # Closing each bounded request also prevents ambiguous body framing reuse.
    protocol_version = "HTTP/1.0"
    server_version = "Rushu"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, format, *args):
        pass  # Never log bearer tokens, source code, or inline input.

    def _respond(self, status, body, content_type="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.close_connection = True

    def _header(self, name):
        values = self.headers.get_all(name, [])
        if len(values) > 1:
            raise KernelError("重复的请求头：" + name)
        return values[0] if values else None

    def _security(self, api=False, mutation=False):
        if self._header("Host") != self.server.host:
            raise KernelError("仅接受本机启动地址", 403)
        origin = self._header("Origin")
        if origin is not None and origin != self.server.origin:
            raise KernelError("拒绝跨站请求", 403)
        if mutation and origin != self.server.origin:
            raise KernelError("修改请求必须来自本机页面", 403)
        site = self._header("Sec-Fetch-Site")
        if site not in (None, "none", "same-origin"):
            raise KernelError("拒绝跨站请求", 403)
        if self._header("Transfer-Encoding") is not None:
            raise KernelError("不支持分块请求")
        length = self._header("Content-Length")
        if length is not None and (not re.fullmatch(r"[0-9]+", length) or len(length) > 10):
            raise KernelError("无效请求长度")
        if length is not None and int(length) > MAX_BODY:
            raise KernelError("请求超过 1 MiB 上限", 413)
        if api:
            token = self._header("X-Rushu-Token") or ""
            if not hmac.compare_digest(token.encode("utf-8"), self.server.token.encode("ascii")):
                raise KernelError("启动令牌无效，请使用终端给出的完整链接", 401)

    def _body(self):
        content_type = (self._header("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise KernelError("请求须使用 application/json", 415)
        length = self._header("Content-Length")
        if length is None:
            raise KernelError("缺少 Content-Length", 411)
        count = int(length)
        raw = self.rfile.read(count)
        if len(raw) != count:
            raise KernelError("请求内容不完整")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError):
            raise KernelError("请求须为有效的 UTF-8 JSON") from None
        if not isinstance(data, dict):
            raise KernelError("请求须为 JSON 对象")
        # JSON escape sequences can encode isolated surrogate code points.
        try:
            json.dumps(data, ensure_ascii=False).encode("utf-8")
        except UnicodeError:
            raise KernelError("请求含无效的 Unicode 字符") from None
        return data

    def _dispatch(self):
        try:
            parsed = urlsplit(self.path)
            if parsed.scheme or parsed.netloc or parsed.fragment:
                raise KernelError("无效请求路径")
            path = parsed.path
            api = path.startswith("/api/")
            mutation = self.command in ("POST", "DELETE")
            self._security(api=api, mutation=mutation)
            if not api:
                if self.command not in ("GET", "HEAD"):
                    raise KernelError("不支持此请求方式", 405)
                if parsed.query or path not in STATIC_FILES:
                    raise KernelError("文件不存在", 404)
                name, mime = STATIC_FILES[path]
                target = (self.server.static_dir / name).resolve()
                try:
                    target.relative_to(self.server.static_dir)
                except ValueError:
                    raise KernelError("文件不存在", 404) from None
                if not target.is_file() or target.stat().st_size > 2 * MAX_BODY:
                    raise KernelError("文件不存在", 404)
                self._respond(200, target.read_bytes(), mime)
                return
            if path == "/api/sessions" and self.command == "POST" and not parsed.query:
                self._body()
                self._respond(201, self.server.sessions.create().snapshot())
                return
            match = SESSION_PATH.fullmatch(path)
            if not match:
                raise KernelError("接口不存在", 404)
            identifier, action = match.groups()
            session = self.server.sessions.get(identifier)
            if action == "events" and self.command == "GET":
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) - {"after"} or len(query.get("after", ["0"])) != 1:
                    raise KernelError("无效事件查询")
                value = query.get("after", ["0"])[0]
                if not re.fullmatch(r"[0-9]{1,16}", value):
                    raise KernelError("after 须为非负整数")
                self._respond(200, session.poll(int(value)))
                return
            if parsed.query:
                raise KernelError("此接口不接受查询参数")
            if action is None and self.command == "DELETE":
                self._body()
                self.server.sessions.delete(identifier)
                self._respond(200, {"deleted": True})
                return
            if self.command != "POST":
                raise KernelError("不支持此请求方式", 405)
            body = self._body()
            if action == "execute":
                result = session.execute(body.get("code"), body.get("cell_id"), body.get("expected_generation"))
                self._respond(202, result)
            elif action == "input":
                result = session.provide_input(body.get("request_id"), body.get("text", ""), body.get("eof", False))
                self._respond(200, result)
            elif action in ("stop", "restart"):
                self._respond(200, session.reset(action))
            else:
                raise KernelError("接口不存在", 404)
        except KernelError as error:
            self._respond(error.status, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except (OSError, ValueError, RecursionError):
            self._respond(500, {"error": "本机服务无法完成请求"})

    do_GET = do_HEAD = do_POST = do_DELETE = do_PUT = do_PATCH = do_OPTIONS = _dispatch


def make_server(port=0, token=None, static_dir=None):
    return NotebookServer(port=port, token=token, static_dir=static_dir)


def main(argv=None):
    # Match the language CLI on Windows consoles and redirected UTF-8 logs.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m rushu", description="如书 · 仅在本机运行的如语言笔记本")
    parser.add_argument("--port", type=int, default=0, help="本机端口，默认自动选择")
    parser.add_argument("--no-browser", action="store_true", help="仅打印地址，不自动打开浏览器")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("端口须在 0 至 65535 之间")
    try:
        server = make_server(args.port)
    except OSError as error:
        parser.exit(1, "无法启动本机服务：" + str(error) + "\n")
    print("如书 · 请用此完整链接打开：\n" + server.url, flush=True)
    print("只运行信任的代码：程序具有当前用户的文件读写权限，并非安全沙箱。\n按 Ctrl-C 关闭服务与全部执行会话。", flush=True)

    def stop_server(signum, frame):
        raise KeyboardInterrupt

    old_sigterm = signal.signal(signal.SIGTERM, stop_server)
    try:
        if not args.no_browser:
            webbrowser.open(server.url)
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        signal.signal(signal.SIGTERM, old_sigterm)
    return 0
