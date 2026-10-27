/* Private LLVM ABI v1. Included in exactly one runtime translation unit.
 * LLVM sees only void pointers, fixed-width integers and doubles. Val/Env and
 * C aggregate calling conventions stay entirely on the C side of the boundary.
 * A frame owns initialized Val slots; all produced values own one GC root.
 * Generated code clears temporaries at statement/unwind boundaries, and copies
 * a returned value into its caller's slot before disposing its own frame.
 */
typedef struct { size_t count; uint64_t roots; Val values[]; } RuLLVMFrame;
static RuFunction *rul_function_descriptor(int32_t id);
static RuClass *rul_class_descriptor(int32_t id);
static Val rul_module_import(int32_t id);

static void rul_drop_slot(Val *slot)
{
    /* Only the heap field is live after a clear. Never read dead payloads. */
    Val root = v_null(); root.heap = slot->heap;
    v_drop(root); slot->heap = NULL;
}
static void rul_init_put(void *out, Val value) { *(Val *)out = value; }
static void rul_put(void *out, Val value)
{
    rul_drop_slot(out); *(Val *)out = value;
}
/* Small frames use an aligned stack buffer; C still owns their size/layout.
 * A nonlocal callback recovery restores abandoned roots independently of the
 * storage location, just as it does for the C backend's stack temporaries. */
__attribute__((always_inline)) uint64_t rul_frame_size(int32_t count)
{
    if (count < 0 || (size_t)count > (SIZE_MAX-sizeof(RuLLVMFrame))/sizeof(Val))
        ru_fail(0, "LLVM 临时值过多");
    return sizeof(RuLLVMFrame)+(size_t)count*sizeof(Val);
}
__attribute__((always_inline)) void rul_frame_init(void *opaque, int32_t count)
{
    RuLLVMFrame *frame = opaque; size_t i;
    frame->count = (size_t)count; frame->roots = UINT64_MAX;
    for (i=0; i<frame->count; ++i) frame->values[i] = v_null();
}
void *rul_frame_new(int32_t count)
{
    RuLLVMFrame *frame; size_t i;
    if (count < 0 || (size_t)count > (SIZE_MAX-sizeof(*frame))/sizeof(Val))
        ru_fail(0, "LLVM 临时值过多");
    frame = ru_scratch_alloc(sizeof(*frame)+(size_t)count*sizeof(Val), 0);
    frame->count = (size_t)count; frame->roots = UINT64_MAX;
    for (i=0; i<frame->count; ++i) frame->values[i] = v_null();
    return frame;
}
__attribute__((always_inline)) void rul_frame_roots(void *opaque, int32_t low, int32_t high)
{ ((RuLLVMFrame *)opaque)->roots = (uint64_t)(uint32_t)low | ((uint64_t)(uint32_t)high << 32); }
void *rul_slot(void *opaque, int32_t index)
{
    RuLLVMFrame *frame = opaque;
    if (index < 0 || (size_t)index >= frame->count) ru_fail(0, "LLVM 临时值索引越界");
    return &frame->values[index];
}
/* Frame metadata is fixed until disposal. Snapshot it before dropping roots:
 * a heap root counter can otherwise conservatively alias these size_t fields
 * in LLVM's loop analysis. This does not shorten any cleanup range. */
__attribute__((always_inline)) void rul_clear(void *opaque)
{
    RuLLVMFrame *frame = opaque; size_t i, count = frame->count;
    uint64_t roots = frame->roots;
    for (i=0; i<count; ++i)
        if (count>64 || ((roots>>i)&1)) rul_drop_slot(&frame->values[i]);
}
__attribute__((always_inline)) void rul_clear_count(void *opaque, int32_t count)
{
    RuLLVMFrame *frame = opaque; size_t i, capacity = frame->count;
    uint64_t roots = frame->roots;
    if (count < 0 || (size_t)count > capacity) ru_fail(0, "LLVM 临时值清理越界");
    for (i=0; i<(size_t)count; ++i)
        if (capacity>64 || ((roots>>i)&1)) rul_drop_slot(&frame->values[i]);
}
__attribute__((always_inline)) void rul_frame_drop(void *opaque) { rul_clear(opaque); }
void rul_frame_free(void *opaque) { rul_clear(opaque); ru_scratch_free(opaque); }
/* Independent payloads expose only their heap fields to cleanup.
 * This private type never aliases the ordinary or interpreter frame header. */
