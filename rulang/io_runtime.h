#ifndef RU_IO_RUNTIME_H
#define RU_IO_RUNTIME_H
/* Checked UTF-8 I/O. Paths follow symlinks except deletion; listings never recurse. */
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <io.h>
#include <windows.h>
#define ru_io_close _close
#define ru_io_fdopen _fdopen
#define ru_io_fstat _fstat64
#define ru_io_statbuf struct _stat64
#define RU_IO_NONBLOCK 0
#define RU_IO_BINARY _O_BINARY
#ifndef S_ISREG
#define S_ISREG(mode) (((mode) & _S_IFMT) == _S_IFREG)
#endif
#else
#include <dirent.h>
#include <unistd.h>
#include <signal.h>
#define ru_io_open open
#define ru_io_close close
#define ru_io_fdopen fdopen
#define ru_io_fstat fstat
#define ru_io_stat stat
#define ru_io_statbuf struct stat
#define ru_io_unlink unlink
#define RU_IO_NONBLOCK O_NONBLOCK
#define RU_IO_BINARY 0
#endif

#ifdef _WIN32
/* Convert strict UTF-8 to Windows wide APIs; never use the active ANSI codepage. */
static int ru_io_windows_errno(DWORD code)
{
    if (code == ERROR_FILE_NOT_FOUND || code == ERROR_PATH_NOT_FOUND) return ENOENT;
    if (code == ERROR_ACCESS_DENIED || code == ERROR_SHARING_VIOLATION) return EACCES;
    if (code == ERROR_DIRECTORY) return ENOTDIR;
    if (code == ERROR_DISK_FULL) return ENOSPC;
    if (code == ERROR_NOT_ENOUGH_MEMORY || code == ERROR_OUTOFMEMORY) return ENOMEM;
    return EIO;
}
static wchar_t *ru_io_wide(const char *path)
{
    int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, NULL, 0);
    wchar_t *wide;
    if (!count) { errno = EILSEQ; return NULL; }
    wide = (wchar_t *)malloc((size_t)count * sizeof(wchar_t));
    if (!wide) { errno = ENOMEM; return NULL; }
    if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, wide, count)) {
        free(wide); errno = EILSEQ; return NULL;
    }
    return wide;
}
static int ru_io_open(const char *path, int flags, int mode)
{
    wchar_t *wide = ru_io_wide(path);
    int result, error;
    if (!wide) return -1;
    result = _wopen(wide, flags, mode); error = errno;
    free(wide); errno = error; return result;
}
static int ru_io_stat(const char *path, struct _stat64 *status)
{
    wchar_t *wide = ru_io_wide(path);
    int result, error;
    if (!wide) return -1;
    result = _wstat64(wide, status); error = errno;
    free(wide); errno = error; return result;
}
static int ru_io_unlink(const char *path)
{
    wchar_t *wide = ru_io_wide(path);
    DWORD attributes;
    int good;
    if (!wide) return -1;
    attributes = GetFileAttributesW(wide);
    if (attributes == INVALID_FILE_ATTRIBUTES) {
        errno = ru_io_windows_errno(GetLastError()); free(wide); return -1;
    }
    if (attributes & FILE_ATTRIBUTE_DIRECTORY) {
        if (!(attributes & FILE_ATTRIBUTE_REPARSE_POINT)) { free(wide); errno = EINVAL; return -1; }
        good = RemoveDirectoryW(wide);
    } else good = DeleteFileW(wide);
    if (!good) errno = ru_io_windows_errno(GetLastError());
    free(wide); return good ? 0 : -1;
}
#endif

static const char *ru_io_path_names[] = {"路径"};
static const char *ru_io_path_types[] = {"句"};
static const char *ru_io_result_names[] = {"结果", "值", "错误信息"};
static const char *ru_io_result_types[] = {"句", "", "句"};
static RuClass ru_io_file_class = {"件", NULL, NULL, 1, ru_io_path_names, ru_io_path_types, 0, NULL};
static RuClass ru_io_directory_class = {"录", NULL, NULL, 1, ru_io_path_names, ru_io_path_types, 0, NULL};
static RuClass ru_io_result_class = {"件作成果", NULL, NULL, 3, ru_io_result_names, ru_io_result_types, 0, NULL};
static RuClass ru_io_input_class = {"输入流", NULL, NULL, 0, NULL, NULL, 0, NULL};
static RuClass ru_io_output_class = {"输出流", NULL, NULL, 0, NULL, NULL, 0, NULL};
static RuClass ru_io_error_class = {"输出流", NULL, NULL, 0, NULL, NULL, 0, NULL};

