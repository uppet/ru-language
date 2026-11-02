# 如声播放器（ruui-player）试用说明

如语言（ru-language）自带的移动端音乐播放器示例，基于 如UI 声明式 UI 库 + 如:声 音频库，SDL2 渲染。暗色主题 + 薄荷绿 accent，对照 Spotify 式移动端四屏设计稿实现。

## 功能一览

- **7 屏**：首页（问候/筛选 chips/FEATURED/最近播放）、搜索（词+扩展名过滤）、曲库、喜欢（♥ 收藏）、更多（循环模式/音量/刷新曲库/关于）、播放中（进度环唱盘/拖动定位/圆形播放键）、播放队列
- **迷你播放条**：除播放中/队列外、有曲目在播时贴底显示
- **底部导航**：5 项，播放中/队列时隐藏
- **收藏**：搜索/曲库列表行右侧 ♡ 点击收藏；喜欢屏列出；播放中屏底行也可收藏
- **循环**：列表循环 / 单曲循环（更多屏切换，播完自动接歌）
- **曲库**：启动自动扫描 `examples/player/music/`（wav/mp3/ogg），更多屏可手动刷新

## 环境要求

- Linux（其他系统未验证）
- Python 3.9+
- C 编译器（gcc/clang）
- SDL2 + SDL2_mixer 开发包

Debian/Ubuntu：

```bash
sudo apt-get install build-essential python3 libsdl2-dev libsdl2-mixer-dev
```

## 检出与运行

```bash
git clone https://github.com/uppet/ru-language.git
cd ru-language
git checkout player-ruaudio     # 播放器开发分支

# 构建（须在仓库根目录跑：曲库用相对路径 examples/player/music/）
RU_SDL_WITH_MIXER=1 python3 ru build examples/ruui-player.ru --target sdl -o /tmp/ru-player

# 运行
/tmp/ru-player
```

窗口 480×840。点击交互全部可用：导航切屏、chips 筛选、点行播放、心形收藏、滑杆定位/音量、圆形键暂停续播、◀◀▶▶ 切歌。

## 无头截图（不需要显示器/声卡）

```bash
bash scripts/ui-shot.sh 0 shot_home.png    # 屏号 0-6，缺省输出 shot_<N>.png
```

机制：`RU_HEADLESS_SMOKE=1` 构建 smoke 版二进制（渲染 N 帧写出 `smoke.png` 即退出），脚本临时把入口屏号写进源码，构建 → dummy SDL 驱动运行 → 拷图 → 自动还原。同时注入一首假曲目让迷你播放条有内容。

屏号：0 首页  1 搜索  2 曲库  3 喜欢  4 更多  5 播放中  6 队列

## 代码结构

- `examples/ruui-player.ru`（~390 行）：全部播放器逻辑——纯声明式 UI 树 + 事件作块，无手写绘制
- `rulang/thirdparty/如UI/如UI.ru`：UI 库（行/列/叠/滚/文/钮/选/滑/盘/块/图载/文入 + 大字/染色/彩/圆/透/可按/度/充/占/间 修饰器）
- `scripts/ui-shot.sh`：截图脚本

## 已知限制

- 喜欢列表仅会话内保存（无持久化存储 API）
- 歌词、歌手/专辑页筹备中（点了会弹提示）
- 其他 5 个 ruui 示例（counter/mixer/notepad/quiz/textfield）编译通过，但本机链接报 `ru_audio_set_host` 未定义——SDL 宿主链接问题，与播放器无关
