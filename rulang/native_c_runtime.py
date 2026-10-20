"""Native-only integration points for the portable, pruned C value runtime.

The ordinary C source is left byte-for-byte unchanged. Native headers and
callback unwind bookkeeping are included only after an explicit capability
choice, never by a runtime or environment-variable switch in the executable.
"""
from pathlib import Path


def _replace(source, old, new, count=1):
    if source.count(old) != count:
        raise ValueError('Native runtime integration point changed: ' + old[:80])
    return source.replace(old, new)


def integrate_runtime(source):
    directory = Path(__file__).parent
    types = (directory / 'native_types.h').read_text(encoding='utf-8')
    platform = (directory / 'native_platform_win64.h').read_text(encoding='utf-8')
    source = _replace(source, 'RU_MODULE, RU_ENV };', 'RU_MODULE, RU_ENV, RU_NATIVE };')
    source = _replace(source, 'struct RuHeap { size_t roots;', 'struct RuHeap { RuHeap *transient_prev, *transient_next; size_t permanent_roots; size_t roots;')
    # Pin the native-enabled layout: two pointer fields (2×8 on x64) plus two
    # size_t fields (2×8) must equal 48 bytes.  A silent drift here breaks the
    # transient-root index offsets without any compile-time diagnostic.  Use a
    # negative-array-size typedef, not _Static_assert, because native tests
    # compile with strict C99 -pedantic where C11 _Static_assert is rejected.
    source = _replace(source, 'static RuHeap *ru_heap;', '/* Native layout contract: transient links + permanent/total root counts. */\n#if defined(_WIN64) || defined(__x86_64__)\ntypedef char ru_native_heap_layout_check[sizeof(RuHeap) == 48 ? 1 : -1];\n#endif\nstatic RuHeap *ru_heap;\nstatic RuHeap *ru_transient_roots;')
    source = _replace(source, 'static Val v_copy(Val v)', '''/* An allocation-free index of heaps with roots > permanent_roots.
 * The index is not a GC root set: permanently rooted heaps may be absent. */
static void rn_transient_link(RuHeap *heap)
{
    heap->transient_prev = NULL; heap->transient_next = ru_transient_roots;
    if (ru_transient_roots) ru_transient_roots->transient_prev = heap;
    ru_transient_roots = heap;
}
static void rn_transient_unlink(RuHeap *heap)
{
    if (heap->transient_prev) heap->transient_prev->transient_next = heap->transient_next;
    else if (ru_transient_roots == heap) ru_transient_roots = heap->transient_next;
    else return; /* Already unlisted, including zero-root GC victims. */
    if (heap->transient_next) heap->transient_next->transient_prev = heap->transient_prev;
    heap->transient_prev = NULL; heap->transient_next = NULL;
}
static Val v_copy(Val v)''')
    source = _replace(source, '++v.heap->roots;', '''if (v.heap->roots == v.heap->permanent_roots) rn_transient_link(v.heap);
        ++v.heap->roots;''')
    source = _replace(source, '--v.heap->roots;', '''--v.heap->roots;
        if (v.heap->roots == v.heap->permanent_roots) rn_transient_unlink(v.heap);''')
    source = _replace(source, 'h->kind=kind; h->roots=1; h->next=ru_heap; ru_heap=h; ++ru_live;',
                      'h->kind=kind; h->roots=1; h->next=ru_heap; ru_heap=h; ++ru_live;\n    rn_transient_link(h);')
    source = _replace(source, '--env->gc.roots; return;', '''--env->gc.roots;
        if (env->gc.roots == env->gc.permanent_roots) rn_transient_unlink(&env->gc);
        return;''')
    source = _replace(source, 'static void ru_heap_dispose(RuHeap *heap)\n{',
                      'static void ru_heap_dispose(RuHeap *heap)\n{\n    rn_transient_unlink(heap);')
    source = _replace(source, 'if(ru_failed) for(h=ru_heap;h;h=h->next) h->roots=0;',
                      'if(ru_failed) for(h=ru_heap;h;h=h->next) { rn_transient_unlink(h); h->roots=0; }')
    source = _replace(source, 'typedef struct RuScratch { void *data;', 'typedef struct RuScratch { void (*cleanup)(void *); void *data;')
    source = _replace(source, 'entry->data = NULL; entry->next = ru_scratch;', 'entry->cleanup = free; entry->data = NULL; entry->next = ru_scratch;')
    source = _replace(source, 'free(entry->data); free(entry); return;', 'entry->cleanup(entry->data); free(entry); return;')
    marker = '/* Diagnostics describe runtime values, never a hypothetical conversion. */'
    source = _replace(source, marker, types + '\n/* RU_NATIVE_PLATFORM_BEGIN */\n' + platform + '\n/* RU_NATIVE_PLATFORM_END */\n' + marker)
    source = _replace(source, 'case RU_MODULE: return "外言";', 'case RU_MODULE: return "外言";\n    case RU_NATIVE: return "密原生值";')
    source = _replace(source, '    va_list args;\n    fprintf(stderr,', '''    va_list args;
    if (ru_native_trap) {
        size_t used = (size_t)snprintf(ru_native_trap->message, sizeof(ru_native_trap->message),
                                     "%.512s:%d: ", ru_source ? ru_source : "<回调>", line);
        if (used >= sizeof(ru_native_trap->message)) used = sizeof(ru_native_trap->message) - 1;
        va_start(args, format);
        vsnprintf(ru_native_trap->message + used, sizeof(ru_native_trap->message) - used, format, args);
        va_end(args);
        longjmp(ru_native_trap->jump, 1);
    }
    fprintf(stderr,''')
    source = _replace(source, 'static void ru_panic_raise(Val reason, int line, int col)', '''/* Persistent roots belong to escaped state, never to an abandoned call frame. */
static Val v_pin(Val value)
{
    if (value.heap) {
        if (value.heap->roots == SIZE_MAX) ru_fail(0, "值引用过多");
        ++value.heap->roots; ++value.heap->permanent_roots;
    }
    return value;
}
static void v_unpin(Val value)
{
    if (value.heap) {
        if (!value.heap->permanent_roots) ru_fail(0, "内部错误：永久根计数失衡");
        --value.heap->permanent_roots;
        if (!value.heap->roots) ru_fail(0, "内部错误：值的根计数失衡");
        --value.heap->roots;
    }
}
static void *ru_native_scratch_realloc(void *data, size_t size)
{
    RuScratch *entry;
    void *grown;
    if (!data) return ru_scratch_alloc(size, 0);
    for (entry = ru_scratch; entry && entry->data != data; entry = entry->next) {}
    if (!entry) ru_fail(0, "内部错误：临时缓冲不受管理");
    grown = realloc(data, size ? size : 1);
    if (!grown) ru_fail(0, "内存不足");
    entry->data = grown; return grown;
}
static void *ru_native_scratch_take(void *data)
{
    RuScratch **slot = &ru_scratch;
    while (*slot) {
        RuScratch *entry = *slot;
        if (entry->data == data) { *slot = entry->next; free(entry); return data; }
        slot = &entry->next;
    }
    ru_fail(0, "内部错误：临时缓冲不受管理"); return NULL;
}
static void ru_native_scratch_adopt(void *data, void (*cleanup)(void *))
{
    RuScratch *entry;
    if (!data) return;
    entry = (RuScratch *)malloc(sizeof(*entry));
    if (!entry) { cleanup(data); ru_fail(0, "内存不足"); }
    entry->data = data; entry->cleanup = cleanup; entry->next = ru_scratch; ru_scratch = entry;
}
typedef struct { char **names; size_t count; } RuNativeNameList;
static void ru_native_names_free(void *data)
{
    RuNativeNameList *list = (RuNativeNameList *)data; size_t i;
    for (i = 0; i < list->count; ++i) free(list->names[i]);
    free(list->names); free(list);
}
static RuNativeNameList *ru_native_names_track(char **names, size_t count)
{
    RuNativeNameList *list = (RuNativeNameList *)malloc(sizeof(*list));
    if (!list) {
        size_t i; for (i = 0; i < count; ++i) free(names[i]); free(names);
        ru_fail(0, "内存不足");
    }
    list->names = names; list->count = count;
    ru_native_scratch_adopt(list, ru_native_names_free); return list;
}
static void ru_panic_raise(Val reason, int line, int col)''')
    source = _replace(source, 'ru_panic_reason = v_copy(reason);', 'ru_panic_reason = v_pin(reason);')
    source = _replace(source, 'failure->reason = v_copy(ru_panic_reason);', 'failure->reason = v_pin(ru_panic_reason);')
    source = _replace(source, 'if (ru_panicking) v_drop(ru_panic_reason);', 'if (ru_panicking) v_unpin(ru_panic_reason);')
    source = _replace(source, 'v_drop(failure->reason); failure->reason', 'v_unpin(failure->reason); failure->reason')
    source = _replace(source, 'Val owned=env->managed ? value : v_copy(value);', 'Val owned;')
    source = _replace(source, '        if(!env->managed) v_drop(b->value);', '        owned=env->managed ? value : v_pin(value);\n        if(!env->managed) v_unpin(b->value);')
    source = _replace(source, 'b=(RuBinding *)ru_alloc(sizeof(*b),0); b->name=(char *)ru_alloc(strlen(name)+1,0); strcpy(b->name,name);', '''b=(RuBinding *)ru_scratch_alloc(sizeof(*b),0);
    b->name=(char *)ru_scratch_alloc(strlen(name)+1,0); strcpy(b->name,name);
    owned=env->managed ? value : v_pin(value);
    ru_native_scratch_take(b->name); ru_native_scratch_take(b);''')
    source = _replace(source, 'RuBinding *next=b->next; v_drop(b->value);', 'RuBinding *next=b->next; v_unpin(b->value);')
    source = _replace(source, 'free(array->items);array->items=(Val *)ru_alloc(map->len*2*sizeof(Val),line);', '{ Val *items=(Val *)ru_alloc(map->len*2*sizeof(Val),line); free(array->items);array->items=items; }')
    source = _replace(source, '        else if (h->kind == RU_ENV) {', '''        else if (h->kind == RU_NATIVE) {
            RuNative *object = (RuNative *)h; size_t i;
            RU_GC_WORK(object->edge_count);
            for (i = 0; i < object->edge_count; ++i) RU_MARK(object->edges[i]);
        }
        else if (h->kind == RU_ENV) {''')
    source = _replace(source, '    else if(heap->kind==RU_ENV) {', '    else if(heap->kind==RU_NATIVE) ru_native_dispose((RuNative *)heap);\n    else if(heap->kind==RU_ENV) {')
    source = _replace(source, '    ru_finished=1;', '    ru_finished=1;\n    ru_native_shutdown();')
    source = _replace(source, '    if(receiver.kind==RU_MODULE){\n        RuBinding *binding;Val value,result;', '    if (ru_native_member(receiver, name, argc, keys, args, line, &io_result)) return io_result;\n    if(receiver.kind==RU_MODULE){\n        RuBinding *binding;Val value,result;')
    source = _replace(source, 'else if (v.kind == RU_NULL) ru_text_word(out, "空");', 'else if (v.kind == RU_NULL) ru_text_word(out, "空");\n    else if (v.kind == RU_NATIVE) ru_text_word(out, "<密原生值>");', count=2)
    # Callback errors may abandon these worklists. Keep them in the existing
    # scratch chain so restoration frees them without touching heap-owned data.
    for old, new in (
        ('realloc(s->data,cap)', 'ru_native_scratch_realloc(s->data,cap)'),
        ('realloc(*steps, *capacity * sizeof(**steps))', 'ru_native_scratch_realloc(*steps, *capacity * sizeof(**steps))'),
        ('free(steps);', 'ru_scratch_free(steps);'),
        ('free(out.data);', 'ru_scratch_free(out.data);'),
        ('ru_alloc(cap * sizeof(*grown), 0)', 'ru_scratch_alloc(cap * sizeof(*grown), 0)'),
        ('free(*table);', 'ru_scratch_free(*table);'),
        ('ru_alloc(capacity * sizeof(*stack), 0)', 'ru_scratch_alloc(capacity * sizeof(*stack), 0)'),
        ('realloc(stack, capacity * sizeof(*stack))', 'ru_native_scratch_realloc(stack, capacity * sizeof(*stack))'),
        ('free(stack); free(seen);', 'ru_scratch_free(stack); ru_scratch_free(seen);'),
        ('item=(char *)ru_alloc(len+1,0)', 'item=(char *)ru_scratch_alloc(len+1,0)'),
        ('free(item);return good;', 'ru_scratch_free(item);return good;'),
    ):
        source = _replace(source, old, new)
    at = source.index('Val read_input(Val prompt, int line)')
    source = source[:at] + source[at:].replace('ru_alloc(capacity, line)', 'ru_scratch_alloc(capacity, line)').replace('realloc(buffer, capacity)', 'ru_native_scratch_realloc(buffer, capacity)').replace('free(buffer)', 'ru_scratch_free(buffer)')
    return source


def integrate_io(source):
    """Track raw I/O worklists only after all OS handles have been closed."""
    source = _replace(source, '    if (!error && !eof) {', '    ru_native_scratch_adopt(buffer, free);\n    if (!error && !eof) {')
    source = _replace(source, '    free(buffer);', '    ru_scratch_free(buffer);')
    source = _replace(source, '    if (!error) {\n        if (count > 1) qsort', '    RuNativeNameList *name_guard = ru_native_names_track(names, count);\n    if (!error) {\n        if (count > 1) qsort')
    source = _replace(source, '            location = v_str(full); free(full);', '            ru_native_scratch_adopt(full, free);\n            location = v_str(full); ru_scratch_free(full);')
    source = _replace(source, '    for (i = 0; i < count; ++i) free(names[i]);\n    free(names);', '    ru_scratch_free(name_guard);')
    return source
