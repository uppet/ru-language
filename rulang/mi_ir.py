"""Internal checked dense-compute IR. No public syntax or native ABI promise.

All names and signatures are data. The accepted operations are an effect
allowlist: no calls, allocation, boxing, mutation of views, or view escape.
"""
from .native_c import C_TYPES

LIMITS = {'u8': 255, 'u32': 4294967295}
SCALARS = frozenset(LIMITS)
VIEW = 'borrow_ro_u8'
UTF8 = 'borrow_ro_utf8'  # Manifest boundary only; lowered to VIEW inside kernels.
EFFECTS = ['borrow-read', 'no-escape', 'no-callback', 'no-gc', 'may-fail']


def validate(ir):
    required = {'version', 'params', 'result', 'locals', 'body', 'effects'}
    if not isinstance(ir, dict) or set(ir) != required or ir['version'] != 2:
        raise ValueError('密实验 IR 版本／字段不支持')
    if ir['result'] not in SCALARS or ir['effects'] != EFFECTS:
        raise ValueError('密实验返回类型／效果合同不支持')
    params, local_types = ir['params'], ir['locals']
    if not isinstance(params, dict) or not isinstance(local_types, dict):
        raise ValueError('密实验参数／局部表无效')
    if sum(t == VIEW for t in params.values()) > 1:
        raise ValueError('密实验当前仅支持一个只读视图；不默许多借用别名')
    if params.keys() & local_types.keys():
        raise ValueError('密实验参数与局部变量重名')
    env = {**params, **local_types}
    if any(not isinstance(n, str) or not n for n in env):
        raise ValueError('密实验名称无效')
    if any(t not in SCALARS | {VIEW} for t in params.values()) or any(t not in SCALARS for t in local_types.values()):
        raise ValueError('密实验类型不支持／借用不得保存')

    def expr(e, assigned):
        if not isinstance(e, list) or not e:
            raise ValueError('密实验非法表达式')
        op, *a = e
        if op == 'at' and len(a) == 3 and all(type(x) is int and 1 <= x <= 4294967295 for x in a[:2]):
            return expr(a[2], assigned)
        if op == 'const' and len(a) == 2:
            t, v = a
            if t == 'fact' and type(v) is bool: return t
            if t not in SCALARS or type(v) is not int or not 0 <= v <= LIMITS[t]:
                raise ValueError('上下文常量超出类型范围')
            return t
        if op == 'var' and len(a) == 1 and a[0] in assigned:
            return env[a[0]]
        if op == 'length' and len(a) == 1 and expr(a[0], assigned) == VIEW:
            return 'u32'
        if op == 'load' and len(a) == 2 and expr(a[0], assigned) == VIEW and expr(a[1], assigned) == 'u32':
            return 'u8'
        if op in ('add', 'sub', 'eq', 'ne', 'lt', 'le', 'gt', 'ge') and len(a) == 2:
            l, r = (expr(x, assigned) for x in a)
            if l != r or l not in SCALARS: raise ValueError('密实验运算类型不匹配')
            return l if op in ('add', 'sub') else 'fact'
        if op in ('and', 'or') and len(a) == 2 and all(expr(x, assigned) == 'fact' for x in a): return 'fact'
        if op == 'not' and len(a) == 1 and expr(a[0], assigned) == 'fact': return 'fact'
        if op == 'truth' and len(a) == 1 and expr(a[0], assigned) in SCALARS | {'fact'}: return 'fact'
        raise ValueError('密实验不支持的表达式／未初始化值／借用逃逸')

    def body(stmts, assigned, in_loop=False):
        assigned = set(assigned)
        for s in stmts:
            if not isinstance(s, list) or not s: raise ValueError('密实验非法语句')
            op, *a = s
            if op == 'set' and len(a) == 2 and a[0] in local_types:
                if expr(a[1], assigned) != env[a[0]]: raise ValueError('密实验局部类型改变')
                assigned.add(a[0])
            elif op == 'if' and len(a) == 3 and expr(a[0], assigned) == 'fact':
                yes = body(a[1], assigned, in_loop); no = body(a[2], assigned, in_loop)
                assigned |= yes & no
            elif op == 'repeat' and len(a) == 2 and expr(a[0], assigned) == 'u32':
                body(a[1], assigned, True)
            elif op == 'break' and not a and in_loop: pass
            elif op == 'return' and len(a) == 1 and expr(a[0], assigned) == ir['result']: pass
            else: raise ValueError('密实验不支持的语句／效果／借用逃逸')
        return assigned
    body(ir['body'], set(params))
    if not ir['body'] or ir['body'][-1][0] != 'return':
        raise ValueError('密实验要求末尾明确返回标量')
    return env


C_HEADER = '''#include <stdint.h>
#include <stddef.h>
enum { RU_MI_OK, RU_MI_BOUNDS, RU_MI_OVERFLOW };
typedef struct { const uint8_t *data; uint32_t length; } RuMiView;
typedef struct { int status; uint32_t value, line, col; } RuMiResult;
'''


