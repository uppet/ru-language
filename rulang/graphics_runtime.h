/* 如观 C 图形宿主协议：graphics_runtime.py 的同构移植（见 plans/ruui-sdl-host.md）。
 * 协议常量、命令形状、预算、事件语义逐项对齐 Python 参考实现；
 * 数字序列化用 %.17g，测试按解析值比对。宿主经 RuGuiHost vtable 注入；
 * SDL 壳见 sdl_host.c，测试录制宿主见 tests/test_ruui_sdl.py。 */
#ifndef RULANG_GRAPHICS_RUNTIME_H
#define RULANG_GRAPHICS_RUNTIME_H

enum {
    RU_G_MAX_SAVE_DEPTH = 64,
    RU_G_MAX_CLIPS = 32,
    RU_G_MAX_COMMANDS = 2048,
    RU_G_MAX_FRAME_BYTES = 262144,
    RU_G_MAX_IMAGES = 8,
    RU_G_MAX_RESOURCE_PIXELS = 4194304,
    RU_G_MAX_RESOURCE_BYTES = 131072,
    RU_G_MAX_LOAD_HANDLES = 64,
    RU_G_MAX_LOAD_EVENTS_PER_FLUSH = 256,
    RU_G_MAX_SOURCE_CHARS = 512,
    RU_G_MAX_SERVICE_NAME_CHARS = 64,
    RU_G_MAX_PASTE_CHARS = 4096,
    RU_G_MAX_COMPOSITION_CHARS = 256,
    RU_G_MAX_CALLBACK_SECONDS = 1,
    RU_G_MAX_FILE_TEXT_BYTES = 8 * 1024 * 1024,
    RU_G_MAX_TEXT_CHARS = 4096
};

enum {
    RU_G_EV_FRAME, RU_G_EV_MOUSE_DOWN, RU_G_EV_MOUSE_UP, RU_G_EV_MOUSE_MOVE,
    RU_G_EV_TOUCH_START, RU_G_EV_TOUCH_MOVE, RU_G_EV_TOUCH_END,
    RU_G_EV_RESIZE, RU_G_EV_KEY_DOWN, RU_G_EV_KEY_UP,
    RU_G_EV_IMAGE_READY, RU_G_EV_IMAGE_FAILED, RU_G_EV_FILE_READY, RU_G_EV_FILE_FAILED,
    RU_G_EV_TEXT_KEY, RU_G_EV_TEXT_CHAR, RU_G_EV_TEXT_PASTE,
    RU_G_EV_COMP_START, RU_G_EV_COMP_UPDATE, RU_G_EV_COMP_END,
    RU_G_EV_SERVICE_RESPONSE, RU_G_EV_SERVICE_AD,
    RU_G_EVENT_COUNT
};

static const char *const ru_g_event_names[RU_G_EVENT_COUNT] = {
    "frame", "mouse_down", "mouse_up", "mouse_move",
    "touch_start", "touch_move", "touch_end", "resize", "key_down", "key_up",
    "image_ready", "image_failed", "file_ready", "file_failed",
    "text_key", "text_char", "text_paste",
    "text_comp_start", "text_comp_update", "text_comp_end",
    "service_response", "service_ad"
};

typedef struct RuGuiHost {
    void *userdata;
    /* 壳所供服务（空格分隔，如 "档 网"）；NULL 或空串 = 不广告。 */
    const char *services;
    void (*open)(void *ud, int w, int h);
    void (*close)(void *ud);
    void (*push_frame)(void *ud, const char *json, size_t bytes);
    double (*now)(void *ud);
    double (*measure_text)(void *ud, const char *utf8, size_t bytes, double size);
    int (*text_metrics)(void *ud, double out3[3]);
    void (*load_image)(void *ud, long handle, const char *source);
    void (*load_file)(void *ud, long handle, const char *source, int as_text);
    void (*service)(void *ud, long handle, const char *service, const char *action,
                    const char *path, const char *text, int flag);
    void (*set_text_input)(void *ud, int active, int x, int y, int w, int h);
    void (*idle)(void *ud, double max_seconds);
    /* 真 = 图请求／件请求 入装载队列由宿主异步装载；假 = 不就绪装载
       （Python GraphicsHost auto_load=False 测试宿主行为）。 */
    int auto_load;
} RuGuiHost;

/* 如声音频宿主（声明镜像 graphics_abi.h；宿主与程序不共编一头）。 */
typedef struct RuAudioHost {
    const char *name;
    int (*open)(void);
    void (*close)(void);
    long (*play)(const char *path, int loop);
    int (*stop)(long channel);
    int (*pause)(long channel);
    int (*resume)(long channel);
    int (*volume)(long channel, int pct);
    double (*position)(long channel);
    int (*playing)(long channel);
} RuAudioHost;

void ru_graphics_set_host(const RuGuiHost *host);
void ru_graphics_post_close(void);
void ru_graphics_post_mouse_down(double x, double y, int button);
void ru_graphics_post_mouse_up(double x, double y, int button);
void ru_graphics_post_mouse_move(double x, double y);
void ru_graphics_post_touch_start(long id, double x, double y);
void ru_graphics_post_touch_move(long id, double x, double y);
void ru_graphics_post_touch_end(long id, double x, double y);
void ru_graphics_post_key_down(const char *key);
void ru_graphics_post_key_up(const char *key);
void ru_graphics_post_text_key(const char *key);
void ru_graphics_post_text_char(const char *utf8);
void ru_graphics_post_text_paste(const char *utf8);
void ru_graphics_post_comp_start(void);
void ru_graphics_post_comp_update(const char *utf8, int cursor);
void ru_graphics_post_comp_end(const char *utf8);
void ru_graphics_post_image_ready(long id, int w, int h);
void ru_graphics_post_image_failed(long id, const char *err);
void ru_graphics_post_file_ready(long id, const char *utf8);
void ru_graphics_post_file_failed(long id, const char *err);
void ru_graphics_post_service_response(long id, int ok, const char *value, const char *error);
int ru_graphics_app_run(void);
/* SDL 壳入口（hosts/sdl_host.c）声明镜像；RU_SDL_HOST 时 main 改调它。 */
void ru_sdl_app_run(void);
void ru_sdl_host_register(void);

/* ---- 基础工具 ---- */
typedef struct { char *data; size_t len, cap; } RuGBuf;
static void ru_gbuf_free(RuGBuf *b) { free(b->data); b->data = NULL; b->len = b->cap = 0; }
static void *ru_g_realloc(void *p, size_t n, int line) {
    void *q = realloc(p, n ? n : 1);
    if (!q) ru_fail(line, "内存不足");
    return q;
}
static void ru_gbuf_reserve(RuGBuf *b, size_t extra, int line) {
    size_t cap;
    if (b->len + extra + 1 <= b->cap) return;
    cap = b->cap ? b->cap : 256;
    while (cap < b->len + extra + 1) cap *= 2;
    b->data = (char *)ru_g_realloc(b->data, cap, line);
    b->cap = cap;
}
static void ru_gbuf_putn(RuGBuf *b, const char *s, size_t n, int line) {
    if (!n) return;
    ru_gbuf_reserve(b, n, line);
    memcpy(b->data + b->len, s, n);
    b->len += n; b->data[b->len] = 0;
}
static void ru_gbuf_puts(RuGBuf *b, const char *s, int line) { ru_gbuf_putn(b, s, strlen(s), line); }
static void ru_gbuf_ch(RuGBuf *b, char c, int line) { ru_gbuf_reserve(b, 1, line); b->data[b->len++] = c; b->data[b->len] = 0; }
static void ru_gbuf_num(RuGBuf *b, double value, int line) {
    char tmp[32];
    if (value == floor(value) && fabs(value) < 1e15) snprintf(tmp, sizeof tmp, "%ld", (long)value);
    else snprintf(tmp, sizeof tmp, "%.17g", value);
    ru_gbuf_puts(b, tmp, line);
}
static void ru_gbuf_json_str(RuGBuf *b, const char *s, size_t n, int line) {
    size_t i;
    ru_gbuf_ch(b, '"', line);
    for (i = 0; i < n; i++) {
        unsigned char c = (unsigned char)s[i];
        if (c == '"' || c == '\\') { ru_gbuf_ch(b, '\\', line); ru_gbuf_ch(b, (char)c, line); }
        else if (c == '\b') ru_gbuf_puts(b, "\\b", line);
        else if (c == '\t') ru_gbuf_puts(b, "\\t", line);
        else if (c == '\n') ru_gbuf_puts(b, "\\n", line);
        else if (c == '\f') ru_gbuf_puts(b, "\\f", line);
        else if (c == '\r') ru_gbuf_puts(b, "\\r", line);
        else if (c < 0x20) { char esc[8]; snprintf(esc, sizeof esc, "\\u%04x", c); ru_gbuf_puts(b, esc, line); }
        else ru_gbuf_ch(b, (char)c, line);
    }
    ru_gbuf_ch(b, '"', line);
}
static size_t ru_g_utf8_count(const char *s) {
    size_t n = 0;
    const unsigned char *p = (const unsigned char *)s;
    while (*p) { if ((*p & 0xC0) != 0x80) n++; p++; }
    return n;
}
static char *ru_strdup(const char *s, int line) {
    size_t n = strlen(s);
    char *copy = (char *)ru_alloc(n + 1, line);
    memcpy(copy, s, n + 1);
    return copy;
}

/* ---- 画布状态 ---- */
typedef struct {
    double x, y, width, height;
    double transform[6];
} RuGClip;

typedef struct {
    char id[16];
    char *definition;      /* 完整配方 JSON 文本（拥有所有权） */
    size_t definition_len;
    long count, pixels;
} RuGResource;

typedef struct {
    char fill[10];    /* "#rrggbb" 或 "#rrggbbaa"（规范小写） */
    char stroke[10];
    int fill_set, stroke_set; /* 空（null）表示不绘制该面 */
    double line_width, text_size;
    int text_align;    /* 0 left 1 center 2 right */
    int text_baseline; /* 0 top 1 middle 2 bottom 3 alphabetic */
    double transform[6];
    double metrics[3]; /* 全 半 行 */
} RuGSnapshot;

struct RuGCanvasRec;
typedef struct RuGCanvasRec RuGCanvas;
struct RuGCanvasRec {
    int is_recorder;
    RuGCanvas *owner;
    int open, closed, running, dirty;
    double width, height, fps;
    long frame;
    RuGSnapshot style;
    RuGSnapshot stack[RU_G_MAX_SAVE_DEPTH];
    int stack_len;
    RuGClip clips[RU_G_MAX_CLIPS];
    int clips_len;
    char **items;          /* 命令 JSON 文本数组（拥有所有权） */
    size_t command_count, command_bytes; /* bytes 语义同 Python：首项 2，逐项 +len+1 */
    RuGResource resources[RU_G_MAX_IMAGES];
    int resource_count;
    size_t resource_bytes, resource_pixels;
    unsigned image_refs;
    long image_loads[RU_G_MAX_LOAD_HANDLES]; int image_loads_len;
    long file_loads[RU_G_MAX_LOAD_HANDLES]; int file_loads_len;
    long load_started[2 * RU_G_MAX_LOAD_HANDLES]; int load_started_len;
    long load_done[2 * RU_G_MAX_LOAD_HANDLES]; int load_done_len;
    Val callbacks[RU_G_EVENT_COUNT];
    unsigned callback_set;
    uint8_t handler_order[RU_G_EVENT_COUNT]; /* 注册顺序（handlers 按此输出，对齐 Python dict 插入序） */
    uint8_t handler_order_len;
    double origin, previous_frame, elapsed, delta;
    size_t recorder_def_overhead;
};

typedef struct {
    int kind;
    double x, y, num2;
    long id;
    int button, w, h, ok;
    char *text;
    char *num2text;
} RuGEvent;

typedef struct {
    int kind;                 /* 0 image 1 file */
    long handle;
    char *source;             /* 拥有所有权 */
    int as_text;
} RuGLoadJob;

typedef struct {
    int is_ad;
    long handle;
    char *service, *action, *path, *text, *ad_services; /* 拥有所有权 */
    int flag;
} RuGServiceJob;

static RuClass ru_graphics_helpers_class = {"如观工具", NULL, NULL, 0, NULL, NULL, 0, NULL};
static RuClass ru_graphics_canvas_class = {"如观画布", NULL, NULL, 0, NULL, NULL, 0, NULL};
static RuClass ru_graphics_recorder_class = {"如观绘图目标", NULL, NULL, 0, NULL, NULL, 0, NULL};
static RuClass ru_graphics_image_class = {"如观图像", NULL, NULL, 3,
    (const char *[]){"号", "宽", "高"}, (const char *[]){"句", "数", "数"}, 0, NULL};

static RuGCanvas ru_g_main_canvas;
static RuGCanvas ru_g_recorder_storage;
static RuGCanvas *ru_g_recording;
static const RuGuiHost *ru_g_host;
static int ru_g_phase; /* 0 init 1 event */
static RuGEvent ru_g_events[256];
static int ru_g_events_head, ru_g_events_tail, ru_g_events_draining;
static RuGLoadJob ru_g_load_queue[256];
static int ru_g_load_head, ru_g_load_tail, ru_g_load_draining;
static RuGServiceJob ru_g_service_queue[256];
static int ru_g_service_head, ru_g_service_tail, ru_g_service_draining;
static int ru_g_last_text_input = -1;

static void ru_g_event_push(RuGEvent *ev);
static void ru_g_event_dispatch(RuGEvent *ev, int line);
static void ru_g_drain_events(int line);