typedef struct { size_t count; uint64_t roots; RuHeap **fields[]; } RuLLVMLocalFrame;
__attribute__((always_inline)) uint64_t rul_local_frame_size(int32_t count)
{
    if(count<0 || count>64)ru_fail(0,"LLVM 独立临时值过多");
    return sizeof(RuLLVMLocalFrame)+(size_t)count*sizeof(RuHeap **);
}
__attribute__((always_inline)) void rul_local_frame_init(void *opaque,int32_t count)
{
    RuLLVMLocalFrame *frame=opaque;
    frame->count=(size_t)count;frame->roots=UINT64_MAX;
}
__attribute__((always_inline)) void rul_local_frame_roots(void *opaque,int32_t low,int32_t high)
{ ((RuLLVMLocalFrame *)opaque)->roots=(uint64_t)(uint32_t)low|((uint64_t)(uint32_t)high<<32); }
__attribute__((always_inline)) void *rul_local_slot(void *opaque,int32_t index,void *storage)
{
    RuLLVMLocalFrame *frame=opaque;Val *value=storage;
    if(index<0 || (size_t)index>=frame->count)ru_fail(0,"LLVM 临时值索引越界");
    *value=v_null();frame->fields[index]=&value->heap;return storage;
}
/* Keep cleanup compact rather than expanding one drop per slot at every site.
 * Only root fields escape through this table; payloads have independent storage. */
static __attribute__((noinline)) void rul_local_scan(void *opaque,int32_t count,uint64_t roots)
{
    /* Both ABI entry wrappers validate count before entering this scanner. */
    RuLLVMLocalFrame *frame=opaque;size_t i;
    for(i=0;i<(size_t)count;++i)if((roots>>i)&1) {
        RuHeap **field=frame->fields[i];Val root=v_null();
        root.heap=*field;v_drop(root);*field=NULL;
    }
}
/* Normal statement boundaries carry the roots written since the previous
 * clear. Unwind and final cleanup retain the whole-function union bitmap. */
__attribute__((always_inline)) void rul_local_clear_count(void *opaque,int32_t count)
{
    RuLLVMLocalFrame *frame=opaque;
    if(count<0 || (size_t)count>frame->count)ru_fail(0,"LLVM 临时值清理越界");
    rul_local_scan(opaque,count,frame->roots);
}
__attribute__((always_inline)) void rul_local_clear_mask(void *opaque,int32_t count,int32_t low,int32_t high)
{
    RuLLVMLocalFrame *frame=opaque;
    uint64_t roots=(uint64_t)(uint32_t)low|((uint64_t)(uint32_t)high<<32);
    if(count<0 || (size_t)count>frame->count)ru_fail(0,"LLVM 临时值清理越界");
    if(roots)rul_local_scan(opaque,count,roots);
}
__attribute__((always_inline)) void rul_local_clear(void *opaque)
{ rul_local_clear_count(opaque,(int32_t)((RuLLVMLocalFrame *)opaque)->count); }
__attribute__((always_inline)) void rul_local_frame_drop(void *opaque)
{ rul_local_clear(opaque); }
void rul_copy(void *out, void *value) { rul_put(out, v_copy(*(Val *)value)); }
/* Direct entry callers provide a fresh standalone result, never a live frame
 * slot. Keep the returned root copy; ordinary temporary cleanup is unchanged.
 * These helpers intentionally bypass the host's overwriting-slot adapter. */
__attribute__((always_inline)) void rul_return_copy(void *out, void *value)
{ *(Val *)out=v_copy(*(Val *)value); }
__attribute__((always_inline)) void rul_return_null(void *out)
{ *(Val *)out=v_null(); }

/* Borrowed packs retain no extra roots; original expression slots own them. */
__attribute__((always_inline)) uint64_t rul_args_size(int32_t count)
{ return (uint64_t)(uint32_t)count*sizeof(Val); }
__attribute__((always_inline)) void rul_args_set(void *args,int32_t index,void *value)
{ ((Val *)args)[index]=*(Val *)value; }
void rul_null(void *out) { rul_put(out, v_null()); }
void rul_number(void *out, double value) { rul_put(out, v_num(value)); }
void rul_fact(void *out, int32_t value) { rul_put(out, v_fact(value)); }
/* Fresh slots own no root after initialization or a statement clear. Dead
 * payloads are overwritten before reading. These entry points are only used
 * for the first write, never for an arbitrary caller result or a live value.
 * C temporaries already initialize
 * directly; expose the same fact to the pointer-only LLVM ABI. */
