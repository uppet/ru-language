"""Self-contained 如UI web app builder.

Compiles a Ru source (typically importing the bundled third-party 如UI widget
library) to a single HTML file: the browser JS runtime plus a small 2D-canvas
host that renders the 如观 command stream and forwards mouse/frame events.
"""
from .browser_compiler import compile_browser
from .frontend import RuError
import base64
import json
from pathlib import Path

MAX_EMBEDDED_ASSETS = 16 * 1024 * 1024
ASSET_IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}


def _embed_assets(assets_dir):
    """Embed a directory as the browser host's asset table for 件目/图载/件载.

    Images become data URLs, UTF-8 files stay text, everything else becomes
    base64. Keys are forward-slash relative paths under the directory.
    """
    root = Path(assets_dir)
    if not root.is_dir():
        raise RuError("资产目录不存在：" + str(root), category="用法错误")
    assets = {}
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if not path.is_file():
            raise RuError("资产目录含非常规文件：" + str(path), category="用法错误")
        key = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        media = ASSET_IMAGE_TYPES.get(path.suffix.lower().lstrip("."))
        if media is not None:
            payload = "data:" + media + ";base64," + base64.b64encode(raw).decode("ascii")
            assets[key] = {"kind": "image", "data": payload}
            total += len(payload.encode("utf-8"))
        else:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                payload = base64.b64encode(raw).decode("ascii")
                assets[key] = {"kind": "binary", "data": payload}
                total += len(payload.encode("utf-8"))
            else:
                assets[key] = {"kind": "text", "data": text}
                total += len(raw)
    if total > MAX_EMBEDDED_ASSETS:
        raise RuError("资产内嵌超过 16 MiB；请缩减 --assets 目录", category="用法错误")
    return assets