/* 如声音频宿主全局（RuAudioHost 声明见 graphics_abi.h，audio_runtime.h 消费）。
 * ru_audio_builtins 定义在 audio_runtime.h（拼接序在后），此处前置声明；
 * 未用如声的程序由 c_runtime 换入 audio stub，符号仍然齐。 */
static Env *ru_audio_builtins(void);
static const RuAudioHost *ru_audio_host;
void ru_graphics_set_host(const RuGuiHost *host) { ru_g_host = host; }
void ru_audio_set_host(const RuAudioHost *host) { ru_audio_host = host; }

static double ru_g_now(int line) {
    double sample;
    if (!ru_g_host || !ru_g_host->now) ru_fail(line, "如观宿主未注册时钟");
    sample = ru_g_host->now(ru_g_host->userdata);
    if (isfinite(sample) && sample >= 0) return sample;
    ru_fail(line, "如观宿主单调时钟无效；请重新运行");
    return 0;
}

static int ru_g_hexval(unsigned char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
/* 校验并规范化 #RRGGBB/#RRGGBBAA；optional 且空值返回 0。 */
static int ru_g_color_parse(Val value, char out[10], int optional, int line) {
    static const char hex[] = "0123456789abcdef";
    const char *s;
    size_t n, i;
    if (value.kind == RU_NULL && optional) return 0;
    if (value.kind != RU_STR) ru_fail(line, "颜色须为 #RRGGBB 或 #RRGGBBAA 文字%s", optional ? "，空表示不绘制" : "");
    s = value.s->data; n = value.s->len;
    if (!((n == 7 || n == 9) && s[0] == '#')) ru_fail(line, "颜色须为 #RRGGBB 或 #RRGGBBAA 文字%s", optional ? "，空表示不绘制" : "");
    out[0] = '#';
    for (i = 1; i < n; i++) {
        int v = ru_g_hexval((unsigned char)s[i]);
        if (v < 0) ru_fail(line, "颜色须为 #RRGGBB 或 #RRGGBBAA 文字%s", optional ? "，空表示不绘制" : "");
        out[i] = hex[v];
    }
    out[n] = 0;
    return 1;
}

static double ru_g_number(Val value, const char *label, double low, double high, int integer, int line) {
    if (value.kind != RU_NUM || !isfinite(value.n) || value.n < low || value.n > high
        || (integer && value.n != floor(value.n)))
        ru_fail(line, "%s须为范围内%s", label, integer ? "整数" : "有限数");
    return value.n;
}
static const char *ru_g_text(Val value, const char *message, int line) {
    if (value.kind != RU_STR) ru_fail(line, "%s", message);
    return value.s->data;
}
static size_t ru_g_text_len(Val value) { return value.kind == RU_STR ? value.s->len : 0; }

static int ru_g_handle_find(const long *handles, int len, long handle) {
    int lo = 0, hi = len;
    while (lo < hi) { int mid = (lo + hi) / 2;
        if (handles[mid] < handle) lo = mid + 1; else hi = mid; }
    return lo;
}
static int ru_g_handle_has(const long *handles, int len, long handle) {
    int at = ru_g_handle_find(handles, len, handle);
    return at < len && handles[at] == handle;
}
static void ru_g_handle_add(long *handles, int *len, long handle) {
    int at;
    if (*len >= 2 * RU_G_MAX_LOAD_HANDLES) return;
    at = ru_g_handle_find(handles, *len, handle);
    if (at < *len && handles[at] == handle) return;
    memmove(handles + at + 1, handles + at, (size_t)(*len - at) * sizeof(long));
    handles[at] = handle; ++*len;
}

/* ---- 画布生命周期 ---- */
static void ru_g_canvas_reset_geometry(RuGCanvas *c) {
    memcpy(c->style.transform, (double[]){1, 0, 0, 1, 0, 0}, sizeof c->style.transform);
    c->clips_len = 0;
}
static void ru_g_canvas_clear(RuGCanvas *c) {
    size_t i;
    for (i = 0; i < c->command_count; i++) free(c->items[i]);
    free(c->items);
    c->items = NULL; c->command_count = 0; c->command_bytes = 2;
    for (i = 0; i < (size_t)c->resource_count; i++) { free(c->resources[i].definition); c->resources[i].definition = NULL; }
    c->resource_count = 0; c->resource_bytes = 2; c->resource_pixels = 0;
    c->image_loads_len = c->file_loads_len = 0;
    c->load_started_len = c->load_done_len = 0;
    c->image_refs = 0;
}

static void ru_g_canvas_close(RuGCanvas *c) {
    int i;
    if (c->closed) return;
    c->closed = 1; c->running = 0;
    for (i = 0; i < RU_G_EVENT_COUNT; i++)
        if (c->callback_set & (1u << i)) { v_drop(c->callbacks[i]); c->callbacks[i] = v_null(); }
    c->callback_set = 0;
    c->handler_order_len = 0;
    ru_g_canvas_clear(c);
    c->stack_len = 0;
    ru_g_canvas_reset_geometry(c);
    if (!c->is_recorder && ru_g_host && ru_g_host->close) ru_g_host->close(ru_g_host->userdata);
}

static void ru_g_check_balanced(RuGCanvas *c, int line) {
    if (c->stack_len) { ru_g_canvas_close(c); ru_fail(line, "如观保存与恢复须成对；尚有未恢复的状态，已关闭交互"); }
}

static void ru_g_compose(RuGCanvas *c, const double m[6], int line) {
    const double *t = c->style.transform;
    double r[6];
    int i;
    r[0] = t[0]*m[0] + t[2]*m[1]; r[1] = t[1]*m[0] + t[3]*m[1];
    r[2] = t[0]*m[2] + t[2]*m[3]; r[3] = t[1]*m[2] + t[3]*m[3];
    r[4] = t[0]*m[4] + t[2]*m[5] + t[4];
    r[5] = t[1]*m[4] + t[3]*m[5] + t[5];
    for (i = 0; i < 6; i++)
        if (!isfinite(r[i]) || fabs(r[i]) > 100000) ru_fail(line, "如观累积变换须为绝对值不超过 100000 的有限数");
    memcpy(c->style.transform, r, sizeof r);
}

/* ---- 命令入队与预算 ---- */
static int ru_g_op_kept_on_background(const char *item) {
    return strstr(item, "\"op\":\"image_request\"") || strstr(item, "\"op\":\"file_request\"")
        || strstr(item, "\"op\":\"image_release\"");
}
static void ru_g_command_attach(RuGCanvas *c, RuGBuf *full, const char *body, int line) {
    int identity, i;
    size_t body_len = strlen(body);
    identity = !memcmp(c->style.transform, (double[]){1, 0, 0, 1, 0, 0}, sizeof(double) * 6);
    full->data = NULL; full->len = full->cap = 0;
    /* body 是完整 JSON 对象；transform/clips 须插在收尾大括号之前 */
    if (body_len && body[body_len - 1] == '}') ru_gbuf_putn(full, body, body_len - 1, line);
    else ru_gbuf_puts(full, body, line);
    if (!identity) {
        ru_gbuf_puts(full, ",\"transform\":[", line);
        for (i = 0; i < 6; i++) { if (i) ru_gbuf_ch(full, ',', line); ru_gbuf_num(full, c->style.transform[i], line); }
        ru_gbuf_ch(full, ']', line);
    }
    if (c->clips_len) {
        ru_gbuf_puts(full, ",\"clips\":[", line);
        for (i = 0; i < c->clips_len; i++) {
            int j;
            if (i) ru_gbuf_ch(full, ',', line);
            ru_gbuf_puts(full, "{\"x\":", line); ru_gbuf_num(full, c->clips[i].x, line);
            ru_gbuf_puts(full, ",\"y\":", line); ru_gbuf_num(full, c->clips[i].y, line);
            ru_gbuf_puts(full, ",\"width\":", line); ru_gbuf_num(full, c->clips[i].width, line);
            ru_gbuf_puts(full, ",\"height\":", line); ru_gbuf_num(full, c->clips[i].height, line);
            ru_gbuf_puts(full, ",\"transform\":[", line);
            for (j = 0; j < 6; j++) { if (j) ru_gbuf_ch(full, ',', line); ru_gbuf_num(full, c->clips[i].transform[j], line); }
            ru_gbuf_puts(full, "]}", line);
        }
        ru_gbuf_ch(full, ']', line);
    }
    ru_gbuf_ch(full, '}', line);
}

static void ru_g_scene_empty(RuGCanvas *c, RuGBuf *out, int line) {
    int i, first = 1;
    ru_gbuf_puts(out, "{\"canvas_id\":\"c\",\"width\":", line); ru_gbuf_num(out, c->width, line);
    ru_gbuf_puts(out, ",\"height\":", line); ru_gbuf_num(out, c->height, line);
    ru_gbuf_puts(out, ",\"fps\":", line); ru_gbuf_num(out, c->fps, line);
    ru_gbuf_puts(out, ",\"running\":", line); ru_gbuf_puts(out, c->running ? "true" : "false", line);
    ru_gbuf_puts(out, ",\"handlers\":[", line);
    for (i = 0; i < c->handler_order_len; i++) {
        if (!first) ru_gbuf_ch(out, ',', line);
        ru_gbuf_ch(out, '"', line); ru_gbuf_puts(out, ru_g_event_names[c->handler_order[i]], line); ru_gbuf_ch(out, '"', line);
        first = 0;
    }
    ru_gbuf_puts(out, "],\"type\":\"graphics\",\"commands\":[]}", line);
}

/* 入队一条命令。body 为完整 JSON 对象文本；is_background 跳过几何快照。 */
static void ru_g_command(RuGCanvas *c, const char *body, int is_background, int line) {
    RuGBuf full;
    const char *text = body;
    size_t size, refs_total = 0, frame_size;
    int i, refs = 0;
    if (c->closed) ru_fail(line, "如观画布已关闭；运行新代码格、停止或重启会话后，请重新创建画布");
    if (!is_background && (memcmp(c->style.transform, (double[]){1, 0, 0, 1, 0, 0}, sizeof(double) * 6)
                           || c->clips_len)) {
        ru_g_command_attach(c, &full, body, line);
        text = full.data;
    } else full.data = NULL;
    size = strlen(text) + 1;
    if (c->is_recorder && c->command_count >= RU_G_MAX_COMMANDS - 1) {
        ru_gbuf_free(&full);
        ru_fail(line, "如观单张缓存最多 2047 个命令；须为贴图保留一个命令");
    }
    if (c->command_count >= RU_G_MAX_COMMANDS || c->command_bytes + size > (size_t)RU_G_MAX_FRAME_BYTES - 1024) {
        ru_gbuf_free(&full);
        ru_fail(line, "如观每帧最多 2048 个绘制命令、256 KiB 数据；请减少图形或文字");
    }
    for (i = 0; i < c->resource_count; i++)
        if (c->image_refs & (1u << i)) refs_total += (size_t)c->resources[i].count;
    if (c->command_count + 1 + refs_total > (size_t)RU_G_MAX_COMMANDS) {
        ru_gbuf_free(&full);
        ru_fail(line, "如观每帧根命令与引用缓存配方合计最多 2048 个命令");
    }
    if (c->image_refs && !is_background) {
        RuGBuf empty;
        empty.data = NULL; empty.len = empty.cap = 0;
        ru_g_scene_empty(c, &empty, line);
        frame_size = empty.len + c->command_bytes + size - 3;
        frame_size += strlen(",\"resources\":") + 2;
        for (i = 0; i < c->resource_count; i++)
            if (c->image_refs & (1u << i)) { frame_size += c->resources[i].definition_len; refs++; }
        if (refs > 1) frame_size += (size_t)(refs - 1);
        ru_gbuf_free(&empty);
        if (frame_size > (size_t)RU_G_MAX_FRAME_BYTES) {
            ru_gbuf_free(&full);
            ru_fail(line, "如观完整绘图帧超过 256 KiB UTF-8 数据；请减少图形或文字");
        }
    }
    c->items = (char **)ru_g_realloc(c->items, (c->command_count + 1) * sizeof(char *), line);
    c->items[c->command_count++] = ru_strdup(text, line);
    c->command_bytes += size;
    c->dirty = 1;
    if (c->is_recorder) {
        size_t def_size = c->recorder_def_overhead + c->command_bytes - 2 - (c->command_count ? 1 : 0);
        if (c->owner && c->owner->resource_bytes + def_size + (c->owner->resource_count ? 1 : 0) > (size_t)RU_G_MAX_RESOURCE_BYTES) {
            free(c->items[--c->command_count]);
            c->command_bytes -= size;
            ru_gbuf_free(&full);
            ru_fail(line, "如观全部缓存定义最多 128 KiB UTF-8 数据；请减少图形或文字");
        }
    }
    ru_gbuf_free(&full);
}

/* ---- 帧组装与 flush ---- */
static void ru_g_flush(int line);

static void ru_g_scene(RuGCanvas *c, RuGBuf *out, int line) {
    size_t i;
    int first = 1;
    ru_gbuf_puts(out, "{\"canvas_id\":\"c\",\"width\":", line); ru_gbuf_num(out, c->width, line);
    ru_gbuf_puts(out, ",\"height\":", line); ru_gbuf_num(out, c->height, line);
    ru_gbuf_puts(out, ",\"fps\":", line); ru_gbuf_num(out, c->fps, line);
    ru_gbuf_puts(out, ",\"running\":", line); ru_gbuf_puts(out, c->running ? "true" : "false", line);
    ru_gbuf_puts(out, ",\"handlers\":[", line);
    for (i = 0; i < (size_t)c->handler_order_len; i++) {
        if (!first) ru_gbuf_ch(out, ',', line);
        ru_gbuf_ch(out, '"', line); ru_gbuf_puts(out, ru_g_event_names[c->handler_order[i]], line); ru_gbuf_ch(out, '"', line);
        first = 0;
    }
    ru_gbuf_puts(out, "],\"type\":\"graphics\",\"commands\":[", line);
    for (i = 0; i < c->command_count; i++) {
        if (i) ru_gbuf_ch(out, ',', line);
        ru_gbuf_puts(out, c->items[i], line);
    }
    ru_gbuf_puts(out, "]", line);
    if (c->image_refs) {
        int refs = 0;
        for (i = 0; i < (size_t)c->resource_count; i++) if (c->image_refs & (1u << i)) refs++;
        if (refs) {
            ru_gbuf_puts(out, ",\"resources\":[", line);
            first = 1;
            for (i = 0; i < (size_t)c->resource_count; i++)
                if (c->image_refs & (1u << i)) {
                    if (!first) ru_gbuf_ch(out, ',', line);
                    ru_gbuf_putn(out, c->resources[i].definition, c->resources[i].definition_len, line);
                    first = 0;
                }
            ru_gbuf_ch(out, ']', line);
        }
    }
    ru_gbuf_ch(out, '}', line);
}

static void ru_g_load_push(int kind, long handle, const char *source, int as_text) {
    int next = (ru_g_load_tail + 1) % 256;
    if (next == ru_g_load_head) return;
    ru_g_load_queue[ru_g_load_tail].kind = kind;
    ru_g_load_queue[ru_g_load_tail].handle = handle;
    ru_g_load_queue[ru_g_load_tail].source = ru_strdup(source, 1);
    ru_g_load_queue[ru_g_load_tail].as_text = as_text;
    ru_g_load_tail = next;
}
static void ru_g_service_push(long handle, const char *service, const char *action,
                              const char *path, const char *text, int flag) {
    int next = (ru_g_service_tail + 1) % 256;
    if (next == ru_g_service_head) return;
    ru_g_service_queue[ru_g_service_tail].is_ad = 0;
    ru_g_service_queue[ru_g_service_tail].handle = handle;
    ru_g_service_queue[ru_g_service_tail].service = ru_strdup(service, 1);
    ru_g_service_queue[ru_g_service_tail].action = ru_strdup(action, 1);
    ru_g_service_queue[ru_g_service_tail].path = ru_strdup(path, 1);
    ru_g_service_queue[ru_g_service_tail].text = ru_strdup(text ? text : "", 1);
    ru_g_service_queue[ru_g_service_tail].flag = flag;
    ru_g_service_tail = next;
}
static void ru_g_service_push_ad(const char *services) {
    int next = (ru_g_service_tail + 1) % 256;
    if (next == ru_g_service_head) return;
    ru_g_service_queue[ru_g_service_tail].is_ad = 1;
    ru_g_service_queue[ru_g_service_tail].handle = 0;
    ru_g_service_queue[ru_g_service_tail].service = NULL;
    ru_g_service_queue[ru_g_service_tail].action = NULL;
    ru_g_service_queue[ru_g_service_tail].path = NULL;
    ru_g_service_queue[ru_g_service_tail].text = NULL;
    ru_g_service_queue[ru_g_service_tail].ad_services = ru_strdup(services, 1);
    ru_g_service_tail = next;
}

static void ru_g_drain_events(int line);

static void ru_g_flush(int line) {
    RuGCanvas *c = &ru_g_main_canvas;
    int saw_focus = -1, focus_x = 0, focus_y = 0, focus_w = 0, focus_h = 0, saw_blur = 0;
    size_t i;
    if (!c->open) return;
    ru_g_check_balanced(c, line);
    if (c->dirty && !c->closed) {
        RuGBuf scene;
        scene.data = NULL; scene.len = scene.cap = 0;
        ru_g_scene(c, &scene, line);
        if (scene.len > (size_t)RU_G_MAX_FRAME_BYTES) {
            ru_gbuf_free(&scene);
            ru_fail(line, "如观完整绘图帧超过 256 KiB UTF-8 数据；请减少图形或文字");
        }
        if (ru_g_host && ru_g_host->push_frame) ru_g_host->push_frame(ru_g_host->userdata, scene.data ? scene.data : "", scene.len);
        ru_gbuf_free(&scene);
        c->dirty = 0;
    }
    /* 文入焦点命令 → 宿主 IME 状态。 */
    for (i = 0; i < c->command_count; i++) {
        const char *p;
        if ((p = strstr(c->items[i], "\"op\":\"text_focus\"")) != NULL) {
            const char *q;
            saw_focus = 1;
            q = strstr(c->items[i], "\"x\":"); if (q) focus_x = (int)strtol(q + 4, NULL, 10);
            q = strstr(c->items[i], "\"y\":"); if (q) focus_y = (int)strtol(q + 4, NULL, 10);
            q = strstr(c->items[i], "\"width\":"); if (q) focus_w = (int)strtol(q + 8, NULL, 10);
            q = strstr(c->items[i], "\"height\":"); if (q) focus_h = (int)strtol(q + 9, NULL, 10);
            (void)p;
        } else if (strstr(c->items[i], "\"op\":\"text_blur\"")) saw_blur = 1;
    }
    if (saw_focus == 1 && ru_g_last_text_input != 1) {
        if (ru_g_host && ru_g_host->set_text_input) ru_g_host->set_text_input(ru_g_host->userdata, 1, focus_x, focus_y, focus_w, focus_h);
        ru_g_last_text_input = 1;
    } else if ((saw_blur || saw_focus < 0) && ru_g_last_text_input != 0) {
        if (ru_g_host && ru_g_host->set_text_input) ru_g_host->set_text_input(ru_g_host->userdata, 0, 0, 0, 0, 0);
        ru_g_last_text_input = 0;
    }
    /* 装载排水（帧外迭代）。 */
    if (!ru_g_load_draining) {
        int delivered = 0;
        ru_g_load_draining = 1;
        while (ru_g_load_head != ru_g_load_tail && delivered < RU_G_MAX_LOAD_EVENTS_PER_FLUSH) {
            RuGLoadJob job = ru_g_load_queue[ru_g_load_head];
            ru_g_load_head = (ru_g_load_head + 1) % 256;
            delivered++;
            if (!c->open || c->closed) { free(job.source); continue; }
            ru_g_handle_add(c->load_started, &c->load_started_len, job.handle);
            if (ru_g_host) {
                if (job.kind == 0 && ru_g_host->load_image) ru_g_host->load_image(ru_g_host->userdata, job.handle, job.source);
                if (job.kind == 1 && ru_g_host->load_file) ru_g_host->load_file(ru_g_host->userdata, job.handle, job.source, job.as_text);
            }
            free(job.source);
        }
        ru_g_load_draining = 0;
    }
    /* 服务排水；广告在 服务告 未绑定时留在队首等注册（与 Python 同）。 */
    if (!ru_g_service_draining) {
        int delivered = 0;
        ru_g_service_draining = 1;
        while (ru_g_service_head != ru_g_service_tail && delivered < RU_G_MAX_LOAD_EVENTS_PER_FLUSH) {
            RuGServiceJob *job = &ru_g_service_queue[ru_g_service_head];
            if (!c->open || c->closed) {
                free(job->service); free(job->action); free(job->path); free(job->text); free(job->ad_services);
                ru_g_service_head = (ru_g_service_head + 1) % 256;
                delivered++;
                continue;
            }
            if (job->is_ad) {
                if (c->callback_set & (1u << RU_G_EV_SERVICE_AD)) {
                    RuGEvent ev;
                    memset(&ev, 0, sizeof ev);
                    ev.kind = RU_G_EV_SERVICE_AD;
                    ev.text = ru_strdup(job->ad_services, line);
                    ru_g_service_head = (ru_g_service_head + 1) % 256;
                    free(job->ad_services); job->ad_services = NULL;
                    delivered++;
                    ru_g_event_push(&ev);
                } else break; /* 等库注册 */
            } else {
                long handle = job->handle;
                char *service = job->service, *action = job->action, *path = job->path, *text = job->text;
                int flag = job->flag;
                ru_g_service_head = (ru_g_service_head + 1) % 256;
                job->service = job->action = job->path = job->text = NULL;
                delivered++;
                if (ru_g_host && ru_g_host->service)
                    ru_g_host->service(ru_g_host->userdata, handle, service, action, path, text, flag);
                free(service); free(action); free(path); free(text);
            }
        }
        ru_g_service_draining = 0;
    }
    ru_g_drain_events(line);
}

/* ---- 事件派发 ---- */
static const char *ru_g_text_edit_keys[] = {"退格", "删除", "左", "右", "上", "下", "家", "终", "回车", "空格", "跳格", "逃脱", NULL};
static int ru_g_is_async(int kind) {
    return kind == RU_G_EV_IMAGE_READY || kind == RU_G_EV_IMAGE_FAILED
        || kind == RU_G_EV_FILE_READY || kind == RU_G_EV_FILE_FAILED;
}

static void ru_g_event_free(RuGEvent *ev) { free(ev->text); free(ev->num2text); ev->text = ev->num2text = NULL; }
static void ru_g_event_push(RuGEvent *ev) {
    int next = (ru_g_events_tail + 1) % 256;
    if (next == ru_g_events_head) { ru_g_event_free(ev); ru_fail(1, "如观事件队列已满"); }
    ru_g_events[ru_g_events_tail] = *ev;
    ru_g_events_tail = next;
}
static int ru_g_event_pop(RuGEvent *ev) {
    if (ru_g_events_head == ru_g_events_tail) return 0;
    *ev = ru_g_events[ru_g_events_head];
    ru_g_events_head = (ru_g_events_head + 1) % 256;
    return 1;
}

static void ru_g_drain_events(int line) {
    RuGEvent ev;
    if (ru_g_events_draining) return;
    ru_g_events_draining = 1;
    while (!ru_panicking && ru_g_event_pop(&ev)) ru_g_event_dispatch(&ev, line);
    ru_g_events_draining = 0;
}

static void ru_g_event_dispatch(RuGEvent *ev, int line) {
    RuGCanvas *c = &ru_g_main_canvas;
    Val cb, values[4];
    int value_count = 0, has_cb, kind = ev->kind, async;
    double started, now;
    char **saved_items;
    size_t saved_count, saved_bytes;
    unsigned saved_refs_value = c->image_refs;
    if (kind == -1) { /* close */
        ru_g_canvas_close(c);
        ru_g_event_free(ev);
        return;
    }
    if (!c->open || c->closed) { ru_g_event_free(ev); return; }
    if (kind < 0 || kind >= RU_G_EVENT_COUNT) { ru_g_event_free(ev); ru_fail(line, "无效如观事件"); }
    has_cb = (c->callback_set & (1u << kind)) != 0;
    async = ru_g_is_async(kind);
    switch (kind) {
    case RU_G_EV_MOUSE_DOWN: case RU_G_EV_MOUSE_UP:
        if (ev->button < 0 || ev->button > 4) { ru_g_event_free(ev); ru_fail(line, "无效如观鼠标键"); }
        /* fallthrough */
    case RU_G_EV_MOUSE_MOVE:
        if (!isfinite(ev->x) || !isfinite(ev->y) || ev->x < -100000 || ev->x > 100000
            || ev->y < -100000 || ev->y > 100000) { ru_g_event_free(ev); ru_fail(line, "无效如观鼠标坐标"); }
        break;
    case RU_G_EV_TOUCH_START: case RU_G_EV_TOUCH_MOVE: case RU_G_EV_TOUCH_END:
        if (!isfinite(ev->x) || !isfinite(ev->y) || ev->x < -100000 || ev->x > 100000
            || ev->y < -100000 || ev->y > 100000) { ru_g_event_free(ev); ru_fail(line, "无效如观触屏坐标"); }
        if (ev->id < 0 || ev->id > 100000) { ru_g_event_free(ev); ru_fail(line, "无效如观触屏指针"); }
        break;
    case RU_G_EV_RESIZE:
        if (ev->w < 1 || ev->w > 100000 || ev->h < 1 || ev->h > 100000) { ru_g_event_free(ev); ru_fail(line, "无效如观尺寸"); }
        break;
    case RU_G_EV_KEY_DOWN: case RU_G_EV_KEY_UP:
        if (!ev->text || strlen(ev->text) > 64) { ru_g_event_free(ev); ru_fail(line, "无效如观按键"); }
        break;
    case RU_G_EV_IMAGE_READY:
        if (ev->id < 0 || ev->id > 10000000 || ev->w < 1 || ev->w > 4096 || ev->h < 1 || ev->h > 4096)
            { ru_g_event_free(ev); ru_fail(line, "无效如观图像尺寸"); }
        break;
    case RU_G_EV_IMAGE_FAILED: case RU_G_EV_FILE_FAILED:
        if (ev->id < 0 || ev->id > 10000000) { ru_g_event_free(ev); ru_fail(line, "无效如观装载句柄"); }
        if (!ev->text || !ev->text[0] || strlen(ev->text) > 512) { ru_g_event_free(ev); ru_fail(line, "无效如观装载错误"); }
        break;
    case RU_G_EV_FILE_READY:
        if (ev->id < 0 || ev->id > 10000000) { ru_g_event_free(ev); ru_fail(line, "无效如观装载句柄"); }
        break;
    case RU_G_EV_SERVICE_RESPONSE:
        if (ev->id < 0 || ev->id > 10000000) { ru_g_event_free(ev); ru_fail(line, "无效如观服务句柄"); }
        break;
    case RU_G_EV_TEXT_KEY: {
        const char **k;
        int found = 0;
        if (!ev->text) { ru_g_event_free(ev); ru_fail(line, "无效如观文入键（须为附录 A 编辑键名）"); }
        for (k = ru_g_text_edit_keys; *k; k++) if (!strcmp(*k, ev->text)) { found = 1; break; }
        if (!found) { ru_g_event_free(ev); ru_fail(line, "无效如观文入键（须为附录 A 编辑键名）"); }
        break;
    }
    case RU_G_EV_TEXT_CHAR:
        if (!ev->text || ru_g_utf8_count(ev->text) != 1) { ru_g_event_free(ev); ru_fail(line, "无效如观文入文本"); }
        break;
    case RU_G_EV_TEXT_PASTE:
        if (!ev->text || !ev->text[0] || ru_g_utf8_count(ev->text) > RU_G_MAX_PASTE_CHARS) { ru_g_event_free(ev); ru_fail(line, "无效如观文入文本"); }
        break;
    case RU_G_EV_COMP_UPDATE:
        if (!ev->text || ru_g_utf8_count(ev->text) > RU_G_MAX_COMPOSITION_CHARS) { ru_g_event_free(ev); ru_fail(line, "无效如观输入法组合"); }
        if (!isfinite(ev->num2) || ev->num2 < 0 || ev->num2 > RU_G_MAX_COMPOSITION_CHARS) { ru_g_event_free(ev); ru_fail(line, "无效如观输入法光标"); }
        break;
    case RU_G_EV_COMP_END:
        if (!ev->text || ru_g_utf8_count(ev->text) > RU_G_MAX_COMPOSITION_CHARS) { ru_g_event_free(ev); ru_fail(line, "无效如观输入法定字"); }
        break;
    case RU_G_EV_SERVICE_AD:
        if (!ev->text || strlen(ev->text) > 4096) { ru_g_event_free(ev); ru_fail(line, "无效如观服务广告"); }
        break;
    default: break;
    }
    if (async) {
        const long *outstanding;
        int outstanding_len;
        if (kind == RU_G_EV_IMAGE_READY || kind == RU_G_EV_IMAGE_FAILED) {
            outstanding = c->image_loads; outstanding_len = c->image_loads_len;
        } else { outstanding = c->file_loads; outstanding_len = c->file_loads_len; }
        if (!has_cb || !ru_g_handle_has(outstanding, outstanding_len, ev->id)
            || !ru_g_handle_has(c->load_started, c->load_started_len, ev->id)
            || ru_g_handle_has(c->load_done, c->load_done_len, ev->id)) {
            ru_g_event_free(ev);
            return; /* 噪音静默（校验仍先行） */
        }
        ru_g_handle_add(c->load_done, &c->load_done_len, ev->id);
    } else if (!has_cb || (kind == RU_G_EV_FRAME && !c->running)) {
        ru_g_event_free(ev);
        ru_fail(line, "如观事件未启用");
    }
    cb = c->callbacks[kind];
    now = ru_g_now(line);
    c->elapsed = now - c->origin;
    c->delta = (kind == RU_G_EV_FRAME && c->previous_frame >= 0) ? now - c->previous_frame : 0.0;
    if (kind == RU_G_EV_FRAME) { c->previous_frame = now; c->frame++; }
    switch (kind) {
    case RU_G_EV_FRAME: values[value_count++] = v_num((double)c->frame); break;
    case RU_G_EV_MOUSE_DOWN: case RU_G_EV_MOUSE_UP:
        values[value_count++] = v_num(ev->x); values[value_count++] = v_num(ev->y);
        values[value_count++] = v_num((double)ev->button); break;
    case RU_G_EV_MOUSE_MOVE:
        values[value_count++] = v_num(ev->x); values[value_count++] = v_num(ev->y); break;
    case RU_G_EV_TOUCH_START: case RU_G_EV_TOUCH_MOVE: case RU_G_EV_TOUCH_END:
        values[value_count++] = v_num((double)ev->id); values[value_count++] = v_num(ev->x); values[value_count++] = v_num(ev->y); break;
    case RU_G_EV_RESIZE:
        values[value_count++] = v_num((double)ev->w); values[value_count++] = v_num((double)ev->h); break;
    case RU_G_EV_IMAGE_READY:
        values[value_count++] = v_num((double)ev->id); values[value_count++] = v_num((double)ev->w); values[value_count++] = v_num((double)ev->h); break;
    case RU_G_EV_IMAGE_FAILED: case RU_G_EV_FILE_FAILED:
        values[value_count++] = v_num((double)ev->id); values[value_count++] = v_str(ev->text ? ev->text : ""); break;
    case RU_G_EV_FILE_READY:
        values[value_count++] = v_num((double)ev->id); values[value_count++] = v_str(ev->text ? ev->text : ""); break;
    case RU_G_EV_COMP_START: break;
    case RU_G_EV_COMP_UPDATE:
        values[value_count++] = v_str(ev->text ? ev->text : ""); values[value_count++] = v_num(ev->num2); break;
    case RU_G_EV_SERVICE_RESPONSE:
        values[value_count++] = v_num((double)ev->id); values[value_count++] = v_fact(ev->ok);
        values[value_count++] = v_str(ev->text ? ev->text : ""); values[value_count++] = v_str(ev->num2text ? ev->num2text : "");
        break;
    case RU_G_EV_SERVICE_AD:
        values[value_count++] = v_str(ev->text ? ev->text : ""); break;
    default:
        values[value_count++] = v_str(ev->text ? ev->text : ""); break;
    }
    /* 输入回调先清场景：绘制即替换；未绘制则恢复原场景（帧与装载就绪除外）。 */
    saved_items = c->items; saved_count = c->command_count; saved_bytes = c->command_bytes;
    saved_refs_value = c->image_refs;
    { int saved_phase = ru_g_phase;
    c->image_refs = 0;
    c->items = NULL; c->command_count = 0; c->command_bytes = 2;
    ru_g_canvas_reset_geometry(c);
    ru_g_phase = 1;
    started = ru_g_now(line);
    { static const char *ru_g_nokeys[4] = {NULL, NULL, NULL, NULL};
      Val result = v_call(cb, (size_t)value_count, ru_g_nokeys, values, line);
      v_drop(result); }
    ru_g_phase = saved_phase;
    c->image_refs |= saved_refs_value; }
    { int i; for (i = 0; i < value_count; i++) v_drop(values[i]); }
    if (ru_panicking) {
        size_t i;
        for (i = 0; i < c->command_count; i++) free(c->items[i]);
        free(c->items);
        c->items = saved_items; c->command_count = saved_count; c->command_bytes = saved_bytes;
        ru_g_event_free(ev);
        return;
    }
    now = ru_g_now(line);
    if (now - started > RU_G_MAX_CALLBACK_SECONDS) {
        ru_g_canvas_close(c);
        ru_fail(line, "如观回调超过时间预算（阈值 1 秒）；已关闭交互，请简化回调后重跑");
    }
    ru_g_check_balanced(c, line);
    if (async) {
        /* 装载就绪：旧装帧作废不恢复（同 Python ASYNC_EVENTS 分支），
           回调期间的绘制保留在画布上由下方 flush 正常发帧。 */
        size_t i;
        for (i = 0; i < saved_count; i++) free(saved_items[i]);
        free(saved_items);
        saved_items = NULL;
    } else if (c->command_count == 0 && kind != RU_G_EV_FRAME) {
        if (kind != RU_G_EV_SERVICE_RESPONSE && kind != RU_G_EV_SERVICE_AD) {
            free(c->items);
            c->items = saved_items; c->command_count = saved_count; c->command_bytes = saved_bytes;
            c->image_refs = saved_refs_value;
            c->dirty = 1;
            saved_items = NULL;
        }
    } else {
        size_t i;
        for (i = 0; i < saved_count; i++) free(saved_items[i]);
        free(saved_items);
        saved_items = NULL;
        c->dirty = 1;
    }
    if (saved_items) {
        size_t i;
        for (i = 0; i < saved_count; i++) free(saved_items[i]);
        free(saved_items);
    }
    ru_g_event_free(ev);
    ru_g_flush(line);
    if (async && c->open && !c->closed && c->running && (c->callback_set & (1u << RU_G_EV_FRAME))) {
        RuGEvent frame;
        memset(&frame, 0, sizeof frame);
        frame.kind = RU_G_EV_FRAME;
        ru_g_event_push(&frame);
    }
}

/* ---- 事件 post API（壳与测试宿主用） ---- */
static void ru_g_post_text(int kind, const char *text) {
    RuGEvent ev;
    memset(&ev, 0, sizeof ev);
    ev.kind = kind;
    if (text) { ev.text = ru_strdup(text, 1); }
    ru_g_event_push(&ev);
}
static void ru_g_post_mouse(int kind, double x, double y, int button) {
    RuGEvent ev;
    memset(&ev, 0, sizeof ev);
    ev.kind = kind; ev.x = x; ev.y = y; ev.button = button;
    ru_g_event_push(&ev);
}
void ru_graphics_post_mouse_down(double x, double y, int button) { ru_g_post_mouse(RU_G_EV_MOUSE_DOWN, x, y, button); }
void ru_graphics_post_mouse_up(double x, double y, int button) { ru_g_post_mouse(RU_G_EV_MOUSE_UP, x, y, button); }
void ru_graphics_post_mouse_move(double x, double y) { ru_g_post_mouse(RU_G_EV_MOUSE_MOVE, x, y, 0); }
static void ru_g_post_touch(int kind, long id, double x, double y) {
    RuGEvent ev;
    memset(&ev, 0, sizeof ev);
    ev.kind = kind; ev.id = id; ev.x = x; ev.y = y;
    ru_g_event_push(&ev);
}
void ru_graphics_post_touch_start(long id, double x, double y) { ru_g_post_touch(RU_G_EV_TOUCH_START, id, x, y); }
void ru_graphics_post_touch_move(long id, double x, double y) { ru_g_post_touch(RU_G_EV_TOUCH_MOVE, id, x, y); }
void ru_graphics_post_touch_end(long id, double x, double y) { ru_g_post_touch(RU_G_EV_TOUCH_END, id, x, y); }
void ru_graphics_post_resize(int w, int h) {
    RuGEvent ev;
    memset(&ev, 0, sizeof ev);
    ev.kind = RU_G_EV_RESIZE; ev.w = w; ev.h = h;
    ru_g_event_push(&ev);
}
static void ru_g_post_key(int down, const char *key) { ru_g_post_text(down ? RU_G_EV_KEY_DOWN : RU_G_EV_KEY_UP, key); }
void ru_graphics_post_key_down(const char *key) { ru_g_post_key(1, key); }
void ru_graphics_post_key_up(const char *key) { ru_g_post_key(0, key); }
void ru_graphics_post_text_key(const char *key) { ru_g_post_text(RU_G_EV_TEXT_KEY, key); }
void ru_graphics_post_text_char(const char *utf8) { ru_g_post_text(RU_G_EV_TEXT_CHAR, utf8); }
void ru_graphics_post_text_paste(const char *utf8) { ru_g_post_text(RU_G_EV_TEXT_PASTE, utf8); }
void ru_graphics_post_comp_start(void) {
    RuGEvent ev;
    memset(&ev, 0, sizeof ev);
    ev.kind = RU_G_EV_COMP_START;
    ru_g_event_push(&ev);
}
void ru_graphics_post_comp_update(const char *utf8, int cursor) {
    RuGEvent ev;
    memset(&ev, 0, sizeof ev);
    ev.kind = RU_G_EV_COMP_UPDATE; ev.num2 = cursor;
    if (utf8) ev.text = ru_strdup(utf8, 1);
    ru_g_event_push(&ev);
}
void ru_graphics_post_comp_end(const char *utf8) { ru_g_post_text(RU_G_EV_COMP_END, utf8); }
void ru_graphics_post_image_ready(long id, int w, int h) {
    RuGEvent ev;
    memset(&ev, 0, sizeof ev);
    ev.kind = RU_G_EV_IMAGE_READY; ev.id = id; ev.w = w; ev.h = h;
    ru_g_event_push(&ev);
}
void ru_graphics_post_image_failed(long id, const char *err) {
    RuGEvent ev;
    memset(&ev, 0, sizeof ev);
    ev.kind = RU_G_EV_IMAGE_FAILED; ev.id = id;
    if (err) ev.text = ru_strdup(err, 1);
    ru_g_event_push(&ev);
}
void ru_graphics_post_file_ready(long id, const char *utf8) {
    RuGEvent ev;
    memset(&ev, 0, sizeof ev);
    ev.kind = RU_G_EV_FILE_READY; ev.id = id;
    if (utf8) ev.text = ru_strdup(utf8, 1);
    ru_g_event_push(&ev);
}
void ru_graphics_post_file_failed(long id, const char *err) {
    RuGEvent ev;
    memset(&ev, 0, sizeof ev);
    ev.kind = RU_G_EV_FILE_FAILED; ev.id = id;
    if (err) ev.text = ru_strdup(err, 1);
    ru_g_event_push(&ev);
}
static void ru_g_post_service_ad(const char *services) { ru_g_post_text(RU_G_EV_SERVICE_AD, services); }
void ru_graphics_post_service_response(long id, int ok, const char *value, const char *error) {
    RuGEvent ev;
    memset(&ev, 0, sizeof ev);
    ev.kind = RU_G_EV_SERVICE_RESPONSE; ev.id = id; ev.ok = ok;
    ev.text = ru_strdup(value ? value : "", 1);
    ev.num2text = ru_strdup(error ? error : "", 1);
    ru_g_event_push(&ev);
}
void ru_graphics_post_close(void) {
    RuGEvent ev;
    memset(&ev, 0, sizeof ev);
    ev.kind = -1;
    ru_g_event_push(&ev);
}

/* ---- 测文 ---- */
static double ru_g_measure(RuGCanvas *c, const char *text, size_t bytes, int line) {
    double size = c->style.text_size;
    double half = c->style.metrics[1], full = c->style.metrics[0];
    double width = 0;
    const unsigned char *p = (const unsigned char *)text, *end = p + bytes;
    if (ru_g_host && ru_g_host->measure_text) {
        width = ru_g_host->measure_text(ru_g_host->userdata, text, bytes, size);
        if (isfinite(width) && width >= 0) {
            if (width > 10000000) ru_fail(line, "如观测文宿主返回无效宽度");
            return width;
        }
    }
    while (p < end) {
        unsigned cp;
        if (*p < 0x80) { cp = *p; p++; }
        else if ((*p & 0xE0) == 0xC0) { cp = *p & 0x1F; p++; if (p < end) { cp = (cp << 6) | (*p & 0x3F); p++; } }
        else if ((*p & 0xF0) == 0xE0) {
            int k;
            cp = *p & 0x0F; p++;
            for (k = 0; k < 2 && p < end; k++) { cp = (cp << 6) | (*p & 0x3F); p++; }
        }
        else { /* 四字节序列（码点 ≥ 0x10000）或非法字节：按全角计 */
            p++;
            while (p < end && (*p & 0xC0) == 0x80) p++;
            cp = 0x4E00;
        }
        width += cp < 0x4E00 ? half : full;
    }
    return width * size;
}

/* ---- 回调注册表 ---- */
typedef struct { const char *name; int kind; int arity; } RuGCallbackDef;
static const RuGCallbackDef ru_g_callbacks[] = {
    {"每帧", RU_G_EV_FRAME, 1}, {"鼠标按下", RU_G_EV_MOUSE_DOWN, 3},
    {"鼠标松开", RU_G_EV_MOUSE_UP, 3}, {"鼠标移动", RU_G_EV_MOUSE_MOVE, 2},
    {"触下", RU_G_EV_TOUCH_START, 3}, {"触移", RU_G_EV_TOUCH_MOVE, 3},
    {"触松", RU_G_EV_TOUCH_END, 3}, {"改尺寸", RU_G_EV_RESIZE, 2},
    {"按键", RU_G_EV_KEY_DOWN, 1}, {"松键", RU_G_EV_KEY_UP, 1},
    {"图就绪", RU_G_EV_IMAGE_READY, 3}, {"图失败", RU_G_EV_IMAGE_FAILED, 2},
    {"件就绪", RU_G_EV_FILE_READY, 2}, {"件失败", RU_G_EV_FILE_FAILED, 2},
    {"键按下", RU_G_EV_TEXT_KEY, 1}, {"字符", RU_G_EV_TEXT_CHAR, 1},
    {"剪贴", RU_G_EV_TEXT_PASTE, 1}, {"组开始", RU_G_EV_COMP_START, 0},
    {"组更新", RU_G_EV_COMP_UPDATE, 2}, {"组结束", RU_G_EV_COMP_END, 1},
    {"服务回", RU_G_EV_SERVICE_RESPONSE, 4}, {"服务告", RU_G_EV_SERVICE_AD, 1},
    {NULL, -1, -1}
};
static const RuGCallbackDef *ru_g_callback_find(const char *name) {
    const RuGCallbackDef *def;
    for (def = ru_g_callbacks; def->name; def++)
        if (!strcmp(def->name, name)) return def;
    return NULL;
}
static int ru_g_read_member(const char *name) {
    return !strcmp(name, "宽") || !strcmp(name, "高") || !strcmp(name, "帧")
        || !strcmp(name, "经过秒") || !strcmp(name, "间隔秒")
        || !strcmp(name, "字度") || !strcmp(name, "测文");
}
static int ru_g_recorder_forbidden(const char *name) {
    return ru_g_callback_find(name) != NULL || !strcmp(name, "缓存") || !strcmp(name, "贴图")
        || !strcmp(name, "帧率") || !strcmp(name, "停") || !strcmp(name, "继续")
        || !strcmp(name, "关闭") || !strcmp(name, "帧") || !strcmp(name, "经过秒")
        || !strcmp(name, "间隔秒") || !strcmp(name, "图请求") || !strcmp(name, "绘图")
        || !strcmp(name, "图释放") || !strcmp(name, "件请求") || !strcmp(name, "服务请")
        || !strcmp(name, "入焦点") || !strcmp(name, "入失焦") || !strcmp(name, "入更新")
        || !strcmp(name, "字度") || !strcmp(name, "测文") || !strcmp(name, "尺寸");
}

static void ru_g_set_running(RuGCanvas *c, int on) {
    if (c->running == on) return;
    c->running = on;
    if (on) c->previous_frame = -1;
}

/* ---- 命令构造小件 ---- */
static void ru_g_json_nullable_color(RuGBuf *b, const char *key, const RuGSnapshot *s,
                                     int which, int line) {
    ru_gbuf_puts(b, ",\"", line); ru_gbuf_puts(b, key, line); ru_gbuf_puts(b, "\":", line);
    if (which ? s->stroke_set : s->fill_set) {
        ru_gbuf_ch(b, '"', line);
        ru_gbuf_puts(b, which ? s->stroke : s->fill, line);
        ru_gbuf_ch(b, '"', line);
    } else ru_gbuf_puts(b, "\"\"", line); /* Python 侧空色为空串，非 null */
}
static void ru_g_json_style(RuGBuf *b, const RuGSnapshot *s, int with_fill, int line) {
    if (with_fill) ru_g_json_nullable_color(b, "fill", s, 0, line);
    ru_g_json_nullable_color(b, "stroke", s, 1, line);
    ru_gbuf_puts(b, ",\"stroke_width\":", line); ru_gbuf_num(b, s->line_width, line);
}
static void ru_g_json_points(RuGBuf *b, Val points, int line) {
    RuArray *arr = (RuArray *)points.heap;
    size_t i;
    ru_gbuf_puts(b, "[", line);
    for (i = 0; i < arr->len; i++) {
        RuArray *point;
        if (arr->items[i].kind != RU_ARRAY) ru_fail(line, "多边形每个点须为恰含两个坐标的阵");
        point = (RuArray *)arr->items[i].heap;
        if (point->len != 2) ru_fail(line, "多边形每个点须为恰含两个坐标的阵");
        if (i) ru_gbuf_ch(b, ',', line);
        ru_gbuf_ch(b, '[', line);
        ru_gbuf_num(b, ru_g_number(point->items[0], "横坐标", 0, 100000, 0, line), line);
        ru_gbuf_ch(b, ',', line);
        ru_gbuf_num(b, ru_g_number(point->items[1], "纵坐标", 0, 100000, 0, line), line);
        ru_gbuf_ch(b, ']', line);
    }
    ru_gbuf_ch(b, ']', line);
}

/* ---- 缓存（录制器） ---- */
static void ru_g_recorder_definition(RuGCanvas *r, RuGBuf *out, int line) {
    size_t i;
    ru_gbuf_puts(out, "{\"id\":\"", line); ru_gbuf_puts(out, r->resources[0].id, line);
    ru_gbuf_puts(out, "\",\"kind\":\"drawing\",\"width\":", line);
    ru_gbuf_num(out, r->width, line);
    ru_gbuf_puts(out, ",\"height\":", line); ru_gbuf_num(out, r->height, line);
    ru_gbuf_puts(out, ",\"commands\":[", line);
    for (i = 0; i < r->command_count; i++) {
        if (i) ru_gbuf_ch(out, ',', line);
        ru_gbuf_puts(out, r->items[i], line);
    }
    ru_gbuf_puts(out, "]}", line);
}

/* ---- 画布创建 ---- */
static Val ru_g_canvas_create(double width, double height, int line) {
    RuGCanvas *c = &ru_g_main_canvas;
    if (!ru_g_host)
        ru_fail(line, "如观画布需要图形宿主；请用 --target sdl 构建，或在宿主程序中调用 ru_graphics_set_host");
    if (ru_g_recording)
        ru_fail(line, "如观缓存录制期间不能创建主画布或嵌套缓存");
    if (c->open && !c->closed) ru_g_canvas_close(c);
    ru_g_canvas_clear(c);
    memset(&c->style, 0, sizeof c->style);
    strcpy(c->style.fill, "#4677ff"); c->style.fill_set = 1;
    strcpy(c->style.stroke, "#202530"); c->style.stroke_set = 1;
    c->style.line_width = 1; c->style.text_size = 16;
    c->style.text_align = 0; c->style.text_baseline = 0;
    memcpy(c->style.transform, (double[]){1, 0, 0, 1, 0, 0}, sizeof c->style.transform);
    c->style.metrics[0] = 1.0; c->style.metrics[1] = 0.56; c->style.metrics[2] = 1.5;
    if (ru_g_host->text_metrics) {
        double m[3];
        if (ru_g_host->text_metrics(ru_g_host->userdata, m)) {
            int i;
            for (i = 0; i < 3; i++)
                if (!isfinite(m[i]) || m[i] <= 0 || m[i] > 1000)
                    ru_fail(line, "如观字度宿主返回无效值");
            memcpy(c->style.metrics, m, sizeof m);
        }
    }
    c->width = width; c->height = height; c->fps = 30;
    c->frame = 0; c->open = 1; c->closed = 0; c->running = 0; c->dirty = 1; /* 同 Python 画布构造即脏：首帧无条件发出 */
    c->is_recorder = 0; c->owner = NULL; c->stack_len = 0; c->clips_len = 0;
    c->recorder_def_overhead = 0;
    c->origin = ru_g_now(line);
    c->previous_frame = c->origin; c->elapsed = 0; c->delta = 0;
    ru_g_host->open(ru_g_host->userdata, (int)width, (int)height);
    if (ru_g_host->services && ru_g_host->services[0]) ru_g_service_push_ad(ru_g_host->services);
    return ru_object_new(&ru_graphics_canvas_class, line);
}

/* ---- 主循环 ---- */
int ru_graphics_app_run(void) {
    RuGCanvas *c = &ru_g_main_canvas;
    double next_frame;
    if (!c->open || c->closed || !ru_g_host) return 0;
    ru_g_drain_events(1);
    ru_g_flush(1);
    next_frame = ru_g_now(1);
    while (c->open && !c->closed && !ru_panicking) {
        double now = ru_g_now(1);
        if (c->running && (c->callback_set & (1u << RU_G_EV_FRAME)) && now >= next_frame) {
            RuGEvent ev;
            memset(&ev, 0, sizeof ev);
            ev.kind = RU_G_EV_FRAME;
            ru_g_event_push(&ev);
            next_frame = now + 1.0 / c->fps;
            ru_g_drain_events(1);
            ru_g_flush(1);
        } else {
            double wait = 0.05;
            if (c->running && (c->callback_set & (1u << RU_G_EV_FRAME))) {
                wait = next_frame - now;
                if (wait > 0.05) wait = 0.05;
                if (wait < 0) wait = 0;
            }
            if (ru_g_host->idle) ru_g_host->idle(ru_g_host->userdata, wait);
            ru_g_drain_events(1);
            ru_g_flush(1);
        }
    }
    return 1;
}

/* ---- 成员派发 ---- */
static int ru_graphics_member(Val receiver, const char *name, size_t argc,
                              const char **keys, Val *args, int line, Val *out) {
    RuClass *klass = receiver.kind == RU_OBJECT ? ((RuObject *)receiver.heap)->klass : NULL;
    Val bound[8];
    RuGCanvas *canvas = NULL;
    int is_recorder = 0;
    if (klass == &ru_graphics_helpers_class) {
        if (!strcmp(name, "颜色")) {
            static const char *names[] = {"红", "绿", "蓝", "不透明度", NULL};
            double r, g, b, a;
            char text[10];
            ru_bind(name, 4, names, argc, keys, args, bound, line);
            r = ru_g_number(bound[0], "红", 0, 255, 1, line);
            g = ru_g_number(bound[1], "绿", 0, 255, 1, line);
            b = ru_g_number(bound[2], "蓝", 0, 255, 1, line);
            a = ru_g_number(bound[3], "不透明度", 0, 255, 1, line);
            snprintf(text, sizeof text, "#%02x%02x%02x%02x", (unsigned)r, (unsigned)g, (unsigned)b, (unsigned)a);
            *out = v_str(text);
            return 1;
        }
        if (!strcmp(name, "画布")) {
            static const char *names[] = {"宽", "高", NULL};
            double width, height;
            ru_bind(name, 2, names, argc, keys, args, bound, line);
            width = ru_g_number(bound[0], "宽", 1, 2048, 1, line);
            height = ru_g_number(bound[1], "高", 1, 2048, 1, line);
            *out = ru_g_canvas_create(width, height, line);
            return 1;
        }
        return 0;
    }
    if (klass == &ru_graphics_image_class) {
        RuObject *image = (RuObject *)receiver.heap;
        static const char *no_names[] = {NULL};
        if (strcmp(name, "宽") && strcmp(name, "高")) ru_fail(line, "如观图像只提供只读宽、高");
        ru_bind(name, 0, no_names, argc, keys, args, bound, line);
        *out = image->fields[!strcmp(name, "宽") ? 1 : 2];
        return 1;
    }
    if (klass == &ru_graphics_canvas_class) {
        canvas = &ru_g_main_canvas;
        is_recorder = 0;
    } else if (klass == &ru_graphics_recorder_class) {
        canvas = ru_g_recording;
        is_recorder = 1;
    } else return 0;
    if (!canvas || canvas->closed || (is_recorder && ru_g_recording != &ru_g_recorder_storage))
        ru_fail(line, "如观画布已关闭；运行新代码格、停止或重启会话后，请重新创建画布");
    if (!is_recorder && ru_g_recording && !ru_g_read_member(name))
        ru_fail(line, "如观缓存录制期间不能修改主画布或嵌套缓存");
    if (is_recorder && ru_g_recorder_forbidden(name))
        ru_fail(line, "如观缓存绘图目标不支持成员：%s", name);

#define RU_G_BIND2(nm, n1, n2) static const char *nm##_names[] = {n1, n2, NULL}; \
    ru_bind(name, 2, nm##_names, argc, keys, args, bound, line)
#define RU_G_BIND4(nm, n1, n2, n3, n4) static const char *nm##_names[] = {n1, n2, n3, n4, NULL}; \
    ru_bind(name, 4, nm##_names, argc, keys, args, bound, line)
#define RU_G_BIND6(nm, n1, n2, n3, n4, n5, n6) static const char *nm##_names[] = {n1, n2, n3, n4, n5, n6, NULL}; \
    ru_bind(name, 6, nm##_names, argc, keys, args, bound, line)
#define RU_G_BIND8(nm, n1, n2, n3, n4, n5, n6, n7, n8) static const char *nm##_names[] = {n1, n2, n3, n4, n5, n6, n7, n8, NULL}; \
    ru_bind(name, 8, nm##_names, argc, keys, args, bound, line)
#define RU_G_BIND0(nm) static const char *nm##_names[] = {NULL}; \
    ru_bind(name, 0, nm##_names, argc, keys, args, bound, line)

    if (!strcmp(name, "缓存")) {
        static const char *names[] = {"宽", "高", "绘制", NULL};
        RuGCanvas *owner = &ru_g_main_canvas;
        RuGCanvas *recorder = &ru_g_recorder_storage;
        RuGBuf definition;
        size_t size;
        char resource_id[24];
        Val target, result;
        RuObject *image_obj;
        ru_bind(name, 3, names, argc, keys, args, bound, line);
        if (ru_g_phase != 0) ru_fail(line, "如观缓存仅可在初始化执行时创建，不能在事件回调中创建");
        recorder->width = ru_g_number(bound[0], "宽", 1, 2048, 1, line);
        recorder->height = ru_g_number(bound[1], "高", 1, 2048, 1, line);
        if (bound[2].kind != RU_FUNCTION
            || ((RuCallable *)bound[2].heap)->function->count != 1)
            ru_fail(line, "缓存绘制需要接受 1 个参数的算／作回调");
        if (owner->resource_count >= RU_G_MAX_IMAGES)
            ru_fail(line, "如观每画布最多 8 张缓存图像");
        if (owner->resource_pixels + (size_t)(recorder->width * recorder->height) > RU_G_MAX_RESOURCE_PIXELS)
            ru_fail(line, "如观全部缓存最多 4194304 像素");
        snprintf(resource_id, sizeof resource_id, "cache-%d", owner->resource_count + 1);
        memset(recorder, 0, sizeof *recorder);
        recorder->is_recorder = 1;
        recorder->owner = owner;
        recorder->width = ru_g_number(bound[0], "宽", 1, 2048, 1, line);
        recorder->height = ru_g_number(bound[1], "高", 1, 2048, 1, line);
        strcpy(recorder->style.fill, "#4677ff"); recorder->style.fill_set = 1;
        strcpy(recorder->style.stroke, "#202530"); recorder->style.stroke_set = 1;
        recorder->style.line_width = 1; recorder->style.text_size = 16;
        memcpy(recorder->style.transform, (double[]){1, 0, 0, 1, 0, 0}, sizeof recorder->style.transform);
        recorder->style.metrics[0] = 1.0; recorder->style.metrics[1] = 0.56; recorder->style.metrics[2] = 1.5;
        recorder->open = 1; recorder->command_bytes = 2;
        /* 配方开销缓存：空命令数组的 definition 长度。 */
        { RuGBuf empty; empty.data = NULL; empty.len = empty.cap = 0;
          ru_g_recorder_definition(recorder, &empty, line);
          recorder->recorder_def_overhead = empty.len; ru_gbuf_free(&empty); }
        strcpy(recorder->resources[0].id, resource_id);
        ru_g_recording = recorder;
        target = ru_object_new(&ru_graphics_recorder_class, line);
        { static const char *nokeys[1] = {NULL};
          Val argv1[1]; Val fnres;
          argv1[0] = target;
          fnres = v_call(bound[2], 1, nokeys, argv1, line);
          v_drop(fnres); }
        v_drop(target);
        ru_g_recording = NULL;
        if (ru_panicking) { recorder->closed = 1; return 1; }
        ru_g_check_balanced(recorder, line);
        definition.data = NULL; definition.len = definition.cap = 0;
        ru_g_recorder_definition(recorder, &definition, line);
        size = definition.len + (owner->resource_count ? 1 : 0);
        if (owner->resource_bytes + size > (size_t)RU_G_MAX_RESOURCE_BYTES)
            ru_fail(line, "如观全部缓存定义最多 128 KiB UTF-8 数据；请减少图形或文字");
        { int idx = owner->resource_count++;
          strcpy(owner->resources[idx].id, resource_id);
          owner->resources[idx].definition = ru_g_realloc(NULL, definition.len + 1, line);
          memcpy(owner->resources[idx].definition, definition.data, definition.len + 1);
          owner->resources[idx].definition_len = definition.len;
          owner->resources[idx].count = (long)recorder->command_count;
          owner->resources[idx].pixels = (long)(recorder->width * recorder->height);
          owner->resource_bytes += size;
          owner->resource_pixels += (size_t)(recorder->width * recorder->height); }
        ru_gbuf_free(&definition);
        recorder->closed = 1;
        result = ru_object_new(&ru_graphics_image_class, line);
        image_obj = (RuObject *)result.heap;
        image_obj->fields[0] = v_str(resource_id);
        image_obj->fields[1] = v_num(recorder->width);
        image_obj->fields[2] = v_num(recorder->height);
        { size_t i; for (i = 0; i < recorder->command_count; i++) free(recorder->items[i]);
          free(recorder->items); recorder->items = NULL; }
        *out = result;
        return 1;
    }
    if (!strcmp(name, "贴图")) {
        static const char *names[] = {"图像", "横", "纵", NULL};
        RuObject *image;
        RuGBuf cmd; const char *resource;
        int i, found = -1;
        ru_bind(name, 3, names, argc, keys, args, bound, line);
        if (bound[0].kind != RU_OBJECT || ((RuObject *)bound[0].heap)->klass != &ru_graphics_image_class)
            ru_fail(line, "贴图需要如观图像");
        image = (RuObject *)bound[0].heap;
        resource = image->fields[0].kind == RU_STR ? image->fields[0].s->data : "";
        for (i = 0; i < ru_g_main_canvas.resource_count; i++)
            if (!strcmp(ru_g_main_canvas.resources[i].id, resource)) { found = i; break; }
        if (found < 0)
            ru_fail(line, "如观图像已失效或属于另一画布；请重新创建缓存");
        cmd.data = NULL; cmd.len = cmd.cap = 0;
        ru_gbuf_puts(&cmd, "{\"op\":\"image\",\"resource\":\"", line);
        ru_gbuf_puts(&cmd, resource, line);
        ru_gbuf_puts(&cmd, "\",\"x\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[1], "横", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"y\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[2], "纵", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, "}", line);
        canvas->image_refs |= (1u << found);
        ru_g_command(canvas, cmd.data, 0, line);
        ru_gbuf_free(&cmd);
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "图请求")) {
        static const char *names[] = {"号", "源", NULL};
        const char *source;
        long handle;
        RuGBuf cmd;
        ru_bind(name, 2, names, argc, keys, args, bound, line);
        handle = (long)ru_g_number(bound[0], "号", 1, 10000000, 1, line);
        source = ru_g_text(bound[1], "如观图像源 须为非空句，最长 512 字节", line);
        if (!source[0] || strlen(source) > RU_G_MAX_SOURCE_CHARS)
            ru_fail(line, "如观图像源 须为非空句，最长 512 字节");
        if (!ru_g_handle_has(canvas->image_loads, canvas->image_loads_len, handle)
            && canvas->image_loads_len >= RU_G_MAX_LOAD_HANDLES)
            ru_fail(line, "如观图像装载最多 64 项；请用 图释放 归还句柄");
        ru_g_handle_add(canvas->image_loads, &canvas->image_loads_len, handle);
        cmd.data = NULL; cmd.len = cmd.cap = 0;
        ru_gbuf_puts(&cmd, "{\"op\":\"image_request\",\"id\":", line);
        ru_gbuf_num(&cmd, (double)handle, line);
        ru_gbuf_puts(&cmd, ",\"source\":", line);
        ru_gbuf_json_str(&cmd, source, strlen(source), line);
        ru_gbuf_puts(&cmd, "}", line);
        ru_g_command(canvas, cmd.data, 0, line);
        ru_gbuf_free(&cmd);
        if (ru_g_host && ru_g_host->auto_load) ru_g_load_push(0, handle, source, 0);
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "绘图")) {
        static const char *names[] = {"号", "横", "纵", "宽", "高", NULL};
        RuGBuf cmd;
        double handle, x, y, w, h;
        ru_bind(name, 5, names, argc, keys, args, bound, line);
        handle = ru_g_number(bound[0], "号", 1, 10000000, 1, line);
        x = ru_g_number(bound[1], "横", 0, 100000, 0, line);
        y = ru_g_number(bound[2], "纵", 0, 100000, 0, line);
        w = ru_g_number(bound[3], "宽", 0, 100000, 0, line);
        h = ru_g_number(bound[4], "高", 0, 100000, 0, line);
        cmd.data = NULL; cmd.len = cmd.cap = 0;
        ru_gbuf_puts(&cmd, "{\"op\":\"draw_image\",\"id\":", line); ru_gbuf_num(&cmd, handle, line);
        ru_gbuf_puts(&cmd, ",\"x\":", line); ru_gbuf_num(&cmd, x, line);
        ru_gbuf_puts(&cmd, ",\"y\":", line); ru_gbuf_num(&cmd, y, line);
        ru_gbuf_puts(&cmd, ",\"width\":", line); ru_gbuf_num(&cmd, w, line);
        ru_gbuf_puts(&cmd, ",\"height\":", line); ru_gbuf_num(&cmd, h, line);
        ru_gbuf_puts(&cmd, "}", line);
        ru_g_command(canvas, cmd.data, 0, line);
        ru_gbuf_free(&cmd);
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "图释放")) {
        static const char *names[] = {"号", NULL};
        long handle;
        RuGBuf cmd;
        ru_bind(name, 1, names, argc, keys, args, bound, line);
        handle = (long)ru_g_number(bound[0], "号", 1, 10000000, 1, line);
        { int at = ru_g_handle_find(canvas->image_loads, canvas->image_loads_len, handle);
          if (at < canvas->image_loads_len && canvas->image_loads[at] == handle) {
              memmove(canvas->image_loads + at, canvas->image_loads + at + 1,
                      (size_t)(canvas->image_loads_len - at - 1) * sizeof(long));
              canvas->image_loads_len--; } }
        cmd.data = NULL; cmd.len = cmd.cap = 0;
        ru_gbuf_puts(&cmd, "{\"op\":\"image_release\",\"id\":", line);
        ru_gbuf_num(&cmd, (double)handle, line);
        ru_gbuf_puts(&cmd, "}", line);
        ru_g_command(canvas, cmd.data, 0, line);
        ru_gbuf_free(&cmd);
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "件请求")) {
        static const char *names[] = {"号", "源", "式", NULL};
        long handle;
        const char *source, *mode;
        RuGBuf cmd;
        ru_bind(name, 3, names, argc, keys, args, bound, line);
        handle = (long)ru_g_number(bound[0], "号", 1, 10000000, 1, line);
        source = ru_g_text(bound[1], "如观文件源 须为非空句，最长 512 字节", line);
        if (!source[0] || strlen(source) > RU_G_MAX_SOURCE_CHARS)
            ru_fail(line, "如观文件源 须为非空句，最长 512 字节");
        mode = ru_g_text(bound[2], "如观文件模式 只支持 '文' 或 'base64'", line);
        if (strcmp(mode, "文") && strcmp(mode, "base64"))
            ru_fail(line, "如观文件模式 只支持 '文' 或 'base64'");
        if (!ru_g_handle_has(canvas->file_loads, canvas->file_loads_len, handle)
            && canvas->file_loads_len >= RU_G_MAX_LOAD_HANDLES)
            ru_fail(line, "如观文件装载最多 64 项");
        ru_g_handle_add(canvas->file_loads, &canvas->file_loads_len, handle);
        cmd.data = NULL; cmd.len = cmd.cap = 0;
        ru_gbuf_puts(&cmd, "{\"op\":\"file_request\",\"id\":", line);
        ru_gbuf_num(&cmd, (double)handle, line);
        ru_gbuf_puts(&cmd, ",\"source\":", line);
        ru_gbuf_json_str(&cmd, source, strlen(source), line);
        ru_gbuf_puts(&cmd, ",\"mode\":\"", line); ru_gbuf_puts(&cmd, mode, line);
        ru_gbuf_puts(&cmd, "\"}", line);
        ru_g_command(canvas, cmd.data, 0, line);
        ru_gbuf_free(&cmd);
        if (ru_g_host && ru_g_host->auto_load) ru_g_load_push(1, handle, source, !strcmp(mode, "文"));
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "服务请")) {
        static const char *names[] = {"号", "服务", "操作", "径", "文", "旗", NULL};
        long handle;
        const char *service, *action, *path, *text;
        RuGBuf cmd;
        ru_bind(name, 6, names, argc, keys, args, bound, line);
        handle = (long)ru_g_number(bound[0], "号", 1, 10000000, 1, line);
        service = ru_g_text(bound[1], "如观服务名 须为非空句，最长 64 字节", line);
        if (!service[0] || strlen(service) > RU_G_MAX_SERVICE_NAME_CHARS)
            ru_fail(line, "如观服务名 须为非空句，最长 64 字节");
        action = ru_g_text(bound[2], "如观服务操作 须为非空句，最长 64 字节", line);
        if (!action[0] || strlen(action) > RU_G_MAX_SERVICE_NAME_CHARS)
            ru_fail(line, "如观服务操作 须为非空句，最长 64 字节");
        path = ru_g_text(bound[3], "如观服务径 最长 512 字节", line);
        if (strlen(path) > RU_G_MAX_SOURCE_CHARS)
            ru_fail(line, "如观服务径 最长 512 字节");
        text = ru_g_text(bound[4], "如观服务文 最长 8 MiB", line);
        if (strlen(text) > RU_G_MAX_FILE_TEXT_BYTES)
            ru_fail(line, "如观服务文 最长 8 MiB");
        if (bound[5].kind != RU_FACT) ru_fail(line, "如观服务旗 须为真假");
        cmd.data = NULL; cmd.len = cmd.cap = 0;
        ru_gbuf_puts(&cmd, "{\"op\":\"service_request\",\"id\":", line);
        ru_gbuf_num(&cmd, (double)handle, line);
        ru_gbuf_puts(&cmd, ",\"service\":", line); ru_gbuf_json_str(&cmd, service, strlen(service), line);
        ru_gbuf_puts(&cmd, ",\"action\":", line); ru_gbuf_json_str(&cmd, action, strlen(action), line);
        ru_gbuf_puts(&cmd, ",\"path\":", line); ru_gbuf_json_str(&cmd, path, strlen(path), line);
        ru_gbuf_puts(&cmd, ",\"text\":", line); ru_gbuf_json_str(&cmd, text, strlen(text), line);
        ru_gbuf_puts(&cmd, ",\"flag\":", line);
        ru_gbuf_puts(&cmd, bound[5].n ? "true" : "false", line);
        ru_gbuf_puts(&cmd, "}", line);
        ru_g_command(canvas, cmd.data, 0, line);
        ru_gbuf_free(&cmd);
        if (ru_g_host) ru_g_service_push(handle, service, action, path, text, (int)bound[5].n);
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "入焦点")) {
        static const char *names[] = {"横", "纵", "宽", "高", "文", "标", NULL};
        const char *text;
        RuGBuf cmd;
        ru_bind(name, 6, names, argc, keys, args, bound, line);
        text = ru_g_text(bound[4], "如观文入文本 须为句，最长 8 MiB", line);
        if (strlen(text) > RU_G_MAX_FILE_TEXT_BYTES)
            ru_fail(line, "如观文入文本 须为句，最长 8 MiB");
        cmd.data = NULL; cmd.len = cmd.cap = 0;
        ru_gbuf_puts(&cmd, "{\"op\":\"text_focus\",\"x\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[0], "横", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"y\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[1], "纵", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"width\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[2], "宽", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"height\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[3], "高", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"text\":", line);
        ru_gbuf_json_str(&cmd, text, strlen(text), line);
        ru_gbuf_puts(&cmd, ",\"cursor\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[5], "标", 0, RU_G_MAX_PASTE_CHARS, 1, line), line);
        ru_gbuf_puts(&cmd, "}", line);
        ru_g_command(canvas, cmd.data, 0, line);
        ru_gbuf_free(&cmd);
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "入失焦")) {
        RU_G_BIND0(g_blur);
        (void)g_blur_names;
        ru_g_command(canvas, "{\"op\":\"text_blur\"}", 0, line);
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "入更新")) {
        static const char *names[] = {"文", "标", NULL};
        const char *text;
        RuGBuf cmd;
        ru_bind(name, 2, names, argc, keys, args, bound, line);
        text = ru_g_text(bound[0], "如观文入文本 最长 4096 字", line);
        if (ru_g_utf8_count(text) > RU_G_MAX_PASTE_CHARS)
            ru_fail(line, "如观文入文本 最长 4096 字");
        cmd.data = NULL; cmd.len = cmd.cap = 0;
        ru_gbuf_puts(&cmd, "{\"op\":\"text_update\",\"text\":", line);
        ru_gbuf_json_str(&cmd, text, strlen(text), line);
        ru_gbuf_puts(&cmd, ",\"cursor\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[1], "标", 0, RU_G_MAX_PASTE_CHARS, 1, line), line);
        ru_gbuf_puts(&cmd, ",\"sel\":\"\"}", line);
        ru_g_command(canvas, cmd.data, 0, line);
        ru_gbuf_free(&cmd);
        *out = v_null();
        return 1;
    }
    {
        const RuGCallbackDef *def = ru_g_callback_find(name);
        if (def) {
            static const char *cb_names[] = {"回调", NULL};
            ru_bind(name, 1, cb_names, argc, keys, args, bound, line);
            if (bound[0].kind != RU_FUNCTION
                || ((RuCallable *)bound[0].heap)->function->count != (size_t)def->arity)
                ru_fail(line, "%s需要接受 %d 个参数的算／作回调", name, def->arity);
            if (canvas->callback_set & (1u << def->kind)) v_drop(canvas->callbacks[def->kind]);
            else canvas->handler_order[canvas->handler_order_len++] = (uint8_t)def->kind;
            canvas->callbacks[def->kind] = v_copy(bound[0]);
            canvas->callback_set |= 1u << def->kind;
            if (def->kind == RU_G_EV_FRAME) ru_g_set_running(canvas, 1);
            *out = v_null();
            return 1;
        }
    }
    if (!strcmp(name, "宽") || !strcmp(name, "高") || !strcmp(name, "帧")) {
        RU_G_BIND0(g_dim);
        (void)g_dim_names;
        *out = v_num(!strcmp(name, "宽") ? canvas->width : !strcmp(name, "高") ? canvas->height : (double)canvas->frame);
        return 1;
    }
    if (!strcmp(name, "尺寸")) {
        RU_G_BIND2(g_size, "宽", "高");
        (void)g_size_names;
        canvas->width = ru_g_number(bound[0], "宽", 1, 100000, 1, line);
        canvas->height = ru_g_number(bound[1], "高", 1, 100000, 1, line);
        canvas->dirty = 1;
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "经过秒") || !strcmp(name, "间隔秒")) {
        RU_G_BIND0(g_time);
        (void)g_time_names;
        *out = v_num(!strcmp(name, "经过秒") ? canvas->elapsed : canvas->delta);
        return 1;
    }
    if (!strcmp(name, "字度")) {
        static const char *const metric_keys[] = {"全", "半", "行"};
        Val map;
        int i;
        RU_G_BIND0(g_metrics);
        (void)g_metrics_names;
        map = v_map_new(line);
        for (i = 0; i < 3; i++)
            v_map_put(map, v_str(metric_keys[i]), v_num(canvas->style.metrics[i]), line);
        *out = map;
        return 1;
    }
    if (!strcmp(name, "测文")) {
        static const char *names[] = {"文", NULL};
        const char *text;
        ru_bind(name, 1, names, argc, keys, args, bound, line);
        text = ru_g_text(bound[0], "测文须为不超过 4096 字符的句", line);
        if (ru_g_utf8_count(text) > RU_G_MAX_TEXT_CHARS)
            ru_fail(line, "测文须为不超过 4096 字符的句");
        *out = v_num(ru_g_measure(canvas, text, strlen(text), line));
        return 1;
    }
    if (!strcmp(name, "关闭")) {
        RU_G_BIND0(g_close);
        (void)g_close_names;
        canvas->stack_len = 0;
        ru_g_flush(line);
        ru_g_canvas_close(canvas);
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "停") || !strcmp(name, "继续")) {
        RU_G_BIND0(g_run);
        (void)g_run_names;
        ru_g_set_running(canvas, !strcmp(name, "继续") && (canvas->callback_set & (1u << RU_G_EV_FRAME)));
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "帧率")) {
        static const char *names[] = {"率", NULL};
        ru_bind(name, 1, names, argc, keys, args, bound, line);
        canvas->fps = ru_g_number(bound[0], "帧率", 1, 30, 1, line);
        canvas->dirty = 1;
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "填色") || !strcmp(name, "描边")) {
        static const char *names[] = {"色", NULL};
        char color[10];
        int set;
        ru_bind(name, 1, names, argc, keys, args, bound, line);
        set = ru_g_color_parse(bound[0], color, 1, line);
        if (!strcmp(name, "填色")) { canvas->style.fill_set = set; if (set) strcpy(canvas->style.fill, color); }
        else { canvas->style.stroke_set = set; if (set) strcpy(canvas->style.stroke, color); }
        canvas->dirty = 1;
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "线宽") || !strcmp(name, "字号")) {
        static const char *lw_names[] = {"粗", NULL};
        static const char *ts_names[] = {"大小", NULL};
        double value;
        if (!strcmp(name, "线宽")) { ru_bind(name, 1, lw_names, argc, keys, args, bound, line); }
        else { ru_bind(name, 1, ts_names, argc, keys, args, bound, line); }
        value = ru_g_number(bound[0], name, 1, 256, 0, line);
        if (!strcmp(name, "线宽")) canvas->style.line_width = value; else canvas->style.text_size = value;
        canvas->dirty = 1;
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "文字对齐")) {
        static const char *names[] = {"横向", "纵向", NULL};
        const char *h, *v;
        int ha, va;
        ru_bind(name, 2, names, argc, keys, args, bound, line);
        h = ru_g_text(bound[0], "文字对齐横向须为 '左'、'中' 或 '右' 的句", line);
        v = ru_g_text(bound[1], "文字对齐纵向须为 '上'、'中'、'下' 或 '基线' 的句", line);
        if (!strcmp(h, "左")) ha = 0; else if (!strcmp(h, "中")) ha = 1; else if (!strcmp(h, "右")) ha = 2;
        else ru_fail(line, "文字对齐横向须为 '左'、'中' 或 '右' 的句");
        if (!strcmp(v, "上")) va = 0; else if (!strcmp(v, "中")) va = 1; else if (!strcmp(v, "下")) va = 2;
        else if (!strcmp(v, "基线")) va = 3;
        else ru_fail(line, "文字对齐纵向须为 '上'、'中'、'下' 或 '基线' 的句");
        canvas->style.text_align = ha; canvas->style.text_baseline = va;
        canvas->dirty = 1;
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "保存")) {
        RU_G_BIND0(g_save);
        (void)g_save_names;
        if (canvas->stack_len >= RU_G_MAX_SAVE_DEPTH) ru_fail(line, "如观最多保存 64 层状态");
        canvas->stack[canvas->stack_len++] = canvas->style;
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "恢复")) {
        RU_G_BIND0(g_restore);
        (void)g_restore_names;
        if (!canvas->stack_len) ru_fail(line, "如观恢复没有对应的保存");
        canvas->style = canvas->stack[--canvas->stack_len];
        canvas->dirty = 1;
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "重置变换")) {
        RU_G_BIND0(g_reset);
        (void)g_reset_names;
        memcpy(canvas->style.transform, (double[]){1, 0, 0, 1, 0, 0}, sizeof canvas->style.transform);
        canvas->dirty = 1;
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "取消裁剪")) {
        RU_G_BIND0(g_unclip);
        (void)g_unclip_names;
        canvas->clips_len = 0;
        canvas->dirty = 1;
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "平移") || !strcmp(name, "旋转") || !strcmp(name, "缩放") || !strcmp(name, "变换")) {
        double m[6];
        if (!strcmp(name, "平移")) {
            RU_G_BIND2(g_move, "横", "纵");
            (void)g_move_names;
            m[0] = 1; m[1] = 0; m[2] = 0; m[3] = 1;
            m[4] = ru_g_number(bound[0], "横", 0, 100000, 0, line);
            m[5] = ru_g_number(bound[1], "纵", 0, 100000, 0, line);
        } else if (!strcmp(name, "旋转")) {
            static const char *names[] = {"弧度", NULL};
            double angle, cs, sn;
            ru_bind(name, 1, names, argc, keys, args, bound, line);
            angle = ru_g_number(bound[0], "弧度", 0, 100000, 0, line);
            cs = cos(angle); sn = sin(angle);
            m[0] = cs; m[1] = sn; m[2] = -sn; m[3] = cs; m[4] = 0; m[5] = 0;
        } else if (!strcmp(name, "缩放")) {
            static const char *names[] = {"横倍率", "纵倍率", NULL};
            ru_bind(name, 2, names, argc, keys, args, bound, line);
            m[0] = ru_g_number(bound[0], "横倍率", 0, 100000, 0, line); m[1] = 0; m[2] = 0;
            m[3] = ru_g_number(bound[1], "纵倍率", 0, 100000, 0, line); m[4] = 0; m[5] = 0;
        } else {
            static const char *names[] = {"a", "b", "c", "d", "e", "f", NULL};
            int i;
            ru_bind(name, 6, names, argc, keys, args, bound, line);
            for (i = 0; i < 6; i++) m[i] = ru_g_number(bound[i], "变换分量", 0, 100000, 0, line);
        }
        ru_g_compose(canvas, m, line);
        canvas->dirty = 1;
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "裁剪")) {
        RU_G_BIND4(g_clip, "横", "纵", "宽", "高");
        RuGClip *clip;
        (void)g_clip_names;
        if (canvas->clips_len >= RU_G_MAX_CLIPS) ru_fail(line, "如观最多叠加 32 个裁剪区域");
        clip = &canvas->clips[canvas->clips_len++];
        clip->x = ru_g_number(bound[0], "横", 0, 100000, 0, line);
        clip->y = ru_g_number(bound[1], "纵", 0, 100000, 0, line);
        clip->width = ru_g_number(bound[2], "宽", 0, 100000, 0, line);
        clip->height = ru_g_number(bound[3], "高", 0, 100000, 0, line);
        memcpy(clip->transform, canvas->style.transform, sizeof clip->transform);
        canvas->dirty = 1;
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "三角形") || !strcmp(name, "多边形") || !strcmp(name, "折线")) {
        RuGBuf cmd;
        RuArray *points_arr = NULL;
        size_t point_count = 0, i;
        double coords[6];
        int is_polyline = !strcmp(name, "折线");
        if (!strcmp(name, "三角形")) {
            RU_G_BIND6(g_tri, "横一", "纵一", "横二", "纵二", "横三", "纵三");
            (void)g_tri_names;
            for (i = 0; i < 6; i++) coords[i] = ru_g_number(bound[i], "坐标", 0, 100000, 0, line);
        } else {
            static const char *names[] = {"点阵", NULL};
            size_t minimum = is_polyline ? 2 : 3;
            ru_bind(name, 1, names, argc, keys, args, bound, line);
            if (bound[0].kind != RU_ARRAY) ru_fail(line, "%s点阵须为包含 %zu 至 256 个点的阵", name, minimum);
            points_arr = (RuArray *)bound[0].heap;
            point_count = points_arr->len;
            if (point_count < minimum || point_count > 256)
                ru_fail(line, "%s点阵须为包含 %zu 至 256 个点的阵", name, minimum);
        }
        cmd.data = NULL; cmd.len = cmd.cap = 0;
        ru_gbuf_puts(&cmd, is_polyline ? "{\"op\":\"polyline\",\"points\":" : "{\"op\":\"polygon\",\"points\":", line);
        if (points_arr) ru_g_json_points(&cmd, bound[0], line);
        else {
            ru_gbuf_puts(&cmd, "[[", line); ru_gbuf_num(&cmd, coords[0], line); ru_gbuf_ch(&cmd, ',', line); ru_gbuf_num(&cmd, coords[1], line);
            ru_gbuf_puts(&cmd, "],[", line); ru_gbuf_num(&cmd, coords[2], line); ru_gbuf_ch(&cmd, ',', line); ru_gbuf_num(&cmd, coords[3], line);
            ru_gbuf_puts(&cmd, "],[", line); ru_gbuf_num(&cmd, coords[4], line); ru_gbuf_ch(&cmd, ',', line); ru_gbuf_num(&cmd, coords[5], line);
            ru_gbuf_puts(&cmd, "]]", line);
        }
        if (is_polyline) ru_gbuf_puts(&cmd, ",\"fill\":\"\"", line);
        else ru_g_json_nullable_color(&cmd, "fill", &canvas->style, 0, line);
        ru_g_json_nullable_color(&cmd, "stroke", &canvas->style, 1, line);
        ru_gbuf_puts(&cmd, ",\"stroke_width\":", line);
        ru_gbuf_num(&cmd, canvas->style.line_width, line);
        ru_gbuf_puts(&cmd, "}", line);
        ru_g_command(canvas, cmd.data, 0, line);
        ru_gbuf_free(&cmd);
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "背景")) {
        static const char *names[] = {"色", NULL};
        char color[10];
        size_t i, kept = 0, old_count = canvas->command_count;
        char **kept_items = NULL;
        RuGBuf cmd;
        ru_bind(name, 1, names, argc, keys, args, bound, line);
        ru_g_color_parse(bound[0], color, 0, line);
        for (i = 0; i < old_count; i++)
            if (ru_g_op_kept_on_background(canvas->items[i])) kept++;
        if (kept) kept_items = (char **)ru_alloc(kept * sizeof(char *), line);
        kept = 0;
        for (i = 0; i < old_count; i++) {
            if (ru_g_op_kept_on_background(canvas->items[i])) kept_items[kept++] = canvas->items[i];
            else free(canvas->items[i]);
        }
        for (i = 0; i < kept; i++) canvas->items[i] = kept_items[i];
        canvas->command_count = kept;
        canvas->command_bytes = 2;
        for (i = 0; i < kept; i++) canvas->command_bytes += strlen(canvas->items[i]) + 1;
        if (kept_items) ru_scratch_free(kept_items);
        canvas->image_refs = 0;
        cmd.data = NULL; cmd.len = cmd.cap = 0;
        ru_gbuf_puts(&cmd, "{\"op\":\"background\",\"color\":\"", line);
        ru_gbuf_puts(&cmd, color, line);
        ru_gbuf_puts(&cmd, "\"}", line);
        ru_g_command(canvas, cmd.data, 1, line);
        ru_gbuf_free(&cmd);
        canvas->dirty = 1;
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "弧") || !strcmp(name, "扇形") || !strcmp(name, "矩形") || !strcmp(name, "椭圆")) {
        double x, y, w, h;
        int is_arc = !strcmp(name, "弧"), is_sector = !strcmp(name, "扇形");
        RuGBuf cmd;
        if (is_arc || is_sector) { RU_G_BIND6(g_arc, "横", "纵", "宽", "高", "始角", "转角"); (void)g_arc_names; }
        else { RU_G_BIND4(g_shape, "横", "纵", "宽", "高"); (void)g_shape_names; }
        x = ru_g_number(bound[0], "横", 0, 100000, 0, line);
        y = ru_g_number(bound[1], "纵", 0, 100000, 0, line);
        w = ru_g_number(bound[2], "宽", 0, 100000, 0, line);
        h = ru_g_number(bound[3], "高", 0, 100000, 0, line);
        cmd.data = NULL; cmd.len = cmd.cap = 0;
        ru_gbuf_puts(&cmd, !strcmp(name, "矩形") ? "{\"op\":\"rect\"" : !strcmp(name, "椭圆") ? "{\"op\":\"ellipse\"" : is_arc ? "{\"op\":\"arc\"" : "{\"op\":\"sector\"", line);
        ru_gbuf_puts(&cmd, ",\"x\":", line); ru_gbuf_num(&cmd, x, line);
        ru_gbuf_puts(&cmd, ",\"y\":", line); ru_gbuf_num(&cmd, y, line);
        ru_gbuf_puts(&cmd, ",\"width\":", line); ru_gbuf_num(&cmd, w, line);
        ru_gbuf_puts(&cmd, ",\"height\":", line); ru_gbuf_num(&cmd, h, line);
        if (is_arc || is_sector) {
            ru_gbuf_puts(&cmd, ",\"start\":", line);
            ru_gbuf_num(&cmd, ru_g_number(bound[4], "始角", 0, 100000, 0, line), line);
            ru_gbuf_puts(&cmd, ",\"sweep\":", line);
            ru_gbuf_num(&cmd, ru_g_number(bound[5], "转角", 0, 100000, 0, line), line);
        }
        if (is_arc) ru_gbuf_puts(&cmd, ",\"fill\":\"\"", line);
        else ru_g_json_nullable_color(&cmd, "fill", &canvas->style, 0, line);
        ru_g_json_nullable_color(&cmd, "stroke", &canvas->style, 1, line);
        ru_gbuf_puts(&cmd, ",\"stroke_width\":", line);
        ru_gbuf_num(&cmd, canvas->style.line_width, line);
        ru_gbuf_puts(&cmd, "}", line);
        ru_g_command(canvas, cmd.data, 0, line);
        ru_gbuf_free(&cmd);
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "贝塞尔")) {
        static const char *names[] = {"起横", "起纵", "控一横", "控一纵", "控二横", "控二纵", "终横", "终纵", NULL};
        RuGBuf cmd;
        int i;
        ru_bind(name, 8, names, argc, keys, args, bound, line);
        cmd.data = NULL; cmd.len = cmd.cap = 0;
        ru_gbuf_puts(&cmd, "{\"op\":\"bezier\",\"x1\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[0], "起横", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"y1\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[1], "起纵", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"cx1\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[2], "控一横", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"cy1\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[3], "控一纵", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"cx2\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[4], "控二横", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"cy2\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[5], "控二纵", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"x2\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[6], "终横", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"y2\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[7], "终纵", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"fill\":\"\"", line);
        ru_g_json_nullable_color(&cmd, "stroke", &canvas->style, 1, line);
        ru_gbuf_puts(&cmd, ",\"stroke_width\":", line);
        ru_gbuf_num(&cmd, canvas->style.line_width, line);
        ru_gbuf_puts(&cmd, "}", line);
        for (i = 0; i < 8; i++) { }
        ru_g_command(canvas, cmd.data, 0, line);
        ru_gbuf_free(&cmd);
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "线")) {
        static const char *names[] = {"横一", "纵一", "横二", "纵二", NULL};
        RuGBuf cmd;
        ru_bind(name, 4, names, argc, keys, args, bound, line);
        cmd.data = NULL; cmd.len = cmd.cap = 0;
        ru_gbuf_puts(&cmd, "{\"op\":\"line\",\"x1\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[0], "横一", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"y1\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[1], "纵一", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"x2\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[2], "横二", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"y2\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[3], "纵二", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"color\":", line);
        if (canvas->style.stroke_set) { ru_gbuf_ch(&cmd, '"', line); ru_gbuf_puts(&cmd, canvas->style.stroke, line); ru_gbuf_ch(&cmd, '"', line); }
        else ru_gbuf_puts(&cmd, "null", line);
        ru_gbuf_puts(&cmd, ",\"width\":", line);
        ru_gbuf_num(&cmd, canvas->style.line_width, line);
        ru_gbuf_puts(&cmd, "}", line);
        ru_g_command(canvas, cmd.data, 0, line);
        ru_gbuf_free(&cmd);
        *out = v_null();
        return 1;
    }
    if (!strcmp(name, "文字")) {
        static const char *names[] = {"文", "横", "纵", NULL};
        const char *text;
        RuGBuf cmd;
        ru_bind(name, 3, names, argc, keys, args, bound, line);
        text = ru_g_text(bound[0], "文字须为不超过 4096 字符的句", line);
        if (ru_g_utf8_count(text) > RU_G_MAX_TEXT_CHARS)
            ru_fail(line, "文字须为不超过 4096 字符的句");
        cmd.data = NULL; cmd.len = cmd.cap = 0;
        ru_gbuf_puts(&cmd, "{\"op\":\"text\",\"x\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[1], "横", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"y\":", line);
        ru_gbuf_num(&cmd, ru_g_number(bound[2], "纵", 0, 100000, 0, line), line);
        ru_gbuf_puts(&cmd, ",\"text\":", line);
        ru_gbuf_json_str(&cmd, text, strlen(text), line);
        ru_gbuf_puts(&cmd, ",\"color\":", line);
        if (canvas->style.fill_set) { ru_gbuf_ch(&cmd, '"', line); ru_gbuf_puts(&cmd, canvas->style.fill, line); ru_gbuf_ch(&cmd, '"', line); }
        else ru_gbuf_puts(&cmd, "\"\"", line);
        ru_gbuf_puts(&cmd, ",\"size\":", line);
        ru_gbuf_num(&cmd, canvas->style.text_size, line);
        if (canvas->style.text_align == 1) ru_gbuf_puts(&cmd, ",\"align\":\"center\"", line);
        else if (canvas->style.text_align == 2) ru_gbuf_puts(&cmd, ",\"align\":\"right\"", line);
        if (canvas->style.text_baseline == 1) ru_gbuf_puts(&cmd, ",\"baseline\":\"middle\"", line);
        else if (canvas->style.text_baseline == 2) ru_gbuf_puts(&cmd, ",\"baseline\":\"bottom\"", line);
        else if (canvas->style.text_baseline == 3) ru_gbuf_puts(&cmd, ",\"baseline\":\"alphabetic\"", line);
        ru_gbuf_puts(&cmd, "}", line);
        ru_g_command(canvas, cmd.data, 0, line);
        ru_gbuf_free(&cmd);
        *out = v_null();
        return 1;
    }
    ru_fail(line, "未知如观画布成员：%s", name);
    return 0;
#undef RU_G_BIND0
#undef RU_G_BIND2
#undef RU_G_BIND4
#undef RU_G_BIND6
#undef RU_G_BIND8
}

/* ---- 内建环境 ---- */
static Env *ru_graphics_builtins(void) {
    static Env env;
    static int initialized;
    Val helpers;
    if (initialized) return &env;
    initialized = 1;
    env_init(&env, ru_practical_builtins());
    ru_graphics_helpers_class.global = &env;
    ru_graphics_canvas_class.global = &env;
    ru_graphics_recorder_class.global = &env;
    ru_graphics_image_class.global = &env;
    helpers = ru_object_new(&ru_graphics_helpers_class, 0);
    env_declare(&env, "__如观", helpers);
    v_drop(helpers);
    return &env;
}

#endif /* RULANG_GRAPHICS_RUNTIME_H */
