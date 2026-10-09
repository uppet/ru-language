#ifndef RU_RUNTIME_H
#define RU_RUNTIME_H
#ifndef _WIN32
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#endif
/* Standalone C99 with precise tracing of rooted values and container edges. */
#include <math.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#include <windows.h>
static UINT ru_input_cp, ru_output_cp;
#endif

enum { RU_NUM, RU_FACT, RU_MAP, RU_STR, RU_NULL, RU_PAIR, RU_ARRAY, RU_OBJECT, RU_FUNCTION, RU_CLASS, RU_MODULE, RU_ENV };
typedef struct RuHeap RuHeap;
typedef struct RuString RuString;
typedef struct RuClass RuClass;
typedef struct Env Env;
typedef struct Val { int kind; double n; RuString *s; RuHeap *heap; RuClass *klass; Env *module; } Val;
struct RuHeap { size_t roots; unsigned mark; int kind; RuHeap *next; };
struct RuString { RuHeap gc; size_t len; char data[]; };
/* RU_MAP */
typedef struct { Val key, value; uint64_t hash; unsigned state; } RuMapEntry;
typedef struct { RuHeap gc; size_t len, used, capacity; uint64_t version; RuMapEntry *entries; } RuMap;
/* RU_END_MAP */
typedef struct { RuHeap gc; Val first, second; } RuPair;
typedef struct { RuHeap gc; size_t len, capacity; Val *items; } RuArray;
typedef struct { RuHeap gc; RuClass *klass; size_t len; Val *fields; } RuObject;
typedef Val (*RuCode)(Env *, Val, int, Val *);
typedef struct { const char *name; size_t count; const char **names, **types; RuCode code; int procedure; } RuFunction;
typedef struct { RuHeap gc; RuFunction *function; Env *global, *closure; Val self; } RuCallable;
struct RuClass { const char *name; RuClass *parent; Env *global; size_t count; const char **names, **types; size_t methods_count; RuFunction **methods; };
typedef struct RuBinding { char *name; Val value; int reserved; struct RuBinding *next; } RuBinding;
enum { RU_SCOPE_MODULE, RU_SCOPE_FUNCTION, RU_SCOPE_RESCUE, RU_SCOPE_BLOCK };
struct Env { RuHeap gc; Env *parent; RuBinding *bindings; Env *registry_next; int managed, scope; };

/* Diagnostics describe runtime values, never a hypothetical conversion. */
static const char *v_type_name(Val value)
{
    switch (value.kind) {
    case RU_NUM: return "数";
    case RU_FACT: return "事实";
    case RU_MAP: return "典";
    case RU_STR: return "句";
    case RU_NULL: return "空";
    case RU_PAIR: return "对";
    case RU_ARRAY: return "阵";
    case RU_OBJECT: return ((RuObject *)value.heap)->klass->name;
    case RU_FUNCTION: return ((RuCallable *)value.heap)->function->procedure ? "作" : "算";
    case RU_CLASS: return "形声明";
    case RU_MODULE: return "外言";
    default: return "未知";
    }
}

static const char *ru_source = "<程序>";
/* RU_FEATURE: callable */
static unsigned ru_call_depth;
/* RU_ELSE_FEATURE */
/* RU_END_FEATURE */
/* RU_FEATURE: panic */
/* Explicit panic state crosses native calls without nonlocal jumps. Each
 * generated caller checks this flag and drops its live owned temporaries.
 * The rooted reason survives environment teardown and collection. */
/* RU_ELSE_FEATURE */
/* RU_END_FEATURE */
/* RU_FEATURE: panic_state */
static int ru_panicking;
/* RU_ELSE_FEATURE */
/* RU_END_FEATURE */
/* RU_FEATURE: panic */
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
/* RU_ELSE_FEATURE */
/* RU_END_FEATURE */
static RuHeap *ru_heap;
static Env *ru_envs;
typedef struct RuScratch { void *data; struct RuScratch *next; } RuScratch;
static RuScratch *ru_scratch;
static size_t ru_live, ru_freed, ru_collections, ru_threshold = 256, ru_next_gc = 256;
static int ru_initialized, ru_finished, ru_failed, ru_gc_explicit;
static void ru_shutdown(void);
static void env_free(Env *env);
static void ru_heap_dispose(RuHeap *heap);
static void ru_io_defaults(Val value, int line);
static int ru_io_member(Val receiver, const char *name, size_t argc, const char **keys,
                        Val *args, int line, Val *out);
static int ru_contest_member(Val receiver, const char *name, size_t argc, const char **keys,
                            Val *args, int line, Val *out);
static int ru_practical_member(Val receiver, const char *name, size_t argc, const char **keys,
                              Val *args, int line, Val *out);
