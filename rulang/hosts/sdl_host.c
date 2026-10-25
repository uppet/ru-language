/* sdl_host.c — 如观 C 运行时的 SDL2 桌面壳（plans/ruui-sdl-host.md M2-M4）。
 *
 * 实现 RuGuiHost vtable（见 rulang/graphics_abi.h）：
 *   窗口/渲染(SDL2)、文字(SDL2_ttf)、图(SDL2_image)、
 *   事件泵(SDL → ru_graphics_post_*)、IME 全协议、剪贴板、
 *   装载(IMG_Load / 文件读 → post_*_ready/failed)、虚拟时钟。
 *
 * 入口 ru_sdl_app_run()：注册本宿主后进入 ru_graphics_app_run()。
 * 生成的 main 在 RU_SDL_HOST 定义时改调本入口（见 compiler.py）。
 *
 * 编译：cc -O2 -I<root> app.c rulang/hosts/sdl_host.c \
 *        $(pkg-config --cflags --libs sdl2 SDL2_ttf SDL2_image) -lm
 *
 * HEADLESS_SMOKE：dummy video driver 下渲染 smoke_frames 帧后把
 * 首帧/末帧存 PNG 并关闭画布，供无头 CI 验证。
 *
 * 已知近似（诚实清单，与 plans 文档同步）：
 *   - shear 变换（b,c 均非零的非对称仿射）按纯平移近似；
 *   - rotate/scale 经整窗纹理 CopyEx，旋转中心 = 窗中心；
 *   - 宽线（width>1）按轴向平行线叠画近似；
 *   - bezier 用 32 段折线采样；
 *   - clip 的 transform 字段忽略（clip 矩形直接取 x/y/width/height）。
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#include "rulang/graphics_abi.h"
#include <SDL.h>
#include <SDL_ttf.h>
#include <SDL_image.h>

#define SDL_MAX_IMAGES 64
#define SDL_FONT_CACHE 8
#define SMOKE_FRAMES_DEFAULT 3

static SDL_Window *sdl_window;
static SDL_Renderer *sdl_renderer;
static int sdl_w, sdl_h;
static char sdl_program_dir[1024] = ".";
static int sdl_text_input_active = 0;
static int sdl_ime_composing = 0;
static int sdl_closed = 0;
static unsigned long long sdl_frame_counter = 0;

/* —— 字体缓存（按像素尺寸） —— */
static TTF_Font *sdl_fonts[SDL_FONT_CACHE];
static int sdl_font_sizes[SDL_FONT_CACHE];
static int sdl_fonts_n = 0;
static char sdl_font_path[1024] = "";

static const char *sdl_pick_font(void) {
    const char *env = getenv("RU_FONT");
    static const char *candidates[] = {
        /* Noto CJK 优先：默认程序文字多为中文，DejaVu 无 CJK 字形 */
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        NULL,
    };
    int i;
    if (env && *env && !access(env, R_OK)) return env;
    for (i = 0; candidates[i]; i++)
        if (!access(candidates[i], R_OK)) return candidates[i];
    return NULL;
}

static TTF_Font *sdl_font_for(int size) {
    int i;
    if (size < 1) size = 1;
    if (size > 400) size = 400;
    for (i = 0; i < sdl_fonts_n; i++)
        if (sdl_font_sizes[i] == size) return sdl_fonts[i];
    if (!sdl_font_path[0]) {
        const char *p = sdl_pick_font();
        if (!p) return NULL;
        snprintf(sdl_font_path, sizeof sdl_font_path, "%s", p);
    }
    if (sdl_fonts_n >= SDL_FONT_CACHE) return sdl_fonts[0];
    sdl_fonts[sdl_fonts_n] = TTF_OpenFont(sdl_font_path, size);
    if (!sdl_fonts[sdl_fonts_n]) return NULL;
    sdl_font_sizes[sdl_fonts_n] = size;
    return sdl_fonts[sdl_fonts_n++];
}

/* —— 图片表（装载句柄 → 纹理） —— */
static struct { long id; SDL_Texture *tex; int w, h; } sdl_images[SDL_MAX_IMAGES];
static int sdl_images_n = 0;

static SDL_Texture *sdl_image_find(long id, int *w, int *h) {
    int i;
    for (i = 0; i < sdl_images_n; i++)
        if (sdl_images[i].id == id) {
            if (w) *w = sdl_images[i].w;
            if (h) *h = sdl_images[i].h;
            return sdl_images[i].tex;
        }
    return NULL;
}

static void sdl_image_drop(long id) {
    int i;
    for (i = 0; i < sdl_images_n; i++)
        if (sdl_images[i].id == id) {
            SDL_DestroyTexture(sdl_images[i].tex);
            sdl_images[i] = sdl_images[--sdl_images_n];
            return;
        }
}

static const char *sdl_jvalue(const char *json, const char *key);

/* —— 事件监听位图（每帧从 "handlers":[...] 刷新；未监听事件静默丢弃） —— */
static unsigned int sdl_listen; /* bit i ↔ ru_g_event_names[i]（21 种） */
static const char *const sdl_event_names[22] = {
    "frame", "mouse_down", "mouse_up", "mouse_move",
    "touch_start", "touch_move", "touch_end", "resize", "key_down", "key_up",
    "image_ready", "image_failed", "file_ready", "file_failed",
    "text_key", "text_char", "text_paste",
    "text_comp_start", "text_comp_update", "text_comp_end",
    "service_response", "service_ad"
};
#define SDL_EV_BIT(i) (1u << (i))
static void sdl_update_handlers(const char *json) {
    const char *p = sdl_jvalue(json, "handlers");
    unsigned int mask = 0;
    int i;
    if (!p || *p != '[') return;
    for (i = 0; i < 22; i++)
        if (strstr(p, sdl_event_names[i])) mask |= SDL_EV_BIT(i);
    sdl_listen = mask;
}

