#ifndef RU_CONTEST_RUNTIME_H
#define RU_CONTEST_RUNTIME_H
/* Protected contest service; scanner and output buffers are traced object edges. */
#define RU_CONTEST_BUFFER_SIZE 65536
static const char *ru_contest_private_names[] = {"\001text", "\001position"};
static const char *ru_contest_private_types[] = {"句", "数"};
static RuClass ru_contest_service_class = {"如竞工具", NULL, NULL, 0, NULL, NULL, 0, NULL};
static RuClass ru_contest_scanner_class = {"如竞读流", NULL, NULL, 2,
    ru_contest_private_names, ru_contest_private_types, 0, NULL};
static RuClass ru_contest_writer_class = {"如竞出流", NULL, NULL, 2,
    ru_contest_private_names, ru_contest_private_types, 0, NULL};

static Env *ru_contest_builtins(void)
{
    static Env env;
    static int initialized;
    Val service;
    if (initialized) return &env;
    initialized = 1;
    env_init(&env, ru_io_builtins());
    ru_contest_service_class.global = ru_contest_scanner_class.global =
        ru_contest_writer_class.global = &env;
    service = ru_object_new(&ru_contest_service_class, 0);
    env_declare(&env, "__如竞", service); v_drop(service);
    return &env;
}
static Val ru_contest_span(Val text, size_t begin, size_t end, int line)
{
    Val out = ru_string_alloc(end - begin, line);
    memcpy(out.s->data, text.s->data + begin, end - begin);
    return out;
}
static void ru_contest_append(Val array, Val value, int line)
{
    Val result = v_append(array, value, line);
    v_drop(result); v_drop(value);
}
static void ru_contest_text(Val value, int line)
{
    if (value.kind != RU_STR) ru_fail(line, "实参「文」须为句");
}
static Val ru_contest_scanner(Val text, int line)
{
    Val out;
    ru_contest_text(text, line);
    /* Positions use the language's exact integer range. */
    if ((uint64_t)text.s->len > UINT64_C(9007199254740991)) ru_fail(line, "输入过长");
    out = ru_object_new(&ru_contest_scanner_class, line);
    ((RuObject *)out.heap)->fields[0] = text;
    ((RuObject *)out.heap)->fields[1] = v_num(0);
    return out;
}
static Val ru_contest_input(int line)
{
    size_t capacity = RU_CONTEST_BUFFER_SIZE, length = 0;
    char *buffer = (char *)ru_scratch_alloc(capacity, line);
    Val text, out;
    for (;;) {
        size_t count;
        if (length == capacity) {
            char *grown;
            size_t next;
            if (capacity > SIZE_MAX / 2) ru_fail(line, "输入过长");
            next = capacity * 2;
            grown = (char *)ru_scratch_alloc(next, line);
            memcpy(grown, buffer, length); ru_scratch_free(buffer);
            buffer = grown; capacity = next;
        }
        count = fread(buffer + length, 1, capacity - length, stdin);
        length += count;
        if (ferror(stdin)) ru_fail(line, "读取输入失败");
        if (feof(stdin)) break;
        if (!count) ru_fail(line, "读取输入失败");
    }
    if (memchr(buffer, 0, length)) ru_fail(line, "输入不能含 NUL");
    if (!ru_valid_utf8(buffer, length)) ru_fail(line, "输入不是有效的 UTF-8");
    text = ru_string_alloc(length, line);
    memcpy(text.s->data, buffer, length); ru_scratch_free(buffer);
    out = ru_contest_scanner(text, line); v_drop(text);
    return out;
}
static Val ru_contest_next(Val scanner, const char *name, int line)
{
    RuObject *object = (RuObject *)scanner.heap;
    Val text = object->fields[0];
    size_t at = (size_t)object->fields[1].n, begin, end;
    int lines = !strcmp(name, "行");
    if (!lines) while (at < text.s->len && ru_ascii_space((unsigned char)text.s->data[at])) ++at;
    begin = at;
    if (at == text.s->len) { object->fields[1] = v_num((double)at); return v_null(); }
    if (lines) {
        while (at < text.s->len && text.s->data[at] != '\n') ++at;
        end = at;
        if (at < text.s->len) {
            ++at;
            if (end > begin && text.s->data[end - 1] == '\r') --end;
        }
    } else {
        while (at < text.s->len && !ru_ascii_space((unsigned char)text.s->data[at])) ++at;
        end = at;
    }
    object->fields[1] = v_num((double)at);
    if (!strcmp(name, "数")) return v_num(ru_parse_number_span(text.s->data + begin, end - begin, line));
    return ru_contest_span(text, begin, end, line);
}
static Val ru_contest_split(Val text, int lines, int line)
{
    Val out;
    size_t at = 0;
    ru_contest_text(text, line);
    out = v_array(0, NULL, line);
    while (at < text.s->len) {
        size_t begin, end;
        if (!lines) while (at < text.s->len && ru_ascii_space((unsigned char)text.s->data[at])) ++at;
        if (at == text.s->len) break;
        begin = at;
        if (lines) {
            while (at < text.s->len && text.s->data[at] != '\n') ++at;
            end = at;
            if (at < text.s->len) {
                ++at;
                if (end > begin && text.s->data[end - 1] == '\r') --end;
            }
        } else {
            while (at < text.s->len && !ru_ascii_space((unsigned char)text.s->data[at])) ++at;
            end = at;
        }
        ru_contest_append(out, ru_contest_span(text, begin, end, line), line);
    }
    return out;
}
static Val ru_contest_characters(Val text, int line)
{
    Val out;
    size_t at = 0;
    ru_contest_text(text, line);
    out = v_array(0, NULL, line);
    while (at < text.s->len) {
        size_t begin = at++;
        while (at < text.s->len && ((unsigned char)text.s->data[at] & 0xc0) == 0x80) ++at;
        ru_contest_append(out, ru_contest_span(text, begin, at, line), line);
    }
    return out;
}
static Val ru_contest_join(Val values, Val separator, int line)
{
    RuArray *array;
    size_t i, length = 0, at = 0;
    Val out;
    if (values.kind != RU_ARRAY) ru_fail(line, "实参「列」须为句阵");
    if (separator.kind != RU_STR) ru_fail(line, "实参「隔」须为句");
    array = (RuArray *)values.heap;
    for (i = 0; i < array->len; ++i) {
        Val item = array->items[i];
        if (item.kind != RU_STR) ru_fail(line, "实参「列」须为句阵");
        if (i) {
            if (separator.s->len > SIZE_MAX - length) ru_fail(line, "字符串过长");
            length += separator.s->len;
        }
        if (item.s->len > SIZE_MAX - length) ru_fail(line, "字符串过长");
        length += item.s->len;
    }
    out = ru_string_alloc(length, line);
    for (i = 0; i < array->len; ++i) {
        Val item = array->items[i];
        if (i) { memcpy(out.s->data + at, separator.s->data, separator.s->len); at += separator.s->len; }
        memcpy(out.s->data + at, item.s->data, item.s->len); at += item.s->len;
    }
    return out;
}
static Val ru_contest_sort(Val values, Val comparator, int line)
{
    RuArray *array, *from, *to;
    Val left, right;
    size_t count, width;
    const char *keys[] = {NULL, NULL};
    if (values.kind != RU_ARRAY) ru_fail(line, "实参「列」须为阵");
    if (comparator.kind != RU_FUNCTION || ((RuCallable *)comparator.heap)->function->procedure)
        ru_fail(line, "实参「比较」须为算");
    array = (RuArray *)values.heap; count = array->len;
    left = v_array(count, array->items, line);
    if (count < 2) return left;
    /* Both complete snapshots remain GC roots across arbitrary callbacks.
     * No borrowed pointer into the caller's mutable source survives a call. */
    right = v_array(count, ((RuArray *)left.heap)->items, line);
    from = (RuArray *)left.heap; to = (RuArray *)right.heap;
    for (width = 1; width < count; width = width > count / 2 ? count : width * 2) {
        size_t begin = 0;
        while (begin < count) {
            size_t middle = begin + (width < count - begin ? width : count - begin);
            size_t end = middle + (width < count - middle ? width : count - middle);
            size_t a = begin, b = middle, out = begin;
            while (a < middle && b < end) {
                Val args[] = {from->items[a], from->items[b]};
                Val comparison = v_call(comparator, 2, keys, args, line);
                if (ru_panicking) { v_drop(comparison); v_drop(left); v_drop(right); return v_null(); }
                if (comparison.kind != RU_NUM || !isfinite(comparison.n)) ru_fail(line, "比较结果须为有限数");
                if (comparison.n <= 0) to->items[out++] = from->items[a++];
                else to->items[out++] = from->items[b++];
                v_drop(comparison);
            }
            while (a < middle) to->items[out++] = from->items[a++];
            while (b < end) to->items[out++] = from->items[b++];
            begin = end;
        }
        { RuArray *swap = from; from = to; to = swap; }
    }
    if (from == (RuArray *)left.heap) { v_drop(right); return left; }
    v_drop(left); return right;
}
static Val ru_contest_writer(int line)
{
    Val out = ru_object_new(&ru_contest_writer_class, line);
    Val buffer = ru_string_alloc(RU_CONTEST_BUFFER_SIZE, line);
    /* This internal string is never exposed; its length is buffer capacity. */
    ((RuObject *)out.heap)->fields[0] = buffer; v_drop(buffer);
    ((RuObject *)out.heap)->fields[1] = v_num(0);
    return out;
}
static void ru_contest_flush(Val writer, int line)
{
    RuObject *object = (RuObject *)writer.heap;
    Val buffer = object->fields[0];
    size_t length = (size_t)object->fields[1].n;
    if ((length && fwrite(buffer.s->data, 1, length, stdout) != length) || fflush(stdout) == EOF)
        ru_fail(line, "输出失败");
    object->fields[1] = v_num(0);
}
static void ru_contest_write(Val writer, const char *text, size_t length, int line)
{
    RuObject *object = (RuObject *)writer.heap;
    Val buffer = object->fields[0];
    while (length) {
        size_t used = (size_t)object->fields[1].n;
        size_t room = RU_CONTEST_BUFFER_SIZE - used;
        size_t count = length < room ? length : room;
        if (count < length) while (count && ((unsigned char)text[count] & 0xc0) == 0x80) --count;
        memcpy(buffer.s->data + used, text, count);
        object->fields[1] = v_num((double)(used + count));
        text += count; length -= count;
        if (count == room || length) ru_contest_flush(writer, line);
    }
}
static int ru_contest_member(Val receiver, const char *name, size_t argc, const char **keys,
                            Val *args, int line, Val *out)
{
    RuClass *klass;
    const char *text_names[] = {"文"}, *join_names[] = {"列", "隔"};
    const char *sort_names[] = {"列", "比较"}, *value_names[] = {"值"}, *content_names[] = {"内容"};
    Val bound[2];
    (void)text_names; (void)join_names; (void)sort_names; (void)value_names; (void)content_names;
    (void)bound; (void)argc; (void)keys; (void)args; (void)line; (void)out;
    if (receiver.kind != RU_OBJECT) return 0;
    klass = ((RuObject *)receiver.heap)->klass;
    if (klass == &ru_contest_service_class) {
/* RU_MEMBERS: 读入 */
        if (!strcmp(name, "读入")) {
            ru_bind(name, 0, NULL, argc, keys, args, bound, line);
            *out = ru_contest_input(line); return 1;
        }
/* RU_END_MEMBERS */
/* RU_MEMBERS: 蓄出 */
        if (!strcmp(name, "蓄出")) {
            ru_bind(name, 0, NULL, argc, keys, args, bound, line);
            *out = ru_contest_writer(line); return 1;
        }
/* RU_END_MEMBERS */
/* RU_MEMBERS: 扫句 */
        if (!strcmp(name, "扫句")) {
            ru_bind(name, 1, text_names, argc, keys, args, bound, line);
            *out = ru_contest_scanner(bound[0], line); return 1;
        }
/* RU_END_MEMBERS */
/* RU_MEMBERS: 字列 */
        if (!strcmp(name, "字列")) {
            ru_bind(name, 1, text_names, argc, keys, args, bound, line);
            *out = ru_contest_characters(bound[0], line); return 1;
        }
/* RU_END_MEMBERS */
/* RU_MEMBERS: 拆词,拆行 */
        if (!strcmp(name, "拆词") || !strcmp(name, "拆行")) {
            ru_bind(name, 1, text_names, argc, keys, args, bound, line);
            *out = ru_contest_split(bound[0], !strcmp(name, "拆行"), line); return 1;
        }
/* RU_END_MEMBERS */
/* RU_MEMBERS: 合句 */
        if (!strcmp(name, "合句")) {
            ru_bind(name, 2, join_names, argc, keys, args, bound, line);
            *out = ru_contest_join(bound[0], bound[1], line); return 1;
        }
/* RU_END_MEMBERS */
/* RU_MEMBERS: 排序 */
        if (!strcmp(name, "排序")) {
            ru_bind(name, 2, sort_names, argc, keys, args, bound, line);
            *out = ru_contest_sort(bound[0], bound[1], line); return 1;
        }
/* RU_END_MEMBERS */
/* RU_MEMBERS: 取整 */
        if (!strcmp(name, "取整")) {
            double value;
            int negative;
            ru_bind(name, 1, value_names, argc, keys, args, bound, line);
            if (bound[0].kind != RU_NUM || !isfinite(bound[0].n)) ru_fail(line, "实参「值」须为数");
            value = bound[0].n;
            negative = signbit(value);
            /* Every binary64 value outside this range is already integral. */
            if (value > -9007199254740992.0 && value < 9007199254740992.0) value = (double)(int64_t)value;
            if (value == 0 && negative) value = -0.0;
            *out = v_num(value); return 1;
        }
/* RU_END_MEMBERS */
        return 0;
    }
/* RU_MEMBERS: 词,数,行 */
    if (klass == &ru_contest_scanner_class && (!strcmp(name, "词") || !strcmp(name, "数") || !strcmp(name, "行"))) {
        ru_bind(name, 0, NULL, argc, keys, args, bound, line);
        *out = ru_contest_next(receiver, name, line); return 1;
    }
/* RU_END_MEMBERS */
    if (klass == &ru_contest_writer_class) {
/* RU_MEMBERS: 清 */
        if (!strcmp(name, "清")) {
            ru_bind(name, 0, NULL, argc, keys, args, bound, line);
            ru_contest_flush(receiver, line);
            *out = v_null(); return 1;
        }
/* RU_END_MEMBERS */
/* RU_MEMBERS: 写,行 */
        if (!strcmp(name, "写") || !strcmp(name, "行")) {
            int lines = !strcmp(name, "行");
            Val content;
            ru_bind(name, 1, lines ? value_names : content_names, argc, keys, args, bound, line);
            if (bound[0].kind != RU_STR && !(lines && bound[0].kind == RU_NUM))
                ru_fail(line, lines ? "实参「值」须为句或数" : "实参「内容」须为句");
            content = v_to_string(bound[0]);
            ru_contest_write(receiver, content.s->data, content.s->len, line);
            if (lines) ru_contest_write(receiver, "\n", 1, line);
            v_drop(content);
            *out = v_null(); return 1;
        }
/* RU_END_MEMBERS */
    }
    return 0;
}
#endif
