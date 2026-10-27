/* 如声：C 音频薄绑定。
 *
 * 如层标准库（stdlib/如声.ru）经 __如声 服务桥接到本头文件；
 * 实际发声由宿主注册的 RuAudioHost 提供（SDL 壳用 SDL_mixer 实现）。
 * 未注册宿主时成员调用 fail（与「如观无宿主」同模式）。
 *
 * 声道号：宿主任意非负整数；<0 表示调用失败（如 文件不存在）。
 * 音量：0..100 整数百分比。
 * 进度：秒（浮点），声道空闲或不可用时返回负数。 */
#ifndef RULANG_AUDIO_RUNTIME_H
#define RULANG_AUDIO_RUNTIME_H

/* RuAudioHost 声明与 ru_audio_set_host 实现见宿主 ABI／graphics_runtime.h；
 * 本文件仅消费 ru_audio_host_slot() 与 RuAudioHost 类型。 */

static RuClass ru_audio_service_class = {"如声工具", NULL, NULL, 0, NULL, NULL, 0, NULL};

static long ru_audio_int(Val v, const char *label, int line) {
    if (v.kind != RU_NUM || v.n != (int64_t)v.n)
        ru_fail(line, "实参「%s」须为整数", label);
    return (long)v.n;
}

static double ru_audio_num(Val v, const char *label, int line) {
    if (v.kind != RU_NUM)
        ru_fail(line, "实参「%s」须为数", label);
    return v.n;
}

static int ru_audio_member(Val receiver, const char *name, size_t argc, const char **keys,
                           Val *args, int line, Val *out) {
    RuClass *klass;
    const RuAudioHost *h;
    const char *path_names[] = {"路径", NULL};
    const char *chan_names[] = {"声道", NULL};
    const char *play_names[] = {"路径", "循环", NULL};
    const char *vol_names[] = {"声道", "音量", NULL};
    Val bound[3];
    (void)path_names; (void)chan_names; (void)play_names; (void)vol_names; (void)bound;
    if (receiver.kind != RU_OBJECT) return 0;
    klass = ((RuObject *)receiver.heap)->klass;
    if (klass != &ru_audio_service_class) return 0;
    h = *ru_audio_host_slot();
/* RU_MEMBERS: 播,停,暂停,续,音量,进度,在播,时长,定位,波形图 */
    if (!strcmp(name, "播")) {
        const char *path;
        long ch;
        ru_bind(name, 2, play_names, argc, keys, args, bound, line);
        if (bound[0].kind != RU_STR || !bound[0].s->len)
            ru_fail(line, "播 的「路径」须为非空句");
        if (bound[1].kind != RU_NULL && bound[1].kind != RU_FACT)
            ru_fail(line, "播 的「循环」须为真假");
        if (!h) ru_fail(line, "如声音频无宿主；如:声 仅支持 SDL 宿主（-t sdl）");
        path = bound[0].s->data;
        ch = h->play(path, bound[1].kind == RU_FACT && (int)bound[1].n);
        *out = v_num((double)ch);
        return 1;
    }
    if (!strcmp(name, "停") || !strcmp(name, "暂停") || !strcmp(name, "续")
        || !strcmp(name, "进度") || !strcmp(name, "在播") || !strcmp(name, "时长")) {
        long ch;
        int ok;
        ru_bind(name, 1, chan_names, argc, keys, args, bound, line);
        if (!h) ru_fail(line, "如声音频无宿主；如:声 仅支持 SDL 宿主（-t sdl）");
        ch = ru_audio_int(bound[0], "声道", line);
        if (!strcmp(name, "停")) ok = h->stop(ch);
        else if (!strcmp(name, "暂停")) ok = h->pause(ch);
        else if (!strcmp(name, "续")) ok = h->resume(ch);
        else if (!strcmp(name, "进度")) { *out = v_num(h->position(ch)); return 1; }
        else if (!strcmp(name, "时长")) { *out = v_num(h->duration ? h->duration(ch) : -1.0); return 1; }
        else ok = h->playing(ch);
        *out = v_fact(ok);
        return 1;
    }
    if (!strcmp(name, "定位")) {
        long ch;
        double seconds;
        const char *pos_names[] = {"声道", "秒", NULL};
        ru_bind(name, 2, pos_names, argc, keys, args, bound, line);
        if (!h) ru_fail(line, "如声音频无宿主；如:声 仅支持 SDL 宿主（-t sdl）");
        ch = ru_audio_int(bound[0], "声道", line);
        seconds = ru_audio_num(bound[1], "秒", line);
        if (seconds < 0) seconds = 0;
        *out = v_fact(h->seek ? h->seek(ch, seconds) : 0);
        return 1;
    }
    if (!strcmp(name, "波形图")) {
        const char *wave_names[] = {"路径", "宽", "高", NULL};
        const char *path;
        char out_path[1600];
        int width, height;
        ru_bind(name, 3, wave_names, argc, keys, args, bound, line);
        if (!h) ru_fail(line, "如声音频无宿主；如:声 仅支持 SDL 宿主（-t sdl）");
        if (bound[0].kind != RU_STR || !bound[0].s->len)
            ru_fail(line, "波形图 的「路径」须为非空句");
        path = bound[0].s->data;
        width = (int)ru_audio_num(bound[1], "宽", line);
        height = (int)ru_audio_num(bound[2], "高", line);
        if (width < 16 || height < 16)
            ru_fail(line, "波形图 的「宽」「高」须 ≥ 16");
        snprintf(out_path, sizeof(out_path), "%s.波形.bmp", path);
        *out = v_fact(h->waveform ? h->waveform(path, out_path, width, height) : 0);
        return 1;
    }
    if (!strcmp(name, "音量")) {
        long ch;
        int pct, got;
        ru_bind(name, 2, vol_names, argc, keys, args, bound, line);
        if (!h) ru_fail(line, "如声音频无宿主；如:声 仅支持 SDL 宿主（-t sdl）");
        ch = ru_audio_int(bound[0], "声道", line);
        pct = (int)ru_audio_int(bound[1], "音量", line);
        if (pct < 0) pct = 0;
        if (pct > 100) pct = 100;
        got = h->volume(ch, pct);
        *out = v_num((double)got);
        return 1;
    }
/* RU_END_MEMBERS */
    (void)argc; (void)keys; (void)args;
    return 0;
}

static Env *ru_audio_builtins(void) {
    static Env env;
    static int initialized;
    Val service;
    if (initialized) return &env;
    initialized = 1;
    env_init(&env, ru_practical_builtins());
    ru_audio_service_class.global = &env;
    service = ru_object_new(&ru_audio_service_class, 0);
    env_declare(&env, "__如声", service);
    v_drop(service);
    return &env;
}

#endif /* RULANG_AUDIO_RUNTIME_H */
