"""End-to-end smoke for the self-contained 如UI app page.

Builds app.html from the counter example, then runs the inlined module plus
canvas host under Node with a minimal DOM stub: assert initial paint, tap the
+1 button, advance the frame clock, and assert the repainted counter value.
"""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from rulang.app_builder import build_app_html

ROOT = Path(__file__).resolve().parent.parent
NODE = subprocess.run(["bash", "-c", "command -v node"], capture_output=True, text=True).stdout.strip()

DOM_STUB = r"""
const __rafQueue = [];
let __rafId = 0;
globalThis.requestAnimationFrame = (fn) => { const id = ++__rafId; __rafQueue.push({id, fn}); return id; };
globalThis.cancelAnimationFrame = (id) => {
  const i = __rafQueue.findIndex((e) => e.id === id);
  if (i >= 0) __rafQueue.splice(i, 1);
};
globalThis.__pump = (now) => {
  const q = __rafQueue.splice(0, __rafQueue.length);
  for (const e of q) e.fn(now);
};
let __clock = 0;
globalThis.performance = { now: () => __clock };

const __texts = [];
const __handlers = {};
function makeCtx() {
  return {
    setTransform() {}, save() {}, restore() {}, beginPath() {},
    rect() {}, ellipse() {}, moveTo() {}, lineTo() {}, closePath() {},
    clip() {}, arc() {}, fill() {}, stroke() {}, fillRect() {},
    fillText(text, x, y) { __texts.push({ text, x, y }); },
    font: '', fillStyle: '', strokeStyle: '', lineWidth: 1,
    textAlign: 'left', textBaseline: 'top',
  };
}
const canvas = {
  width: 0, height: 0,
  getContext() { return makeCtx(); },
  addEventListener(kind, fn) { __handlers[kind] = fn; },
  getBoundingClientRect() { return { left: 0, top: 0, width: this.width, height: this.height }; },
};
globalThis.document = { getElementById: (id) => (id === 'ru-canvas' ? canvas : null) };
globalThis.__texts = __texts;
globalThis.__handlers = __handlers;
"""

EPILOGUE = r"""
__pump(0);
const initial = __texts.map((t) => t.text);
if (!initial.includes('0') || !initial.includes('加一')) {
  console.error('FAIL: initial paint missing, got ' + JSON.stringify(initial));
  process.exit(1);
}
const btn = __texts.find((t) => t.text === '加一');
const before = __texts.length;
__handlers['mousedown']({ clientX: btn.x, clientY: btn.y, button: 0, preventDefault() {} });
__handlers['mouseup']({ clientX: btn.x, clientY: btn.y, button: 0, preventDefault() {} });
// 如UI runs at 30 fps: advance the fake clock past one frame interval.
__clock = 40;
__pump(40);
const after = __texts.slice(before).map((t) => t.text);
if (!after.includes('1')) {
  console.error('FAIL: counter did not increment, got ' + JSON.stringify(after));
  process.exit(1);
}
console.log('PAGE SMOKE OK');
"""


def extract_module_script(html):
    match = re.search(r'<script type="module">\n([\s\S]*?)\n</script>', html)
    assert match, "module script missing"
    return match.group(1).replace('<\\/script', '</script>')


@unittest.skipUnless(NODE, 'Node required for app page smoke')
class AppPageSmokeTest(unittest.TestCase):
    def test_counter_page_tap_increments_in_node(self):
        code = (ROOT / 'examples' / 'ruui-counter.ru').read_text(encoding='utf-8')
        html = build_app_html(code, title='如UI 计数器')
        self.assertIn('<canvas id="ru-canvas">', html)
        self.assertIn('RuHost.start(createRuntime)', html)
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'page_smoke.mjs'
            script.write_text(DOM_STUB + extract_module_script(html) + EPILOGUE,
                              encoding='utf-8')
            result = subprocess.run([NODE, str(script)], text=True,
                                    capture_output=True, timeout=30)
        if result.returncode != 0:
            self.fail(result.stderr)
        self.assertIn('PAGE SMOKE OK', result.stdout)

    def test_page_is_self_contained_single_file(self):
        code = (ROOT / 'examples' / 'ruui-quiz.ru').read_text(encoding='utf-8')
        html = build_app_html(code)
        # No external references: single <script type="module">, no src=, no link.
        self.assertEqual(html.count('<script type="module">'), 1)
        self.assertNotIn(' src=', html)
        self.assertNotIn('<link', html)
        self.assertIn('mouse_down', html)  # host forwards pointer events
        self.assertIn('requestAnimationFrame', html)  # host drives the frame loop

    def test_assets_dir_embeds_into_page(self):
        code = (ROOT / 'examples' / 'ruui-counter.ru').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # 1x1 PNG
            (root / 'dot.png').write_bytes(bytes.fromhex(
                '89504e470d0a1a0a0000000d494844520000000100000001080600000'
                '01f15c4890000000d4944415478da63fcffff3f030005fe02fea735814'
                '40000000049454e44ae426082'))
            (root / 'note.txt').write_text('你好资产', encoding='utf-8')
            (root / 'blob.bin').write_bytes(b'\x00\xff\x10')
            html = build_app_html(code, assets_dir=root)
        # PNG → data URL；UTF-8 文本内联；其余 base64。
        self.assertIn('data:image/png;base64,', html)
        self.assertIn('你好资产', html)
        self.assertIn('AP8Q', html)  # b'\x00\xff\x10' 的 base64


if __name__ == '__main__':
    unittest.main()