static void ru_fail(int line, const char *format, ...)
{
    va_list args;
    fprintf(stderr, "%s:%d: 运行错误：", ru_source ? ru_source : "<程序>", line);
    va_start(args, format); vfprintf(stderr, format, args); va_end(args);
    fputc('\n', stderr); ru_failed=1; ru_shutdown(); exit(1);
}
static void *ru_alloc(size_t size, int line)
{
    void *p = malloc(size ? size : 1);
    if (!p) ru_fail(line, "内存不足");
    return p;
}
/* Track argument-binding buffers for cleanup on fatal diagnostics. */
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
static Val v_fact(int n) { Val v = {0}; v.kind = RU_FACT; v.n = !!n; return v; }
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
/* Iterative marking visits each node once without recursive stack growth. */
static void ru_gc(void)
{
    RuHeap *h, **slot, **todo;
    size_t used = 0, at = 0, work = 0, budget;
    ++ru_collections;
    todo = (RuHeap **)ru_alloc((ru_live ? ru_live : 1) * sizeof(*todo), 0);
    for (h = ru_heap; h; h = h->next) {
        h->mark = h->roots != 0;
        if (h->mark) todo[used++] = h;
    }
#define RU_MARK_HEAP(ptr) do { RuHeap *child_ = (ptr); if (child_ && !child_->mark) { child_->mark=1; todo[used++]=child_; } } while (0)
#define RU_MARK(v) RU_MARK_HEAP((v).heap)
#define RU_MARK_ENV(e) RU_MARK_HEAP((e) && (e)->managed ? &(e)->gc : NULL)
#define RU_GC_WORK(n) do { size_t amount_ = (n); work = amount_ > SIZE_MAX - work ? SIZE_MAX : work + amount_; } while (0)
    while (at < used) {
        h = todo[at++];
        RU_GC_WORK(1);
        if (0) {}
/* RU_FEATURE: pair */
        else if (h->kind == RU_PAIR) { RuPair *p=(RuPair *)h; RU_GC_WORK(2); RU_MARK(p->first); RU_MARK(p->second); }
/* RU_ELSE_FEATURE */
/* RU_END_FEATURE */
/* RU_FEATURE: array */
        else if (h->kind == RU_ARRAY) { RuArray *a=(RuArray *)h; size_t i; RU_GC_WORK(a->len); for(i=0;i<a->len;++i) RU_MARK(a->items[i]); }
/* RU_ELSE_FEATURE */
/* RU_END_FEATURE */
        /* RU_FEATURE: map */
        else if (h->kind == RU_MAP) { RuMap *m=(RuMap *)h; size_t i; RU_GC_WORK(m->capacity); for(i=0;i<m->capacity;++i) if(m->entries[i].state==1) { RU_MARK(m->entries[i].key); RU_MARK(m->entries[i].value); } }
/* RU_ELSE_FEATURE */
/* RU_END_FEATURE */
        else if (h->kind == RU_OBJECT) { RuObject *o=(RuObject *)h; size_t i; RU_GC_WORK(o->len); for(i=0;i<o->len;++i) RU_MARK(o->fields[i]); }
        else if (h->kind == RU_FUNCTION) { RuCallable *f=(RuCallable *)h; RU_GC_WORK(2); RU_MARK(f->self); RU_MARK_ENV(f->closure); }
        else if (h->kind == RU_ENV) {
            Env *env=(Env *)h; RuBinding *binding;
            RU_GC_WORK(1); RU_MARK_ENV(env->parent);
            for(binding=env->bindings;binding;binding=binding->next) { RU_GC_WORK(1); RU_MARK(binding->value); }
        }
    }
#undef RU_GC_WORK
#undef RU_MARK_ENV
#undef RU_MARK
#undef RU_MARK_HEAP
    free(todo);
    slot = &ru_heap;
    while ((h = *slot)) {
        if (h->mark) { slot = &h->next; continue; }
        *slot = h->next;
        ru_heap_dispose(h); --ru_live; ++ru_freed;
    }
    /* Scale default GC work to the reachable graph: callback call frames
     * otherwise cause quadratic rescans. Explicit stress budgets stay fixed. */
    budget = ru_threshold;
    if (!ru_gc_explicit && work / 16 > budget) budget = work / 16;
    ru_next_gc = ru_live > SIZE_MAX - budget ? SIZE_MAX : ru_live + budget;
}
static void ru_init(void)
{
    const char *text;
    if (ru_initialized) return;
    ru_initialized=1;
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
    _setmode(_fileno(stderr), _O_BINARY);
    ru_input_cp = GetConsoleCP(); ru_output_cp = GetConsoleOutputCP();
    if (ru_input_cp) SetConsoleCP(CP_UTF8);
    if (ru_output_cp) SetConsoleOutputCP(CP_UTF8);
#endif
    text=getenv("RU_GC_THRESHOLD");
    if (text && *text) { char *end; unsigned long n=strtoul(text,&end,10); if (!*end && n>0 && n<=100000000) { ru_threshold=(size_t)n; ru_gc_explicit=1; } }
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
    return v.kind != RU_NULL && (v.kind != RU_FACT || v.n != 0);
}
/* Module bindings own roots; lexical edges preserve escaped captures. */
static void env_init(Env *env, Env *parent)
{
    memset(env, 0, sizeof(*env)); env->parent=parent;
    env->registry_next=ru_envs; ru_envs=env;
}
static Env *env_new(Env *parent, int scope, int line)
{
    Env *env=(Env *)ru_new_heap(sizeof(*env), RU_ENV, line);
    env->parent=parent; env->managed=1; env->scope=scope;
    return env;
}
static RuBinding *env_find_local(Env *env,const char *name)
{
    RuBinding *binding;
    for(binding=env->bindings;binding;binding=binding->next)
        if(!strcmp(binding->name,name)) return binding;
    return NULL;
}
static RuBinding *env_find(Env *env,const char *name)
{
    for(;env;env=env->parent) { RuBinding *binding=env_find_local(env,name); if(binding)return binding; }
    return NULL;
}
static Val env_get(Env *env,const char *name,int line)
{ RuBinding *b=env_find(env,name); if(!b) ru_fail(line,"未定义变量：%s",name); return v_copy(b->value); }
static Val ru_ordinary_value(Val value, int line)
{
/* RU_FEATURE: user_class */
    if(value.kind==RU_CLASS)
        ru_fail(line,"形名「%s」不能作为普通值；创建实例请用「新 %s」，类型注解请直接使用形名",value.klass->name,value.klass->name);
/* RU_ELSE_FEATURE */
    (void)line;
/* RU_END_FEATURE */
    return value;
}
static void env_set(Env *env,const char *name,Val value)
{
    RuBinding *b; Val owned=env->managed ? value : v_copy(value);
    for(b=env->bindings;b;b=b->next) if(!strcmp(b->name,name)) {
        if(!env->managed) v_drop(b->value);
        b->value=owned; return;
    }
    b=(RuBinding *)ru_alloc(sizeof(*b),0); b->name=(char *)ru_alloc(strlen(name)+1,0); strcpy(b->name,name);
    b->value=owned; b->reserved=0; b->next=env->bindings; env->bindings=b;
}
static void env_declare(Env *env, const char *name, Val value)
{
    env_set(env, name, value);
    env_find_local(env, name)->reserved = 1;
}
static void env_bind(Env *env, const char *name, Val value, int line)
{
    RuBinding *existing = env_find(env, name);
    Env *target=env, *outer;
    if (!strcmp(name, "读") || (existing && existing->reserved))
        ru_fail(line, "变量名不能与函数名、形名或内置名称重名");
    /* Blocks and rescue shadow; functions update captured lexical bindings, not globals. */
    if(env->scope==RU_SCOPE_FUNCTION && !env_find_local(env,name)) {
        for(outer=env->parent;outer && outer->managed;outer=outer->parent)
            if(env_find_local(outer,name)) { target=outer; break; }
    }
    env_set(target, name, value);
}
static void env_free(Env *env)
{
    Env **slot; RuBinding *b;
    if(env->managed) {
        if(!env->gc.roots) ru_fail(0,"内部错误：环境根计数失衡");
        --env->gc.roots; return;
    }
    slot=&ru_envs; b=env->bindings;
    while(*slot && *slot!=env) slot=&(*slot)->registry_next;
    if(*slot) *slot=env->registry_next;
    while(b) { RuBinding *next=b->next; v_drop(b->value); free(b->name); free(b); b=next; }
    env->bindings=NULL; env->parent=NULL;
}
static void ru_heap_dispose(RuHeap *heap)
{
    if(0) {}
/* RU_MAP */
    else if(heap->kind==RU_MAP) free(((RuMap *)heap)->entries);
/* RU_END_MAP */
    else if(heap->kind==RU_ARRAY) free(((RuArray *)heap)->items);
    else if(heap->kind==RU_OBJECT) free(((RuObject *)heap)->fields);
    else if(heap->kind==RU_ENV) {
        RuBinding *binding=((Env *)heap)->bindings;
        while(binding) { RuBinding *next=binding->next; free(binding->name); free(binding); binding=next; }
    }
    free(heap);
}
static void ru_shutdown(void)
{
    RuHeap *h;
    if(ru_finished) return;
    ru_finished=1;
/* RU_FEATURE: panic */
    ru_panic_clear();
    while(ru_module_failures) {
        RuModuleFailure *failure = ru_module_failures;
        ru_module_failures = failure->next;
        v_drop(failure->reason); failure->reason = v_null();
    }
/* RU_ELSE_FEATURE */
/* RU_END_FEATURE */
    while(ru_envs) env_free(ru_envs);
    while(ru_scratch) ru_scratch_free(ru_scratch->data);
    /* Fatal exit invalidates roots still held by native frames. */
    if(ru_failed) for(h=ru_heap;h;h=h->next) h->roots=0;
    ru_gc();
    if(getenv("RU_GC_STATS")) fprintf(stderr,"RU_GC live=%zu freed=%zu collections=%zu\n",ru_live,ru_freed,ru_collections);
    /* Dispose of remaining temporaries on process exit. */
    while((h=ru_heap)) { ru_heap=h->next; ru_heap_dispose(h); }
    ru_live=0;
#ifdef _WIN32
    fflush(stdout); fflush(stderr);
    if (ru_input_cp) SetConsoleCP(ru_input_cp);
    if (ru_output_cp) SetConsoleOutputCP(ru_output_cp);
#endif
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

/* Parse separator-terminated spans without allocating a token. */
static double ru_parse_number_span(const char *text, size_t length, int line)
{
    const char *start = text;
    const char *end = text + length;
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
    /* C locale; grammar above excludes hex, infinity and NaN. */
    result = strtod(start, &parsed_end);
    if (parsed_end != end || !isfinite(result))
        ru_fail(line, "无法转为有限数字");
    return result;
}
static double ru_parse_number(const char *text, int line)
{
    return ru_parse_number_span(text, strlen(text), line);
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
/* RU_FEATURE: container */
typedef struct { int action; Val value; const char *text; unsigned old_mark; } RuFormatStep;
/* RU_ELSE_FEATURE */
/* RU_END_FEATURE */
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
/* RU_FEATURE: container */
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
        else if (v.kind == RU_FACT) ru_text_word(out, v.n ? "真" : "假");
        else if (v.kind == RU_STR) ru_text_add(out, v.s->data, v.s->len);
        else if (v.kind == RU_NULL) ru_text_word(out, "空");
        else if (v.kind == RU_OBJECT || v.kind == RU_CLASS) {
            ru_text_word(out, "<形 ");
            ru_text_word(out, v.kind == RU_CLASS ? v.klass->name : ((RuObject *)v.heap)->klass->name);
            ru_text_word(out, ">");
        } else if (v.kind == RU_MODULE) ru_text_word(out, "<外言>");
        else if (v.kind == RU_FUNCTION) {
            ru_text_word(out, ((RuCallable *)v.heap)->function->procedure ? "<作 " : "<算 ");
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
            }
/* RU_MAP */
            else if (v.kind == RU_MAP) {
                RuMap *map = (RuMap *)v.heap; size_t count = 0;
                RU_PUSH(1, v_null(), "}", 0);
                for (i=map->capacity;i>0;--i) if(map->entries[i-1].state==1) {
                    if(count++) RU_PUSH(1,v_null(),", ",0);
                    RU_PUSH(0,map->entries[i-1].value,NULL,0);
                    RU_PUSH(1,v_null(),": ",0);
                    RU_PUSH(0,map->entries[i-1].key,NULL,0);
                }
                ru_text_word(out,"{");
            }
/* RU_END_MAP */
            else if (v.kind == RU_ARRAY) {
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
/* RU_ELSE_FEATURE */
/* No array/pair constructor is reachable; there is no recursive value to walk. */
static void ru_format(RuText *out, Val v)
{
    char buffer[64];
    if (v.kind == RU_NUM) { snprintf(buffer, sizeof(buffer), "%.15g", v.n); ru_text_word(out, buffer); }
    else if (v.kind == RU_FACT) ru_text_word(out, v.n ? "真" : "假");
    else if (v.kind == RU_STR) ru_text_add(out, v.s->data, v.s->len);
    else if (v.kind == RU_NULL) ru_text_word(out, "空");
    else if (v.kind == RU_OBJECT || v.kind == RU_CLASS) {
        ru_text_word(out, "<形 ");
        ru_text_word(out, v.kind == RU_CLASS ? v.klass->name : ((RuObject *)v.heap)->klass->name);
        ru_text_word(out, ">");
    } else if (v.kind == RU_MODULE) ru_text_word(out, "<外言>");
    else if (v.kind == RU_FUNCTION) {
        ru_text_word(out, ((RuCallable *)v.heap)->function->procedure ? "<作 " : "<算 ");
        ru_text_word(out, ((RuCallable *)v.heap)->function->name);
        ru_text_word(out, ">");
    }
}
/* RU_END_FEATURE */
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
    if(kind==RU_FACT)return v_fact(v_truth(value));
    if(kind==RU_NUM) { if(value.kind==RU_NUM)return v_copy(value);if(value.kind!=RU_STR)ru_fail(line,"无法转为数字");return v_num(ru_parse_number(value.s->data,line)); }
    if(kind==RU_STR)return v_to_string(value);
    if(kind==RU_ARRAY)return v_array(1,&value,line);
    ru_fail(line,"未知转换类型");return v_null();
}
static Val ru_finite(double n,int line) { if(!isfinite(n))ru_fail(line,"运算结果不是有限数字");return v_num(n); }
static Val v_unary(const char *op,Val v,int line)
{
    if(!strcmp(op,"非"))return v_fact(!v_truth(v));
    if(!strcmp(op,"+")||!strcmp(op,"-")) { if(v.kind!=RU_NUM)ru_fail(line,"运算符 %s 需要数字",op);return ru_finite(op[0]=='-'?-v.n:v.n,line); }
    ru_fail(line,"未知一元运算符：%s",op);return v_null();
}
/* RU_FEATURE: pair */
typedef struct { RuHeap *a, *b; } RuCompared;
/* RU_ELSE_FEATURE */
/* RU_END_FEATURE */
static int ru_object_equal(Val a, Val b, int line);
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
/* RU_FEATURE: pair */
static int v_equal(Val a, Val b, int line)
{
    (void)ru_panicking;
    typedef struct { Val a, b; } Compare;
    size_t used = 1, capacity = 16, seen_capacity = 0, seen_count = 0;
    Compare *stack = (Compare *)ru_alloc(capacity * sizeof(*stack), 0);
    RuCompared *seen = NULL;
    int equal = 1;
    stack[0].a = a; stack[0].b = b;
    while (used && equal && !ru_panicking) {
        Compare comparison = stack[--used]; a = comparison.a; b = comparison.b;
        if (a.kind != b.kind) { equal = 0; break; }
        if (a.kind == RU_NUM || a.kind == RU_FACT) equal = a.n == b.n;
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
        } else if (a.kind == RU_OBJECT) equal = ru_object_equal(a,b,line);
        else if (a.kind == RU_CLASS) equal = a.klass == b.klass;
        else if (a.kind == RU_MODULE) equal = a.module == b.module;
        else if (a.kind != RU_NULL) equal = a.heap == b.heap;
    }
    free(stack); free(seen); return equal;
}
/* RU_ELSE_FEATURE */
/* No pair constructor is reachable: equality is shallow for every live kind. */
static int v_equal(Val a, Val b, int line)
{
    (void)ru_panicking;
    if (a.kind != b.kind) return 0;
    if (a.kind == RU_NUM || a.kind == RU_FACT) return a.n == b.n;
    if (a.kind == RU_STR) return !strcmp(a.s->data, b.s->data);
    if (a.kind == RU_OBJECT) return ru_object_equal(a,b,line);
    if (a.kind == RU_CLASS) return a.klass == b.klass;
    if (a.kind == RU_MODULE) return a.module == b.module;
    return a.kind == RU_NULL || a.heap == b.heap;
}
/* RU_END_FEATURE */
static Val v_binary(const char *op,Val a,Val b,int line)
{
/* RU_OPERATORS: 对 */
    if(!strcmp(op,"对"))return v_pair(a,b,line);
/* RU_END_MEMBERS */
/* RU_OPERATORS: 且 */
    if(!strcmp(op,"且"))return v_fact(v_truth(a)&&v_truth(b));
/* RU_END_MEMBERS */
/* RU_OPERATORS: 或 */
    if(!strcmp(op,"或"))return v_fact(v_truth(a)||v_truth(b));
/* RU_END_MEMBERS */
    if(!strcmp(op,"==")||!strcmp(op,"!=")) {int equal=v_equal(a,b,line);return v_fact(!strcmp(op,"==")?equal:!equal);}
/* RU_OPERATORS: 含 */
    if(!strcmp(op,"含")) { if(a.kind!=RU_STR||b.kind!=RU_STR)ru_fail(line,"含 需要两个字符串");return v_fact(strstr(a.s->data,b.s->data)!=NULL); }
/* RU_END_MEMBERS */
    if(!strcmp(op,"<")||!strcmp(op,"<=")||!strcmp(op,">")||!strcmp(op,">=")) {
        int cmp;if(a.kind!=b.kind || (a.kind!=RU_NUM&&a.kind!=RU_STR))ru_fail(line,"比较需要相同的数字或字符串类型%s",(a.kind==RU_FACT||b.kind==RU_FACT)?"；比较结果为事实，若要连续比较，请拆成两个比较并用「且」连接":"");
        cmp=a.kind==RU_NUM?(a.n>b.n)-(a.n<b.n):strcmp(a.s->data,b.s->data);
        if (!strcmp(op,"<")) return v_fact(cmp<0);
        if (!strcmp(op,"<=")) return v_fact(cmp<=0);
        if (!strcmp(op,">")) return v_fact(cmp>0);
        return v_fact(cmp>=0);
    }
    if(!strcmp(op,"+")&&a.kind==RU_STR&&b.kind==RU_STR) {Val v;if(a.s->len>SIZE_MAX-b.s->len)ru_fail(line,"字符串过长");v=ru_string_alloc(a.s->len+b.s->len,line);memcpy(v.s->data,a.s->data,a.s->len);memcpy(v.s->data+a.s->len,b.s->data,b.s->len);return v;}
    if(!strcmp(op,"+")||!strcmp(op,"-")||!strcmp(op,"*")||!strcmp(op,"/")||!strcmp(op,"%")) {
        if(a.kind!=RU_NUM||b.kind!=RU_NUM)ru_fail(line,"算术运算符 %s 需要两个数字",op);
        if((op[0]=='/'||op[0]=='%')&&b.n==0)ru_fail(line,"除数不能为零");
        switch(op[0]) {case '+':return ru_finite(a.n+b.n,line);case '-':return ru_finite(a.n-b.n,line);case '*':return ru_finite(a.n*b.n,line);case '/':return ru_finite(a.n/b.n,line);
#ifdef RU_ENABLE_MODULO
        case '%':return ru_finite(fmod(a.n,b.n),line);
#endif
        }
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
    if(v.kind!=RU_NUM||!isfinite(v.n)||v.n<0||v.n>9007199254740991.0||(double)(uint64_t)v.n!=v.n)ru_fail(line,"重复次数须为 0 至 9007199254740991 的整数");
    return (uint64_t)v.n;
}
static size_t ru_index(Val v,size_t max,int endpoint,int line)
{
    if(v.kind!=RU_NUM||!isfinite(v.n)||v.n<0||v.n>9007199254740991.0||(double)(uint64_t)v.n!=v.n)ru_fail(line,"索引须为非负整数");
    if(v.n>(double)max||(!endpoint&&v.n==(double)max))ru_fail(line,"索引越界");
    return (size_t)v.n;
}
static size_t ru_utf8_len(Val v) {size_t i,n=0;for(i=0;i<v.s->len;++i)if(((unsigned char)v.s->data[i]&0xc0)!=0x80)++n;return n;}
static size_t ru_utf8_offset(Val v,size_t at) {size_t i,n=0;for(i=0;i<v.s->len;++i)if(((unsigned char)v.s->data[i]&0xc0)!=0x80){if(n++==at)return i;}return v.s->len;}
static size_t v_length(Val v,int line)
{
    if(v.kind==RU_STR)return ru_utf8_len(v);
    if(v.kind==RU_ARRAY)return ((RuArray *)v.heap)->len;
    ru_fail(line,"量／索引需要阵或句");return 0;
}
/* RU_MAP */
static Val ru_map_get(Val receiver, Val key, int remove, int line);
/* RU_END_MAP */
static Val v_index(Val v,Val index,int line)
{
    size_t i;
/* RU_MAP */
    if(v.kind==RU_MAP)return ru_map_get(v,index,0,line);
/* RU_END_MAP */
    i=ru_index(index,v_length(v,line),0,line);
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
/* Removed container edges become owned roots before the mutation. */
static Val v_array_delete(Val receiver, Val index, int line)
{
    RuArray *array;
    size_t at;
    Val out;
    if (receiver.kind != RU_ARRAY) ru_fail(line, "删 需要阵");
    array = (RuArray *)receiver.heap;
    at = ru_index(index, array->len, 0, line);
    out = v_copy(array->items[at]);
    --array->len;
    if (at < array->len)
        memmove(array->items + at, array->items + at + 1, (array->len - at) * sizeof(Val));
    array->items[array->len] = v_null();
    return out;
}
static Val v_array_pop(Val receiver, int line)
{
    RuArray *array;
    Val out;
    if (receiver.kind != RU_ARRAY) ru_fail(line, "弹 需要阵");
    array = (RuArray *)receiver.heap;
    if (!array->len) ru_fail(line, "空阵不能弹出");
    out = v_copy(array->items[--array->len]);
    array->items[array->len] = v_null();
    return out;
}
/* User equality may mutate the receiver, allocate, or panic. A rooted shallow
 * snapshot keeps both traversal storage and every original element reachable. */
static Val v_array_find(Val receiver, Val needle, int line)
{
    Val snapshot, result = v_null();
    RuArray *array;
    size_t i;
    if (receiver.kind != RU_ARRAY) ru_fail(line, "查 需要阵或典");
    array = (RuArray *)receiver.heap;
    needle = v_copy(needle);
    snapshot = v_array(array->len, array->items, line);
    array = (RuArray *)snapshot.heap;
    for (i = 0; i < array->len; ++i) {
        int same = v_equal(array->items[i], needle, line);
        if (ru_panicking) break;
        if (same) { result = v_num((double)i); break; }
    }
    v_drop(snapshot); v_drop(needle);
    return result;
}
/* Read the Unicode command line without depending on an ANSI CRT argv. */
static Val ru_arguments(int argc, char **argv)
{
    Val arguments = v_array(0, NULL, 0);
    int i;
#ifdef _WIN32
    typedef LPWSTR *(WINAPI *RuCommandLineParser)(LPCWSTR, int *);
    HMODULE library = LoadLibraryExW(L"shell32.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
    FARPROC address;
    RuCommandLineParser parse;
    LPWSTR *wide;
    (void)argv;
    if (!library) ru_fail(0, "无法读取命令行");
    address = GetProcAddress(library, "CommandLineToArgvW");
    if (!address) ru_fail(0, "无法读取命令行");
    memcpy(&parse, &address, sizeof(parse));
    wide = parse(GetCommandLineW(), &argc);
    if (!wide) ru_fail(0, "无法读取命令行");
    for (i = 1; i < argc; ++i) {
        int size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide[i], -1, NULL, 0, NULL, NULL);
        Val arg, added;
        if (!size) ru_fail(0, "命令行不是有效的 Unicode");
        arg = ru_string_alloc((size_t)size - 1, 0);
        if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide[i], -1, arg.s->data, size, NULL, NULL))
            ru_fail(0, "无法读取命令行");
        added = v_append(arguments, arg, 0);
        v_drop(added); v_drop(arg);
    }
    LocalFree(wide);
    FreeLibrary(library);
#else
    for (i = 1; i < argc; ++i) {
        Val arg = v_str(argv[i]);
        Val added = v_append(arguments, arg, 0);
        v_drop(added); v_drop(arg);
    }
#endif
    return arguments;
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
static void ru_annotation_ready(const char *type,Env *env,int line)
{
    size_t length=strlen(type); RuBinding *binding;
    while(length>=4 && !strncmp(type+length-4," 阵",4)) length-=4;
    if ((length==6 && !strncmp(type,"事实",6)) || (length==0) || (length==3 && (!strncmp(type,"典",3)||!strncmp(type,"数",3)||!strncmp(type,"句",3)||!strncmp(type,"空",3)||!strncmp(type,"对",3)||!strncmp(type,"阵",3)||!strncmp(type,"算",3)||!strncmp(type,"作",3)))) return;
    for(;env;env=env->parent) for(binding=env->bindings;binding;binding=binding->next)
        if(strlen(binding->name)==length && !strncmp(binding->name,type,length) && binding->value.kind==RU_CLASS) return;
    ru_fail(line,"未定义类型：%s；类型注解须使用已声明或已尽取导入的形名",type);
}
static void ru_class_ready(RuClass *klass, int line)
{
    for (; klass; klass = klass->parent) {
        size_t i,j;
        if(klass->parent) {
            RuBinding *parent = env_find(klass->global, klass->parent->name);
            if (!parent || parent->value.kind != RU_CLASS || parent->value.klass != klass->parent)
                ru_fail(line, "未定义父形：%s", klass->parent->name);
        }
        for(i=0;i<klass->count;++i) ru_annotation_ready(klass->types[i],klass->global,line);
        for(i=0;i<klass->methods_count;++i)
            for(j=0;j<klass->methods[i]->count;++j)
                ru_annotation_ready(klass->methods[i]->types[j],klass->global,line);
    }
}
static int v_is_type(Val v,const char *type,Env *env)
{
    size_t type_len = strlen(type);
    if (!type_len) return 1;
    const char *suffix = type_len >= 4 ? type + type_len - 4 : NULL;
/* RU_FEATURE: array */
    if(suffix && !strcmp(suffix," 阵")) {size_t i,len=(size_t)(suffix-type);char *item;RuArray *a;int good=1;if(v.kind!=RU_ARRAY)return 0;item=(char *)ru_alloc(len+1,0);memcpy(item,type,len);item[len]=0;a=(RuArray *)v.heap;for(i=0;i<a->len&&good;++i)good=v_is_type(a->items[i],item,env);free(item);return good;}
/* RU_ELSE_FEATURE */
    if(suffix && !strcmp(suffix," 阵")) return 0;
/* RU_END_FEATURE */
    if(!strcmp(type,"算")||!strcmp(type,"作"))return v.kind==RU_FUNCTION && ((RuCallable *)v.heap)->function->procedure==!strcmp(type,"作");
    if(!strcmp(type,"典"))return v.kind==RU_MAP;
    if(!strcmp(type,"事实"))return v.kind==RU_FACT;
    if(!strcmp(type,"数"))return v.kind==RU_NUM;
    if(!strcmp(type,"句"))return v.kind==RU_STR;
    if(!strcmp(type,"空"))return v.kind==RU_NULL;
    if(!strcmp(type,"对"))return v.kind==RU_PAIR;
    if(!strcmp(type,"阵"))return v.kind==RU_ARRAY;
    {RuBinding *b=env_find(env,type);RuClass *klass;if(!b||b->value.kind!=RU_CLASS||v.kind!=RU_OBJECT)return 0;for(klass=((RuObject *)v.heap)->klass;klass;klass=klass->parent)if(klass==b->value.klass)return 1;}
    return 0;
}
/* RU_FEATURE: type_detail */
/* Error-only detail: finite annotation depth bounds traversal, even for cycles.
 * Scratch storage survives until ru_fail exits; no values or addresses are shown. */
static const char *v_type_detail(Val value,const char *type,Env *env,int line)
{
    size_t length=strlen(type),capacity=length*32+256,used=0;
    char *detail=(char *)ru_scratch_alloc(capacity,line);
    char *item=(char *)ru_scratch_alloc(length+1,line);
    strcpy(item,type);detail[0]=0;(void)env;
    while(length>=4 && !strcmp(item+length-4," 阵") && value.kind==RU_ARRAY) {
        size_t i;RuArray *array=(RuArray *)value.heap;
        item[length-4]=0;
        for(i=0;i<array->len;++i)if(!v_is_type(array->items[i],item,env))break;
        if(i==array->len){item[length-4]=' ';break;}
        if(!used)used+=(size_t)snprintf(detail+used,capacity-used,"；元素");
        used+=(size_t)snprintf(detail+used,capacity-used,"[%zu]",i);
        value=array->items[i];length-=4;
    }
    if(used) {
        const char *actual=v_type_name(value);
        size_t extra=strlen(actual)+strlen(item)+64;
        char *grown=(char *)ru_scratch_alloc(used+extra,line);
        memcpy(grown,detail,used);
        snprintf(grown+used,extra,"须为%s，实际收到%s",item,actual);
        detail=grown;
    }
    if(value.kind==RU_OBJECT && !strcmp(v_type_name(value),item)) {
        const char *identity="；同名但不同形身份：期望形与实际形来自不同声明；请核对所用形声明，若曾重定义，请按需重建相关实例或函数";
        size_t size=strlen(detail)+strlen(identity)+1;
        char *grown=(char *)ru_scratch_alloc(size,line);
        snprintf(grown,size,"%s%s",detail,identity);detail=grown;
    }
    return detail;
}
/* RU_ELSE_FEATURE */
static const char *v_type_detail(Val value,const char *type,Env *env,int line)
{
    (void)value;(void)type;(void)env;(void)line;return "";
}
/* RU_END_FEATURE */
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
    if(value.kind!=RU_NULL&&!v_is_type(value,type,owner))ru_fail(line,"字段「%s」须为%s，实际收到%s%s",name,type,v_type_name(value),v_type_detail(value,type,owner,line));
    o->fields[index]=value;
}
static Val v_class(RuClass *klass) {Val v=v_null();v.kind=RU_CLASS;v.klass=klass;return v;}
static Val v_module(Env *env) {Val v=v_null();v.kind=RU_MODULE;v.module=env;return v;}
static Val v_function(RuFunction *function,Env *global,Val self)
{
    Val v=v_null();RuCallable *f=(RuCallable *)ru_new_heap(sizeof(*f),RU_FUNCTION,0);
    v.kind=RU_FUNCTION;v.heap=&f->gc;f->function=function;f->closure=global;f->self=self;
    while(global && global->managed) global=global->parent;
    f->global=global;return v;
}
static Val v_function_reference(Val value, int procedure, int line)
{
    if(value.kind!=RU_FUNCTION) ru_fail(line,"引用的值不是函数／过程");
    if(((RuCallable *)value.heap)->function->procedure!=procedure)
        ru_fail(line,"函数引用的算／作种类不匹配");
    return v_copy(value);
}
static Val v_member_reference(Val receiver, const char *name, int line)
{
    if(receiver.kind==RU_MODULE) {
        RuBinding *binding=env_find_local(receiver.module,name);
        if(!binding) ru_fail(line,"未知成员：%s",name);
        return ru_ordinary_value(v_copy(binding->value),line);
    }
/* RU_FEATURE: user_class */
    if(receiver.kind==RU_OBJECT) {
        RuObject *object=(RuObject *)receiver.heap;
        RuClass *klass; size_t index, i; const char *type; Env *owner;
        if(ru_find_field(object->klass,name,&index,&type,&owner)) return v_copy(object->fields[index]);
        for(klass=object->klass;klass;klass=klass->parent)
            for(i=0;i<klass->methods_count;++i)
                if(!strcmp(klass->methods[i]->name,name))
                    return v_function(klass->methods[i],klass->global,receiver);
    }
/* RU_ELSE_FEATURE */
/* RU_END_FEATURE */

    /* Pair projections are value properties, like object fields. Their
     * contained callable is invokable without binding a builtin method. */
    if(receiver.kind==RU_PAIR && (!strcmp(name,"囫") || !strcmp(name,"囵")))
        return v_copy(!strcmp(name,"囫") ? ((RuPair *)receiver.heap)->first : ((RuPair *)receiver.heap)->second);
    ru_fail(line,"成员暂不支持函数引用：%s",name); return v_null();
}
/* Freeze mutable callable members before argument evaluation can replace them. */
static Val v_member_prepare(Val receiver, const char *name, size_t argc, int line, int *mode)
{
    *mode=0;
    if(receiver.kind==RU_MODULE) {
        RuBinding *binding=env_find_local(receiver.module,name);
        if(!binding) ru_fail(line,"未知成员：%s",name);
        *mode=argc || (binding->reserved && binding->value.kind==RU_FUNCTION) ? 2 : 1;
        return ru_ordinary_value(v_copy(binding->value),line);
    }
/* RU_FEATURE: user_class */
    if(receiver.kind==RU_OBJECT) {
        RuObject *object=(RuObject *)receiver.heap;
        RuClass *klass; size_t index, i; const char *type; Env *owner;
        if(ru_find_field(object->klass,name,&index,&type,&owner)) {
            *mode=argc ? 2 : 1;
            return v_copy(object->fields[index]);
        }
        for(klass=object->klass;klass;klass=klass->parent)
            for(i=0;i<klass->methods_count;++i)
                if(!strcmp(klass->methods[i]->name,name)) {
                    *mode=2; return v_function(klass->methods[i],klass->global,receiver);
                }
    }
/* RU_ELSE_FEATURE */
/* RU_END_FEATURE */

    return v_null();
}
/* Allocate protected runtime objects without source constructor validation. */
static Val ru_object_new(RuClass *klass, int line)
{
    RuObject *o; Val v = v_null(); size_t i;
    o = (RuObject *)ru_new_heap(sizeof(*o), RU_OBJECT, line);
    v.kind = RU_OBJECT; v.heap = &o->gc; o->klass = klass; o->len = ru_field_count(klass);
    o->fields = (Val *)ru_alloc(o->len * sizeof(Val), line);
    for (i = 0; i < o->len; ++i) o->fields[i] = v_null();
    return v;
}
static Val v_new(Val class_value,size_t argc,const char **keys,Val *args,int line)
{
    RuClass *klass; Val v; size_t i,j;
    if(class_value.kind!=RU_CLASS)ru_fail(line,"新 需要形名称");
    klass=class_value.klass; ru_class_ready(klass,line);
    v=ru_object_new(klass,line);
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
    if(callable.kind!=RU_FUNCTION)ru_fail(line,"值不是函数%s",((callable.kind==RU_ARRAY||callable.kind==RU_STR||callable.kind==RU_MAP)&&argc==1&&args[0].kind==RU_ARRAY)?"；若要索引，请让方括号紧邻接收者，如 列[0]；列 [0] 会被解析为调用":"");
    f=(RuCallable *)callable.heap;fn=f->function;
    bound=(Val *)ru_scratch_alloc((fn->count?fn->count:1)*sizeof(Val),line);ru_bind(fn->name,fn->count,fn->names,argc,keys,args,bound,line);
    for(i=0;i<fn->count;++i) {
/* RU_FEATURE: user_class */
        ru_annotation_ready(fn->types[i],f->global,line);
/* RU_ELSE_FEATURE */
/* RU_END_FEATURE */
        if(!v_is_type(bound[i],fn->types[i],f->global))ru_fail(line,"函数「%s」的实参「%s」须为%s，实际收到%s%s",fn->name,fn->names[i],fn->types[i],v_type_name(bound[i]),v_type_detail(bound[i],fn->types[i],f->global,line));
    }
    ru_enter(line);result=fn->code(f->closure,f->self,line,bound);ru_leave();ru_scratch_free(bound);return result;
}
/* Look up protocol methods without treating fields as methods. */
static RuFunction *ru_protocol(Val object, const char *name, Env **owner)
{
    RuClass *klass; size_t i;
    if(object.kind!=RU_OBJECT) return NULL;
    for(klass=((RuObject *)object.heap)->klass;klass;klass=klass->parent)
        for(i=0;i<klass->methods_count;++i) if(!strcmp(klass->methods[i]->name,name)) {
            *owner=klass->global; return klass->methods[i];
        }
    return NULL;
}
static Val ru_protocol_call(Val object, const char *name, size_t count, Val *args, int line)
{
    Env *owner=NULL; RuFunction *fn=ru_protocol(object,name,&owner); Val callable,result;
    const char *keys[]={NULL};
    if(!fn || fn->procedure || fn->count!=count) ru_fail(line,"典键的「%s」须为接收 %zu 个参数的算",name,count);
    callable=v_function(fn,owner,object);
    result=v_call(callable,count,keys,args,line); v_drop(callable); return result;
}
/* RU_FEATURE: user_class */
static int ru_object_equal(Val a, Val b, int line)
{
    Env *owner=NULL; RuFunction *fn; Val result; int equal;
    if(((RuObject *)a.heap)->klass!=((RuObject *)b.heap)->klass) return 0;
    fn=ru_protocol(a,"同",&owner);
    if(!fn) return a.heap==b.heap;
    a=v_copy(a); b=v_copy(b);
    result=ru_protocol_call(a,"同",1,&b,line);
    v_drop(a); v_drop(b);
    if(ru_panicking) {v_drop(result);return 0;}
    if(result.kind!=RU_FACT) ru_fail(line,"「同」须返回事实，实际收到%s",v_type_name(result));
    equal=result.n!=0; v_drop(result); return equal;
}
/* RU_ELSE_FEATURE */
static int ru_object_equal(Val a, Val b, int line) { (void)line; return a.heap==b.heap; }
/* RU_END_FEATURE */
static uint64_t ru_hash_mix(uint64_t x)
{
    x ^= x >> 30; x *= UINT64_C(0xbf58476d1ce4e5b9);
    x ^= x >> 27; x *= UINT64_C(0x94d049bb133111eb);
    return x ^ (x >> 31);
}
static uint64_t ru_key_hash(Val key, int line)
{
    uint64_t bits=0; size_t i;
    if(key.kind==RU_NUM) { double n=key.n==0 ? 0 : key.n; if(!isfinite(n))ru_fail(line,"典键须为有限数"); memcpy(&bits,&n,sizeof(bits)); return ru_hash_mix(bits ^ UINT64_C(0x1234)); }
    if(key.kind==RU_FACT) return ru_hash_mix((uint64_t)key.n ^ UINT64_C(0x2345));
    if(key.kind==RU_STR) { bits=UINT64_C(1469598103934665603); for(i=0;i<key.s->len;++i) {bits^=(unsigned char)key.s->data[i];bits*=UINT64_C(1099511628211);}return ru_hash_mix(bits ^ UINT64_C(0x3456)); }
    if(key.kind==RU_OBJECT) {
        Env *owner=NULL; RuFunction *same=ru_protocol(key,"同",&owner), *hash=ru_protocol(key,"印",&owner); Val result;
        if(!same || same->procedure || same->count!=1 || !hash || hash->procedure || hash->count)
            ru_fail(line,"形典键须定义算「同」的一参数与算「印」的零参数");
        result=ru_protocol_call(key,"印",0,NULL,line);
        if(ru_panicking) {v_drop(result);return 0;}
        if(result.kind!=RU_NUM || !isfinite(result.n) || result.n < -9007199254740991.0 || result.n > 9007199254740991.0 || result.n!=(double)(int64_t)result.n)
            ru_fail(line,"「印」须返回安全整数数");
        bits=(uint64_t)(int64_t)result.n;v_drop(result);
        return ru_hash_mix(bits ^ (uint64_t)(uintptr_t)((RuObject *)key.heap)->klass ^ UINT64_C(0x4567));
    }
    ru_fail(line,"%s不能作为典键",v_type_name(key));return 0;
}
static Val v_map_new(int line)
{
    Val value=v_null(); RuMap *map=(RuMap *)ru_new_heap(sizeof(*map),RU_MAP,line);
    value.kind=RU_MAP;value.heap=&map->gc;
    map->len=map->used=map->capacity=0;map->version=0;map->entries=NULL;return value;
}
/* Rehash cached hashes without user code; compact tombstones before growing. */
static void ru_map_grow(RuMap *map, int line)
{
    size_t cap=map->capacity ? (map->len>=map->capacity/4 ? map->capacity*2 : map->capacity) : 16,i,at; RuMapEntry *entries;
    if(cap<map->capacity || cap>SIZE_MAX/sizeof(*entries))ru_fail(line,"典过大");
    entries=(RuMapEntry *)ru_alloc(cap*sizeof(*entries),line);memset(entries,0,cap*sizeof(*entries));
    for(i=0;i<map->capacity;++i) if(map->entries[i].state==1) {
        at=(size_t)map->entries[i].hash & (cap-1);
        while(entries[at].state)at=(at+1)&(cap-1);
        entries[at]=map->entries[i];
    }
    free(map->entries);map->entries=entries;map->capacity=cap;map->used=map->len;
}
static size_t ru_map_find(RuMap *map, Val key, uint64_t hash, uint64_t version, int line, int *found)
{
    size_t at=(size_t)hash&(map->capacity-1), tomb=SIZE_MAX;
    *found=0;
    while(map->entries[at].state) {
        if(map->entries[at].state==2) {if(tomb==SIZE_MAX)tomb=at;}
        else if(map->entries[at].hash==hash) {
            Val stored=v_copy(map->entries[at].key); int same=v_equal(stored,key,line); v_drop(stored);
            if(ru_panicking)return 0;
            if(map->version!=version)ru_fail(line,"典键的同／印回调修改了当前典");
            if(same){*found=1;return at;}
        }
        at=(at+1)&(map->capacity-1);
    }
    return tomb==SIZE_MAX ? at : tomb;
}
static uint64_t ru_map_hash(RuMap *map, Val key, int line)
{
    uint64_t version=map->version, hash=ru_key_hash(key,line);
    if(!ru_panicking && version!=map->version)ru_fail(line,"典键的同／印回调修改了当前典");
    return hash;
}
static Val v_map_put(Val receiver, Val key, Val value, int line)
{
    RuMap *map=(RuMap *)receiver.heap; uint64_t hash=ru_map_hash(map,key,line); size_t at; int found;
    if(ru_panicking)return v_null();
    if(map->used>=map->capacity/2)ru_map_grow(map,line);
    at=ru_map_find(map,key,hash,map->version,line,&found);
    if(ru_panicking)return v_null();
    if(!found){if(!map->entries[at].state)++map->used;++map->len;map->entries[at].key=key;map->entries[at].hash=hash;map->entries[at].state=1;}
    map->entries[at].value=value;++map->version;return v_copy(receiver);
}
static Val ru_map_get(Val receiver, Val key, int remove, int line)
{
    RuMap *map=(RuMap *)receiver.heap; uint64_t hash=ru_map_hash(map,key,line); size_t at; int found;
    if(ru_panicking)return v_null();
    if(!map->capacity)return remove ? v_fact(0) : v_null();
    at=ru_map_find(map,key,hash,map->version,line,&found);
    if(ru_panicking)return v_null();
    if(remove){if(found){map->entries[at].state=2;map->entries[at].key=v_null();map->entries[at].value=v_null();--map->len;++map->version;}return v_fact(found);}
    return found ? v_copy(map->entries[at].value) : v_null();
}
static Val ru_map_each(Val receiver, Val callback, int line)
{
    RuMap *map=(RuMap *)receiver.heap; Val snapshot; RuArray *array; size_t i,at=0; const char *keys[]={NULL,NULL};
    if(callback.kind!=RU_FUNCTION || ((RuCallable *)callback.heap)->function->count!=2)ru_fail(line,"典的列需要接收键和值两个参数的算或作");
    snapshot=v_array(0,NULL,line);array=(RuArray *)snapshot.heap;
    if(map->len>SIZE_MAX/sizeof(Val)/2)ru_fail(line,"典过大");
    free(array->items);array->items=(Val *)ru_alloc(map->len*2*sizeof(Val),line);array->len=array->capacity=map->len*2;
    for(i=0;i<map->capacity;++i)if(map->entries[i].state==1){array->items[at++]=map->entries[i].key;array->items[at++]=map->entries[i].value;}
    for(i=0;i<array->len;i+=2){Val result=v_call(callback,2,keys,array->items+i,line);v_drop(result);if(ru_panicking)break;}
    v_drop(snapshot);return v_null();
}
static Val ru_map_member(Val receiver,const char *name,size_t argc,const char **keys,Val *args,int line)
{
    const char *key_name[]={"键"}, *both[]={"键","值"}, *callback[]={"回调"}; Val bound[2];
    (void)receiver; (void)key_name; (void)both; (void)callback; (void)bound;
    (void)argc; (void)keys; (void)args;
/* RU_MEMBERS: 查,除 */
    if(!strcmp(name,"查") || !strcmp(name,"除")){ru_bind(name,1,key_name,argc,keys,args,bound,line);return ru_map_get(receiver,bound[0],!strcmp(name,"除"),line);}
/* RU_END_MEMBERS */
/* RU_MEMBERS: 增 */
    if(!strcmp(name,"增")){ru_bind(name,2,both,argc,keys,args,bound,line);return v_map_put(receiver,bound[0],bound[1],line);}
/* RU_END_MEMBERS */
/* RU_MEMBERS: 列 */
    if(!strcmp(name,"列")){ru_bind(name,1,callback,argc,keys,args,bound,line);return ru_map_each(receiver,bound[0],line);}
/* RU_END_MEMBERS */
/* RU_MEMBERS: 量 */
    if(!strcmp(name,"量")){if(argc)ru_fail(line,"量不接收实参");return v_num((double)((RuMap *)receiver.heap)->len);}
/* RU_END_MEMBERS */
    ru_fail(line,"未知典成员：%s",name);return v_null();
}
static Val v_member(Val receiver,const char *name,size_t argc,const char **keys,Val *args,int line)
{
    const char *one[]={"值"},*position[]={"位"},*range[]={"始","终"};Val bound[2], io_result = v_null();
/* RU_FEATURE: map */
    if(receiver.kind==RU_MAP)return ru_map_member(receiver,name,argc,keys,args,line);
/* RU_ELSE_FEATURE */
/* RU_END_FEATURE */
    (void)one; (void)position; (void)range; (void)bound; (void)io_result;
/* RU_MEMBERS: 读入,扫句,拆词,拆行,字列,合句,排序,取整,蓄出,词,数,行,写,清 */
    if (ru_contest_member(receiver, name, argc, keys, args, line, &io_result)) return io_result;
/* RU_END_MEMBERS */
/* RU_MEMBERS: 拆分,替换,去空白,定点,平方根,幂,向下取整,向上取整,四舍五入,造源,整数,洗牌 */
    if (ru_practical_member(receiver, name, argc, keys, args, line, &io_result)) return io_result;
/* RU_END_MEMBERS */
/* RU_MEMBERS: 读,写,在,除,列 */
    if (ru_io_member(receiver, name, argc, keys, args, line, &io_result)) return io_result;
/* RU_END_MEMBERS */
    if(receiver.kind==RU_MODULE){
        RuBinding *binding;Val value,result;
        /* Qualified access exposes only the module's own exports, not builtins
         * inherited through its parent environment. */
        for(binding=receiver.module->bindings;binding;binding=binding->next)
            if(!strcmp(binding->name,name))break;
        if(!binding)ru_fail(line,"未知成员：%s",name);
        value=ru_ordinary_value(v_copy(binding->value),line);
        if(value.kind==RU_FUNCTION && (argc || binding->reserved)){result=v_call(value,argc,keys,args,line);v_drop(value);return result;}
        if(argc)ru_fail(line,"成员不是函数：%s",name);
        return value;
    }
/* RU_FEATURE: user_class */
    if(receiver.kind==RU_OBJECT){RuObject *o=(RuObject *)receiver.heap;size_t index,i;const char *type;Env *owner;RuClass *klass;
        if(ru_find_field(o->klass,name,&index,&type,&owner)){Val value=v_copy(o->fields[index]);if(argc){Val result=v_call(value,argc,keys,args,line);v_drop(value);return result;}return value;}
        for(klass=o->klass;klass;klass=klass->parent)for(i=0;i<klass->methods_count;++i)if(!strcmp(klass->methods[i]->name,name)){Val method=v_function(klass->methods[i],klass->global,receiver),result=v_call(method,argc,keys,args,line);v_drop(method);return result;}
        ru_fail(line,"未知成员：%s",name);
    }
/* RU_ELSE_FEATURE */
    if(receiver.kind==RU_OBJECT) ru_fail(line,"未知成员：%s",name);
/* RU_END_FEATURE */

/* RU_MEMBERS: 囫,囵 */
    if(receiver.kind==RU_PAIR&&(!strcmp(name,"囫")||!strcmp(name,"囵"))){if(argc)ru_fail(line,"对的成员不接收实参");return v_copy(!strcmp(name,"囫")?((RuPair *)receiver.heap)->first:((RuPair *)receiver.heap)->second);}
/* RU_END_MEMBERS */
/* RU_MEMBERS: 量 */
    if(!strcmp(name,"量")){if(argc)ru_fail(line,"量不接收实参");return v_num((double)v_length(receiver,line));}
/* RU_END_MEMBERS */
/* RU_MEMBERS: 位 */
    if(!strcmp(name,"位")){ru_bind(name,1,position,argc,keys,args,bound,line);return v_index(receiver,bound[0],line);}
/* RU_END_MEMBERS */
/* RU_MEMBERS: 段 */
    if(!strcmp(name,"段")){ru_bind(name,2,range,argc,keys,args,bound,line);return v_slice(receiver,bound[0],bound[1],line);}
/* RU_END_MEMBERS */
/* RU_MEMBERS: 增 */
    if(!strcmp(name,"增")){ru_bind(name,1,one,argc,keys,args,bound,line);return v_append(receiver,bound[0],line);}
/* RU_END_MEMBERS */
/* RU_MEMBERS: 删 */
    if(!strcmp(name,"删")){ru_bind(name,1,position,argc,keys,args,bound,line);return v_array_delete(receiver,bound[0],line);}
/* RU_END_MEMBERS */
/* RU_MEMBERS: 弹 */
    if(!strcmp(name,"弹")){ru_bind(name,0,NULL,argc,keys,args,bound,line);return v_array_pop(receiver,line);}
/* RU_END_MEMBERS */
/* RU_MEMBERS: 查 */
    if(!strcmp(name,"查")){ru_bind(name,1,one,argc,keys,args,bound,line);return v_array_find(receiver,bound[0],line);}
/* RU_END_MEMBERS */
/* RU_MEMBERS: 含 */
    if(!strcmp(name,"含")){const char *text[]={"句"};ru_bind(name,1,text,argc,keys,args,bound,line);return v_binary("含",receiver,bound[0],line);}
/* RU_END_MEMBERS */
    ru_fail(line,"未知成员：%s",name);return v_null();
}
static Val v_member_finish(Val receiver, const char *name, size_t argc, const char **keys,
                           Val *args, int line, int mode, Val prepared)
{
    if(mode==2) return v_call(prepared,argc,keys,args,line);
    if(mode==1) return v_copy(prepared);
    return v_member(receiver,name,argc,keys,args,line);
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
    if (prompt.kind != RU_STR) ru_fail(line, "输入提示须为字符串");
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
