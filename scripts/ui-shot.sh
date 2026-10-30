#!/usr/bin/env bash
# ui-shot.sh — 如UI 播放器渲染到文件：把指定屏截图保存为 PNG。
# 用法： scripts/ui-shot.sh <屏号> [输出.png]
#   屏号： 0 首页  1 搜索  2 曲库  3 喜欢  4 更多  5 播放中  6 队列
# 机制：RU_HEADLESS_SMOKE=1 让 SDL 宿主渲染 N 帧后退出并写出 smoke.png，
#       本脚本临时把入口屏号写进源码，构建 → 运行 → 拷图 → 还原。
set -euo pipefail
cd "$(dirname "$0")/.."

N="${1:-0}"
OUT="${2:-shot_${N}.png}"
SRC=examples/ruui-player.ru
RESTORE_LINE='屏 取 [0].        # 截图入口（脚本临时改）'

sed -i "s/^屏 取 \[.\].*\$/屏 取 [${N}].        # 截图入口（脚本临时改）/" "$SRC"
trap "sed -i \"s/^屏 取 \[.\].*\$/${RESTORE_LINE}/\" \"$SRC\"" EXIT

echo "[ui-shot] 构建（屏 ${N}）..."
RU_HEADLESS_SMOKE=1 RU_SDL_WITH_MIXER=1 python3 ru build "$SRC" --target sdl -o /tmp/ruui-shot >/dev/null

rm -f smoke.png
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy RU_SMOKE_FRAMES=12 /tmp/ruui-shot
cp smoke.png "$OUT"
echo "[ui-shot] 已保存 ${OUT}"
