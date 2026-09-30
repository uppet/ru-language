#ifndef RU_TOY_RUNTIME_H
#define RU_TOY_RUNTIME_H

/* Standalone C99 runtime. Generated expressions own their results; operands
 * are borrowed. Environments and copied strings retain their own references.
 * Include this implementation once in each generated translation unit. */
#include <math.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct RuString {
    size_t refs;
    size_t len;
    char data[];
} RuString;

typedef struct Val {
    int kind; /* 0: number, 1: immutable UTF-8 string */
    double n;
    RuString *s;
} Val;

typedef struct RuBinding {
    char *name;
    Val value;
    struct RuBinding *next;
} RuBinding;

typedef struct Env {
    struct Env *parent;
    RuBinding *bindings;
} Env;

const char *ru_source = "<程序>";
static unsigned int ru_call_depth = 0;

void ru_fail(int line, const char *format, ...)
{
    va_list args;
    fprintf(stderr, "%s:%d: 运行错误：", ru_source ? ru_source : "<程序>", line);
    va_start(args, format);
    vfprintf(stderr, format, args);
    va_end(args);
    fputc('\n', stderr);
    exit(1);
}

static void *ru_alloc(size_t size, int line)
{
    void *result = malloc(size);
    if (!result) ru_fail(line, "内存不足");
    return result;
}

static Val ru_string_alloc(size_t len, int line)
{
    Val value;
    if (len > SIZE_MAX - sizeof(RuString) - 1)
        ru_fail(line, "字符串过长");
    value.kind = 1;
    value.n = 0.0;
    value.s = (RuString *)ru_alloc(sizeof(RuString) + len + 1, line);
    value.s->refs = 1;
    value.s->len = len;
    value.s->data[len] = '\0';
    return value;
}

Val v_num(double n)
{
    Val value;
    value.kind = 0;
    value.n = n;
    value.s = NULL;
    return value;
}

Val v_str(const char *s)
{
    size_t len = strlen(s);
    Val value = ru_string_alloc(len, 0);
    memcpy(value.s->data, s, len);
    return value;
}

Val v_copy(Val value)
{
    if (value.kind == 1) {
        if (value.s->refs == SIZE_MAX) ru_fail(0, "字符串引用过多");
        value.s->refs++;
    }
    return value;
}

void v_drop(Val value)
{
    if (value.kind == 1 && --value.s->refs == 0) free(value.s);
}

int v_truth(Val value)
{
    return value.kind == 1 ? value.s->len != 0 : value.n != 0.0;
}

static int ru_ascii_space(unsigned char c)
{
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' ||
           c == '\v' || c == '\f';
}

static int ru_ascii_digit(unsigned char c)
{
    return c >= '0' && c <= '9';
}

static double ru_parse_number(const char *text, int line)
{
    const char *start = text;
    const char *end = text + strlen(text);
    const char *p;
    char *parsed_end;
    int digits = 0;
    double result;

    while (start < end && ru_ascii_space((unsigned char)*start)) start++;
    while (end > start && ru_ascii_space((unsigned char)end[-1])) end--;
    p = start;
    if (p < end && (*p == '+' || *p == '-')) p++;
    while (p < end && ru_ascii_digit((unsigned char)*p)) {
        digits = 1;
        p++;
    }
    if (p < end && *p == '.') {
        p++;
        while (p < end && ru_ascii_digit((unsigned char)*p)) {
            digits = 1;
            p++;
        }
    }
    if (!digits) ru_fail(line, "无法转为数字");
    if (p < end && (*p == 'e' || *p == 'E')) {
        p++;
        if (p < end && (*p == '+' || *p == '-')) p++;
        digits = 0;
        while (p < end && ru_ascii_digit((unsigned char)*p)) {
            digits = 1;
            p++;
        }
        if (!digits) ru_fail(line, "无法转为数字");
    }
    if (p != end) ru_fail(line, "无法转为数字");
    /* A standalone C program starts in the C locale. The explicit grammar
     * above excludes strtod's hexadecimal, infinity, and NaN extensions. */
    result = strtod(start, &parsed_end);
    if (parsed_end != end || !isfinite(result))
        ru_fail(line, "无法转为有限数字");
    return result;
}

