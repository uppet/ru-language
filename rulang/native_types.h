/* Included only in explicitly native-enabled generated applications. */
#include <setjmp.h>
#include <inttypes.h>
#include <limits.h>
#include <float.h>
#include <errno.h>

enum { RN_VOID, RN_I8, RN_U8, RN_I16, RN_U16, RN_I32, RN_U32,
       RN_I64, RN_U64, RN_INTPTR, RN_UINTPTR, RN_F32, RN_F64, RN_PTR, RN_STRUCT };
enum { RN_CONTEXT, RN_TYPE, RN_SCALAR, RN_MEMORY, RN_SIGNATURE,
       RN_LIBRARY, RN_FUNCTION, RN_CALLBACK, RN_OUTCOME };
typedef union RuNativeRaw { int64_t i; uint64_t u; float f32; double f64; void *p; } RuNativeRaw;
typedef struct RuNative RuNative;
typedef struct { Val name; RuNative *type; size_t offset; } RuNativeField;
struct RuNative {
    RuHeap gc;
    int tag, closed;
    /* All owning graph edges, including field pins and closure captures, are
     * traced. The runtime never infers ownership from an arbitrary address. */
    Val *edges;
    size_t edge_count, edge_capacity;
    union {
        struct { int code, bits, is_signed; size_t size, alignment, count; RuNativeField *fields; } type;
        struct { RuNative *type; RuNativeRaw raw; } scalar;
        struct { RuNative *type, *root, *parent; unsigned char *data; size_t size, offset, mi_read_borrows; size_t *pin_offsets, *pin_sizes; } memory;
        struct { int id, convention; RuNative *result; size_t count; RuNative *params[64]; } signature;
        struct { void *handle; } library;
        struct { RuNative *library, *signature; void *address; } function;
        struct { RuNative *signature; unsigned slot, active; size_t retained; } callback;
        struct { unsigned long error; } outcome;
    } as;
};
typedef struct { RuHeap *heap; size_t transient; } RuNativeRoot;
typedef struct RuNativeTrap {
    jmp_buf jump;
    struct RuNativeTrap *previous;
    RuNativeRoot *roots;
    size_t root_count;
    void *scratch;
    unsigned call_depth;
    const char *source;
    char message[4097];
    RuNativeRaw result;
} RuNativeTrap;
static RuNativeTrap *ru_native_trap;
static unsigned ru_native_depth, ru_native_callback_depth;
static size_t ru_mi_active_borrows;
static int ru_native_handling_failure;
static char ru_native_callback_error[4097];
static int ru_native_member(Val, const char *, size_t, const char **, Val *, int, Val *);
static void ru_native_dispose(RuNative *);
static void ru_native_shutdown(void);
static int ru_native_generated_signature(int, int, const int *, int);
static RuNativeRaw ru_native_generated_call(int, void *, const RuNativeRaw *);
static void *ru_native_generated_callback(int, unsigned);
static RuNativeRaw ru_native_callback_dispatch(unsigned, int, const RuNativeRaw *);
static void ru_fail(int, const char *, ...);
typedef struct {
    RuNative *object;
    RuNativeRaw fallback;
    uint32_t owner_thread;
    int signature;
} RuNativeSlot;
static RuNativeSlot ru_native_slots[1024];
static unsigned ru_native_slot_count;
