"""如UI 桌面目标（--target desktop）：分发目录、档桥语义与 WebKitGTK 烟测。"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rulang.desktop_builder import _BRIDGE_PY, write_desktop_app

NOTEPAD = (ROOT / "examples" / "ruui-notepad.ru").read_text(encoding="utf-8")


def load_bridge(directory):
    """在临时目录里装载壳内嵌的 DangBridge（与分发产物同一份代码）。"""
    namespace = {"__file__": str(Path(directory) / "run-webkitgtk.py")}
    exec(_BRIDGE_PY, namespace)
    return namespace["DangBridge"](), Path(directory)


def webkitgtk_available():
    if shutil.which("xvfb-run") is None:
        return False
    try:
        import gi
        gi.require_version("WebKit2", "4.1")
        from gi.repository import WebKit2  # noqa: F401
        gi.require_foreign("cairo")
    except (ValueError, ImportError):
        return False
    return True


class DesktopBuildTests(unittest.TestCase):
    def test_desktop_dir_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "app.desktop"
            write_desktop_app(out, NOTEPAD, title="记事本")
            names = sorted(p.name for p in out.iterdir())
            self.assertEqual(names, ["README.txt", "index.html",
                                     "run-pywebview.py", "run-webkitgtk.py"])
            page = (out / "index.html").read_text(encoding="utf-8")
            # 桌面胶：服务桥挂钩、触屏通道、缩放回路。
            self.assertIn("window.ruDesktop", page)
            self.assertIn("__ruServiceResponse", page)
            self.assertIn("touch_start", page)
            self.assertIn("type: 'resize'", page.replace('"', "'"))
            self.assertIn("width: 100vw", page)
            # 运行器可执行。
            self.assertTrue((out / "run-webkitgtk.py").stat().st_mode & 0o111)
            self.assertTrue((out / "run-pywebview.py").stat().st_mode & 0o111)

    def test_ui_page_has_no_desktop_glue(self):
        from rulang.app_builder import build_app_html
        page = build_app_html(NOTEPAD, title="记事本")
        self.assertNotIn("__ruServiceResponse", page)
        self.assertNotIn("ruDesktop", page)
        desktop = build_app_html(NOTEPAD, title="记事本", desktop=True)
        self.assertIn("__ruServiceResponse", desktop)

    def test_cli_build_desktop(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "np.desktop"
            result = subprocess.run(
                [sys.executable, str(ROOT / "ru"), "build",
                 str(ROOT / "examples" / "ruui-notepad.ru"),
                 "--target", "desktop", "-o", str(out)],
                text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((out / "index.html").is_file())
            self.assertIn("桌面分发目录", result.stdout)

    def test_cli_rejects_cc_with_desktop(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(ROOT / "ru"), "build",
                 str(ROOT / "examples" / "ruui-notepad.ru"),
                 "--target", "desktop", "--cc", "cc", "-o", str(Path(directory) / "x")],
                text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 1)
            self.assertIn("不能使用 --cc", result.stderr + result.stdout)


class DangBridgeTests(unittest.TestCase):
    def test_write_append_and_list(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, root = load_bridge(directory)
            response = bridge.execute({"id": 1, "service": "档", "action": "写",
                                       "path": "notes/a.txt", "text": "你好", "flag": False})
            self.assertEqual(response, {"id": 1, "ok": True, "value": None, "error": None})
            self.assertEqual((root / "notes" / "a.txt").read_text(encoding="utf-8"), "你好")
            response = bridge.execute({"id": 2, "service": "档", "action": "写",
                                       "path": "notes/a.txt", "text": "世界", "flag": True})
            self.assertTrue(response["ok"])
            self.assertEqual((root / "notes" / "a.txt").read_text(encoding="utf-8"), "你好世界")
            response = bridge.execute({"id": 3, "service": "档", "action": "列",
                                       "path": "notes", "text": "", "flag": False})
            self.assertTrue(response["ok"])
            self.assertEqual(response["value"], "a.txt")
            self.assertIsNone(response["error"])

    def test_traversal_and_absolute_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, _root = load_bridge(directory)
            for path in ("../out.txt", "a/../../out.txt"):
                response = bridge.execute({"id": 1, "service": "档", "action": "写",
                                           "path": path, "text": "x", "flag": False})
                self.assertFalse(response["ok"])
                self.assertIn("件目", response["error"])
            response = bridge.execute({"id": 2, "service": "档", "action": "写",
                                       "path": "/tmp/out.txt", "text": "x", "flag": False})
            self.assertFalse(response["ok"])
            self.assertIn("绝对路径", response["error"])

    def test_unknown_service_and_action(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, _root = load_bridge(directory)
            response = bridge.execute({"id": 1, "service": "网", "action": "取",
                                       "path": "", "text": "", "flag": False})
            self.assertFalse(response["ok"])
            self.assertIn("无此服务", response["error"])
            response = bridge.execute({"id": 2, "service": "档", "action": "删",
                                       "path": "x", "text": "", "flag": False})
            self.assertFalse(response["ok"])
            self.assertIn("不识此操作", response["error"])


@unittest.skipUnless(webkitgtk_available(), "需要 WebKitGTK GI + xvfb-run")
class WebKitGtkSmokeTests(unittest.TestCase):
    def test_notepad_renders_first_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "app.desktop"
            write_desktop_app(out, NOTEPAD, title="记事本")
            result = subprocess.run(
                ["xvfb-run", "-a", sys.executable,
                 str(out / "run-webkitgtk.py"), "--smoke"],
                text=True, capture_output=True, timeout=120)
            self.assertIn("SMOKE_OK", result.stdout + result.stderr,
                          result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
