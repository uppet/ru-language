"""Dependency-closed source pruning for the bundled C runtime.

This is deliberately not a general C optimizer. Runtime functions follow the
header's plain, top-level definition convention; everything else (types, globals,
preprocessor directives, platform alternatives) is conservatively retained.
References include function addresses and macro bodies, not only calls. Comments
and literals are masked before scanning, and retained text is never minified.
"""
import re
from pathlib import Path
from .frontend import Node


# Markers describe closed sets of statically spelled Ru member names. Unknown
# receiver types are safe: all implementations of a used name remain eligible.
_MAP_REGION = re.compile(r'/\* RU_MAP \*/\n(.*?)/\* RU_END_MAP \*/\n', re.S)
_FEATURE = re.compile(r'/\* RU_FEATURE: (\w+) \*/\n(.*?)/\* RU_ELSE_FEATURE \*/\n(.*?)/\* RU_END_FEATURE \*/\n', re.S)
_REGION = re.compile(r'/\* RU_MEMBERS: ([^\n*]+) \*/\n(.*?)/\* RU_END_MEMBERS \*/\n', re.S)
_C_NONCODE = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)
_IDENT = re.compile(r'\b[A-Za-z_]\w*\b', re.ASCII)
_FUNCTION = re.compile(
    r'(?m)^(?:static\s+)?(?:[A-Za-z_]\w*\s+|\*\s*)+'
    r'([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{', re.ASCII)
_PROTOTYPE = re.compile(
    r'(?m)^static\s+(?:[A-Za-z_]\w*\s+|\*\s*)+'
    r'([A-Za-z_]\w*)\s*\([^;{}]*\)\s*;', re.ASCII)


def mask_noncode(source):
    """Preserve offsets/newlines while hiding strings, characters and comments."""
    return _C_NONCODE.sub(lambda m: ''.join('\n' if c == '\n' else ' ' for c in m[0]), source)


def member_names(value):
    """Include implicit operator dispatch as well as explicit member syntax."""
    names = set()
    def visit(value):
        if isinstance(value, Node):
            if value.kind == 'member':
                names.add(value.data['name'])
            if value.kind == 'binary' and value.data['op'] == '含':
                names.add('含')
            visit(value.data)
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)
    visit(value)
    return names


def specialize_members(source, names):
    return _REGION.sub(lambda m: m[2] if names.intersection(m[1].split(',')) else '', source)


def prune_functions(source, roots):
    """Keep the transitive identifier closure of roots and all nonfunction text.

    Function declarations do not root their definitions. Same-name alternative
    definitions (e.g. Windows/POSIX implementations) are all kept when reachable.
    Directives remain in place, so this requires no host C compiler/preprocessor
    and produces portable C rather than a host-specific preprocessed dump.
    """
    masked = mask_noncode(source)
    spans = []
    comments = [m for m in _C_NONCODE.finditer(source) if m[0].startswith(('/*', '//'))]
    end = 0
    for match in _FUNCTION.finditer(masked):
        if match.start() < end:
            continue
        depth, end = 1, match.end()
        while depth and end < len(masked):
            depth += (masked[end] == '{') - (masked[end] == '}')
            end += 1
        if depth:
            raise ValueError('Unbalanced bundled runtime function: ' + match[1])
        start = match.start()
        # Documentation attached to an unreachable function belongs to it too.
        # Never consume intervening directives, declarations or marker comments.
        for comment in reversed(comments):
            if comment.end() > start:
                continue
            if source[comment.end():start].strip() or 'RU_' in comment[0]:
                break
            start = comment.start()
        spans.append((start, end, match[1], True))
    for match in _PROTOTYPE.finditer(masked):
        if not any(start <= match.start() < end for start, end, _, _ in spans):
            spans.append((match.start(), match.end(), match[1], False))
    spans.sort()
    dependencies = {}
    rest, at = [], 0
    for start, end, name, definition in spans:
        rest.append(masked[at:start])
        at = end
        if definition:
            dependencies.setdefault(name, set()).update(_IDENT.findall(masked[start:end]))
    rest.append(masked[at:])
    live = set(_IDENT.findall(mask_noncode(roots) + ''.join(rest)))
    pending = list(live)
    while pending:
        for child in dependencies.get(pending.pop(), set()) - live:
            live.add(child)
            pending.append(child)
    result, at = [], 0
    for start, end, name, _ in spans:
        result.append(source[at:start])
        if name in live:
            result.append(source[start:end])
        at = end
    result.append(source[at:])
    # Empty lines left by removed definitions are not meaningful source layout.
    return re.sub(r'\n{3,}', '\n\n', ''.join(result))


