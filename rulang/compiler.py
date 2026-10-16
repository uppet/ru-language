"""Direct AST-to-C99 lowering with a tracing, explicitly rooted value runtime.

Every expression emits native C statements and yields one owned temporary.
Arguments are evaluated left-to-right before C calls; container edges are traced,
not reference-counted. Module source is resolved and compiled at build time.
"""
from pathlib import Path
from . import __version__
from .frontend import BUILTIN_TYPES, Node, RuError, bind_arguments, validate
from .c_runtime import ast_strings
from .diagnostics import display_text


def cstr(value):
    out = []
    for byte in value.encode('utf-8'):
        out.append(chr(byte) if 32 <= byte <= 126 and byte not in (34, 92) else f'\\{byte:03o}')
    return '"' + ''.join(out) + '"'


class Compiler:
    supports_browser_graphics = False

    def __init__(self, program, source_name='<源码>', modules=None, full_runtime=False, allow_native=False):
        self.full_runtime = full_runtime
        self.allow_native = bool(allow_native)
        from .modules import import_nodes, load_module_graph
        if modules is None and any(import_nodes(program)):
            modules = load_module_graph(source_name, program)
        from .native_runtime import _native_nodes, reject_native_backend
        self.native_enabled = bool(list(_native_nodes((program, modules))))
        if self.native_enabled and (not self.allow_native or type(self) is not Compiler):
            reject_native_backend((program, modules))
        for node in import_nodes(modules or program):
            if not self.supports_browser_graphics and (node.data.get("path") == "如:观" or Path(node.data.get("resolved", "")).resolve() == (Path(__file__).parent / "stdlib" / "如观.ru").resolve()):
                raise RuError("如观图形仅支持如书 Python 会话；C／JavaScript 编译后端尚不支持", node.token.line, node.token.col, "能力错误")
        self.source_name = str(source_name)
        self.root = str(Path(source_name).resolve()) if modules else self.source_name
        self.source_texts = getattr(modules, 'sources', {})
        self.modules = dict(modules or {self.root: program})
        self.modules[self.root] = program
        self.program = program
        self.native_plan = None
        if self.native_enabled:
            from .native_c import NativeCPlan
            self.native_plan = NativeCPlan(self.modules)
        from .c_runtime import walk_nodes
        self.can_panic = self.native_enabled or full_runtime or any(n.kind in ('panic', 'try') for n in walk_nodes(self.modules))
        self.counter = 0
        self.lines = []
        self.indent = 0
        self.live_temps = []
        self.handlers = []
        self.lexical_envs = []
        self.loop_scopes = []
        self.module_ids = {path: f'ru_module_{i}' for i, path in enumerate(self.modules)}
        self.declarations = {}
        self.function_ids = {}
        self.all_functions = []
        self.function_scopes = {}
        self.function_value_scopes = {}
        self.type_ids = {}
        self.exports = {}
        self.value_exports = {}
        for path, body in self.modules.items():
            validate(body)
            self.declarations[path] = {n.data['name']: n for n in body if n.kind in ('function', 'type')}
            self.collect_functions(path, body, [])
        for path in self.modules:
            self._exports(path)
        self._validate_parameters()
        self._validate_type_uses()
        self._validate_classes()
        entry = self.declarations[self.root].get('元初')
        if entry:
            if entry.kind != 'function' or entry.data['procedure'] or len(entry.data['params']) != 1 or entry.data['params'][0][1] != '句 阵':
                self.error(entry, '元初必须为恰有一个「句 阵」参数的算')
        self.entry = entry
        self.current_path = self.root
        self.current_function = None
        self.functions = self._functions(self.root)
        if not full_runtime:
            from .stdlib_pruning import prune_bundled_stdlib
            pruned = prune_bundled_stdlib(program, source_name, self.modules)
            if any(len(pruned[path]) != len(body) for path, body in self.modules.items()):
                # Validate the complete graph above before rebuilding its semantic
                # indexes: omitted exports must not hide declaration conflicts.
                source_texts = self.source_texts
                self.__init__(program, source_name, modules=pruned, full_runtime=True, allow_native=allow_native)
                self.source_texts = source_texts
                self.full_runtime = False
                self.can_panic = self.native_enabled or any(n.kind in ('panic', 'try') for n in walk_nodes(self.modules))

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

    @staticmethod
    def local_functions(statements):
        return {n.data['name']: n for n in statements if n.kind == 'function'}

    @staticmethod
    def scope_bindings(statements):
        names = set()
        for n in statements:
            d = n.data
            if n.kind == 'bind':
                names.add(d['name'])
            elif n.kind == 'if':
                names.update(Compiler.scope_bindings(d['yes']))
                names.update(Compiler.scope_bindings(d['no']))
            elif n.kind in ('loop', 'try'):
                names.update(Compiler.scope_bindings(d['body']))
        return names

    def collect_functions(self, path, statements, scopes, owner=None, local=False,
                          value_scopes=(), local_names=()):
        if local:
            scopes = scopes + [self.local_functions(statements)]
            value_scopes = (*value_scopes, self.scope_bindings(statements) | set(local_names))
        if owner is not None:
            self.function_scopes[id(owner)] = scopes
            self.function_value_scopes[id(owner)] = value_scopes
        for n in statements:
            d = n.data
            if n.kind in ('function', 'function_literal'):
                self.function_ids[id(n)] = self.new('function')
                self.all_functions.append((path, n))
                self.collect_functions(path, d['body'], scopes, owner=n, local=True,
                    value_scopes=value_scopes, local_names=[key for key, _ in d['params']])
            elif n.kind == 'type':
                self.type_ids[id(n)] = self.new('class')
                for method in d['methods']:
                    self.function_ids[id(method)] = self.new('method')
                    self.all_functions.append((path, method))
                    self.collect_functions(path, method.data['body'], scopes, owner=method, local=True,
                        value_scopes=value_scopes, local_names=[key for key, _ in method.data['params']])
            elif n.kind == 'if':
                self.collect_expression_functions(path, d['condition'], scopes, value_scopes)
                self.collect_functions(path, d['yes'], scopes, value_scopes=value_scopes)
                self.collect_functions(path, d['no'], scopes, value_scopes=value_scopes)
            elif n.kind == 'loop':
                self.collect_expression_functions(path, d['count'], scopes, value_scopes)
                self.collect_functions(path, d['body'], scopes, value_scopes=value_scopes)
            elif n.kind == 'scope':
                self.collect_functions(path, d['body'], scopes, local=True,
                    value_scopes=value_scopes)
            elif n.kind == 'try':
                self.collect_functions(path, d['body'], scopes, value_scopes=value_scopes)
                self.collect_functions(path, d['rescue'], scopes, local=True,
                    value_scopes=value_scopes, local_names=[d['reason']])
            else:
                self.collect_expression_functions(path, d, scopes, value_scopes)

    def collect_expression_functions(self, path, value, scopes, value_scopes):
        """Find literals at any expression depth without crossing scope boundaries.

        A literal has a statically emitted body just like a declaration, but its
        closure is created only when the expression is evaluated. Its body must
        be collected in a new lexical scope, not in the enclosing expression's.
        """
        if isinstance(value, Node):
            if value.kind == 'function_literal':
                self.collect_functions(path, [value], scopes, value_scopes=value_scopes)
            else:
                self.collect_expression_functions(path, value.data, scopes, value_scopes)
        elif isinstance(value, dict):
            for child in value.values():
                self.collect_expression_functions(path, child, scopes, value_scopes)
        elif isinstance(value, (list, tuple)):
            for child in value:
                self.collect_expression_functions(path, child, scopes, value_scopes)

    def _functions(self, path, function=None):
        functions = {name: n for name, n in self.exports[path].items() if n.kind == 'function'}
        if function is not None:
            for scope in self.function_scopes[id(function)]:
                functions.update(scope)
        return functions

    def _exported_values(self, path):
        # Possible runtime bindings are separate from unconditional exports:
        # if/loop/try bodies share the module scope, but their names may never
        # be initialized. Keep import conflicts and missing values runtime
        # checks rather than treating these names as definite declarations.
        if path not in self.value_exports:
            values = self.scope_bindings(self.modules[path])
            self.value_exports[path] = values
            for n in self.modules[path]:
                if n.kind == 'import_all':
                    values.update(self._exported_values(n.data['expr'].data['resolved']))
        return self.value_exports[path]

    def _values(self, path, function=None):
        values = set(self._exported_values(path))
        if function is not None:
            for scope in self.function_value_scopes[id(function)]:
                values.update(scope)
        return values

    def _validate_parameters(self):
        # Imported module declarations and lexically visible declarations are
        # protected names. Callable variables remain ordinary local bindings.
        for path, function in self.all_functions:
            protected = {name for name, n in self.exports[path].items()
                         if n.kind in ('function', 'type')}
            protected.update(self._functions(path, function))
            if any(name in protected for name, _ in function.data['params']):
                self.error(function, '参数名不能与函数名、形名或内置名称重名')

    def type_identity(self, path, annotation, n):
        # Empty parameter annotations are the existing internal any sentinel.
        if annotation.endswith(' 阵'):
            return ('array', self.type_identity(path, annotation[:-2], n))
        if annotation in ('', '数', '句', '空', '阵', '对', '算', '作', '事实', '典') or annotation in BUILTIN_TYPES:
            return annotation
        declaration = self.exports[path].get(annotation)
        if declaration is None or declaration.kind != 'type':
            self.error(n, '未定义类型：' + annotation + '；类型注解须使用已声明或已尽取导入的形名')
        return ('shape', id(declaration))

    def _validate_type_uses(self):
        from .c_runtime import walk_nodes
        for path, body in self.modules.items():
            shapes = {name for name, n in self.exports[path].items() if n.kind == 'type'} | BUILTIN_TYPES
            for n in walk_nodes({path: body}):
                if n.kind in ('name', 'call') and n.data['name'] in shapes:
                    name = n.data['name']
                    self.error(n, f'形名「{name}」不能作为普通值；创建实例请用「新 {name}」，类型注解请直接使用形名')
                if n.kind in ('function', 'function_literal'):
                    for _, annotation in n.data['params']:
                        self.type_identity(path, annotation, n)
                elif n.kind == 'type':
                    for _, annotation in n.data['fields']:
                        self.type_identity(path, annotation, n)
                elif n.kind == 'new':
                    if n.data['name'] not in shapes:
                        self.error(n, '未定义形：' + n.data['name'] + '；新 后须使用已声明或已尽取导入的形名')

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
                    ancestors.update({m.data['name']: ('method', m, owners[id(ancestor)]) for m in ancestor.data['methods'] if m.data['name'] not in ancestors})
                    ancestor = self.parents[id(ancestor)]
                for key, _ in n.data['fields']:
                    if key in ancestors:
                        self.error(n, '继承的字段／方法名称冲突：' + key)
                for method in n.data['methods']:
                    prior = ancestors.get(method.data['name'])
                    signature = lambda owner, params: [(key, self.type_identity(owner, annotation, method)) for key, annotation in params]
                    if prior and (prior[0] != 'method' or signature(prior[2], prior[1].data['params']) != signature(path, method.data['params']) or prior[1].data['procedure'] != method.data['procedure']):
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
        if can_panic and self.can_panic:
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
        self.live_temps, self.handlers, self.lexical_envs, self.loop_scopes = [], [], [], []
        self.base_env = env_name
        self.panic_exit = self.new('panic_exit')
        if self.can_panic:
            self.line(f'if (0) goto {self.panic_exit};')

    def clean_scopes(self, depth=0):
        # Both statement blocks and rescue clauses own rooted lexical frames.
        # A transfer releases only frames it actually exits; closures retain
        # escaped frames through ordinary traced edges.
        for env_name in reversed(self.lexical_envs[depth:]):
            self.line(f'env_free({env_name});')

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
        if n.kind == 'fact':
            return self.temp(f"v_fact({int(d['value'])})")
        if n.kind == 'map':
            out = self.temp(f'v_map_new({ln})')
            for key_node, value_node in d['entries']:
                key = self.expr(key_node)
                value = self.expr(value_node)
                added = self.temp(f'v_map_put({out}, {key}, {value}, {ln})', can_panic=True)
                self.drop(added, key, value)
            return out
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
        if n.kind == 'function_literal':
            receiver = 'self' if self.current_function is not None else 'v_null()'
            return self.temp(f'v_function(&{self.function_ids[id(n)]}_descriptor, env, {receiver})')
        if n.kind == 'function_ref':
            value = self.reference(d['expr'])
            out = self.temp(f'v_function_reference({value}, {int(d["procedure"])}, {ln})')
            self.drop(value)
            return out
        if n.kind == 'invoke':
            if d['callee'].kind == 'name' and d['callee'].data['name'] == '读':
                return self.call(n, '读', d['args'])
            callable_value = self.reference(d['callee'])
            actuals, values = self.argument_values(d['args'])
            out = self.temp(f'v_call({callable_value}, {actuals}, {ln})', can_panic=True)
            self.drop(callable_value, *values)
            return out
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
            target = {'数': 'RU_NUM', '句': 'RU_STR', '阵': 'RU_ARRAY', '事实': 'RU_FACT'}[d['target']]
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
                out = self.temp(f'v_fact({flag})')
                self.line(f'if ({"" if d["op"] == "且" else "!"}{flag}) {{')
                self.indent += 1
                right = self.expr(d['right'])
                self.line(f'{out} = v_fact(v_truth({right}));')
                self.drop(right)
                self.indent -= 1
                self.line('}')
                return out
            right = self.expr(d['right'])
            if d['op'] == '含':
                out = self.temp(f'v_member({left}, "含", 1, (const char *[]){{NULL}}, (Val[]){{{right}}}, {ln})', can_panic=True)
            else:
                out = self.temp(f"v_binary({cstr(d['op'])}, {left}, {right}, {ln})", can_panic=True)
            self.drop(left, right)
            return out
        if n.kind == 'member':
            receiver = self.expr(d['receiver'])
            mode = self.new('member_mode')
            self.line(f'int {mode};')
            prepared = self.temp(f"v_member_prepare({receiver}, {cstr(d['name'])}, {len(d['args'])}, {ln}, &{mode})")
            args, values = self.argument_values(d['args'])
            out = self.temp(f"v_member_finish({receiver}, {cstr(d['name'])}, {args}, {ln}, {mode}, {prepared})", can_panic=True)
            self.drop(receiver, prepared, *values)
            return out
        if n.kind in ('index', 'slice'):
            receiver = self.expr(d['receiver'])
            if n.kind == 'index':
                index = self.expr(d['index'])
                out = self.temp(f'v_index({receiver}, {index}, {ln})', can_panic=True)
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

    def reference(self, n):
        """Load a callee without the legacy implicit call on declared names."""
        d, ln = n.data, n.token.line
        if n.kind == 'name':
            if d['name'] == '读':
                self.error(n, '内置「读」暂不支持函数引用')
            return self.temp(f"env_get(env, {cstr(d['name'])}, {ln})")
        if n.kind == 'member' and not d['args']:
            receiver = self.expr(d['receiver'])
            out = self.temp(f"v_member_reference({receiver}, {cstr(d['name'])}, {ln})")
            self.drop(receiver)
            return out
        return self.expr(n)

    def call(self, n, name, args):
        if name != '读' and name not in self.functions and name not in self.known_values:
            self.error(n, f'未定义函数：{name}')
        if name == '读' or name in self.functions:
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

    def hoist(self, statements, function):
        for n in statements:
            if n.kind == 'function':
                value = self.temp(f'v_function(&{self.function_ids[id(n)]}_descriptor, env, {"self" if function else "v_null()"})')
                self.line(f'env_declare(env, {cstr(n.data["name"])}, {value});')
                self.drop(value)

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
            elif n.kind == 'finish':
                self.clean_scopes()
                self.line(f'env_free({self.base_env});')
                self.line('ru_source = previous_source;')
                self.line('return v_null();')
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
            elif n.kind == 'scope':
                scope_env = self.new('scope_env')
                self.line('{')
                self.indent += 1
                self.line(f'Env *{scope_env} = env_new(env, RU_SCOPE_BLOCK, {ln});')
                self.line('{')
                self.indent += 1
                self.line(f'Env *env = {scope_env};')
                self.lexical_envs.append(scope_env)
                previous_functions, previous_values = self.functions, self.known_values
                self.functions = {**self.functions, **self.local_functions(d['body'])}
                self.known_values = self.known_values | self.scope_bindings(d['body'])
                self.hoist(d['body'], function)
                self.block(d['body'], function)
                self.functions, self.known_values = previous_functions, previous_values
                self.lexical_envs.pop()
                self.line('env_free(env);')
                self.indent -= 1
                self.line('}')
                self.indent -= 1
                self.line('}')
            elif n.kind == 'try':
                rescued, finished, rescue_env = self.new('rescue'), self.new('end_try'), self.new('rescue_env')
                self.line('{')
                self.indent += 1
                self.line(f'if (0) goto {rescued};')
                self.handlers.append((rescued, len(self.lexical_envs)))
                self.block(d['body'], function)
                self.handlers.pop()
                self.line(f'goto {finished};')
                self.line(f'{rescued}: {{')
                self.indent += 1
                self.line(f'Env *{rescue_env} = env_new(env, RU_SCOPE_RESCUE, {ln});')
                self.line('{')
                self.indent += 1
                self.line(f'Env *env = {rescue_env};')
                self.line(f'env_bind(env, {cstr(d["reason"])}, ru_panic_reason, {ln});')
                self.line('ru_panic_clear();')
                self.lexical_envs.append(rescue_env)
                previous_functions, previous_values = self.functions, self.known_values
                self.functions = {**self.functions, **self.local_functions(d['rescue'])}
                self.known_values = self.known_values | self.scope_bindings(d['rescue']) | {d['reason']}
                self.hoist(d['rescue'], function)
                self.block(d['rescue'], function)
                self.functions, self.known_values = previous_functions, previous_values
                self.lexical_envs.pop()
                self.line(f'env_free({rescue_env});')
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
                if d['no']:
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
                self.loop_scopes.append(len(self.lexical_envs))
                self.block(d['body'], function)
                self.loop_scopes.pop()
                self.indent -= 1
                self.line('}')
            else:
                raise AssertionError(n.kind)

    def emit_function(self, path, fn):
        ident = self.function_ids[id(fn)]
        self.current_function = fn
        self.current_path, self.functions = path, self._functions(path, fn)
        self.known_values = self._values(path, fn)
        self.line(f'static Val {ident}(Env *global, Val self, int call_line, Val *args) {{')
        self.indent += 1
        self.line(f'const char *previous_source = ru_source; ru_source = {cstr(display_text(path))};')
        self.line('(void) self; (void) args; (void) call_line;')
        self.line(f'Env *local = env_new(global, RU_SCOPE_FUNCTION, {fn.token.line}); Env *env = local;')
        self.panic_context('local')
        for i, (key, _) in enumerate(fn.data['params']):
            self.line(f'env_set(env, {cstr(key)}, args[{i}]);')
        self.hoist(fn.data['body'], True)
        self.block(fn.data['body'], True)
        self.line('env_free(env);')
        if not fn.data['procedure']:
            self.line(f"ru_fail(call_line, {cstr('函数「' + fn.data['name'] + '」没有执行「得」')});")
        self.line('ru_source = previous_source;')
        self.line('return v_null();')
        if self.can_panic:
            self.line(f'{self.panic_exit}: env_free(local); ru_source = previous_source; return v_null();')
        self.indent -= 1
        self.line('}')

    def string_array(self, name, strings):
        if not strings:
            return 'NULL'
        self.line(f'static const char *{name}[] = {{{", ".join(cstr(s) for s in strings)}}};')
        return name

    def compile(self):
        def uses_modulo(value):
            if isinstance(value, Node):
                return (value.kind == 'binary' and value.data['op'] == '%') or uses_modulo(value.data)
            if isinstance(value, dict):
                return any(uses_modulo(child) for child in value.values())
            if isinstance(value, (list, tuple)):
                return any(uses_modulo(child) for child in value)
            return False

        self.line(f'/* Generated by ru {__version__}. Standalone C99; source AST is not embedded. */')
        if uses_modulo(self.modules):
            self.line('#define RU_ENABLE_MODULO 1')
        runtime_position = len(self.lines)
        for path, ident in self.module_ids.items():
            self.line(f'static Env {ident}_env; static int {ident}_state;')
            if self.can_panic:
                self.line(f'static RuModuleFailure {ident}_failure;')
            self.line(f'static Val {ident}_init(void);')
        for _, n in self.all_functions:
            ident = self.function_ids[id(n)]
            self.line(f'static Val {ident}(Env *, Val, int, Val *);')
            keys = self.string_array(ident + '_names', [p[0] for p in n.data['params']])
            types = self.string_array(ident + '_types', [p[1] for p in n.data['params']])
            self.line(f'static RuFunction {ident}_descriptor = {{{cstr(n.data["name"])}, {len(n.data["params"])}, {keys}, {types}, {ident}, {int(n.data["procedure"])}}};')
        for names in self.declarations.values():
            for n in names.values():
                if n.kind == 'type':
                    self.line(f'static RuClass {self.type_ids[id(n)]};')
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
        for path, fn in self.all_functions:
            self.emit_function(path, fn)
        for path, program in self.modules.items():
            ident = self.module_ids[path]
            self.current_function = None
            self.current_path, self.functions = path, self._functions(path)
            self.known_values = self._values(path)
            self.line(f'static Val {ident}_init(void) {{')
            self.indent += 1
            self.line(f'if ({ident}_state == 2) return v_module(&{ident}_env);')
            if self.can_panic:
                self.line(f'if ({ident}_state == 3) return ru_module_failure_raise(&{ident}_failure);')
            self.line(f'if ({ident}_state == 1) ru_fail(1, "循环外言");')
            if self.native_enabled:
                # A caught ordinary error cannot strand a first-time module in
                # initialization state. Static imports must initialize before
                # entering foreign code; repeat imports remain allowed.
                self.line('if (ru_native_callback_depth) ru_fail(1, "原生 C 回调中不能首次初始化外言；请在首次原生调用之前导入依赖");')
            self.line(f'{ident}_state = 1;')
            self.line(f'const char *previous_source = ru_source; ru_source = {cstr(display_text(path))};')
            builtins = 'ru_practical_builtins' if '__实用' in set(ast_strings(self.modules)) else 'ru_contest_builtins'
            builtins_call = f'ru_native_builtins({builtins}())' if self.native_enabled else f'{builtins}()'
            self.line(f'Env *global = &{ident}_env; Env *env = global; env_init(env, {builtins_call});')
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
            if self.can_panic:
                self.line(f'{self.panic_exit}: ru_module_failure_save(&{ident}_failure); {ident}_state = 3; ru_source = previous_source; return v_null();')
            self.indent -= 1
            self.line('}')
        self.line('int main(int argc, char **argv) {')
        self.indent += 1
        self.line(f'ru_source = {cstr(display_text(self.source_name))}; ru_init();')
        self.line(f'Val root = {self.module_ids[self.root]}_init(); (void) root; (void) argc; (void) argv;')
        if self.can_panic:
            self.line('if (ru_panicking) return ru_panic_uncaught();')
        self.line('int status = 0;')
        if self.entry:
            self.line('Val arguments = ru_arguments(argc, argv);')
            self.line('Val entry = env_get(root.module, "元初", 1); const char *keys[] = {NULL};')
            self.line('Val result = v_call(entry, 1, keys, &arguments, 1);')
            if self.can_panic:
                self.line('if (ru_panicking) { v_drop(result); v_drop(entry); v_drop(arguments); return ru_panic_uncaught(); }')
            self.line('if (result.kind != RU_NUM || !isfinite(result.n) || result.n < 0 || result.n > 255 || (double)(unsigned int)result.n != result.n) ru_fail(1, "元初须返回 0 至 255 的整数");')
            self.line('status = (int) result.n; v_drop(result); v_drop(entry); v_drop(arguments);')
        self.line('ru_shutdown(); return status;')
        self.indent -= 1
        self.line('}')
        from .c_runtime import runtime_source
        generated = '\n'.join(self.lines)
        self.lines.insert(runtime_position, runtime_source(self.modules, generated, self.full_runtime, native_plan=self.native_plan))
        return '\n'.join(self.lines) + '\n'
