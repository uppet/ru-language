# 如观 C 宿主 + SDL2 壳（P6 · D2）

日期：2026-10-24。状态：实施中。

## 目标

把如观协议从「仅如书 Python 会话」扩到 **C 目标 + SDL2 壳**：单个原生二进制、
无 Python／JS／WebView。协议、预算、帧语义与 `graphics_runtime.py` 严格同构。
`rulang/graphics_runtime.py`（1306 行）是规格原文；本文件只记设计与偏差。

## 架构

```
ru 程序 --编译--> app.c --链接--> sdl_host.o --+--> 单二进制
                    |                          |
                    v                          v
            graphics_runtime.h          SDL2/SDL2_ttf/SDL2_image
            （协议状态机，与 Python    （窗口/渲染/事件泵/IME/
              参考实现逐条对齐）         剪贴板/字体/HTTP）
```

- **graphics_runtime.h**：如观协议的状态机。Canvas/Recorder/Image 三类的成员
  派发、命令累积（transform/clips 快照 + 预算）、帧 flush、事件队列、回调
  预算、装载/服务队列、测文三档。对宿主只暴露一个 vtable（见下），不依赖
  SDL——测试宿主（录制帧流）与 SDL 壳都实现同一 vtable。
- **宿主 ABI**：壳注册、程序驱动。帧/事件语义全部在 runtime；壳只做 IO。

## 宿主 vtable

```c
typedef struct RuGuiHost {
    void *userdata;
    /* 窗口生命周期。open 在 画布 创建时调用；close 在 关闭/错误/程序结束。 */
    void (*open)(void *ud, int w, int h);
    void (*close)(void *ud);
    /* 帧 flush（JSON 与 graphics_runtime.scene() 同构；调用方保有所有权）。 */
    void (*push_frame)(void *ud, const char *json, size_t bytes);
    /* 单调时钟（秒，非负不减）。无效时 runtime 报错关闭。 */
    double (*now)(void *ud);
    /* 测文宿主实测钩；NULL 或返回负 = 按字度表回退（与 Python 一致）。 */
    double (*measure_text)(void *ud, const char *utf8, size_t bytes, double size);
    /* 装载/服务：runtime 排入队列，壳同步执行并通过 ru_graphics_post_* 回事件。 */
    void (*load_image)(void *ud, long handle, const char *source);
    void (*load_file)(void *ud, long handle, const char *source, int as_text);
    void (*service)(void *ud, long handle, const char *svc, const char *action,
                    const char *path, const char *text, int flag);
    /* 文入焦点（text_focus/blur 命令到达时调用，壳启停 IME）。 */
    void (*set_text_input)(void *ud, int active, int x, int y, int w, int h);
    /* 无事件时等待秒（可 sleeping；测试宿主可立即返回）。NULL = 忙等轮询。 */
    void (*idle)(void *ud, double seconds);
    /* 真 = 图请求／件请求 入装载队列由宿主异步装载（浏览器/SDL 行为）；
       假 = 只登记句柄与命令，不就绪装载（Python GraphicsHost auto_load=False
       测试宿主行为；外部注入的 ready 事件按噪音丢弃）。 */
    int auto_load;
} RuGuiHost;

void ru_graphics_set_host(const RuGuiHost *host);   /* 壳注册，main 前 */
void ru_graphics_post_mouse(int kind, double x, double y, int button); /* 0down 1move 2up */
void ru_graphics_post_touch(int kind, long id, double x, double y);    /* 0start 1move 2end */
void ru_graphics_post_resize(int w, int h);
void ru_graphics_post_key(int down, const char *key);
void ru_graphics_post_text_key(const char *key);
void ru_graphics_post_text_char(const char *utf8);
void ru_graphics_post_text_paste(const char *utf8);
void ru_graphics_post_comp_start(void);
void ru_graphics_post_comp_update(const char *utf8, double cursor);
void ru_graphics_post_comp_end(const char *utf8);
void ru_graphics_post_image_ready(long id, int w, int h);
void ru_graphics_post_image_failed(long id, const char *err);
void ru_graphics_post_file_ready(long id, const char *utf8);
void ru_graphics_post_file_failed(long id, const char *err);
/* 主循环：init 后进入。无画布/未注册宿主则立即返回；返回 1 = 画布已关。 */
int ru_graphics_app_run(void);
```

