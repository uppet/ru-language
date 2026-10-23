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

  // 文入桥（3c）：隐藏 input 承载系统 IME，把编辑行为翻译回如观文入事件。
  // 如观侧命令 text_focus／text_update／text_blur 驱动 input 的几何与内容；
  // input 侧的 keydown／beforeinput／composition 事件翻译回 text_key／
  // text_char／text_paste／text_comp_* 事件。input 永不拦截指针（画布
  // 的 mousedown 已 preventDefault，焦点切换全由如观命令决定）。
  const textBridge = { input: null, active: false, composing: false, mirror: '' };

  // 测文协议：用显示上下文实测字度（号的倍数），供如UI 文入光标、换行断点
  // 与真实字形对齐；候选窗桥的光标同步不受影响。引擎缺 measureText 时回退
  // 到协议缺省值。
  function measureTextMetrics() {
    const fallback = { 全: 1, 半: 0.56, 行: 1.5 };
    try {
      if (typeof ctx.measureText !== 'function') return fallback;
      ctx.font = '16px ' + FONT;
      const probe = ctx.measureText('字');
      if (!probe || typeof probe.width !== 'number') return fallback;
      const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
      const line = (probe.actualBoundingBoxAscent != null && probe.actualBoundingBoxDescent != null)
        ? (probe.actualBoundingBoxAscent + probe.actualBoundingBoxDescent) / 16
        : fallback.行;
      return {
        全: clamp(probe.width / 16, 0.5, 2),
        半: clamp(ctx.measureText('a').width / 16, 0.2, 1),
        行: clamp(line, 1, 2.5),
      };
    } catch (error) {
      return fallback;
    }
  }
  const TEXT_KEY_MAP = {
    Backspace: '退格', Delete: '删除', ArrowLeft: '左', ArrowRight: '右',
    ArrowUp: '上', ArrowDown: '下', Home: '家', End: '终', Enter: '回车',
    Tab: '跳格', Escape: '逃脱',
  };

  function dispatchText(type, fields) {
    if (canvasId === null) return;
    runtime.dispatch({ canvas_id: canvasId, event: Object.assign({ type }, fields) });
  }

  function textBridgeEnsure() {
    if (textBridge.input) return textBridge.input;
    const input = document.createElement('input');
    input.setAttribute('type', 'text');
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('autocapitalize', 'off');
    input.setAttribute('spellcheck', 'false');
    input.style.position = 'fixed';
    input.style.opacity = '0';
    input.style.pointerEvents = 'none';
    input.style.zIndex = '-1';
    input.style.border = '0';
    input.style.padding = '0';
    input.style.margin = '0';
    input.style.background = 'transparent';
    (document.body || document.documentElement).appendChild(input);
    input.addEventListener('keydown', (event) => {
      if (!textBridge.active || textBridge.composing || event.isComposing) return;
      const key = TEXT_KEY_MAP[event.key];
      if (key === undefined) return;
      event.preventDefault();
      dispatchText('text_key', { key });
    });
    input.addEventListener('beforeinput', (event) => {
      if (!textBridge.active || textBridge.composing || event.isComposing) return;
      const type = event.inputType || '';
      if (type === 'insertText' || type === 'insertFromPaste' || type === 'insertFromDrop') {
        const data = event.data || '';
        if (!data) return;
        event.preventDefault();
        if (type === 'insertText' && Array.from(data).length <= 1)
          dispatchText('text_char', { text: data });
        else
          dispatchText('text_paste', { text: data });
      } else if (type === 'insertLineBreak' || type === 'insertParagraph') {
        event.preventDefault();
        dispatchText('text_key', { key: '回车' });
      } else if (/^delete(Content|Word|SoftLine)Backward/.test(type)) {
        event.preventDefault();
        dispatchText('text_key', { key: '退格' });
      } else if (/^delete(Content|Word|SoftLine)Forward/.test(type)) {
        event.preventDefault();
        dispatchText('text_key', { key: '删除' });
      } else if (type === 'insertCompositionText') {
        // composition 事件驱动；不拦截。
      } else {
        event.preventDefault();
      }
    });
    input.addEventListener('input', (event) => {
      // 兜底：不支持 beforeinput 的引擎按差异翻译（组合期间忽略）。
      if (!textBridge.active || textBridge.composing) return;
      if (event.inputType) return;
      const value = input.value, old = textBridge.mirror;
      if (value === old) return;
      let prefix = 0;
      const maxPrefix = Math.min(value.length, old.length);
      while (prefix < maxPrefix && value[prefix] === old[prefix]) prefix += 1;
      let suffix = 0;
      while (suffix < Math.min(value.length, old.length) - prefix
             && value[value.length - 1 - suffix] === old[old.length - 1 - suffix]) suffix += 1;
      const removed = old.slice(prefix, old.length - suffix);
      const inserted = value.slice(prefix, value.length - suffix);
      const caretUnits = input.selectionStart == null ? old.length : input.selectionStart;
      if (removed && removed.length <= 32) {
        const back = prefix + removed.length >= caretUnits;
        const key = back ? '退格' : '删除';
        for (let i = 0; i < Array.from(removed).length; i += 1) dispatchText('text_key', { key });
      }
      if (inserted) {
        if (Array.from(inserted).length <= 4)
          for (const ch of inserted) dispatchText('text_char', { text: ch });
        else
          dispatchText('text_paste', { text: inserted });
      }
      textBridge.mirror = value;
    });
    input.addEventListener('compositionstart', () => {
      if (!textBridge.active) return;
      textBridge.composing = true;
      textBridge.compBase = input.selectionStart || 0;
      dispatchText('text_comp_start', {});
    });
    input.addEventListener('compositionupdate', (event) => {
      if (!textBridge.active || !textBridge.composing) return;
      const data = event.data || '';
      let caret = (input.selectionStart || 0) - (textBridge.compBase || 0);
      caret = Math.max(0, Math.min(caret, data.length));
      dispatchText('text_comp_update', { text: data, cursor: caret });
    });
    input.addEventListener('compositionend', (event) => {
      textBridge.composing = false;
      if (!textBridge.active) return;
      dispatchText('text_comp_end', { text: event.data || '' });
      textBridge.mirror = input.value;
    });
    textBridge.input = input;
    return input;
  }

  function textBridgeSet(text, cursor) {
    const input = textBridge.input;
    const units = Array.from(text).slice(0, cursor).join('').length;
    input.value = text;
    try { input.setSelectionRange(units, units); } catch (error) { /* 桩环境无选择区 */ }
  }

  function textBridgeFocus(command) {
    const input = textBridgeEnsure();
    const rect = canvas.getBoundingClientRect();
    const kx = rect.width / canvas.width, ky = rect.height / canvas.height;
    input.style.left = (rect.left + command.x * kx) + 'px';
    input.style.top = (rect.top + command.y * ky) + 'px';
    input.style.width = Math.max(1, command.width * kx) + 'px';
    input.style.height = Math.max(1, command.height * ky) + 'px';
    textBridge.active = true;
    if (!textBridge.composing) {
      textBridge.mirror = command.text;
      textBridgeSet(command.text, command.cursor);
    }
    if (document.activeElement !== input) {
      try { input.focus({ preventScroll: true }); }
      catch (error) { try { input.focus(); } catch (inner) { /* 桩环境无焦点 */ } }
    }
  }

  function textBridgeSync(command) {
    if (!textBridge.input || textBridge.composing) return;
    if (textBridge.input.value !== command.text) {
      textBridge.mirror = command.text;
      textBridgeSet(command.text, command.cursor);
    } else {
      try {
        const units = Array.from(command.text).slice(0, command.cursor).join('').length;
        textBridge.input.setSelectionRange(units, units);
      } catch (error) { /* 桩环境无选择区 */ }
    }
  }

  function textBridgeBlur() {
    textBridge.active = false;
    textBridge.composing = false;
    const input = textBridge.input;
    if (input && document.activeElement === input) input.blur();
  }

  const host = {
    textMetrics: measureTextMetrics(),
    textMeasurer(text, size) {
      ctx.font = size + 'px ' + FONT;
      return ctx.measureText(text).width;
    },
    emit(e) {
      if (e.type === 'graphics') {
        if (e.width && canvas.width !== e.width) { canvas.width = e.width; canvas.height = e.height; }
        for (const command of e.commands) {
          if (command.op === 'image_request') requestImage(command.id, command.source);
          else if (command.op === 'file_request') requestFile(command.id, command.source, command.mode);
          else if (command.op === 'image_release') images.delete(command.id);
          else if (command.op === 'text_focus') textBridgeFocus(command);
          else if (command.op === 'text_update') textBridgeSync(command);
          else if (command.op === 'text_blur') textBridgeBlur();
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

  // 桌面烟测挂钩：壳可用 window.__ruFrames 等待首帧后再截图。
  if (typeof desktopBridge === 'function' && desktopBridge()) {
    const hostEmit = host.emit.bind(host);
    host.emit = (e) => {
      if (e.type === 'graphics' && typeof window !== 'undefined')
        window.__ruFrames = (window.__ruFrames || 0) + 1;
      hostEmit(e);
    };
  }

  // __DESKTOP_GLUE__

  return {
    start(create) {
      const bridge = typeof desktopBridge === 'function' ? desktopBridge() : null;
      runtime = create(bridge ? Object.assign({}, host, bridge) : host);
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

_PAGE_DESKTOP = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  html, body {{ margin: 0; padding: 0; background: #16181d; height: 100%; overflow: hidden; }}
  canvas {{ display: block; width: 100vw; height: 100vh; touch-action: none; }}
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

# 桌面壳胶（--target desktop）：壳在文档起始注入 window.ruDesktop（services 静态
# 可知；request(json) 出壳异步执行），本胶只在其存在时激活。开窗缩放→改尺寸
# 事件→应用重排（缩放回路）；pointer 事件→touch_*（多点 pointerId 一等公民）。
_DESKTOP_GLUE = r"""
  function desktopBridge() {
    if (typeof window === 'undefined' || !window.ruDesktop) return null;
    return {
      services() {
        const list = window.ruDesktop.services;
        return typeof list === 'string' ? list.split(' ').filter(Boolean) : [];
      },
      handleService(canvasId, request) {
        if (typeof window.ruDesktop.request === 'function')
          window.ruDesktop.request(JSON.stringify(request));
      },
    };
  }

  // 壳完成文件操作后经 evaluate_javascript 回调此函数，把回执作为
  // service_response 事件送回运行时（与 Python 宿主同帧应答同一形状）。
  function desktopServiceResponse(json) {
    if (!runtime || canvasId === null) return;
    let event = null;
    try { event = JSON.parse(json); } catch (error) { return; }
    if (!event || typeof event !== 'object') return;
    runtime.dispatch({ canvas_id: canvasId, event: {
      type: 'service_response', id: event.id, ok: event.ok === true,
      value: typeof event.value === 'string' ? event.value : null,
      error: typeof event.error === 'string' ? event.error : null,
    } });
  }
  if (typeof window !== 'undefined') window.__ruServiceResponse = desktopServiceResponse;

  function desktopInputGlue() {
    if (typeof window === 'undefined' || !window.ruDesktop) return;
    window.addEventListener('resize', () => {
      if (canvasId === null || !runtime) return;
      const width = Math.round(canvas.clientWidth || window.innerWidth || 0);
      const height = Math.round(canvas.clientHeight || window.innerHeight || 0);
      if (width > 0 && height > 0)
        runtime.dispatch({ canvas_id: canvasId, event: { type: 'resize', width, height } });
    });
    const activePointers = new Set();
    canvas.addEventListener('pointerdown', (event) => {
      if (canvasId === null) return;
      activePointers.add(event.pointerId);
      const p = pointer(event);
      runtime.dispatch({ canvas_id: canvasId, event: { type: 'touch_start', id: event.pointerId, x: p.x, y: p.y } });
      event.preventDefault();
    });
    canvas.addEventListener('pointermove', (event) => {
      if (canvasId === null || !activePointers.has(event.pointerId)) return;
      const p = pointer(event);
      runtime.dispatch({ canvas_id: canvasId, event: { type: 'touch_move', id: event.pointerId, x: p.x, y: p.y } });
    });
    const pointerUp = (event) => {
      if (!activePointers.has(event.pointerId)) return;
      activePointers.delete(event.pointerId);
      const p = pointer(event);
      runtime.dispatch({ canvas_id: canvasId, event: { type: 'touch_end', id: event.pointerId, x: p.x, y: p.y } });
    };
    canvas.addEventListener('pointerup', pointerUp);
    canvas.addEventListener('pointercancel', pointerUp);
  }
  desktopInputGlue();
"""


def build_app_html(code, title="如UI 应用", assets_dir=None, desktop=False):
    """Compile Ru source to a self-contained interactive HTML app.

    desktop=True 产出 WebView 壳页：画布铺满窗口、开窗缩放走 改尺寸 回路、
    pointer 事件走 touch_* 多点通道、window.ruDesktop 存在时接 档 服务桥。
    """
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
    host_js = HOST_JS.replace("// __DESKTOP_GLUE__", _DESKTOP_GLUE) if desktop else HOST_JS
    page = _PAGE_DESKTOP if desktop else _PAGE
    return page.format(title=title, module_js=inlined, host_js=host_js, assets_js=assets_js)