/* Assign a heap value as a container edge and release its temporary root. */
static void ru_io_edge(Val object, size_t index, Val value)
{
    ((RuObject *)object.heap)->fields[index] = value;
    v_drop(value);
}
static void ru_io_defaults(Val value, int line)
{
    RuClass *klass;
    (void)line;
    if (value.kind != RU_OBJECT) return;
    klass = ((RuObject *)value.heap)->klass;
    if (klass == &ru_io_file_class) ru_io_edge(value, 0, v_str(""));
    else if (klass == &ru_io_directory_class) ru_io_edge(value, 0, v_str("."));
    else if (klass == &ru_io_result_class) {
        ru_io_edge(value, 0, v_str("成功"));
        ru_io_edge(value, 2, v_str(""));
    }
}
static Env *ru_io_builtins(void)
{
    static Env env;
    static int initialized;
    Val stream;
    if (initialized) return &env;
    initialized = 1;
#ifndef _WIN32
    /* A disconnected output pipe is a checked EPIPE result, not termination. */
    signal(SIGPIPE, SIG_IGN);
#endif
    env_init(&env, NULL);
    ru_io_file_class.global = ru_io_directory_class.global = ru_io_result_class.global = &env;
    ru_io_input_class.global = ru_io_output_class.global = ru_io_error_class.global = &env;
    env_declare(&env, "件", v_class(&ru_io_file_class));
    env_declare(&env, "录", v_class(&ru_io_directory_class));
    env_declare(&env, "件作成果", v_class(&ru_io_result_class));
    stream = v_new(v_class(&ru_io_input_class), 0, NULL, NULL, 0);
    env_declare(&env, "读取", stream); v_drop(stream);
    stream = v_new(v_class(&ru_io_output_class), 0, NULL, NULL, 0);
    env_declare(&env, "显出", stream); v_drop(stream);
    stream = v_new(v_class(&ru_io_error_class), 0, NULL, NULL, 0);
    env_declare(&env, "错误", stream); v_drop(stream);
    return &env;
}
static Val ru_io_result(Val value, int number, const char *operation, const char *message, int line)
{
    Val out = v_new(v_class(&ru_io_result_class), 0, NULL, NULL, line);
    if (number) {
        char diagnostic[512];
        const char *detail = message ? message : strerror(number);
        /* Some locale-dependent strerror text is not UTF-8. Keep the errno
         * even then, rather than turning a checked failure into a panic. */
        if (!ru_valid_utf8(detail, strlen(detail))) detail = "I/O failure";
        snprintf(diagnostic, sizeof(diagnostic), "%s: [errno %d] %.400s", operation, number, detail);
        /* Truncation cannot split a multibyte diagnostic into an invalid value. */
        if (!ru_valid_utf8(diagnostic, strlen(diagnostic)))
            snprintf(diagnostic, sizeof(diagnostic), "%s: [errno %d] I/O failure", operation, number);
        ru_io_edge(out, 0, v_str("失败"));
        ru_io_edge(out, 2, v_str(diagnostic));
    } else ((RuObject *)out.heap)->fields[1] = value;
    return out;
}
static int ru_io_text(Val value, const char **message)
{
    if (value.kind != RU_STR) { *message = "路径或内容须为句"; return EINVAL; }
    if (memchr(value.s->data, 0, value.s->len)) { *message = "文本不能含 NUL"; return EINVAL; }
    if (!ru_valid_utf8(value.s->data, value.s->len)) { *message = "文本不是有效的 UTF-8"; return EILSEQ; }
    return 0;
}
static int ru_io_errno(void) { return errno ? errno : EIO; }
static FILE *ru_io_open_regular(const char *path, int writing, int append, int *error)
{
    int fd, flags = (writing ? O_WRONLY | O_CREAT : O_RDONLY) | RU_IO_BINARY | RU_IO_NONBLOCK;
    ru_io_statbuf status;
    FILE *stream;
    if (append) flags |= O_APPEND;
    errno = 0;
    fd = ru_io_open(path, flags, 0666);
    if (fd < 0) { *error = ru_io_errno(); return NULL; }
    if (ru_io_fstat(fd, &status) != 0) { *error = ru_io_errno(); ru_io_close(fd); return NULL; }
    if (!S_ISREG(status.st_mode)) { *error = EINVAL; ru_io_close(fd); return NULL; }
    if (writing && !append) {
#ifdef _WIN32
        { int code = (int)_chsize_s(fd, 0); if (code) { *error = code; ru_io_close(fd); return NULL; } }
#else
        if (ftruncate(fd, 0) != 0) { *error = ru_io_errno(); ru_io_close(fd); return NULL; }
#endif
    }
    stream = ru_io_fdopen(fd, writing ? "wb" : "rb");
    if (!stream) { *error = ru_io_errno(); ru_io_close(fd); }
    return stream;
}
static int ru_io_grow(char **buffer, size_t *capacity, size_t needed)
{
    size_t next;
    char *grown;
    if (needed <= *capacity) return 0;
    next = *capacity ? *capacity : 4096;
    while (next < needed) {
        if (next > SIZE_MAX / 2) { next = needed; break; }
        next *= 2;
    }
    grown = (char *)realloc(*buffer, next);
    if (!grown) return ENOMEM;
    *buffer = grown; *capacity = next;
    return 0;
}
static Val ru_io_read(FILE *stream, int close_stream, int one_line, int line)
{
    char *buffer = NULL;
    const char *message = NULL;
    size_t len = 0, capacity = 0;
    int error = 0, eof = 0;
    Val value = v_null(), result;
    if (!close_stream) clearerr(stream);
    errno = 0;
    if (one_line) {
        int ch;
        while ((ch = fgetc(stream)) != EOF && ch != '\n') {
            if (len == SIZE_MAX) { error = EOVERFLOW; break; }
            error = ru_io_grow(&buffer, &capacity, len + 1);
            if (error) break;
            buffer[len++] = (char)ch;
        }
        if (!error && ferror(stream)) error = ru_io_errno();
        eof = ch == EOF && len == 0 && !error;
        if (len && buffer[len-1] == '\r') --len;
    } else {
        for (;;) {
            size_t got;
            if (len > SIZE_MAX - 4096) { error = EOVERFLOW; break; }
            error = ru_io_grow(&buffer, &capacity, len + 4096);
            if (error) break;
            errno = 0;
            got = fread(buffer + len, 1, 4096, stream);
            len += got;
            if (ferror(stream)) { error = ru_io_errno(); break; }
            if (!got) break;
        }
    }
    if (close_stream) {
        errno = 0;
        if (fclose(stream) != 0 && !error) error = ru_io_errno();
    }
    if (!error && len && memchr(buffer, 0, len)) { error = EINVAL; message = "文本不能含 NUL"; }
    if (!error && !ru_valid_utf8(buffer, len)) { error = EILSEQ; message = "文本不是有效的 UTF-8"; }
    if (!error && !eof) {
        value = ru_string_alloc(len, line);
        if (len) memcpy(value.s->data, buffer, len);
    }
    free(buffer);
    result = ru_io_result(value, error, "读", message, line);
    v_drop(value);
    return result;
}
static Val ru_io_write(FILE *stream, int close_stream, Val content, int line)
{
    int error = 0;
    size_t written;
    if (!close_stream) clearerr(stream);
    errno = 0;
    written = fwrite(content.s->data, 1, content.s->len, stream);
    if (written != content.s->len || ferror(stream)) error = ru_io_errno();
    errno = 0;
    if (fflush(stream) != 0 && !error) error = ru_io_errno();
    if (close_stream) {
        errno = 0;
        if (fclose(stream) != 0 && !error) error = ru_io_errno();
    }
    return ru_io_result(v_null(), error, "写", NULL, line);
}
static int ru_io_name_compare(const void *left, const void *right)
{ return strcmp(*(const char *const *)left, *(const char *const *)right); }
static char *ru_io_join(const char *path, const char *name)
{
    size_t a = strlen(path), b = strlen(name);
#ifdef _WIN32
    int separator = a && path[a-1] != '/' && path[a-1] != '\\';
    const char slash = '\\';
#else
    int separator = a && path[a-1] != '/';
    const char slash = '/';
#endif
    char *joined;
    if (a > SIZE_MAX - b - 2) { errno = EOVERFLOW; return NULL; }
    joined = (char *)malloc(a + b + (size_t)separator + 1);
    if (!joined) { errno = ENOMEM; return NULL; }
    memcpy(joined, path, a);
    if (separator) joined[a++] = slash;
    memcpy(joined + a, name, b + 1);
    return joined;
}
/* Add only regular files, inspecting every entry's UTF-8 name before use. */
static int ru_io_list_entry(const char *path, const char *name, char ***names, size_t *count, size_t *capacity)
{
    char *full;
    char **grown;
    ru_io_statbuf status;
    size_t len = strlen(name), next;
    int number;
    if (!strcmp(name, ".") || !strcmp(name, "..")) return 0;
    if (!ru_valid_utf8(name, len)) return EILSEQ;
    full = ru_io_join(path, name);
    if (!full) return ru_io_errno();
    if (ru_io_stat(full, &status) != 0) {
        number = ru_io_errno(); free(full);
        return number == ENOENT || number == ENOTDIR ? 0 : number;
    }
    if (!S_ISREG(status.st_mode)) { free(full); return 0; }
    free(full);
    if (*count == *capacity) {
        if (*capacity > SIZE_MAX / sizeof(char *) / 2) return EOVERFLOW;
        next = *capacity ? *capacity * 2 : 16;
        grown = (char **)realloc(*names, next * sizeof(char *));
        if (!grown) return ENOMEM;
        *names = grown; *capacity = next;
    }
    (*names)[*count] = (char *)malloc(len + 1);
    if (!(*names)[*count]) return ENOMEM;
    memcpy((*names)[(*count)++], name, len + 1);
    return 0;
}
static Val ru_io_list(const char *path, int line)
{
    char **names = NULL;
    size_t count = 0, capacity = 0, i;
    int error = 0;
    Val values = v_null(), result;
#ifdef _WIN32
    WIN32_FIND_DATAW entry;
    HANDLE directory = INVALID_HANDLE_VALUE;
    char *pattern = NULL;
    wchar_t *wide = NULL;
    ru_io_statbuf status;
    if (ru_io_stat(path, &status) != 0) error = ru_io_errno();
    else if ((status.st_mode & _S_IFMT) != _S_IFDIR) error = ENOTDIR;
    if (!error) pattern = ru_io_join(path, "*");
    if (!error && !pattern) error = ru_io_errno();
    if (!error) wide = ru_io_wide(pattern);
    if (!error && !wide) error = ru_io_errno();
    if (!error) {
        directory = FindFirstFileW(wide, &entry);
        if (directory == INVALID_HANDLE_VALUE && GetLastError() != ERROR_FILE_NOT_FOUND)
            error = ru_io_windows_errno(GetLastError());
    }
    free(wide); free(pattern);
    if (directory != INVALID_HANDLE_VALUE) {
        do {
            int bytes = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, entry.cFileName, -1, NULL, 0, NULL, NULL);
            char *name = bytes ? (char *)malloc((size_t)bytes) : NULL;
            if (!bytes) { error = EILSEQ; break; }
            if (!name) { error = ENOMEM; break; }
            if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, entry.cFileName, -1, name, bytes, NULL, NULL))
                error = EILSEQ;
            else error = ru_io_list_entry(path, name, &names, &count, &capacity);
            free(name);
        } while (!error && FindNextFileW(directory, &entry));
        if (!error && GetLastError() != ERROR_NO_MORE_FILES) error = ru_io_windows_errno(GetLastError());
        if (!FindClose(directory) && !error) error = EIO;
    }
