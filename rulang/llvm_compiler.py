"""Direct AST -> LLVM 14 typed-pointer IR; no generated Ru program in C.

The C compiler's semantic preparation is reused, not its code generation.
LLVM owns expression order, branches, loops and function bodies. A private
pointer-only ABI delegates dynamic values to one C runtime translation unit.
Ordinary function descriptors point directly to the private pointer ABI;
C-only entries retain RuCode adapters. Descriptors and module state are data,
not an interpreter or a second program lowering.
"""
from pathlib import Path
import struct

from . import __version__
from .compiler import BINARY_OPERATIONS, Compiler, cstr
from .c_runtime import runtime_source, walk_nodes
from .diagnostics import display_text
from .frontend import bind_arguments


# Keep these declarations next to the implementation of the private ABI.
ABI = {
    'numeric_check': ('void', 'i8*, i8*, i8*, i32'),
    'number_value': ('double', 'i8*'), 'number_convert': ('double', 'i8*, i32'),
    'number_unary': ('double', 'i8*, i8*, i32'),
    'finite_number': ('double', 'double, i32'), 'nonzero_number': ('double', 'double, i32'),
    'frame_new': ('i8*', 'i32'), 'slot': ('i8*', 'i8*, i32'),
    'frame_size': ('i64', 'i32'), 'frame_init': ('void', 'i8*, i32'),
    'frame_drop': ('void', 'i8*'),
    'frame_roots': ('void', 'i8*, i32, i32'),
    'local_frame_size': ('i64', 'i32'), 'local_frame_init': ('void', 'i8*, i32'),
    'local_frame_roots': ('void', 'i8*, i32, i32'),
    'local_slot': ('i8*', 'i8*, i32, i8*'),
    'local_clear': ('void', 'i8*'), 'local_clear_count': ('void', 'i8*, i32'),
    'local_clear_mask': ('void', 'i8*, i32, i32, i32'),
    'local_frame_drop': ('void', 'i8*'),
    'args_size': ('i64', 'i32'), 'args_set': ('void', 'i8*, i32, i8*'),
    'bind_cached': ('void', 'i8*, i8*, i8*, i32, i8**'),
    'get_cached': ('void', 'i8*, i8*, i8*, i32, i8**'),
    'clear': ('void', 'i8*'), 'frame_free': ('void', 'i8*'),
    'clear_count': ('void', 'i8*, i32'),
    'return_copy': ('void', 'i8*, i8*'), 'return_null': ('void', 'i8*'),
    'copy': ('void', 'i8*, i8*'), 'null': ('void', 'i8*'),
    'number': ('void', 'i8*, double'), 'fact': ('void', 'i8*, i32'),
    'string': ('void', 'i8*, i8*'), 'truth': ('i32', 'i8*'),
    'count': ('i64', 'i8*, i32'), 'source': ('i8*', 'i8*'),
    'source_restore': ('void', 'i8*'), 'env_new': ('i8*', 'i8*, i32, i32'),
    'env_free': ('void', 'i8*'), 'bind_arg': ('void', 'i8*, i8*, i8*, i32'),
    'get': ('void', 'i8*, i8*, i8*, i32'), 'bind': ('void', 'i8*, i8*, i8*, i32'),
    'declare': ('void', 'i8*, i8*, i8*'), 'function': ('void', 'i8*, i32, i8*, i8*'),
    'class': ('void', 'i8*, i32'), 'class_ready': ('void', 'i32, i32'),
    'reference': ('void', 'i8*, i8*, i32, i32'),
    'member_reference': ('void', 'i8*, i8*, i8*, i32'),
    'call': ('void', 'i8*, i8*, i32, i8**, i8*, i32'),
    'read': ('void', 'i8*, i8*, i32'), 'print': ('void', 'i8*, i32'),
    'array': ('void', 'i8*, i32, i8*, i32'), 'map': ('void', 'i8*, i32'),
    'map_put': ('void', 'i8*, i8*, i8*, i32'),
    'unary': ('void', 'i8*, i8*, i8*, i32'),
    'binary': ('void', 'i8*, i8*, i8*, i8*, i32'),
    'convert': ('void', 'i8*, i8*, i8*, i32'),
    'index': ('void', 'i8*, i8*, i8*, i32'),
    'slice': ('void', 'i8*, i8*, i8*, i8*, i32'),
    'member_prepare': ('void', 'i8*, i8*, i8*, i32, i32, i32*'),
    'member_finish': ('void', 'i8*, i8*, i8*, i32, i8**, i8*, i32, i32, i8*'),
    'check_index': ('void', 'i8*, i8*, i32'),
    'set_index': ('void', 'i8*, i8*, i8*, i32'),
    'check_member': ('void', 'i8*, i8*, i32'),
    'set_member': ('void', 'i8*, i8*, i8*, i32'),
    'new': ('void', 'i8*, i8*, i32, i8**, i8*, i32'),
    'import': ('void', 'i8*, i32'), 'import_all': ('void', 'i8*, i8*, i32'),
    'panicking': ('i32', ''), 'raise': ('void', 'i8*, i32, i32'),
    'catch': ('void', 'i8*, i8*'), 'missing_return': ('void', 'i8*, i32'),
    'main': ('i32', 'i32, i8**, i32, i32'),
}
for _name in BINARY_OPERATIONS.values():
    ABI[_name] = ('void', 'i8*, i8*, i8*, i32')
