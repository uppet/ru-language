/* sdl_waveform.h — 如声·波形图：wav/mp3/ogg 解码 → 峰值包络 → BMP。
 *
 * 单头文件实现（仅允许被一个编译单元包含：sdl_host.c 或单测）。
 * 路径一律经 SDL_RWops（Windows UTF-8 安全）；解码器：
 *   .wav → SDL_LoadWAV（格式不符时 SDL_AudioCVT 转 S16）
 *   .mp3 → minimp3_ex（rulang/thirdparty/auddec/minimp3_ex.h）
 *   .ogg → stb_vorbis（rulang/thirdparty/auddec/stb_vorbis.c）
 *
 * 包络：把整轨 PCM 帧映射到 width 个列，每列记 |峰值|；渲染时以中线
 * 对称画条（foobar2000 waveform seekbar 式）。BMP 由 SDL_SaveBMP 写出，
 * 覆盖写：同路径重复调用以最新解码为准（缓存策略归调用方）。
 */
#ifndef RULANG_SDL_WAVEFORM_H
#define RULANG_SDL_WAVEFORM_H

#include <SDL.h>

#include <stdlib.h>
#include <string.h>

#if defined(__GNUC__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wunused-variable"
#pragma GCC diagnostic ignored "-Wsign-compare"
#pragma GCC diagnostic ignored "-Wtype-limits"
#pragma GCC diagnostic ignored "-Wunused-but-set-variable"
#endif

#define MINIMP3_IMPLEMENTATION
#include "../thirdparty/auddec/minimp3_ex.h"

/* minimp3 与 stb_vorbis 同编译单元有同名 static get_bits，
 * minimp3 先解析不受影响，宏只改写随后编译的 stb 侧。 */
#define get_bits sdl_wf_stb_get_bits
#define STB_VORBIS_IMPLEMENTATION
#include "../thirdparty/auddec/stb_vorbis.c"
#undef get_bits

#if defined(__GNUC__)
#pragma GCC diagnostic pop
#endif

/* 单轨最大解码体量（256MB 内存上限，超出诚实失败）。 */
#define SDL_WF_MAX_BYTES (256ll * 1024 * 1024)

/* 包络累加器：total/done 以单声道帧计（与声道数无关）。 */
typedef struct {
    int cols;
    long long total;
    long long done;
    short *peak; /* 每列 |峰值|，0..32767 */
} SdlWfEnv;

static int sdl_wf_env_init(SdlWfEnv *env, int cols, long long total) {
    if (cols <= 0 || total <= 0)
        return 0;
    env->cols = cols;
    env->total = total;
    env->done = 0;
    env->peak = (short *)calloc((size_t)cols, sizeof(short));
    return env->peak != NULL;
}

static void sdl_wf_env_free(SdlWfEnv *env) {
    free(env->peak);
    env->peak = NULL;
}

/* pcm 为 S16 交错样本。逐帧落列（列界单调推进，无需二分）。 */
static void sdl_wf_env_feed(SdlWfEnv *env, const short *pcm, long long frames, int channels) {
    long long i;
    int c;
    for (i = 0; i < frames; i++) {
        long long col = (env->done * env->cols) / env->total;
        int peak = 0;
        if (col >= env->cols)
            col = env->cols - 1;
        for (c = 0; c < channels; c++) {
            int v = pcm[i * channels + c];
            if (v < 0)
                v = -v;
            if (v > peak)
                peak = v;
        }
        if (peak > env->peak[col])
            env->peak[col] = (short)peak;
        env->done++;
    }
}

static int sdl_wf_render(const SdlWfEnv *env, const char *out_path, int width, int height) {
    SDL_Surface *surface = SDL_CreateRGBSurfaceWithFormat(0, width, height, 32, SDL_PIXELFORMAT_RGBA32);
    Uint32 bg, fg;
    SDL_Rect rect;
    int x, mid;
    int rc;
    if (!surface)
        return 0;
    bg = SDL_MapRGB(surface->format, 24, 26, 32);
    fg = SDL_MapRGB(surface->format, 94, 196, 246);
    SDL_FillRect(surface, NULL, bg);
    mid = height / 2;
    for (x = 0; x < width && x < env->cols; x++) {
        int half;
        if (env->peak[x] <= 0)
            continue;
        half = (int)env->peak[x] * mid / 32768;
        if (half < 1)
            half = 1;
        if (half > mid)
            half = mid;
        rect.x = (Sint16)x;
        rect.y = (Sint16)(mid - half);
        rect.w = 1;
        rect.h = (Uint16)(half * 2);
        SDL_FillRect(surface, &rect, fg);
    }
    rc = SDL_SaveBMP(surface, out_path) == 0;
    SDL_FreeSurface(surface);
    return rc;
}

/* 整文件读入内存（SDL_RWops，UTF-8 安全）；NULL 失败。 */
static unsigned char *sdl_wf_slurp(const char *path, size_t *size_out) {
    SDL_RWops *rw = SDL_RWFromFile(path, "rb");
    Sint64 size;
    unsigned char *buf;
    size_t got;
    if (!rw)
        return NULL;
    size = SDL_RWsize(rw);
    if (size <= 0 || size > SDL_WF_MAX_BYTES) {
        SDL_RWclose(rw);
        return NULL;
    }
    buf = (unsigned char *)malloc((size_t)size);
    if (!buf) {
        SDL_RWclose(rw);
        return NULL;
    }
    got = SDL_RWread(rw, buf, 1, (size_t)size);
    SDL_RWclose(rw);
    if (got != (size_t)size) {
        free(buf);
        return NULL;
    }
    *size_out = (size_t)size;
    return buf;
}

