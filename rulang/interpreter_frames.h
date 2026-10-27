/* Opt-in LLVM frames for the Ru interpreter. Val slots remain contiguous:
 * generated argument arrays keep the unchanged private LLVM pointer ABI.
 * All slots start null. Every write is recorded once, including scalar writes,
 * so clear has exactly the original effect without scanning untouched slots. */
typedef struct RuLLVMFrame {
    size_t count, active_count;
    struct RuLLVMFrame *previous, *next;
    size_t *active;
    unsigned char *written;
    Val values[];
} RuLLVMFrame;
static RuLLVMFrame *ru_llvm_active_frames;
/* This host also tracks scalar writes for its reset protocol. Keep that
 * stronger bookkeeping when the ordinary emitter supplies a static root map. */
void rul_frame_roots(void *opaque,int32_t low,int32_t high)
{ (void)opaque;(void)low;(void)high; }
static RuFunction *rul_function_descriptor(int32_t id);
static RuClass *rul_class_descriptor(int32_t id);
static Val rul_module_import(int32_t id);

static void ru_interpreter_frames_reset(void) { ru_llvm_active_frames=NULL; }
static void rul_put(void *out,Val value)
{
    RuLLVMFrame *frame;uintptr_t address=(uintptr_t)out;
    for(frame=ru_llvm_active_frames;frame;frame=frame->previous) {
        uintptr_t begin=(uintptr_t)frame->values;
        if(address>=begin && address-begin<frame->count*sizeof(Val)) {
            size_t offset=(size_t)(address-begin),position=offset/sizeof(Val);
            if(offset%sizeof(Val))ru_fail(0,"LLVM 临时值地址未对齐");
            if(!frame->written[position]) {
                frame->written[position]=1;frame->active[frame->active_count++]=position;
            }
            break;
        }
    }
    /* Return values may point to a C bridge's initialized stack Val. They
     * retain normal ownership, and do not belong to a temporary frame. */
    v_drop(*(Val *)out);*(Val *)out=value;
}
static void rul_init_put(void *out,Val value) { rul_put(out,value); }
__attribute__((always_inline)) uint64_t rul_frame_size(int32_t count)
{
    if(count<0||(size_t)count>(SIZE_MAX-sizeof(RuLLVMFrame))/(sizeof(Val)+sizeof(size_t)+1))
        ru_fail(0,"LLVM 临时值过多");
    return sizeof(RuLLVMFrame)+(size_t)count*(sizeof(Val)+sizeof(size_t)+1);
}
__attribute__((always_inline)) void rul_frame_init(void *opaque,int32_t count)
{
    RuLLVMFrame *frame=opaque;size_t i;
    frame->count=(size_t)count;frame->active_count=0;
    frame->active=(size_t *)(frame->values+count);
    frame->written=(unsigned char *)(frame->active+count);
    memset(frame->written,0,(size_t)count);
    for(i=0;i<(size_t)count;++i)frame->values[i]=v_null();
    frame->previous=ru_llvm_active_frames;frame->next=NULL;
    if(ru_llvm_active_frames)ru_llvm_active_frames->next=frame;
    ru_llvm_active_frames=frame;
}
void *rul_frame_new(int32_t count)
{
    void *frame=ru_scratch_alloc((size_t)rul_frame_size(count),0);
    rul_frame_init(frame,count);return frame;
}
void *rul_slot(void *opaque,int32_t index)
{
    RuLLVMFrame *frame=opaque;
    if(index<0||(size_t)index>=frame->count)ru_fail(0,"LLVM 临时值索引越界");
    return &frame->values[index];
}
void rul_clear(void *opaque)
{
    RuLLVMFrame *frame=opaque;size_t i;
    for(i=0;i<frame->active_count;++i) {
        size_t index=frame->active[i];
        v_drop(frame->values[index]);frame->values[index]=v_null();frame->written[index]=0;
    }
    frame->active_count=0;
}
void rul_clear_count(void *opaque,int32_t count)
{
    RuLLVMFrame *frame=opaque;size_t i,kept=0;
    if(count<0||(size_t)count>frame->count)ru_fail(0,"LLVM 临时值清理越界");
    for(i=0;i<frame->active_count;++i) {
        size_t index=frame->active[i];
        if(index<(size_t)count) {
            v_drop(frame->values[index]);frame->values[index]=v_null();frame->written[index]=0;
        } else frame->active[kept++]=index;
    }
    frame->active_count=kept;
}
void rul_frame_drop(void *opaque)
{
    RuLLVMFrame *frame=opaque;
    rul_clear(frame);
    if(frame->next)frame->next->previous=frame->previous;
    else ru_llvm_active_frames=frame->previous;
    if(frame->previous)frame->previous->next=frame->next;
}
void rul_frame_free(void *opaque)
{
    rul_frame_drop(opaque);ru_scratch_free(opaque);
}

/* Match the ordinary emitter without weakening the host's written registry. */
__attribute__((always_inline)) uint64_t rul_local_frame_size(int32_t count)
{ return rul_frame_size(count); }
__attribute__((always_inline)) void rul_local_frame_init(void *opaque,int32_t count)
{ rul_frame_init(opaque,count); }
__attribute__((always_inline)) void rul_local_frame_roots(void *opaque,int32_t low,int32_t high)
{ rul_frame_roots(opaque,low,high); }
__attribute__((always_inline)) void *rul_local_slot(void *opaque,int32_t index,void *storage)
{ (void)storage;return rul_slot(opaque,index); }
void rul_local_clear_count(void *opaque,int32_t count) { rul_clear_count(opaque,count); }
/* Even an empty static mask must reset the host's dynamic written registry. */
void rul_local_clear_mask(void *opaque,int32_t count,int32_t low,int32_t high)
{ (void)low;(void)high;rul_clear_count(opaque,count); }

void rul_local_clear(void *opaque) { rul_clear(opaque); }
void rul_local_frame_drop(void *opaque) { rul_frame_drop(opaque); }
