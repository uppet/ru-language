"""Direct AST-to-C99 lowering with a tracing, explicitly rooted value runtime.

Every expression emits native C statements and yields one owned temporary.
Arguments are evaluated left-to-right before C calls; container edges are traced,
not reference-counted. Module source is resolved and compiled at build time.
"""
from pathlib import Path
from . import __version__
from .frontend import Node, RuError, bind_arguments, validate


def cstr(value):
    out = []
    for byte in value.encode('utf-8'):
        out.append(chr(byte) if 32 <= byte <= 126 and byte not in (34, 92) else f'\\{byte:03o}')
    return '"' + ''.join(out) + '"'


class Compiler:
    def __init__(self, program, source_name='<源码>', modules=None):
        from .modules import import_nodes, load_module_graph
        if modules is None and any(import_nodes(program)):
            modules = load_module_graph(source_name, program)
        self.source_name = str(source_name)
        self.root = str(Path(source_name).resolve()) if modules else self.source_name
        self.source_texts = getattr(modules, 'sources', {})
        self.modules = dict(modules or {self.root: program})
        self.modules[self.root] = program
        self.program = program
        self.counter = 0
        self.lines = []
        self.indent = 0
        self.live_temps = []
        self.handlers = []
        self.rescue_envs = []
        self.loop_scopes = []
        self.module_ids = {path: f'ru_module_{i}' for i, path in enumerate(self.modules)}
        self.declarations = {}
        self.function_ids = {}
        self.type_ids = {}
        self.exports = {}
        for path, body in self.modules.items():
            validate(body)
            self.declarations[path] = {n.data['name']: n for n in body if n.kind in ('function', 'type')}
            for n in body:
                if n.kind == 'function':
                    self.function_ids[id(n)] = self.new('function')
                elif n.kind == 'type':
                    self.type_ids[id(n)] = self.new('class')
                    for method in n.data['methods']:
                        self.function_ids[id(method)] = self.new('method')
        for path in self.modules:
            self._exports(path)
        self._validate_parameters()
        self._validate_classes()
        entry = self.declarations[self.root].get('元初')
        if entry:
            if entry.kind != 'function' or entry.data['procedure'] or len(entry.data['params']) != 1 or entry.data['params'][0][1] != '句 阵':
                self.error(entry, '元初必须为恰有一个「句 阵」参数的算')
        self.entry = entry
        self.current_path = self.root
        self.functions = self._functions(self.root)

    def _exports(self, path):
        if path in self.exports:
            return self.exports[path]
        result = dict(self.declarations[path])
        self.exports[path] = result
        for n in self.modules[path]:
            if n.kind == 'bind':
                previous = result.get(n.data['name'])
                if previous and previous.kind in ('function', 'type'):
                    self.error(n, '变量名不能与函数名或形名重名')
                result[n.data['name']] = n
            elif n.kind == 'import_all':
                other = self._exports(n.data['expr'].data['resolved'])
                overlap = result.keys() & other.keys()
                if overlap:
                    self.error(n, '尽取名称冲突：' + '、'.join(sorted(overlap)))
                result.update(other)
        return result

    def _functions(self, path):
        return {name: n for name, n in self.exports[path].items() if n.kind == 'function'}

    def _validate_parameters(self):
        # Imported declarations become protected names only after exports are
        # resolved. Check the owner's scope, not the scope of its importers;
        # ordinary bindings (including type aliases) remain shadowable.
        for path, declarations in self.declarations.items():
            protected = {name for name, n in self.exports[path].items()
                         if n.kind in ('function', 'type')}
            for declaration in declarations.values():
                functions = ([declaration] if declaration.kind == 'function'
                             else declaration.data['methods'])
                for function in functions:
                    if any(name in protected for name, _ in function.data['params']):
                        self.error(function, '参数名不能与函数名、形名或内置名称重名')

    def _validate_classes(self):
        self.parents = {}
        owners = {id(n): path for path, names in self.declarations.items() for n in names.values() if n.kind == 'type'}
        def check(n, active=()):
            if id(n) in active:
                self.error(n, '形的继承形成循环')
            if id(n) in self.parents:
                return
            path = owners[id(n)]
            parent = self.exports[path].get(n.data['parent']) if n.data['parent'] else None
            if n.data['parent'] and (parent is None or parent.kind != 'type'):
                self.error(n, '未定义父形：' + n.data['parent'])
            if parent:
                check(parent, active + (id(n),))
                ancestors = {}
                ancestor = parent
                while ancestor:
                    ancestors.update({key: ('field', typ) for key, typ in ancestor.data['fields']})
                    ancestors.update({m.data['name']: ('method', m) for m in ancestor.data['methods']})
                    ancestor = self.parents[id(ancestor)]
                for key, _ in n.data['fields']:
                    if key in ancestors:
                        self.error(n, '继承的字段／方法名称冲突：' + key)
                for method in n.data['methods']:
                    prior = ancestors.get(method.data['name'])
                    if prior and (prior[0] != 'method' or prior[1].data['params'] != method.data['params'] or prior[1].data['procedure'] != method.data['procedure']):
                        self.error(method, '覆盖方法必须保持参数名称、类型和算／作种类')
            self.parents[id(n)] = parent
        for names in self.declarations.values():
            for n in names.values():
                if n.kind == 'type':
                    check(n)

    def line(self, text):
        self.lines.append('    ' * self.indent + text)

    def new(self, prefix='v'):
        self.counter += 1
        return f'ru_{prefix}_{self.counter}'

    def temp(self, expression, can_panic=False):
        name = self.new()
        self.line(f'Val {name} = {expression};')
        self.live_temps.append(name)
        if can_panic:
            self.line('if (ru_panicking) {')
            self.indent += 1
            self.panic_transfer()
            self.indent -= 1
            self.line('}')
        return name

    def drop(self, *names):
        for name in names:
            self.line(f'v_drop({name});')
            self.live_temps.remove(name)

    def panic_context(self, env_name):
        self.live_temps, self.handlers, self.rescue_envs, self.loop_scopes = [], [], [], []
        self.base_env = env_name
        self.panic_exit = self.new('panic_exit')
        self.line(f'if (0) goto {self.panic_exit};')

    def clean_scopes(self, depth=0):
        for env_name in reversed(self.rescue_envs[depth:]):
            self.line(f'env_free(&{env_name});')

    def panic_transfer(self):
        # Explicit propagation, rather than longjmp, leaves every runtime call
        # normally. Its argument scratch and call-depth accounting are always
        # restored. Drop every live caller temporary before entering a rescue.
        for name in reversed(self.live_temps):
            self.line(f'v_drop({name});')
        target, depth = self.handlers[-1] if self.handlers else (self.panic_exit, 0)
        self.clean_scopes(depth)
        self.line(f'goto {target};')

    def error(self, n, text):
        error = RuError(text, n.token.line, n.token.col, '编译错误')
        # Validation also runs before code generation selects current_path.
        # Locate the actual AST owner rather than borrowing the root filename
        # for diagnostics arising in an imported function or type definition.
        for path, program in self.modules.items():
            pending = list(program)
            while pending:
                value = pending.pop()
                if value is n:
                    error.source_name = path
                    error.source_text = self.source_texts.get(path, '')
                    raise error
                if isinstance(value, Node):
                    pending.extend(value.data.values())
                elif isinstance(value, dict):
                    pending.extend(value.values())
                elif isinstance(value, (list, tuple)):
                    pending.extend(value)
        raise error

    def argument_values(self, args):
        values = [self.expr(expr) for _, expr in args]
        if not values:
            return '0, NULL, NULL', values
        array, keys = self.new('args'), self.new('keys')
        self.line(f'Val {array}[] = {{{", ".join(values)}}};')
        self.line(f'const char *{keys}[] = {{{", ".join("NULL" if key is None else cstr(key) for key, _ in args)}}};')
        return f'{len(values)}, {keys}, {array}', values

    def expr(self, n):
        d, ln = n.data, n.token.line
        if n.kind == 'number':
            return self.temp(f"v_num({d['value'].hex()})")
        if n.kind == 'string':
            return self.temp(f"v_str({cstr(d['value'])})")
        if n.kind == 'null':
            return self.temp('v_null()')
        if n.kind == 'self':
            return self.temp('v_copy(self)')
        if n.kind == 'name':
            if d['name'] in self.functions or d['name'] == '读':
                return self.call(n, d['name'], [])
            return self.temp(f"env_get(env, {cstr(d['name'])}, {ln})")
        if n.kind == 'call':
            return self.call(n, d['name'], d['args'])
        if n.kind == 'array':
            values = [self.expr(item) for item in d['items']]
            args = self.new('items')
            if values:
                self.line(f'Val {args}[] = {{{", ".join(values)}}};')
            out = self.temp(f'v_array({len(values)}, {args if values else "NULL"}, {ln})')
            self.drop(*values)
            return out
        if n.kind == 'convert':
            arg = self.expr(d['expr'])
            target = {'数': 'RU_NUM', '句': 'RU_STR', '阵': 'RU_ARRAY'}[d['target']]
            out = self.temp(f'v_convert({arg}, {target}, {ln})')
            self.drop(arg)
            return out
        if n.kind == 'unary':
            arg = self.expr(d['expr'])
            out = self.temp(f"v_unary({cstr(d['op'])}, {arg}, {ln})")
            self.drop(arg)
            return out
        if n.kind == 'binary':
            left = self.expr(d['left'])
            if d['op'] in ('且', '或'):
                flag = self.new('truth')
                self.line(f'int {flag} = v_truth({left});')
                self.drop(left)
                out = self.temp(f'v_num({flag})')
                self.line(f'if ({"" if d["op"] == "且" else "!"}{flag}) {{')
                self.indent += 1
                right = self.expr(d['right'])
                self.line(f'{out} = v_num(v_truth({right}));')
                self.drop(right)
                self.indent -= 1
                self.line('}')
                return out
            right = self.expr(d['right'])
            if d['op'] == '含':
                out = self.temp(f'v_member({left}, "含", 1, (const char *[]){{NULL}}, (Val[]){{{right}}}, {ln})', can_panic=True)
            else:
                out = self.temp(f"v_binary({cstr(d['op'])}, {left}, {right}, {ln})")
            self.drop(left, right)
            return out
        if n.kind == 'member':
            receiver = self.expr(d['receiver'])
            args, values = self.argument_values(d['args'])
            out = self.temp(f"v_member({receiver}, {cstr(d['name'])}, {args}, {ln})", can_panic=True)
            self.drop(receiver, *values)
            return out
        if n.kind in ('index', 'slice'):
            receiver = self.expr(d['receiver'])
            if n.kind == 'index':
                index = self.expr(d['index'])
                out = self.temp(f'v_index({receiver}, {index}, {ln})')
                self.drop(receiver, index)
            else:
                start = self.expr(d['start']) if d['start'] else self.temp('v_null()')
                end = self.expr(d['end']) if d['end'] else self.temp('v_null()')
                out = self.temp(f'v_slice({receiver}, {start}, {end}, {ln})')
                self.drop(receiver, start, end)
            return out
        if n.kind == 'new':
            klass = self.temp(f"env_get(env, {cstr(d['name'])}, {ln})")
            args, values = self.argument_values(d['args'])
            out = self.temp(f'v_new({klass}, {args}, {ln})')
            self.drop(klass, *values)
            return out
        if n.kind == 'import':
            return self.temp(f"{self.module_ids[d['resolved']]}_init()", can_panic=True)
        raise AssertionError(n.kind)

    def call(self, n, name, args):
        if name != '读' and name not in self.functions:
            self.error(n, f'未定义函数：{name}')
        params = ['提示'] if name == '读' else [p[0] for p in self.functions[name].data['params']]
        bind_arguments(name, args, params, lambda message: self.error(n, message), optional=name == '读')
        if name == '读':
            values = [self.expr(expr) for _, expr in args]
            prompt = values[0] if values else self.temp('v_str("")')
            out = self.temp(f'read_input({prompt}, {n.token.line})')
            self.drop(prompt)
            return out
        function = self.temp(f'env_get(env, {cstr(name)}, {n.token.line})')
        actuals, values = self.argument_values(args)
        out = self.temp(f'v_call({function}, {actuals}, {n.token.line})', can_panic=True)
        self.drop(function, *values)
        return out

    def block(self, statements, function=False):
        for n in statements:
            d, ln = n.data, n.token.line
            if n.kind == 'function':
                continue
            if n.kind == 'type':
                self.line(f'ru_class_ready(&{self.type_ids[id(n)]}, {ln});')
                continue
            self.line(f'/* 如 source line {ln}: {n.kind} */')
            if n.kind in ('bind', 'print', 'expr', 'return', 'import_all'):
                value = self.expr(d['expr'])
                if n.kind == 'bind':
                    self.line(f"env_bind(env, {cstr(d['name'])}, {value}, {ln});")
                elif n.kind == 'print':
                    self.line(f'v_print({value}, {ln});')
                elif n.kind == 'import_all':
                    self.line(f'env_import_all(env, {value}, {ln});')
                elif n.kind == 'return':
                    self.clean_scopes()
                    self.line(f'env_free({self.base_env});')
                    self.line('ru_source = previous_source;')
                    self.line(f'return {value};')
                    self.live_temps.remove(value)
                    continue
                self.drop(value)
            elif n.kind == 'assign':
                target = d['target']
                td = target.data
                receiver = self.expr(td['receiver'])
                index = self.expr(td['index']) if target.kind == 'index' else None
                if target.kind == 'member' and td['name'] == '位':
                    params = ['位']
                    bound = bind_arguments('位', td['args'], params, lambda message: self.error(target, message))
                    index = self.expr(bound['位'])
                if index:
                    self.line(f'v_check_index_target({receiver}, {index}, {ln});')
                else:
                    self.line(f"v_check_member_target({receiver}, {cstr(td['name'])}, {ln});")
                value = self.expr(d['expr'])
                if index:
                    self.line(f'v_set_index({receiver}, {index}, {value}, {ln});')
                else:
                    self.line(f"v_set_member({receiver}, {cstr(td['name'])}, {value}, {ln});")
                self.drop(receiver, value, *([index] if index else []))
            elif n.kind == 'panic':
                value = self.expr(d['expr'])
                self.line(f'ru_panic_raise({value}, {ln}, {n.token.col});')
                self.panic_transfer()
                self.live_temps.remove(value)
            elif n.kind == 'try':
                rescued, finished, rescue_env = self.new('rescue'), self.new('end_try'), self.new('rescue_env')
                self.line('{')
                self.indent += 1
                self.line(f'if (0) goto {rescued};')
                self.handlers.append((rescued, len(self.rescue_envs)))
                self.block(d['body'], function)
                self.handlers.pop()
                self.line(f'goto {finished};')
                self.line(f'{rescued}: {{')
                self.indent += 1
                self.line(f'Env {rescue_env}; env_init(&{rescue_env}, env);')
                self.line('{')
                self.indent += 1
                self.line(f'Env *env = &{rescue_env};')
                self.line(f'env_bind(env, {cstr(d["reason"])}, ru_panic_reason, {ln});')
                self.line('ru_panic_clear();')
                self.rescue_envs.append(rescue_env)
                self.block(d['rescue'], function)
                self.rescue_envs.pop()
                self.line(f'env_free(&{rescue_env});')
                self.indent -= 1
                self.line('}')
                self.indent -= 1
                self.line('}')
                self.line(f'{finished}: ;')
                self.indent -= 1
                self.line('}')
            elif n.kind == 'break':
                self.clean_scopes(self.loop_scopes[-1])
                self.line('break;')
            elif n.kind == 'if':
                value = self.expr(d['condition'])
                flag = self.new('condition')
                self.line(f'int {flag} = v_truth({value});')
                self.drop(value)
                self.line(f'if ({flag}) {{')
                self.indent += 1
                self.block(d['yes'], function)
                self.indent -= 1
                self.line('} else {')
                self.indent += 1
                self.block(d['no'], function)
                self.indent -= 1
                self.line('}')
            elif n.kind == 'loop':
                if d['count'] is None:
                    self.line('for (;;) {')
                else:
                    value = self.expr(d['count'])
                    count, counter = self.new('count'), self.new('index')
                    self.line(f'uint64_t {count} = v_count({value}, {ln});')
                    self.drop(value)
                    self.line(f'for (uint64_t {counter} = 0; {counter} < {count}; ++{counter}) {{')
                self.indent += 1
                self.loop_scopes.append(len(self.rescue_envs))
                self.block(d['body'], function)
                self.loop_scopes.pop()
                self.indent -= 1
                self.line('}')
            else:
                raise AssertionError(n.kind)

    def emit_function(self, path, fn):
        ident = self.function_ids[id(fn)]
        self.current_path, self.functions = path, self._functions(path)
        self.line(f'static Val {ident}(Env *global, Val self, int call_line, Val *args) {{')
        self.indent += 1
        self.line(f'const char *previous_source = ru_source; ru_source = {cstr(path)};')
        self.line('(void) self; (void) args; (void) call_line;')
        self.line('Env local; env_init(&local, global); Env *env = &local;')
        self.panic_context('&local')
        for i, (key, _) in enumerate(fn.data['params']):
            self.line(f'env_set(env, {cstr(key)}, args[{i}]);')
        self.block(fn.data['body'], True)
        self.line('env_free(env);')
        if not fn.data['procedure']:
            self.line(f"ru_fail(call_line, {cstr('函数「' + fn.data['name'] + '」没有执行「得」')});")
        self.line('ru_source = previous_source;')
        self.line('return v_str("");')
        self.line(f'{self.panic_exit}: env_free(&local); ru_source = previous_source; return v_null();')
        self.indent -= 1
        self.line('}')

    def string_array(self, name, strings):
        if not strings:
            return 'NULL'
        self.line(f'static const char *{name}[] = {{{", ".join(cstr(s) for s in strings)}}};')
        return name

    def compile(self):
        runtime = Path(__file__).with_name('runtime.h').read_text(encoding='utf-8')
        self.line(f'/* Generated by ru {__version__}. Standalone C99; source AST is not embedded. */')
        self.line(runtime)
        self.line(Path(__file__).with_name('io_runtime.h').read_text(encoding='utf-8'))
        for path, ident in self.module_ids.items():
            self.line(f'static Env {ident}_env; static int {ident}_state; static RuModuleFailure {ident}_failure;')
            self.line(f'static Val {ident}_init(void);')
        for names in self.declarations.values():
            for fn in names.values():
                nodes = [fn] if fn.kind == 'function' else fn.data['methods']
                for n in nodes:
                    ident = self.function_ids[id(n)]
                    self.line(f'static Val {ident}(Env *, Val, int, Val *);')
                    keys = self.string_array(ident + '_names', [p[0] for p in n.data['params']])
                    types = self.string_array(ident + '_types', [p[1] for p in n.data['params']])
                    self.line(f'static RuFunction {ident}_descriptor = {{{cstr(n.data["name"])}, {len(n.data["params"])}, {keys}, {types}, {ident}}};')
                if fn.kind == 'type':
                    self.line(f'static RuClass {self.type_ids[id(fn)]};')
        for path, names in self.declarations.items():
            for n in names.values():
                if n.kind != 'type':
                    continue
                ident = self.type_ids[id(n)]
                keys = self.string_array(ident + '_names', [p[0] for p in n.data['fields']])
                types = self.string_array(ident + '_types', [p[1] for p in n.data['fields']])
                methods = 'NULL'
                if n.data['methods']:
                    methods = ident + '_methods'
                    self.line(f'static RuFunction *{methods}[] = {{{", ".join("&" + self.function_ids[id(m)] + "_descriptor" for m in n.data["methods"])}}};')
                parent = self.parents[id(n)]
                parent_ref = '&' + self.type_ids[id(parent)] if parent else 'NULL'
                self.line(f'static RuClass {ident} = {{{cstr(n.data["name"])}, {parent_ref}, &{self.module_ids[path]}_env, {len(n.data["fields"])}, {keys}, {types}, {len(n.data["methods"])}, {methods}}};')
        for path, names in self.declarations.items():
            for n in names.values():
                for fn in [n] if n.kind == 'function' else n.data['methods']:
                    self.emit_function(path, fn)
        for path, program in self.modules.items():
            ident = self.module_ids[path]
            self.current_path, self.functions = path, self._functions(path)
            self.line(f'static Val {ident}_init(void) {{')
            self.indent += 1
            self.line(f'if ({ident}_state == 2) return v_module(&{ident}_env);')
            self.line(f'if ({ident}_state == 3) return ru_module_failure_raise(&{ident}_failure);')
            self.line(f'if ({ident}_state == 1) ru_fail(1, "循环外言");')
            self.line(f'{ident}_state = 1;')
            self.line(f'const char *previous_source = ru_source; ru_source = {cstr(path)};')
            self.line(f'Env *global = &{ident}_env; Env *env = global; env_init(env, ru_io_builtins());')
            self.panic_context(f'&{ident}_env')
            for n in program:
                if n.kind == 'function':
                    value = self.temp(f'v_function(&{self.function_ids[id(n)]}_descriptor, global, v_null())')
                    self.line(f'env_declare(env, {cstr(n.data["name"])}, {value});')
                    self.drop(value)
                elif n.kind == 'type':
                    self.line(f'env_declare(env, {cstr(n.data["name"])}, v_class(&{self.type_ids[id(n)]}));')
            self.block(program)
            self.line(f'{ident}_state = 2; ru_source = previous_source; return v_module(env);')
            self.line(f'{self.panic_exit}: ru_module_failure_save(&{ident}_failure); {ident}_state = 3; ru_source = previous_source; return v_null();')
            self.indent -= 1
            self.line('}')
        self.line('int main(int argc, char **argv) {')
        self.indent += 1
        self.line(f'ru_source = {cstr(self.source_name)}; ru_init();')
        self.line(f'Val root = {self.module_ids[self.root]}_init(); (void) root; (void) argc; (void) argv;')
        self.line('if (ru_panicking) return ru_panic_uncaught();')
        self.line('int status = 0;')
        if self.entry:
            self.line('Val arguments = v_array(0, NULL, 0);')
            self.line('for (int i = 1; i < argc; ++i) { Val arg = v_str(argv[i]); Val added = v_append(arguments, arg, 0); v_drop(added); v_drop(arg); }')
            self.line('Val entry = env_get(root.module, "元初", 1); const char *keys[] = {NULL};')
            self.line('Val result = v_call(entry, 1, keys, &arguments, 1);')
            self.line('if (ru_panicking) { v_drop(result); v_drop(entry); v_drop(arguments); return ru_panic_uncaught(); }')
            self.line('if (result.kind != RU_NUM || result.n < 0 || result.n > 255 || floor(result.n) != result.n) ru_fail(1, "元初须返回 0 至 255 的整数");')
            self.line('status = (int) result.n; v_drop(result); v_drop(entry); v_drop(arguments);')
        self.line('ru_shutdown(); return status;')
        self.indent -= 1
        self.line('}')
        return '\n'.join(self.lines) + '\n'