## 编译器接线（compiler.py / c_runtime.py / runtime.h）

1. `compiler.py:48-49` 硬拒绝 → C 目标放行（基类
   `supports_c_graphics=True`，JSCompiler 置 False 维持拒绝）。
   修复该拒绝路径引用未定义 `node` 变量的 NameError。
2. `c_runtime.runtime_source`：模块图含 `如:观` 导入时追加
   `graphics_runtime.h`；否则追加同签名 stub（仿 `__实用` 的处理）。
3. `runtime.h` 的 `v_member` 加 `RU_MEMBERS: 画布,颜色,矩形,…` 块调
   `ru_graphics_member`；未用如观的程序经 specialize_members 剪掉，零开销。
4. 根模块 init：`env_declare(env, "__如观", ru_graphics_helpers_instance())`
   （先于模块体，因 stdlib/如观.ru 门面在模块体里即引用 `__如观`）。
5. `main()`：root init 后无条件 `ru_graphics_app_run()`——无画布即空转返回；
   有画布未注册宿主 → 画布 创建处报「如观画布需要图形宿主」。
   `--target sdl` 时改发 `ru_graphics_app_entry(const RuGuiHost*)`，
   由 sdl_host.c 提供真 `main`。

## 与 Python 参考实现的对齐点（测试锚定）

- 预算常量逐项相同：MAX_COMMANDS=2048、MAX_FRAME_BYTES=262144、
  MAX_SAVE_DEPTH=64、MAX_CLIPS=32、MAX_IMAGES=8、缓存 128KiB/4Mi px、
  句柄 64、回调 1.0s、装载就绪 256 事件/flush、文字 ≤4096 字、
  色 `#RRGGBB[AA]`、帧率 1..30、尺寸 1..2048（画布）/1..100000（尺寸成员）。
- 命令 JSON 形状逐项相同（background/rect/ellipse/arc/sector/line/text/
  polyline/polygon/bezier + transform/clips/alpha 附加规则 + 文入/装载/服务）。
- 事件→回调实参映射、异步噪音静默、帧补发、服务邮件静默不补帧
  （`fef5e6c` 修复的那条）全部移植。
- 数字序列化：C 用 `%.17g`；测试按解析后数值比对，不做文本比对。
- canvas_id：Python 随机 16 字节 hex；C 固定 `"c"`（单例画布，测试不比此字段）。
- 回调行预算：C 无行跟踪，只守时（1.0s）与分配记账（近似：GC 计数差值），
  文档明写此偏差。

## SDL 壳（rulang/sdl_host.c + sdl_builder.py）

- `--target sdl`：编译 app.c → 与 `sdl_host.c` 链成单二进制。
  `sdl_builder.py` 处理 pkg-config、字体查找、`-DHEADLESS_SMOKE`。
- 渲染：JSON 帧 → SDL_Renderer。快路径 = 无 transform/clips（如UI 全量走此路）；
  translate 直加偏移；rotate/scale 渲染到纹理再 CopyEx；**shear 文档声明为
  近似**（SDL_Renderer 无仿射，v1 不软件光栅化）。
- 文字：SDL_ttf；字体查找 RU_FONT 环境变量 → 常见路径 → 内嵌点阵回退提示。
  measure_text 用 TTF_SizeUTF8。
- 图：SDL_image（PNG/JPG/BMP/GIF/WEBP），尺寸头校验复刻 `_image_head_size`。
- 件/档：文件读，程序目录为根（与桌面壳一致），路径校验同 desktop_host。
- 网：OpenSSL 手写最小 HTTP/1.1 客户端（GET/POST/PUT/DELETE，TLS）。
- 事件泵：SDL → 上述 post API；text input → IME 全协议（组开始/更新/结束）；
  剪贴板 → text_paste；窗口 close → 画布 关闭 协议。