#else
    DIR *directory;
    struct dirent *entry;
    errno = 0;
    directory = opendir(path);
    if (!directory) error = ru_io_errno();
    else {
        for (;;) {
            errno = 0;
            entry = readdir(directory);
            if (!entry) { if (errno) error = errno; break; }
            error = ru_io_list_entry(path, entry->d_name, &names, &count, &capacity);
            if (error) break;
        }
        errno = 0;
        if (closedir(directory) != 0 && !error) error = ru_io_errno();
    }
#endif
    if (!error) {
        if (count > 1) qsort(names, count, sizeof(char *), ru_io_name_compare);
        values = v_array(0, NULL, line);
        for (i = 0; i < count; ++i) {
            char *full = ru_io_join(path, names[i]);
            Val file, location, added;
            if (!full) { error = ru_io_errno(); break; }
            location = v_str(full); free(full);
            file = v_new(v_class(&ru_io_file_class), 0, NULL, NULL, line);
            ((RuObject *)file.heap)->fields[0] = location;
            added = v_append(values, file, line);
            v_drop(added); v_drop(file); v_drop(location);
        }
    }
    for (i = 0; i < count; ++i) free(names[i]);
    free(names);
    result = ru_io_result(values, error, "列", error == EILSEQ ? "文件名不是有效的 UTF-8" : NULL, line);
    v_drop(values);
    return result;
}
/* Optional 追加 is the trailing second argument; names are not keywords. */
static int ru_io_arguments(const char *name, size_t argc, const char **keys, Val *args,
                           int writing, int append_allowed, Val *content, Val *append, int line)
{
    size_t i;
    int seen_content = 0, seen_append = 0, positional = argc && !keys[0];
    *content = v_null(); *append = v_num(0);
    if (!writing) {
        if (argc) { ru_fail(line, "方法「%s」不接收实参", name); return 0; }
        return 1;
    }
    if (positional) {
        if (argc < 1 || argc > (size_t)(append_allowed ? 2 : 1)) {
            ru_fail(line, "方法「%s」实参数量错误", name); return 0;
        }
        for (i = 0; i < argc; ++i) if (keys[i]) {
            ru_fail(line, "同一次调用不能混用位置实参与命名实参"); return 0;
        }
        *content = args[0]; if (argc == 2) *append = args[1];
        return 1;
    }
    for (i = 0; i < argc; ++i) {
        if (!keys[i]) { ru_fail(line, "同一次调用不能混用位置实参与命名实参"); return 0; }
        if (!strcmp(keys[i], "内容") && !seen_content) { *content = args[i]; seen_content = 1; }
        else if (append_allowed && !strcmp(keys[i], "追加") && !seen_append) { *append = args[i]; seen_append = 1; }
        else { ru_fail(line, "方法「%s」未知或重复实参：%s", name, keys[i]); return 0; }
    }
    if (!seen_content) { ru_fail(line, "方法「%s」缺少实参：内容", name); return 0; }
    return 1;
}
static int ru_io_member(Val receiver, const char *name, size_t argc, const char **keys,
                        Val *args, int line, Val *out)
{
    RuClass *klass;
    Val content, append, path;
    int file, directory, input, output, writing, error = 0;
    const char *message = NULL;
    FILE *stream;
    ru_io_statbuf status;
    if (receiver.kind != RU_OBJECT) return 0;
    klass = ((RuObject *)receiver.heap)->klass;
    file = klass == &ru_io_file_class; directory = klass == &ru_io_directory_class;
    input = klass == &ru_io_input_class;
    output = klass == &ru_io_output_class || klass == &ru_io_error_class;
    writing = !strcmp(name, "写");
    if (!(file && (writing || !strcmp(name, "读") || !strcmp(name, "在") || !strcmp(name, "除"))) &&
        !(directory && !strcmp(name, "列")) && !(input && !strcmp(name, "读")) && !(output && writing)) return 0;
    if (!ru_io_arguments(name, argc, keys, args, writing, file, &content, &append, line)) {
        *out = v_null(); return 1;
    }
    if (writing) {
        error = ru_io_text(content, &message);
        if (!error && (append.kind != RU_NUM || (append.n != 0 && append.n != 1))) {
            error = EINVAL; message = "追加须为数 0 或 1";
        }
    }
    if (!error && (file || directory)) {
        path = ((RuObject *)receiver.heap)->fields[0];
        error = ru_io_text(path, &message);
        if (!error && !path.s->len) { error = EINVAL; message = "路径不能为空"; }
    } else path = v_null();
    if (error) { *out = ru_io_result(v_null(), error, name, message, line); return 1; }
    if (input) *out = ru_io_read(stdin, 0, 1, line);
    else if (output) *out = ru_io_write(klass == &ru_io_error_class ? stderr : stdout, 0, content, line);
    else if (directory) *out = ru_io_list(path.s->data, line);
    else if (writing || !strcmp(name, "读")) {
        stream = ru_io_open_regular(path.s->data, writing, append.n != 0, &error);
        *out = stream ? (writing ? ru_io_write(stream, 1, content, line) : ru_io_read(stream, 1, 0, line)) :
                       ru_io_result(v_null(), error, name, NULL, line);
    } else if (!strcmp(name, "在")) {
        errno = 0;
        if (ru_io_stat(path.s->data, &status) == 0)
            *out = ru_io_result(v_fact(S_ISREG(status.st_mode) ? 1 : 0), 0, name, NULL, line);
        else { error = ru_io_errno();
            *out = error == ENOENT || error == ENOTDIR ? ru_io_result(v_fact(0), 0, name, NULL, line) :
                ru_io_result(v_null(), error, name, NULL, line);
        }
    } else {
        errno = 0;
#ifdef _WIN32
        /* ru_io_unlink checks attributes without following reparse targets. */
#else
        if (lstat(path.s->data, &status) != 0) error = ru_io_errno();
        else if (!S_ISREG(status.st_mode) && !S_ISLNK(status.st_mode)) error = EINVAL;
#endif
        if (!error && ru_io_unlink(path.s->data) != 0) error = ru_io_errno();
        *out = ru_io_result(v_null(), error, name, NULL, line);
    }
    return 1;
}
#endif
