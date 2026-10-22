#include <stdint.h>
#include <stddef.h>
enum { RU_MI_OK, RU_MI_BOUNDS, RU_MI_OVERFLOW };
typedef struct { const uint8_t *data; uint32_t length; } RuMiView;
typedef struct { int status; uint32_t value, line, col; } RuMiResult;

static RuMiResult ru_mi_kernel_0(RuMiView p0, uint32_t p1, uint32_t p2) {
    (void)p0;
    (void)p1;
    (void)p2;
    uint32_t l0 = 0;
    (void)l0;
    uint8_t l1 = 0;
    (void)l1;
    l0 = p1;
    if (p2 < p1) { return (RuMiResult){RU_MI_OVERFLOW, 0, 4, 10}; }
    uint32_t t1 = p2 - p1;
    uint32_t t2 = t1;
    for (uint32_t t3 = 0; t3 < t2; ++t3) {
        if (l0 >= p0.length) { return (RuMiResult){RU_MI_BOUNDS, 0, 5, 15}; }
        uint8_t t4 = p0.data[l0];
        l1 = t4;
        int t5 = (l1 >= 128u);
        if (!t5) {
            t5 = (l1 == 13u);
        }
        int t6 = t5;
        if (!t6) {
            t6 = (l1 == 10u);
        }
        int t7 = t6;
        if (!t7) {
            t7 = (l1 == 62u);
        }
        if (t7) {
            break;
        }
        if (1u > 4294967295u - l0) { return (RuMiResult){RU_MI_OVERFLOW, 0, 9, 15}; }
        uint32_t t8 = l0 + 1u;
        l0 = t8;
    }
    if (l0 < p1) { return (RuMiResult){RU_MI_OVERFLOW, 0, 11, 9}; }
    uint32_t t9 = l0 - p1;
    return (RuMiResult){RU_MI_OK, t9, 0, 0};
}