/* Owned Win64 acceptance fixture; no Python or fabricated memory addresses. */
#include <stdint.h>
#ifdef _WIN32
#define API __declspec(dllexport)
#else
#error This fixture is intentionally Windows-only
#endif
typedef int64_t (*DenseCallback)(uint32_t);
static uint32_t returns;
API int64_t dense_invoke(DenseCallback callback, uint32_t mode)
{
    int64_t result = callback(mode);
    ++returns; /* Must run even when the Ru callback has failed. */
    return result;
}
API uint32_t dense_returns(void) { return returns; }
