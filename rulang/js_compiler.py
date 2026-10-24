"""Direct Ru AST-to-JavaScript lowering for standalone Node.js programs.

Only runtime values and native functions are emitted, never an AST interpreter.
The existing C compiler's semantic preparation is shared by both backends.
"""
import json
import re
from pathlib import Path

from . import __version__
from .compiler import Compiler
from .diagnostics import display_text
from .frontend import Node, bind_arguments


def js(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


class JSCompiler(Compiler):
    supports_c_graphics = False

    def loc(self, node):
        return js([node.token.line, node.token.col])

    def args(self, args):
        return '[' + ','.join('[' + js(key) + ',' + self.expr(value) + ']' for key, value in args) + ']'

    def reference(self, n):
        d, loc = n.data, self.loc(n)
        if n.kind == 'name':
            if d['name'] == '读':
                self.error(n, '内置「读」暂不支持函数引用')
            return f'R.get(m,s,{js(d["name"])},{loc},true)'
        if n.kind == 'member' and not d['args']:
            return f'R.ref(m,{self.expr(d["receiver"])},{js(d["name"])},{loc})'
        return self.expr(n)

    def call(self, n, name, args):
        if name != '读' and name not in self.functions and name not in self.known_values:
            self.error(n, f'未定义函数：{name}')
        if name == '读' or name in self.functions:
            params = ['提示'] if name == '读' else [p[0] for p in self.functions[name].data['params']]
            bind_arguments(name, args, params, lambda message: self.error(n, message), optional=name == '读')
        if name == '读':
            return f'R.read(m,{self.args(args)},{self.loc(n)})'
        return f'R.call(m,R.get(m,s,{js(name)},{self.loc(n)},true),{self.args(args)},{self.loc(n)})'

    def expr(self, n):
        d, loc = n.data, self.loc(n)
        kind = n.kind
        if kind in ('number', 'string', 'fact'):
            return js(d['value'])
        if kind == 'null':
            return 'null'
        if kind == 'self':
            return f'R.get(m,s,"其",{loc},true)'
        if kind == 'name':
            if d['name'] == '读':
                return self.call(n, '读', [])
            return f'R.get(m,s,{js(d["name"])},{loc})'
        if kind == 'call':
            return self.call(n, d['name'], d['args'])
        if kind == 'function_literal':
            return self.function(n)
        if kind == 'function_ref':
            return f'R.functionRef(m,{self.reference(d["expr"])},{js(d["procedure"])},{loc})'
        if kind == 'invoke':
            if d['callee'].kind == 'name' and d['callee'].data['name'] == '读':
                return self.call(n, '读', d['args'])
            return f'R.call(m,{self.reference(d["callee"])},{self.args(d["args"])},{loc})'
        if kind == 'array':
            return '[' + ','.join(self.expr(item) for item in d['items']) + ']'
        if kind == 'map':
            entries = '[' + ','.join('[()=>'+self.expr(k)+',()=>'+self.expr(v)+']' for k,v in d['entries']) + ']'
            return f'R.map(m,{entries},{loc})'
        if kind == 'convert':
            if d['target'] not in ('数', '句', '阵', '事实'):
                self.error(n, 'JavaScript 后端不支持转换：' + d['target'])
            return f'R.convert(m,{self.expr(d["expr"])},{js(d["target"])},{loc})'
        if kind == 'unary':
            if d['op'] not in ('+', '-', '非'):
                self.error(n, 'JavaScript 后端不支持一元运算：' + d['op'])
            return f'R.unary(m,{js(d["op"])},{self.expr(d["expr"])},{loc})'
        if kind == 'binary':
            if d['op'] not in ('+', '-', '*', '/', '%', '对', '且', '或', '含', '==', '!=', '<', '<=', '>', '>='):
                self.error(n, 'JavaScript 后端不支持二元运算：' + d['op'])
            left, right = self.expr(d['left']), self.expr(d['right'])
            if d['op'] in ('且', '或'):
                op = '&&' if d['op'] == '且' else '||'
                return f'(R.truth({left}){op}R.truth({right}))'
            return f'R.binary(m,{js(d["op"])},{left},{right},{loc})'
        if kind == 'member':
            return f'R.member(m,{self.expr(d["receiver"])},{js(d["name"])},()=>{self.args(d["args"])},{loc})'
        if kind == 'index':
            return f'R.index(m,{self.expr(d["receiver"])},{self.expr(d["index"])},{loc})'
        if kind == 'slice':
            start = self.expr(d['start']) if d['start'] else 'null'
            end = self.expr(d['end']) if d['end'] else 'null'
            return f'R.slice(m,{self.expr(d["receiver"])},{start},{end},{loc})'
        if kind == 'new':
            fields = '[' + ','.join('[' + js(key) + ',()=>'+self.expr(value)+']' for key,value in d['args']) + ']'
            return f'R.new(m,s,{js(d["name"])},()=>{fields},{loc})'
        if kind == 'import':
            return self.module_ids[d['resolved']] + '()'
        self.error(n, 'JavaScript 后端不支持表达式：' + kind)

    def function(self, n):
        return f'R.fn(m,s,{js(n.data["name"])},{js(n.data["params"])},{js(n.data["procedure"])},{self.function_ids[id(n)]},{self.loc(n)})'

    def hoist(self, statements, function=False):
        for n in statements:
            if n.kind == 'function':
                self.line(f'R.declare(m,s,{self.function(n)},{self.loc(n)});')

    def block(self, statements, function=False):
        for n in statements:
            d, kind, loc = n.data, n.kind, self.loc(n)
            if kind in ('function', 'module_decl'):
                continue
            if kind == 'type':
                self.line(f'R.resolve(m.types[{js(d["name"])}]);')
            elif kind == 'scope':
                parent = self.new('scope')
                self.line(f'const {parent}=s;')
                self.line('{')
                self.indent += 1
                self.line(f'const s=R.scope({parent},"block");')
                previous_functions, previous_values = self.functions, self.known_values
                self.functions = {**self.functions, **self.local_functions(d['body'])}
                self.known_values = self.known_values | self.scope_bindings(d['body'])
                self.hoist(d['body'], function)
                # Native braces preserve the enclosing return/break target.
                self.block(d['body'], function)
                self.functions, self.known_values = previous_functions, previous_values
                self.indent -= 1
                self.line('}')
            elif kind == 'bind':
                self.line(f'R.bind(m,s,{js(d["name"])},{self.expr(d["expr"])},{loc});')
            elif kind == 'print':
                self.line(f'R.print(m,{self.expr(d["expr"])},{loc});')
            elif kind == 'expr':
                self.line(self.expr(d['expr']) + ';')
            elif kind == 'return':
                self.line('return ' + self.expr(d['expr']) + ';')
            elif kind == 'finish':
                self.line('return null;')
            elif kind == 'import_all':
                self.line(f'R.importAll(m,s,{self.expr(d["expr"])},{loc});')
            elif kind == 'assign':
                target = d['target']
                td = target.data
                receiver = self.expr(td['receiver'])
                index = self.expr(td['index']) if target.kind == 'index' else None
                if target.kind == 'member' and td['name'] == '位':
                    bound = bind_arguments('位', td['args'], ['位'], lambda message: self.error(target, message))
                    index = self.expr(bound['位'])
                if index is not None:
                    self.line(f'R.setIndex(m,{receiver},{index},()=>{self.expr(d["expr"])},{loc});')
                else:
                    self.line(f'R.setField(m,{receiver},{js(td["name"])},()=>{self.expr(d["expr"])},{loc});')
            elif kind == 'panic':
                self.line(f'R.panic(m,{self.expr(d["expr"])},{loc});')
            elif kind == 'try':
                self.line('try {')
                self.indent += 1
                self.block(d['body'], function)
                self.indent -= 1
                self.line('} catch (error) {')
                self.indent += 1
                self.line('if (!(error instanceof R.Panic)) throw error;')
                parent = self.new('scope')
                self.line(f'const {parent}=s;')
                self.line('{')
                self.indent += 1
                self.line(f'const s=R.scope({parent},"rescue");')
                self.line(f'R.bind(m,s,{js(d["reason"])},error.reason,{loc});')
                previous_functions, previous_values = self.functions, self.known_values
                self.functions = {**self.functions, **self.local_functions(d['rescue'])}
                self.known_values = self.known_values | self.scope_bindings(d['rescue']) | {d['reason']}
                self.hoist(d['rescue'], function)
                self.block(d['rescue'], function)
                self.functions, self.known_values = previous_functions, previous_values
                self.indent -= 1
                self.line('}')
                self.indent -= 1
                self.line('}')
            elif kind == 'if':
                self.line(f'if (R.truth({self.expr(d["condition"])})) {{')
                self.indent += 1
                self.block(d['yes'], function)
                self.indent -= 1
                self.line('} else {')
                self.indent += 1
                self.block(d['no'], function)
                self.indent -= 1
                self.line('}')
            elif kind == 'loop':
                if d['count'] is None:
                    self.line('for (;;) {')
                else:
                    count, index = self.new('count'), self.new('index')
                    self.line(f'const {count}=R.count(m,{self.expr(d["count"])},{loc});')
                    self.line(f'for(let {index}=0;{index}<{count};++{index}) {{')
                self.indent += 1
                self.block(d['body'], function)
                self.indent -= 1
                self.line('}')
            elif kind == 'break':
                self.line('break;')
            else:
                self.error(n, 'JavaScript 后端不支持语句：' + kind)

    def runtime(self):
        """Retain optional runtimes conservatively across the complete graph.

        Every runtime value originates in a literal, declaration, builtin name,
        or statically bundled module. Ru has no eval or dynamic member names.
        Inspect all AST data strings (including type annotations and literals),
        so aliases and dependencies cannot hide an optional builtin reference.
        Keeping an unnecessary section is harmless; missing markers fall back
        to the full runtime rather than guessing at JavaScript syntax.
        """
        runtime = Path(__file__).with_name('runtime.js').read_text(encoding='utf-8')
        display_paths = {path: display_text(path) for path in self.modules
                         if display_text(path) != path}
        if display_paths:
            # Keep RuError.source raw; only its editor-facing rendering is escaped.
            runtime = runtime.replace('error.source+', '(' + js(display_paths) + '[error.source]||error.source)+')
        if self.full_runtime:
            return runtime
        words = set()
        has_map = False
        has_diagnostics = False
        pending = list(self.modules.values())
        while pending:
            value = pending.pop()
            if isinstance(value, Node):
                has_map = has_map or value.kind == 'map'
                # Keep error detail conservatively for every possible call,
                # typed declaration, member access, and binary operation.
                has_diagnostics = has_diagnostics or value.kind in (
                    'function', 'function_literal', 'type', 'call', 'invoke', 'member', 'binary', 'new')
                pending.append(value.data)
            elif isinstance(value, dict):
                pending.extend(value.values())
            elif isinstance(value, (list, tuple)):
                pending.extend(value)
            elif isinstance(value, str):
                words.update(value.split())
        for feature, needed, handler in (
            ('IO', bool(words & {'件', '录', '件作成果', '读取', '显出', '错误'}), 'ioMember'),
            ('CONTEST', '__如竞' in words, 'contestMember'),
            ('PRACTICAL', '__实用' in words, 'practicalMember'),
        ):
            if not needed:
                pattern = r'/\* RU_OPTIONAL_' + feature + r'_BEGIN \*/.*?/\* RU_OPTIONAL_' + feature + r'_END \*/'
                replacement = '' if feature == 'PRACTICAL' else 'function ' + handler + '(){return MISSING;}'
                runtime = re.sub(pattern, replacement, runtime, count=1, flags=re.S)
                if feature == 'PRACTICAL':
                    runtime = re.sub(r'/\* RU_PRACTICAL_DISPATCH_BEGIN \*/.*?/\* RU_PRACTICAL_DISPATCH_END \*/',
                                     '', runtime, count=1, flags=re.S)
        if not has_diagnostics:
            runtime = re.sub(r'/\* RU_OPTIONAL_DIAGNOSTIC_DETAIL_BEGIN \*/.*?/\* RU_OPTIONAL_DIAGNOSTIC_DETAIL_END \*/',
                             '',
                             runtime, count=1, flags=re.S)
        runtime = re.sub(r'/\* RU_DETAIL \*/(.*?)/\* RU_END_DETAIL \*/',
                         lambda match: match[1] if has_diagnostics else '', runtime)
        if not words.intersection({'排序', '另成', '逐位'}):
            for section in ('ARRAY_ALGORITHM', 'ARRAY_ALGORITHM_DISPATCH'):
                runtime = re.sub(r'/\* RU_OPTIONAL_' + section + r'_BEGIN \*/.*?/\* RU_OPTIONAL_' + section + r'_END \*/',
                                 '', runtime, count=1, flags=re.S)
        if not words.intersection({'删', '弹', '查'}):
            runtime = re.sub(r'/\* RU_OPTIONAL_ARRAY_EDIT_BEGIN \*/.*?/\* RU_OPTIONAL_ARRAY_EDIT_END \*/',
                             '', runtime, count=1, flags=re.S)
        if not has_map:
            runtime = re.sub(r'/\* RU_OPTIONAL_MAP_INDEX_BEGIN \*/.*?/\* RU_OPTIONAL_MAP_INDEX_END \*/',
                             '', runtime, count=1, flags=re.S)
            runtime = re.sub(r'/\* RU_OPTIONAL_MAP_BEGIN \*/.*?/\* RU_OPTIONAL_MAP_END \*/',
                             'function map(){throw new Error("map runtime unavailable");} function mapMember(){return MISSING;}',
                             runtime, count=1, flags=re.S)
        return runtime

    def source_label(self, path):
        return path

    def emit_entry(self):
        self.line("try {")
        self.line(f"const root={self.module_ids[self.root]}();")
        if self.entry:
            self.line("process.exitCode=R.entry(root,process.argv.slice(2));")
        self.line("} catch(error) { R.finish(error); }")

    def compile(self):
        self.lines, self.indent = [], 0
        self.line(f'// Generated by ru {__version__}. Standalone Node.js; no source AST.')
        self.line('"use strict";')
        self.line(self.runtime())
        for path, fn in self.all_functions:
            self.current_path, self.functions = path, self._functions(path, fn)
            self.known_values = self._values(path, fn)
            self.line(f'function {self.function_ids[id(fn)]}(s,self) {{')
            self.indent += 1
            self.line(f'const m={self.module_ids[path]}_module;')
            self.hoist(fn.data['body'], True)
            self.block(fn.data['body'], True)
            self.line('return R.NO_RETURN;')
            self.indent -= 1
            self.line('}')
        for path, program in self.modules.items():
            ident = self.module_ids[path]
            self.current_path, self.functions = path, self._functions(path)
            self.known_values = self._values(path)
            self.line(f'const {ident}_module=R.module({js(self.source_label(path))});')
            self.line(f'let {ident}_state=0,{ident}_error;')
            self.line(f'function {ident}() {{')
            self.indent += 1
            self.line(f'const m={ident}_module,s=m.scope;')
            self.line(f'if({ident}_state===2)return m;')
            self.line(f'if({ident}_state===3)throw {ident}_error;')
            self.line(f'if({ident}_state===1)throw new Error("循环外言");')
            self.line(f'{ident}_state=1;')
            self.line('try {')
            self.indent += 1
            self.hoist(program)
            for n in program:
                if n.kind == 'type':
                    d = n.data
                    methods = '[' + ','.join('['+','.join([js(method.data['name']), js(method.data['params']), js(method.data['procedure']), self.function_ids[id(method)], self.loc(method)])+']' for method in d['methods']) + ']'
                    self.line(f'R.type(m,{js(d["name"])},{js(d["parent"])},{js(d["fields"])},{methods},{self.loc(n)});')
            self.block(program)
            self.line(f'{ident}_state=2;return m;')
            self.indent -= 1
            self.line(f'}} catch(error) {{ {ident}_state=3;{ident}_error=error;throw error; }}')
            self.indent -= 1
            self.line('}')
        self.emit_entry()
        return '\n'.join(self.lines) + '\n'
