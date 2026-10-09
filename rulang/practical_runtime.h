#ifndef RU_PRACTICAL_RUNTIME_H
#define RU_PRACTICAL_RUNTIME_H
/* PCG32 algorithm: Copyright 2014 Melissa O'Neill. Apache License 2.0.
 * https://www.apache.org/licenses/LICENSE-2.0 ; see docs/third-party-notices.md. */
/* Protected helpers are reached through ordinary standard-module functions.
 * A random source has no public fields. Its inline state adds no tracing edges;
 * the ordinary RU_OBJECT marker and disposer handle the zero-field prefix. */
typedef struct { RuObject object; uint64_t state; } RuRandom;
static RuClass ru_practical_service_class = {"实用工具", NULL, NULL, 0, NULL, NULL, 0, NULL};
static RuClass ru_random_class = {"随机源", NULL, NULL, 0, NULL, NULL, 0, NULL};
static Env *ru_practical_builtins(void)
{
    static Env env;
    static int initialized;
    Val service;
    if (initialized) return &env;
    initialized = 1;
    env_init(&env, ru_contest_builtins());
    ru_practical_service_class.global = ru_random_class.global = &env;
    service = ru_object_new(&ru_practical_service_class, 0);
    env_declare(&env, "__实用", service); v_drop(service);
    return &env;
}
static void ru_practical_text(Val value, const char *name, int line)
{
    if (value.kind != RU_STR) ru_fail(line, "实参「%s」须为句，实际收到%s", name, v_type_name(value));
}
static double ru_practical_number(Val value, const char *name, int line)
{
    if (value.kind != RU_NUM || !isfinite(value.n))
        ru_fail(line, "实参「%s」须为有限数，实际收到%s", name, v_type_name(value));
    return value.n;
}
static Val ru_practical_span(Val text, size_t start, size_t end, int line)
{
    Val out = ru_string_alloc(end - start, line);
    memcpy(out.s->data, text.s->data + start, end - start);
    return out;
}
static Val ru_practical_split(Val text, Val separator, int line)
{
    Val out;
    const char *start, *match;
    ru_practical_text(text, "文", line); ru_practical_text(separator, "隔", line);
    if (!separator.s->len) ru_fail(line, "拆分的隔不能是空句");
    out = v_array(0, NULL, line);
    start = text.s->data;
    for (;;) {
        Val part, appended;
        size_t end;
        match = strstr(start, separator.s->data);
        end = match ? (size_t)(match - text.s->data) : text.s->len;
        part = ru_practical_span(text, (size_t)(start - text.s->data), end, line);
        appended = v_append(out, part, line); v_drop(appended); v_drop(part);
        if (!match) break;
        start = match + separator.s->len;
    }
    return out;
}
static Val ru_practical_replace(Val text, Val old, Val replacement, int line)
{
    const char *start, *match;
    size_t length, at = 0;
    Val out;
    ru_practical_text(text, "文", line); ru_practical_text(old, "旧", line);
    ru_practical_text(replacement, "新文", line);
    if (!old.s->len) ru_fail(line, "替换的旧不能是空句");
    length = text.s->len; start = text.s->data;
    while ((match = strstr(start, old.s->data)) != NULL) {
        length -= old.s->len;
        if (replacement.s->len > SIZE_MAX - length) ru_fail(line, "字符串过长");
        length += replacement.s->len;
        start = match + old.s->len;
    }
    out = ru_string_alloc(length, line); start = text.s->data;
    while ((match = strstr(start, old.s->data)) != NULL) {
        size_t count = (size_t)(match - start);
        memcpy(out.s->data + at, start, count); at += count;
        memcpy(out.s->data + at, replacement.s->data, replacement.s->len); at += replacement.s->len;
        start = match + old.s->len;
    }
    memcpy(out.s->data + at, start, text.s->len - (size_t)(start - text.s->data));
    return out;
}
static Val ru_practical_trim(Val text, int line)
{
    size_t first = 0, last;
    ru_practical_text(text, "文", line);
    last = text.s->len;
    while (first < last && ru_ascii_space((unsigned char)text.s->data[first])) ++first;
    while (last > first && ru_ascii_space((unsigned char)text.s->data[last - 1])) --last;
    return ru_practical_span(text, first, last, line);
}
/* Exact binary64 fixed formatting. A finite magnitude is below 2^1024;
 * multiplying by 10^15 yields fewer than 1074 bits. 36 limbs provide 1152
 * bits, including rounding carry. Every capacity boundary is still checked.
 * These private integers never become language values. */
