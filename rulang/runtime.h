#ifndef RU_RUNTIME_H
#define RU_RUNTIME_H
#ifndef _WIN32
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#endif
/* Standalone C99 runtime. Every generated temporary and environment binding
 * owns one external root. Container edges never own roots. Mark/sweep follows
 * edges from external roots, so shared references and cycles are reclaimed.
 * No conservative stack scanning, reference-count cycle leaks, AST, or VM. */
#include <math.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { RU_NUM, RU_STR, RU_NULL, RU_PAIR, RU_ARRAY, RU_OBJECT, RU_FUNCTION, RU_CLASS, RU_MODULE };
typedef struct RuHeap RuHeap;
typedef struct RuString RuString;
typedef struct RuClass RuClass;
typedef struct Env Env;
typedef struct Val { int kind; double n; RuString *s; RuHeap *heap; RuClass *klass; Env *module; } Val;
struct RuHeap { size_t roots; unsigned mark; int kind; RuHeap *next; };
struct RuString { RuHeap gc; size_t len; char data[]; };
typedef struct { RuHeap gc; Val first, second; } RuPair;
typedef struct { RuHeap gc; size_t len, capacity; Val *items; } RuArray;
typedef struct { RuHeap gc; RuClass *klass; size_t len; Val *fields; } RuObject;
typedef Val (*RuCode)(Env *, Val, int, Val *);
typedef struct { const char *name; size_t count; const char **names, **types; RuCode code; } RuFunction;
typedef struct { RuHeap gc; RuFunction *function; Env *global; Val self; } RuCallable;
struct RuClass { const char *name; RuClass *parent; Env *global; size_t count; const char **names, **types; size_t methods_count; RuFunction **methods; };
typedef struct RuBinding { char *name; Val value; int reserved; struct RuBinding *next; } RuBinding;
struct Env { Env *parent; RuBinding *bindings; Env *registry_next; };

static const char *ru_source = "<程序>";
static unsigned ru_call_depth;
/* Explicit panic state crosses native calls without nonlocal jumps. Each
 * generated caller checks this flag and drops its live owned temporaries.
 * The rooted reason survives environment teardown and collection. */
static int ru_panicking;
static Val ru_panic_reason;
static const char *ru_panic_source;
static int ru_panic_line, ru_panic_col;
typedef struct RuModuleFailure {
    Val reason;
    const char *source;
    int line, col;
    struct RuModuleFailure *next;
} RuModuleFailure;
static RuModuleFailure *ru_module_failures;
static RuHeap *ru_heap;
static Env *ru_envs;
typedef struct RuScratch { void *data; struct RuScratch *next; } RuScratch;
static RuScratch *ru_scratch;
static size_t ru_live, ru_freed, ru_collections, ru_threshold = 256, ru_next_gc = 256;
static int ru_initialized, ru_finished;
static void ru_shutdown(void);
static void env_free(Env *env);
static void ru_io_defaults(Val value, int line);
static int ru_io_member(Val receiver, const char *name, size_t argc, const char **keys,
                        Val *args, int line, Val *out);
static void ru_fail(int line, const char *format, ...)
{
    va_list args;
    fprintf(stderr, "%s:%d: 运行错误：", ru_source ? ru_source : "<程序>", line);
    va_start(args, format); vfprintf(stderr, format, args); va_end(args);
    fputc('\n', stderr); ru_shutdown(); exit(1);
}
static void *ru_alloc(size_t size, int line)
{
    void *p = malloc(size ? size : 1);
    if (!p) ru_fail(line, "内存不足");
    return p;
}
/* Temporary argument-binding buffers are registered separately so fatal
 * diagnostics also dispose of in-flight calls before exiting. */
static void *ru_scratch_alloc(size_t size, int line)
{
    RuScratch *entry = (RuScratch *)ru_alloc(sizeof(*entry), line);
    entry->data = NULL; entry->next = ru_scratch; ru_scratch = entry;
    entry->data = ru_alloc(size, line);
    return entry->data;
}
static void ru_scratch_free(void *data)
{
    RuScratch **slot = &ru_scratch;
    while (*slot) {
        RuScratch *entry = *slot;
        if (entry->data == data) {
            *slot = entry->next; free(entry->data); free(entry); return;
        }
        slot = &entry->next;
    }
}
static Val v_num(double n) { Val v = {0}; v.kind = RU_NUM; v.n = n; return v; }
static Val v_null(void) { Val v = {0}; v.kind = RU_NULL; return v; }
static Val v_copy(Val v)
{
    if (v.heap) { if (v.heap->roots == SIZE_MAX) ru_fail(0, "值引用过多"); ++v.heap->roots; }
    return v;
}
static void v_drop(Val v)
{
    if (v.heap) { if (!v.heap->roots) ru_fail(0, "内部错误：值的根计数失衡"); --v.heap->roots; }
}
static void ru_panic_raise(Val reason, int line, int col)
{
    if (reason.kind != RU_STR) ru_fail(line, "「卒」的原因须为句");
    ru_panic_reason = v_copy(reason);
    ru_panic_source = ru_source;
    ru_panic_line = line; ru_panic_col = col; ru_panicking = 1;
}
/* Failed initializations retain their globals: already escaped objects and
 * functions still refer to that environment. Imports rethrow the original
 * cached failure instead of replaying side effects or retargeting classes. */