def walk_nodes(value):
    if isinstance(value, Node):
        yield value
        yield from walk_nodes(value.data)
    elif isinstance(value, dict):
        for child in value.values():
            yield from walk_nodes(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from walk_nodes(child)


def ast_strings(value):
    if isinstance(value, Node):
        yield from ast_strings(value.data)
    elif isinstance(value, dict):
        for child in value.values():
            yield from ast_strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from ast_strings(child)
    elif isinstance(value, str):
        yield value


_IO_STUB = r'''/* Checked I/O is unreferenced; retain the process-wide pipe contract. */
#ifndef _WIN32
#include <signal.h>
#endif
static Env *ru_io_builtins(void)
{
#ifndef _WIN32
    signal(SIGPIPE, SIG_IGN);
#endif
    return NULL;
}
static void ru_io_defaults(Val value, int line) { (void)value; (void)line; }
static int ru_io_member(Val receiver, const char *name, size_t argc, const char **keys,
                        Val *args, int line, Val *out)
{
    (void)receiver; (void)name; (void)argc; (void)keys; (void)args; (void)line; (void)out;
    return 0;
}
'''


def runtime_source(modules, generated, full=False, native_plan=None):
    directory = Path(__file__).parent
    headers = [(directory / name).read_text(encoding='utf-8')
               for name in ('runtime.h', 'io_runtime.h', 'contest_runtime.h', 'practical_runtime.h',
                            'graphics_runtime.h', 'audio_runtime.h')]
    if native_plan is not None:
        from .native_c_runtime import integrate_runtime, integrate_io
        headers[0] = integrate_runtime(headers[0])
        headers[1] = integrate_io(headers[1])
        headers.append((directory / 'native_runtime.h').read_text(encoding='utf-8'))
        headers.append(native_plan.emit_c())
    if full:
        source = _FEATURE.sub(lambda m: m[2], _MAP_REGION.sub(lambda m: m[1], '\n'.join(headers)))
        return re.sub(r'/\* RU_(?:MEMBERS: [^*]*|OPERATORS: [^*]*|END_MEMBERS) \*/\n', '', source)
    strings = set(ast_strings(modules))
    from .modules import import_nodes
    stdlib_ruguan = directory / 'stdlib' / '如观.ru'
    uses_graphics = any(node.data.get("path") == "如:观" or Path(node.data.get("resolved", "")).resolve() == stdlib_ruguan.resolve() for node in import_nodes(modules))
    stdlib_rusheng = directory / 'stdlib' / '如声.ru'
    uses_audio = any(node.data.get("path") == "如:声" or Path(node.data.get("resolved", "")).resolve() == stdlib_rusheng.resolve() for node in import_nodes(modules))
    if uses_graphics and uses_audio:
        # 图形+音频并存：如观 builtins 的父链改挂如声 builtins，
        # 使 __如声 在图形环境也可用（反之 audio 头独立时自带 practical 父链）。
        headers[4] = headers[4].replace(
            'env_init(&env, ru_practical_builtins());',
            'env_init(&env, ru_audio_builtins());', 1)
    if not uses_audio:
        headers[5] = """
static Env *ru_audio_builtins(void) { return ru_practical_builtins(); }
static int ru_audio_member(Val receiver, const char *name, size_t argc,
                           const char **keys, Val *args, int line, Val *out)
{
    (void)receiver; (void)name; (void)argc; (void)keys; (void)args; (void)line; (void)out;
    return 0;
}
"""
    if not uses_graphics:
        headers[4] = """
/* 音频可独立使用：消费方（audio_runtime.h 与 SDL 宿主链接根）需要
 * RuAudioHost 类型与注册入口；完整声明镜像 graphics_runtime.h。 */
typedef struct RuAudioHost {
    const char *name;
    int (*open)(void);
    void (*close)(void);
    long (*play)(const char *path, int loop);
    int (*stop)(long channel);
    int (*pause)(long channel);
    int (*resume)(long channel);
    int (*volume)(long channel, int pct);
    double (*position)(long channel);
    int (*playing)(long channel);
} RuAudioHost;
static const RuAudioHost **ru_audio_host_slot(void)
{
    static const RuAudioHost *host;
    return &host;
}
void ru_audio_set_host(const RuAudioHost *host) { *ru_audio_host_slot() = host; }
static Env *ru_graphics_builtins(void) { return ru_practical_builtins(); }
static int ru_graphics_member(Val receiver, const char *name, size_t argc,
                              const char **keys, Val *args, int line, Val *out)
{
    (void)receiver; (void)name; (void)argc; (void)keys; (void)args; (void)line; (void)out;
    return 0;
}
"""
    if '__实用' not in strings:
        headers[3] = """
static Env *ru_practical_builtins(void) { return ru_contest_builtins(); }
static int ru_practical_member(Val receiver, const char *name, size_t argc,
                              const char **keys, Val *args, int line, Val *out)
{
    (void)receiver; (void)name; (void)argc; (void)keys; (void)args; (void)line; (void)out;
    return 0;
}
"""
    io_names = {'件', '录', '件作成果', '读取', '显出', '错误'}
    # Empty (untyped) parameter annotations add no type dependency.
    # Type annotations may include a trailing array qualifier. Unknown strings
    # conservatively keep I/O, including string literals that merely name it.
    uses_io = any(word in io_names for text in strings for word in text.split())
    if not uses_io:
        headers[1] = _IO_STUB
    uses_map = uses_graphics or any(n.kind == 'map' for n in walk_nodes(modules))
    # 宿主 ABI（graphics_abi.h）声明的外部符号是宿主编译单元的链接根：
    # 生成的程序自身不调用 post_*，但 SDL/record 宿主会链接它们，
    # 剪枝时必须按存活根保留（否则宿主 undefined reference）。
    if uses_graphics and isinstance(generated, str):
        abi_names = ' '.join(sorted(set(re.findall(r'\bru_graphics_\w+',
            (directory / 'graphics_abi.h').read_text(encoding='utf-8')))))
        generated += '\n/* RU_GRAPHICS_HOST_ABI_ROOTS */\n' + abi_names
    if uses_audio and isinstance(generated, str):
        generated += '\n/* RU_AUDIO_HOST_ABI_ROOTS */\nru_audio_set_host' 
    source = _MAP_REGION.sub(lambda m: m[1] if uses_map else '', '\n'.join(headers))
    source = specialize_members(source, member_names(modules))
    # Binary operators are statically spelled too (含 can also be a member).
    source = source.replace('/* RU_OPERATORS:', '/* RU_MEMBERS:')
    source = specialize_members(source, strings | member_names(modules))
    # First compute a conservative closure with the general implementations.
    user_class = uses_io or any(n.kind == 'type' for n in walk_nodes(modules))
    # Class lookup can be removed before closure: runtime-only classes expose no
    # public fields or source-defined methods. Keep it for every user class.
    source = _FEATURE.sub(lambda m: (m[2] if user_class else m[3])
                          if m[1] == 'user_class' else (m[2] if uses_map else m[3])
                          if m[1] == 'map' else m[0], source)
    general = _FEATURE.sub(lambda m: m[2], source)
    preliminary = prune_functions(general, generated)
    definitions = {m[1] for m in _FUNCTION.finditer(mask_noncode(preliminary))}
    panic = native_plan is not None or any(n.kind in ('panic', 'try') for n in walk_nodes(modules))
    features = {'type_detail': user_class or 'v_array' in definitions,
                'callable': 'ru_enter' in definitions,
                'panic': panic,
                'panic_state': panic or bool({'ru_contest_sort', 'v_array_sort', 'v_array_transform', 'v_array_each', 'v_equal', 'ru_object_equal', 'ru_map_find', 'ru_map_each'} & definitions),
                'array': 'v_array' in definitions,
                'map': 'v_map_new' in definitions,
                'pair': 'v_pair' in definitions,
                'container': bool({'v_pair', 'v_array', 'v_map_new'} & definitions)}
    source = _FEATURE.sub(lambda m: m[2] if features[m[1]] else m[3], source)
    return prune_functions(source, generated)
