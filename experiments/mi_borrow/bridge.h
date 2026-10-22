/* Private synchronous bridge over the REAL native owner graph. No exported
 * language member, raw-address entry, callback or arbitrary function pointer.
 * Include after generated native runtime and experiments/mi_kernel/kernel.h.
 * Caller is trusted generated code on the owning runtime thread. */
typedef struct {
    RuNative *root;
    Val owners;
    const uint8_t *data;
    uint32_t length;
} RuMiBorrow;
static RuMiBorrow rn_mi_acquire(Val value, int64_t offset, int64_t length,
                               int64_t seed, int line)
{
    RuMiBorrow borrow;
    RuNative *memory = rn_expect(value, RN_MEMORY, line, "密视图需要拥有型 NativeMemory");
    if (rn_platform_thread() != ru_native_thread_id)
        ru_fail(line, "密视图只能在所属执行线程使用");
    if (ru_native_depth || ru_native_callback_depth)
        ru_fail(line, "密视图暂不支持原生调用或回调重入");
    rn_memory_check(memory, line);
    if (offset < 0 || length < 0 || seed < 0 || offset > UINT32_MAX ||
        length > UINT32_MAX || seed > UINT32_MAX)
        ru_fail(line, "密视图范围须为 u32");
    if ((uint64_t)offset > memory->as.memory.size ||
        (uint64_t)length > memory->as.memory.size - (size_t)offset)
        ru_fail(line, "密视图超出缓冲边界");
    borrow.root = memory->as.memory.root ? memory->as.memory.root : memory;
    if (borrow.root->as.memory.mi_read_borrows == SIZE_MAX || ru_mi_active_borrows == SIZE_MAX)
        ru_fail(line, "密视图借用计数溢出");
    /* All potentially throwing operations PRECEDE both counter increments. */
    borrow.owners = rn_owners(value, 1, line);
    borrow.data = length ? memory->as.memory.data + (size_t)offset : NULL;
    borrow.length = (uint32_t)length;
    ++borrow.root->as.memory.mi_read_borrows;
    ++ru_mi_active_borrows;
    return borrow;
}
static void rn_mi_release(RuMiBorrow *borrow)
{
    --borrow->root->as.memory.mi_read_borrows;
    --ru_mi_active_borrows;
    v_drop(borrow->owners);
    borrow->root = NULL; borrow->owners = v_null(); borrow->data = NULL;
}
static Val rn_mi_scan(Val memory, int64_t offset, int64_t length, int64_t seed, int line)
{
    RuMiBorrow borrow = rn_mi_acquire(memory, offset, length, seed, line);
    /* Fixed generated kernel: no runtime allocation, ru_fail, longjmp, FFI or
     * callbacks. DO NOT substitute another entry without effect verification. */
    MiResult result = mi_kernel(borrow.data, borrow.length, (uint32_t)seed);
    rn_mi_release(&borrow);
    if (result.status != MI_OK) ru_fail(line, "密内核失败，status=%d", result.status);
    return v_num((double)result.count);
}
