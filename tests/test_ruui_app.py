"""End-to-end smoke for the self-contained 如UI app page.

Builds app.html from the counter example, then runs the inlined module plus
canvas host under Node with a minimal DOM stub: assert initial paint, tap the
+1 button, advance the frame clock, and assert the repainted counter value.
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from rulang.app_builder import build_app_html

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which('node') or ''

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
const __rects = [];
const __handlers = {};
function makeCtx() {
  return {
    setTransform() {}, save() {}, restore() {}, beginPath() {},
    rect(x, y, w, h) { __rects.push({ x, y, w, h }); },
    measureText(text) { return { width: Array.from(text).length * 8 }; },
    ellipse() {}, moveTo() {}, lineTo() {}, closePath() {},
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
globalThis.__inputs = [];
function makeInput() {
  const listeners = {};
  const input = {
    value: '', style: {}, _sel: 0,
    setAttribute() {},
    get selectionStart() { return this._sel; },
    setSelectionRange(start, end) { this._sel = start; },
    focus() { document.activeElement = input; },
    blur() { if (document.activeElement === input) document.activeElement = null; },
    addEventListener(kind, fn) { listeners[kind] = fn; },
    dispatch(kind, event) {
      if (listeners[kind]) listeners[kind](Object.assign({ preventDefault() {} }, event));
    },
  };
  __inputs.push(input);
  return input;
}
globalThis.document = {
  getElementById: (id) => (id === 'ru-canvas' ? canvas : null),
  createElement: (tag) => makeInput(),
  body: { appendChild(el) { this.child = el; } },
  activeElement: null,
};
globalThis.__texts = __texts;
globalThis.__rects = __rects;
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

    def test_textfield_ime_bridge_in_node(self):
        html = build_app_html(TEXTFIELD_PROGRAM, title='如UI 文入')
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'textfield_page.mjs'
            script.write_text(DOM_STUB + extract_module_script(html) + TEXTFIELD_EPILOGUE,
                              encoding='utf-8')
            result = subprocess.run([NODE, str(script)], text=True,
                                    capture_output=True, timeout=30)
        if result.returncode != 0:
            self.fail(result.stderr)
        self.assertIn('TEXTFIELD PAGE OK', result.stdout)

    @unittest.skipUnless(shutil.which('node'), 'node required for page smoke test')
    def test_page_measures_real_text_metrics_for_caret(self):
        # stub measureText 每字恒 8px：实测钩生效时打 '小' 光标 x＝9.6＋8＝17.6；
        # 若页主没接测文协议，回退宽度为 1.0×16＝16，光标会是 25.6。
        html = build_app_html(TEXTFIELD_PROGRAM, title='如UI 文入')
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'textfield_caret_page.mjs'
            script.write_text(DOM_STUB + extract_module_script(html) + TEXTFIELD_CARET_EPILOGUE,
                              encoding='utf-8')
            result = subprocess.run([NODE, str(script)], text=True,
                                    capture_output=True, timeout=30)
        if result.returncode != 0:
            self.fail(result.stderr)
        self.assertIn('TEXTFIELD CARET OK', result.stdout)

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


TEXTFIELD_EPILOGUE = r"""
__pump(0);
const placeholder = __texts.find((t) => t.text === '姓名');
if (!placeholder) { console.error('FAIL: placeholder missing'); process.exit(1); }
const fx = placeholder.x + 1, fy = placeholder.y + 1;
const click = (x, y) => {
  __handlers['mousedown']({ clientX: x, clientY: y, button: 0, preventDefault() {} });
  __handlers['mouseup']({ clientX: x, clientY: y, button: 0, preventDefault() {} });
};
click(fx, fy);
const input = __inputs[0];
if (!input) { console.error('FAIL: hidden input not created'); process.exit(1); }
if (document.activeElement !== input) { console.error('FAIL: input not focused'); process.exit(1); }
if (input.value !== '' || input.style.left === undefined) {
  console.error('FAIL: focus geometry/value, got ' + JSON.stringify({ value: input.value, left: input.style.left }));
  process.exit(1);
}
// beforeinput 单字 → text_char → 入更新 同步回 input。
input.dispatch('beforeinput', { inputType: 'insertText', data: '小' });
if (input.value !== '小') { console.error('FAIL: insertText, got ' + input.value); process.exit(1); }
// keydown Backspace → 退格。
input.dispatch('keydown', { key: 'Backspace' });
if (input.value !== '') { console.error('FAIL: backspace, got ' + input.value); process.exit(1); }
// 重新输入并走一遍 IME 组合：组开始/更新/结束 → 定字恰一次上屏。
input.dispatch('beforeinput', { inputType: 'insertText', data: '甲' });
input.dispatch('compositionstart', {});
input.dispatch('compositionupdate', { data: 'ni' });
input.dispatch('compositionend', { data: '你' });
if (input.value !== '甲你') { console.error('FAIL: ime commit, got ' + input.value); process.exit(1); }
// 点按框外 → 失焦提交，input 交出焦点。
click(4, 600);
if (document.activeElement !== null) { console.error('FAIL: blur, still focused'); process.exit(1); }
console.log('TEXTFIELD PAGE OK');
"""

TEXTFIELD_CARET_EPILOGUE = r"""
__pump(0);
const placeholder = __texts.find((t) => t.text === '姓名');
if (!placeholder) { console.error('FAIL: placeholder missing'); process.exit(1); }
const click = (x, y) => {
  __handlers['mousedown']({ clientX: x, clientY: y, button: 0, preventDefault() {} });
  __handlers['mouseup']({ clientX: x, clientY: y, button: 0, preventDefault() {} });
};
click(placeholder.x + 1, placeholder.y + 1);
const input = __inputs[0];
if (!input) { console.error('FAIL: hidden input not created'); process.exit(1); }
input.dispatch('beforeinput', { inputType: 'insertText', data: '小' });
__rects.length = 0;
__texts.length = 0;
__pump(40);
// stub 实测：'小' 宽 8px，值区起始 x 9.6 → 光标 x 17.6（回退度量会给 25.6）。
const carets = __rects.filter((r) => r.w === 2);
if (!carets.length) { console.error('FAIL: caret rect missing'); process.exit(1); }
const last = carets[carets.length - 1];
if (Math.abs(last.x - (9.6 + 8)) > 1e-9) {
  console.error('FAIL: caret x, got ' + JSON.stringify(last));
  process.exit(1);
}
console.log('TEXTFIELD CARET OK');
"""

TEXTFIELD_PROGRAM = """\
尽取 外言 '如UI'.
名 取 [''].
机 取 新 应用 宽: 360 高: 640 构: (算:
    得 列 [
        (文入 (名[0]) '姓名' (作 新文 为 句: 名[0] 取 新文. 为)),
        (文 (名[0]))
    ].
法).
机 其 运行.
"""


if __name__ == '__main__':
    unittest.main()
