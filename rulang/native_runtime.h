/* Trusted fixed-signature native bridge. Included only after explicit build
 * opt-in. Ru 数 remains binary64; all native scalars are separate heap values. */
#define RN_MAX_BUFFER ((size_t)16777216)
#define RN_MAX_U32_BATCH ((size_t)4096)
#define RN_SAFE_INTEGER UINT64_C(9007199254740991)
static RuNative *ru_native_primitives[14];
static Env ru_native_environment;
static int ru_native_ready;

static Val rn_value(RuNative *object)
{
    Val result = v_null(); result.kind = RU_NATIVE; result.heap = &object->gc; return result;
}
static Val rn_new(int tag, int line)
{
    RuNative *object = (RuNative *)ru_new_heap(sizeof(*object), RU_NATIVE, line);
    object->tag = tag; return rn_value(object);
}
static RuNative *rn_expect(Val value, int tag, int line, const char *message)
{
    if (value.kind != RU_NATIVE || ((RuNative *)value.heap)->tag != tag) ru_fail(line, "%s", message);
    return (RuNative *)value.heap;
}
static void rn_edge(RuNative *object, Val value, int line)
{
    if (object->edge_count == object->edge_capacity) {
        size_t capacity = object->edge_capacity ? object->edge_capacity * 2 : 8;
        Val *edges;
        if (capacity > SIZE_MAX / sizeof(*edges)) ru_fail(line, "原生所有权图过大");
        edges = (Val *)realloc(object->edges, capacity * sizeof(*edges));
        if (!edges) ru_fail(line, "内存不足");
        object->edges = edges; object->edge_capacity = capacity;
    }
    object->edges[object->edge_count++] = value;
}
static const char *rn_text(Val value, int line, const char *message)
{
    if (value.kind != RU_STR || memchr(value.s->data, 0, value.s->len)) ru_fail(line, "%s", message);
    return value.s->data;
}
static int rn_integral_type(RuNative *type)
{
    int code = type->as.type.code; return code >= RN_I8 && code <= RN_UINTPTR;
}
static uint64_t rn_mask(int bits)
{
    return bits == 64 ? UINT64_MAX : (UINT64_C(1) << bits) - 1;
}
static int64_t rn_signed_bits(uint64_t bits, int width)
{
    uint64_t mask = rn_mask(width), sign = UINT64_C(1) << (width - 1);
    bits &= mask;
    /* Avoid implementation-defined out-of-range unsigned-to-signed casts. */
    return bits & sign ? -1 - (int64_t)(mask ^ bits) : (int64_t)bits;
}
static void rn_memory_check(RuNative *memory, int line)
{
    for (; memory; memory = memory->as.memory.parent)
        if (memory->closed) ru_fail(line, "原生缓冲已关闭");
}
/* No change to legacy FFI when the private dense bridge is inactive. */
static void rn_memory_check_mutation(RuNative *memory, int line)
{
    RuNative *root = memory->as.memory.root ? memory->as.memory.root : memory;
    if (root->as.memory.mi_read_borrows)
        ru_fail(line, "密只读借用期间不能关闭或写入同根缓冲");
}
/* Check and optionally retain a snapshot of every owner reachable through an
 * argument. Reentrant code may mutate arrays and pins while the DLL uses them.
 * Temporary roots preserve bytes even after logical close. */