#define RU_FIXED_LIMBS 36
typedef struct { uint32_t limb[RU_FIXED_LIMBS]; size_t used; } RuFixedInteger;
static void ru_fixed_multiply(RuFixedInteger *number, uint32_t factor, int line)
{
    uint64_t carry = 0;
    size_t i;
    for (i = 0; i < number->used; ++i) {
        uint64_t product = (uint64_t)number->limb[i] * factor + carry;
        number->limb[i] = (uint32_t)product; carry = product >> 32;
    }
    if (carry) {
        if (number->used == RU_FIXED_LIMBS) ru_fail(line, "内部错误：定点整数容量不足");
        number->limb[number->used++] = (uint32_t)carry;
    }
}
static void ru_fixed_increment(RuFixedInteger *number, int line)
{
    size_t i = 0;
    while (i < number->used && number->limb[i] == UINT32_MAX) number->limb[i++] = 0;
    if (i == number->used) {
        if (i == RU_FIXED_LIMBS) ru_fail(line, "内部错误：定点整数容量不足");
        number->limb[number->used++] = 1;
    } else ++number->limb[i];
}
static void ru_fixed_shift(RuFixedInteger *number, int shift, int line)
{
    RuFixedInteger out = {{0}, 0};
    size_t i, words;
    unsigned bits;
    if (!shift) return;
    if (shift > 0) {
        words = (unsigned)shift / 32; bits = (unsigned)shift % 32;
        for (i = 0; i < number->used; ++i) {
            uint64_t part = (uint64_t)number->limb[i] << bits;
            if (i + words >= RU_FIXED_LIMBS) ru_fail(line, "内部错误：定点整数容量不足");
            out.limb[i + words] |= (uint32_t)part;
            if (part >> 32) {
                if (i + words + 1 >= RU_FIXED_LIMBS) ru_fail(line, "内部错误：定点整数容量不足");
                out.limb[i + words + 1] |= (uint32_t)(part >> 32);
            }
        }
        out.used = RU_FIXED_LIMBS;
    } else {
        unsigned distance = (unsigned)(-shift);
        size_t half_word = (distance - 1) / 32;
        int round_up = half_word < number->used &&
            ((number->limb[half_word] >> ((distance - 1) % 32)) & 1);
        words = distance / 32; bits = distance % 32;
        for (i = words; i < number->used; ++i) {
            out.limb[i - words] = number->limb[i] >> bits;
            if (bits && i + 1 < number->used)
                out.limb[i - words] |= number->limb[i + 1] << (32 - bits);
        }
        out.used = number->used > words ? number->used - words : 0;
        while (out.used && !out.limb[out.used - 1]) --out.used;
        if (round_up) ru_fixed_increment(&out, line);
    }
    while (out.used && !out.limb[out.used - 1]) --out.used;
    *number = out;
}
static unsigned ru_fixed_digit(RuFixedInteger *number)
{
    uint64_t remainder = 0;
    size_t i = number->used;
    while (i) {
        uint64_t part = (remainder << 32) | number->limb[--i];
        number->limb[i] = (uint32_t)(part / 10); remainder = part % 10;
    }
    while (number->used && !number->limb[number->used - 1]) --number->used;
    return (unsigned)remainder;
}
static Val ru_practical_fixed(Val value, Val decimals, int line)
{
    uint64_t encoding, mantissa;
    int exponent, negative, places;
    double n = ru_practical_number(value, "值", line);
    double d = ru_practical_number(decimals, "位数", line);
    RuFixedInteger integer = {{0}, 0};
    char reversed[336], buffer[352];
    size_t count = 0, at = 0, i;
    Val out;
    if (d < 0 || d > 15 || d != (double)(int)d) ru_fail(line, "位数须为 0 至 15 的整数");
    places = (int)d; negative = signbit(n) != 0;
    /* The language number representation is IEEE 754 binary64. */
    if (sizeof(n) != sizeof(encoding)) ru_fail(line, "内部错误：定点需要 binary64");
    memcpy(&encoding, &n, sizeof(encoding));
    exponent = (int)((encoding >> 52) & 0x7ff);
    mantissa = encoding & UINT64_C(0x000fffffffffffff);
    if (exponent) { mantissa |= UINT64_C(0x0010000000000000); exponent -= 1075; }
    else exponent = -1074;
    integer.limb[0] = (uint32_t)mantissa; integer.limb[1] = (uint32_t)(mantissa >> 32);
    integer.used = integer.limb[1] ? 2 : integer.limb[0] ? 1 : 0;
    for (i = 0; i < (size_t)places; ++i) ru_fixed_multiply(&integer, 5, line);
    ru_fixed_shift(&integer, exponent + places, line);
    do {
        if (count == sizeof(reversed)) ru_fail(line, "内部错误：定点字符容量不足");
        reversed[count++] = (char)('0' + ru_fixed_digit(&integer));
    } while (integer.used);
    if (negative) buffer[at++] = '-';
    if (count <= (size_t)places) {
        buffer[at++] = '0'; buffer[at++] = '.';
        for (i = count; i < (size_t)places; ++i) buffer[at++] = '0';
    }
    for (i = count; i; --i) {
        buffer[at++] = reversed[i - 1];
        if (places && i - 1 == (size_t)places) buffer[at++] = '.';
    }
    if (at >= sizeof(buffer)) ru_fail(line, "内部错误：定点字符容量不足");
    out = ru_string_alloc(at, line); memcpy(out.s->data, buffer, at);
    return out;
}
static Val ru_practical_sqrt(Val value, int line)
{
    double n = ru_practical_number(value, "值", line);
    if (n < 0) ru_fail(line, "平方根的值不能为负数");
    return ru_finite(sqrt(n), line);
}
static Val ru_practical_pow(Val base, Val power, int line)
{
    double b = ru_practical_number(base, "底数", line);
    double p = ru_practical_number(power, "指数", line);
    if (b < 0 && trunc(p) != p) ru_fail(line, "负底数的指数须为整数");
    if (b == 0 && p < 0) ru_fail(line, "零不能取负指数");
    return ru_finite(p == 0 ? 1 : pow(b, p), line);
}
static Val ru_practical_round(Val value, const char *name, int line)
{
    double n = ru_practical_number(value, "值", line), out;
    if (!strcmp(name, "向下取整")) out = floor(n);
    else if (!strcmp(name, "向上取整")) out = ceil(n);
    else out = round(n);
    if (out == 0) out = copysign(0.0, n);
    return ru_finite(out, line);
}
/* PCG32 XSH-RR, fixed initseq 54. Independently expressed from the published
 * algorithm by M. E. O'Neill: https://www.pcg-random.org/using-pcg-c-basic.html
 * Unsigned operations define the 64-bit state wrap and 32-bit output rotation. */
