"""Checked Mi IR -> LLVM 14. Private pointer/scalar ABI, no C body lowering.

The caller checks ordinary values and owns any synchronous readonly borrow.
The kernel writes [status, value, line, col] to four u32 output slots. Views
cross as a data pointer plus u32 length; no C aggregate ABI or Val layout leaks.
"""
from .mi_ir import LIMITS, VIEW, validate


def lower(ir, symbol='ru_mi_kernel'):
    env = validate(ir)
    if not symbol.isascii() or not symbol.isidentifier():
        raise ValueError('非法生成符号')
    emitter = Emitter(ir, env)
    return emitter.run(symbol)


class Emitter:
    def __init__(self, ir, env):
        self.ir, self.env = ir, env
        self.lines, self.allocations, self.loops = [], [], []
        self.serial, self.terminated, self.current = 0, False, 'entry'
        self.names = {n: f'%p{i}' for i, n in enumerate(ir['params'])}
        self.locals = {n: f'%l{i}' for i, n in enumerate(ir['locals'])}

    def fresh(self, prefix='t'):
        self.serial += 1
        return prefix + str(self.serial)

    def emit(self, text): self.lines.append('  ' + text)

    def value(self, text):
        name = '%' + self.fresh()
        self.emit(f'{name} = {text}')
        return name

    def label(self, name):
        self.lines.append(name + ':')
        self.current, self.terminated = name, False

    def jump(self, name):
        self.emit(f'br label %{name}')
        self.terminated = True

    @staticmethod
    def typ(t): return {'u8': 'i8', 'u32': 'i32', 'fact': 'i1'}[t]

    def finish(self, status, value='0', location=(0, 0)):
        for i, v in enumerate((str(status), value, *map(str, location))):
            pointer = self.value(f'getelementptr i32, i32* %out, i32 {i}')
            self.emit(f'store i32 {v}, i32* {pointer}, align 4')
        self.emit('ret void')
        self.terminated = True

    def check(self, invalid, status, location):
        fail, valid = self.fresh('fail'), self.fresh('valid')
        self.emit(f'br i1 {invalid}, label %{fail}, label %{valid}')
        self.label(fail); self.finish(status, location=location)
        self.label(valid)

    def expr(self, e, location=(0, 0)):
        op, *a = e
        if op == 'at': return self.expr(a[2], (a[0], a[1]))
        if op == 'const':
            return str(int(a[1])), a[0]
        if op == 'var':
            name, t = a[0], self.env[a[0]]
            if name in self.locals:
                ty = self.typ(t)
                return self.value(f'load {ty}, {ty}* {self.locals[name]}'), t
            return self.names[name], t
        if op == 'length':
            view, _ = self.expr(a[0])
            return view + '_length', 'u32'
        if op == 'load':
            view, _ = self.expr(a[0]); index, _ = self.expr(a[1])
            invalid = self.value(f'icmp uge i32 {index}, {view}_length')
            self.check(invalid, 1, location)
            wide = self.value(f'zext i32 {index} to i64')
            pointer = self.value(f'getelementptr i8, i8* {view}, i64 {wide}')
            return self.value(f'load i8, i8* {pointer}, align 1'), 'u8'
        if op in ('truth', 'not'):
            value, t = self.expr(a[0])
            # Even a discarded checked numeric operand must be evaluated. All
            # ordinary Ru numbers, including zero, are true.
            if t != 'fact': value = '1'
            return (self.value(f'xor i1 {value}, true') if op == 'not' else value), 'fact'
        left, t = self.expr(a[0])
        if op in ('and', 'or'):
            before = self.current
            right_label, done = self.fresh('rhs'), self.fresh('logic')
            yes, no = (right_label, done) if op == 'and' else (done, right_label)
            self.emit(f'br i1 {left}, label %{yes}, label %{no}')
            self.label(right_label)
            right, _ = self.expr(a[1]); after = self.current
            self.jump(done); self.label(done)
            return self.value(f'phi i1 [{left}, %{before}], [{right}, %{after}]'), 'fact'
        right, _ = self.expr(a[1]); ty = self.typ(t)
        if op in ('add', 'sub'):
            if op == 'add':
                room = self.value(f'sub {ty} {LIMITS[t]}, {left}')
                invalid = self.value(f'icmp ugt {ty} {right}, {room}')
            else: invalid = self.value(f'icmp ult {ty} {left}, {right}')
            self.check(invalid, 2, location)
            return self.value(f'{op} {ty} {left}, {right}'), t
        predicate = {'eq': 'eq', 'ne': 'ne', 'lt': 'ult', 'le': 'ule', 'gt': 'ugt', 'ge': 'uge'}[op]
        return self.value(f'icmp {predicate} {ty} {left}, {right}'), 'fact'

    def body(self, stmts):
        for op, *a in stmts:
            if self.terminated: break
            if op == 'set':
                value, t = self.expr(a[1]); ty = self.typ(t)
                self.emit(f'store {ty} {value}, {ty}* {self.locals[a[0]]}')
            elif op == 'return':
                value, t = self.expr(a[0])
                if t == 'u8': value = self.value(f'zext i8 {value} to i32')
                self.finish(0, value)
            elif op == 'break': self.jump(self.loops[-1])
            elif op == 'if':
                value, _ = self.expr(a[0])
                yes, no, done = self.fresh('yes'), self.fresh('no'), self.fresh('endif')
                self.emit(f'br i1 {value}, label %{yes}, label %{no}')
                self.label(yes); self.body(a[1]); yes_terminated = self.terminated
                if not self.terminated: self.jump(done)
                self.label(no); self.body(a[2]); no_terminated = self.terminated
                if not self.terminated: self.jump(done)
                if yes_terminated and no_terminated: self.terminated = True
                else: self.label(done)
            elif op == 'repeat':
                count, _ = self.expr(a[0])
                slot = '%' + self.fresh('counter')
                self.allocations.append(f'  {slot} = alloca i32')
                self.emit(f'store i32 0, i32* {slot}')
                test, loop, step, done = (self.fresh(p) for p in ('test', 'loop', 'step', 'endloop'))
                self.jump(test); self.label(test)
                index = self.value(f'load i32, i32* {slot}')
                condition = self.value(f'icmp ult i32 {index}, {count}')
                self.emit(f'br i1 {condition}, label %{loop}, label %{done}')
                self.label(loop); self.loops.append(done); self.body(a[1]); self.loops.pop()
                if not self.terminated:
                    self.jump(step); self.label(step)
                    next_index = self.value(f'add i32 {index}, 1')
                    self.emit(f'store i32 {next_index}, i32* {slot}'); self.jump(test)
                self.label(done)

    def run(self, symbol):
        params, conversions = ['i32* %out'], []
        for n, t in self.ir['params'].items():
            name = self.names[n]
            if t == VIEW: params.extend((f'i8* {name}', f'i32 {name}_length'))
            else:
                params.append(f'i32 {name}_arg')
                if t == 'u8': conversions.append(f'  {name} = trunc i32 {name}_arg to i8')
                else: self.names[n] = name + '_arg'
        for n, t in self.ir['locals'].items():
            ty = self.typ(t); slot = self.locals[n]
            self.allocations.extend((f'  {slot} = alloca {ty}', f'  store {ty} 0, {ty}* {slot}'))
        self.body(self.ir['body'])
        return '\n'.join([f'define void @{symbol}_llvm({", ".join(params)}) {{', 'entry:',
                          *self.allocations, *conversions, *self.lines, '}'])


def c_adapter(ir, symbol):
    """Only an ABI adapter: computation and checks are emitted as LLVM above."""
    params, arguments, abi = [], ['out'], ['uint32_t *']
    for i, t in enumerate(ir['params'].values()):
        name = f'p{i}'
        if t == VIEW:
            params.append(f'RuMiView {name}')
            arguments.extend((name + '.data', name + '.length'))
            abi.extend(('const uint8_t *', 'uint32_t'))
        else:
            params.append(f'uint32_t {name}'); arguments.append(name); abi.append('uint32_t')
    return (f'extern void {symbol}_llvm({", ".join(abi)});\n'
            f'static RuMiResult {symbol}({", ".join(params) or "void"}) {{\n'
            f'    uint32_t out[4]; {symbol}_llvm({", ".join(arguments)});\n'
            '    return (RuMiResult){(int)out[0], out[1], out[2], out[3]};\n}')