static void ru_module_failure_save(RuModuleFailure *failure)
{
    failure->reason = v_copy(ru_panic_reason);
    failure->source = ru_panic_source;
    failure->line = ru_panic_line; failure->col = ru_panic_col;
    failure->next = ru_module_failures; ru_module_failures = failure;
}
static Val ru_module_failure_raise(RuModuleFailure *failure)
{
    ru_panic_raise(failure->reason, failure->line, failure->col);
    ru_panic_source = failure->source;
    return v_null();
}
static void ru_panic_clear(void)
{
    if (ru_panicking) v_drop(ru_panic_reason);
    ru_panic_reason = v_null(); ru_panicking = 0;
}
static int ru_panic_uncaught(void)
{
    fprintf(stderr, "%s:%d:%d: 未救之卒：%s\n", ru_panic_source ? ru_panic_source : "<程序>",
            ru_panic_line, ru_panic_col, ru_panic_reason.s->data);
    ru_panic_clear(); ru_shutdown(); return 1;
}
/* Mark iteratively: deeply nested pairs and cyclic graphs cannot overflow the
 * C stack. Each node enters the worklist once per collection. */
static void ru_gc(void)
{
    RuHeap *h, **slot, **todo;
    size_t used = 0, at = 0;
    ++ru_collections;
    todo = (RuHeap **)ru_alloc((ru_live ? ru_live : 1) * sizeof(*todo), 0);
    for (h = ru_heap; h; h = h->next) {
        h->mark = h->roots != 0;
        if (h->mark) todo[used++] = h;
    }
#define RU_MARK(v) do { RuHeap *child_ = (v).heap; if (child_ && !child_->mark) { child_->mark=1; todo[used++]=child_; } } while (0)
    while (at < used) {
        h = todo[at++];
        if (h->kind == RU_PAIR) { RuPair *p=(RuPair *)h; RU_MARK(p->first); RU_MARK(p->second); }
        else if (h->kind == RU_ARRAY) { RuArray *a=(RuArray *)h; size_t i; for(i=0;i<a->len;++i) RU_MARK(a->items[i]); }
        else if (h->kind == RU_OBJECT) { RuObject *o=(RuObject *)h; size_t i; for(i=0;i<o->len;++i) RU_MARK(o->fields[i]); }
        else if (h->kind == RU_FUNCTION) { RuCallable *f=(RuCallable *)h; RU_MARK(f->self); }
    }
#undef RU_MARK
    free(todo);
    slot = &ru_heap;
    while ((h = *slot)) {
        if (h->mark) { slot = &h->next; continue; }
        *slot = h->next;
        if (h->kind == RU_ARRAY) free(((RuArray *)h)->items);
        if (h->kind == RU_OBJECT) free(((RuObject *)h)->fields);
        free(h); --ru_live; ++ru_freed;
    }
    ru_next_gc = ru_live > SIZE_MAX - ru_threshold ? SIZE_MAX : ru_live + ru_threshold;
}
static void ru_init(void)
{
    const char *text;
    if (ru_initialized) return;
    ru_initialized=1;
    text=getenv("RU_GC_THRESHOLD");
    if (text && *text) { char *end; unsigned long n=strtoul(text,&end,10); if (!*end && n>0 && n<=100000000) ru_threshold=(size_t)n; }
    ru_next_gc=ru_threshold;
}
static RuHeap *ru_new_heap(size_t size, int kind, int line)
{
    RuHeap *h;
    ru_init();
    if (ru_live >= ru_next_gc) ru_gc();
    h=(RuHeap *)ru_alloc(size,line); memset(h,0,size);
    h->kind=kind; h->roots=1; h->next=ru_heap; ru_heap=h; ++ru_live;
    return h;
}
static Val ru_string_alloc(size_t len, int line)
{
    Val v=v_null();
    if (len > SIZE_MAX-sizeof(RuString)-1) ru_fail(line,"字符串过长");
    v.kind=RU_STR; v.heap=ru_new_heap(sizeof(RuString)+len+1,RU_STR,line); v.s=(RuString *)v.heap;
    v.s->len=len; v.s->data[len]=0; return v;
}
static int ru_valid_utf8(const char *text, size_t length)
{
    size_t i = 0, remaining;
    uint32_t cp, minimum;
    while (i < length) {
        unsigned char byte = (unsigned char)text[i++];
        if (byte < 0x80) continue;
        if (byte >= 0xc2 && byte <= 0xdf) { cp = byte & 0x1f; remaining = 1; minimum = 0x80; }
        else if (byte >= 0xe0 && byte <= 0xef) { cp = byte & 0x0f; remaining = 2; minimum = 0x800; }
        else if (byte >= 0xf0 && byte <= 0xf4) { cp = byte & 7; remaining = 3; minimum = 0x10000; }
        else return 0;
        if (remaining > length - i) return 0;
        while (remaining--) {
            byte = (unsigned char)text[i++];
            if ((byte & 0xc0) != 0x80) return 0;
            cp = (cp << 6) | (byte & 0x3f);
        }
        if (cp < minimum || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)) return 0;
    }
    return 1;
}
static Val v_str(const char *text)
{
    size_t length = strlen(text);
    Val value;
    if (!ru_valid_utf8(text, length)) ru_fail(0, "字符串不是有效的 UTF-8");
    value = ru_string_alloc(length, 0);
    memcpy(value.s->data, text, length);
    return value;
}
static Val v_pair(Val a, Val b, int line)
{
    Val v=v_null(); RuPair *p=(RuPair *)ru_new_heap(sizeof(*p),RU_PAIR,line);
    v.kind=RU_PAIR; v.heap=&p->gc; p->first=a; p->second=b; return v;
}
static Val v_array(size_t count, Val *items, int line)
{
    Val v=v_null(); RuArray *a;
    if(count>SIZE_MAX/sizeof(Val)) ru_fail(line,"阵过长");
    a=(RuArray *)ru_new_heap(sizeof(*a),RU_ARRAY,line);
    v.kind=RU_ARRAY; v.heap=&a->gc; a->len=a->capacity=count;
    a->items=(Val *)ru_alloc(count*sizeof(Val),line);
    if(count) memcpy(a->items,items,count*sizeof(Val));
    return v;
}
static int v_truth(Val v)
{
    if(v.kind==RU_NULL) return 0;
    if(v.kind==RU_NUM) return v.n!=0;
    if(v.kind==RU_STR) return v.s->len!=0;
    if(v.kind==RU_ARRAY) return ((RuArray *)v.heap)->len!=0;
    return 1;
}
static void env_init(Env *env, Env *parent)
{ env->parent=parent; env->bindings=NULL; env->registry_next=ru_envs; ru_envs=env; }
static RuBinding *env_find(Env *env,const char *name)
{
    for(;env;env=env->parent) { RuBinding *b; for(b=env->bindings;b;b=b->next) if(!strcmp(b->name,name)) return b; }
    return NULL;
}
static Val env_get(Env *env,const char *name,int line)
{ RuBinding *b=env_find(env,name); if(!b) ru_fail(line,"未定义变量：%s",name); return v_copy(b->value); }
static void env_set(Env *env,const char *name,Val value)
{
    RuBinding *b; Val owned=v_copy(value);
    for(b=env->bindings;b;b=b->next) if(!strcmp(b->name,name)) { v_drop(b->value); b->value=owned; return; }
    b=(RuBinding *)ru_alloc(sizeof(*b),0); b->name=(char *)ru_alloc(strlen(name)+1,0); strcpy(b->name,name);
    b->value=owned; b->reserved=0; b->next=env->bindings; env->bindings=b;
}
static void env_declare(Env *env, const char *name, Val value)
{
    env_set(env, name, value);
    env_find(env, name)->reserved = 1;
}
static void env_bind(Env *env, const char *name, Val value, int line)
{
    RuBinding *existing = env_find(env, name);
    if (!strcmp(name, "读") || (existing && existing->reserved))
        ru_fail(line, "变量名不能与函数名、形名或内置名称重名");
    env_set(env, name, value);
}
static void env_free(Env *env)
{
    Env **slot=&ru_envs; RuBinding *b=env->bindings;
    while(*slot && *slot!=env) slot=&(*slot)->registry_next;
    if(*slot) *slot=env->registry_next;
    while(b) { RuBinding *next=b->next; v_drop(b->value); free(b->name); free(b); b=next; }
    env->bindings=NULL; env->parent=NULL;
}
static void ru_shutdown(void)
{
    RuHeap *h;
    if(ru_finished) return;
    ru_finished=1;
    ru_panic_clear();
    while(ru_module_failures) {
        RuModuleFailure *failure = ru_module_failures;
        ru_module_failures = failure->next;
        v_drop(failure->reason); failure->reason = v_null();
    }
    while(ru_envs) env_free(ru_envs);
    while(ru_scratch) ru_scratch_free(ru_scratch->data);
    ru_gc();
    if(getenv("RU_GC_STATS")) fprintf(stderr,"RU_GC live=%zu freed=%zu collections=%zu\n",ru_live,ru_freed,ru_collections);
    /* Error exits can have live generated temporaries. The process is ending,
     * so dispose of those too, without traversing already-cleared roots. */
    while((h=ru_heap)) { ru_heap=h->next; if(h->kind==RU_ARRAY) free(((RuArray *)h)->items); if(h->kind==RU_OBJECT) free(((RuObject *)h)->fields); free(h); }
    ru_live=0;
}
static int ru_ascii_space(unsigned char c)
{
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' ||
           c == '\v' || c == '\f';
}