Val v_convert(Val value, int targetKind, int line)
{
    if (targetKind == 0) {
        if (value.kind == 0) {
            if (!isfinite(value.n)) ru_fail(line, "数字必须有限");
            return v_copy(value);
        }
        return v_num(ru_parse_number(value.s->data, line));
    }
    if (targetKind == 1) {
        char buffer[64];
        int len;
        Val result;
        if (value.kind == 1) return v_copy(value);
        if (!isfinite(value.n)) ru_fail(line, "数字必须有限");
        len = snprintf(buffer, sizeof(buffer), "%.15g", value.n);
        if (len < 0 || (size_t)len >= sizeof(buffer))
            ru_fail(line, "数字格式化失败");
        result = ru_string_alloc((size_t)len, line);
        memcpy(result.s->data, buffer, (size_t)len);
        return result;
    }
    ru_fail(line, "未知转换类型");
    return v_num(0);
}

static Val ru_finite(double n, int line)
{
    if (!isfinite(n)) ru_fail(line, "运算结果不是有限数字");
    return v_num(n);
}

Val v_unary(const char *op, Val value, int line)
{
    if (strcmp(op, "非") == 0) return v_num(!v_truth(value));
    if (strcmp(op, "+") == 0 || strcmp(op, "-") == 0) {
        if (value.kind != 0) ru_fail(line, "运算符 %s 需要数字", op);
        return ru_finite(op[0] == '-' ? -value.n : value.n, line);
    }
    ru_fail(line, "未知一元运算符：%s", op);
    return v_num(0);
}

Val v_binary(const char *op, Val a, Val b, int line)
{
    if (strcmp(op, "且") == 0) return v_num(v_truth(a) && v_truth(b));
    if (strcmp(op, "或") == 0) return v_num(v_truth(a) || v_truth(b));
    if (strcmp(op, "==") == 0 || strcmp(op, "!=") == 0) {
        int equal = a.kind == b.kind &&
            (a.kind == 0 ? a.n == b.n : strcmp(a.s->data, b.s->data) == 0);
        return v_num(strcmp(op, "==") == 0 ? equal : !equal);
    }
    if (strcmp(op, "含") == 0) {
        if (a.kind != 1 || b.kind != 1) ru_fail(line, "含 需要两个字符串");
        return v_num(strstr(a.s->data, b.s->data) != NULL);
    }
    if (strcmp(op, "<") == 0 || strcmp(op, "<=") == 0 ||
        strcmp(op, ">") == 0 || strcmp(op, ">=") == 0) {
        int cmp;
        if (a.kind != b.kind) ru_fail(line, "比较需要相同类型");
        cmp = a.kind == 0 ? (a.n > b.n) - (a.n < b.n)
                          : strcmp(a.s->data, b.s->data);
        if (strcmp(op, "<") == 0) return v_num(cmp < 0);
        if (strcmp(op, "<=") == 0) return v_num(cmp <= 0);
        if (strcmp(op, ">") == 0) return v_num(cmp > 0);
        return v_num(cmp >= 0);
    }
    if (strcmp(op, "+") == 0 && a.kind == 1 && b.kind == 1) {
        Val result;
        if (a.s->len > SIZE_MAX - b.s->len) ru_fail(line, "字符串过长");
        result = ru_string_alloc(a.s->len + b.s->len, line);
        memcpy(result.s->data, a.s->data, a.s->len);
        memcpy(result.s->data + a.s->len, b.s->data, b.s->len);
        return result;
    }
    if (strcmp(op, "+") == 0 || strcmp(op, "-") == 0 ||
        strcmp(op, "*") == 0 || strcmp(op, "/") == 0 || strcmp(op, "%") == 0) {
        if (a.kind != 0 || b.kind != 0)
            ru_fail(line, "运算符 %s 需要两个数字", op);
        if ((op[0] == '/' || op[0] == '%') && b.n == 0.0)
            ru_fail(line, "除数不能为零");
        switch (op[0]) {
            case '+': return ru_finite(a.n + b.n, line);
            case '-': return ru_finite(a.n - b.n, line);
            case '*': return ru_finite(a.n * b.n, line);
            case '/': return ru_finite(a.n / b.n, line);
            case '%': return ru_finite(fmod(a.n, b.n), line);
        }
    }
    ru_fail(line, "未知二元运算符：%s", op);
    return v_num(0);
}

