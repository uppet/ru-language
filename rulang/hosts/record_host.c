/* record_host.c — 如观 C 运行时的帧录制测试宿主（parity harness）。
 *
 * 把每个 push_frame 的 JSON 原样写到 stdout（一行一帧，前缀 "FRAME "），
 * 宿主侧动作（open/close/装载/服务请求）以 "EVENT ..." 行记录。
 * 用于与 Python GraphicsHost 的帧输出做 parity 对比；不含任何真实渲染。
 *
 * 确定性驱动协议（stdin，每行一条 JSON）：
 *   {"set_now": t}        虚拟时钟置 t（秒，单调；now() 返回值）
 *   {"advance": dt}       虚拟时钟前进 dt
 *   {"event": {...}}      立即 post 一个如观事件（字段同 Python 侧事件 dict）
 * stdin 耗尽（EOF）后，下一次 idle 会 post_close 结束 app_run。
 * idle 每回调至多消费一行脚本；消费脚本行时不推进时钟。
 * 装载/服务请求只记录不处理（就绪事件由脚本注入），服务广告为空。
 *
 * 编译：与 `ru build --target c --emit-c program.c` 的产物同链接：
 *   cc -O1 -std=gnu99 -I<repo> program.c rulang/hosts/record_host.c -lm -o app
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "rulang/graphics_abi.h"

static double record_virtual_now = 0.0;
static int record_eof = 0;

/* ---- 极简 JSON 行解析（仅支持本协议需要的形状） ---- */

/* 定位 "key" : 值 中值的起点（容忍冒号后空白，兼容 json.dumps 默认分隔符）。 */
static const char *record_json_value(const char *json, const char *key) {
    char pattern[64];
    const char *p;
    snprintf(pattern, sizeof pattern, "\"%s\"", key);
    p = strstr(json, pattern);
    if (!p) return NULL;
    p += strlen(pattern);
    while (*p == ' ' || *p == '\t') p++;
    if (*p != ':') return NULL;
    p++;
    while (*p == ' ' || *p == '\t') p++;
    return p;
}

static const char *record_json_str(const char *json, const char *key, char *out, size_t cap) {
    const char *p = record_json_value(json, key);
    const char *q;
    if (!p || *p != '"') return NULL;
    p++;
    q = strchr(p, '"');
    if (!q) return NULL;
    if ((size_t)(q - p) >= cap) return NULL;
    memcpy(out, p, (size_t)(q - p));
    out[q - p] = '\0';
    return out;
}

static int record_json_num(const char *json, const char *key, double *out) {
    const char *p = record_json_value(json, key);
    if (!p) return 0;
    *out = strtod(p, NULL);
    return 1;
}

/* ---- 宿主 vtable ---- */

static void record_open(void *ud, int w, int h) {
    (void)ud;
    printf("EVENT open %d %d\n", w, h);
}

static void record_close(void *ud) {
    (void)ud;
    printf("EVENT close\n");
}