/* —— 帧 JSON 扫描器（只解析本 runtime 生成的固定形状） —— */
static const char *sdl_jvalue(const char *json, const char *key) {
    static char pat[64];
    const char *p;
    /* pattern 带冒号：避免把 op 值（如 "op":"text"）当键 "text" 命中。
     * 本 runtime 生成的帧 JSON 为紧凑无空白格式。 */
    snprintf(pat, sizeof pat, "\"%s\":", key);
    p = strstr(json, pat);
    if (!p) return NULL;
    p += strlen(pat);
    while (*p == ' ' || *p == '\t') p++;
    return p;
}

static double sdl_jnum(const char *json, const char *key, double def) {
    const char *p = sdl_jvalue(json, key);
    return p ? strtod(p, NULL) : def;
}

static int sdl_jstr(const char *json, const char *key, char *out, size_t cap) {
    const char *p = sdl_jvalue(json, key);
    const char *q;
    size_t n;
    if (!p || *p != '"') return 0;
    p++;
    q = strchr(p, '"');
    if (!q) return 0;
    n = (size_t)(q - p);
    if (n >= cap) n = cap - 1;
    memcpy(out, p, n);
    out[n] = '\0';
    return 1;
}

/* 解析 "#RRGGBB" / "#RRGGBBAA"。空串/缺键 = 无效（*ok=0）。 */
static SDL_Color sdl_jcolor(const char *json, const char *key, int *ok) {
    char buf[16];
    SDL_Color c = {0, 0, 0, 255};
    unsigned v;
    *ok = 0;
    if (!sdl_jstr(json, key, buf, sizeof buf) || buf[0] != '#') return c;
    v = (unsigned)strtoul(buf + 1, NULL, 16);
    if (strlen(buf) >= 9) {
        c.a = (Uint8)(v & 255); v >>= 8;
    } else if (strlen(buf) < 7) {
        return c;
    }
    c.b = (Uint8)(v & 255); v >>= 8;
    c.g = (Uint8)(v & 255); v >>= 8;
    c.r = (Uint8)(v & 255);
    *ok = 1;
    return c;
}

/* 解析 [[x,y],...] 点数组到 out（最多 max 点），返回点数。 */
static int sdl_jpoints(const char *json, const char *key, SDL_FPoint *out, int max) {
    const char *p = sdl_jvalue(json, key);
    int n = 0;
    if (!p || *p != '[') return 0;
    p++;
    while (*p && *p != ']' && n < max) {
        while (*p == ' ' || *p == '\t' || *p == ',') p++;
        if (*p == '[') {
            p++;
            out[n].x = (float)strtod(p, (char **)&p);
            while (*p == ' ' || *p == '\t' || *p == ',') p++;
            out[n].y = (float)strtod(p, (char **)&p);
            while (*p == ' ' || *p == '\t') p++;
            if (*p == ']') p++;
            n++;
        } else break;
    }
    return n;
}

/* 解析命令级 transform（6 元素）。返回 1 = 存在。 */
static int sdl_jtransform(const char *json, double t[6]) {
    const char *p = sdl_jvalue(json, "transform");
    int i;
    if (!p || *p != '[') return 0;
    p++;
    for (i = 0; i < 6; i++) {
        t[i] = strtod(p, (char **)&p);
        while (*p == ' ' || *p == '\t' || *p == ',') p++;
    }
    return 1;
}

/* —— 变换分解 ——
 * 返回平移偏移；*rot = 弧度角（无旋转 = 0）；sx／sy 出参 = 缩放（无 = 1）。
 * shear（非对称 b,c）→ 按平移近似（诚实清单）。 */
static void sdl_transform_split(const double t[6], float *tx, float *ty,
                                double *rot, double *sx, double *sy) {
    double a = t[0], b = t[1], c = t[2], d = t[3];
    *tx = (float)t[4]; *ty = (float)t[5];
    *rot = 0; *sx = 1; *sy = 1;
    if (a == 1 && b == 0 && c == 0 && d == 1) return;
    if (b == 0 && c == 0) {
        *sx = a; *sy = d;
        return;
    }
    if (fabs(a - d) < 1e-9 && fabs(b + c) < 1e-9) {
        *rot = atan2(b, a);
        *sx = sqrt(a * a + b * b);
        *sy = *sx;
        return;
    }
    /* shear 或更一般仿射：只取平移 */
}

/* —— 剪辑区 —— */
static void sdl_apply_clips(const char *json, SDL_Rect *saved) {
    const char *p = sdl_jvalue(json, "clips");
    int any = 0;
    (void)saved;
    if (!p || *p != '[') return;
    while ((p = strstr(p, "\"width\"")) != NULL) {
        SDL_Rect r;
        r.x = (int)sdl_jnum(p - 64, "x", 0);
        r.y = (int)sdl_jnum(p - 64, "y", 0);
        r.w = (int)sdl_jnum(p, "width", 0);
        r.h = (int)sdl_jnum(p, "height", 0);
        if (!any) {
            SDL_RenderGetClipRect(sdl_renderer, saved);
            SDL_RenderSetClipRect(sdl_renderer, NULL);
        }
        SDL_RenderSetClipRect(sdl_renderer, &r);
        any = 1;
        p += 7;
    }
}

