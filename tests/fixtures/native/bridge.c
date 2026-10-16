/* Test-owned fixture. Build locally; never download or execute a foreign DLL. */
#include <stdint.h>
#include <stddef.h>
#ifdef _WIN32
#include <windows.h>
#define API __declspec(dllexport)
#else
#define API __attribute__((visibility("default")))
#endif
API uint64_t echo_u64(uint64_t value) { return value; }
API int64_t echo_i64(int64_t value) { return value; }
API void *echo_pointer(void *value) { return value; }
struct Mixed { uint8_t tiny; uint64_t wide; int32_t tail; };
API uint64_t mixed_read(struct Mixed *value) { return value->wide + value->tiny; }
API void mixed_fill(struct Mixed *value) { value->tiny = 7; value->wide = UINT64_MAX; value->tail = -19; }
API uint32_t mixed_size(void) { return (uint32_t) sizeof(struct Mixed); }
API uint32_t mixed_wide_offset(void) { return (uint32_t) offsetof(struct Mixed, wide); }
API void fill_utf16(uint16_t *text) { text[0] = 0x4f60; text[1] = 0xd83d; text[2] = 0xde00; text[3] = 0; }
typedef int64_t (*Callback)(uint64_t);
API int64_t invoke_callback(Callback callback, uint64_t value) { return callback(value); }
API int64_t invoke_twice(Callback callback, uint64_t value) { return callback(value) + callback(value); }
API int32_t last_error_value(void) {
#ifdef _WIN32
    SetLastError(1234);
#endif
    return -1;
}

typedef void *(*PointerCallback)(void);
API void *invoke_pointer_callback(PointerCallback callback) { return callback(); }