static Val rn_owners(Val value, int retain, int line)
{
    Val snapshot = v_array(1, &value, line);
    RuArray *array = (RuArray *)snapshot.heap;
    size_t at = 0;
    while (at < array->len) {
        Val current = array->items[at++];
        Val *children = NULL; size_t count = 0, i, j;
        if (current.kind == RU_NATIVE) {
            RuNative *object = (RuNative *)current.heap;
            if (object->tag == RN_MEMORY) rn_memory_check(object, line);
            if (object->tag == RN_CALLBACK && object->closed) ru_fail(line, "原生回调已关闭");
            /* Only ownership-bearing links are followed, not arbitrary Ru
             * closure graphs or descriptors. GC traces those independently. */
            if (object->tag == RN_SCALAR) { children = object->edges + 1; count = object->edge_count - 1; }
            else if (object->tag == RN_MEMORY) { children = object->edges + 1; count = object->edge_count - 1; }
        } else if (current.kind == RU_ARRAY) {
            children = ((RuArray *)current.heap)->items; count = ((RuArray *)current.heap)->len;
        }
        for (i = 0; i < count; ++i) {
            Val child = children[i];
            if (!child.heap) continue;
            for (j = 0; j < array->len; ++j) if (array->items[j].heap == child.heap) break;
            if (j == array->len) { Val ignored = v_append(snapshot, child, line); v_drop(ignored); }
        }
    }
    if (!retain) { v_drop(snapshot); return v_null(); }
    return snapshot;
}
static Val rn_scalar(RuNative *type, RuNativeRaw raw, Val owner, int line)
{
    Val result;
    if ((type->as.type.code == RN_F32 && !isfinite(raw.f32)) ||
        (type->as.type.code == RN_F64 && !isfinite(raw.f64))) ru_fail(line, "原生浮点结果不是有限数");
    result = rn_new(RN_SCALAR, line);
    ((RuNative *)result.heap)->as.scalar.type = type;
    ((RuNative *)result.heap)->as.scalar.raw = raw;
    rn_edge((RuNative *)result.heap, rn_value(type), line);
    if (owner.kind != RU_NULL) rn_edge((RuNative *)result.heap, owner, line);
    return result;
}
static Val rn_scalar_convert(RuNative *type, RuNativeRaw raw, Val source, int line)
{
    Val result = rn_scalar(type, raw, v_null(), line);
    if (source.kind == RU_NATIVE && ((RuNative *)source.heap)->tag == RN_SCALAR) {
        RuNative *from = (RuNative *)source.heap; size_t i;
        /* Preserve the original anchors, not each transient cast wrapper.
         * Recasting one resource must not consume 128 callback owner slots. */
        for (i = 1; i < from->edge_count; ++i) rn_edge((RuNative *)result.heap, from->edges[i], line);
    }
    return result;
}
typedef struct { uint64_t magnitude; int negative; } RuNativeInteger;
static RuNativeInteger rn_integer(Val value, int line)
{
    RuNativeInteger result = {0, 0};
    if (value.kind == RU_NUM) {
        if (!isfinite(value.n) || trunc(value.n) != value.n || fabs(value.n) > (double)RN_SAFE_INTEGER)
            ru_fail(line, "数转原生整数须为安全整数；大整数请使用精确十进制句");
        result.negative = value.n < 0; result.magnitude = (uint64_t)fabs(value.n);
    } else if (value.kind == RU_STR) {
        size_t i = 0;
        if (!value.s->len || value.s->len > 128) ru_fail(line, "原生整数需要精确十进制句");
        if (value.s->data[i] == '+' || value.s->data[i] == '-') result.negative = value.s->data[i++] == '-';
        if (i == value.s->len) ru_fail(line, "原生整数需要精确十进制句");
        for (; i < value.s->len; ++i) {
            unsigned c = (unsigned char)value.s->data[i];
            if (c < '0' || c > '9') ru_fail(line, "原生整数需要精确十进制句");
            if (result.magnitude > (UINT64_MAX - (c - '0')) / 10) ru_fail(line, "原生整数转换溢出");
            result.magnitude = result.magnitude * 10 + c - '0';
        }
    } else if (value.kind == RU_NATIVE && ((RuNative *)value.heap)->tag == RN_SCALAR) {
        RuNative *scalar = (RuNative *)value.heap, *type = scalar->as.scalar.type;
        rn_owners(value, 0, line);
        if (!rn_integral_type(type) && type->as.type.code != RN_PTR) ru_fail(line, "整数转换需要原生整数或指针");
        if (type->as.type.is_signed && scalar->as.scalar.raw.i < 0) {
            result.negative = 1; result.magnitude = (uint64_t)(-(scalar->as.scalar.raw.i + 1)) + 1;
        } else if (type->as.type.code == RN_PTR) result.magnitude = (uint64_t)(uintptr_t)scalar->as.scalar.raw.p;
        else result.magnitude = type->as.type.is_signed ? (uint64_t)scalar->as.scalar.raw.i : scalar->as.scalar.raw.u;
    } else ru_fail(line, "原生整数需要安全整数数、精确十进制句或原生整数");
    if (!result.magnitude) result.negative = 0;
    return result;
}
static size_t rn_bounded(Val value, size_t low, size_t high, int line, const char *label)
{
    RuNativeInteger integer = rn_integer(value, line);
    if (integer.negative || integer.magnitude < low || integer.magnitude > high) ru_fail(line, "%s超出范围", label);
    return (size_t)integer.magnitude;
}
static RuNativeRaw rn_convert(RuNative *type, Val value, int line)
{
    RuNativeRaw result; int code = type->as.type.code; memset(&result, 0, sizeof(result));
    if (rn_integral_type(type) || code == RN_PTR) {
        RuNativeInteger integer;
        uint64_t maximum = type->as.type.is_signed ? rn_mask(type->as.type.bits - 1) : rn_mask(type->as.type.bits);
        if (code == RN_PTR && value.kind == RU_NULL) return result;
        integer = rn_integer(value, line);
        if (integer.negative) {
            if (!type->as.type.is_signed || integer.magnitude > maximum + 1) ru_fail(line, "原生整数转换溢出");
            result.i = -1 - (int64_t)(integer.magnitude - 1);
        } else {
            if (integer.magnitude > maximum) ru_fail(line, "原生整数转换溢出");
            if (code == RN_PTR) result.p = (void *)(uintptr_t)integer.magnitude;
            else if (type->as.type.is_signed) result.i = (int64_t)integer.magnitude;
            else result.u = integer.magnitude;
        }
    } else if (code == RN_F32 || code == RN_F64) {
        double number;
        if (value.kind == RU_NUM) number = value.n;
        else if (value.kind == RU_NATIVE && ((RuNative *)value.heap)->tag == RN_SCALAR) {
            RuNative *scalar = (RuNative *)value.heap, *from = scalar->as.scalar.type;
            rn_owners(value, 0, line);
            if (from->as.type.code == RN_PTR || scalar->edge_count > 1) ru_fail(line, "指针或携带资源所有权的值不能转换为浮点");
            if (from->as.type.code == RN_F32) number = scalar->as.scalar.raw.f32;
            else if (from->as.type.code == RN_F64) number = scalar->as.scalar.raw.f64;
            else if (from->as.type.is_signed) number = (double)scalar->as.scalar.raw.i;
            else number = (double)scalar->as.scalar.raw.u;
        } else { ru_fail(line, "原生浮点需要有限数"); number = 0; }
        if (!isfinite(number)) ru_fail(line, "原生浮点需要有限数");
        if (code == RN_F32) {
            if (fabs(number) > FLT_MAX) ru_fail(line, "f32转换溢出");
            result.f32 = (float)number;
            if (!isfinite(result.f32)) ru_fail(line, "f32转换溢出");
        }
        else result.f64 = number;
    } else ru_fail(line, "此类型不支持标量转换");
    return result;
}
static RuNativeRaw rn_marshal(RuNative *type, Val value, int line)
{
    RuNativeRaw result; memset(&result, 0, sizeof(result));
    if (type->as.type.code == RN_VOID) {
        if (value.kind != RU_NULL) ru_fail(line, "无值回调须返回空");
        return result;
    }
    if (type->as.type.code == RN_PTR) {
        RuNative *object;
        if (value.kind == RU_NULL) return result;
        if (value.kind != RU_NATIVE) ru_fail(line, "指针参数须为空、原生指针、拥有的缓冲或回调；数值请先显式转换为指针");
        object = (RuNative *)value.heap; rn_owners(value, 0, line);
        if (object->tag == RN_MEMORY) result.p = object->as.memory.data;
        else if (object->tag == RN_CALLBACK) result.p = ru_native_generated_callback(object->as.callback.signature->as.signature.id, object->as.callback.slot);
        else if (object->tag == RN_SCALAR && object->as.scalar.type->as.type.code == RN_PTR) result.p = object->as.scalar.raw.p;
        else ru_fail(line, "指针参数需要原生指针、拥有的缓冲或回调");
        return result;
    }
    if (value.kind == RU_NATIVE && ((RuNative *)value.heap)->tag == RN_SCALAR && ((RuNative *)value.heap)->as.scalar.type->as.type.code == RN_PTR)
        ru_fail(line, "指针转整数须先用 intptr／uintptr 的重释显式转换");
    if (value.kind != RU_NUM && !(value.kind == RU_NATIVE && ((RuNative *)value.heap)->tag == RN_SCALAR))
        ru_fail(line, "原生标量实参须为数或原生值；精确十进制句请先用类型的值转换");
    return rn_convert(type, value, line);
}
static Val rn_memory(RuNative *type, size_t size, int line)
{
    Val result;
    RuNative *object;
    if (!size || size > RN_MAX_BUFFER) ru_fail(line, "原生缓冲大小须为 1 至 16777216 字节");
    result = rn_new(RN_MEMORY, line); object = (RuNative *)result.heap;
    object->as.memory.type = type; object->as.memory.size = size;
    object->as.memory.data = (unsigned char *)ru_alloc(size, line);
    memset(object->as.memory.data, 0, size);
    rn_edge(object, type ? rn_value(type) : v_null(), line);
    rn_edge(object, v_null(), line); /* root owner of a nested view */
    return result;
}
static size_t rn_batch_index(Val value, size_t high, int line, const char *label)
{
    if (value.kind != RU_NUM || !isfinite(value.n) || trunc(value.n) != value.n)
        ru_fail(line, "读U32LE阵%s须为有限非负整数的普通数", label);
    if (value.n < 0 || value.n > (double)high) ru_fail(line, "读U32LE阵%s超出范围", label);
    return (size_t)value.n;
}
static Val rn_read_u32le_array(RuNative *memory, Val offset_value, Val count_value, int line)
{
    size_t offset, count, i; RuArray *array; Val result = v_null();
    const unsigned char *bytes;
    rn_memory_check(memory, line);
    offset = rn_batch_index(offset_value, memory->as.memory.size, line, "字节偏移");
    count = rn_batch_index(count_value, RN_MAX_U32_BATCH, line, "个数");
    if (offset % 4) ru_fail(line, "读U32LE阵字节偏移须为 4 的倍数");
    if (count > (memory->as.memory.size - offset) / 4) ru_fail(line, "读U32LE阵超出缓冲边界");
    array = (RuArray *)ru_new_heap(sizeof(*array), RU_ARRAY, line);
    result.kind = RU_ARRAY; result.heap = &array->gc;
    /* Publish length only after allocation/fill: callback OOM cleanup can
     * safely dispose the initially empty heap. Scalars need no extra roots. */
    array->items = (Val *)ru_alloc(count * sizeof(Val), line);
    bytes = memory->as.memory.data + offset;
    for (i = 0; i < count; ++i, bytes += 4) {
        uint32_t word = (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) |
                        ((uint32_t)bytes[2] << 16) | ((uint32_t)bytes[3] << 24);
        array->items[i] = v_num((double)word);
    }
    array->len = array->capacity = count;
    return result;
}
/* Transactional pin replacement: an allocation failure must leave both old
 * pointer bytes and their ownership intact in a surviving callback context. */