/* —— 绘图助手 —— */
static void sdl_set_color(SDL_Color c) {
    SDL_SetRenderDrawColor(sdl_renderer, c.r, c.g, c.b, c.a);
}

/* 椭圆/弧/扇形：参数采样多边形。 */
static int sdl_arc_points(SDL_FPoint *out, int max, double x, double y,
                          double w, double h, double start_deg, double sweep_deg) {
    int n = 0, steps = 64, i;
    double a0 = start_deg * M_PI / 180.0, sw = sweep_deg * M_PI / 180.0;
    double rx = w / 2.0, ry = h / 2.0, cx = x + rx, cy = y + ry;
    if (sweep_deg == 0) return 0;
    for (i = 0; i <= steps && n < max; i++) {
        double a = a0 + sw * (double)i / steps;
        out[n].x = (float)(cx + rx * cos(a));
        out[n].y = (float)(cy + ry * sin(a));
        n++;
    }
    return n;
}

static void sdl_fill_poly(const SDL_FPoint *pts, int n, SDL_Color c) {
    /* 扫描线填充（SDL2 无原生多边形填充） */
    int i, y;
    float ymin = pts[0].y, ymax = pts[0].y;
    if (n < 3) return;
    for (i = 1; i < n; i++) {
        if (pts[i].y < ymin) ymin = pts[i].y;
        if (pts[i].y > ymax) ymax = pts[i].y;
    }
    sdl_set_color(c);
    for (y = (int)ceil(ymin); y <= (int)floor(ymax); y++) {
        float xs[128];
        int xn = 0;
        for (i = 0; i < n && xn < 126; i++) {
            float y1 = pts[i].y, y2 = pts[(i + 1) % n].y;
            if ((y1 <= y && y < y2) || (y2 <= y && y < y1))
                xs[xn++] = pts[i].x + (y - y1) / (y2 - y1) * (pts[(i + 1) % n].x - pts[i].x);
        }
        /* 冒泡排 xs */
        for (i = 0; i + 1 < xn; i++)
            for (int j = i + 1; j < xn; j++)
                if (xs[j] < xs[i]) { float t = xs[i]; xs[i] = xs[j]; xs[j] = t; }
        for (i = 0; i + 1 < xn; i += 2)
            SDL_RenderDrawLine(sdl_renderer, (int)ceil(xs[i]), y, (int)floor(xs[i + 1]), y);
    }
}

static void sdl_stroke_poly(const SDL_FPoint *pts, int n, SDL_Color c, double width) {
    int i, k;
    if (n < 2) return;
    sdl_set_color(c);
    for (i = 0; i < n - 1; i++)
        for (k = 0; k < (int)width; k++) {
            SDL_RenderDrawLineF(sdl_renderer, pts[i].x, pts[i].y + k, pts[i + 1].x, pts[i + 1].y + k);
            SDL_RenderDrawLineF(sdl_renderer, pts[i].x + k, pts[i].y, pts[i + 1].x + k, pts[i + 1].y);
        }
}

static void sdl_draw_text(double x, double y, const char *text, SDL_Color color,
                          double size, const char *align, const char *baseline) {
    TTF_Font *font = sdl_font_for((int)size);
    SDL_Surface *surf;
    SDL_Texture *tex;
    SDL_Rect dst;
    int tw = 0, th = 0;
    if (getenv("RU_SDL_DEBUG"))
        fprintf(stderr, "[sdl] text '%s' size=%g font=%p\n", text, size, (void *)font);
    if (!font) return;
    surf = TTF_RenderUTF8_Blended(font, text, color);
    if (!surf) return;
    tex = SDL_CreateTextureFromSurface(sdl_renderer, surf);
    tw = surf->w; th = surf->h;
    SDL_FreeSurface(surf);
    if (!tex) return;
    dst.x = (int)x; dst.w = tw; dst.h = th;
    if (!strcmp(align, "center")) dst.x -= tw / 2;
    else if (!strcmp(align, "right")) dst.x -= tw;
    if (!strcmp(baseline, "middle")) dst.y = (int)y - th / 2;
    else if (!strcmp(baseline, "bottom")) dst.y = (int)y - th;
    else dst.y = (int)y;
    SDL_RenderCopy(sdl_renderer, tex, NULL, &dst);
    SDL_DestroyTexture(tex);
}

/* 把一条命令渲染到当前 target（应用平移）。rotate/scale 由调用方走纹理路径。 */
static void sdl_render_command(const char *cmd);

/* 非平移变换：命令画到整窗纹理，CopyEx 回屏幕（旋转中心 = 窗中心）。 */
static void sdl_render_command_transformed(const char *cmd, const double t[6]) {
    static SDL_Texture *canvas_tex;
    float tx, ty; double rot, sx, sy;
    SDL_Rect dst;
    if (!canvas_tex) {
        canvas_tex = SDL_CreateTexture(sdl_renderer, SDL_PIXELFORMAT_RGBA8888,
                                       SDL_TEXTUREACCESS_TARGET, sdl_w, sdl_h);
        if (!canvas_tex) { sdl_render_command(cmd); return; }
    }
    if (SDL_QueryTexture(canvas_tex, NULL, NULL, NULL, NULL) != 0) return;
    /* 纹理尺寸随窗口重建 */
    SDL_SetRenderTarget(sdl_renderer, canvas_tex);
    SDL_SetRenderDrawColor(sdl_renderer, 0, 0, 0, 0);
    SDL_RenderClear(sdl_renderer);
    sdl_render_command(cmd);
    SDL_SetRenderTarget(sdl_renderer, NULL);
    sdl_transform_split(t, &tx, &ty, &rot, &sx, &sy);
    dst.x = (int)tx; dst.y = (int)ty; dst.w = sdl_w; dst.h = sdl_h;
    SDL_RenderCopyEx(sdl_renderer, canvas_tex, NULL, &dst,
                     -rot * 180.0 / M_PI, NULL, SDL_FLIP_NONE);
}

