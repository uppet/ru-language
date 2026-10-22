/* Private immutable UTF8 boundary. Ru strings never expose writable storage or
 * a native address in the language. Borrow bytes, not scalar/codepoint indices.
 * It is safe to enter a checked no-call/no-GC kernel inside a synchronous Ru
 * callback: no native pointer is imported and no external code can reenter.
 * This does not relax NativeMemory's separate reentry/owner rules. */
static RuMiView ru_mi_string_view(Val value, int line)
{
    RuMiView view;
    if (value.kind != RU_STR) ru_fail(line, "密 UTF8 视图需要不可变普通句");
    if (value.s->len > UINT32_MAX) ru_fail(line, "密 UTF8 视图长度超出 u32");
    view.data = (const uint8_t *)value.s->data;
    view.length = (uint32_t)value.s->len;
    return view;
}
