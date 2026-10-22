'use strict';
const [RU_MI_OK, RU_MI_BOUNDS, RU_MI_OVERFLOW] = [0,1,2];

function ru_mi_kernel_0(p0, p1, p2) {
    let l0 = 0;
    let l1 = 0;
    l0 = p1;
    if (p2 < p1) { return {status: RU_MI_OVERFLOW, value: 0, line: 4, col: 10}; }
    let t1 = p2 - p1;
    let t2 = t1;
    for (let t3 = 0; t3 < t2; ++t3) {
        if (l0 >= p0.length) { return {status: RU_MI_BOUNDS, value: 0, line: 5, col: 15}; }
        let t4 = p0[l0];
        l1 = t4;
        let t5 = (l1 >= 128);
        if (!t5) {
            t5 = (l1 == 13);
        }
        let t6 = t5;
        if (!t6) {
            t6 = (l1 == 10);
        }
        let t7 = t6;
        if (!t7) {
            t7 = (l1 == 62);
        }
        if (t7) {
            break;
        }
        if (1 > 4294967295 - l0) { return {status: RU_MI_OVERFLOW, value: 0, line: 9, col: 15}; }
        let t8 = l0 + 1;
        l0 = t8;
    }
    if (l0 < p1) { return {status: RU_MI_OVERFLOW, value: 0, line: 11, col: 9}; }
    let t9 = l0 - p1;
    return {status: RU_MI_OK, value: t9, line: 0, col: 0};
}
module.exports = {ru_mi_kernel_0};
