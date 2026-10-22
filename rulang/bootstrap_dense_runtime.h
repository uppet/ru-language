#ifndef RU_BOOTSTRAP_DENSE_RUNTIME_H
#define RU_BOOTSTRAP_DENSE_RUNTIME_H
/* Private bootstrap ABI, included after the fixed ordinary runtime.
 * No ownership changes, NativeMemory access, callbacks or kernel algorithms.
 * Generated bridges validate ALL scalars, then views/ranges, then retain;
 * they release immediately after the synchronous no-call/no-GC LLVM kernel.
 */
typedef struct {
    const unsigned char *data;
    uint32_t length;
} BootDenseUtf8;

static uint32_t boot_dense_scalar(Val value, int line, uint32_t maximum)
{
    if (value.kind != RU_NUM || !isfinite(value.n) || value.n < 0.0 ||
        value.n > (double)maximum || floor(value.n) != value.n)
        ru_fail(line, "密整数参数须为精确范围内的普通整数");
    return (uint32_t)value.n;
}

static BootDenseUtf8 boot_dense_utf8(Val value, int line)
{
    BootDenseUtf8 view;
    if (value.kind != RU_STR || value.s == NULL)
        ru_fail(line, "密 UTF8 视图需要不可变普通句");
    if (value.s->len > UINT32_MAX)
        ru_fail(line, "密 UTF8 视图长度超出 u32");
    view.data = (const unsigned char *)value.s->data;
    view.length = (uint32_t)value.s->len;
    return view;
}
#endif
