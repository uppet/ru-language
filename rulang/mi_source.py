"""Explicit experimental manifest -> existing Ru AST -> checked dense IR.

Not new language syntax. Unselected ASTs and ordinary source interpretation are
unchanged. C bridging is opt-in; JS output here is a compute semantic model only.
"""
import json
from pathlib import Path
import re
from .frontend import RuError
from .mi_ir import EFFECTS, LIMITS, SCALARS, VIEW, UTF8, C_HEADER, lower, validate


def reject(node, message, path):
    error = RuError('密实验：' + message, node.token.line, node.token.col, '编译错误')
    error.source_name = str(path)
    raise error


class SourceLowerer:
    def __init__(self, function, spec, path):
        self.function, self.spec, self.path = function, spec, path
        self.params = spec['params']
        self.env = dict(self.params)
        self.locals = {}
        self.local_hints = spec.get('locals', {})
        self.assigned = set(self.params)
        if function.data['procedure']:
            self.fail(function, '当前只支持返回标量的算')
        if list(self.params) != [p[0] for p in function.data['params']]:
            self.fail(function, '清单参数须按源码顺序逐项匹配')
        # A dynamic array annotation is not a NativeMemory type requirement.
        if any(t for _, t in function.data['params']):
            self.fail(function, '实验密算参数须省略普通动态注解，由清单指定精确类型')
        if any(t not in SCALARS for t in self.local_hints.values()):
            self.fail(function, '清单局部类型不支持')

    def fail(self, node, message): reject(node, message, self.path)

    def known_type(self, node):
        d = node.data
        if node.kind == 'name': return self.env.get(d['name'])
        if node.kind == 'index': return 'u8'
        if node.kind == 'member' and d['name'] == '量': return 'u32'
        if node.kind == 'fact': return 'fact'
        if node.kind == 'binary':
            if d['op'] in ('==', '!=', '<', '<=', '>', '>=', '且', '或'): return 'fact'
            return self.known_type(d['left']) or self.known_type(d['right'])
        return None

    def truth(self, node):
        e, t = self.expr(node, 'u32' if node.kind == 'number' else None)
        if t not in SCALARS | {'fact'}: self.fail(node, '条件不得是借用视图')
        return ['truth', e]

    def expr(self, node, expected=None):
        expression, typ = self._expr(node, expected)
        if expected is not None and typ != expected:
            self.fail(node, '表达式类型不匹配；不得改变清单／已确定的局部类型')
        return ['at', node.token.line, node.token.col, expression], typ

    def _expr(self, node, expected=None):
        d, kind = node.data, node.kind
        if kind == 'number':
            # Never use data['value']: frontend intentionally stores ordinary
            # numbers as float. Contextual dense constants use exact token text.
            raw = node.token.value
            if not re.fullmatch(r'[0-9]+', raw): self.fail(node, '当前仅支持精确十进制整数字面量')
            if expected not in SCALARS: self.fail(node, '整数字面量需要清单／运算上下文类型')
            value = int(raw)
            if value > LIMITS[expected]: self.fail(node, f'整数字面量 {raw} 超出 {expected} 范围')
            return ['const', expected, value], expected
        if kind == 'fact': return ['const', 'fact', d['value']], 'fact'
        if kind == 'name':
            name = d['name']
            if name not in self.assigned: self.fail(node, '未知或未初始化名称：' + name)
            t = self.env[name]
            if expected and t != expected: self.fail(node, '类型不匹配；不隐式缩窄或改变符号')
            return ['var', name], t
        if kind == 'index':
            receiver, rt = self.expr(d['receiver'])
            index, it = self.expr(d['index'], 'u32')
            if rt != VIEW: self.fail(node, '索引只支持清单中的只读字节视图')
            if expected and expected != 'u8': self.fail(node, '字节读取结果类型为 u8，不隐式提升')
            return ['load', receiver, index], 'u8'
        if kind == 'member' and d['name'] == '量' and not d['args']:
            receiver, rt = self.expr(d['receiver'])
            if rt != VIEW: self.fail(node, '量只支持只读字节视图')
            return ['length', receiver], 'u32'
        if kind == 'unary' and d['op'] == '非': return ['not', self.truth(d['expr'])], 'fact'
        if kind == 'binary':
            op = d['op']
            if op in ('且', '或'):
                return ['and' if op == '且' else 'or', self.truth(d['left']), self.truth(d['right'])], 'fact'
            ops = {'+': 'add', '-': 'sub', '==': 'eq', '!=': 'ne', '<': 'lt', '<=': 'le', '>': 'gt', '>=': 'ge'}
            if op not in ops: self.fail(node, '运算尚无本批合同：' + op)
            context = self.known_type(d['left']) or self.known_type(d['right']) or expected
            if context not in SCALARS: self.fail(node, '运算需要一致的显式整数类型')
            left, lt = self.expr(d['left'], context); right, rt = self.expr(d['right'], context)
            if lt != rt: self.fail(node, '运算类型不匹配')
            result = lt if op in ('+', '-') else 'fact'
            if expected and result != expected: self.fail(node, '表达式类型不匹配')
            return [ops[op], left, right], result
        self.fail(node, '不支持的 AST／效果：' + kind + '；不允许回调、分配、外部调用或视图逃逸')

    def body(self, nodes, in_loop=False):
        out = []
        for node in nodes:
            d = node.data
            if node.kind == 'bind':
                name = d['name']
                if name in self.params: self.fail(node, '本批不允许重绑定参数')
                expected = self.env.get(name) or self.local_hints.get(name)
                e, t = self.expr(d['expr'], expected)
                if t not in SCALARS: self.fail(node, '借用不可保存／装箱；局部须为整数')
                self.env[name] = self.locals[name] = t
                self.assigned.add(name); out.append(['set', name, e])
            elif node.kind == 'if':
                condition = self.truth(d['condition']); before = set(self.assigned)
                yes = self.body(d['yes'], in_loop); after_yes = set(self.assigned)
                self.assigned = set(before)
                no = self.body(d['no'], in_loop)
                self.assigned = before | (after_yes & self.assigned)
                out.append(['if', condition, yes, no])
            elif node.kind == 'loop':
                if d['count'] is None: self.fail(node, '本批仅支持有界「循 次」，不支持无界循环')
                count, ct = self.expr(d['count'], 'u32')
                if ct != 'u32': self.fail(node, '循环次数须为 u32')
                before = set(self.assigned); body = self.body(d['body'], True); self.assigned = before
                out.append(['repeat', count, body])
            elif node.kind == 'break' and in_loop: out.append(['break'])
            elif node.kind == 'return':
                e, t = self.expr(d['expr'], self.spec['result'])
                if t != self.spec['result']: self.fail(node, '返回须为精确标量；借用不得逃逸')
                out.append(['return', e])
            else: self.fail(node, '不支持的语句／效果：' + node.kind)
        return out

    def run(self):
        body = self.body(self.function.data['body'])
        if self.local_hints.keys() - self.locals.keys(): self.fail(self.function, '清单含源码未定义的局部变量')
        ir = {'version': 2, 'params': self.params, 'result': self.spec['result'], 'locals': self.locals, 'body': body, 'effects': EFFECTS}
        try: validate(ir)
        except ValueError as e: self.fail(self.function, str(e))
        return ir


