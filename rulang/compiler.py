"""Ahead-of-time lowering of every AST expression/statement to C99 code.

The output includes a small value/runtime library, not a parser or interpreter.
Each expression yields an owned Val; each generated consumer releases it.
"""
from pathlib import Path
from . import __version__
from .frontend import RuError, bind_arguments, validate


def cstr(value):
    out = []
    for byte in value.encode("utf-8"):
        if 32 <= byte <= 126 and byte not in (34, 92):
            out.append(chr(byte))
        else:
            out.append(f"\\{byte:03o}")
    return '"' + "".join(out) + '"'


class Compiler:
    def __init__(self, program, source_name="<源码>"):
        validate(program)
        self.program, self.source_name = program, source_name
        self.functions = {n.data["name"]: n for n in program if n.kind == "function"}
        self.ids = {name: f"ru_function_{i}" for i, name in enumerate(self.functions)}
        self.counter = 0
        self.lines = []
        self.indent = 0

    def line(self, text):
        self.lines.append("    " * self.indent + text)

    def new(self, prefix="v"):
        self.counter += 1
        return f"ru_{prefix}_{self.counter}"

    def temp(self, expression):
        name = self.new()
        self.line(f"Val {name} = {expression};")
        return name

    def drop(self, *names):
        for name in names:
            self.line(f"v_drop({name});")

    def error(self, n, text):
        raise RuError(text, n.token.line, n.token.col, "编译错误")

    def expr(self, n):
        d, ln = n.data, n.token.line
        if n.kind == "number":
            return self.temp(f"v_num({d['value'].hex()})")
        if n.kind == "string":
            return self.temp(f"v_str({cstr(d['value'])})")
        if n.kind == "name":
            if d["name"] in self.functions or d["name"] == "读":
                return self.call(n, d["name"], [])
            return self.temp(f"env_get(env, {cstr(d['name'])}, {ln})")
        if n.kind == "call":
            return self.call(n, d["name"], d["args"])
        if n.kind == "convert":
            arg = self.expr(d["expr"])
            out = self.temp(f"v_convert({arg}, {0 if d['target'] == '数' else 1}, {ln})")
            self.drop(arg)
            return out
        if n.kind == "unary":
            arg = self.expr(d["expr"])
            out = self.temp(f"v_unary({cstr(d['op'])}, {arg}, {ln})")
            self.drop(arg)
            return out
        if n.kind == "binary":
            left = self.expr(d["left"])
            if d["op"] in ("且", "或"):
                flag = self.new("truth")
                self.line(f"int {flag} = v_truth({left});")
                self.drop(left)
                out = self.temp(f"v_num({flag})")
                self.line(f"if ({'' if d['op'] == '且' else '!'}{flag}) {{")
                self.indent += 1
                right = self.expr(d["right"])
                self.line(f"{out} = v_num(v_truth({right}));")
                self.drop(right)
                self.indent -= 1
                self.line("}")
                return out
            right = self.expr(d["right"])
            out = self.temp(f"v_binary({cstr(d['op'])}, {left}, {right}, {ln})")
            self.drop(left, right)
            return out
        raise AssertionError(n.kind)

    def call(self, n, name, args):
        if name != "读" and name not in self.functions:
            self.error(n, f"未定义函数：{name}")
        params = ["提示"] if name == "读" else [p[0] for p in self.functions[name].data["params"]]
        bound = bind_arguments(name, args, params, lambda message: self.error(n, message), optional=name == "读")
        # The binding keeps source order. Evaluate left-to-right, then reorder
        # named arguments for the C call (C argument order is unspecified).
        values = {key: self.expr(expr) for key, expr in bound.items()}
        if name == "读":
            prompt = values.get("提示") or self.temp('v_str("")')
            out = self.temp(f"read_input({prompt}, {n.token.line})")
            self.drop(prompt)
            return out
        actuals = ["global", str(n.token.line)] + [values[key] for key in params]
        out = self.temp(f"{self.ids[name]}({', '.join(actuals)})")
        self.drop(*values.values())
        return out

    def block(self, statements, function=False):
        for n in statements:
            d = n.data
            if n.kind == "function":
                continue
            self.line(f"/* 如 source line {n.token.line}: {n.kind} */")
            if n.kind in ("bind", "print", "expr", "return"):
                value = self.expr(d["expr"])
                if n.kind == "bind":
                    self.line(f"env_set(env, {cstr(d['name'])}, {value});")
                elif n.kind == "print":
                    self.line(f"v_print({value});")
                elif n.kind == "return":
                    self.line("env_free(env);")
                    self.line("ru_leave();")
                    self.line(f"return {value};")
                    continue
                self.drop(value)
            elif n.kind == "break":
                self.line("break;")
            elif n.kind == "if":
                value = self.expr(d["condition"])
                flag = self.new("condition")
                self.line(f"int {flag} = v_truth({value});")
                self.drop(value)
                self.line(f"if ({flag}) {{")
                self.indent += 1
                self.block(d["yes"], function)
                self.indent -= 1
                self.line("} else {")
                self.indent += 1
                self.block(d["no"], function)
                self.indent -= 1
                self.line("}")
            elif n.kind == "loop":
                if d["count"] is None:
                    self.line("for (;;) {")
                else:
                    value = self.expr(d["count"])
                    count, counter = self.new("count"), self.new("index")
                    self.line(f"uint64_t {count} = v_count({value}, {n.token.line});")
                    self.drop(value)
                    self.line(f"for (uint64_t {counter} = 0; {counter} < {count}; ++{counter}) {{")
                self.indent += 1
                self.block(d["body"], function)
                self.indent -= 1
                self.line("}")

    def signature(self, name):
        params = self.functions[name].data["params"]
        return f"static Val {self.ids[name]}(Env *global, int call_line" + "".join(f", Val arg_{i}" for i in range(len(params))) + ")"

    def compile(self):
        runtime = Path(__file__).with_name("runtime.h").read_text(encoding="utf-8")
        self.line(f"/* Generated by ru {__version__}. Standalone C99; source AST is not embedded. */")
        self.line(runtime)
        for name in self.functions:
            self.line(self.signature(name) + ";")
        for name, fn in self.functions.items():
            self.line(self.signature(name) + " {")
            self.indent += 1
            self.line("ru_enter(call_line);")
            self.line("Env local; env_init(&local, global); Env *env = &local;")
            for i, (key, typ) in enumerate(fn.data["params"]):
                kind = 0 if typ == "数" else 1
                self.line(f"if (arg_{i}.kind != {kind}) ru_fail(call_line, {cstr('实参「'+key+'」须为'+typ+'，请显式使用「为 '+typ+'」转换')});")
                self.line(f"env_set(env, {cstr(key)}, arg_{i});")
            self.block(fn.data["body"], True)
            self.line("env_free(env);")
            self.line("ru_leave();")
            if not fn.data["procedure"]:
                self.line(f"ru_fail(call_line, {cstr('函数「'+name+'」没有执行「得」')});")
            self.line('return v_str("");')
            self.indent -= 1
            self.line("}")
        self.line("int main(void) {")
        self.indent += 1
        self.line(f"ru_source = {cstr(self.source_name)};")
        self.line("Env storage; env_init(&storage, NULL); Env *global = &storage; Env *env = global;")
        self.block(self.program)
        self.line("env_free(env);")
        self.line("return 0;")
        self.indent -= 1
        self.line("}")
        return "\n".join(self.lines) + "\n"