void v_print(Val value)
{
    if (value.kind == 1) fputs(value.s->data, stdout);
    else printf("%.15g", value.n);
    fputc('\n', stdout);
}

uint64_t v_count(Val value, int line)
{
    if (value.kind != 0 || !isfinite(value.n) || value.n < 0.0 ||
        value.n > 9007199254740991.0 || floor(value.n) != value.n)
        ru_fail(line, "重复次数须为 0 至 9007199254740991 的整数");
    return (uint64_t)value.n;
}

void env_init(Env *env, Env *parent)
{
    env->parent = parent;
    env->bindings = NULL;
}

Val env_get(Env *env, const char *name, int line)
{
    Env *scope;
    for (scope = env; scope; scope = scope->parent) {
        RuBinding *binding;
        for (binding = scope->bindings; binding; binding = binding->next) {
            if (strcmp(binding->name, name) == 0) return v_copy(binding->value);
        }
    }
    ru_fail(line, "未定义变量：%s", name);
    return v_num(0);
}

void env_set(Env *env, const char *name, Val value)
{
    RuBinding *binding;
    Val retained = v_copy(value);
    for (binding = env->bindings; binding; binding = binding->next) {
        if (strcmp(binding->name, name) == 0) {
            v_drop(binding->value);
            binding->value = retained;
            return;
        }
    }
    binding = (RuBinding *)ru_alloc(sizeof(RuBinding), 0);
    binding->name = (char *)ru_alloc(strlen(name) + 1, 0);
    strcpy(binding->name, name);
    binding->value = retained;
    binding->next = env->bindings;
    env->bindings = binding;
}

void env_free(Env *env)
{
    RuBinding *binding = env->bindings;
    while (binding) {
        RuBinding *next = binding->next;
        free(binding->name);
        v_drop(binding->value);
        free(binding);
        binding = next;
    }
    env->bindings = NULL;
    env->parent = NULL;
}

Val read_input(Val prompt, int line)
{
    size_t len = 0;
    size_t capacity = 128;
    char *buffer;
    int ch;
    Val result;
    if (prompt.kind != 1) ru_fail(line, "输入提示须为字符串");
    if (fputs(prompt.s->data, stdout) == EOF || fflush(stdout) == EOF)
        ru_fail(line, "输出失败");
    buffer = (char *)ru_alloc(capacity, line);
    while ((ch = fgetc(stdin)) != EOF && ch != '\n') {
        if (ch == 0) {
            free(buffer);
            ru_fail(line, "输入不能含空字符");
        }
        if (len == capacity - 1) {
            char *grown;
            if (capacity > SIZE_MAX / 2) {
                free(buffer);
                ru_fail(line, "输入过长");
            }
            capacity *= 2;
            grown = (char *)realloc(buffer, capacity);
            if (!grown) {
                free(buffer);
                ru_fail(line, "内存不足");
            }
            buffer = grown;
        }
        buffer[len++] = (char)ch;
    }
    if (ferror(stdin)) {
        free(buffer);
        ru_fail(line, "读取输入失败");
    }
    if (ch == EOF && len == 0) {
        free(buffer);
        ru_fail(line, "输入结束（EOF）");
    }
    if (len > 0 && buffer[len - 1] == '\r') len--;
    result = ru_string_alloc(len, line);
    memcpy(result.s->data, buffer, len);
    free(buffer);
    return result;
}

void ru_enter(int line)
{
    if (ru_call_depth >= 128) ru_fail(line, "函数调用深度超过 128");
    ru_call_depth++;
}

void ru_leave(void)
{
    if (ru_call_depth > 0) ru_call_depth--;
}

#endif