static void rn_replace_pins(RuNative *memory, size_t offset, size_t span, size_t additions,
                            const size_t *offsets, const size_t *spans, const Val *owners, int line)
{
    RuNative *root = memory->as.memory.root ? memory->as.memory.root : memory;
    size_t absolute = memory->as.memory.offset + offset, old_count = root->edge_count - 2;
    size_t i, count = 0, at = 0, *new_offsets, *new_spans;
    Val *new_edges;
    for (i = 0; i < old_count; ++i) {
        size_t start = root->as.memory.pin_offsets[i], end = start + root->as.memory.pin_sizes[i];
        if (!(start < absolute + span && absolute < end)) ++count;
    }
    if (count > SIZE_MAX / sizeof(Val) - additions - 2) ru_fail(line, "原生所有权图过大");
    count += additions;
    new_edges = (Val *)ru_scratch_alloc((count + 2) * sizeof(*new_edges), line);
    new_offsets = (size_t *)ru_scratch_alloc(count * sizeof(*new_offsets), line);
    new_spans = (size_t *)ru_scratch_alloc(count * sizeof(*new_spans), line);
    new_edges[0] = root->edges[0]; new_edges[1] = root->edges[1];
    for (i = 0; i < old_count; ++i) {
        size_t start = root->as.memory.pin_offsets[i], end = start + root->as.memory.pin_sizes[i];
        if (!(start < absolute + span && absolute < end)) {
            new_offsets[at] = start; new_spans[at] = root->as.memory.pin_sizes[i]; new_edges[at + 2] = root->edges[i + 2]; ++at;
        }
    }
    for (i = 0; i < additions; ++i) {
        new_offsets[at] = absolute + offsets[i]; new_spans[at] = spans[i]; new_edges[at + 2] = owners[i]; ++at;
    }
    ru_native_scratch_take(new_edges); ru_native_scratch_take(new_offsets); ru_native_scratch_take(new_spans);
    free(root->edges); free(root->as.memory.pin_offsets); free(root->as.memory.pin_sizes);
    root->edges = new_edges; root->edge_count = root->edge_capacity = count + 2;
    root->as.memory.pin_offsets = new_offsets; root->as.memory.pin_sizes = new_spans;
}
static void rn_pin_field(RuNative *memory, size_t offset, size_t span, Val owner, int line)
{
    size_t zero = 0;
    rn_replace_pins(memory, offset, span, owner.kind == RU_NULL ? 0 : 1, &zero, &span, &owner, line);
}
static void rn_store(RuNative *type, unsigned char *destination, RuNativeRaw raw)
{
    /* memcpy avoids strict-aliasing and unaligned-access assumptions. */
#define RN_STORE(CODE, CTYPE, FIELD) case CODE: { CTYPE value = (CTYPE)raw.FIELD; memcpy(destination, &value, sizeof(value)); break; }
    switch (type->as.type.code) {
    RN_STORE(RN_I8, int8_t, i) RN_STORE(RN_U8, uint8_t, u)
    RN_STORE(RN_I16, int16_t, i) RN_STORE(RN_U16, uint16_t, u)
    RN_STORE(RN_I32, int32_t, i) RN_STORE(RN_U32, uint32_t, u)
    RN_STORE(RN_I64, int64_t, i) RN_STORE(RN_U64, uint64_t, u)
    RN_STORE(RN_INTPTR, intptr_t, i) RN_STORE(RN_UINTPTR, uintptr_t, u)
    RN_STORE(RN_F32, float, f32) RN_STORE(RN_F64, double, f64)
    RN_STORE(RN_PTR, void *, p)
    default: break;
    }
#undef RN_STORE
}
static RuNativeRaw rn_load(RuNative *type, const unsigned char *source)
{
    RuNativeRaw raw; memset(&raw, 0, sizeof(raw));
#define RN_LOAD(CODE, CTYPE, FIELD) case CODE: { CTYPE value; memcpy(&value, source, sizeof(value)); raw.FIELD = value; break; }
    switch (type->as.type.code) {
    RN_LOAD(RN_I8, int8_t, i) RN_LOAD(RN_U8, uint8_t, u)
    RN_LOAD(RN_I16, int16_t, i) RN_LOAD(RN_U16, uint16_t, u)
    RN_LOAD(RN_I32, int32_t, i) RN_LOAD(RN_U32, uint32_t, u)
    RN_LOAD(RN_I64, int64_t, i) RN_LOAD(RN_U64, uint64_t, u)
    RN_LOAD(RN_INTPTR, intptr_t, i) RN_LOAD(RN_UINTPTR, uintptr_t, u)
    RN_LOAD(RN_F32, float, f32) RN_LOAD(RN_F64, double, f64)
    RN_LOAD(RN_PTR, void *, p)
    default: break;
    }
#undef RN_LOAD
    return raw;
}
static Val rn_struct(Val fields, int line)
{
    RuArray *array; Val result; RuNative *object; size_t i, j, size = 0, alignment = 1;
    if (fields.kind != RU_ARRAY || !((RuArray *)fields.heap)->len || ((RuArray *)fields.heap)->len > 128)
        ru_fail(line, "结构需要 1 至 128 个字段的阵");
    array = (RuArray *)fields.heap; result = rn_new(RN_TYPE, line); object = (RuNative *)result.heap;
    object->as.type.code = RN_STRUCT;
    object->as.type.fields = (RuNativeField *)ru_alloc(array->len * sizeof(RuNativeField), line);
    memset(object->as.type.fields, 0, array->len * sizeof(RuNativeField));
    for (i = 0; i < array->len; ++i) {
        RuArray *field; RuNative *type; Val name; const char *text;
        if (array->items[i].kind != RU_ARRAY || ((RuArray *)array->items[i].heap)->len != 2) ru_fail(line, "结构字段须为 [字段句, 类型]");
        field = (RuArray *)array->items[i].heap; name = field->items[0];
        text = rn_text(name, line, "结构字段名须为不含 NUL 的句");
        if (!*text || *text == '_') ru_fail(line, "结构字段名非空且不能以下划线开头");
        for (j = 0; j < i; ++j) if (!strcmp(text, object->as.type.fields[j].name.s->data)) ru_fail(line, "结构字段名重复");
        type = rn_expect(field->items[1], RN_TYPE, line, "结构字段需要原生类型");
        if (type->as.type.code == RN_VOID) ru_fail(line, "结构字段不能为无值");
        if (type->as.type.alignment > alignment) alignment = type->as.type.alignment;
        size = (size + type->as.type.alignment - 1) & ~(type->as.type.alignment - 1);
        object->as.type.fields[i].name = name; object->as.type.fields[i].type = type;
        object->as.type.fields[i].offset = size; size += type->as.type.size;
        if (size > RN_MAX_BUFFER) ru_fail(line, "原生结构超过缓冲上限");
        rn_edge(object, name, line); rn_edge(object, field->items[1], line);
        ++object->as.type.count;
    }
    size = (size + alignment - 1) & ~(alignment - 1);
    object->as.type.size = size; object->as.type.alignment = alignment;
    return result;
}
static RuNativeField *rn_field(RuNative *type, Val name, int line)
{
    size_t i; const char *text = rn_text(name, line, "字段名须为句");
    if (type && type->as.type.code == RN_STRUCT)
        for (i = 0; i < type->as.type.count; ++i) if (!strcmp(text, type->as.type.fields[i].name.s->data)) return type->as.type.fields + i;
    ru_fail(line, "未知结构字段；不支持解引用外部指针"); return NULL;
}
static uint32_t rn_read_utf8(const unsigned char *bytes, size_t *at)
{
    uint32_t code = bytes[(*at)++]; unsigned remaining;
    if (code < 0x80) return code;
    if (code < 0xe0) { code &= 31; remaining = 1; }
    else if (code < 0xf0) { code &= 15; remaining = 2; }
    else { code &= 7; remaining = 3; }
    while (remaining--) code = (code << 6) | (bytes[(*at)++] & 63);
    return code;
}
static uint32_t rn_read_utf16(const unsigned char *bytes, size_t size, size_t *at, int line)
{
    uint32_t code = (uint32_t)bytes[*at] | ((uint32_t)bytes[*at + 1] << 8); *at += 2;
    if (code >= 0xdc00 && code <= 0xdfff) ru_fail(line, "无效 UTF16：孤立低代理项");
    if (code >= 0xd800 && code <= 0xdbff) {
        uint32_t low;
        if (*at + 2 > size) ru_fail(line, "无效 UTF16：缺少低代理项");
        low = (uint32_t)bytes[*at] | ((uint32_t)bytes[*at + 1] << 8); *at += 2;
        if (low < 0xdc00 || low > 0xdfff) ru_fail(line, "无效 UTF16：缺少低代理项");
        code = UINT32_C(0x10000) + ((code - 0xd800) << 10) + low - 0xdc00;
    }
    return code;
}
static size_t rn_put_utf8(uint32_t code, unsigned char *out)
{
    if (code < 0x80) { out[0] = (unsigned char)code; return 1; }
    if (code < 0x800) { out[0] = (unsigned char)(0xc0 | (code >> 6)); out[1] = (unsigned char)(0x80 | (code & 63)); return 2; }
    if (code < 0x10000) { out[0] = (unsigned char)(0xe0 | (code >> 12)); out[1] = (unsigned char)(0x80 | ((code >> 6) & 63)); out[2] = (unsigned char)(0x80 | (code & 63)); return 3; }
    out[0] = (unsigned char)(0xf0 | (code >> 18)); out[1] = (unsigned char)(0x80 | ((code >> 12) & 63)); out[2] = (unsigned char)(0x80 | ((code >> 6) & 63)); out[3] = (unsigned char)(0x80 | (code & 63)); return 4;
}
static Val rn_utf(Val text, int utf16, int line)
{
    const unsigned char *input = (const unsigned char *)rn_text(text, line, "原生文本需要不含 NUL 的句");
    Val result;
    if (!utf16) {
        result = rn_memory(NULL, text.s->len + 1, line);
        memcpy(((RuNative *)result.heap)->as.memory.data, input, text.s->len);
    } else {
        size_t at = 0, size = 2, output = 0; unsigned char *bytes;
        while (at < text.s->len) size += rn_read_utf8(input, &at) >= 0x10000 ? 4 : 2;
        result = rn_memory(NULL, size, line); bytes = ((RuNative *)result.heap)->as.memory.data; at = 0;
        while (at < text.s->len) {
            uint32_t code = rn_read_utf8(input, &at), low;
            if (code >= 0x10000) {
                code -= 0x10000; low = 0xdc00 + (code & 1023); code = 0xd800 + (code >> 10);
                bytes[output++] = (unsigned char)(code & 255); bytes[output++] = (unsigned char)(code >> 8); code = low;
            }
            bytes[output++] = (unsigned char)(code & 255); bytes[output++] = (unsigned char)(code >> 8);
        }
    }
    return result;
}
static Val rn_decode(RuNative *memory, int utf16, int line)
{
    size_t i, size = memory->as.memory.size; const unsigned char *bytes = memory->as.memory.data;
    Val result; rn_memory_check(memory, line);
    if (!utf16) {
        for (i = 0; i < size && bytes[i]; ++i) {}
        if (i == size) ru_fail(line, "UTF8 缓冲缺少界内 NUL 终止符");
        if (!ru_valid_utf8((const char *)bytes, i)) ru_fail(line, "无效 UTF8");
        result = ru_string_alloc(i, line); memcpy(result.s->data, bytes, i); return result;
    }
    if (size % 2) ru_fail(line, "UTF16 缓冲字节数须为偶数");
    for (i = 0; i < size && (bytes[i] || bytes[i + 1]); i += 2) {}
    if (i == size) ru_fail(line, "UTF16 缓冲缺少界内 NUL 终止符");
    {
        size_t at = 0, length = 0, output = 0; unsigned char encoded[4];
        while (at < i) length += rn_put_utf8(rn_read_utf16(bytes, i, &at, line), encoded);
        result = ru_string_alloc(length, line); at = 0;
        while (at < i) output += rn_put_utf8(rn_read_utf16(bytes, i, &at, line), (unsigned char *)result.s->data + output);
        return result;
    }
}
static Val rn_signature(Val result_type, Val parameters, Val convention, int line)
{
    RuNative *result = rn_expect(result_type, RN_TYPE, line, "签名返回需要原生类型"), *object;
    RuArray *array; const char *text = rn_text(convention, line, "调用约定须为句");
    int codes[64], cc, id; size_t i; Val value;
    if (strcmp(text, "win64") && strcmp(text, "cdecl")) ru_fail(line, "调用约定只支持 win64 或 cdecl；不支持变参");
    cc = !strcmp(text, "cdecl");
    if (parameters.kind != RU_ARRAY || ((RuArray *)parameters.heap)->len > 64) ru_fail(line, "签名参数须为不超过 64 项的阵");
    array = (RuArray *)parameters.heap;
    if (result->as.type.code == RN_STRUCT) ru_fail(line, "不支持结构按值返回；请传结构地址");
    for (i = 0; i < array->len; ++i) {
        RuNative *type = rn_expect(array->items[i], RN_TYPE, line, "签名参数需要原生类型");
        codes[i] = type->as.type.code;
        if (codes[i] == RN_VOID || codes[i] == RN_STRUCT) ru_fail(line, "不支持结构按值或无值参数；请传结构地址");
    }
    id = ru_native_generated_signature(result->as.type.code, (int)array->len, codes, cc);
    if (id < 0) ru_fail(line, "原生签名不在静态编译集合中；动态签名不受支持");
    value = rn_new(RN_SIGNATURE, line); object = (RuNative *)value.heap;
    object->as.signature.id = id; object->as.signature.convention = cc;
    object->as.signature.result = result; object->as.signature.count = array->len;
    rn_edge(object, result_type, line);
    for (i = 0; i < array->len; ++i) {
        object->as.signature.params[i] = (RuNative *)array->items[i].heap;
        rn_edge(object, array->items[i], line);
    }
    return value;
}
static Val rn_library(Val path, int system, int line)
{
    const char *text = rn_text(path, line, "动态库路径须为不含 NUL 的句");
    Val wide, result; void *handle;
    wide = rn_utf(path, 1, line);
    handle = ru_native_load_library(text, ((RuNative *)wide.heap)->as.memory.data, system, line);
    v_drop(wide);
    result = rn_new(RN_LIBRARY, line); ((RuNative *)result.heap)->as.library.handle = handle;
    return result;
}
static Val rn_bind(RuNative *library, Val name, Val signature, int line)
{
    const char *text = rn_text(name, line, "原生符号名须为有效 ASCII 名称");
    RuNative *sig = rn_expect(signature, RN_SIGNATURE, line, "绑定需要原生签名"), *object;
    void *address; Val result; size_t i;
    if (library->closed) ru_fail(line, "动态库已关闭");
    for (i = 0; i < name.s->len; ++i) {
        unsigned c = (unsigned char)text[i];
        int alpha = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_';
        if (!(alpha || (i && ((c >= '0' && c <= '9') || c == '@' || c == '?')))) ru_fail(line, "原生符号名须为有效 ASCII 名称；不支持序号绑定");
    }
    if (!i) ru_fail(line, "原生符号名不能为空");
    address = ru_native_find_symbol(library->as.library.handle, text);
    if (!address) ru_fail(line, "动态库没有导出符号：%s", text);
    result = rn_new(RN_FUNCTION, line); object = (RuNative *)result.heap;
    object->as.function.library = library; object->as.function.signature = sig; object->as.function.address = address;
    rn_edge(object, rn_value(library), line); rn_edge(object, signature, line); return result;
}
static void rn_error_utf8(char *message)
{
    size_t at = 0, length = strlen(message);
    /* snprintf limits bytes, not code points. A truncated source/argument can
     * occur in the middle as well as at the end; replace broken bytes without
     * allocating or losing the original failure to a second encoding error. */
    while (at < length) {
        unsigned char first = (unsigned char)message[at];
        size_t count = first < 0x80 ? 1 : first >= 0xc2 && first <= 0xdf ? 2 : first >= 0xe0 && first <= 0xef ? 3 : first >= 0xf0 && first <= 0xf4 ? 4 : 0;
        if (!count || count > length - at || !ru_valid_utf8(message + at, count)) message[at++] = '?';
        else at += count;
    }
}
static void rn_record_error(const char *message)
{
    if (!ru_native_callback_error[0]) {
        snprintf(ru_native_callback_error, sizeof(ru_native_callback_error), "原生回调失败：%.4000s", message);
        rn_error_utf8(ru_native_callback_error);
    }
}
static Val rn_invoke(RuNative *function, Val parameters, int line)
{
    RuNative *sig = function->as.function.signature, *outcome;
    RuArray *array; RuNativeRaw args[64], raw; Val snapshot, value, result;
    size_t i; int outer; uint32_t error; char callback_error[4097];
    if (ru_mi_active_borrows) ru_fail(line, "密只读借用期间拒绝未知 effect 原生调用");
    if (rn_platform_thread() != ru_native_thread_id) ru_fail(line, "原生对象只能在所属执行线程使用");
    if (function->as.function.library->closed) ru_fail(line, "动态库已关闭");
    if (parameters.kind != RU_ARRAY || ((RuArray *)parameters.heap)->len != sig->as.signature.count) ru_fail(line, "原生调用实参数量与签名不符");
    array = (RuArray *)parameters.heap;
    snapshot = rn_owners(parameters, 1, line);
    for (i = 0; i < array->len; ++i) args[i] = rn_marshal(sig->as.signature.params[i], array->items[i], line);
    outer = ru_native_depth == 0;
    if (outer) { ru_native_callback_error[0] = 0; rn_platform_wrong_thread(1); }
    ++ru_native_depth;
    rn_platform_set_error(0);
    raw = ru_native_generated_call(sig->as.signature.id, function->as.function.address, args);
    error = rn_platform_error(); /* Must precede cleanup, allocation and formatting. */
    --ru_native_depth;
    if (rn_platform_wrong_thread(0)) rn_record_error("只支持所属执行线程上的同步回调");
    memcpy(callback_error, ru_native_callback_error, sizeof(callback_error));
    if (outer) { ru_native_callback_error[0] = 0; rn_platform_wrong_thread(1); }
    v_drop(snapshot);
    value = sig->as.signature.result->as.type.code == RN_VOID ? v_null() : rn_scalar(sig->as.signature.result, raw, v_null(), line);
    result = rn_new(RN_OUTCOME, line); outcome = (RuNative *)result.heap;
    outcome->as.outcome.error = error; rn_edge(outcome, value, line); v_drop(value);
    value = callback_error[0] ? v_str(callback_error) : v_null(); rn_edge(outcome, value, line); v_drop(value);
    return result;
}
static int rn_root_compare(const void *a, const void *b)
{
    uintptr_t x = (uintptr_t)((const RuNativeRoot *)a)->heap, y = (uintptr_t)((const RuNativeRoot *)b)->heap;
    return (x > y) - (x < y);
}
/* Trap objects stay heap-allocated: setjmp/longjmp requires that objects
 * written between setjmp and longjmp not be non-volatile automatics of the
 * setjmp function.  A per-process freelist recycles trap objects so the
 * common callback path never touches calloc/free.  The freelist lives
 * inside ru_native_callback_dispatch (function-local static) so translation
 * units that never emit dispatch don't warn about an unused variable under
 * -Werror.  It is safe as an ordinary global because the whole native
 * subsystem is pinned to ru_native_thread_id.  The list is a stack linked
 * through the trap's own `previous` field: dispatch reads the outer trap
 * from that field before recycling the node, so the two uses never overlap.
 * Resident memory equals peak nesting depth, not call count. */