for _name in ('eq', 'ne', 'lt', 'le', 'gt', 'ge'):
    ABI['test_' + _name] = ('i32', 'i8*, i8*, i32')
INITIALIZERS = {'copy', 'null', 'number', 'fact', 'get', 'get_cached',
                'string', 'function', 'class', 'reference', 'member_reference', 'call', 'read',
                'array', 'map', 'unary', 'binary', 'convert', 'index', 'slice',
                'member_prepare', 'member_finish', 'new', 'import', *BINARY_OPERATIONS.values()}
for _name in sorted(INITIALIZERS):
    ABI['init_' + _name] = ABI[_name]


class LLVMCompiler(Compiler):
    supports_mi_llvm = True
    independent_slots = True

    def compile(self, triple=None, data_layout=None):
        self.strings, self.constants, self.bodies = {}, [], []
        self.llvm_counter = 0
        self.fn_indices = {id(fn): i for i, (_, fn) in enumerate(self.all_functions)}
        self.class_indices = {identity: i for i, identity in enumerate(self.type_ids)}
        self.module_indices = {path: i for i, path in enumerate(self.modules)}
        # Exhaustive preflight, including dead bodies, before emitting anything.
        kinds = {'fact', 'map', 'number', 'string', 'null', 'self', 'name', 'call',
                 'function_literal', 'function_ref', 'invoke', 'array', 'convert',
                 'unary', 'binary', 'member', 'index', 'slice', 'new', 'import',
                 'function', 'module_decl', 'type', 'bind', 'print', 'expr',
                 'return', 'import_all', 'finish', 'assign', 'panic', 'scope',
                 'try', 'break', 'continue', 'if', 'loop'}
        for n in walk_nodes(self.modules):
            if n.kind not in kinds:
                self.error(n, 'LLVM AOT 尚不支持语法节点：' + n.kind)
        for path, fn in self.all_functions:
            if self.mi_plan and id(fn) in self.mi_plan.functions:
                continue
            self.emit_body(path, fn, fn.data['body'], self.function_ids[id(fn)] + '_llvm')
        for path, body in self.modules.items():
            self.emit_body(path, None, body, self.module_ids[path] + '_llvm')
        declarations = [f'declare {result} @rul_{name}({args})'
                        for name, (result, args) in ABI.items()]
        declarations += ['declare void @llvm.lifetime.start.p0i8(i64 immarg, i8* nocapture)',
                         'declare void @llvm.lifetime.end.p0i8(i64 immarg, i8* nocapture)']
        header = [f'; Generated by ru {__version__}; direct LLVM AOT; private ABI v1.',
                  'source_filename = "ru-direct-llvm"']
        if triple:
            header.append(f'target triple = "{triple}"')
        if data_layout:
            header.append(f'target datalayout = "{data_layout}"')
        root = self.module_indices[self.root]
        if self.mi_plan:
            self.bodies.append(self.mi_plan.compute_source('llvm'))
        main = ('define i32 @main(i32 %argc, i8** %argv) {\nentry:\n'
                f'  %status = call i32 @rul_main(i32 %argc, i8** %argv, i32 {root}, i32 {int(bool(self.entry))})\n'
                '  ret i32 %status\n}')
        return '\n\n'.join(['\n'.join(header), '\n'.join(self.constants),
                             '\n'.join(declarations), *self.bodies, main]) + '\n'

    def fresh(self, prefix='t'):
        self.llvm_counter += 1
        return prefix + str(self.llvm_counter)

    def emit(self, line):
        self.body.append('  ' + line)

    def label(self, name):
        self.body.append(name + ':')
        self.current_label = name
        self.terminated = False

    def jump(self, name):
        if not self.terminated:
            self.emit('br label %' + name)
            self.terminated = True

    def branch(self, condition, yes, no):
        self.emit(f'br i1 {condition}, label %{yes}, label %{no}')
        self.terminated = True

    def call_abi(self, name, *values):
        if name in ('clear', 'clear_count', 'frame_drop'):
            self.cleanup_sites[len(self.body)] = (
                name, int(values[1]) if name == 'clear_count' else None,
                frozenset(self.live_root_slots))
            # Unwind is emitted before its success continuation; clearing that
            # edge must not erase the continuation's live-root analysis.
            if name == 'clear_count':
                self.live_root_slots.clear()
        if name in ('get', 'init_get', 'bind') and self.current_function:
            env_index, name_index = (0, 1) if name == 'bind' else (1, 2)
            if values[env_index] == self.base_env and values[name_index] in self.cached_binding_keys:
                key = values[name_index]
                if key not in self.binding_caches:
                    cache = self.alloca('i8*')
                    self.entry_allocations.append(f'  store i8* null, i8** {cache}')
                    self.binding_caches[key] = cache
                name, values = name + '_cached', (*values, self.binding_caches[key])
        result, signature = ABI[name]
        types = signature.split(', ') if signature else []
        assert len(types) == len(values), name
        call = f'call {result} @rul_{name}(' + ', '.join(f'{t} {v}' for t, v in zip(types, values)) + ')'
        if result == 'void':
            self.emit(call)
            return None
        value = '%' + self.fresh()
        self.emit(value + ' = ' + call)
        return value

    def string(self, text):
        if text not in self.strings:
            data = text.encode('utf-8') + b'\0'
            ident = '@' + self.fresh('str')
            literal = ''.join(f'\\{byte:02X}' for byte in data)
            self.constants.append(f'{ident} = private unnamed_addr constant [{len(data)} x i8] c"{literal}"')
            self.strings[text] = f'getelementptr inbounds ([{len(data)} x i8], [{len(data)} x i8]* {ident}, i32 0, i32 0)'
        return self.strings[text]

    def slot(self):
        ident = '%' + self.fresh('v')
        index = self.slot_count
        self.slot_count += 1
        self.slot_peak = max(self.slot_peak, self.slot_count)
        if index < len(self.slot_addresses):
            return self.slot_addresses[index]
        self.entry_allocations.append(f'  {ident} = call i8* @rul_slot(i8* %frame, i32 {index})')
        self.slot_addresses.append(ident)
        return ident

    def clear_temporaries(self):
        # Only normal control-flow boundaries: no expression temporary remains
        # live after these clears. SSA identities stay globally fresh even when
        # their physical frame slot is reused by a later statement.
        self.call_abi('clear_count', '%frame', str(self.slot_count))
        self.slot_count = 0

    def alloca(self, typ):
        ident = '%' + self.fresh('local')
        self.entry_allocas.append(f'  {ident} = alloca {typ}')
        return ident

    def load(self, typ, pointer):
        ident = '%' + self.fresh()
        self.emit(f'{ident} = load {typ}, {typ}* {pointer}')
        return ident

    def truth(self, value):
        flag = self.call_abi('truth', value)
        ident = '%' + self.fresh()
        self.emit(f'{ident} = icmp ne i32 {flag}, 0')
        return ident

    def condition(self, n):
        """Keep condition results in SSA instead of materializing Val slots."""
        d = n.data
        if n.kind == 'fact':
            return 'true' if d['value'] else 'false'
        if n.kind == 'null':
            return 'false'
        if n.kind == 'number':
            return 'true'
        if n.kind == 'unary' and d['op'] == '非':
            value = self.condition(d['expr'])
            out = '%' + self.fresh()
            self.emit(f'{out} = xor i1 {value}, true')
            return out
        if n.kind == 'binary' and d['op'] in ('且', '或'):
            left = self.condition(d['left'])
            predecessor = self.current_label
            right_label, done = self.fresh('right'), self.fresh('logical_end')
            self.branch(left, *((right_label, done) if d['op'] == '且' else (done, right_label)))
            self.label(right_label)
            right = self.condition(d['right'])
            right_predecessor = self.current_label
            self.jump(done)
            self.label(done)
            out = '%' + self.fresh()
            short = 'false' if d['op'] == '且' else 'true'
            self.emit(f'{out} = phi i1 [ {short}, %{predecessor} ], [ {right}, %{right_predecessor} ]')
            return out
        if n.kind == 'binary' and d['op'] in ('==', '!=', '<', '<=', '>', '>='):
            left, right = self.expr(d['left']), self.expr(d['right'])
            flag = self.call_abi('test_' + BINARY_OPERATIONS[d['op']], left, right, str(n.token.line))
            self.check_panic()
            out = '%' + self.fresh()
            self.emit(f'{out} = icmp ne i32 {flag}, 0')
            return out
        return self.truth(self.expr(n))

    def scalar_number(self, n):
        d, ln = n.data, str(n.token.line)
        if n.kind == 'number':
            bits = struct.unpack('>Q', struct.pack('>d', d['value']))[0]
            return f'0x{bits:016X}'
        if n.kind == 'convert':
            return self.call_abi('number_convert', self.expr(d['expr']), ln)
        if n.kind == 'unary':
            if self.numeric_expression(d['expr']):
                value = self.scalar_number(d['expr'])
            else:
                value = self.call_abi('number_unary', self.expr(d['expr']), self.string(d['op']), ln)
            if d['op'] == '-':
                out = '%' + self.fresh()
                self.emit(f'{out} = fneg double {value}')
                value = out
            return self.call_abi('finite_number', value, ln)
        values, boxed = [], []
        for child in (d['left'], d['right']):
            scalar = self.numeric_expression(child)
            values.append(self.scalar_number(child) if scalar else self.expr(child))
            boxed.append(not scalar)
        if any(boxed):
            self.call_abi('numeric_check', self.string(d['op']),
                          values[0] if boxed[0] else 'null', values[1] if boxed[1] else 'null', ln)
        values = [self.call_abi('number_value', value) if box else value for value, box in zip(values, boxed)]
        if d['op'] in ('/', '%'):
            values[1] = self.call_abi('nonzero_number', values[1], ln)
        out = '%' + self.fresh()
        instruction = {'+':'fadd', '-':'fsub', '*':'fmul', '/':'fdiv', '%':'frem'}[d['op']]
        self.emit(f'{out} = {instruction} double {values[0]}, {values[1]}')
        return self.call_abi('finite_number', out, ln)

    def clean_environments(self, depth=0):
        for env in reversed(self.llvm_envs[depth:]):
            self.call_abi('env_free', env)

    def panic_transfer(self):
        target, depth = self.llvm_handlers[-1] if self.llvm_handlers else (self.panic_label, 0)
        self.clean_environments(depth)
        self.call_abi('clear', '%frame')
        self.jump(target)

    def check_panic(self):
        flag = self.call_abi('panicking')
        test = '%' + self.fresh()
        self.emit(f'{test} = icmp ne i32 {flag}, 0')
        unwind, resumed = self.fresh('unwind'), self.fresh('resume')
        self.branch(test, unwind, resumed)
        self.label(unwind)
        self.panic_transfer()
        self.label(resumed)

    def result(self, operation, *args, panic=False):
        if operation not in ('number', 'null', 'fact', 'eq', 'ne', 'lt', 'le', 'gt', 'ge', 'contains'):
            self.root_slots.add(self.slot_count)
            self.live_root_slots.add(self.slot_count)
        out = self.slot()
        if operation in INITIALIZERS:
            operation = 'init_' + operation
        self.call_abi(operation, out, *args)
        for value in args:
            if value in self.pack_buffers:
                self.pack_ends.setdefault(len(self.body), []).append(value)
        if panic:
            self.check_panic()
        return out

    def pack(self, args):
        # Evaluate all arguments left-to-right before choosing their layout.
        # Every expression result already owns a root. Defer small multi-value
        # packs until the final frame layout is known: independent slots need
        # contiguous borrowed storage. Keep original roots until normal/unwind
        # cleanup; one result can always be passed directly.
        values, contiguous = [], True
        for _, value in args:
            before = self.slot_count
            values.append(self.expr(value))
            contiguous = contiguous and self.slot_count == before + 1
        if 1 < len(values) <= 64:
            pointer = '%' + self.fresh('pack')
            self.pack_buffers[pointer] = (values, contiguous)
            self.pack_starts.setdefault(len(self.body), []).append(pointer)
            packed = [pointer]
        elif len(values) == 1 or contiguous:
            packed = values
        else:
            self.root_slots.update(range(self.slot_count, self.slot_count + len(values)))
            self.live_root_slots.update(range(self.slot_count, self.slot_count + len(values)))
            packed = [self.slot() for _ in values]
            for out, value in zip(packed, values):
                self.call_abi('init_copy', out, value)
        if not args:
            return '0', 'null', 'null'
        keys = [self.string(key) if key is not None else 'null' for key, _ in args]
        name = '@' + self.fresh('keys')
        self.constants.append(f'{name} = private constant [{len(keys)} x i8*] [' +
                              ', '.join('i8* ' + key for key in keys) + ']')
        pointer = f'getelementptr inbounds ([{len(keys)} x i8*], [{len(keys)} x i8*]* {name}, i32 0, i32 0)'
        return str(len(args)), pointer, packed[0]

    def reference(self, n):
        d, ln = n.data, str(n.token.line)
        if n.kind == 'name':
            if d['name'] == '读':
                self.error(n, '内置「读」暂不支持函数引用')
            return self.result('get', self.env, self.string(d['name']), ln)
        if n.kind == 'member' and not d['args']:
            return self.result('member_reference', self.expr(d['receiver']), self.string(d['name']), ln)
        return self.expr(n)

    def call(self, n, name, args):
        if name != '读' and name not in self.functions and name not in self.known_values:
            self.error(n, '未定义函数：' + name)
        if name == '读' or name in self.functions:
            params = ['提示'] if name == '读' else [p[0] for p in self.functions[name].data['params']]
            bind_arguments(name, args, params, lambda message: self.error(n, message), optional=name == '读')
        ln = str(n.token.line)
        if name == '读':
            prompt = self.expr(args[0][1]) if args else self.result('string', self.string(''))
            return self.result('read', prompt, ln)
        callee = self.result('get', self.env, self.string(name), ln)
        return self.result('call', callee, *self.pack(args), ln, panic=True)

    def expr(self, n):
        d, ln, kind = n.data, str(n.token.line), n.kind
        if kind != 'number' and self.numeric_expression(n):
            return self.result('number', self.scalar_number(n))
        if kind == 'number':
            bits = struct.unpack('>Q', struct.pack('>d', d['value']))[0]
            return self.result('number', f'0x{bits:016X}')
        if kind == 'string':
            return self.result('string', self.string(d['value']))
        if kind == 'fact':
            return self.result('fact', str(int(d['value'])))
        if kind == 'null':
            return self.result('null')
        if kind == 'self':
            return self.result('copy', '%self')
        if kind == 'name':
            if d['name'] in self.functions or d['name'] == '读':
                return self.call(n, d['name'], [])
            return self.result('get', self.env, self.string(d['name']), ln)
        if kind == 'call':
            return self.call(n, d['name'], d['args'])
        if kind == 'function_literal':
            return self.result('function', str(self.fn_indices[id(n)]), self.env,
                               '%self' if self.current_function else 'null')
        if kind == 'function_ref':
            return self.result('reference', self.reference(d['expr']), str(int(d['procedure'])), ln)
        if kind == 'invoke':
            if d['callee'].kind == 'name' and d['callee'].data['name'] == '读':
                return self.call(n, '读', d['args'])
            callee = self.reference(d['callee'])
            return self.result('call', callee, *self.pack(d['args']), ln, panic=True)
        if kind == 'array':
            count, _, values = self.pack([(None, item) for item in d['items']])
            return self.result('array', count, values, ln)
        if kind == 'map':
            out = self.result('map', ln)
            for key_node, value_node in d['entries']:
                key, value = self.expr(key_node), self.expr(value_node)
                self.call_abi('map_put', out, key, value, ln)
                self.check_panic()
            return out
        if kind == 'convert':
            return self.result('convert', self.expr(d['expr']), self.string(d['target']), ln)
        if kind == 'unary':
            return self.result('unary', self.string(d['op']), self.expr(d['expr']), ln)
        if kind == 'binary':
            if d['op'] in ('且', '或'):
                test = self.condition(n)
                flag = '%' + self.fresh()
                self.emit(f'{flag} = zext i1 {test} to i32')
                return self.result('fact', flag)
            left = self.expr(d['left'])
            right = self.expr(d['right'])
            return self.result(BINARY_OPERATIONS[d['op']], left, right, ln, panic=True)
        if kind == 'member':
            receiver, mode = self.expr(d['receiver']), self.alloca('i32')
            prepared = self.result('member_prepare', receiver, self.string(d['name']), str(len(d['args'])), ln, mode)
            actuals = self.pack(d['args'])
            return self.result('member_finish', receiver, self.string(d['name']), *actuals,
                               ln, self.load('i32', mode), prepared, panic=True)
        if kind == 'index':
            return self.result('index', self.expr(d['receiver']), self.expr(d['index']), ln, panic=True)
        if kind == 'slice':
            receiver = self.expr(d['receiver'])
            start = self.expr(d['start']) if d['start'] else self.result('null')
            end = self.expr(d['end']) if d['end'] else self.result('null')
            return self.result('slice', receiver, start, end, ln)
        if kind == 'new':
            klass = self.result('get', self.env, self.string(d['name']), ln)
            return self.result('new', klass, *self.pack(d['args']), ln)
        if kind == 'import':
            return self.result('import', str(self.module_indices[d['resolved']]), panic=True)
        self.error(n, 'LLVM AOT 尚不支持表达式：' + kind)

    def hoist(self, statements, function):
        for n in statements:
            if n.kind == 'function':
                value = self.result('function', str(self.fn_indices[id(n)]), self.env,
                                    '%self' if function else 'null')
                self.call_abi('declare', self.env, self.string(n.data['name']), value)
            elif n.kind == 'type':
                value = self.result('class', str(self.class_indices[id(n)]))
                self.call_abi('declare', self.env, self.string(n.data['name']), value)
        self.clear_temporaries()

    def scoped_block(self, body, scope, function, reason=None, line='1'):
        previous = self.env
        self.env = self.call_abi('env_new', previous, str(scope), line)
        self.llvm_envs.append(self.env)
        old_functions, old_values = self.functions, self.known_values
        self.functions = {**self.functions, **self.local_functions(body)}
        self.known_values = self.known_values | self.scope_bindings(body)
        if reason is not None:
            self.known_values |= {reason}
            self.call_abi('catch', self.env, self.string(reason))
        self.hoist(body, function)
        self.block(body, function)
        if not self.terminated:
            self.call_abi('env_free', self.env)
        self.llvm_envs.pop()
        self.env, self.functions, self.known_values = previous, old_functions, old_values

    def block(self, statements, function=False):
        for n in statements:
            if self.terminated:
                self.label(self.fresh('unreachable'))
            d, ln, kind = n.data, str(n.token.line), n.kind
            if kind in ('function', 'module_decl'):
                continue
            if kind == 'type':
                self.call_abi('class_ready', str(self.class_indices[id(n)]), ln)
            elif kind in ('bind', 'print', 'expr', 'return', 'import_all', 'panic'):
                value = self.expr(d['expr'])
                if kind == 'bind':
                    self.call_abi('bind', self.env, self.string(d['name']), value, ln)
                elif kind == 'print':
                    self.call_abi('print', value, ln)
                elif kind == 'import_all':
                    self.call_abi('import_all', self.env, value, ln)
                elif kind == 'return':
                    self.call_abi('return_copy', '%out', value)
                    self.clean_environments()
                    self.jump(self.finish_label)
                elif kind == 'panic':
                    self.call_abi('raise', value, ln, str(n.token.col))
                    self.panic_transfer()
            elif kind == 'finish':
                self.call_abi('return_null', '%out')
                self.clean_environments()
                self.jump(self.finish_label)
            elif kind == 'assign':
                target, value_node = d['target'], d['expr']
                td = target.data
                receiver = self.expr(td['receiver'])
                if target.kind == 'index':
                    index = self.expr(td['index'])
                elif td['name'] == '位':
                    bound = bind_arguments('位', td['args'], ['位'], lambda message: self.error(target, message))
                    index = self.expr(bound['位'])
                else:
                    index = None
                if index is not None:
                    self.call_abi('check_index', receiver, index, ln)
                    value = self.expr(value_node)
                    self.call_abi('set_index', receiver, index, value, ln)
                else:
                    name = self.string(td['name'])
                    self.call_abi('check_member', receiver, name, ln)
                    value = self.expr(value_node)
                    self.call_abi('set_member', receiver, name, value, ln)
            elif kind == 'scope':
                self.scoped_block(d['body'], 3, function, line=ln)
            elif kind == 'try':
                rescue, done = self.fresh('rescue'), self.fresh('try_end')
                self.llvm_handlers.append((rescue, len(self.llvm_envs)))
                self.block(d['body'], function)
                self.llvm_handlers.pop()
                self.jump(done)
                self.label(rescue)
                self.scoped_block(d['rescue'], 2, function, reason=d['reason'], line=ln)
                self.jump(done)
                self.label(done)
            elif kind in ('break', 'continue'):
                done, resume, depth = self.llvm_loops[-1]
                self.clean_environments(depth)
                self.clear_temporaries()
                self.jump(done if kind == 'break' else resume)
            elif kind == 'if':
                flag = self.condition(d['condition'])
                self.clear_temporaries()
                yes, no, done = self.fresh('yes'), self.fresh('no'), self.fresh('if_end')
                self.branch(flag, yes, no)
                self.label(yes)
                self.block(d['yes'], function)
                self.jump(done)
                self.label(no)
                self.block(d['no'], function)
                self.jump(done)
                self.label(done)
            elif kind == 'loop':
                condition, body, done = self.fresh('loop_check'), self.fresh('loop_body'), self.fresh('loop_end')
                if d['count'] is not None:
                    count = self.call_abi('count', self.expr(d['count']), ln)
                    counter = self.alloca('i64')
                    self.emit(f'store i64 0, i64* {counter}')
                self.clear_temporaries()
                self.jump(condition)
                self.label(condition)
                if d['count'] is None:
                    self.jump(body)
                else:
                    index = self.load('i64', counter)
                    test = '%' + self.fresh()
                    self.emit(f'{test} = icmp ult i64 {index}, {count}')
                    self.branch(test, body, done)
                self.label(body)
                # A counted continue must execute the increment, not restart
                # the condition with the same counter. Infinite loops have no
                # increment and resume directly at their condition/header.
                resume = self.fresh('loop_increment') if d['count'] is not None else condition
                self.llvm_loops.append((done, resume, len(self.llvm_envs)))
                self.block(d['body'], function)
                self.llvm_loops.pop()
                self.jump(resume)
                if d['count'] is not None:
                    self.label(resume)
                    value = self.load('i64', counter)
                    inc = '%' + self.fresh()
                    self.emit(f'{inc} = add i64 {value}, 1')
                    self.emit(f'store i64 {inc}, i64* {counter}')
                    self.jump(condition)
                self.label(done)
            else:
                self.error(n, 'LLVM AOT 尚不支持语句：' + kind)
            if not self.terminated:
                self.clear_temporaries()

    def emit_body(self, path, fn, statements, name):
        self.current_path, self.current_function = path, fn
        self.functions, self.known_values = self._functions(path, fn), self._values(path, fn)
        self.body, self.entry_allocations, self.slot_count = [], [], 0
        self.entry_allocas = []
        self.slot_peak = 0
        self.slot_addresses = []
        self.root_slots = set()
        self.live_root_slots = set()
        self.cleanup_sites = {}
        self.pack_buffers, self.pack_starts, self.pack_ends = {}, {}, {}
        self.binding_caches = {}
        # Select the same repeated local names as the C emitter.
        self.cached_binding_keys = {self.string(key) for key in sorted(self.local_binding_cache_names(fn))}
        self.terminated = False
        self.current_label = 'entry'
        self.llvm_envs, self.llvm_handlers, self.llvm_loops = [], [], []
        self.finish_label, self.panic_label = self.fresh('finish'), self.fresh('panic')
        previous = self.call_abi('source', self.string(display_text(path)))
        self.env = self.call_abi('env_new', '%global', '1', str(fn.token.line)) if fn else '%global'
        base_env = self.env
        self.base_env = base_env
        if fn:
            for index, (key, _) in enumerate(fn.data['params']):
                self.call_abi('bind_arg', self.env, self.string(key), '%args', str(index))
        self.hoist(statements, bool(fn))
        self.block(statements, bool(fn))
        if not self.terminated:
            if fn and not fn.data['procedure']:
                self.call_abi('missing_return', self.string(fn.data['name']), '%call_line')
            self.jump(self.finish_label)
        self.label(self.panic_label)
        self.call_abi('return_null', '%out')
        self.jump(self.finish_label)
        self.label(self.finish_label)
        if fn:
            self.call_abi('env_free', base_env)
        self.call_abi('frame_drop' if self.slot_peak <= 64 else 'frame_free', '%frame')
        if self.slot_peak <= 64:
            self.emit('call void @llvm.lifetime.end.p0i8(i64 -1, i8* %frame)')
        self.call_abi('source_restore', previous)
        self.emit('ret void')
        # v_call and module initialization supply a fresh result Val, separate
        # from the arguments/environment. This matches Clang's noalias sret
        # storage contract; the heap objects referenced by values may alias.
        signature = f'define void @{name}(i8* %global, i8* %self, i32 %call_line, i8* %args, i8* noalias writeonly %out) {{'
        independent = self.independent_slots and self.slot_peak <= 64
        allocation = [f'  %frame = call i8* @rul_frame_new(i32 {self.slot_peak})']
        if self.slot_peak <= 64:
            prefix = 'local_' if independent else ''
            allocation = [f'  %frame_bytes = call i64 @rul_{prefix}frame_size(i32 {self.slot_peak})',
                          '  %frame = alloca i8, i64 %frame_bytes, align 16',
                          '  call void @llvm.lifetime.start.p0i8(i64 -1, i8* %frame)',
                          f'  call void @rul_{prefix}frame_init(i8* %frame, i32 {self.slot_peak})']
            roots = sum(1 << index for index in self.root_slots)
            allocation.append(f'  call void @rul_{prefix}frame_roots(i8* %frame, i32 {roots & 0xffffffff}, i32 {roots >> 32})')
        addresses, buffers = list(self.entry_allocations), []
        if independent:
            buffers.append('  %value_bytes = call i64 @rul_args_size(i32 1)')
            for index, address in enumerate(self.slot_addresses):
                storage = '%value_storage' + str(index)
                buffers.append(f'  {storage} = alloca i8, i64 %value_bytes, align 16')
                old = f'  {address} = call i8* @rul_slot(i8* %frame, i32 {index})'
                addresses[addresses.index(old)] = f'  {address} = call i8* @rul_local_slot(i8* %frame, i32 {index}, i8* {storage})'
        borrowed = {p for p, (_, contiguous) in self.pack_buffers.items() if independent or not contiguous}
        if borrowed:
            size = max(len(self.pack_buffers[p][0]) for p in borrowed)
            buffers.extend([f'  %argpack_bytes = call i64 @rul_args_size(i32 {size})',
                            '  %argpack = alloca i8, i64 %argpack_bytes, align 16'])
        for pointer, (values, _) in self.pack_buffers.items():
            base = '%argpack' if pointer in borrowed else values[0]
            addresses.append(f'  {pointer} = getelementptr i8, i8* {base}, i64 0')
        body = []
        for index in range(len(self.body) + 1):
            for pointer in self.pack_ends.get(index, []):
                if pointer in borrowed:
                    body.append('  call void @llvm.lifetime.end.p0i8(i64 -1, i8* %argpack)')
            for pointer in self.pack_starts.get(index, []):
                if pointer in borrowed:
                    body.append('  call void @llvm.lifetime.start.p0i8(i64 -1, i8* %argpack)')
                    body.extend(f'  call void @rul_args_set(i8* %argpack, i32 {position}, i8* {value})'
                                for position, value in enumerate(self.pack_buffers[pointer][0]))
            if index == len(self.body):
                break
            line = self.body[index]
            if independent and index in self.cleanup_sites:
                kind, limit, live = self.cleanup_sites[index]
                if kind == 'clear_count':
                    if limit == 0:
                        continue
                    mask = sum(1 << slot for slot in live if slot < limit)
                    line = (f'  call void @rul_local_clear_mask(i8* %frame, i32 {limit}, '
                            f'i32 {mask & 0xffffffff}, i32 {mask >> 32})')
                else:
                    line = line.replace('@rul_'+kind+'(', '@rul_local_'+kind+'(')
            body.append(line)
        entry = ['entry:', *self.entry_allocas, *buffers, *allocation, *addresses]
        self.bodies.append('\n'.join([signature, *entry, *body, '}']))

    def runtime_c(self):
        """Runtime plus ABI descriptors/bridges only; no user AST-to-C lowering."""
        lines = ['#define RU_ENABLE_MODULO 1', runtime_source(self.modules, '', full=True, native_plan=self.native_plan, llvm=True),
                 Path(__file__).with_name('llvm_runtime.h').read_text(encoding='utf-8')]
        if self.mi_plan:
            lines.append(self.mi_plan.bridge_source('llvm'))
        for path, ident in self.module_ids.items():
            lines.extend([f'static Env {ident}_env;', f'static int {ident}_state;',
                          f'static RuModuleFailure {ident}_failure;', f'static Val {ident}_init(void);'])
        def strings(name, values):
            if not values:
                return 'NULL'
            lines.append(f'static const char *{name}[] = {{' + ','.join(cstr(v) for v in values) + '};')
            return name
        for _, fn in self.all_functions:
            ident = self.function_ids[id(fn)]
            if self.mi_plan and id(fn) in self.mi_plan.functions:
                self.lines, self.indent = [], 0
                self.mi_plan.emit_wrapper(self, fn, ident + '_bridge')
                lines.extend(self.lines)
                entry, direct = ident + '_bridge', 'NULL'
            else:
                lines.append(f'extern void {ident}_llvm(void *, void *, int32_t, void *, void *);')
                entry, direct = 'NULL', ident + '_llvm'
            keys = strings(ident+'_names', [p[0] for p in fn.data['params']])
            types = strings(ident+'_types', [p[1] for p in fn.data['params']])
            lines.append(f'static RuFunction {ident}_descriptor = {{{cstr(fn.data["name"])}, {len(fn.data["params"])}, {keys}, {types}, {entry}, {int(fn.data["procedure"])}, {direct}}};')
        functions = ','.join('&'+self.function_ids[id(fn)]+'_descriptor' for _, fn in self.all_functions) or 'NULL'
        lines.extend([f'static RuFunction *rul_functions[] = {{{functions}}};',
                      'static RuFunction *rul_function_descriptor(int32_t id) { return rul_functions[id]; }'])
        for ident in self.type_ids.values():
            lines.append(f'static RuClass {ident};')
        for path, declarations in self.declarations.items():
            for n in declarations.values():
                if n.kind != 'type':
                    continue
                ident = self.type_ids[id(n)]
                names = strings(ident+'_names', [p[0] for p in n.data['fields']])
                types = strings(ident+'_types', [p[1] for p in n.data['fields']])
                methods = 'NULL'
                if n.data['methods']:
                    methods = ident+'_methods'
                    lines.append(f'static RuFunction *{methods}[] = {{' + ','.join('&'+self.function_ids[id(m)]+'_descriptor' for m in n.data['methods']) + '};')
                parent = self.parents[id(n)]
                parent_ref = '&'+self.type_ids[id(parent)] if parent else 'NULL'
                lines.append(f'static RuClass {ident} = {{{cstr(n.data["name"])}, {parent_ref}, &{self.module_ids[path]}_env, {len(n.data["fields"])}, {names}, {types}, {len(n.data["methods"])}, {methods}}};')
        classes = ','.join('&'+ident for ident in self.type_ids.values()) or 'NULL'
        lines.extend([f'static RuClass *rul_classes[] = {{{classes}}};',
                      'static RuClass *rul_class_descriptor(int32_t id) { return rul_classes[id]; }'])
        for path, ident in self.module_ids.items():
            builtins = 'ru_native_builtins(ru_practical_builtins())' if self.native_enabled else 'ru_practical_builtins()'
            lines.extend([f'extern void {ident}_llvm(void *, void *, int32_t, void *, void *);',
                          f'static Val {ident}_init(void) {{',
                          f'if ({ident}_state==2) return v_module(&{ident}_env);',
                          f'if ({ident}_state==3) return ru_module_failure_raise(&{ident}_failure);',
                          f'if ({ident}_state==1) ru_fail(1,"循环外言");',
                          # Match the C backend: a callback's longjmp must not
                          # strand a newly imported module in state 1.
                          *(['if (ru_native_callback_depth) ru_fail(1, "原生 C 回调中不能首次初始化外言；请在首次原生调用之前导入依赖");']
                            if self.native_enabled else []),
                          f'{ident}_state=1; const char *old=ru_source; ru_source={cstr(display_text(path))};',
                          f'env_init(&{ident}_env,{builtins}); Val out=v_null();',
                          f'{ident}_llvm(&{ident}_env,NULL,0,NULL,&out); v_drop(out);',
                          f'if (ru_panicking) {{ ru_module_failure_save(&{ident}_failure); {ident}_state=3; ru_source=old; return v_null(); }}',
                          f'{ident}_state=2; ru_source=old; return v_module(&{ident}_env); }}'])
        lines.append('static Val rul_module_import(int32_t id) { switch(id) {')
        for path, index in self.module_indices.items():
            lines.append(f'case {index}: return {self.module_ids[path]}_init();')
        lines.extend(['default: ru_fail(0,"LLVM 外言索引越界"); return v_null(); }}'])
        return '\n'.join(lines) + '\n'
