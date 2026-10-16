/* Repository-owned acceptance fixture. Never dereference fabricated addresses.
 * Windows callbacks are driven here so the generated executable, rather than
 * Python/ctypes, owns every ABI transition under test. */
#include <stdint.h>
#include <stddef.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#define API __declspec(dllexport)
#else
#define API __attribute__((visibility("default")))
#endif

API uint64_t echo_u64(uint64_t value) { return value; }
API int64_t echo_i64(int64_t value) { return value; }
API float echo_f32(float value) { return value; }
API double nonfinite_f64(void) { return INFINITY; }
typedef float (*FloatCallback)(float);
API float invoke_f32(FloatCallback callback) { return callback(2.5f); }
API void *echo_pointer(void *value) { return value; }
API void reject_probe(void *value)
{
    (void)value;
    fputs("unexpected-native-call\n", stdout);
    fflush(stdout);
}

struct Mixed { uint8_t tiny; uint64_t wide; int32_t tail; };
API uint32_t mixed_size(void) { return (uint32_t)sizeof(struct Mixed); }
API uint32_t mixed_wide_offset(void) { return (uint32_t)offsetof(struct Mixed, wide); }
API uint32_t mixed_tail_offset(void) { return (uint32_t)offsetof(struct Mixed, tail); }
API void mixed_fill(struct Mixed *value)
{
    value->tiny = 7; value->wide = UINT64_MAX; value->tail = -19;
}
API void fill_utf16(uint16_t *text)
{
    text[0] = 0x4f60; text[1] = 0xd83d; text[2] = 0xde00; text[3] = 0;
}

/* Positional Win64 GP/XMM registers plus stack arguments, including exact
 * values that cannot be represented by a Ru binary64 number. */
API double mixed_registers(int64_t a, double b, uint64_t c, float d,
                           int32_t e, double f, uint64_t g, float h)
{
    if (a != INT64_MIN || b != 1.25 || c != UINT64_MAX || d != 2.5f ||
        e != -17 || f != 4.75 || g != UINT64_C(9007199254740993) || h != 8.5f)
        return -999.0;
    return b + d + f + h;
}
typedef double (*MixedCallback)(int64_t, double, uint64_t, float,
                                int32_t, double, uint64_t, float);
API double invoke_mixed(MixedCallback callback)
{
    return callback(INT64_MIN, 1.25, UINT64_MAX, 2.5f,
                    -17, 4.75, UINT64_C(9007199254740993), 8.5f);
}

typedef int64_t (*Callback)(uint64_t);
static int32_t returned_count;
static int32_t hook_count;
static Callback saved_callback;
API int64_t invoke_callback(Callback callback, uint64_t value)
{
    int64_t result = callback(value);
    ++returned_count; /* Must execute even after a Ru callback error. */
    return result;
}
API int64_t invoke_twice(Callback callback, uint64_t value)
{
    int64_t first = invoke_callback(callback, value);
    return first + invoke_callback(callback, value);
}
API int32_t callback_returns(void) { return returned_count; }
API void mark_failure(int32_t value) { hook_count += value; }
API int32_t failure_count(void) { return hook_count; }
API void save_callback(Callback callback) { saved_callback = callback; }
API int64_t invoke_saved(uint64_t value)
{
    return saved_callback ? invoke_callback(saved_callback, value) : -999;
}

typedef void *(*PointerCallback)(void);
static const char *saved_text;
API void capture_pointer(PointerCallback callback)
{
    saved_text = (const char *)callback();
}
API int32_t saved_text_matches(void)
{
    return saved_text != NULL && strcmp(saved_text, "retained-owner") == 0;
}
struct Inner { const char *text; };
struct Outer { struct Inner inner; };
API int32_t nested_text_matches(const struct Outer *value)
{
    return value->inner.text != NULL &&
           strcmp(value->inner.text, "nested-owner") == 0;
}

API int32_t last_error_value(void)
{
#ifdef _WIN32
    SetLastError(4321);
#endif
    return -1;
}
API uint32_t callback_last_error(Callback callback)
{
#ifdef _WIN32
    SetLastError(1234);
    (void)invoke_callback(callback, 1);
    return GetLastError();
#else
    (void)invoke_callback(callback, 1);
    return 0;
#endif
}

#ifdef _WIN32
struct ThreadCall { Callback callback; uint64_t value; int64_t result; };
static DWORD WINAPI foreign_callback(void *opaque)
{
    struct ThreadCall *call = (struct ThreadCall *)opaque;
    call->result = call->callback(call->value);
    return 0;
}
API int64_t invoke_foreign_thread(Callback callback, uint64_t value)
{
    struct ThreadCall call;
    HANDLE thread;
    call.callback = callback; call.value = value; call.result = -999;
    thread = CreateThread(NULL, 0, foreign_callback, &call, 0, NULL);
    if (!thread) return -998;
    /* The test runner bounds and kills the whole child process if this stalls.
     * Do not return with a worker still referring to the stack allocation. */
    if (WaitForSingleObject(thread, INFINITE) != WAIT_OBJECT_0) ExitProcess(97);
    CloseHandle(thread);
    return call.result;
}
#endif
