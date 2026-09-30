"""Command-line entry point, native compilation and incremental REPL."""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
from . import __version__
from .compiler import Compiler
from .frontend import Incomplete, RuError, parse, validate
from .interpreter import Interpreter
from .io_runtime import read_stream_line
from .modules import load_module_graph, read_source, reject_generation_document
from .generation import generate


def report(error, name, source=""):
    name = getattr(error, "source_name", name)
    source = getattr(error, "source_text", "") or source
    print(f"{name}:{error.line}:{error.col}: {error.category}：{error.message}", file=sys.stderr)
    lines = [] if getattr(error, "suppress_source", False) else source.splitlines()
    if 0 < error.line <= len(lines):
        print("  " + lines[error.line-1], file=sys.stderr)


def build(program, source_path, output, cc=None, emit_c=None, modules=None):
    source_path = Path(source_path).resolve()
    modules = load_module_graph(source_path, program) if modules is None else modules
    output = Path(output).resolve()
    source_paths = {Path(path).resolve() for path in modules} | {source_path}
    if output in source_paths:
        raise RuError("输出路径不能覆盖源文件或外言依赖", category="编译错误")
    if emit_c:
        cpath = Path(emit_c).resolve()
        if cpath in source_paths or cpath == output:
            raise RuError("C 输出、程序输出、源文件及外言依赖必须使用不同路径", category="编译错误")
    generated = Compiler(program, str(source_path), modules=modules).compile()
    if emit_c:
        cpath.parent.mkdir(parents=True, exist_ok=True)
        cpath.write_text(generated, encoding="utf-8")
    selected = cc or os.environ.get("CC")
    command = shlex.split(selected) if selected else None
    if not command:
        found = next((shutil.which(c) for c in ("clang", "gcc", "cc") if shutil.which(c)), None)
        if not found:
            raise RuError("未找到 C 编译器。请安装 Clang/GCC，或用 --cc 指定路径；REPL 和 ru run 不需要 C 编译器。", category="编译错误")
        command = [found]
    output.parent.mkdir(parents=True, exist_ok=True)
    # Compile beside the destination, then replace atomically only on success.
    with tempfile.TemporaryDirectory(prefix=".ru-build-", dir=output.parent) as temp:
        temp = Path(temp)
        cfile, binary = temp / "program.c", temp / ("program.exe" if os.name == "nt" else "program")
        cfile.write_text(generated, encoding="utf-8")
        invocation = command + ["-std=c99", "-O2", "-Wall", "-Wextra", "-Wno-unused-function", str(cfile), "-o", str(binary), "-lm"]
        try:
            completed = subprocess.run(invocation, capture_output=True, text=True, timeout=120)
        except FileNotFoundError:
            raise RuError(f"找不到编译器：{command[0]}", category="编译错误") from None
        except subprocess.TimeoutExpired:
            raise RuError("C 编译超过 120 秒，已停止", category="编译错误") from None
        if completed.returncode:
            raise RuError("C 编译器失败：\n" + completed.stderr.strip(), category="编译错误")
        os.replace(binary, output)
    return output, command[0]


