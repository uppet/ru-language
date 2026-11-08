#!/usr/bin/env bash
# ui-shot.sh — 如UI 网页目标（--target ui）截图：构建自包含 HTML 后用无头 Chrome 截屏。
# 用法: scripts/ui-shot.sh <屏号> [输出.png]
# 需要: python3 + playwright + google-chrome（--no-sandbox）。
# 原理: 临时把 屏 取 [..] 改成目标屏（可带 道/曲 注入），ru build --target ui，
#       再起 http.server 供 Chrome 加载（file:// 被浏览器策略拦截）。
set -euo pipefail
cd "$(dirname "$0")/.."

屏="${1:-0}"
输出="${2:-ui-shot-${屏}.png}"
临时="$(mktemp -d /tmp/ruui-shot-XXXX)"
源=examples/ruui-player.ru
端口=8901

清理() {
  mv "${源}.bak" "$源" 2>/dev/null || true
  rm -rf "$临时"
}
trap 清理 EXIT

cp "$源" "${源}.bak"
python3 - "$屏" "$源" <<'PY'
import sys
屏, 路径 = sys.argv[1], sys.argv[2]
s = open(路径, encoding='utf-8').read()
s = s.replace("屏 取 [0].", f"屏 取 [{屏}].        # ui-shot 注入")
s = s.replace("道 取 [(0 - 1)].", "道 取 [0].")
s = s.replace("曲 取 [[]].", "曲 取 [['样例.mp3']].")
open(路径, 'w', encoding='utf-8').write(s)
PY

python3 ru build "$源" --target ui --assets examples/player/music -o "$临时/app.html" >/dev/null

(cd "$临时" && python3 -m http.server "$端口" >/dev/null 2>&1) &
服务=$!
trap 'kill '"$服务"' 2>/dev/null || true; 清理' EXIT
sleep 1

python3 - "$输出" <<'PY'
import sys
from playwright.sync_api import sync_playwright
out = sys.argv[1]
with sync_playwright() as p:
    b = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
    pg = b.new_page(viewport={'width': 500, 'height': 900})
    errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto('http://127.0.0.1:8901/app.html')
    pg.wait_for_timeout(1500)
    pg.screenshot(path=out)
    b.close()
    if errs:
        print('JS 错误: ' + '; '.join(errs[:3]), file=sys.stderr)
        sys.exit(1)
PY
echo "截图: $输出"
