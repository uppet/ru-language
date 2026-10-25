/* Owned, nonblocking fixture for one-shot native budget cleanup. */
#include <stdint.h>
#ifdef _WIN32
#define API __declspec(dllexport)
#else
#define API __attribute__((visibility("default")))
#endif
typedef int64_t (*Callback)(uint64_t);
static uint64_t cleanup_calls;
API int64_t invoke_callback(Callback callback, uint64_t value) {
    return callback(value);
}
API int64_t invoke_twice(Callback callback, uint64_t value) {
    int64_t first = callback(value);
    return first + callback(value);
}
API void cleanup_increment(uint64_t amount) { cleanup_calls += amount; }
API uint64_t cleanup_count(uint64_t reset) {
    uint64_t result = cleanup_calls;
    if (reset) cleanup_calls = 0;
    return result;
}
API int64_t cleanup_then_callback(Callback callback, uint64_t value) {
    cleanup_calls++;
    return callback(value);
}