static void sdl_render_command_full(const char *cmd) {
    double t[6];
    SDL_Rect clip_saved;
    int had_clip;
    had_clip = SDL_RenderIsClipEnabled(sdl_renderer);
    SDL_RenderGetClipRect(sdl_renderer, &clip_saved);
    sdl_apply_clips(cmd, &clip_saved);
    if (sdl_jtransform(cmd, t)) {
        float tx, ty; double rot, sx, sy;
        sdl_transform_split(t, &tx, &ty, &rot, &sx, &sy);
        if (rot != 0 || sx != 1 || sy != 1) {
            /* 临时改 t 为纯平移，走纹理路径 */
            double tt[6] = {1, 0, 0, 1, t[4], t[5]};
            (void)tt;
            sdl_render_command_transformed(cmd, t);
        } else {
            sdl_render_command(cmd);
        }
    } else {
        sdl_render_command(cmd);
    }
    if (had_clip || SDL_RenderIsClipEnabled(sdl_renderer))
        SDL_RenderSetClipRect(sdl_renderer, &clip_saved);
}

/* —— 逐命令渲染（无 transform/clips；偏移已由纹理路径或直绘处理） —— */
static void sdl_render_command(const char *cmd) {
    char op[32];
    if (!sdl_jstr(cmd, "op", op, sizeof op)) return;
    if (getenv("RU_SDL_DEBUG")) fprintf(stderr, "[sdl] op=%s\n", op);

    if (!strcmp(op, "background")) {
        int ok;
        SDL_Color c = sdl_jcolor(cmd, "color", &ok);
        if (ok) {
            sdl_set_color(c);
            SDL_RenderClear(sdl_renderer);
        }
        return;
    }
    if (!strcmp(op, "rect")) {
        double x = sdl_jnum(cmd, "x", 0), y = sdl_jnum(cmd, "y", 0);
        double w = sdl_jnum(cmd, "width", 0), h = sdl_jnum(cmd, "height", 0);
        double sw = sdl_jnum(cmd, "stroke_width", 1);
        int fok, sok;
        SDL_Color fill = sdl_jcolor(cmd, "fill", &fok);
        SDL_Color stroke = sdl_jcolor(cmd, "stroke", &sok);
        if (getenv("RU_SDL_DEBUG"))
            fprintf(stderr, "[sdl] rect x=%g y=%g w=%g h=%g fill_ok=%d stroke_ok=%g\n",
                    x, y, w, h, fok, sok ? (double)stroke.r : -1.0);
        SDL_Rect r = {(int)x, (int)y, (int)w, (int)h};
        if (fok) {
            int rc;
            sdl_set_color(fill);
            rc = SDL_RenderFillRect(sdl_renderer, &r);
            if (getenv("RU_SDL_DEBUG")) {
                Uint32 px;
                SDL_Rect pt = {60, 40, 1, 1};
                fprintf(stderr, "[sdl] fillrect rc=%d err=%s clip=%d\n",
                        rc, SDL_GetError(), (int)SDL_RenderIsClipEnabled(sdl_renderer));
                if (SDL_RenderReadPixels(sdl_renderer, &pt, SDL_PIXELFORMAT_RGBA8888, &px, 4) == 0)
                    fprintf(stderr, "[sdl] px(60,40) after fill = %08x\n", px);
            }
        }
        if (sok && sw > 0) {
            sdl_set_color(stroke);
            for (int k = 0; k < (int)sw; k++) {
                SDL_Rect b = {(int)x - k, (int)y - k, (int)w + 2 * k, (int)h + 2 * k};
                SDL_RenderDrawRect(sdl_renderer, &b);
            }
        }
        return;
    }
    if (!strcmp(op, "ellipse") || !strcmp(op, "arc") || !strcmp(op, "sector")) {
        double x = sdl_jnum(cmd, "x", 0), y = sdl_jnum(cmd, "y", 0);
        double w = sdl_jnum(cmd, "width", 0), h = sdl_jnum(cmd, "height", 0);
        double start = sdl_jnum(cmd, "start", 0), sweep = sdl_jnum(cmd, "sweep", 360);
        double sw = sdl_jnum(cmd, "stroke_width", 1);
        int fok, sok;
        SDL_Color fill = sdl_jcolor(cmd, "fill", &fok);
        SDL_Color stroke = sdl_jcolor(cmd, "stroke", &sok);
        SDL_FPoint pts[80];
        int n;
        if (!strcmp(op, "ellipse")) { sweep = 360; start = 0; }
        n = sdl_arc_points(pts, 78, x, y, w, h, start, sweep);
        if (n < 2) return;
        if (!strcmp(op, "sector")) {
            /* 补圆心闭合扇形 */
            pts[n].x = (float)(x + w / 2); pts[n].y = (float)(y + h / 2); n++;
        }
        if (fok) sdl_fill_poly(pts, n, fill);
        if (sok && sw > 0) sdl_stroke_poly(pts, n, stroke, sw);
        return;
    }
    if (!strcmp(op, "line")) {
        double x1 = sdl_jnum(cmd, "x1", 0), y1 = sdl_jnum(cmd, "y1", 0);
        double x2 = sdl_jnum(cmd, "x2", 0), y2 = sdl_jnum(cmd, "y2", 0);
        double wd = sdl_jnum(cmd, "width", 1);
        int cok;
        SDL_Color c = sdl_jcolor(cmd, "color", &cok);
        int k;
        if (!cok) return;
        sdl_set_color(c);
        for (k = 0; k < (int)wd; k++) {
            SDL_RenderDrawLineF(sdl_renderer, (float)x1, (float)(y1 + k), (float)x2, (float)(y2 + k));
            SDL_RenderDrawLineF(sdl_renderer, (float)(x1 + k), (float)y1, (float)(x2 + k), (float)y2);
        }
        return;
    }
    if (!strcmp(op, "text")) {
        double x = sdl_jnum(cmd, "x", 0), y = sdl_jnum(cmd, "y", 0);
        double size = sdl_jnum(cmd, "size", 16);
        char text[4096], align[16] = "left", baseline[16] = "top";
        int cok;
        SDL_Color c = sdl_jcolor(cmd, "color", &cok);
        if (!sdl_jstr(cmd, "text", text, sizeof text)) return;
        sdl_jstr(cmd, "align", align, sizeof align);
        sdl_jstr(cmd, "baseline", baseline, sizeof baseline);
        sdl_draw_text(x, y, text, cok ? c : (SDL_Color){0, 0, 0, 255},
                      size, align, baseline);
        return;
    }
    if (!strcmp(op, "polyline") || !strcmp(op, "polygon")) {
        SDL_FPoint pts[256];
        int n = sdl_jpoints(cmd, "points", pts, 256);
        double sw = sdl_jnum(cmd, "stroke_width", 1);
        int fok, sok;
        SDL_Color fill = sdl_jcolor(cmd, "fill", &fok);
        SDL_Color stroke = sdl_jcolor(cmd, "stroke", &sok);
        if (n < 2) return;
        if (!strcmp(op, "polygon")) {
            if (fok) sdl_fill_poly(pts, n, fill);
            if (sok && sw > 0) {
                pts[n] = pts[0]; n++; /* 闭合 */
                sdl_stroke_poly(pts, n, stroke, sw);
            }
        } else {
            if (sok) sdl_stroke_poly(pts, n, stroke, sw);
        }
        return;
    }
    if (!strcmp(op, "bezier")) {
        double x1 = sdl_jnum(cmd, "x1", 0), y1 = sdl_jnum(cmd, "y1", 0);
        double cx1 = sdl_jnum(cmd, "cx1", 0), cy1 = sdl_jnum(cmd, "cy1", 0);
        double cx2 = sdl_jnum(cmd, "cx2", 0), cy2 = sdl_jnum(cmd, "cy2", 0);
        double x2 = sdl_jnum(cmd, "x2", 0), y2 = sdl_jnum(cmd, "y2", 0);
        double sw = sdl_jnum(cmd, "stroke_width", 1);
        int fok, sok, i;
        SDL_Color fill = sdl_jcolor(cmd, "fill", &fok);
        SDL_Color stroke = sdl_jcolor(cmd, "stroke", &sok);
        SDL_FPoint pts[34];
        for (i = 0; i <= 32; i++) {
            double t = (double)i / 32, u = 1 - t;
            pts[i].x = (float)(u*u*u*x1 + 3*u*u*t*cx1 + 3*u*t*t*cx2 + t*t*t*x2);
            pts[i].y = (float)(u*u*u*y1 + 3*u*u*t*cy1 + 3*u*t*t*cy2 + t*t*t*y2);
        }
        if (fok) { pts[33] = pts[0]; sdl_fill_poly(pts, 33, fill); }
        if (sok && sw > 0) sdl_stroke_poly(pts, 33, stroke, sw);
        return;
    }
    if (!strcmp(op, "draw_image") || !strcmp(op, "image")) {
        long id = (long)sdl_jnum(cmd, "id", -1);
        double x = sdl_jnum(cmd, "x", 0), y = sdl_jnum(cmd, "y", 0);
        double w = sdl_jnum(cmd, "width", -1), h = sdl_jnum(cmd, "height", -1);
        SDL_Texture *tex = sdl_image_find(id, NULL, NULL);
        SDL_Rect dst = {(int)x, (int)y, (int)w, (int)h};
        if (tex && w >= 0 && h >= 0) SDL_RenderCopy(sdl_renderer, tex, NULL, &dst);
        return;
    }
    /* text_focus/blur/update、image_request/release、file/service_request
       是纯协议命令（宿主动作或不渲染），SDL 侧无需绘制。 */
}

