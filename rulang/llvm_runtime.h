/* Private LLVM ABI v1. Included in exactly one runtime translation unit.
 * LLVM sees only void pointers, fixed-width integers and doubles. Val/Env and
 * C aggregate calling conventions stay entirely on the C side of the boundary.
 * A frame owns initialized Val slots; all produced values own one GC root.
 * Generated code clears temporaries at statement/unwind boundaries, and copies
 * a returned value into its caller's slot before disposing its own frame.
 */
typedef struct { size_t count; Val values[]; } RuLLVMFrame;
static RuFunction *rul_function_descriptor(int32_t id);
static RuClass *rul_class_descriptor(int32_t id);
static Val rul_module_import(int32_t id);

static void rul_put(void *out, Val value)
{
    v_drop(*(Val *)out); *(Val *)out = value;
}
void *rul_frame_new(int32_t count)
{
    RuLLVMFrame *frame; size_t i;
    if (count < 0 || (size_t)count > (SIZE_MAX-sizeof(*frame))/sizeof(Val))
        ru_fail(0, "LLVM 临时值过多");
    frame = ru_scratch_alloc(sizeof(*frame)+(size_t)count*sizeof(Val), 0);
    frame->count = (size_t)count;
    for (i=0; i<frame->count; ++i) frame->values[i] = v_null();
    return frame;
}
void *rul_slot(void *opaque, int32_t index)
{
    RuLLVMFrame *frame = opaque;
    if (index < 0 || (size_t)index >= frame->count) ru_fail(0, "LLVM 临时值索引越界");
    return &frame->values[index];
}
void rul_clear(void *opaque)
{
    RuLLVMFrame *frame = opaque; size_t i;
    for (i=0; i<frame->count; ++i) { v_drop(frame->values[i]); frame->values[i]=v_null(); }
}
__attribute__((always_inline)) void rul_clear_count(void *opaque, int32_t count)
{
    RuLLVMFrame *frame = opaque; size_t i;
    if (count < 0 || (size_t)count > frame->count) ru_fail(0, "LLVM 临时值清理越界");
    for (i=0; i<(size_t)count; ++i) { v_drop(frame->values[i]); frame->values[i]=v_null(); }
}
void rul_frame_free(void *opaque) { rul_clear(opaque); ru_scratch_free(opaque); }
void rul_copy(void *out, void *value) { rul_put(out, v_copy(*(Val *)value)); }
void rul_null(void *out) { rul_put(out, v_null()); }
void rul_number(void *out, double value) { rul_put(out, v_num(value)); }
void rul_fact(void *out, int32_t value) { rul_put(out, v_fact(value)); }
void rul_string(void *out, const char *value) { rul_put(out, v_str(value)); }
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
/* A cache belongs to one generated function invocation and its root Env.
 * Bindings never move or disappear while that Env is rooted. Cache the binding,
 * not its mutable value. Ancestor hits must remain uncached: a later local
 * declaration can shadow them. Nested block/rescue environments are excluded. */
void rul_get_cached(void *out, void *opaque, const char *name, int32_t line, void **cache)
{
    Env *env=opaque; RuBinding *binding=*cache;
    if (!binding) { binding=env_find_local(env,name); *cache=binding; }
    rul_put(out,binding ? v_copy(binding->value) : env_get(env,name,line));
}
void rul_bind(void *env, const char *name, void *value, int32_t line)
{ env_bind(env,name,*(Val *)value,line); }
void rul_bind_cached(void *opaque, const char *name, void *value, int32_t line, void **cache)
{
    Env *env=opaque; RuBinding *binding=*cache;
    if (!binding) binding=env_find_local(env,name);
    if (binding && !binding->reserved && strcmp(name,"读")) binding->value=*(Val *)value;
    else { env_bind(env,name,*(Val *)value,line); binding=env_find_local(env,name); }
    *cache=binding;
}
void rul_declare(void *env, const char *name, void *value)
{ env_declare(env,name,*(Val *)value); }
void rul_function(void *out, int32_t id, void *env, void *self)
{ rul_put(out,v_function(rul_function_descriptor(id),env,self ? *(Val *)self : v_null())); }
void rul_class(void *out, int32_t id) { rul_put(out,v_class(rul_class_descriptor(id))); }
void rul_class_ready(int32_t id, int32_t line) { ru_class_ready(rul_class_descriptor(id),line); }
void rul_reference(void *out, void *value, int32_t procedure, int32_t line)
{ rul_put(out,v_function_reference(*(Val *)value,procedure,line)); }
void rul_member_reference(void *out, void *receiver, const char *name, int32_t line)
{ rul_put(out,v_member_reference(*(Val *)receiver,name,line)); }
void rul_call(void *out, void *callee, int32_t count, const char **keys, void *args, int32_t line)
{ rul_put(out,v_call(*(Val *)callee,(size_t)count,keys,args,line)); }
void rul_read(void *out, void *prompt, int32_t line) { rul_put(out,read_input(*(Val *)prompt,line)); }
void rul_print(void *value, int32_t line) { v_print(*(Val *)value,line); }
void rul_array(void *out, int32_t count, void *values, int32_t line)
{ rul_put(out,v_array((size_t)count,values,line)); }
void rul_map(void *out, int32_t line) { rul_put(out,v_map_new(line)); }
void rul_map_put(void *map, void *key, void *value, int32_t line)
{ Val result=v_map_put(*(Val *)map,*(Val *)key,*(Val *)value,line); v_drop(result); }
void rul_unary(void *out, const char *op, void *arg, int32_t line)
{ rul_put(out,v_unary(op,*(Val *)arg,line)); }
void rul_binary(void *out, const char *op, void *left, void *right, int32_t line)
{ rul_put(out,v_binary(op,*(Val *)left,*(Val *)right,line)); }
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
void rul_index(void *out, void *receiver, void *index, int32_t line)
{ rul_put(out,v_index(*(Val *)receiver,*(Val *)index,line)); }
void rul_slice(void *out, void *receiver, void *start, void *end, int32_t line)
{ rul_put(out,v_slice(*(Val *)receiver,*(Val *)start,*(Val *)end,line)); }
void rul_member_prepare(void *out, void *receiver, const char *name, int32_t argc, int32_t line, int32_t *mode)
{ int selected; Val result=v_member_prepare(*(Val *)receiver,name,(size_t)argc,line,&selected); *mode=selected; rul_put(out,result); }
void rul_member_finish(void *out, void *receiver, const char *name, int32_t argc,
                       const char **keys, void *args, int32_t line, int32_t mode, void *prepared)
{ rul_put(out,v_member_finish(*(Val *)receiver,name,(size_t)argc,keys,args,line,mode,*(Val *)prepared)); }
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
void rul_import(void *out, int32_t id) { rul_put(out,rul_module_import(id)); }
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
