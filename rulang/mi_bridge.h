/* Internal synchronous readonly bridge. No raw address input, callbacks or
 * user-selectable function pointer. Generated effect-checked kernels only. */
typedef struct {
    RuNative *root;
    Val owners;
    RuMiView view;
} RuMiSourceBorrow;
static RuNative *ru_mi_memory(Val value, int line)
{
    RuNative *memory = rn_expect(value, RN_MEMORY, line, "密视图需要拥有型 NativeMemory");
    if (rn_platform_thread() != ru_native_thread_id)
        ru_fail(line, "密视图只能在所属执行线程使用");
    if (ru_native_depth || ru_native_callback_depth)
        ru_fail(line, "密视图暂不支持原生调用或回调重入");
    rn_memory_check(memory, line);
    if (memory->as.memory.size > UINT32_MAX)
        ru_fail(line, "密视图长度超出 u32");
    return memory;
}
static RuMiSourceBorrow ru_mi_acquire(Val value, RuNative *memory, int line)
{
    RuMiSourceBorrow borrow;
    borrow.root = memory->as.memory.root ? memory->as.memory.root : memory;
    if (borrow.root->as.memory.mi_read_borrows == SIZE_MAX || ru_mi_active_borrows == SIZE_MAX)
        ru_fail(line, "密视图借用计数溢出");
    /* All checks and allocating owner snapshots precede counter increments.
     * Snapshot is a real rooted Val retaining the existing complete owner graph. */
    borrow.owners = rn_owners(value, 1, line);
    borrow.view.data = memory->as.memory.size ? memory->as.memory.data : NULL;
    borrow.view.length = (uint32_t)memory->as.memory.size;
    ++borrow.root->as.memory.mi_read_borrows;
    ++ru_mi_active_borrows;
    return borrow;
}
static void ru_mi_release(RuMiSourceBorrow *borrow)
{
    --borrow->root->as.memory.mi_read_borrows;
    --ru_mi_active_borrows;
    v_drop(borrow->owners);
    borrow->root = NULL; borrow->owners = v_null();
    borrow->view.data = NULL; borrow->view.length = 0;
}
