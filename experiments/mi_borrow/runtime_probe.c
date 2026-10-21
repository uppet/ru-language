#include <assert.h>
/* Traps here are a TEST HARNESS around rejected operations, never callbacks
 * inside rn_mi_scan. The borrow is acquired outside each trap's snapshot. */
#define EXPECT_FAILURE(EXPR, TEXT) do { \
    RuNativeTrap *test_trap = rn_trap_new(); assert(test_trap); \
    ru_native_trap = test_trap; \
    if (!setjmp(test_trap->jump)) { (void)(EXPR); assert(!"expected failure"); } \
    else { assert(strstr(test_trap->message, TEXT)); rn_trap_restore(test_trap); } \
    ru_native_trap = test_trap->previous; rn_trap_release(test_trap); \
} while (0)
static Val test_type(RuNative *child)
{
    Val name = v_str("x"), pair[2], row, fields, result;
    pair[0] = name; pair[1] = rn_value(child);
    row = v_array(2, pair, 0); fields = v_array(1, &row, 0);
    result = rn_struct(fields, 0);
    v_drop(fields); v_drop(row); v_drop(name); return result;
}
static Val test_outer(RuNative *child)
{
    Val names[2] = {v_str("pad"), v_str("x")}, pair[2], rows[2], fields, result;
    pair[0] = names[0]; pair[1] = rn_value(ru_native_primitives[RN_U8]);
    rows[0] = v_array(2, pair, 0);
    pair[0] = names[1]; pair[1] = rn_value(child); rows[1] = v_array(2, pair, 0);
    fields = v_array(2, rows, 0); result = rn_struct(fields, 0);
    v_drop(fields); v_drop(rows[0]); v_drop(rows[1]); v_drop(names[0]); v_drop(names[1]);
    return result;
}
static Val test_close(Val memory)
{
    Val result;
    assert(ru_native_member(memory, "关闭", 0, NULL, NULL, 0, &result));
    return result;
}
int main(void)
{
    Val t1, t2, t3, root, middle, view, field, retained, result, closed_view, bad_field;
    RuNative *root_object, *view_object;
    RuMiBorrow borrow;
    RuNative dummy_function;
    size_t initial;
    ru_init(); ru_native_builtins(NULL); ru_gc(); initial = ru_live;
    t1 = test_type(ru_native_primitives[RN_U16]);
    t2 = test_type((RuNative *)t1.heap); t3 = test_outer((RuNative *)t2.heap);
    root = rn_memory((RuNative *)t3.heap, ((RuNative *)t3.heap)->as.type.size, 0); field = v_str("x");
    middle = rn_memory_read((RuNative *)root.heap, field, 0);
    view = rn_memory_read((RuNative *)middle.heap, field, 0);
    result = rn_memory_write((RuNative *)view.heap, field, v_num(2573), 0); v_drop(result);
    assert(rn_mi_scan(view, 0, 2, 0, 0).n == 1);
    EXPECT_FAILURE(rn_mi_scan(view, -1, 2, 0, 0), "u32");
    EXPECT_FAILURE(rn_mi_scan(view, 0, 3, 0, 0), "边界");
    EXPECT_FAILURE(rn_mi_scan(view, 0, 2, INT64_C(4294967296), 0), "u32");
    EXPECT_FAILURE(rn_mi_scan(view, 0, 2, UINT32_MAX, 0), "status");
    assert(!ru_mi_active_borrows);
    assert(rn_mi_scan(view, 2, 0, 0, 0).n == 0);
    assert(rn_mi_scan(view, 0, 2, 0, 0).n == 1);
    ru_native_callback_depth = 1;
    EXPECT_FAILURE(rn_mi_scan(view, 0, 2, 0, 0), "重入");
    ru_native_callback_depth = 0;
    ru_native_depth = 1;
    EXPECT_FAILURE(rn_mi_scan(view, 0, 2, 0, 0), "重入");
    ru_native_depth = 0;
    closed_view = rn_memory_read((RuNative *)middle.heap, field, 0);
    test_close(closed_view); bad_field = v_str("missing");
    assert(((RuNative *)view.heap)->as.memory.offset > 0);
    borrow = rn_mi_acquire(view, 0, 2, 0, 0);
    EXPECT_FAILURE(rn_memory_write((RuNative *)closed_view.heap, bad_field, v_null(), 0), "关闭");
    EXPECT_FAILURE(rn_memory_write((RuNative *)view.heap, bad_field, v_null(), 0), "未知结构字段");
    EXPECT_FAILURE(rn_memory_write((RuNative *)view.heap, field, v_null(), 0), "借用");
    v_drop(closed_view); v_drop(bad_field);
    root_object = borrow.root;
    retained = ((RuArray *)borrow.owners.heap)->items[0];
    view_object = (RuNative *)retained.heap;
    /* Remove EVERY caller owner/type/view root; only rn_owners snapshot remains. */
    v_drop(root); v_drop(middle); v_drop(view);
    v_drop(t1); v_drop(t2); v_drop(t3);
    ru_gc();
    assert(mi_kernel(borrow.data, borrow.length, 0).count == 1);
    EXPECT_FAILURE(test_close(rn_value(root_object)), "借用");
    EXPECT_FAILURE(test_close(rn_value(view_object->as.memory.parent)), "借用");
    EXPECT_FAILURE(test_close(retained), "借用");
    EXPECT_FAILURE(rn_memory_write(view_object, field, v_num(0), 0), "借用");
    EXPECT_FAILURE(rn_memory_write(root_object, field, rn_value(view_object->as.memory.parent), 0), "借用");
    memset(&dummy_function, 0, sizeof(dummy_function));
    EXPECT_FAILURE(rn_invoke(&dummy_function, v_null(), 0), "effect");
    assert(root_object->as.memory.mi_read_borrows == 1 && ru_mi_active_borrows == 1);
    assert(rn_mi_scan(retained, 0, 2, 0, 0).n == 1);
    assert(root_object->as.memory.mi_read_borrows == 1);
    retained = v_copy(retained); /* keep a real caller owner for post-release use */
    rn_mi_release(&borrow);
    assert(!root_object->as.memory.mi_read_borrows && !ru_mi_active_borrows);
    EXPECT_FAILURE(rn_memory_write(view_object, field, v_null(), 0), "原生标量");
    result = rn_memory_write(view_object, field, v_num(10), 0); v_drop(result);
    assert(rn_mi_scan(retained, 0, 2, 0, 0).n == 1);
    test_close(rn_value(view_object->as.memory.parent));
    EXPECT_FAILURE(rn_mi_scan(retained, 0, 2, 0, 0), "关闭");
    assert(!root_object->closed); /* old view-close behavior remains local */
    v_drop(retained); v_drop(field); ru_gc(); assert(ru_live == initial);
    puts("real owner borrow checks passed"); ru_shutdown(); return 0;
}
