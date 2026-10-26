# SDL 目标：如观原生桌面壳

`--target sdl` 把如观/如UI 程序编译为**单二进制原生桌面应用**：窗口与渲染
走 SDL2，文字 SDL2_ttf，图 SDL2_image，音频 SDL2_mixer（如:声），可选
libcurl（网 服务）。宿主实现见 `rulang/hosts/sdl_host.c`。

```bash
python3 -m rulang build examples/ruui-player.ru --target sdl -o player
./player    # 从仓库根运行：档服务按当前目录解析相对路径
```

## Linux 构建

发行版包 + pkg-config（编译器自动探测，无需额外配置）：

```bash
sudo apt install clang pkg-config \
  libsdl2-dev libsdl2-ttf-dev libsdl2-image-dev libsdl2-mixer-dev
```

## Windows 构建

两条路都支持，CI 各有一个任务锁定：

### 原生构建（MSYS2，推荐）

windows-latest 与多数 Windows 开发机可用 [MSYS2](https://www.msys2.org)：

```bash
pacman -S --noconfirm mingw-w64-ucrt-x86_64-SDL2 \
  mingw-w64-ucrt-x86_64-SDL2_ttf \
  mingw-w64-ucrt-x86_64-SDL2_image \
  mingw-w64-ucrt-x86_64-SDL2_mixer
export PATH="/ucrt64/bin:$PATH"   # git-bash 下：/c/msys64/ucrt64/bin
python -m rulang build examples/ruui-player.ru --target sdl -o player.exe
```

ucrt64 的 pkg-config 直接提供四件套 flags，代码路径与 Linux 一致。

### 参数注入（无 pkg-config 的工具链 / 交叉编译）

`RU_SDL_CFLAGS` + `RU_SDL_LIBS` 成对设置时取代 pkg-config；编解码器支持用
`RU_SDL_WITH_MIXER=1` 显式开启（mixer 库名自己加进 RU_SDL_LIBS）：

```bash
RU_SDL_CFLAGS="-I.../include/SDL2 ..." \
RU_SDL_LIBS="-L.../lib ... -lSDL2 -lSDL2_ttf -lSDL2_image -lSDL2_mixer" \
RU_SDL_WITH_MIXER=1 \
CC=x86_64-w64-mingw32-gcc \
python -m rulang build examples/ruui-player.ru --target sdl -o player.exe
```

## 运行

- 发行包 = `player.exe` + 4 个 `SDL2*.dll`（原生构建从 PATH 取，发行时放同目录）。
- 相对路径按**当前工作目录**解析：保持 `examples/player/music/` 结构、从解压根运行。
- 字体取 `RU_FONT` 环境变量，否则 Windows 用 `C:/Windows/Fonts/msyh.ttc` 候选，
  Linux 用 Noto/DejaVu 候选；全无则文字渲染不可用（图形照常）。
- 中文路径/曲名：宿主内文件系统操作全部宽字符 API，UTF-8 安全。

## 无头冒烟

```bash
RU_HEADLESS_SMOKE=1 python -m rulang build app.ru -t sdl -o app
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy RU_SMOKE_FRAMES=6 ./app
# dummy 驱动下渲染 N 帧，首帧/末帧存 smoke.png 后退出（帧数默认 3）
```

CI 任务：`player-smoke`（Linux 构建+运行）、`player-windows-cross`
（MinGW 交叉编译 .exe）、`player-windows-native`（MSYS2 原生构建+运行）。