- HEADLESS_SMOKE：dummy video driver，首帧渲染到 surface 写 PNG，
  供无显示器的 CI 验证像素。

## 录制宿主协议（rulang/hosts/record_host.c）

stdin 逐行 JSON（EOF = 画布关闭）：
- `{"set_now": t}` 设虚拟时钟；`{"advance": dt}` 步进时钟。
- `{"event": {...}}` 调对应 `ru_graphics_post_*`。

stdout：`EVENT <name> <args…>`（宿主动作记录）与 `FRAME <json>`（帧流，
逐字节对应 Python `canvas.scene()` 的 JSON 序列化）。

**JSON 解析容忍冒号后空白**：测试端 `json.dumps` 默认 `", "`/`": "` 分隔符；
早期紧凑 pattern 匹配把带空格脚本行全部解析失败、事件静默丢弃，而手工
printf 紧凑 JSON 恰好可解析——同一二进制"时好时坏"的假 heisenbug 查了两
小时。教训：**调试手工构造的输入必须与程序实际输入逐字节一致**。

## 里程碑

1. **M1 协议内核** ✅：graphics_runtime.h 全成员 + 编译器接线 + 录制宿主
   （stdin JSON-lines / stdout FRAME 流）+ **16 例 parity 测试全绿**
   （Python GraphicsHost vs C+record host 帧 JSON 双端比对，
   `python3 -m unittest tests.test_ruui_c_graphics_parity`，-O0/-O1 双确认）。
2. **M2 SDL 壳** ✅：`--target sdl` 单二进制（compiler main 双路 +
   `ru_sdl_host_register`/`ru_sdl_app_run` + pkg-config 链 SDL2/TTF/IMG）。
   渲染全 11 种绘制 op；counter 与 mix（矩形/椭圆/扇形/折线/多边形/中文文字）
   dummy driver HEADLESS_SMOKE PNG 像素级验证通过。
   排查记录：dummy 下 ACCELERATED renderer 创建成功但绘制静默失败
   （SMOKE 强制 SOFTWARE）；键扫描 pattern 须带冒号（`"key":`），否则
   `"op":"text"` 会被 `text` 键匹配命中。
3. **M3 输入全协议** ✅：鼠标/touch/按键（可打印键 down/up，编辑键 text_key）/
   IME（comp_start/update/end + text_char）/剪贴板取/`resize`。
   **handlers 位图过滤**：壳按最新帧 `handlers` 数组过滤未监听事件
   （runtime 对未监听事件是硬错误，GUI 噪声必须壳侧拦）。
4. **M4 装载与服务** ◐：图装载（IMG_Load → image_ready/failed）、件/档读
   （文/base64，8MiB 上限）就绪事件已通；**档/网 service 诚实 stub**
   （固定失败响应，HTTP 客户端未接线）。
5. **M5 变换与缓存** ◐：translate 直加偏移；rotate/scale 整窗纹理 CopyEx
   （中心 = 窗中心）；shear 近似平移（诚实清单已记）；宽线叠画近似；
   bezier 32 段采样。字体按像素尺寸缓存 8 槽。**未做**：缓存/贴图录制、
   预算压测。

HEADLESS_SMOKE 用法：`RU_HEADLESS_SMOKE=1 python3 -m rulang build app.ru
--target sdl -o app && SDL_VIDEODRIVER=dummy RU_SMOKE_FRAMES=3 ./app`
（帧数默认 3，落盘 smoke.png）。RU_FONT 环境变量可覆盖字体。

## 已知偏差（诚实清单）

- C 回调预算只有时间一项硬守；行/内存预算近似。Python 的
  tracemalloc 行级账本无对应物。
- 服务请求壳内同步执行（与 Python 宿主 urllib 同步一致）；大响应受
  MAX_FILE_TEXT_BYTES=8MiB 约束。
- 双指以上 touch：SDL 事件逐个 post，不做手势合成（协议本来逐指）。
- 高帧率：fps 上限沿用 Python 的 30（浏览器宿主才放到 60）。