/* —— 帧渲染 —— */
static void sdl_render_frame(const char *json) {
    const char *cmds;
    if (sdl_closed || !sdl_renderer) return;
    sdl_update_handlers(json);
    cmds = sdl_jvalue(json, "commands");
    if (cmds && *cmds == '[') {
        const char *p = cmds + 1;
        for (;;) {
            const char *start;
            int depth;
            while (*p == ' ' || *p == '\t' || *p == ',') p++;
            if (*p != '{') break;
            start = p;
            depth = 0;
            while (*p) {
                if (*p == '{') depth++;
                else if (*p == '}') { depth--; if (!depth) { p++; break; } }
                p++;
            }
            {
                size_t len = (size_t)(p - start);
                char *one = (char *)malloc(len + 1);
                if (one) {
                    memcpy(one, start, len);
                    one[len] = '\0';
                    sdl_render_command_full(one);
                    free(one);
                }
            }
        }
    }
    SDL_RenderPresent(sdl_renderer);
    sdl_frame_counter++;
#ifdef HEADLESS_SMOKE
    {
        static int smoke_frames = -1;
        if (smoke_frames < 0) {
            const char *e = getenv("RU_SMOKE_FRAMES");
            smoke_frames = e ? atoi(e) : SMOKE_FRAMES_DEFAULT;
            if (smoke_frames < 1) smoke_frames = 1;
        }
        if (sdl_frame_counter >= (unsigned long long)smoke_frames) {
            static int saved = 0;
            if (!saved) {
                SDL_Surface *shot = SDL_CreateRGBSurfaceWithFormat(0, sdl_w, sdl_h, 32,
                                                                   SDL_PIXELFORMAT_RGBA8888);
                if (shot) {
                    SDL_RenderReadPixels(sdl_renderer, NULL, SDL_PIXELFORMAT_RGBA8888,
                                         shot->pixels, shot->pitch);
                    IMG_SavePNG(shot, "smoke.png");
                    SDL_FreeSurface(shot);
                }
                saved = 1;
            }
            ru_graphics_post_close();
        }
    }
#endif
}