static int ru_ascii_digit(unsigned char c)
{
    return c >= '0' && c <= '9';
}

static double ru_parse_number(const char *text, int line)
{
    const char *start = text;
    const char *end = text + strlen(text);
    const char *p;
    char *parsed_end;
    int digits = 0;
    double result;

    while (start < end && ru_ascii_space((unsigned char)*start)) start++;
    while (end > start && ru_ascii_space((unsigned char)end[-1])) end--;
    p = start;
    if (p < end && (*p == '+' || *p == '-')) p++;
    while (p < end && ru_ascii_digit((unsigned char)*p)) {
        digits = 1;
        p++;
    }
    if (p < end && *p == '.') {
        p++;
        while (p < end && ru_ascii_digit((unsigned char)*p)) {
            digits = 1;
            p++;
        }
    }
    if (!digits) ru_fail(line, "无法转为数字");
    if (p < end && (*p == 'e' || *p == 'E')) {
        p++;
        if (p < end && (*p == '+' || *p == '-')) p++;
        digits = 0;
        while (p < end && ru_ascii_digit((unsigned char)*p)) {
            digits = 1;
            p++;
        }
        if (!digits) ru_fail(line, "无法转为数字");
    }
    if (p != end) ru_fail(line, "无法转为数字");
    /* A standalone C program starts in the C locale. The explicit grammar
     * above excludes strtod's hexadecimal, infinity, and NaN extensions. */
    result = strtod(start, &parsed_end);
    if (parsed_end != end || !isfinite(result))
        ru_fail(line, "无法转为有限数字");
    return result;
}

