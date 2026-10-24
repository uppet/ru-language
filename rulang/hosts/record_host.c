/* record_host.c — 如观 C 运行时的帧录制测试宿主。
 *
 * 把每个 push_frame 的 JSON 原样写到 stdout（一行一帧，前缀 "FRAME "），
 * 事件流（装载/服务）以 "EVENT ..." 行记录。用于与 Python GraphicsHost
 * 的帧输出做 parity 对比；不含任何真实渲染。
 *
 * 编译：与 `ru build --target c --emit-c program.c` 的产物同链接：
 *   cc -O1 -std=gnu99 -I<repo> program.c record_host.c -lm -o app
 * （record_host.c 提供 main 之前的 ru_graphics_set_host —— 见文件尾
 *   constructor 说明；若宿主环境不支持 constructor，可在程序 main 前
 *   显式调用 record_host_install()。）
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>
#include "rulang/graphics_abi.h"

static double record_now(void *ud) {
    struct timespec ts;
    (void)ud;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static void record_idle(void *ud, double seconds) {
    struct timespec ts;
    (void)ud;
    if (seconds <= 0) return;
    ts.tv_sec = (time_t)seconds;
    ts.tv_nsec = (long)((seconds - (double)ts.tv_sec) * 1e9);
    nanosleep(&ts, NULL);
}

static void record_frame(void *ud, const char *json, size_t bytes) {
    (void)ud;
    fwrite("FRAME ", 1, 6, stdout);
    fwrite(json, 1, bytes, stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

static void record_open(void *ud, int w, int h) {
    (void)ud;
    printf("EVENT open %d %d\n", w, h);
}

static void record_close(void *ud) {
    (void)ud;
    printf("EVENT close\n");
}

static void record_load_image(void *ud, long handle, const char *source) {
    (void)ud;
    printf("EVENT image_request %ld %s\n", handle, source);
    ru_graphics_post_image_failed(handle, "record host 无图像装载");
}

static void record_load_file(void *ud, long handle, const char *source, int as_text) {
    (void)ud;
    printf("EVENT file_request %ld %s %d\n", handle, source, as_text);
    ru_graphics_post_file_failed(handle, "record host 无档装载");
}

static void record_service(void *ud, long handle, const char *service,
                           const char *action, const char *path,
                           const char *text, int flag) {
    (void)ud; (void)path; (void)text; (void)flag;
    printf("EVENT service_request %ld %s %s\n", handle, service, action);
    ru_graphics_post_service_response(handle, 0, NULL, "record host 无网服务");
}

static const RuGuiHost record_host = {
    NULL, "", record_open, record_close, record_frame,
    record_now, NULL, NULL,
    record_load_image, record_load_file, record_service,
    NULL, record_idle,
};

void record_host_install(void) { ru_graphics_set_host(&record_host); }

#if defined(__GNUC__)
__attribute__((constructor))
#endif
static void record_host_auto_install(void) { record_host_install(); }