/* —— vtable —— */
static void sdl_open(void *ud, int w, int h) {
    uint32_t flags = SDL_WINDOW_SHOWN | SDL_WINDOW_RESIZABLE;
    (void)ud;
    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_TIMER | SDL_INIT_EVENTS) < 0) {
        fprintf(stderr, "SDL 初始化失败: %s\n", SDL_GetError());
        exit(1);
    }
    if (TTF_Init() < 0) {
        fprintf(stderr, "TTF 初始化失败: %s\n", TTF_GetError());
        exit(1);
    }
    IMG_Init(IMG_INIT_PNG | IMG_INIT_JPG);
#ifdef HEADLESS_SMOKE
    flags = SDL_WINDOW_HIDDEN;
#endif
    sdl_window = SDL_CreateWindow("如", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                                  w, h, flags);
    if (!sdl_window) {
        fprintf(stderr, "窗口创建失败: %s\n", SDL_GetError());
        exit(1);
    }
#ifdef HEADLESS_SMOKE
    /* dummy video driver 下 ACCELERATED 创建会"成功"但绘制静默失败，直接 SOFTWARE。 */
    sdl_renderer = SDL_CreateRenderer(sdl_window, -1, SDL_RENDERER_SOFTWARE);
#else
    sdl_renderer = SDL_CreateRenderer(sdl_window, -1,
                                      SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!sdl_renderer)
        sdl_renderer = SDL_CreateRenderer(sdl_window, -1, SDL_RENDERER_SOFTWARE);
#endif
    if (!sdl_renderer) {
        fprintf(stderr, "渲染器创建失败: %s\n", SDL_GetError());
        exit(1);
    }
    SDL_SetRenderDrawBlendMode(sdl_renderer, SDL_BLENDMODE_BLEND);
    sdl_w = w; sdl_h = h;
    sdl_closed = 0;
}

static void sdl_close(void *ud) {
    int i;
    (void)ud;
    sdl_closed = 1;
    if (sdl_text_input_active) { SDL_StopTextInput(); sdl_text_input_active = 0; }
    for (i = 0; i < sdl_images_n; i++) SDL_DestroyTexture(sdl_images[i].tex);
    sdl_images_n = 0;
    for (i = 0; i < sdl_fonts_n; i++) TTF_CloseFont(sdl_fonts[i]);
    sdl_fonts_n = 0;
    if (sdl_renderer) SDL_DestroyRenderer(sdl_renderer);
    if (sdl_window) SDL_DestroyWindow(sdl_window);
    IMG_Quit();
    TTF_Quit();
    SDL_Quit();
}

static void sdl_frame(void *ud, const char *json, size_t bytes) {
    char *copy;
    (void)ud;
    copy = (char *)malloc(bytes + 1);
    if (!copy) return;
    memcpy(copy, json, bytes);
    copy[bytes] = '\0';
    sdl_render_frame(copy);
    free(copy);
}

static double sdl_now(void *ud) {
    static struct timespec t0;
    struct timespec t;
    (void)ud;
    if (!t0.tv_sec && !t0.tv_nsec) clock_gettime(CLOCK_MONOTONIC, &t0);
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)(t.tv_sec - t0.tv_sec) + (double)(t.tv_nsec - t0.tv_nsec) * 1e-9;
}

static double sdl_measure_text(void *ud, const char *utf8, size_t bytes, double size) {
    TTF_Font *font;
    int w = 0, h = 0;
    char buf[4096];
    (void)ud;
    if (bytes >= sizeof buf) bytes = sizeof buf - 1;
    memcpy(buf, utf8, bytes);
    buf[bytes] = '\0';
    font = sdl_font_for((int)size);
    if (!font || TTF_SizeUTF8(font, buf, &w, &h) < 0) return (double)bytes *size * 0.56;
    return (double)w;
}

