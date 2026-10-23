"""如UI 桌面目标（--target desktop）：WebView 壳 + 档服务桥。

产物是一个可双击的分发目录：
- index.html：自包含页面（同 --target ui，加桌面胶：缩放回路／触屏通道／服务桥挂钩）
- run-webkitgtk.py：Linux 原生 WebKitGTK 壳（仅需系统 PyGObject，无 pip 依赖）
- run-pywebview.py：跨平台壳（Windows WebView2／macOS WKWebView／Linux WebKitGTK，pip install pywebview）
- README.txt：依赖与诚实说明

壳的职责只有两件：开窗嵌 WebView，以及在文档起始注入 window.ruDesktop
（services 静态可知；request(json) 经各引擎的消息通道出壳异步执行，完成后
由壳回调 window.__ruServiceResponse 把回执送回运行时）。页内运行时仍是
JS——启动暖 WebView 引擎、内存是 WebView 量级，如实定位。
"""
from .app_builder import build_app_html
from .frontend import RuError
import os
from pathlib import Path

# 档服务桥：根＝index.html 所在目录（程序目录语义）；拒绝对径与 .. 逃逸
# （件目语义）；写 支持 flag 追加（添写）；列 返回空格连接名表。与 Python
# GraphicsHost 的档服务同形状同语义（tests/test_ruui_services.py 校准）。
_BRIDGE_PY = '''
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"


class DangBridge:
    """档服务：{id, ok, value, error} 单形状回执，与 Python 宿主一致。"""

    def execute(self, request):
        ok, value, error = False, None, None
        try:
            if request.get("service") != "档":
                raise ValueError("宿主无此服务：" + str(request.get("service")))
            path = request.get("path") or ""
            if path.startswith("/"):
                raise ValueError("径 不可为绝对路径")
            target = (ROOT / path).resolve()
            if ROOT not in (target, *target.parents):
                raise ValueError("径 越出件目")
            action = request.get("action")
            if action == "写":
                target.parent.mkdir(parents=True, exist_ok=True)
                mode = "a" if request.get("flag") else "w"
                with target.open(mode, encoding="utf-8") as stream:
                    stream.write(request.get("text") or "")
                ok = True
            elif action == "列":
                if not target.is_dir():
                    raise ValueError("径 不是目录")
                value = " ".join(sorted(entry.name for entry in target.iterdir()))
                ok = True
            else:
                raise ValueError("档 不识此操作：" + str(action))
        except (OSError, ValueError) as exc:
            error = str(exc)[:512]
        return {"id": request.get("id"), "ok": ok,
                "value": value if ok else None, "error": error if not ok else None}


def respond(webview, callback_js, payload):
    """壳完成文件操作后经 JS 回调把回执送回运行时。"""
    script = callback_js % json.dumps(json.dumps(payload))
    evaluate(webview, script)


def evaluate(webview, script):
    raise NotImplementedError
'''

_WEBKITGTK_PY = '''#!/usr/bin/env python3
"""如UI 桌面壳（Linux WebKitGTK）：python3 run-webkitgtk.py

依赖：sudo apt install gir1.2-webkit2-4.1（Debian/Ubuntu；其他发行版装
对应的 webkit2gtk 4.1 GI 包）。壳内跑的仍是 JS 运行时。
"""
import gi

gi.require_foreign("cairo")  # get_snapshot 返回 cairo.Surface

gi.require_version("Gtk", "3.0")
try:
    gi.require_version("WebKit2", "4.1")
except ValueError:
    gi.require_version("WebKit2", "4.0")
from gi.repository import GLib, Gtk, WebKit2  # noqa: E402

__BRIDGE__

def evaluate(webview, script):
    try:
        webview.evaluate_javascript(script, -1, None, None, None)
    except AttributeError:  # 旧版 WebKit2（<2.40）无 evaluate_javascript
        webview.run_javascript(script, None, None, None)


def evaluate_text(webview, script, callback):
    def done(webview, result):
        try:
            callback(webview.evaluate_javascript_finish(result).to_string())
        except (TypeError, ValueError, AttributeError):
            callback("")
    try:
        webview.evaluate_javascript(script, -1, None, None, None, done)
    except (AttributeError, TypeError):
        callback("")


def evaluate_result(webview, script, callback):
    """取 JS 表达式结果（GVariant 数值／布尔）；旧版回退为 0。"""
    def done(webview, result):
        try:
            value = webview.evaluate_javascript_finish(result)
            callback(int(value.to_string()))
        except (TypeError, ValueError, AttributeError):
            callback(0)
    try:
        webview.evaluate_javascript(script, -1, None, None, None, done)
    except (AttributeError, TypeError):
        callback(0)


def main():
    smoke = "--smoke" in sys.argv[1:]
    bridge = DangBridge()
    window = Gtk.Window(title="如UI 应用")
    window.set_default_size(420, 760)
    webview = WebKit2.WebView()
    settings = webview.get_settings()
    settings.set_allow_file_access_from_file_urls(True)
    settings.set_enable_write_console_messages_to_stdout(True)
    window.add(webview)
    manager = webview.get_user_content_manager()
    manager.register_script_message_handler("ruDesktop")

    def on_service(_manager, result):
        try:
            request = json.loads(result.get_js_value().to_string())
        except (ValueError, AttributeError):
            return
        respond(webview, "window.__ruServiceResponse(%s)",
                bridge.execute(request))

    manager.connect("script-message-received::ruDesktop", on_service)
    # 文档起始注入：services 静态可知；request 经消息通道出壳异步执行。
    manager.add_script(WebKit2.UserScript(
        "window.ruDesktop={services:'档',request:(s)=>"
        "window.webkit.messageHandlers.ruDesktop.postMessage(s)};",
        WebKit2.UserContentInjectedFrames.TOP_FRAME,
        WebKit2.UserScriptInjectionTime.START, None, None))
    window.connect("destroy", Gtk.main_quit)
    webview.load_uri("file://" + str(INDEX))
    window.show_all()
    if smoke:
        GLib.timeout_add(250, poll_frames, webview, window)
    Gtk.main()


_state = {"ticks": 0}


def poll_frames(webview, window):
    """烟测：等首帧后截屏并断言非纯色，然后退出（0=通过）。"""
    _state["ticks"] += 1
    if _state["ticks"] in (4, 12, 24):
        def show(value):
            print("STATE ticks=%d %s" % (_state["ticks"], value))
        evaluate_text(webview,
                      "JSON.stringify({frames:window.__ruFrames|0,"
                      " rd:String((window.ruDesktop||{}).services),"
                      " err:window.__ruErr||null})", show)
    if _state["ticks"] > 40:  # 10 秒无帧＝失败
        print("SMOKE_FAIL no-frame")
        Gtk.main_quit()
        return GLib.SOURCE_REMOVE
    def got(frames):
        if frames < 2:
            GLib.timeout_add(250, poll_frames, webview, window)
            return
        def snap_ready(webview, result):
            try:
                surface = webview.get_snapshot_finish(result)
            except (AttributeError, GLib.Error) as exc:
                print("SMOKE_FAIL snapshot: %s" % exc)
                Gtk.main_quit()
                return
            data = surface.get_data()
            distinct = len(set(bytes(data[::977])))
            print("SMOKE_OK frames=%d distinct=%d" % (frames, distinct)
                   if distinct > 4 else "SMOKE_FAIL blank distinct=%d" % distinct)
            Gtk.main_quit()
        webview.get_snapshot(WebKit2.SnapshotRegion.VISIBLE,
                             WebKit2.SnapshotOptions.NONE, None, snap_ready)
    evaluate_result(webview, "window.__ruFrames|0", got)
    return GLib.SOURCE_REMOVE


if __name__ == "__main__":
    import sys
    main()
'''