def read_manifest(path):
    """Validate structural fields before the generator resolves source paths."""
    try: document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e: raise RuError('密实验清单无法读取：' + str(e), category='编译错误') from e
    if not isinstance(document, dict) or set(document) != {'version', 'functions'} or type(document['version']) is not int or document['version'] != 1 or not isinstance(document['functions'], list) or not document['functions']:
        raise RuError('密实验清单版本／字段不支持', category='编译错误')
    for spec in document['functions']:
        required = {'module', 'function', 'params', 'result', 'effects'}
        if not isinstance(spec, dict) or not required <= spec.keys() or spec.keys() - required - {'locals', 'ranges'}:
            raise RuError('密实验函数清单字段不支持', category='编译错误')
        if any(not isinstance(spec[k], str) or not spec[k] for k in ('module', 'function')):
            raise RuError('密实验模块／函数名称须为非空字符串', category='编译错误')
    return document


class MiSourcePlan:
    def __init__(self, modules, manifest):
        self.functions = {}
        self.records = []
        path = Path(manifest).resolve()
        document = read_manifest(path)
        lookup = {str(Path(p).resolve()): body for p, body in modules.items()}
        for spec in document['functions']:
            required = {'module', 'function', 'params', 'result', 'effects'}
            if not isinstance(spec, dict) or not required <= spec.keys() or spec.keys() - required - {'locals', 'ranges'}:
                raise RuError('密实验函数清单字段不支持', category='编译错误')
            if any(not isinstance(spec[k], str) or not spec[k] for k in ('module', 'function')):
                raise RuError('密实验模块／函数名称须为非空字符串', category='编译错误')
            module = str((path.parent / spec['module']).resolve())
            candidates = [n for n in lookup.get(module, []) if n.kind == 'function' and n.data['name'] == spec['function']]
            if len(candidates) != 1: raise RuError('密实验清单函数未在加载模块的顶层唯一找到：' + spec['function'], category='编译错误')
            fn = candidates[0]
            if id(fn) in self.functions: reject(fn, '重复清单绑定', module)
            if spec['effects'] != EFFECTS: reject(fn, '效果合同必须完整匹配受限只读计算子集', module)
            if (not isinstance(spec['params'], dict) or
                any(not isinstance(n, str) or not n or not isinstance(t, str) or t not in SCALARS | {VIEW, UTF8} for n, t in spec['params'].items()) or
                not isinstance(spec['result'], str) or spec['result'] not in SCALARS):
                reject(fn, '参数／结果类型无效', module)
            hints = spec.get('locals', {})
            if not isinstance(hints, dict) or any(not isinstance(n, str) or not n or not isinstance(t, str) or t not in SCALARS for n, t in hints.items()):
                reject(fn, '局部类型清单无效', module)
            if not isinstance(spec.get('ranges', []), list): reject(fn, '范围合同须为列表', module)
            for constraint in spec.get('ranges', []):
                if not isinstance(constraint, dict) or set(constraint) != {'view', 'begin', 'end'} or any(not isinstance(v, str) for v in constraint.values()) or spec['params'].get(constraint['view']) not in (VIEW, UTF8) or any(spec['params'].get(constraint[x]) != 'u32' for x in ('begin', 'end')):
                    reject(fn, '范围合同须绑定一个视图和 u32 起止参数', module)
            typed_spec = {**spec, 'params': {n: VIEW if t == UTF8 else t for n, t in spec['params'].items()}}
            ir = SourceLowerer(fn, typed_spec, module).run()
            record = {'module': module, 'function': spec['function'], 'node': fn, 'ir': ir,
                      'input_contracts': spec['params'], 'ranges': spec.get('ranges', []),
                      'symbol': f'ru_mi_kernel_{len(self.records)}'}
            self.functions[id(fn)] = record; self.records.append(record)

    def compute_source(self, target):
        if target == 'llvm':
            from .mi_llvm import lower as lower_llvm
            return '\n\n'.join(lower_llvm(r['ir'], r['symbol']) for r in self.records) + '\n'
        if target not in ('c', 'js'):
            raise ValueError('未知密后端')
        header = C_HEADER if target == 'c' else "'use strict';\nconst [RU_MI_OK, RU_MI_BOUNDS, RU_MI_OVERFLOW] = [0,1,2];\n"
        result = header + '\n' + '\n'.join(lower(r['ir'], target, r['symbol']) for r in self.records)
        if target == 'js': result += '\nmodule.exports = {' + ', '.join(r['symbol'] for r in self.records) + '};\n'
        return result

    def bridge_source(self, target='c'):
        if target == 'llvm':
            from .mi_llvm import c_adapter
            source = C_HEADER + '\n'.join(c_adapter(r['ir'], r['symbol']) for r in self.records)
        else:
            source = self.compute_source('c')
        source += '''
static uint32_t ru_mi_scalar(Val value, uint32_t limit, int line)
{
    if (value.kind != RU_NUM || !isfinite(value.n) || value.n < 0 ||
        value.n > limit || floor(value.n) != value.n)
        ru_fail(line, "密整数参数须为精确范围内的普通整数");
    return (uint32_t)value.n;
}
'''
        if any(VIEW in r['input_contracts'].values() for r in self.records):
            source += (Path(__file__).parent / 'mi_bridge.h').read_text(encoding='utf-8')
        if any(UTF8 in r['input_contracts'].values() for r in self.records):
            source += (Path(__file__).parent / 'mi_string_bridge.h').read_text(encoding='utf-8')
        return source

    def emit_wrapper(self, compiler, fn, name=None):
        record = self.functions[id(fn)]
        ir, symbol = record['ir'], record['symbol']
        params = {n: f'mi_p{i}' for i, n in enumerate(ir['params'])}
        name = name or compiler.function_ids[id(fn)]
        compiler.line(f'static Val {name}(Env *global, Val self, int call_line, Val *args) {{')
        compiler.indent += 1
        compiler.line('(void)global; (void)self; (void)args; (void)call_line;')
        view = None
        # Validate every scalar before obtaining a borrow; no lossy cast first.
        for i, (name, typ) in enumerate(ir['params'].items()):
            if typ != VIEW: compiler.line(f'uint32_t {params[name]} = ru_mi_scalar(args[{i}], {LIMITS[typ]}u, call_line);')
            else: view = (i, name)
        if view:
            i, name = view
            utf8 = record['input_contracts'][name] == UTF8
            if utf8:
                compiler.line(f'RuMiView mi_view = ru_mi_string_view(args[{i}], call_line);')
                length = 'mi_view.length'
            else:
                compiler.line(f'RuNative *mi_memory = ru_mi_memory(args[{i}], call_line);')
                length = 'mi_memory->as.memory.size'
            for constraint in record['ranges']:
                begin, end = params[constraint['begin']], params[constraint['end']]
                compiler.line(f'if ({begin} > {end} || {end} > {length}) ru_fail(call_line, "密视图起止范围越界");')
            if utf8:
                # Validate before retaining; only the checked kernel and v_drop
                # follow this retain. Even kernel failure releases before fail.
                compiler.line(f'Val mi_owner = v_copy(args[{i}]);')
                params[name] = 'mi_view'
            else:
                compiler.line(f'RuMiSourceBorrow mi_borrow = ru_mi_acquire(args[{i}], mi_memory, call_line);')
                params[name] = 'mi_borrow.view'
        compiler.line(f'RuMiResult mi_result = {symbol}({", ".join(params.values())});')
        if view: compiler.line('v_drop(mi_owner);' if utf8 else 'ru_mi_release(&mi_borrow);')
        # No allocation/throw/callback exists between acquire and release. Kernel
        # status maps into the ordinary runtime only AFTER release on all exits.
        from .compiler import cstr
        source = cstr(compiler.source_path_mapper(record['module']))
        compiler.line(f'if (mi_result.status != RU_MI_OK) {{ ru_source = {source}; ru_fail((int)mi_result.line, "密内核失败，列=%u，status=%d", mi_result.col, mi_result.status); }}')
        compiler.line('return v_num((double)mi_result.value);')
        compiler.indent -= 1; compiler.line('}')
