/* Platform mechanics only. No GUI class, window, layout, or message policy. */
#if !defined(_WIN32) || !(defined(_M_X64) || defined(__x86_64__)) || defined(_M_ARM64) || defined(_M_ARM64EC)
#error "Ru native C applications currently require a Windows x64 C compiler/target"
#endif
typedef char RuNativePointerMustBe64Bits[sizeof(void *) == 8 ? 1 : -1];
static uint32_t ru_native_thread_id;
/* Wrong-thread callbacks may only touch immutable slot fields and this atomic
 * flag. They never enter the non-thread-safe language heap or run Ru code. */
static volatile LONG ru_native_wrong_thread;
static uint32_t rn_platform_thread(void) { return (uint32_t)GetCurrentThreadId(); }
static uint32_t rn_platform_error(void) { return (uint32_t)GetLastError(); }
static void rn_platform_set_error(uint32_t error) { SetLastError((DWORD)error); }
static void rn_platform_thread_error(void) { InterlockedExchange(&ru_native_wrong_thread, 1); }
static int rn_platform_wrong_thread(int clear)
{
    return clear ? (int)InterlockedExchange(&ru_native_wrong_thread, 0) : (int)InterlockedCompareExchange(&ru_native_wrong_thread, 0, 0);
}
static void *ru_native_load_library(const char *text, const unsigned char *utf16, int system, int line)
{
    size_t i, length = strlen(text);
    HMODULE handle;
    if (system) {
        if (length < 5 || _stricmp(text + length - 4, ".dll")) ru_fail(line, "系统库只接受 DLL 文件名，并仅从 System32 加载");
        for (i = 0; i < length - 4; ++i) {
            unsigned c = (unsigned char)text[i];
            if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-'))
                ru_fail(line, "系统库只接受 DLL 文件名，并仅从 System32 加载");
        }
    } else {
        int drive = length >= 3 && ((text[0] >= 'a' && text[0] <= 'z') || (text[0] >= 'A' && text[0] <= 'Z')) && text[1] == ':' && (text[2] == '\\' || text[2] == '/');
        int unc = length >= 5 && text[0] == '\\' && text[1] == '\\';
        DWORD attributes;
        if (!drive && !unc) ru_fail(line, "动态库只接受现有文件的绝对路径；禁止隐式当前目录搜索");
        attributes = GetFileAttributesW((const wchar_t *)utf16);
        if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_DIRECTORY)) ru_fail(line, "动态库只接受现有文件的绝对路径");
    }
    handle = LoadLibraryExW((const wchar_t *)utf16, NULL, system ? 0x800 : 0x100 | 0x800);
    if (!handle) { DWORD error = GetLastError(); ru_fail(line, "加载动态库失败（Windows 错误 %lu）", (unsigned long)error); }
    return (void *)handle;
}
static void *ru_native_find_symbol(void *handle, const char *name)
{
    union { FARPROC function; void *address; } result;
    result.function = GetProcAddress((HMODULE)handle, name);
    return result.address;
}