_PYWEBVIEW_PY = '''#!/usr/bin/env python3
"""如UI 桌面壳（跨平台 pywebview）：python3 run-pywebview.py

依赖：pip install pywebview
  Windows → WebView2（系统自带）；macOS → WKWebView；Linux → WebKitGTK
  （另需系统 WebKitGTK GI 包）。壳内跑的仍是 JS 运行时。
"""
import json  # noqa: E402

import webview  # noqa: E402

__BRIDGE__


class Api:
    def __init__(self, window_holder):
        self.window_holder = window_holder
        self.bridge = DangBridge()

    def service(self, raw):
        return self.bridge.execute(json.loads(raw))


def main():
    holder = {}
    api = Api(holder)
    window = webview.create_window("如UI 应用", str(INDEX),
                                   width=420, height=760, js_api=api)
    holder["window"] = window

    def on_loaded():
        window.evaluate_js(
            "window.ruDesktop={services:'档',request:(s)=>"
            "window.pywebview.api.service(s).then((r)=>"
            "window.__ruServiceResponse(JSON.stringify(r)))};")

    window.events.loaded += on_loaded
    webview.start(private_mode=False)


if __name__ == "__main__":
    main()
'''

_README = """如UI 桌面应用（--target desktop 产物）
=====================================

index.html 是自包含页面：JS 运行时 + 2D 画布宿主 + 桌面胶
（窗口缩放 → 改尺寸 重排回路；触屏 pointer → touch_* 多点通道）。

运行（任选其一）：
  Linux   python3 run-webkitgtk.py   # 仅需系统 PyGObject + WebKitGTK GI
          sudo apt install gir1.2-webkit2-4.1
  跨平台  python3 run-pywebview.py   # pip install pywebview
          Windows 用 WebView2、macOS 用 WKWebView、Linux 用 WebKitGTK

档服务（机 其 服务 '档'）：写/添写/列 落到本目录（程序目录语义），
拒绝对径与 .. 越界（件目语义）；壳在文档起始注入 window.ruDesktop。

诚实定位：壳里跑的仍是 JS 运行时——启动暖 WebView（百毫秒级）、
内存 WebView 量级（百 MB 级）、Linux 需系统 WebKitGTK。
WebKitGTK 壳在本仓库开发机实测；WebView2/WKWebView 路径与
WebKitGTK 同构（消息通道 + evaluateJS 回执），未经真机核验。
"""


def write_desktop_app(output_dir, code, title, assets_dir=None):
    """写桌面分发目录；返回目录路径。"""
    out = Path(output_dir)
    if out.exists() and not out.is_dir():
        raise RuError("桌面目标输出须为目录：" + str(out), category="用法错误")
    out.mkdir(parents=True, exist_ok=True)
    page = build_app_html(code, title=title, assets_dir=assets_dir, desktop=True)
    for name, content, executable in (
        ("index.html", page, False),
        ("run-webkitgtk.py", _WEBKITGTK_PY.replace("__BRIDGE__", _BRIDGE_PY), True),
        ("run-pywebview.py", _PYWEBVIEW_PY.replace("__BRIDGE__", _BRIDGE_PY), True),
        ("README.txt", _README, False),
    ):
        path = out / name
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if executable:
            path.chmod(0o755)
    return out