__attribute__((always_inline)) void rul_init_copy(void *out, void *value)
{ rul_init_put(out,v_copy(*(Val *)value)); }
__attribute__((always_inline)) void rul_init_null(void *out) { rul_init_put(out,v_null()); }
__attribute__((always_inline)) void rul_init_number(void *out, double value) { rul_init_put(out,v_num(value)); }
/* Scalar expression boundaries. Layout stays C-owned; type checks occur only
 * after both operand expressions have completed, as in v_binary. */
__attribute__((always_inline)) void rul_numeric_check(const char *op, void *left, void *right, int32_t line)
{
    if ((left && ((Val *)left)->kind!=RU_NUM) || (right && ((Val *)right)->kind!=RU_NUM))
        ru_fail(line,"算术运算符 %s 需要两个数字",op);
}
__attribute__((always_inline)) double rul_number_value(void *value) { return ((Val *)value)->n; }
__attribute__((always_inline)) double rul_number_convert(void *value, int32_t line)
{ return v_convert(*(Val *)value,RU_NUM,line).n; }
__attribute__((always_inline)) double rul_number_unary(void *value, const char *op, int32_t line)
{
    if (((Val *)value)->kind!=RU_NUM) ru_fail(line,"运算符 %s 需要数字",op);
    return ((Val *)value)->n;
}
__attribute__((always_inline)) double rul_finite_number(double value, int32_t line)
{ return ru_finite_number(value,line); }
__attribute__((always_inline)) double rul_nonzero_number(double value, int32_t line)
{ if (value==0) ru_fail(line,"除数不能为零"); return value; }
__attribute__((always_inline)) void rul_init_fact(void *out, int32_t value) { rul_init_put(out,v_fact(value)); }
void rul_string(void *out, const char *value) { rul_put(out, v_str(value)); }
void rul_init_string(void *out, const char *value) { rul_init_put(out, v_str(value)); }
int32_t rul_truth(void *value) { return v_truth(*(Val *)value); }
uint64_t rul_count(void *value, int32_t line) { return v_count(*(Val *)value,line); }
const char *rul_source(const char *source) { const char *old=ru_source; ru_source=source; return old; }
void rul_source_restore(const char *source) { ru_source=source; }
void *rul_env_new(void *parent, int32_t scope, int32_t line) { return env_new(parent,scope,line); }
void rul_env_free(void *env) { env_free(env); }
void rul_bind_arg(void *env, const char *name, void *args, int32_t index)
{ env_set(env,name,((Val *)args)[index]); }
void rul_get(void *out, void *env, const char *name, int32_t line)
{ rul_put(out,env_get(env,name,line)); }
void rul_init_get(void *out, void *env, const char *name, int32_t line)
{ rul_init_put(out,env_get(env,name,line)); }
/* A cache belongs to one generated function invocation and its root Env.
 * Bindings never move or disappear while that Env is rooted. Cache the binding,
 * not its mutable value. Ancestor hits must remain uncached: a later local
 * declaration can shadow them. Nested block/rescue environments are excluded. */