static void record_frame(void *ud, const char *json, size_t bytes) {
    (void)ud;
    fwrite("FRAME ", 1, 6, stdout);
    fwrite(json, 1, bytes, stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

static double record_now(void *ud) {
    (void)ud;
    return record_virtual_now;
}

/* 处理一行脚本；返回 1 表示有动作，0 表示空行/无法解析。 */
static int record_script_line(const char *line) {
    double num;
    const char *ep;
    char text[4096];
    if (strstr(line, "\"set_now\"")) {
        if (record_json_num(line, "set_now", &num)) record_virtual_now = num;
        return 1;
    }
    if (strstr(line, "\"advance\"")) {
        if (record_json_num(line, "advance", &num)) record_virtual_now += num;
        return 1;
    }
    ep = record_json_value(line, "event");
    if (!ep) return 0;
    if (record_json_str(ep, "type", text, sizeof text)) {
        double x = 0, y = 0, button = 0, id = 0, w = 0, h = 0, cursor = 0, ok = 0;
        record_json_num(ep, "x", &x); record_json_num(ep, "y", &y);
        record_json_num(ep, "button", &button); record_json_num(ep, "id", &id);
        record_json_num(ep, "width", &w); record_json_num(ep, "height", &h);
        record_json_num(ep, "cursor", &cursor); record_json_num(ep, "ok", &ok);
        if (!strcmp(text, "mouse_down")) ru_graphics_post_mouse_down(x, y, (int)button);
        else if (!strcmp(text, "mouse_up")) ru_graphics_post_mouse_up(x, y, (int)button);
        else if (!strcmp(text, "mouse_move")) ru_graphics_post_mouse_move(x, y);
        else if (!strcmp(text, "touch_start")) ru_graphics_post_touch_start((long)id, x, y);
        else if (!strcmp(text, "touch_move")) ru_graphics_post_touch_move((long)id, x, y);
        else if (!strcmp(text, "touch_end")) ru_graphics_post_touch_end((long)id, x, y);
        else if (!strcmp(text, "key_down")) {
            if (record_json_str(ep, "key", text, sizeof text)) ru_graphics_post_key_down(text);
        } else if (!strcmp(text, "key_up")) {
            if (record_json_str(ep, "key", text, sizeof text)) ru_graphics_post_key_up(text);
        } else if (!strcmp(text, "resize")) ru_graphics_post_resize((int)w, (int)h);
        else if (!strcmp(text, "text_key")) {
            if (record_json_str(ep, "key", text, sizeof text)) ru_graphics_post_text_key(text);
        } else if (!strcmp(text, "text_char")) {
            if (record_json_str(ep, "text", text, sizeof text)) ru_graphics_post_text_char(text);
        } else if (!strcmp(text, "text_paste")) {
            if (record_json_str(ep, "text", text, sizeof text)) ru_graphics_post_text_paste(text);
        } else if (!strcmp(text, "text_comp_start")) ru_graphics_post_comp_start();
        else if (!strcmp(text, "text_comp_update")) {
            if (record_json_str(ep, "text", text, sizeof text))
                ru_graphics_post_comp_update(text, (int)cursor);
        } else if (!strcmp(text, "text_comp_end")) {
            if (record_json_str(ep, "text", text, sizeof text)) ru_graphics_post_comp_end(text);
        } else if (!strcmp(text, "image_ready"))
            ru_graphics_post_image_ready((long)id, (int)w, (int)h);
        else if (!strcmp(text, "image_failed")) {
            if (record_json_str(ep, "error", text, sizeof text))
                ru_graphics_post_image_failed((long)id, text);
        } else if (!strcmp(text, "file_ready")) {
            if (record_json_str(ep, "text", text, sizeof text))
                ru_graphics_post_file_ready((long)id, text);
        } else if (!strcmp(text, "file_failed")) {
            if (record_json_str(ep, "error", text, sizeof text))
                ru_graphics_post_file_failed((long)id, text);
        } else if (!strcmp(text, "service_response")) {
            char value[4096], error[4096];
            const char *vp = record_json_str(ep, "value", value, sizeof value);
            const char *ep2 = record_json_str(ep, "error", error, sizeof error);
            ru_graphics_post_service_response((long)id, (int)ok, vp, ep2);
        }
        /* frame 事件由运行时按虚拟时钟自行调度，脚本不注入。 */
    }
    return 1;
}

static void record_idle(void *ud, double seconds) {
    char line[8192];
    (void)ud;
    if (record_eof) {
        ru_graphics_post_close();
        return;
    }
    if (!fgets(line, sizeof line, stdin)) {
        record_eof = 1;
        ru_graphics_post_close();
        return;
    }
    if (record_script_line(line)) return;
    /* 空行/无法解析：按无脚本处理，推进时钟。 */
    record_virtual_now += seconds;
}

static void record_load_image(void *ud, long handle, const char *source) {
    (void)ud;
    printf("EVENT image_request %ld %s\n", handle, source);
}

static void record_load_file(void *ud, long handle, const char *source, int as_text) {
    (void)ud;
    printf("EVENT file_request %ld %s %d\n", handle, source, as_text);
}

static void record_service(void *ud, long handle, const char *service,
                           const char *action, const char *path,
                           const char *text, int flag) {
    (void)ud; (void)path; (void)text; (void)flag;
    printf("EVENT service_request %ld %s %s\n", handle, service, action);
}

static const RuGuiHost record_host = {
    NULL, "", record_open, record_close, record_frame,
    record_now, NULL, NULL,
    record_load_image, record_load_file, record_service,
    NULL, record_idle,
    0, /* auto_load = 0：镜像 Python GraphicsHost(auto_load=False) 测试宿主 */
};

void record_host_install(void) { ru_graphics_set_host(&record_host); }

#if defined(__GNUC__)
__attribute__((constructor))
static void record_host_auto_install(void) { record_host_install(); }
#elif defined(_MSC_VER)
/* MSVC/clang-cl 无 GNU constructor 属性：注册进 CRT 初始化段，等效 pre-main 调用 */
#pragma section(".CRT$XCU", read)
__declspec(allocate(".CRT$XCU")) static void (*record_host_auto_install_p)(void) = record_host_install;
#endif