static uint32_t ru_random_next(RuRandom *source)
{
    uint64_t before = source->state;
    uint32_t word = (uint32_t)(((before >> 18) ^ before) >> 27);
    unsigned rotation = (unsigned)(before >> 59);
    source->state = before * UINT64_C(6364136223846793005) + UINT64_C(109);
    return (word >> rotation) | (word << ((32 - rotation) & 31));
}
static Val ru_random_new(Val seed, int line)
{
    double n = ru_practical_number(seed, "种子", line);
    RuRandom *source;
    Val out = v_null();
    if (n < 0 || n > 4294967295.0 || (double)(uint32_t)n != n)
        ru_fail(line, "种子须为 0 至 4294967295 的整数");
    source = (RuRandom *)ru_new_heap(sizeof(*source), RU_OBJECT, line);
    source->object.klass = &ru_random_class;
    out.kind = RU_OBJECT; out.heap = &source->object.gc;
    /* Official two-step initialization, rather than assigning seed to state. */
    (void)ru_random_next(source); source->state += (uint64_t)n; (void)ru_random_next(source);
    return out;
}
static uint32_t ru_random_bounded(RuRandom *source, uint64_t count)
{
    uint32_t word, threshold;
    if (count == 1) return 0;
    if (count == UINT64_C(4294967296)) return ru_random_next(source);
    threshold = (uint32_t)(UINT64_C(4294967296) % count);
    do { word = ru_random_next(source); } while (word < threshold);
    return word % (uint32_t)count;
}
static int64_t ru_random_endpoint(Val value, const char *name, int line)
{
    double n = ru_practical_number(value, name, line);
    if (n < -9007199254740991.0 || n > 9007199254740991.0 || (double)(int64_t)n != n)
        ru_fail(line, "实参「%s」须为 -9007199254740991 至 9007199254740991 的整数", name);
    return (int64_t)n;
}
static Val ru_random_integer(Val receiver, Val lower, Val upper, int line)
{
    int64_t low = ru_random_endpoint(lower, "下", line);
    int64_t high = ru_random_endpoint(upper, "上", line);
    uint64_t count;
    if (low > high) ru_fail(line, "随机整数的下不能大于上");
    count = (uint64_t)(high - low) + 1;
    if (count > UINT64_C(4294967296)) ru_fail(line, "随机整数范围不能超过 4294967296 个整数");
    return v_num((double)(low + (int64_t)ru_random_bounded((RuRandom *)receiver.heap, count)));
}
static Val ru_random_shuffle(Val receiver, Val input, int line)
{
    RuArray *array;
    Val out;
    size_t i;
    if (input.kind != RU_ARRAY) ru_fail(line, "实参「列」须为阵，实际收到%s", v_type_name(input));
    array = (RuArray *)input.heap;
    if ((uint64_t)array->len > UINT64_C(4294967296)) ru_fail(line, "洗牌的阵不能超过 4294967296 项");
    out = v_array(array->len, array->items, line); array = (RuArray *)out.heap;
    for (i = array->len; i > 1; --i) {
        size_t at = ru_random_bounded((RuRandom *)receiver.heap, (uint64_t)i);
        Val temporary = array->items[i - 1]; array->items[i - 1] = array->items[at]; array->items[at] = temporary;
    }
    return out;
}
static int ru_practical_member(Val receiver, const char *name, size_t argc, const char **keys,
                              Val *args, int line, Val *out)
{
    RuClass *klass;
    const char *split_names[] = {"文", "隔"}, *replace_names[] = {"文", "旧", "新文"};
    const char *text_names[] = {"文"}, *fixed_names[] = {"值", "位数"};
    const char *value_names[] = {"值"}, *power_names[] = {"底数", "指数"};
    const char *seed_names[] = {"种子"}, *range_names[] = {"下", "上"}, *array_names[] = {"列"};
    Val bound[3];
    (void)split_names; (void)replace_names; (void)text_names; (void)fixed_names;
    (void)value_names; (void)power_names; (void)seed_names; (void)range_names; (void)array_names;
    (void)bound; (void)argc; (void)keys; (void)args; (void)line; (void)out; (void)name;
    if (receiver.kind != RU_OBJECT) return 0;
    klass = ((RuObject *)receiver.heap)->klass;
    if (klass == &ru_practical_service_class) {
/* RU_MEMBERS: 拆分 */
        if (!strcmp(name, "拆分")) {
            ru_bind(name, 2, split_names, argc, keys, args, bound, line);
            *out = ru_practical_split(bound[0], bound[1], line); return 1;
        }
/* RU_END_MEMBERS */
/* RU_MEMBERS: 替换 */
        if (!strcmp(name, "替换")) {
            ru_bind(name, 3, replace_names, argc, keys, args, bound, line);
            *out = ru_practical_replace(bound[0], bound[1], bound[2], line); return 1;
        }
/* RU_END_MEMBERS */
/* RU_MEMBERS: 去空白 */
        if (!strcmp(name, "去空白")) {
            ru_bind(name, 1, text_names, argc, keys, args, bound, line);
            *out = ru_practical_trim(bound[0], line); return 1;
        }
/* RU_END_MEMBERS */
/* RU_MEMBERS: 定点 */
        if (!strcmp(name, "定点")) {
            ru_bind(name, 2, fixed_names, argc, keys, args, bound, line);
            *out = ru_practical_fixed(bound[0], bound[1], line); return 1;
        }
/* RU_END_MEMBERS */
/* RU_MEMBERS: 平方根 */
        if (!strcmp(name, "平方根")) {
            ru_bind(name, 1, value_names, argc, keys, args, bound, line);
            *out = ru_practical_sqrt(bound[0], line); return 1;
        }
/* RU_END_MEMBERS */
/* RU_MEMBERS: 幂 */
        if (!strcmp(name, "幂")) {
            ru_bind(name, 2, power_names, argc, keys, args, bound, line);
            *out = ru_practical_pow(bound[0], bound[1], line); return 1;
        }
/* RU_END_MEMBERS */
/* RU_MEMBERS: 向下取整,向上取整,四舍五入 */
        if (!strcmp(name, "向下取整") || !strcmp(name, "向上取整") || !strcmp(name, "四舍五入")) {
            ru_bind(name, 1, value_names, argc, keys, args, bound, line);
            *out = ru_practical_round(bound[0], name, line); return 1;
        }
/* RU_END_MEMBERS */
/* RU_MEMBERS: 造源 */
        if (!strcmp(name, "造源")) {
            ru_bind(name, 1, seed_names, argc, keys, args, bound, line);
            *out = ru_random_new(bound[0], line); return 1;
        }
/* RU_END_MEMBERS */
        return 0;
    }
    if (klass == &ru_random_class) {
/* RU_MEMBERS: 整数 */
        if (!strcmp(name, "整数")) {
            ru_bind(name, 2, range_names, argc, keys, args, bound, line);
            *out = ru_random_integer(receiver, bound[0], bound[1], line); return 1;
        }
/* RU_END_MEMBERS */
/* RU_MEMBERS: 洗牌 */
        if (!strcmp(name, "洗牌")) {
            ru_bind(name, 1, array_names, argc, keys, args, bound, line);
            *out = ru_random_shuffle(receiver, bound[0], line); return 1;
        }
/* RU_END_MEMBERS */
    }
    return 0;
}
#endif