HOST_JS = r"""
const RuHost = (() => {
  const canvas = document.getElementById('ru-canvas');
  const ctx = canvas.getContext('2d');
  let runtime = null;
  let canvasId = null;
  let running = false;
  let fps = 60;
  let rafId = 0;
  const images = new Map();
  const files = new Map();

  function loadEvent(type, id, error) {
    runtime.dispatch({ canvas_id: canvasId, event: { type, id, error } });
  }

  function requestImage(id, source) {
    if (images.has(id)) return;
    const entry = { status: 'loading' };
    images.set(id, entry);
    const failReady = (message) => {
      if (entry.status === 'loading') { entry.status = 'failed'; loadEvent('image_failed', id, message); }
    };
    const ready = (img) => {
      if (entry.status !== 'loading') return;
      entry.status = 'ready'; entry.img = img;
      runtime.dispatch({ canvas_id: canvasId, event: { type: 'image_ready', id, width: img.naturalWidth, height: img.naturalHeight } });
    };
    const timer = setTimeout(() => failReady('装载超时'), 10000);
    const finish = (work) => { clearTimeout(timer); work(); };
    const asset = Object.prototype.hasOwnProperty.call(ASSETS, source) ? ASSETS[source] : null;
    const fromImage = (img) => {
      img.onload = () => finish(() => ready(img));
      img.onerror = () => finish(() => failReady('装载失败'));
    };
    if (asset && asset.kind === 'image') {
      const img = new Image(); fromImage(img); img.src = asset.data;
    } else if (/^https?:\/\//.test(source)) {
      fetch(source).then((response) => {
        if (!response.ok) throw new Error('bad');
        return response.blob();
      }).then((blob) => {
        if (blob.size > 67108864) throw new Error('big');
        const img = new Image(); fromImage(img); img.src = URL.createObjectURL(blob);
      }).catch(() => finish(() => failReady('读不到文件')));
    } else {
      finish(() => failReady('读不到文件'));
    }
  }

  function bytesToBase64(bytes) {
    let out = '';
    for (let i = 0; i < bytes.length; i += 32768)
      out += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768));
    return btoa(out);
  }

  function requestFile(id, source, mode) {
    if (files.has(id)) return;
    const entry = { status: 'loading' };
    files.set(id, entry);
    const failReady = (message) => {
      if (entry.status === 'loading') { entry.status = 'failed'; loadEvent('file_failed', id, message); }
    };
    const ready = (text) => {
      if (entry.status !== 'loading') return;
      entry.status = 'ready';
      runtime.dispatch({ canvas_id: canvasId, event: { type: 'file_ready', id, text } });
    };
    const timer = setTimeout(() => failReady('装载超时'), 10000);
    const finish = (work) => { clearTimeout(timer); work(); };
    const asset = Object.prototype.hasOwnProperty.call(ASSETS, source) ? ASSETS[source] : null;
    if (asset) {
      finish(() => {
        if (mode === '文') {
          if (asset.kind === 'text') ready(asset.data);
          else failReady('不是有效 UTF-8 文本');
        } else if (asset.kind === 'binary') {
          ready(asset.data);
        } else if (asset.kind === 'text') {
          ready(bytesToBase64(new TextEncoder().encode(asset.data)));
        } else {
          ready(asset.data.slice(asset.data.indexOf(',') + 1));
        }
      });
      return;
    }
    if (/^https?:\/\//.test(source)) {
      fetch(source).then((response) => {
        if (!response.ok) throw new Error('bad');
        return response.blob();
      }).then((blob) => {
        if (blob.size > 4194304) throw new Error('big');
        if (mode === '文') return blob.text().then((text) => finish(() => ready(text)));
        return blob.arrayBuffer().then((buffer) => {
          const encoded = bytesToBase64(new Uint8Array(buffer));
          if (encoded.length > 4194304) throw new Error('big');
          finish(() => ready(encoded));
        });
      }).catch(() => finish(() => failReady('读不到文件')));
    } else {
      finish(() => failReady('读不到文件'));
    }
  }
  let lastFrame = 0;

  const FONT = '"PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif';

  function styleOf(c) {
    if (c.stroke_width !== undefined && c.stroke_width > 0) ctx.lineWidth = c.stroke_width;
    return c;
  }

  function pathOf(c) {
    ctx.beginPath();
    if (c.op === 'rect') {
      ctx.rect(c.x, c.y, c.width, c.height);
    } else if (c.op === 'ellipse') {
      ctx.ellipse(c.x + c.width / 2, c.y + c.height / 2,
        Math.abs(c.width / 2), Math.abs(c.height / 2), 0, 0, Math.PI * 2);
    } else if (c.op === 'triangle') {
      ctx.moveTo(c.x1, c.y1); ctx.lineTo(c.x2, c.y2); ctx.lineTo(c.x3, c.y3); ctx.closePath();
    } else if (c.op === 'line') {
      ctx.moveTo(c.x1, c.y1); ctx.lineTo(c.x2, c.y2);
    } else if (c.op === 'polygon' || c.op === 'polyline') {
      const pts = c.points;
      if (pts.length) {
        ctx.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
        if (c.op === 'polygon') ctx.closePath();
      }
    } else if (c.op === 'arc') {
      ctx.arc(c.x, c.y, c.radius, c.start, c.end);
    } else if (c.op === 'sector') {
      ctx.moveTo(c.x, c.y); ctx.arc(c.x, c.y, c.radius, c.start, c.end); ctx.closePath();
    }
  }

  function draw(c) {
    if (c.op === 'background') {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = c.color;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      return;
    }
    if (c.op === 'text') {
      ctx.save();
      for (const clip of c.clips || []) {
        ctx.beginPath();
        if (clip.transform) ctx.setTransform(...clip.transform);
        ctx.rect(clip.x, clip.y, clip.width, clip.height);
        ctx.clip();
      }
      if (c.transform) ctx.setTransform(...c.transform);
      ctx.font = (c.size || 16) + 'px ' + FONT;
      ctx.fillStyle = c.color || '#000000';
      ctx.textAlign = c.align || 'left';
      ctx.textBaseline = c.baseline || 'top';
      ctx.fillText(c.text, c.x, c.y);
      for (const _ of c.clips || []) ctx.restore();
      ctx.restore();
      return;
    }
    if (c.op === 'draw_image') {
      const entry = images.get(c.id);
      ctx.save();
      for (const clip of c.clips || []) {
        ctx.beginPath();
        if (clip.transform) ctx.setTransform(...clip.transform);
        ctx.rect(clip.x, clip.y, clip.width, clip.height);
        ctx.clip();
      }
      if (c.transform) ctx.setTransform(...c.transform);
      if (entry && entry.status === 'ready') ctx.drawImage(entry.img, c.x, c.y, c.width, c.height);
      for (const _ of c.clips || []) ctx.restore();
      ctx.restore();
      return;
    }
    ctx.save();
    for (const clip of c.clips || []) {
      ctx.save();
      ctx.setTransform(...(clip.transform || [1, 0, 0, 1, 0, 0]));
      ctx.beginPath();
      ctx.rect(clip.x, clip.y, clip.width, clip.height);
      ctx.clip();
    }
    if (c.transform) ctx.setTransform(...c.transform);
    styleOf(c);
    pathOf(c);
    if (c.fill) { ctx.fillStyle = c.fill; ctx.fill(); }
    if (c.stroke && c.stroke_width !== 0) { ctx.strokeStyle = c.stroke; ctx.stroke(); }
    for (const _ of c.clips || []) ctx.restore();
    ctx.restore();
  }

  function frame(now) {
    rafId = 0;
    if (!running) return;
    const interval = 1000 / fps;
    if (now - lastFrame >= interval - 1) {
      lastFrame = now;
      runtime.dispatch({ canvas_id: canvasId, event: { type: 'frame' } });
    }
    rafId = requestAnimationFrame(frame);
  }

  function pointer(event) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left) * (canvas.width / rect.width),
      y: (event.clientY - rect.top) * (canvas.height / rect.height),
    };
  }

  const host = {
    emit(e) {
      if (e.type === 'graphics') {
        if (e.width && canvas.width !== e.width) { canvas.width = e.width; canvas.height = e.height; }
        for (const command of e.commands) {
          if (command.op === 'image_request') requestImage(command.id, command.source);
          else if (command.op === 'file_request') requestFile(command.id, command.source, command.mode);
          else if (command.op === 'image_release') images.delete(command.id);
          else draw(command);
        }
        canvasId = e.canvas_id;
        running = e.running;
        if (e.fps) fps = e.fps;
        if (running && !rafId) { lastFrame = performance.now(); rafId = requestAnimationFrame(frame); }
        if (!running && rafId) { cancelAnimationFrame(rafId); rafId = 0; }
      } else if (e.type === 'output') {
        console.log(e.text);
      }
    },
  };

  for (const [dom, ru] of [['mousedown', 'mouse_down'], ['mousemove', 'mouse_move'], ['mouseup', 'mouse_up']]) {
    canvas.addEventListener(dom, (event) => {
      if (canvasId === null) return;
      const p = pointer(event);
      runtime.dispatch({
        canvas_id: canvasId,
        event: { type: ru, x: p.x, y: p.y, button: event.button },
      });
      event.preventDefault();
    });
  }

  return {
    start(create) {
      runtime = create(host);
    },
  };
})();
"""

