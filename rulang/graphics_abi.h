/* graphics_abi.h — 如观 C 图形运行时的宿主 ABI。
 *
 * 壳（SDL2）与测试宿主（帧录制器）只应包含本文件，不得包含
 * graphics_runtime.h（其定义属于程序翻译单元，重复包含会链接冲突）。
 *
 * 生命周期：宿主在运行程序 main 之前先 ru_graphics_set_host(&vtable)；
 * vtable 中除 now 外均可按需置 NULL（缺省行为见各字段注释）。
 * 事件 post API 全部可重入；壳可在 push_frame/idle 内调用。
 */
#ifndef RULANG_GRAPHICS_ABI_H
#define RULANG_GRAPHICS_ABI_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct RuGuiHost {
    void *userdata;
    /* 壳所供服务（空格分隔，如 "档 网"）；NULL 或空串 = 不广告。 */
    const char *services;
    void (*open)(void *ud, int w, int h);
    void (*close)(void *ud);
    /* 一帧命令 JSON：{"frame":n,"width":w,"height":h,"commands":[...],"resources":[...]}。
     * 渲染须在回调返回前完成；回调内可安全 post 新事件。 */
    void (*push_frame)(void *ud, const char *json, size_t bytes);
    /* 单调秒（帧率上限、经过秒/间隔秒）。NULL → wall clock。 */
    double (*now)(void *ud);
    /* 测文（宿主精确测量）：返回像素宽；NaN/Inf/<0/>10000000 → 运行时 fail。
     * NULL → 运行时按字度表近似。 */
    double (*measure_text)(void *ud, const char *utf8, size_t bytes, double size);
    /* 测文三档：返回 1 表示注入成功，out[0]=全 out[1]=半 out[2]=行。
     * NULL/未注入 → 运行时缺省近似值。 */
    int (*text_metrics)(void *ud, double out3[3]);
    /* 图请求（壳装载位图后 post image_ready/image_failed）。 */
    void (*load_image)(void *ud, long handle, const char *source);
    /* 件请求（壳读档后 post file_ready/file_failed；as_text=1 → 文，0 → base64）。 */
    void (*load_file)(void *ud, long handle, const char *source, int as_text);
    /* 服务请（壳执行后 post service_response）。 */
    void (*service)(void *ud, long handle, const char *service, const char *action,
                    const char *path, const char *text, int flag);
    /* 文入焦点/失焦（IME 生命周期；SDL 用位置放候选窗）。NULL/不实现 = 无文入。 */
    void (*set_text_input)(void *ud, int active, int x, int y, int w, int h);
    /* 无事件时等待秒（可 sleeping；测试宿主可立即返回）。NULL = 忙等轮询。 */
    void (*idle)(void *ud, double seconds);
    /* 真 = 图请求／件请求 入装载队列由宿主异步装载（浏览器/SDL 行为）；
       假 = 只登记句柄与命令，不就绪装载（Python GraphicsHost auto_load=False
       测试宿主行为；外部注入的 ready 事件按噪音丢弃）。 */
    int auto_load;
} RuGuiHost;

void ru_graphics_set_host(const RuGuiHost *host);

void ru_graphics_post_close(void);
void ru_graphics_post_resize(int width, int height);
void ru_graphics_post_mouse_down(double x, double y, int button);
void ru_graphics_post_mouse_up(double x, double y, int button);
void ru_graphics_post_mouse_move(double x, double y);
void ru_graphics_post_touch_start(long id, double x, double y);
void ru_graphics_post_touch_move(long id, double x, double y);
void ru_graphics_post_touch_end(long id, double x, double y);
void ru_graphics_post_key_down(const char *key);     /* 不拷贝；立即入队 */
void ru_graphics_post_key_up(const char *key);
void ru_graphics_post_text_key(const char *key);     /* 编辑键：退格/删除/左/右/上/下/家/终/回车/空格/跳格/逃脱 */
void ru_graphics_post_text_char(const char *text);   /* 已合成字符（拷贝） */
void ru_graphics_post_text_paste(const char *text);  /* 剪贴文本（拷贝） */
void ru_graphics_post_comp_start(void);              /* 组开始 */
void ru_graphics_post_comp_update(const char *text, int cursor); /* 组更新（拷贝） */
void ru_graphics_post_comp_end(const char *text);    /* 组结束（拷贝；可空串） */
void ru_graphics_post_image_ready(long handle, int width, int height);
void ru_graphics_post_image_failed(long handle, const char *error); /* 拷贝 */
void ru_graphics_post_file_ready(long handle, const char *text);    /* 拷贝 */
void ru_graphics_post_file_failed(long handle, const char *error);  /* 拷贝 */
void ru_graphics_post_service_response(long handle, int ok,
                                       const char *value, const char *error); /* 拷贝 */

/* 程序 main 内部在模块初始化后自动调用；壳一般无需直接调。 */
int ru_graphics_app_run(void);

#ifdef __cplusplus
}
#endif

#endif /* RULANG_GRAPHICS_ABI_H */