/* The freelist head lives behind an accessor so translation units that never
 * emit callback dispatch don't trip -Wunused-variable under -Werror; the
 * accessor itself is a static function, which the build already tolerates
 * unused (-Wno-unused-function).  Keeps this header free of __attribute__ or
 * other non-C99 extensions. */
static RuNativeTrap **rn_trap_freelist_head(void)
{
    static RuNativeTrap *freelist;
    return &freelist;
}
static RuNativeTrap *rn_trap_new(void)
{
    RuNativeTrap **head = rn_trap_freelist_head();
    RuNativeTrap *trap = *head;
    RuHeap *heap; size_t count = 0;
    if (trap) {
        *head = trap->previous;
        trap->root_count = 0;
    } else {
        trap = (RuNativeTrap *)calloc(1, sizeof(*trap));
        if (!trap) return NULL;
    }
    for (heap = ru_transient_roots; heap; heap = heap->transient_next) ++count;
    if (count > SIZE_MAX / sizeof(*trap->roots)) { trap->previous = *head; *head = trap; return NULL; }
    trap->roots = (RuNativeRoot *)malloc((count ? count : 1) * sizeof(*trap->roots));
    if (!trap->roots) { trap->previous = *head; *head = trap; return NULL; }
    trap->message[0] = 0;
    for (heap = ru_transient_roots; heap; heap = heap->transient_next) {
        trap->roots[trap->root_count].heap = heap;
        trap->roots[trap->root_count++].transient = heap->roots - heap->permanent_roots;
    }
    qsort(trap->roots, trap->root_count, sizeof(*trap->roots), rn_root_compare);
    trap->previous = ru_native_trap; trap->scratch = ru_scratch;
    trap->call_depth = ru_call_depth; trap->source = ru_source;
    return trap;
}
static void rn_trap_release(RuNativeTrap *trap)
{
    RuNativeTrap **head = rn_trap_freelist_head();
    free(trap->roots);
    trap->roots = NULL;
    trap->previous = *head;
    *head = trap;
}
static void rn_trap_restore(RuNativeTrap *trap)
{
    RuHeap *heap;
    /* Persistent roots have changed legitimately during the callback; restore
     * only abandoned frame roots. Entry transient roots keep their heaps alive. */
    ru_panic_clear();
    ru_transient_roots = NULL;
    for (heap = ru_heap; heap; heap = heap->next) {
        RuNativeRoot key, *saved; key.heap = heap; key.transient = 0;
        saved = (RuNativeRoot *)bsearch(&key, trap->roots, trap->root_count, sizeof(*trap->roots), rn_root_compare);
        heap->roots = heap->permanent_roots + (saved ? saved->transient : 0);
        heap->mark = 0;
        heap->transient_prev = NULL; heap->transient_next = NULL;
        if (heap->roots > heap->permanent_roots) rn_transient_link(heap);
    }
    while (ru_scratch != (RuScratch *)trap->scratch) ru_scratch_free(ru_scratch->data);
    ru_call_depth = trap->call_depth; ru_source = trap->source;
}
static void rn_callback_detach(RuNative *callback)
{
    RuNativeSlot *slot = ru_native_slots + callback->as.callback.slot;
    /* Keep executable thunk and immutable fallback forever, detach Ru graph. */
    slot->object = NULL;
    callback->edge_count = 0; callback->as.callback.signature = NULL;
    v_unpin(rn_value(callback));
}
static void rn_callback_close(RuNative *callback)
{
    if (callback->closed) return;
    callback->closed = 1;
    if (!callback->as.callback.active) rn_callback_detach(callback);
}
static void rn_callback_return_owner(RuNative *callback, Val value, int line)
{
    Val *owners = &value; size_t count = 1, i, j;
    if (value.kind == RU_NATIVE && ((RuNative *)value.heap)->tag == RN_SCALAR) {
        RuNative *scalar = (RuNative *)value.heap;
        owners = scalar->edges + 1; count = scalar->edge_count - 1;
    }
    if (callback->closed && count) ru_fail(line, "关闭中的回调不能返回拥有型指针");
    for (i = 0; i < count; ++i) {
        if (!owners[i].heap) continue;
        for (j = 4; j < callback->edge_count; ++j) if (callback->edges[j].heap == owners[i].heap) break;
        if (j == callback->edge_count) {
            if (callback->as.callback.retained == 128) ru_fail(line, "单个回调返回的拥有型指针资源超过 128 个上限");
            rn_edge(callback, owners[i], line); ++callback->as.callback.retained;
        }
    }
}
static RuNativeRaw ru_native_callback_dispatch(unsigned slot_index, int signature_id, const RuNativeRaw *raw_args)
{
    RuNativeSlot *slot = ru_native_slots + slot_index;
    uint32_t entry_error = rn_platform_error();
    RuNativeRaw answer = slot->fallback;
    RuNative *callback;
    /* volatile: setjmp stores/restores this automatic by value; without the
     * qualifier a longjmp back to trap->jump would leave it indeterminate
     * (C11 7.13.1.1).  The pointed-to object is heap storage, unaffected. */
    RuNativeTrap *volatile trap;
    /* Immutable fields only until owner thread has been verified. In
     * particular no callback object, heap, counter, or closure is read here. */
    if (rn_platform_thread() != slot->owner_thread) {
        rn_platform_thread_error(); rn_platform_set_error(entry_error); return answer;
    }
    callback = slot->object;
    if (!callback || callback->closed || signature_id != slot->signature || !ru_native_depth) {
        rn_record_error(!callback || callback->closed ? "原生回调已关闭；外部代码仍持有其地址" : "只支持原生调用期间的同步回调");
        rn_platform_set_error(entry_error); return answer;
    }
    /* This local root is included in the snapshot and survives logical close. */
    v_copy(rn_value(callback)); ++callback->as.callback.active; ++ru_native_callback_depth;
    trap = rn_trap_new();
    if (!trap) {
        rn_record_error("内存不足，无法进入安全回调边界");
    } else {
        trap->result = answer; ru_native_trap = trap;
        if (setjmp(trap->jump) == 0) {
            RuNative *sig = callback->as.callback.signature;
            Val args[64], result; const char *keys[64] = {0}; size_t i;
            for (i = 0; i < sig->as.signature.count; ++i) args[i] = rn_scalar(sig->as.signature.params[i], raw_args[i], v_null(), 0);
            result = v_call(callback->edges[1], sig->as.signature.count, keys, args, 0);
            if (ru_panicking) {
                snprintf(trap->message, sizeof(trap->message), "%.512s:%d:%d: %.3500s", ru_panic_source ? ru_panic_source : "<回调>", ru_panic_line, ru_panic_col, ru_panic_reason.s->data);
            } else {
                trap->result = rn_marshal(sig->as.signature.result, result, 0);
                if (sig->as.signature.result->as.type.code == RN_PTR && trap->result.p) rn_callback_return_owner(callback, result, 0);
                v_drop(result);
                for (i = 0; i < sig->as.signature.count; ++i) v_drop(args[i]);
            }
        }
        if (trap->message[0]) {
            rn_record_error(trap->message); trap->result = slot->fallback;
            rn_trap_restore(trap);
            /* A bounded direct native failure action can wake a blocked API.
             * It has its own setjmp attempt and cannot recurse indefinitely. */
            if (!ru_native_handling_failure && callback->edge_count >= 4 && callback->edges[2].kind != RU_NULL) {
                ru_native_handling_failure = 1;
                if (setjmp(trap->jump) == 0) {
                    Val ignored = rn_invoke((RuNative *)callback->edges[2].heap, callback->edges[3], 0); v_drop(ignored);
                } else rn_trap_restore(trap);
                ru_native_handling_failure = 0;
            }
        }
        answer = trap->result;
        ru_native_trap = trap->previous; ru_source = trap->source;
        rn_trap_release(trap);
    }
    --callback->as.callback.active; --ru_native_callback_depth;
    if (callback->closed && !callback->as.callback.active) rn_callback_detach(callback);
    v_drop(rn_value(callback));
    rn_platform_set_error(entry_error); return answer;
}
static Val rn_callback(Val signature, Val function, Val fallback, int line)
{
    RuNative *sig = rn_expect(signature, RN_SIGNATURE, line, "回调需要原生签名"), *object;
    RuNativeRaw raw; RuNativeSlot *slot; Val result;
    if (function.kind != RU_FUNCTION || ((RuCallable *)function.heap)->function->procedure || ((RuCallable *)function.heap)->function->count != sig->as.signature.count)
        ru_fail(line, "回调需要与签名参数数量一致的如算");
    raw = rn_marshal(sig->as.signature.result, fallback, line);
    if (sig->as.signature.result->as.type.code == RN_PTR && raw.p) ru_fail(line, "指针回调失败值只支持空指针，避免关闭后返回失效地址");
    if (ru_native_slot_count >= 1024) ru_fail(line, "本进程原生回调总数达到 1024 上限；关闭的安全占位也计入，请重启进程");
    if (!ru_native_generated_callback(sig->as.signature.id, ru_native_slot_count)) ru_fail(line, "回调签名不在静态编译集合中");
    result = rn_new(RN_CALLBACK, line); object = (RuNative *)result.heap;
    object->as.callback.signature = sig; object->as.callback.slot = ru_native_slot_count;
    rn_edge(object, signature, line); rn_edge(object, function, line);
    rn_edge(object, v_null(), line); rn_edge(object, v_null(), line);
    slot = ru_native_slots + ru_native_slot_count++;
    slot->object = object; slot->fallback = raw; slot->owner_thread = ru_native_thread_id; slot->signature = sig->as.signature.id;
    v_pin(result); /* Process callback registry, released on logical close. */
    return result;
}
static Val rn_memory_read(RuNative *memory, Val name, int line)
{
    RuNativeField *field = rn_field(memory->as.memory.type, name, line);
    RuNative *root = memory->as.memory.root ? memory->as.memory.root : memory;
    Val result, owner = v_null(); size_t i, absolute = memory->as.memory.offset + field->offset;
    rn_memory_check(memory, line);
    if (field->type->as.type.code == RN_STRUCT) {
        RuNative *view;
        result = rn_new(RN_MEMORY, line); view = (RuNative *)result.heap;
        view->as.memory.type = field->type; view->as.memory.root = root; view->as.memory.parent = memory;
        view->as.memory.data = memory->as.memory.data + field->offset;
        view->as.memory.offset = absolute; view->as.memory.size = field->type->as.type.size;
        rn_edge(view, rn_value(field->type), line); rn_edge(view, rn_value(memory), line);
        return result;
    }
    for (i = 2; i < root->edge_count; ++i) if (root->as.memory.pin_offsets[i - 2] == absolute) { owner = root->edges[i]; break; }
    return rn_scalar(field->type, rn_load(field->type, memory->as.memory.data + field->offset), owner, line);
}
static Val rn_memory_write(RuNative *memory, Val name, Val value, int line)
{
    RuNativeField *field = rn_field(memory->as.memory.type, name, line);
    rn_memory_check(memory, line);
    rn_memory_check_mutation(memory, line);
    if (field->type->as.type.code == RN_STRUCT) {
        RuNative *source = rn_expect(value, RN_MEMORY, line, "嵌套结构写入需要同类型缓冲");
        RuNative *root = source->as.memory.root ? source->as.memory.root : source;
        size_t i, begin = source->as.memory.offset, end = begin + source->as.memory.size;
        Val pins = v_array(0, NULL, line); RuArray *array = (RuArray *)pins.heap;
        rn_memory_check(source, line);
        if (source->as.memory.type != field->type) ru_fail(line, "嵌套结构类型不匹配");
        /* Snapshot before clearing destination, including self/overlap copies. */
        for (i = 2; i < root->edge_count; ++i) {
            size_t offset = root->as.memory.pin_offsets[i - 2];
            if (offset >= begin && offset < end) {
                Val ignored = v_append(pins, v_num((double)(offset - begin)), line); v_drop(ignored);
                ignored = v_append(pins, v_num((double)root->as.memory.pin_sizes[i - 2]), line); v_drop(ignored);
                ignored = v_append(pins, root->edges[i], line); v_drop(ignored);
            }
        }
        {
            size_t count = array->len / 3, *offsets, *spans;
            Val *owners;
            offsets = (size_t *)ru_scratch_alloc(count * sizeof(*offsets), line);
            spans = (size_t *)ru_scratch_alloc(count * sizeof(*spans), line);
            owners = (Val *)ru_scratch_alloc(count * sizeof(*owners), line);
            for (i = 0; i < count; ++i) {
                offsets[i] = (size_t)array->items[i * 3].n;
                spans[i] = (size_t)array->items[i * 3 + 1].n;
                owners[i] = array->items[i * 3 + 2];
            }
            rn_replace_pins(memory, field->offset, field->type->as.type.size, count, offsets, spans, owners, line);
            memmove(memory->as.memory.data + field->offset, source->as.memory.data, field->type->as.type.size);
            ru_scratch_free(offsets); ru_scratch_free(spans); ru_scratch_free(owners);
        }
        v_drop(pins);
    } else {
        RuNativeRaw raw = rn_marshal(field->type, value, line);
        /* Publish pin before bytes: allocation failure cannot silently leave
         * an unowned new pointer in a surviving structure. */
        rn_pin_field(memory, field->offset, field->type->as.type.size, value, line);
        rn_store(field->type, memory->as.memory.data + field->offset, raw);
    }
    return v_copy(rn_value(memory));
}
static void ru_native_dispose(RuNative *object)
{
    if (object->tag == RN_TYPE) free(object->as.type.fields);
    if (object->tag == RN_MEMORY && !object->as.memory.root) {
        free(object->as.memory.data); free(object->as.memory.pin_offsets); free(object->as.memory.pin_sizes);
    }
    /* DLLs deliberately stay loaded until process exit. */
    free(object->edges);
}
static void ru_native_shutdown(void)
{
    unsigned i;
    for (i = 0; i < ru_native_slot_count; ++i)
        if (ru_native_slots[i].object) rn_callback_close(ru_native_slots[i].object);
}
static Env *ru_native_builtins(Env *parent)
{
    static const char *names[] = {"无值", "i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64", "intptr", "uintptr", "f32", "f64", "指针"};
    /* Windows x64 target-layout data, not host sizeof or a portable ABI claim. */
    static const unsigned char sizes[] = {0, 1, 1, 2, 2, 4, 4, 8, 8, 8, 8, 4, 8, 8};
    size_t i; Val context;
    (void)ru_native_handling_failure; /* Dispatcher may be pruned if no callback shape is used. */
    if (ru_native_ready) return &ru_native_environment;
    ru_native_ready = 1; ru_native_thread_id = rn_platform_thread();
    env_init(&ru_native_environment, parent);
    context = rn_new(RN_CONTEXT, 0);
    for (i = 0; i < 14; ++i) {
        Val value = rn_new(RN_TYPE, 0); RuNative *type = (RuNative *)value.heap;
        type->as.type.code = (int)i; type->as.type.size = sizes[i]; type->as.type.bits = sizes[i] * 8;
        type->as.type.alignment = sizes[i] ? sizes[i] : 1;
        type->as.type.is_signed = i == RN_I8 || i == RN_I16 || i == RN_I32 || i == RN_I64 || i == RN_INTPTR;
        ru_native_primitives[i] = type;
        rn_edge((RuNative *)context.heap, value, 0); v_drop(value);
        (void)names;
    }
    env_declare(&ru_native_environment, "__密", context); v_drop(context);
    return &ru_native_environment;
}
static int ru_native_member(Val receiver, const char *name, size_t argc, const char **keys, Val *args, int line, Val *out)
{
    RuNative *object; Val bound[3];
    const char *one[] = {"值"}, *field[] = {"字段"}, *text[] = {"句"}, *path[] = {"路径"};
    if (receiver.kind != RU_NATIVE) return 0;
    if (rn_platform_thread() != ru_native_thread_id) ru_fail(line, "原生对象只能在所属执行线程使用");
    object = (RuNative *)receiver.heap;
#define RN_BIND(COUNT, NAMES) ru_bind(name, COUNT, NAMES, argc, keys, args, bound, line)
#define RN_RETURN(VALUE) do { *out = (VALUE); return 1; } while (0)
    if (object->tag == RN_CONTEXT) {
        if (!strcmp(name, "回调中")) { RN_BIND(0, NULL); RN_RETURN(v_fact(ru_native_callback_depth != 0)); }
        if (!strcmp(name, "类型")) {
            static const char *names[] = {"无值", "i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64", "intptr", "uintptr", "f32", "f64", "指针"};
            const char *parameters[] = {"名称"}, *requested; size_t i;
            RN_BIND(1, parameters); requested = rn_text(bound[0], line, "原生类型名须为句");
            for (i = 0; i < 14; ++i) if (!strcmp(names[i], requested)) RN_RETURN(v_copy(rn_value(ru_native_primitives[i])));
            ru_fail(line, "未知原生类型");
        }
        if (!strcmp(name, "结构")) { RN_BIND(1, field); RN_RETURN(rn_struct(bound[0], line)); }
        if (!strcmp(name, "缓冲")) { const char *parameters[] = {"字节数"}; RN_BIND(1, parameters); RN_RETURN(rn_memory(NULL, rn_bounded(bound[0], 1, RN_MAX_BUFFER, line, "缓冲大小"), line)); }
        if (!strcmp(name, "UTF8") || !strcmp(name, "UTF16")) { RN_BIND(1, text); RN_RETURN(rn_utf(bound[0], !strcmp(name, "UTF16"), line)); }
        if (!strcmp(name, "系统库") || !strcmp(name, "动态库")) { RN_BIND(1, path); RN_RETURN(rn_library(bound[0], !strcmp(name, "系统库"), line)); }
        if (!strcmp(name, "签名")) { const char *parameters[] = {"返回", "参数", "约定"}; RN_BIND(3, parameters); RN_RETURN(rn_signature(bound[0], bound[1], bound[2], line)); }
        if (!strcmp(name, "回调")) { const char *parameters[] = {"签名", "算", "失败值"}; RN_BIND(3, parameters); RN_RETURN(rn_callback(bound[0], bound[1], bound[2], line)); }
    } else if (object->tag == RN_TYPE) {
        if (!strcmp(name, "大小") || !strcmp(name, "对齐")) { RN_BIND(0, NULL); RN_RETURN(v_num((double)(!strcmp(name, "大小") ? object->as.type.size : object->as.type.alignment))); }
        if (!strcmp(name, "值")) {
            RuNativeRaw raw; RN_BIND(1, one); raw = rn_convert(object, bound[0], line);
            RN_RETURN(rn_scalar_convert(object, raw, bound[0], line));
        }
        if (!strcmp(name, "重释")) {
            RuNative *from; RuNativeRaw raw; uint64_t bits;
            RN_BIND(1, one); from = rn_expect(bound[0], RN_SCALAR, line, "重释只支持等宽原生整数与指针");
            if ((!rn_integral_type(object) && object->as.type.code != RN_PTR) || (!rn_integral_type(from->as.scalar.type) && from->as.scalar.type->as.type.code != RN_PTR) || object->as.type.bits != from->as.scalar.type->as.type.bits)
                ru_fail(line, "重释只支持等宽原生整数与指针");
            rn_owners(bound[0], 0, line);
            if (from->as.scalar.type->as.type.code == RN_PTR) bits = (uint64_t)(uintptr_t)from->as.scalar.raw.p;
            else if (from->as.scalar.type->as.type.is_signed) bits = (uint64_t)from->as.scalar.raw.i;
            else bits = from->as.scalar.raw.u;
            memset(&raw, 0, sizeof(raw)); bits &= rn_mask(object->as.type.bits);
            if (object->as.type.code == RN_PTR) raw.p = (void *)(uintptr_t)bits;
            else if (object->as.type.is_signed) raw.i = rn_signed_bits(bits, object->as.type.bits);
            else raw.u = bits;
            RN_RETURN(rn_scalar_convert(object, raw, bound[0], line));
        }
        if (!strcmp(name, "偏移")) { RN_BIND(1, field); RN_RETURN(v_num((double)rn_field(object, bound[0], line)->offset)); }
        if (!strcmp(name, "新建")) {
            RN_BIND(0, NULL); if (object->as.type.code != RN_STRUCT) ru_fail(line, "新建只适用于结构描述符");
            RN_RETURN(rn_memory(object, object->as.type.size, line));
        }
    } else if (object->tag == RN_SCALAR) {
        RuNative *type = object->as.scalar.type; RuNativeRaw raw = object->as.scalar.raw; int code = type->as.type.code;
        rn_owners(receiver, 0, line);
        if (!strcmp(name, "数") || !strcmp(name, "句") || !strcmp(name, "为空")) {
            double number = 0; char buffer[128]; int zero;
            RN_BIND(0, NULL);
            if (code == RN_F32 || code == RN_F64) {
                number = code == RN_F32 ? raw.f32 : raw.f64; zero = number == 0;
                snprintf(buffer, sizeof(buffer), "%.17g", number);
            } else if (type->as.type.is_signed) {
                number = (double)raw.i; zero = raw.i == 0;
                snprintf(buffer, sizeof(buffer), "%" PRId64, raw.i);
                if (!strcmp(name, "数") && (raw.i < -(int64_t)RN_SAFE_INTEGER || raw.i > (int64_t)RN_SAFE_INTEGER)) ru_fail(line, "原生整数超出数的安全整数范围；请用其句或保持原生值");
            } else {
                uint64_t integer = code == RN_PTR ? (uint64_t)(uintptr_t)raw.p : raw.u;
                number = (double)integer; zero = integer == 0;
                snprintf(buffer, sizeof(buffer), "%" PRIu64, integer);
                if (!strcmp(name, "数") && integer > RN_SAFE_INTEGER) ru_fail(line, "原生整数超出数的安全整数范围；请用其句或保持原生值");
            }
            if (!strcmp(name, "为空")) RN_RETURN(v_fact(zero));
            if (!strcmp(name, "句")) RN_RETURN(v_str(buffer));
            RN_RETURN(v_num(number));
        }
        if (!strcmp(name, "位段")) {
            const char *parameters[] = {"起", "宽"}; size_t start, width, maximum; uint64_t bits;
            RN_BIND(2, parameters);
            if (!rn_integral_type(type) && code != RN_PTR) ru_fail(line, "位段只支持原生整数或指针");
            start = rn_bounded(bound[0], 0, (size_t)type->as.type.bits - 1, line, "位段起点");
            maximum = (size_t)type->as.type.bits - start; if (maximum > 53) maximum = 53;
            width = rn_bounded(bound[1], 1, maximum, line, "位段宽度");
            bits = code == RN_PTR ? (uint64_t)(uintptr_t)raw.p : type->as.type.is_signed ? (uint64_t)raw.i : raw.u;
            RN_RETURN(v_num((double)((bits >> start) & rn_mask((int)width))));
        }
    } else if (object->tag == RN_MEMORY) {
        if (!strcmp(name, "关闭")) {
            RN_BIND(0, NULL); rn_memory_check_mutation(object, line); object->closed = 1;
            if (!object->as.memory.root) object->edge_count = 2;
            RN_RETURN(v_null());
        }
        rn_memory_check(object, line);
        if (!strcmp(name, "大小")) { RN_BIND(0, NULL); RN_RETURN(v_num((double)object->as.memory.size)); }
        if (!strcmp(name, "地址")) { RuNativeRaw raw; RN_BIND(0, NULL); memset(&raw, 0, sizeof(raw)); raw.p = object->as.memory.data; RN_RETURN(rn_scalar(ru_native_primitives[RN_PTR], raw, receiver, line)); }
        if (!strcmp(name, "读U32LE阵")) { const char *parameters[] = {"字节偏移", "个数"}; RN_BIND(2, parameters); RN_RETURN(rn_read_u32le_array(object, bound[0], bound[1], line)); }
        if (!strcmp(name, "解UTF8") || !strcmp(name, "解UTF16")) { RN_BIND(0, NULL); RN_RETURN(rn_decode(object, !strcmp(name, "解UTF16"), line)); }
        if (!strcmp(name, "读")) { RN_BIND(1, field); RN_RETURN(rn_memory_read(object, bound[0], line)); }
        if (!strcmp(name, "写")) { const char *parameters[] = {"字段", "值"}; RN_BIND(2, parameters); RN_RETURN(rn_memory_write(object, bound[0], bound[1], line)); }
    } else if (object->tag == RN_LIBRARY) {
        if (!strcmp(name, "关闭")) { RN_BIND(0, NULL); object->closed = 1; RN_RETURN(v_null()); }
        if (object->closed) ru_fail(line, "动态库已关闭");
        if (!strcmp(name, "绑定")) { const char *parameters[] = {"名称", "签名"}; RN_BIND(2, parameters); RN_RETURN(rn_bind(object, bound[0], bound[1], line)); }
    } else if (object->tag == RN_FUNCTION) {
        if (!strcmp(name, "调用")) { const char *parameters[] = {"参数"}; RN_BIND(1, parameters); RN_RETURN(rn_invoke(object, bound[0], line)); }
    } else if (object->tag == RN_OUTCOME) {
        RN_BIND(0, NULL);
        if (!strcmp(name, "值")) RN_RETURN(v_copy(object->edges[0]));
        if (!strcmp(name, "错误码")) RN_RETURN(v_num((double)object->as.outcome.error));
        if (!strcmp(name, "回调错误")) RN_RETURN(v_copy(object->edges[1]));
    } else if (object->tag == RN_CALLBACK) {
        if (!strcmp(name, "关闭")) { RN_BIND(0, NULL); rn_callback_close(object); RN_RETURN(v_null()); }
        if (object->closed) ru_fail(line, "原生回调已关闭");
        if (!strcmp(name, "地址")) {
            RuNativeRaw raw; RN_BIND(0, NULL); memset(&raw, 0, sizeof(raw));
            raw.p = ru_native_generated_callback(object->as.callback.signature->as.signature.id, object->as.callback.slot);
            RN_RETURN(rn_scalar(ru_native_primitives[RN_PTR], raw, receiver, line));
        }
        if (!strcmp(name, "失败时")) {
            const char *parameters[] = {"函数", "参数"}; RuNative *function, *sig; RuArray *array; Val snapshot; size_t i;
            RN_BIND(2, parameters); function = rn_expect(bound[0], RN_FUNCTION, line, "回调失败动作需要原生绑定函数");
            sig = function->as.function.signature;
            if (bound[1].kind != RU_ARRAY || ((RuArray *)bound[1].heap)->len != sig->as.signature.count) ru_fail(line, "回调失败动作实参数量与签名不符");
            array = (RuArray *)bound[1].heap;
            for (i = 0; i < array->len; ++i) rn_marshal(sig->as.signature.params[i], array->items[i], line);
            snapshot = v_array(array->len, array->items, line);
            object->edges[2] = bound[0]; object->edges[3] = snapshot; v_drop(snapshot);
            RN_RETURN(v_copy(receiver));
        }
    }
    ru_fail(line, "未知原生成员：%s", name);
#undef RN_BIND
#undef RN_RETURN
    return 1;
}
