/* Generated experiment, not production Ru syntax. MIT: repository LICENSE. */
#ifndef MI_KERNEL_H
#define MI_KERNEL_H
#include <stdint.h>
#include <stddef.h>
enum { MI_OK, MI_BOUNDS, MI_OVERFLOW, MI_CLOSED, MI_BORROWED, MI_RANGE };
typedef struct { int status; uint32_t count; } MiResult;
/* Internal-only owner/view; callers must supply genuine storage extent.
   No raw user addresses. Thread-confined; not an FFI or concurrency protocol. */
typedef struct { const uint8_t *data; uint32_t size; uint32_t borrows; int closed; } MiOwner;
static inline int mi_close(MiOwner *owner) {
    if (owner->borrows) return MI_BORROWED;
    owner->closed = 1; return MI_OK;
}
static inline int mi_truth_u32(uint32_t value) { (void)value; return 1; }
static MiResult mi_kernel(const uint8_t *data, uint32_t length, uint32_t seed) {
    uint32_t local_0 = seed;
    uint32_t local_1 = 0u;
    uint8_t local_2 = 0u;
    uint8_t local_3 = 0u;
    if (1) {
        while ((local_1 < length)) {
            if (local_1 >= length) return (MiResult){MI_BOUNDS, local_0};
            uint8_t byte_1 = data[local_1];
            local_3 = byte_1;
            if (((local_3 == 13u) || ((local_3 == 10u) && (local_2 != 13u)))) {
                if (1u > UINT32_MAX - local_0) return (MiResult){MI_OVERFLOW, local_0};
                local_0 += 1u;
            }
            local_2 = local_3;
            if (1u > UINT32_MAX - local_1) return (MiResult){MI_OVERFLOW, local_0};
            local_1 += 1u;
        }
    }
    return (MiResult){MI_OK, local_0};
}
/* Internal scalar failure state is NOT a C ABI signature extension. */
static MiResult mi_scan(MiOwner *owner, uint32_t offset, uint32_t length, uint32_t seed) {
    if (owner->closed) return (MiResult){MI_CLOSED, seed};
    if (offset > owner->size || length > owner->size - offset)
        return (MiResult){MI_BOUNDS, seed};
    if ((length && !owner->data) || owner->borrows == UINT32_MAX)
        return (MiResult){MI_RANGE, seed};
    ++owner->borrows;
    /* Avoid even +0 arithmetic on NULL for the legal empty view. */
    const uint8_t *view = length ? owner->data + offset : NULL;
    MiResult result = mi_kernel(view, length, seed);
    --owner->borrows;
    return result;
}
/* Fixture ordinary-input adapter: validate BEFORE any uint32_t narrowing. */
static inline MiResult mi_scan_checked(MiOwner *owner, int64_t offset, int64_t length, int64_t seed) {
    if (seed < 0 || seed > UINT32_MAX) return (MiResult){MI_RANGE, 0};
    if (offset < 0 || offset > UINT32_MAX || length < 0 || length > UINT32_MAX)
        return (MiResult){MI_RANGE, (uint32_t)seed};
    return mi_scan(owner, (uint32_t)offset, (uint32_t)length, (uint32_t)seed);
}
#endif
