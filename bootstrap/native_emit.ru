算 密发射含 列 值:
    得 (列 其 查 值) != 空.
法.
# Closed native ABI emitter. Input: [[result primitive ID, parameter IDs, callback bool], ...].
# No source analysis, C identifiers or address conversion: every C type/name comes from
# this fixed table or a bounded integer index. The runtime owns structures and pointers.
算 密发射 签列:
    型名 取 ['void','int8_t','uint8_t','int16_t','uint16_t','int32_t','uint32_t','int64_t','uint64_t','intptr_t','uintptr_t','float','double','void *'].
    槽名 取 ['','i','u','i','u','i','u','i','u','i','u','f32','f64','p'].
    若 (签列 其 量) > 1024 则 卒 'error: 原生静态签名超过 1024'. 然.
    # Validate before emitting even one bridge. Comparisons against the finite integer
    # whitelist reject fractions, strings, unknown IDs and void parameters.
    序 取 0.
    循 (签列 其 量) 次
        签 取 签列[序].
        若 (签 其 量) != 3 则 卒 'error: 原生签名记录无效'. 然.
        若 非 (密发射含 [0,1,2,3,4,5,6,7,8,9,10,11,12,13] 签[0]) 则 卒 'error: 原生返回类型无效'. 然.
        若 签[2] != 真 且 签[2] != 假 则 卒 'error: 原生回调标记无效'. 然.
        项 取 0.
        循 (签[1] 其 量) 次
            若 非 (密发射含 [1,2,3,4,5,6,7,8,9,10,11,12,13] 签[1][项]) 则 卒 'error: 原生参数类型无效'. 然.
            项 取 项+1.
        环.
        序 取 序+1.
    环.
    文 取 ['/* Ahead-of-time primitive ABI thunks: Windows x64 only. */','#if !defined(_WIN32) || defined(_M_ARM64) || defined(_M_ARM64EC) || (!defined(_M_X64) && !defined(__x86_64__))','#error "Ru native C requires Windows x64"','#endif'].
    序 取 0.
    循 (签列 其 量) 次
        签 取 签列[序]. 号 取 序 为 句. 返 取 型名[签[0]].
        形列 取 []. 实 取 []. 回形列 取 []. 项 取 0.
        循 (签[1] 其 量) 次
            型 取 签[1][项]. 位 取 项 为 句.
            形列 其 增 型名[型]. 实 其 增 ('('+型名[型]+')args['+位+'].'+槽名[型]).
            回形列 其 增 (型名[型]+' a'+位). 项 取 项+1.
        环.
        形文 取 __如竞 其 合句 形列 ', '. 回文 取 __如竞 其 合句 回形列 ', '.
        若 (形列 其 量) == 0 则 形文 取 'void'. 回文 取 'void'. 然.
        文 其 增 ('typedef '+返+' (*RuNativeCall_'+号+')('+形文+');').
        文 其 增 ('static RuNativeRaw ru_native_call_'+号+'(void *address, const RuNativeRaw *args) {').
        文 其 增 ('    union { void *address; RuNativeCall_'+号+' function; } target;').
        文 其 增 '    RuNativeRaw result = {0}; target.address = address; (void)args;'.
        调 取 'target.function('+(__如竞 其 合句 实 ', ')+')'.
        若 签[0] == 0 则 文 其 增 ('    '+调+';').
        另 文 其 增 ('    result.'+槽名[签[0]]+' = '+调+';'). 然.
        文 其 增 '    return result;'. 文 其 增 '}'.
        若 签[2] 则
            槽 取 0.
            循 1024 次
                槽文 取 槽 为 句.
                文 其 增 ('static '+返+' ru_native_callback_'+号+'_'+槽文+'('+回文+') {').
                若 (签[1] 其 量) > 0 则
                    文 其 增 ('    RuNativeRaw args['+((签[1] 其 量) 为 句)+'] = {0};').
                    项 取 0.
                    循 (签[1] 其 量) 次
                        位 取 项 为 句.
                        文 其 增 ('    args['+位+'].'+槽名[签[1][项]]+' = a'+位+';'). 项 取 项+1.
                    环.
                然.
                调 取 'ru_native_callback_dispatch('+槽文+', '+号+', '.
                若 (签[1] 其 量) > 0 则 调 取 调+'args)'. 另 调 取 调+'NULL)'. 然.
                若 签[0] == 0 则 文 其 增 ('    (void)'+调+';').
                另 文 其 增 ('    return ('+返+')'+调+'.'+槽名[签[0]]+';'). 然.
                文 其 增 '}'. 槽 取 槽+1.
            环.
            文 其 增 ('static RuNativeCall_'+号+' const ru_native_callbacks_'+号+'[1024] = {').
            槽 取 0.
            循 128 次
                行 取 []. 循 8 次 行 其 增 ('ru_native_callback_'+号+'_'+(槽 为 句)). 槽 取 槽+1. 环.
                文 其 增 ('    '+(__如竞 其 合句 行 ', ')+',').
            环.
            文 其 增 '};'.
        然.
        序 取 序+1.
    环.
    文 其 增 'static int ru_native_generated_signature(int result, int argc, const int *params, int convention) {'.
    文 其 增 '    if (convention != 0 && convention != 1) return -1;'.
    文 其 增 '    (void)result; (void)argc; (void)params;'.
    序 取 0.
    循 (签列 其 量) 次
        签 取 签列[序]. 条 取 ['result == '+(签[0] 为 句),'argc == '+((签[1] 其 量) 为 句)].
        若 (签[1] 其 量) > 0 则 条 其 增 'params != NULL'. 然.
        项 取 0.
        循 (签[1] 其 量) 次
            条 其 增 ('params['+(项 为 句)+'] == '+(签[1][项] 为 句)). 项 取 项+1.
        环.
        文 其 增 ('    if ('+(__如竞 其 合句 条 ' && ')+') return '+(序 为 句)+';'). 序 取 序+1.
    环.
    文 其 增 '    return -1;'. 文 其 增 '}'.
    文 其 增 'static RuNativeRaw ru_native_generated_call(int signature, void *address, const RuNativeRaw *args) {'.
    文 其 增 '    (void)address; (void)args;'. 文 其 增 '    switch (signature) {'.
    序 取 0.
    循 (签列 其 量) 次
        号 取 序 为 句. 文 其 增 ('    case '+号+': return ru_native_call_'+号+'(address, args);'). 序 取 序+1.
    环.
    文 其 增 '    default: { RuNativeRaw zero = {0}; return zero; }'. 文 其 增 '    }'. 文 其 增 '}'.
    文 其 增 'static void *ru_native_generated_callback(int signature, unsigned slot) {'.
    文 其 增 '    if (slot >= 1024) return NULL;'. 文 其 增 '    switch (signature) {'.
    序 取 0.
    循 (签列 其 量) 次
        若 签列[序][2] 则
            号 取 序 为 句.
            文 其 增 ('    case '+号+': { union { RuNativeCall_'+号+' function; void *address; } value;').
            文 其 增 ('        value.function = ru_native_callbacks_'+号+'[slot]; return value.address; }').
        然. 序 取 序+1.
    环.
    文 其 增 '    default: return NULL;'. 文 其 增 '    }'. 文 其 增 '}'.
    得 (__如竞 其 合句 文 '\n')+'\n'.
法.
