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
void *rul_frame_new(int32_t count)
{
    RuLLVMFrame *frame;size_t i;
    if(count<0||(size_t)count>(SIZE_MAX-sizeof(*frame))/(sizeof(Val)+sizeof(size_t)+1))
        ru_fail(0,"LLVM 临时值过多");
    frame=ru_scratch_alloc(sizeof(*frame)+(size_t)count*(sizeof(Val)+sizeof(size_t)+1),0);
    frame->count=(size_t)count;frame->active_count=0;
    frame->active=(size_t *)(frame->values+count);
    frame->written=(unsigned char *)(frame->active+count);
    memset(frame->written,0,(size_t)count);
    for(i=0;i<(size_t)count;++i)frame->values[i]=v_null();
    frame->previous=ru_llvm_active_frames;frame->next=NULL;
    if(ru_llvm_active_frames)ru_llvm_active_frames->next=frame;
    ru_llvm_active_frames=frame;return frame;
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
void rul_frame_free(void *opaque)
{
    RuLLVMFrame *frame=opaque;
    rul_clear(frame);
    if(frame->next)frame->next->previous=frame->previous;
    else ru_llvm_active_frames=frame->previous;
    if(frame->previous)frame->previous->next=frame->next;
    ru_scratch_free(frame);
}