/* Formatting uses an explicit worklist; arbitrary-depth cyclic graphs are safe. */
typedef struct { char *data; size_t len,cap; } RuText;
static void ru_text_add(RuText *s,const char *text,size_t n)
{
    size_t need;
    if(n>SIZE_MAX-s->len-1) ru_fail(0,"字符串过长");
    need=s->len+n+1;
    if(need>s->cap) { size_t cap=s->cap?s->cap:64; char *p; while(cap<need) { if(cap>SIZE_MAX/2) {cap=need;break;} cap*=2; } p=(char *)realloc(s->data,cap); if(!p) ru_fail(0,"内存不足"); s->data=p;s->cap=cap; }
    memcpy(s->data+s->len,text,n);s->len+=n;s->data[s->len]=0;
}
static void ru_text_word(RuText *s,const char *text) { ru_text_add(s,text,strlen(text)); }
typedef struct { int action; Val value; const char *text; unsigned old_mark; } RuFormatStep;
static void ru_format_push(RuFormatStep **steps, size_t *used, size_t *capacity,
                           int action, Val value, const char *text, unsigned old_mark)
{
    if (*used == *capacity) {
        RuFormatStep *grown;
        if (*capacity > SIZE_MAX / sizeof(**steps) / 2) ru_fail(0, "字符串过长");
        *capacity = *capacity ? *capacity * 2 : 32;
        grown = (RuFormatStep *)realloc(*steps, *capacity * sizeof(**steps));
        if (!grown) ru_fail(0, "内存不足");
        *steps = grown;
    }
    (*steps)[*used].action = action;
    (*steps)[*used].value = value;
    (*steps)[*used].text = text;
    (*steps)[*used].old_mark = old_mark;
    ++*used;
}
static void ru_format(RuText *out, Val value)
{
    RuFormatStep *steps = NULL;
    size_t used = 0, capacity = 0, i;
    char buffer[64];
#define RU_PUSH(a,v,t,m) ru_format_push(&steps, &used, &capacity, a, v, t, m)
    RU_PUSH(0, value, NULL, 0);
    while (used) {
        RuFormatStep step = steps[--used];
        Val v = step.value;
        if (step.action == 1) { ru_text_word(out, step.text); continue; }
        if (step.action == 2) { v.heap->mark = step.old_mark; continue; }
        if (v.kind == RU_NUM) { snprintf(buffer, sizeof(buffer), "%.15g", v.n); ru_text_word(out, buffer); }
        else if (v.kind == RU_STR) ru_text_add(out, v.s->data, v.s->len);
        else if (v.kind == RU_NULL) ru_text_word(out, "空");
        else if (v.kind == RU_OBJECT || v.kind == RU_CLASS) {
            ru_text_word(out, "<形 ");
            ru_text_word(out, v.kind == RU_CLASS ? v.klass->name : ((RuObject *)v.heap)->klass->name);
            ru_text_word(out, ">");
        } else if (v.kind == RU_MODULE) ru_text_word(out, "<外言>");
        else if (v.kind == RU_FUNCTION) {
            ru_text_word(out, "<算 ");
            ru_text_word(out, ((RuCallable *)v.heap)->function->name);
            ru_text_word(out, ">");
        } else {
            /* The formatter never allocates GC values while this temporary
             * active-path mark is present; leave events restore every mark. */
            if (v.heap->mark == 2) { ru_text_word(out, "<循环>"); continue; }
            RU_PUSH(2, v, NULL, v.heap->mark);
            v.heap->mark = 2;
            if (v.kind == RU_PAIR) {
                RuPair *pair = (RuPair *)v.heap;
                RU_PUSH(1, v_null(), ")", 0);
                RU_PUSH(0, pair->second, NULL, 0);
                RU_PUSH(1, v_null(), " 对 ", 0);
                RU_PUSH(0, pair->first, NULL, 0);
                ru_text_word(out, "(");
            } else if (v.kind == RU_ARRAY) {
                RuArray *array = (RuArray *)v.heap;
                RU_PUSH(1, v_null(), "]", 0);
                for (i = array->len; i > 0; --i) {
                    RU_PUSH(0, array->items[i - 1], NULL, 0);
                    if (i > 1) RU_PUSH(1, v_null(), ", ", 0);
                }
                ru_text_word(out, "[");
            }
        }
    }
#undef RU_PUSH
    free(steps);
}
static Val v_to_string(Val value)
{
    RuText out = {0};
    Val result;
    if (value.kind == RU_STR) return v_copy(value);
    ru_format(&out, value);
    result = ru_string_alloc(out.len, 0);
    if (out.len) memcpy(result.s->data, out.data, out.len);
    free(out.data);
    return result;
}
static Val v_convert(Val value,int kind,int line)
{
    if(kind==RU_NUM) { if(value.kind==RU_NUM)return v_copy(value);if(value.kind!=RU_STR)ru_fail(line,"无法转为数字");return v_num(ru_parse_number(value.s->data,line)); }
    if(kind==RU_STR)return v_to_string(value);
    if(kind==RU_ARRAY)return v_array(1,&value,line);
    ru_fail(line,"未知转换类型");return v_null();
}
static Val ru_finite(double n,int line) { if(!isfinite(n))ru_fail(line,"运算结果不是有限数字");return v_num(n); }
static Val v_unary(const char *op,Val v,int line)
{
    if(!strcmp(op,"非"))return v_num(!v_truth(v));
    if(!strcmp(op,"+")||!strcmp(op,"-")) { if(v.kind!=RU_NUM)ru_fail(line,"运算符 %s 需要数字",op);return ru_finite(op[0]=='-'?-v.n:v.n,line); }
    ru_fail(line,"未知一元运算符：%s",op);return v_null();
}
typedef struct { RuHeap *a, *b; } RuCompared;
static size_t ru_compare_hash(RuHeap *a, RuHeap *b)
{
    uintptr_t x = (uintptr_t)a >> 3, y = (uintptr_t)b >> 3;
    return (size_t)((x * (uintptr_t)2654435761u) ^ (y * (uintptr_t)2246822519u));
}
static int ru_compare_seen(RuCompared **table, size_t *capacity, size_t *count,
                           RuHeap *a, RuHeap *b)
{
    size_t at;
    if (*count >= *capacity / 2) {
        size_t i, cap = *capacity ? *capacity * 2 : 32;
        RuCompared *grown;
        if (cap < *capacity || cap > SIZE_MAX / sizeof(*grown)) ru_fail(0, "比较结构过大");
        grown = (RuCompared *)ru_alloc(cap * sizeof(*grown), 0);
        memset(grown, 0, cap * sizeof(*grown));
        for (i = 0; i < *capacity; ++i) {
            RuCompared entry = (*table)[i];
            if (!entry.a) continue;
            at = ru_compare_hash(entry.a, entry.b) & (cap - 1);
            while (grown[at].a) at = (at + 1) & (cap - 1);
            grown[at] = entry;
        }
        free(*table); *table = grown; *capacity = cap;
    }
    at = ru_compare_hash(a, b) & (*capacity - 1);
    while ((*table)[at].a) {
        if ((*table)[at].a == a && (*table)[at].b == b) return 1;
        at = (at + 1) & (*capacity - 1);
    }
    (*table)[at].a = a; (*table)[at].b = b; ++*count;
    return 0;
}
static int v_equal(Val a, Val b)
{
    typedef struct { Val a, b; } Compare;
    size_t used = 1, capacity = 16, seen_capacity = 0, seen_count = 0;
    Compare *stack = (Compare *)ru_alloc(capacity * sizeof(*stack), 0);
    RuCompared *seen = NULL;
    int equal = 1;
    stack[0].a = a; stack[0].b = b;
    while (used && equal) {
        Compare comparison = stack[--used]; a = comparison.a; b = comparison.b;
        if (a.kind != b.kind) { equal = 0; break; }
        if (a.kind == RU_NUM) equal = a.n == b.n;
        else if (a.kind == RU_STR) equal = !strcmp(a.s->data, b.s->data);
        else if (a.kind == RU_PAIR) {
            RuPair *pa = (RuPair *)a.heap, *pb = (RuPair *)b.heap;
            if (a.heap == b.heap || ru_compare_seen(&seen, &seen_capacity, &seen_count, a.heap, b.heap)) continue;
            if (used + 2 > capacity) {
                Compare *grown;
                if (capacity > SIZE_MAX / sizeof(*stack) / 2) ru_fail(0, "比较结构过大");
                capacity *= 2;
                grown = (Compare *)realloc(stack, capacity * sizeof(*stack));
                if (!grown) ru_fail(0, "内存不足");
                stack = grown;
            }
            stack[used].a = pa->second; stack[used++].b = pb->second;
            stack[used].a = pa->first; stack[used++].b = pb->first;
        } else if (a.kind == RU_CLASS) equal = a.klass == b.klass;
        else if (a.kind == RU_MODULE) equal = a.module == b.module;
        else if (a.kind != RU_NULL) equal = a.heap == b.heap;
    }
    free(stack); free(seen); return equal;
}
static Val v_binary(const char *op,Val a,Val b,int line)
{
    if(!strcmp(op,"对"))return v_pair(a,b,line);
    if(!strcmp(op,"且"))return v_num(v_truth(a)&&v_truth(b));
    if(!strcmp(op,"或"))return v_num(v_truth(a)||v_truth(b));
    if(!strcmp(op,"==")||!strcmp(op,"!=")) {int equal=v_equal(a,b);return v_num(!strcmp(op,"==")?equal:!equal);}
    if(!strcmp(op,"含")) { if(a.kind!=RU_STR||b.kind!=RU_STR)ru_fail(line,"含 需要两个字符串");return v_num(strstr(a.s->data,b.s->data)!=NULL); }
    if(!strcmp(op,"<")||!strcmp(op,"<=")||!strcmp(op,">")||!strcmp(op,">=")) {
        int cmp;if(a.kind!=b.kind || (a.kind!=RU_NUM&&a.kind!=RU_STR))ru_fail(line,"比较需要相同的数字或字符串类型");
        cmp=a.kind==RU_NUM?(a.n>b.n)-(a.n<b.n):strcmp(a.s->data,b.s->data);
        if (!strcmp(op,"<")) return v_num(cmp<0);
        if (!strcmp(op,"<=")) return v_num(cmp<=0);
        if (!strcmp(op,">")) return v_num(cmp>0);
        return v_num(cmp>=0);
    }
    if(!strcmp(op,"+")&&a.kind==RU_STR&&b.kind==RU_STR) {Val v;if(a.s->len>SIZE_MAX-b.s->len)ru_fail(line,"字符串过长");v=ru_string_alloc(a.s->len+b.s->len,line);memcpy(v.s->data,a.s->data,a.s->len);memcpy(v.s->data+a.s->len,b.s->data,b.s->len);return v;}
    if(!strcmp(op,"+")||!strcmp(op,"-")||!strcmp(op,"*")||!strcmp(op,"/")||!strcmp(op,"%")) {
        if(a.kind!=RU_NUM||b.kind!=RU_NUM)ru_fail(line,"运算符 %s 需要两个数字",op);
        if((op[0]=='/'||op[0]=='%')&&b.n==0)ru_fail(line,"除数不能为零");
        switch(op[0]) {case '+':return ru_finite(a.n+b.n,line);case '-':return ru_finite(a.n-b.n,line);case '*':return ru_finite(a.n*b.n,line);case '/':return ru_finite(a.n/b.n,line);case '%':return ru_finite(fmod(a.n,b.n),line);}
    }
    ru_fail(line,"未知二元运算符：%s",op);return v_null();
}
static void v_print(Val v, int line)
{
    Val text = v_to_string(v);
    int failed = fputs(text.s->data, stdout) == EOF || fputc('\n', stdout) == EOF || fflush(stdout) == EOF;
    v_drop(text);
    if (failed) ru_fail(line, "输出失败");
}
static uint64_t v_count(Val v,int line)
{
    if(v.kind!=RU_NUM||!isfinite(v.n)||v.n<0||v.n>9007199254740991.0||floor(v.n)!=v.n)ru_fail(line,"重复次数须为 0 至 9007199254740991 的整数");
    return (uint64_t)v.n;
}
static size_t ru_index(Val v,size_t max,int endpoint,int line)
{
    if(v.kind!=RU_NUM||!isfinite(v.n)||v.n<0||v.n>9007199254740991.0||floor(v.n)!=v.n)ru_fail(line,"索引须为非负整数");
    if(v.n>(double)max||(!endpoint&&v.n==(double)max))ru_fail(line,"索引越界");
    return (size_t)v.n;
}
static size_t ru_utf8_len(Val v) {size_t i,n=0;for(i=0;i<v.s->len;++i)if(((unsigned char)v.s->data[i]&0xc0)!=0x80)++n;return n;}
static size_t ru_utf8_offset(Val v,size_t at) {size_t i,n=0;for(i=0;i<v.s->len;++i)if(((unsigned char)v.s->data[i]&0xc0)!=0x80){if(n++==at)return i;}return v.s->len;}
static size_t v_length(Val v,int line) {if(v.kind==RU_STR)return ru_utf8_len(v);if(v.kind==RU_ARRAY)return ((RuArray *)v.heap)->len;ru_fail(line,"量／索引需要阵或句");return 0;}
static Val v_index(Val v,Val index,int line)
{
    size_t i=ru_index(index,v_length(v,line),0,line);
    if(v.kind==RU_ARRAY)return v_copy(((RuArray *)v.heap)->items[i]);
    {size_t a=ru_utf8_offset(v,i),b=ru_utf8_offset(v,i+1);Val out=ru_string_alloc(b-a,line);memcpy(out.s->data,v.s->data+a,b-a);return out;}
}
static Val v_slice(Val v,Val start,Val end,int line)
{
    size_t len=v_length(v,line),a=start.kind==RU_NULL?0:ru_index(start,len,1,line),b=end.kind==RU_NULL?len:ru_index(end,len,1,line);
    if(a>b)ru_fail(line,"切片开始不能大于结束");
    if(v.kind==RU_ARRAY)return v_array(b-a,((RuArray *)v.heap)->items+a,line);
    {Val out;a=ru_utf8_offset(v,a);b=ru_utf8_offset(v,b);out=ru_string_alloc(b-a,line);memcpy(out.s->data,v.s->data+a,b-a);return out;}
}
static void v_check_index_target(Val v, Val index, int line)
{
    if (v.kind != RU_ARRAY) ru_fail(line, "只能修改阵的索引");
    (void)ru_index(index, ((RuArray *)v.heap)->len, 0, line);
}
static void v_set_index(Val v, Val index, Val value, int line)
{
    size_t at;
    v_check_index_target(v, index, line);
    at = ru_index(index, ((RuArray *)v.heap)->len, 0, line);
    ((RuArray *)v.heap)->items[at] = value;
}
static Val v_append(Val v,Val value,int line)
{
    RuArray *a;Val *items;size_t cap;
    if(v.kind!=RU_ARRAY)ru_fail(line,"增 需要阵");
    a=(RuArray *)v.heap;
    if(a->len==a->capacity) {if(a->capacity>(SIZE_MAX/sizeof(Val)-1)/2)ru_fail(line,"阵过长");cap=a->capacity?a->capacity*2:4;items=(Val *)realloc(a->items,cap*sizeof(Val));if(!items)ru_fail(line,"内存不足");a->items=items;a->capacity=cap;}
    a->items[a->len++]=value;return v_copy(v);
}
static size_t ru_field_count(RuClass *klass) {size_t n=0;for(;klass;klass=klass->parent)n+=klass->count;return n;}
static int ru_find_field(RuClass *klass, const char *name, size_t *index,
                         const char **type, Env **owner)
{
    for (; klass; klass = klass->parent) {
        size_t i, base = klass->parent ? ru_field_count(klass->parent) : 0;
        for (i = 0; i < klass->count; ++i) {
            if (!strcmp(klass->names[i], name)) {
                *index = base + i; *type = klass->types[i]; *owner = klass->global;
                return 1;
            }
        }
    }
    return 0;
}
static void ru_class_ready(RuClass *klass, int line)
{
    for (; klass && klass->parent; klass = klass->parent) {
        RuBinding *parent = env_find(klass->global, klass->parent->name);
        if (!parent || parent->value.kind != RU_CLASS || parent->value.klass != klass->parent)
            ru_fail(line, "未定义父形：%s", klass->parent->name);
    }
}
static int v_is_type(Val v,const char *type,Env *env)
{
    size_t type_len = strlen(type);
    if (!type_len) return 1;
    const char *suffix = type_len >= 4 ? type + type_len - 4 : NULL;
    if(suffix && !strcmp(suffix," 阵")) {size_t i,len=(size_t)(suffix-type);char *item;RuArray *a;int good=1;if(v.kind!=RU_ARRAY)return 0;item=(char *)ru_alloc(len+1,0);memcpy(item,type,len);item[len]=0;a=(RuArray *)v.heap;for(i=0;i<a->len&&good;++i)good=v_is_type(a->items[i],item,env);free(item);return good;}
    if(!strcmp(type,"数"))return v.kind==RU_NUM;
    if(!strcmp(type,"句"))return v.kind==RU_STR;
    if(!strcmp(type,"空"))return v.kind==RU_NULL;
    if(!strcmp(type,"对"))return v.kind==RU_PAIR;
    if(!strcmp(type,"阵"))return v.kind==RU_ARRAY;
    {RuBinding *b=env_find(env,type);RuClass *klass;if(!b||b->value.kind!=RU_CLASS||v.kind!=RU_OBJECT)return 0;for(klass=((RuObject *)v.heap)->klass;klass;klass=klass->parent)if(klass==b->value.klass)return 1;}
    return 0;
}
static void v_check_member_target(Val receiver, const char *name, int line)
{
    size_t index;
    const char *type;
    Env *owner;
    if (receiver.kind != RU_OBJECT) ru_fail(line, "只能修改对象字段");
    if (!ru_find_field(((RuObject *)receiver.heap)->klass, name, &index, &type, &owner))
        ru_fail(line, "未知字段：%s", name);
}
static void v_set_member(Val receiver,const char *name,Val value,int line)
{
    size_t index;const char *type;Env *owner;RuObject *o;
    if(receiver.kind!=RU_OBJECT)ru_fail(line,"只能修改对象字段");
    o=(RuObject *)receiver.heap;
    if(!ru_find_field(o->klass,name,&index,&type,&owner))ru_fail(line,"未知字段：%s",name);
    if(value.kind!=RU_NULL&&!v_is_type(value,type,owner))ru_fail(line,"字段「%s」须为%s",name,type);
    o->fields[index]=value;
}
static Val v_class(RuClass *klass) {Val v=v_null();v.kind=RU_CLASS;v.klass=klass;return v;}
static Val v_module(Env *env) {Val v=v_null();v.kind=RU_MODULE;v.module=env;return v;}
static Val v_function(RuFunction *function,Env *global,Val self)
{
    Val v=v_null();RuCallable *f=(RuCallable *)ru_new_heap(sizeof(*f),RU_FUNCTION,0);v.kind=RU_FUNCTION;v.heap=&f->gc;f->function=function;f->global=global;f->self=self;return v;
}
static Val v_new(Val class_value,size_t argc,const char **keys,Val *args,int line)
{
    RuClass *klass;RuObject *o;Val v=v_null();size_t i,j;
    if(class_value.kind!=RU_CLASS)ru_fail(line,"新 需要形名称");
    klass=class_value.klass; ru_class_ready(klass,line);
    o=(RuObject *)ru_new_heap(sizeof(*o),RU_OBJECT,line);v.kind=RU_OBJECT;v.heap=&o->gc;o->klass=klass;o->len=ru_field_count(klass);
    o->fields=(Val *)ru_alloc(o->len*sizeof(Val),line);for(i=0;i<o->len;++i)o->fields[i]=v_null();
    ru_io_defaults(v, line);
    for(i=0;i<argc;++i){if(!keys[i])ru_fail(line,"新 的字段必须使用命名实参");for(j=0;j<i;++j)if(!strcmp(keys[i],keys[j]))ru_fail(line,"重复的实参：%s",keys[i]);v_set_member(v,keys[i],args[i],line);}
    return v;
}
static void ru_enter(int line) {if(ru_call_depth>=128)ru_fail(line,"函数调用深度超过 128");++ru_call_depth;}
static void ru_leave(void) {if(ru_call_depth)--ru_call_depth;}
static void ru_bind(const char *name,size_t count,const char **names,size_t argc,const char **keys,Val *args,Val *bound,int line)
{
    size_t i,j;unsigned char *seen=(unsigned char *)ru_scratch_alloc(count?count:1,line);int positional=argc&&keys[0]==NULL;
    memset(seen,0,count);
    if(positional&&argc!=count)ru_fail(line,"函数「%s」需要 %zu 个位置实参，收到 %zu 个",name,count,argc);
    for(i=0;i<argc;++i){if((keys[i]==NULL)!=positional)ru_fail(line,"同一次调用不能混用位置实参与命名实参");j=i;if(!positional){for(j=0;j<count;++j)if(!strcmp(names[j],keys[i]))break;if(j==count)ru_fail(line,"函数「%s」未知实参「%s」",name,keys[i]);}if(seen[j])ru_fail(line,"重复的实参：%s",names[j]);seen[j]=1;bound[j]=args[i];}
    for(i=0;i<count;++i)if(!seen[i])ru_fail(line,"函数「%s」缺少「%s」",name,names[i]);
    ru_scratch_free(seen);
}
static Val v_call(Val callable,size_t argc,const char **keys,Val *args,int line)
{
    RuCallable *f;RuFunction *fn;Val *bound,result;size_t i;
    if(callable.kind!=RU_FUNCTION)ru_fail(line,"值不是函数");
    f=(RuCallable *)callable.heap;fn=f->function;
    bound=(Val *)ru_scratch_alloc((fn->count?fn->count:1)*sizeof(Val),line);ru_bind(fn->name,fn->count,fn->names,argc,keys,args,bound,line);
    for(i=0;i<fn->count;++i)if(!v_is_type(bound[i],fn->types[i],f->global))ru_fail(line,"实参「%s」须为%s，请显式使用「为 %s」转换",fn->names[i],fn->types[i],fn->types[i]);
    ru_enter(line);result=fn->code(f->global,f->self,line,bound);ru_leave();ru_scratch_free(bound);return result;
}
static Val v_member(Val receiver,const char *name,size_t argc,const char **keys,Val *args,int line)
{
    const char *one[]={"值"},*position[]={"位"},*range[]={"始","终"};Val bound[2], io_result;
    if (ru_io_member(receiver, name, argc, keys, args, line, &io_result)) return io_result;
    if(receiver.kind==RU_MODULE){Val value=env_get(receiver.module,name,line),result;if(value.kind==RU_FUNCTION){result=v_call(value,argc,keys,args,line);v_drop(value);return result;}if(argc)ru_fail(line,"成员不是函数：%s",name);return value;}
    if(receiver.kind==RU_OBJECT){RuObject *o=(RuObject *)receiver.heap;size_t index,i;const char *type;Env *owner;RuClass *klass;
        if(ru_find_field(o->klass,name,&index,&type,&owner)){if(argc)ru_fail(line,"字段不是方法：%s",name);return v_copy(o->fields[index]);}
        for(klass=o->klass;klass;klass=klass->parent)for(i=0;i<klass->methods_count;++i)if(!strcmp(klass->methods[i]->name,name)){Val method=v_function(klass->methods[i],klass->global,receiver),result=v_call(method,argc,keys,args,line);v_drop(method);return result;}
        ru_fail(line,"未知成员：%s",name);
    }
    if(receiver.kind==RU_PAIR&&(!strcmp(name,"囫")||!strcmp(name,"囵"))){if(argc)ru_fail(line,"对的成员不接收实参");return v_copy(!strcmp(name,"囫")?((RuPair *)receiver.heap)->first:((RuPair *)receiver.heap)->second);}
    if(!strcmp(name,"量")){if(argc)ru_fail(line,"量不接收实参");return v_num((double)v_length(receiver,line));}
    if(!strcmp(name,"位")){ru_bind(name,1,position,argc,keys,args,bound,line);return v_index(receiver,bound[0],line);}
    if(!strcmp(name,"段")){ru_bind(name,2,range,argc,keys,args,bound,line);return v_slice(receiver,bound[0],bound[1],line);}
    if(!strcmp(name,"增")){ru_bind(name,1,one,argc,keys,args,bound,line);return v_append(receiver,bound[0],line);}
    if(!strcmp(name,"含")){const char *text[]={"句"};ru_bind(name,1,text,argc,keys,args,bound,line);return v_binary("含",receiver,bound[0],line);}
    ru_fail(line,"未知成员：%s",name);return v_null();
}
static void env_import_all(Env *env,Val module,int line)
{
    RuBinding *b;
    if(module.kind!=RU_MODULE)ru_fail(line,"尽 取 需要外言");
    for(b=module.module->bindings;b;b=b->next)
        if(env_find(env,b->name)||!strcmp(b->name,"读"))ru_fail(line,"导入名称冲突：%s",b->name);
    for(b=module.module->bindings;b;b=b->next) {
        if(b->reserved)env_declare(env,b->name,b->value);
        else env_set(env,b->name,b->value);
    }
}
Val read_input(Val prompt, int line)
{
    size_t len = 0;
    size_t capacity = 128;
    char *buffer;
    int ch;
    Val result;
    if (prompt.kind != 1) ru_fail(line, "输入提示须为字符串");
    if (fputs(prompt.s->data, stdout) == EOF || fflush(stdout) == EOF)
        ru_fail(line, "输出失败");
    buffer = (char *)ru_alloc(capacity, line);
    while ((ch = fgetc(stdin)) != EOF && ch != '\n') {
        if (ch == 0) {
            free(buffer);
            ru_fail(line, "输入不能含空字符");
        }
        if (len == capacity - 1) {
            char *grown;
            if (capacity > SIZE_MAX / 2) {
                free(buffer);
                ru_fail(line, "输入过长");
            }
            capacity *= 2;
            grown = (char *)realloc(buffer, capacity);
            if (!grown) {
                free(buffer);
                ru_fail(line, "内存不足");
            }
            buffer = grown;
        }
        buffer[len++] = (char)ch;
    }
    if (ferror(stdin)) {
        free(buffer);
        ru_fail(line, "读取输入失败");
    }
    if (ch == EOF && len == 0) {
        free(buffer);
        ru_fail(line, "输入结束（EOF）");
    }
    if (len > 0 && buffer[len - 1] == '\r') len--;
    if (!ru_valid_utf8(buffer, len)) {
        free(buffer);
        ru_fail(line, "输入不是有效的 UTF-8");
    }
    result = ru_string_alloc(len, line);
    memcpy(result.s->data, buffer, len);
    free(buffer);
    return result;
}


#endif