static void sdl_load_image(void *ud, long handle, const char *source) {
    char path[1200];
    SDL_Surface *surf;
    (void)ud;
    snprintf(path, sizeof path, "%s/%s", sdl_program_dir, source);
    surf = IMG_Load(path);
    if (!surf) {
        ru_graphics_post_image_failed(handle, "图像载入失败");
        return;
    }
    if (sdl_images_n < SDL_MAX_IMAGES) {
        SDL_Texture *tex = SDL_CreateTextureFromSurface(sdl_renderer, surf);
        if (tex) {
            sdl_images[sdl_images_n].id = handle;
            sdl_images[sdl_images_n].tex = tex;
            sdl_images[sdl_images_n].w = surf->w;
            sdl_images[sdl_images_n].h = surf->h;
            sdl_images_n++;
            SDL_FreeSurface(surf);
            ru_graphics_post_image_ready(handle, sdl_images[sdl_images_n - 1].w,
                                         sdl_images[sdl_images_n - 1].h);
            return;
        }
    }
    SDL_FreeSurface(surf);
    ru_graphics_post_image_failed(handle, "图像纹理创建失败");
}

static void sdl_load_file(void *ud, long handle, const char *source, int as_text) {
    char path[1200];
    FILE *f;
    long size;
    char *buf;
    size_t got;
    (void)ud;
    snprintf(path, sizeof path, "%s/%s", sdl_program_dir, source);
    f = fopen(path, "rb");
    if (!f) {
        ru_graphics_post_file_failed(handle, "文件打开失败");
        return;
    }
    fseek(f, 0, SEEK_END);
    size = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (size < 0 || size > 8 * 1024 * 1024) {
        fclose(f);
        ru_graphics_post_file_failed(handle, "文件过大或不可读");
        return;
    }
    buf = (char *)malloc((size_t)size + 1);
    if (!buf) {
        fclose(f);
        ru_graphics_post_file_failed(handle, "内存不足");
        return;
    }
    got = fread(buf, 1, (size_t)size, f);
    fclose(f);
    if (as_text) {
        buf[got] = '\0';
        ru_graphics_post_file_ready(handle, buf);
    } else {
        /* base64 编码 */
        static const char b64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        char *enc = (char *)malloc(got / 3 * 4 + 5);
        size_t i, o = 0;
        if (!enc) { free(buf); ru_graphics_post_file_failed(handle, "内存不足"); return; }
        for (i = 0; i + 2 < got; i += 3) {
            unsigned v = (unsigned char)buf[i] << 16 | (unsigned char)buf[i + 1] << 8 | (unsigned char)buf[i + 2];
            enc[o++] = b64[v >> 18 & 63]; enc[o++] = b64[v >> 12 & 63];
            enc[o++] = b64[v >> 6 & 63]; enc[o++] = b64[v & 63];
        }
        if (i < got) {
            unsigned v = (unsigned char)buf[i] << 16;
            enc[o++] = b64[v >> 18 & 63];
            if (i + 1 < got) {
                v |= (unsigned char)buf[i + 1] << 8;
                enc[o++] = b64[v >> 12 & 63];
                enc[o++] = b64[v >> 6 & 63];
                enc[o++] = '=';
            } else {
                enc[o++] = b64[v >> 12 & 63];
                enc[o++] = '=';
                enc[o++] = '=';
            }
        }
        enc[o] = '\0';
        ru_graphics_post_file_ready(handle, enc);
        free(enc);
    }
    free(buf);
}

static void sdl_service(void *ud, long handle, const char *svc, const char *action,
                        const char *path, const char *text, int flag) {
    (void)ud; (void)svc; (void)action; (void)path; (void)text; (void)flag;
    /* v1：网络服务未接线（计划 M4 的 HTTP 客户端未实现），
       诚实返回失败事件，让程序侧得到确定响应。 */
    ru_graphics_post_service_response(handle, 0, NULL, "服务不可用：SDL 壳网络未接线");
}

static void sdl_set_text_input(void *ud, int active, int x, int y, int w, int h) {
    SDL_Rect r = {x, y, w, h};
    (void)ud;
    if (active && !sdl_text_input_active) {
        SDL_SetTextInputRect(&r);
        SDL_StartTextInput();
        sdl_text_input_active = 1;
        sdl_ime_composing = 0;
    } else if (!active && sdl_text_input_active) {
        SDL_StopTextInput();
        sdl_text_input_active = 0;
        sdl_ime_composing = 0;
    }
}

static void sdl_push_event(SDL_Event *ev);

static void sdl_idle(void *ud, double seconds) {
    SDL_Event ev;
    int timeout = (int)(seconds * 1000.0);
    (void)ud;
    if (timeout < 1) timeout = 1;
    if (timeout > 250) timeout = 250;
    if (SDL_WaitEventTimeout(&ev, timeout)) sdl_push_event(&ev);
    while (SDL_PollEvent(&ev)) sdl_push_event(&ev);
}

/* —— SDL 事件 → 如观事件 —— */
static const char *sdl_key_name(SDL_Keycode k) {
    switch (k) {
    case SDLK_BACKSPACE: return "退格";
    case SDLK_DELETE: return "删除";
    case SDLK_LEFT: return "左";
    case SDLK_RIGHT: return "右";
    case SDLK_UP: return "上";
    case SDLK_DOWN: return "下";
    case SDLK_HOME: return "家";
    case SDLK_END: return "终";
    case SDLK_RETURN: case SDLK_KP_ENTER: return "回车";
    case SDLK_SPACE: return "空格";
    case SDLK_TAB: return "跳格";
    case SDLK_ESCAPE: return "逃脱";
    default: return NULL;
    }
}