def lower(ir, target, symbol='ru_mi_kernel'):
    """Emit a complete function, including signature, from validated typed IR."""
    if target not in ('c', 'js'): raise ValueError('未知密后端')
    if not symbol.isascii() or not symbol.isidentifier(): raise ValueError('非法生成符号')
    env = validate(ir)
    names = {n: f'p{i}' for i, n in enumerate(ir['params'])}
    names.update({n: f'l{i}' for i, n in enumerate(ir['locals'])})
    lines, serial = [], 0
    def emit(text, depth): lines.append('    ' * depth + text)
    def temp():
        nonlocal serial
        serial += 1
        return f't{serial}'
    def typ(t): return 'RuMiView' if t == VIEW else 'int' if t == 'fact' else C_TYPES[t]
    def fail(status, location):
        line, col = location
        return f'return (RuMiResult){{RU_MI_{status}, 0, {line}, {col}}};' if target == 'c' else f'return {{status: RU_MI_{status}, value: 0, line: {line}, col: {col}}};'
    def declare(t, name, value, depth):
        emit(f'{typ(t) if target == "c" else "let"} {name} = {value};', depth)
    def expr(e, depth, location=(0, 0)):
        op, *a = e
        if op == 'at': return expr(a[2], depth, (a[0], a[1]))
        if op == 'const':
            t, value = a
            if t == 'fact': return ('1' if value else '0') if target == 'c' else ('true' if value else 'false'), t
            return str(value) + ('u' if target == 'c' else ''), t
        if op == 'var': return names[a[0]], env[a[0]]
        if op == 'length':
            v, _ = expr(a[0], depth); return f'{v}.length', 'u32'
        if op == 'load':
            v, _ = expr(a[0], depth); i, _ = expr(a[1], depth)
            emit(f'if ({i} >= {v}.length) {{ {fail("BOUNDS", location)} }}', depth)
            n = temp(); declare('u8', n, f'{v}.data[{i}]' if target == 'c' else f'{v}[{i}]', depth)
            return n, 'u8'
        if op in ('truth', 'not'):
            v, t = expr(a[0], depth)
            if t != 'fact':
                # Evaluate checked operands even though all Ru numbers are true.
                emit(f'(void)({v});' if target == 'c' else f'void ({v});', depth)
                v = '1' if target == 'c' else 'true'
            return (f'(!{v})' if op == 'not' else v), 'fact'
        x, t = expr(a[0], depth)
        if op in ('and', 'or'):
            n = temp(); declare('fact', n, x, depth)
            emit(f'if ({n if op == "and" else "!" + n}) {{', depth)
            y, _ = expr(a[1], depth + 1); emit(f'{n} = {y};', depth + 1); emit('}', depth)
            return n, 'fact'
        y, _ = expr(a[1], depth)
        if op in ('add', 'sub'):
            n = temp(); condition = f'{y} > {LIMITS[t]}u - {x}' if op == 'add' else f'{x} < {y}'
            if target == 'js': condition = condition.replace('u -', ' -')
            emit(f'if ({condition}) {{ {fail("OVERFLOW", location)} }}', depth)
            declare(t, n, f'{x} {"+" if op == "add" else "-"} {y}', depth)
            return n, t
        return f'({x} ' + {'eq':'==', 'ne':'!=', 'lt':'<', 'le':'<=', 'gt':'>', 'ge':'>='}[op] + f' {y})', 'fact'
    def body(stmts, depth):
        for op, *a in stmts:
            if op == 'set':
                v, _ = expr(a[1], depth); emit(f'{names[a[0]]} = {v};', depth)
            elif op == 'if':
                v, _ = expr(a[0], depth); emit(f'if ({v}) {{', depth); body(a[1], depth + 1)
                if a[2]: emit('} else {', depth); body(a[2], depth + 1)
                emit('}', depth)
            elif op == 'repeat':
                count, _ = expr(a[0], depth)
                limit, index = temp(), temp()
                declare('u32', limit, count, depth)
                emit(f'for ({"uint32_t" if target == "c" else "let"} {index} = 0; {index} < {limit}; ++{index}) {{', depth)
                body(a[1], depth + 1); emit('}', depth)
            elif op == 'break': emit('break;', depth)
            elif op == 'return':
                v, _ = expr(a[0], depth)
                emit(f'return (RuMiResult){{RU_MI_OK, {v}, 0, 0}};' if target == 'c' else f'return {{status: RU_MI_OK, value: {v}, line: 0, col: 0}};', depth)
    params = ', '.join(f'{typ(t)} {names[n]}' if target == 'c' else names[n] for n, t in ir['params'].items())
    emit(f'static RuMiResult {symbol}({params or "void"}) {{' if target == 'c' else f'function {symbol}({params}) {{', 0)
    for n in ir['params']:
        if target == 'c': emit(f'(void){names[n]};', 1)
    for n, t in ir['locals'].items():
        emit(f'{typ(t) if target == "c" else "let"} {names[n]} = 0;', 1)
        if target == 'c': emit(f'(void){names[n]};', 1)
    body(ir['body'], 1); emit('}', 0)
    return '\n'.join(lines)
