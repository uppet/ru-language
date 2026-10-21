// Generated semantic model. No native-address or no-GC promise for JS.
'use strict';
const [MI_OK, MI_BOUNDS, MI_OVERFLOW, MI_CLOSED, MI_BORROWED, MI_RANGE] = [0,1,2,3,4,5];
function truthU32(value) { return true; }
function kernel(data, length, seed) {
    let local_0 = seed;
    let local_1 = 0;
    let local_2 = 0;
    let local_3 = 0;
    if (true) {
        while ((local_1 < length)) {
            if (local_1 >= length) return {status: MI_BOUNDS, count: local_0};
            const byte_1 = data[local_1];
            local_3 = byte_1;
            if (((local_3 == 13) || ((local_3 == 10) && (local_2 != 13)))) {
                if (1 > 4294967295 - local_0) return {status: MI_OVERFLOW, count: local_0};
                local_0 += 1;
            }
            local_2 = local_3;
            if (1 > 4294967295 - local_1) return {status: MI_OVERFLOW, count: local_0};
            local_1 += 1;
        }
    }
    return {status: MI_OK, count: local_0};
}
function u32(x) { return Number.isInteger(x) && x >= 0 && x <= 4294967295; }
class Owner {
    #data; #closed = false; #borrows = 0;
    constructor(bytes) {
        if (!(bytes instanceof Uint8Array) || bytes.length > 4294967295)
            throw new TypeError('需要范围内的字节输入');
        // Explicit copy at owner creation; no arbitrary external mutable alias.
        this.#data = new Uint8Array(bytes);
    }
    get borrows() { return this.#borrows; }
    close() {
        if (this.#borrows) return MI_BORROWED;
        this.#closed = true; this.#data = null; return MI_OK;
    }
    scan(offset, length, seed) {
        if (!u32(seed)) return {status:MI_RANGE, count:0};
        if (!u32(offset) || !u32(length)) return {status:MI_RANGE, count:seed};
        if (this.#closed) return {status:MI_CLOSED, count:seed};
        if (offset > this.#data.length || length > this.#data.length - offset)
            return {status:MI_BOUNDS, count:seed};
        ++this.#borrows;
        try { return kernel(this.#data.subarray(offset, offset+length), length, seed); }
        finally { --this.#borrows; }
    }
}
function scan(owner, offset, length, seed=0) {
    if (!(owner instanceof Owner)) throw new TypeError('需要受管理 owner');
    return owner.scan(offset, length, seed);
}
module.exports = {Owner, scan, truthU32};