_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  html, body {{ margin: 0; padding: 0; background: #16181d; height: 100%; }}
  body {{ display: flex; align-items: flex-start; justify-content: center; }}
  canvas {{ margin: 16px 0; max-width: 96vw; height: auto; box-shadow: 0 4px 32px #000a; border-radius: 6px; touch-action: none; }}
</style>
</head>
<body>
<canvas id="ru-canvas"></canvas>
<script type="module">
{module_js}
{host_js}
const ASSETS = {assets_js};
RuHost.start(createRuntime);
</script>
</body>
</html>
"""


def build_app_html(code, title="如UI 应用", assets_dir=None):
    """Compile Ru source to a self-contained interactive HTML app."""
    module_js = compile_browser(code)
    if "export default function createRuntime" not in module_js:
        raise RuError("浏览器编译产物缺少默认导出", category="编译错误")
    assets = _embed_assets(assets_dir) if assets_dir is not None else {}
    assets_js = json.dumps(assets, ensure_ascii=False).replace("</script", "<\\/script")
    # Inline the ES module body; keep the createRuntime function named so the
    # host can start it directly. Guard the one sequence that could break out
    # of the script element if it ever appeared in a Ru string literal.
    inlined = module_js.replace("export default function createRuntime", "function createRuntime", 1)
    inlined = inlined.replace("</script", "<\\/script")
    return _PAGE.format(title=title, module_js=inlined, host_js=HOST_JS, assets_js=assets_js)
