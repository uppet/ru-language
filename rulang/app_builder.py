"""Self-contained 如UI web app builder.

Compiles a Ru source (typically importing the bundled third-party 如UI widget
library) to a single HTML file: the browser JS runtime plus a small 2D-canvas
host that renders the 如观 command stream and forwards mouse/frame events.
"""
from .browser_compiler import compile_browser
from .frontend import RuError

HOST_JS = r"""
const RuHost = (() => {
  const canvas = document.getElementById('ru-canvas');
  const ctx = canvas.getContext('2d');
  let runtime = null;
  let canvasId = null;
  let running = false;
  let fps = 60;
  let rafId = 0;
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
      if (c.transform) ctx.setTransform(...c.transform);
      ctx.font = (c.size || 16) + 'px ' + FONT;
      ctx.fillStyle = c.color || '#000000';
      ctx.textAlign = c.align || 'left';
      ctx.textBaseline = c.baseline || 'top';
      ctx.fillText(c.text, c.x, c.y);
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
        for (const command of e.commands) draw(command);
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
RuHost.start(createRuntime);
</script>
</body>
</html>
"""


def build_app_html(code, title="如UI 应用"):
    """Compile Ru source to a self-contained interactive HTML app."""
    module_js = compile_browser(code)
    if "export default function createRuntime" not in module_js:
        raise RuError("浏览器编译产物缺少默认导出", category="编译错误")
    # Inline the ES module body; keep the createRuntime function named so the
    # host can start it directly. Guard the one sequence that could break out
    # of the script element if it ever appeared in a Ru string literal.
    inlined = module_js.replace("export default function createRuntime", "function createRuntime", 1)
    inlined = inlined.replace("</script", "<\\/script")
    return _PAGE.format(title=title, module_js=inlined, host_js=HOST_JS)