static __attribute__((noinline)) Val rul_cached_miss(void *env, const char *name, int32_t line, void **cache)
{
    RuBindingCache c={name,*cache}; Val value=env_cget_miss(env,&c,line);
    *cache=c.ptr; return value;
}
static __attribute__((always_inline)) Val rul_cached_value(void *env, const char *name, int32_t line, void **cache)
{
    RuBinding *binding=*cache;
    return binding ? v_copy(binding->value) : rul_cached_miss(env,name,line,cache);
}
__attribute__((always_inline)) void rul_get_cached(void *out, void *env, const char *name, int32_t line, void **cache)
{ rul_put(out,rul_cached_value(env,name,line,cache)); }
__attribute__((always_inline)) void rul_init_get_cached(void *out, void *env, const char *name, int32_t line, void **cache)
{ rul_init_put(out,rul_cached_value(env,name,line,cache)); }
void rul_bind(void *env, const char *name, void *value, int32_t line)
{ env_bind(env,name,*(Val *)value,line); }
static __attribute__((noinline)) void rul_bind_cached_miss(void *env, const char *name, void *value, int32_t line, void **cache)
{
    RuBindingCache c={name,*cache}; env_cbind_miss(env,&c,*(Val *)value,line); *cache=c.ptr;
}
__attribute__((always_inline)) void rul_bind_cached(void *opaque, const char *name, void *value, int32_t line, void **cache)
{
    RuBinding *binding=*cache;
    if (binding && !binding->reserved && strcmp(name,"读")) binding->value=*(Val *)value;
    else rul_bind_cached_miss(opaque,name,value,line,cache);
}
void rul_declare(void *env, const char *name, void *value)
{ env_declare(env,name,*(Val *)value); }
void rul_function(void *out, int32_t id, void *env, void *self)
{ rul_put(out,v_function(rul_function_descriptor(id),env,self ? *(Val *)self : v_null())); }
void rul_init_function(void *out, int32_t id, void *env, void *self)
{ rul_init_put(out,v_function(rul_function_descriptor(id),env,self ? *(Val *)self : v_null())); }
void rul_class(void *out, int32_t id) { rul_put(out,v_class(rul_class_descriptor(id))); }
void rul_init_class(void *out, int32_t id) { rul_init_put(out,v_class(rul_class_descriptor(id))); }
void rul_class_ready(int32_t id, int32_t line) { ru_class_ready(rul_class_descriptor(id),line); }
void rul_reference(void *out, void *value, int32_t procedure, int32_t line)
{ rul_put(out,v_function_reference(*(Val *)value,procedure,line)); }
void rul_init_reference(void *out, void *value, int32_t procedure, int32_t line)
{ rul_init_put(out,v_function_reference(*(Val *)value,procedure,line)); }
void rul_member_reference(void *out, void *receiver, const char *name, int32_t line)
{ rul_put(out,v_member_reference(*(Val *)receiver,name,line)); }
void rul_init_member_reference(void *out, void *receiver, const char *name, int32_t line)
{ rul_init_put(out,v_member_reference(*(Val *)receiver,name,line)); }
void rul_call(void *out, void *callee, int32_t count, const char **keys, void *args, int32_t line)
{ rul_put(out,v_call(*(Val *)callee,(size_t)count,keys,args,line)); }
void rul_init_call(void *out, void *callee, int32_t count, const char **keys, void *args, int32_t line)
{ rul_init_put(out,v_call(*(Val *)callee,(size_t)count,keys,args,line)); }
void rul_read(void *out, void *prompt, int32_t line) { rul_put(out,read_input(*(Val *)prompt,line)); }
void rul_init_read(void *out, void *prompt, int32_t line) { rul_init_put(out,read_input(*(Val *)prompt,line)); }
void rul_print(void *value, int32_t line) { v_print(*(Val *)value,line); }
void rul_array(void *out, int32_t count, void *values, int32_t line)
{ rul_put(out,v_array((size_t)count,values,line)); }
void rul_init_array(void *out, int32_t count, void *values, int32_t line)
{ rul_init_put(out,v_array((size_t)count,values,line)); }
void rul_map(void *out, int32_t line) { rul_put(out,v_map_new(line)); }
void rul_init_map(void *out, int32_t line) { rul_init_put(out,v_map_new(line)); }
void rul_map_put(void *map, void *key, void *value, int32_t line)
{ Val result=v_map_put(*(Val *)map,*(Val *)key,*(Val *)value,line); v_drop(result); }
void rul_unary(void *out, const char *op, void *arg, int32_t line)
{ rul_put(out,v_unary(op,*(Val *)arg,line)); }
void rul_init_unary(void *out, const char *op, void *arg, int32_t line)
{ rul_init_put(out,v_unary(op,*(Val *)arg,line)); }
void rul_binary(void *out, const char *op, void *left, void *right, int32_t line)
{ rul_put(out,v_binary(op,*(Val *)left,*(Val *)right,line)); }
void rul_init_binary(void *out, const char *op, void *left, void *right, int32_t line)
{ rul_init_put(out,v_binary(op,*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_add(void *out, void *left, void *right, int32_t line)
{ rul_put(out,v_add(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_init_add(void *out, void *left, void *right, int32_t line)
{ rul_init_put(out,v_add(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_sub(void *out, void *left, void *right, int32_t line)
{ rul_put(out,v_sub(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_init_sub(void *out, void *left, void *right, int32_t line)
{ rul_init_put(out,v_sub(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_mul(void *out, void *left, void *right, int32_t line)
{ rul_put(out,v_mul(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_init_mul(void *out, void *left, void *right, int32_t line)
{ rul_init_put(out,v_mul(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_div(void *out, void *left, void *right, int32_t line)
{ rul_put(out,v_div(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_init_div(void *out, void *left, void *right, int32_t line)
{ rul_init_put(out,v_div(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_mod(void *out, void *left, void *right, int32_t line)
{ rul_put(out,v_mod(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_init_mod(void *out, void *left, void *right, int32_t line)
{ rul_init_put(out,v_mod(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_eq(void *out, void *left, void *right, int32_t line)
{ rul_put(out,v_eq(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_init_eq(void *out, void *left, void *right, int32_t line)
{ rul_init_put(out,v_eq(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_ne(void *out, void *left, void *right, int32_t line)
{ rul_put(out,v_ne(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_init_ne(void *out, void *left, void *right, int32_t line)
{ rul_init_put(out,v_ne(*(Val *)left,*(Val *)right,line)); }
/* Conditions return a scalar and leave ownership with their input slots. */
__attribute__((always_inline)) int32_t rul_test_eq(void *left, void *right, int32_t line)
{ return v_equal(*(Val *)left,*(Val *)right,line); }
__attribute__((always_inline)) int32_t rul_test_ne(void *left, void *right, int32_t line)
{ return !v_equal(*(Val *)left,*(Val *)right,line); }
__attribute__((always_inline)) int32_t rul_test_lt(void *left, void *right, int32_t line)
{ return ru_order(*(Val *)left,*(Val *)right,line)<0; }
__attribute__((always_inline)) int32_t rul_test_le(void *left, void *right, int32_t line)
{ return ru_order(*(Val *)left,*(Val *)right,line)<=0; }
__attribute__((always_inline)) int32_t rul_test_gt(void *left, void *right, int32_t line)
{ return ru_order(*(Val *)left,*(Val *)right,line)>0; }
__attribute__((always_inline)) int32_t rul_test_ge(void *left, void *right, int32_t line)
{ return ru_order(*(Val *)left,*(Val *)right,line)>=0; }
__attribute__((always_inline)) void rul_lt(void *out, void *left, void *right, int32_t line)
{ rul_put(out,v_lt(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_init_lt(void *out, void *left, void *right, int32_t line)
{ rul_init_put(out,v_lt(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_le(void *out, void *left, void *right, int32_t line)
{ rul_put(out,v_le(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_init_le(void *out, void *left, void *right, int32_t line)
{ rul_init_put(out,v_le(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_gt(void *out, void *left, void *right, int32_t line)
{ rul_put(out,v_gt(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_init_gt(void *out, void *left, void *right, int32_t line)
{ rul_init_put(out,v_gt(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_ge(void *out, void *left, void *right, int32_t line)
{ rul_put(out,v_ge(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_init_ge(void *out, void *left, void *right, int32_t line)
{ rul_init_put(out,v_ge(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_pair(void *out, void *left, void *right, int32_t line)
{ rul_put(out,v_pair(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_init_pair(void *out, void *left, void *right, int32_t line)
{ rul_init_put(out,v_pair(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_contains(void *out, void *left, void *right, int32_t line)
{ rul_put(out,v_contains(*(Val *)left,*(Val *)right,line)); }
__attribute__((always_inline)) void rul_init_contains(void *out, void *left, void *right, int32_t line)
{ rul_init_put(out,v_contains(*(Val *)left,*(Val *)right,line)); }
void rul_convert(void *out, void *arg, const char *target, int32_t line)
{
    int kind;
    if (!strcmp(target,"数")) kind=RU_NUM;
    else if (!strcmp(target,"句")) kind=RU_STR;
    else if (!strcmp(target,"阵")) kind=RU_ARRAY;
    else if (!strcmp(target,"事实")) kind=RU_FACT;
    else { ru_fail(line,"LLVM 未知转换目标：%s",target); return; }
    rul_put(out,v_convert(*(Val *)arg,kind,line));
}
void rul_init_convert(void *out, void *arg, const char *target, int32_t line)
{
    int kind;
    if (!strcmp(target,"数")) kind=RU_NUM;
    else if (!strcmp(target,"句")) kind=RU_STR;
    else if (!strcmp(target,"阵")) kind=RU_ARRAY;
    else if (!strcmp(target,"事实")) kind=RU_FACT;
    else { ru_fail(line,"LLVM 未知转换目标：%s",target); return; }
    rul_init_put(out,v_convert(*(Val *)arg,kind,line));
}
void rul_index(void *out, void *receiver, void *index, int32_t line)
{ rul_put(out,v_index(*(Val *)receiver,*(Val *)index,line)); }
void rul_init_index(void *out, void *receiver, void *index, int32_t line)
{ rul_init_put(out,v_index(*(Val *)receiver,*(Val *)index,line)); }
void rul_slice(void *out, void *receiver, void *start, void *end, int32_t line)
{ rul_put(out,v_slice(*(Val *)receiver,*(Val *)start,*(Val *)end,line)); }
void rul_init_slice(void *out, void *receiver, void *start, void *end, int32_t line)
{ rul_init_put(out,v_slice(*(Val *)receiver,*(Val *)start,*(Val *)end,line)); }
void rul_member_prepare(void *out, void *receiver, const char *name, int32_t argc, int32_t line, int32_t *mode)
{ int selected; Val result=v_member_prepare(*(Val *)receiver,name,(size_t)argc,line,&selected); *mode=selected; rul_put(out,result); }
void rul_init_member_prepare(void *out, void *receiver, const char *name, int32_t argc, int32_t line, int32_t *mode)
{ int selected; Val result=v_member_prepare(*(Val *)receiver,name,(size_t)argc,line,&selected); *mode=selected; rul_init_put(out,result); }
void rul_member_finish(void *out, void *receiver, const char *name, int32_t argc,
                       const char **keys, void *args, int32_t line, int32_t mode, void *prepared)
{ rul_put(out,v_member_finish(*(Val *)receiver,name,(size_t)argc,keys,args,line,mode,*(Val *)prepared)); }
void rul_init_member_finish(void *out, void *receiver, const char *name, int32_t argc,
                       const char **keys, void *args, int32_t line, int32_t mode, void *prepared)
{ rul_init_put(out,v_member_finish(*(Val *)receiver,name,(size_t)argc,keys,args,line,mode,*(Val *)prepared)); }
void rul_check_index(void *receiver, void *index, int32_t line)
{ v_check_index_target(*(Val *)receiver,*(Val *)index,line); }
void rul_set_index(void *receiver, void *index, void *value, int32_t line)
{ v_set_index(*(Val *)receiver,*(Val *)index,*(Val *)value,line); }
void rul_check_member(void *receiver, const char *name, int32_t line)
{ v_check_member_target(*(Val *)receiver,name,line); }
void rul_set_member(void *receiver, const char *name, void *value, int32_t line)
{ v_set_member(*(Val *)receiver,name,*(Val *)value,line); }
void rul_new(void *out, void *klass, int32_t count, const char **keys, void *args, int32_t line)
{ rul_put(out,v_new(*(Val *)klass,(size_t)count,keys,args,line)); }
void rul_init_new(void *out, void *klass, int32_t count, const char **keys, void *args, int32_t line)
{ rul_init_put(out,v_new(*(Val *)klass,(size_t)count,keys,args,line)); }
void rul_import(void *out, int32_t id) { rul_put(out,rul_module_import(id)); }
void rul_init_import(void *out, int32_t id) { rul_init_put(out,rul_module_import(id)); }
void rul_import_all(void *env, void *module, int32_t line) { env_import_all(env,*(Val *)module,line); }
int32_t rul_panicking(void) { return ru_panicking; }
void rul_raise(void *reason, int32_t line, int32_t col) { ru_panic_raise(*(Val *)reason,line,col); }
void rul_catch(void *env, const char *name) { env_set(env,name,ru_panic_reason); ru_panic_clear(); }
void rul_missing_return(const char *name, int32_t line) { ru_fail(line,"函数「%s」没有执行「得」",name); }
int32_t rul_main(int32_t argc, char **argv, int32_t module, int32_t has_entry)
{
    Val root; int status=0;
    ru_init(); root=rul_module_import(module);
    if (ru_panicking) return ru_panic_uncaught();
    if (has_entry) {
        Val args=ru_arguments(argc,argv), entry=env_get(root.module,"元初",1), result;
        const char *keys[]={NULL};
        result=v_call(entry,1,keys,&args,1);
        if (ru_panicking) { v_drop(result); v_drop(entry); v_drop(args); return ru_panic_uncaught(); }
        if (result.kind!=RU_NUM || !isfinite(result.n) || result.n<0 || result.n>255 || (double)(unsigned)result.n!=result.n)
            ru_fail(1,"元初须返回 0 至 255 的整数");
        status=(int)result.n; v_drop(result); v_drop(entry); v_drop(args);
    }
    ru_shutdown(); return status;
}