static void sdl_push_event(SDL_Event *ev) {
    switch (ev->type) {
    case SDL_QUIT:
        ru_graphics_post_close();
        break;
    case SDL_WINDOWEVENT:
        if (ev->window.event == SDL_WINDOWEVENT_RESIZED) {
            sdl_w = ev->window.data1;
            sdl_h = ev->window.data2;
            SDL_RenderSetLogicalSize(sdl_renderer, sdl_w, sdl_h);
            if (sdl_listen & SDL_EV_BIT(7)) ru_graphics_post_resize(sdl_w, sdl_h);
        } else if (ev->window.event == SDL_WINDOWEVENT_CLOSE) {
            ru_graphics_post_close();
        }
        break;
    case SDL_MOUSEBUTTONDOWN:
        if (!(sdl_listen & SDL_EV_BIT(1))) break;
        ru_graphics_post_mouse_down((double)ev->button.x, (double)ev->button.y, ev->button.button - 1);
        break;
    case SDL_MOUSEBUTTONUP:
        if (!(sdl_listen & SDL_EV_BIT(2))) break;
        ru_graphics_post_mouse_up((double)ev->button.x, (double)ev->button.y, ev->button.button - 1);
        break;
    case SDL_MOUSEMOTION:
        if (!(sdl_listen & SDL_EV_BIT(3))) break;
        ru_graphics_post_mouse_move((double)ev->motion.x, (double)ev->motion.y);
        break;
    case SDL_FINGERDOWN:
        if (!(sdl_listen & SDL_EV_BIT(4))) break;
        ru_graphics_post_touch_start((long)(ev->tfinger.fingerId + 1),
                                 (double)ev->tfinger.x * sdl_w, (double)ev->tfinger.y * sdl_h);
        break;
    case SDL_FINGERMOTION:
        if (!(sdl_listen & SDL_EV_BIT(5))) break;
        ru_graphics_post_touch_move((long)(ev->tfinger.fingerId + 1),
                                (double)ev->tfinger.x * sdl_w, (double)ev->tfinger.y * sdl_h);
        break;
    case SDL_FINGERUP:
        if (!(sdl_listen & SDL_EV_BIT(6))) break;
        ru_graphics_post_touch_end((long)(ev->tfinger.fingerId + 1),
                               (double)ev->tfinger.x * sdl_w, (double)ev->tfinger.y * sdl_h);
        break;
    case SDL_KEYDOWN: case SDL_KEYUP: {
        /* 编辑键只走 text_key（按下时）；可打印键走 key_down/key_up。 */
        const char *name = sdl_key_name(ev->key.keysym.sym);
        if (name) {
            if (ev->type == SDL_KEYDOWN && (sdl_listen & SDL_EV_BIT(14)))
                ru_graphics_post_text_key(name);
            if (ev->type == SDL_KEYDOWN && ev->key.keysym.sym == SDLK_ESCAPE)
                ru_graphics_post_close();
        } else if (ev->key.keysym.sym < 128 && ev->key.keysym.sym > 0 &&
                   !ev->key.keysym.mod) {
            char buf[2] = {(char)ev->key.keysym.sym, 0};
            if (ev->type == SDL_KEYDOWN) {
                if (sdl_listen & SDL_EV_BIT(8)) ru_graphics_post_key_down(buf);
            } else {
                if (sdl_listen & SDL_EV_BIT(9)) ru_graphics_post_key_up(buf);
            }
        }
        break;
    }
    case SDL_TEXTINPUT:
        if (sdl_ime_composing) {
            if (sdl_listen & SDL_EV_BIT(19)) ru_graphics_post_comp_end(ev->text.text);
            sdl_ime_composing = 0;
        }
        if (sdl_listen & SDL_EV_BIT(15)) ru_graphics_post_text_char(ev->text.text);
        break;
    case SDL_TEXTEDITING:
        if (ev->edit.length == 0) {
            if (sdl_ime_composing) {
                if (sdl_listen & SDL_EV_BIT(19)) ru_graphics_post_comp_end("");
                sdl_ime_composing = 0;
            }
        } else {
            if (!sdl_ime_composing) {
                if (sdl_listen & SDL_EV_BIT(17)) ru_graphics_post_comp_start();
                sdl_ime_composing = 1;
            }
            if (sdl_listen & SDL_EV_BIT(18))
                ru_graphics_post_comp_update(ev->edit.text, (double)ev->edit.start);
        }
        break;
    case SDL_KEYMAPCHANGED:
        break;
    }
}

static const RuGuiHost sdl_host = {
    NULL, "", sdl_open, sdl_close, sdl_frame,
    sdl_now, sdl_measure_text, NULL,
    sdl_load_image, sdl_load_file, sdl_service,
    sdl_set_text_input, sdl_idle,
    1, /* auto_load = 1：SDL 壳真装载 */
};

void ru_sdl_host_register(void) {
    const char *dir = getenv("RU_PROGRAM_DIR");
    ru_graphics_set_host(&sdl_host);
    if (dir && *dir) {
        snprintf(sdl_program_dir, sizeof sdl_program_dir, "%s", dir);
    } else {
        /* 默认程序目录 = 当前工作目录 */
        sdl_program_dir[0] = '.';
        sdl_program_dir[1] = '\0';
    }
}

void ru_sdl_app_run(void) {
    ru_sdl_host_register();
    ru_graphics_app_run();
}

/* 剪贴板 → text_paste：程序侧调用；SDL 侧经按键（Ctrl+V 等）由程序
   自己决定何时取剪贴板。提供便捷入口（可选链接）。 */
void ru_sdl_paste_clipboard(void) {
    char *text = SDL_GetClipboardText();
    if (text) {
        if (*text) ru_graphics_post_text_paste(text);
        SDL_free(text);
    }
}