/* ---- wav ---- */

static int sdl_wf_from_wav(const char *path, SdlWfEnv *env) {
    SDL_RWops *rw = SDL_RWFromFile(path, "rb");
    SDL_AudioSpec spec;
    Uint8 *buf = NULL;
    Uint32 len = 0;
    long long frames;
    int bytes_per_frame;
    int ok = 0;
    if (!rw)
        return 0;
    if (SDL_LoadWAV_RW(rw, 1, &spec, &buf, &len) == NULL)
        return 0;
    bytes_per_frame = (int)SDL_AUDIO_BITSIZE(spec.format) / 8 * spec.channels;
    if (bytes_per_frame <= 0)
        goto out;
    if (spec.format != AUDIO_S16SYS) {
        SDL_AudioCVT cvt;
        if (SDL_BuildAudioCVT(&cvt, spec.format, spec.channels, spec.freq,
                              AUDIO_S16SYS, spec.channels, spec.freq) < 0)
            goto out;
        cvt.len = (int)len;
        cvt.buf = (Uint8 *)malloc((size_t)cvt.len * cvt.len_mult);
        if (!cvt.buf)
            goto out;
        memcpy(cvt.buf, buf, len);
        if (SDL_ConvertAudio(&cvt) != 0) {
            free(cvt.buf);
            goto out;
        }
        SDL_FreeWAV(buf);
        buf = cvt.buf;
        len = (Uint32)cvt.len_cvt;
    }
    frames = (long long)len / bytes_per_frame;
    if (sdl_wf_env_init(env, env->cols, frames))
        sdl_wf_env_feed(env, (const short *)buf, frames, spec.channels);
    else
        goto out;
    ok = env->done > 0;
out:
    if (buf)
        SDL_FreeWAV(buf);
    return ok;
}

/* ---- mp3（minimp3_ex，内存缓冲整轨解码） ---- */

static int sdl_wf_from_mp3_buf(const unsigned char *buf, size_t size, SdlWfEnv *env) {
    mp3dec_t dec;
    mp3dec_file_info_t info;
    long long frames;
    memset(&info, 0, sizeof(info));
    if (mp3dec_load_buf(&dec, buf, size, &info, NULL, NULL) != 0)
        return 0;
    if (info.samples <= 0 || info.channels <= 0) {
        free(info.buffer);
        return 0;
    }
    frames = (long long)info.samples / info.channels;
    if (frames > 0 && sdl_wf_env_init(env, env->cols, frames))
        sdl_wf_env_feed(env, info.buffer, frames, info.channels);
    free(info.buffer);
    return env->done > 0;
}

/* ---- ogg（stb_vorbis，内存缓冲） ---- */

static int sdl_wf_from_ogg_buf(const unsigned char *buf, size_t size, SdlWfEnv *env) {
    stb_vorbis *v;
    int err = 0;
    stb_vorbis_info info;
    long long total;
    short *pcm;
    int channels;
    v = stb_vorbis_open_memory(buf, (int)size, &err, NULL);
    if (!v)
        return 0;
    info = stb_vorbis_get_info(v);
    channels = info.channels;
    total = (long long)stb_vorbis_stream_length_in_samples(v);
    if (channels <= 0 || total <= 0) {
        stb_vorbis_close(v);
        return 0;
    }
    if (!sdl_wf_env_init(env, env->cols, total)) {
        stb_vorbis_close(v);
        return 0;
    }
    pcm = (short *)malloc(sizeof(short) * 4096 * (size_t)channels);
    if (!pcm) {
        stb_vorbis_close(v);
        return 0;
    }
    for (;;) {
        int got = stb_vorbis_get_samples_short_interleaved(v, channels, pcm, 4096 * channels);
        if (got <= 0)
            break;
        sdl_wf_env_feed(env, pcm, got, channels);
    }
    free(pcm);
    stb_vorbis_close(v);
    return env->done > 0;
}

/* 入口：按扩展名分派解码，渲染并写 BMP。返回 1 成功 / 0 失败。 */
static int sdl_waveform_bmp(const char *path, const char *out_path, int width, int height) {
    SdlWfEnv env;
    const char *dot;
    int ok = 0;
    if (!path || !out_path || width < 16 || height < 16 || width > 8192 || height > 8192)
        return 0;
    memset(&env, 0, sizeof(env));
    env.cols = width;
    dot = strrchr(path, '.');
    if (!dot)
        return 0;
    if (SDL_strcasecmp(dot, ".wav") == 0) {
        ok = sdl_wf_from_wav(path, &env);
    } else if (SDL_strcasecmp(dot, ".mp3") == 0) {
        size_t size = 0;
        unsigned char *buf = sdl_wf_slurp(path, &size);
        if (buf) {
            ok = sdl_wf_from_mp3_buf(buf, size, &env);
            free(buf);
        }
    } else if (SDL_strcasecmp(dot, ".ogg") == 0 || SDL_strcasecmp(dot, ".oga") == 0) {
        size_t size = 0;
        unsigned char *buf = sdl_wf_slurp(path, &size);
        if (buf) {
            ok = sdl_wf_from_ogg_buf(buf, size, &env);
            free(buf);
        }
    }
    if (ok)
        ok = sdl_wf_render(&env, out_path, width, height);
    sdl_wf_env_free(&env);
    return ok;
}

#endif /* RULANG_SDL_WAVEFORM_H */