def repl():
    try:
        interactive = sys.stdin.isatty()
    except (OSError, ValueError):
        report(RuError("输入失败：无法读取标准输入", category="运行错误"), "<repl>")
        return 1
    if interactive:
        print(f"如 {__version__} · 语句以 . 结束 · :help 查看帮助 · :quit 退出")
    interpreter, pending = Interpreter(), ""
    while True:
        try:
            if interactive:
                print("… " if pending else "如> ", end="", flush=True)
            line = read_stream_line(sys.stdin)
            if not line:
                if pending.strip():
                    try:
                        parse(pending)
                    except RuError as error:
                        report(error, "<repl>", pending)
                        return 1
                return 0
            if not pending and line.strip().startswith(":"):
                command = line.strip()
                if command in (":quit", ":q", ":exit"):
                    return 0
                if command == ":reset":
                    interpreter = Interpreter()
                    if interactive:
                        print("已清空变量与函数")
                elif command == ":help":
                    print("显 ‘你好’. | 数值 取 3. | 数值 + 4.\n支持多行块；:reset 清空状态；:quit 退出；Ctrl-C 取消当前输入／执行")
                else:
                    print("未知命令；输入 :help", file=sys.stderr)
                continue
            pending += line
            reject_generation_document(pending)
            try:
                program = parse(pending)
            except Incomplete:
                continue
            interpreter.execute(program, echo=True)
            pending = ""
        except RuError as error:
            report(error, "<repl>", pending)
            pending = ""
        except RecursionError:
            report(RuError("表达式或语句结构过深，请拆分为较小的步骤"), "<repl>")
            pending = ""
        except (OSError, UnicodeError, ValueError) as error:
            report(RuError("输入失败：无法读取有效 UTF-8 输入", category="运行错误"), "<repl>")
            pending = ""
            # A rejected decoded line has been consumed; broken/closed streams
            # have not progressed and must stop rather than spin forever.
            if not getattr(error, "input_line_consumed", isinstance(error, UnicodeError)):
                return 1
        except KeyboardInterrupt:
            print("\n已取消当前输入／执行", file=sys.stderr)
            pending = ""


def make_parser():
    parser = argparse.ArgumentParser(prog="ru", description=f"如 {__version__}：中文关键词语言，带 REPL 与 C99 原生编译后端")
    parser.add_argument("--version", action="version", version=f"如 {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("repl", help="启动保留状态的多行 REPL")
    for name, help_text in (("run", "解释执行 .ru 文件"), ("check", "检查语法与函数调用")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("source")
        if name == "run":
            p.add_argument("args", nargs=argparse.REMAINDER, help="传给元初的外参；可使用 -- 分隔")
    p = sub.add_parser("build", help="把源码编译成真正独立的原生程序")
    p.add_argument("source")
    p.add_argument("-o", "--output", help="输出路径；默认去掉源文件扩展名")
    p.add_argument("--cc", help="C 编译器（默认依次查找 clang、gcc、cc；也支持 CC 环境变量）")
    p.add_argument("--emit-c", metavar="PATH", help="额外保存可审阅的独立 C99 源码")
    p = sub.add_parser("generate", help="显式发送意图文档至 Responses API，检查并保存源码（不执行）")
    p.add_argument("document")
    p.add_argument("-o", "--output", help="新建 .ru 输出文件，默认 *.generated.ru；不覆盖已有文件")
    p.add_argument("--timeout", type=float, default=60.0, help="连接／读取超时秒数，默认 60，最大 300；不自动重试")
    return parser


def main(argv=None):
    # Keep UTF-8 source/output usable in terminals whose system locale differs.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.command in (None, "repl"):
        return repl()
    source, name = "", getattr(args, "source", getattr(args, "document", "<输入>"))
    try:
        if args.command == "generate":
            result = generate(args.document, args.output, args.timeout)
            print(f"已生成并检查：{result}\n未执行；请先审阅源码，再使用 ru run 或 ru build。")
            return 0
        source = read_source(args.source)
        program = parse(source)
        modules = load_module_graph(args.source, program)
        modules.sources[modules.root] = source
        if args.command == "run":
            interpreter = Interpreter()
            interpreter.execute(program, source_path=modules.root, modules=modules)
            # argparse already consumes the optional separator. A second --
            # is an actual program argument and must be preserved.
            return interpreter.execute_entry(args.args)
        elif args.command == "check":
            Compiler(program, modules.root, modules=modules).compile()
            print(f"检查通过：{name}")
        elif args.command == "build":
            output = args.output or str(Path(args.source).with_suffix("")) + (".exe" if os.name == "nt" else "")
            result, compiler = build(program, args.source, output, args.cc, args.emit_c, modules=modules)
            print(f"已编译：{result}\nC 编译器：{compiler}")
        return 0
    except RuError as error:
        report(error, name, source)
        return 1
    except RecursionError:
        report(RuError("表达式或语句结构过深，请拆分为较小的步骤"), name)
        return 1
    except (OSError, UnicodeError) as error:
        print(f"ru: 文件／编码错误：{error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
