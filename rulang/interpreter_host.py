"""Opt-in primitive/transport bridge for the AOT-compiled Ru interpreter.

No source parsing, AST evaluation, guest environments or guest calls live here.
Ordinary AOT products do not include this bridge.
"""
from pathlib import Path


def integrate_host(runtime):
    def insert(anchor, replacement):
        nonlocal runtime
        if runtime.count(anchor) != 1:
            raise ValueError('interpreter host runtime integration anchor changed')
        runtime = runtime.replace(anchor, replacement)

    beginning = 'typedef struct { size_t count; Val values[]; } RuLLVMFrame;'
    ending = 'void rul_copy(void *out, void *value)'
    if runtime.count(beginning) != 1 or runtime.count(ending) != 1:
        raise ValueError('interpreter LLVM frame integration anchor changed')
    first, last = runtime.index(beginning), runtime.index(ending)
    runtime = (runtime[:first] + Path(__file__).with_name('interpreter_frames.h').read_text(encoding='utf-8')+
               '\n'+runtime[last:])

    insert('static Env *ru_contest_builtins(void)',
           Path(__file__).with_name('interpreter_host.h').read_text(encoding='utf-8') +
           '\nstatic Env *ru_contest_builtins(void)')
    insert('env_declare(&env, "__如竞", service); v_drop(service);',
           'env_declare(&env, "__如竞", service); v_drop(service);\n'
           '    ru_interpreter_install(&env);')
    insert('static void ru_shutdown(void);',
           'static void ru_interpreter_literals_clear(void);\n'
           'static void ru_interpreter_frames_reset(void);\nstatic void ru_shutdown(void);')
    insert('while(ru_scratch) ru_scratch_free(ru_scratch->data);',
           'ru_interpreter_frames_reset();\n    while(ru_scratch) ru_scratch_free(ru_scratch->data);\n'
           '    ru_interpreter_literals_clear();')
    # The interpreter adds host frames around guest calls. Its own recoverable
    # depth check fires well before this last-resort native bound.
    insert('if(ru_call_depth>=128)', 'if(ru_call_depth>=1024)')
    insert('void rul_string(void *out, const char *value) { rul_put(out, v_str(value)); }',
           'void rul_string(void *out, const char *value) { rul_put(out, ru_interpreter_literal(value)); }')
    insert('ru_enter(line);result=fn->code',
           'if(ru_call_depth>=500) {\n'
           '        Val reason=v_str("调用或源码结构过深，请拆分为较小的步骤。");\n'
           '        ru_panic_raise(reason,line,1);v_drop(reason);ru_scratch_free(bound);return v_null();\n'
           '    }\n    ru_enter(line);result=fn->code')
    insert('static Val v_member(Val receiver,const char *name,size_t argc,const char **keys,Val *args,int line)\n{',
           'static int ru_interpreter_member(Val, const char *, size_t, const char **, Val *, int, Val *);\n'
           'static Val v_member(Val receiver,const char *name,size_t argc,const char **keys,Val *args,int line)\n{\n'
           '    Val host_result;\n'
           '    if (ru_interpreter_member(receiver,name,argc,keys,args,line,&host_result)) return host_result;')
    return ('#if defined(__clang__)\n#pragma clang diagnostic error "-Wimplicit-function-declaration"\n'
            '#pragma clang diagnostic error "-Wint-conversion"\n#endif\n'
            '#ifndef _WIN32\n#ifndef _XOPEN_SOURCE\n#define _XOPEN_SOURCE 700\n'
            '#endif\n#endif\n'+runtime)
