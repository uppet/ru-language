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

GENERATION_MARKER = "如是我言"


def report(error, name, source=""):
    print(f"{name}:{error.line}:{error.col}: {error.category}：{error.message}", file=sys.stderr)
    lines = source.splitlines()
    if 0 < error.line <= len(lines):
        print("  " + lines[error.line-1], file=sys.stderr)


def read_source(path):
    source = Path(path).read_text(encoding="utf-8-sig")
    if source.rstrip().endswith(GENERATION_MARKER):
        raise RuError("检测到以「如是我言」结尾的意图文档。LLM 生成入口尚未连接提供方；未发送文档，也未生成或执行代码。请先手写 .ru 源码。", category="生成功能未配置")
    return source


def build(program, source_path, output, cc=None, emit_c=None):
    generated = Compiler(program, str(source_path)).compile()
    output = Path(output).resolve()
    source_path = Path(source_path).resolve()
    if output == source_path:
        raise RuError("输出路径不能覆盖源文件", category="编译错误")
    if emit_c:
        cpath = Path(emit_c).resolve()
        if cpath in (source_path, output):
            raise RuError("C 输出、程序输出、源文件必须使用不同路径", category="编译错误")
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
    interactive = sys.stdin.isatty()
    if interactive:
        print("如 0.1.0 · 语句以 . 结束 · :help 查看帮助 · :quit 退出")
    interpreter, pending = Interpreter(), ""
    while True:
        try:
            if interactive:
                print("… " if pending else "如> ", end="", flush=True)
            line = sys.stdin.readline()
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
            if pending.rstrip().endswith(GENERATION_MARKER):
                raise RuError("LLM 生成入口尚未连接；文档没有发送到外部", category="生成功能未配置")
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
        except KeyboardInterrupt:
            print("\n已取消当前输入／执行", file=sys.stderr)
            pending = ""


def make_parser():
    parser = argparse.ArgumentParser(prog="ru", description="如 0.1：中文关键词玩具语言，带 REPL 与 C99 原生编译后端")
    parser.add_argument("--version", action="version", version=f"如 {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("repl", help="启动保留状态的多行 REPL")
    for name, help_text in (("run", "解释执行 .ru 文件"), ("check", "检查语法与函数调用")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("source")
    p = sub.add_parser("build", help="把源码编译成真正独立的原生程序")
    p.add_argument("source")
    p.add_argument("-o", "--output", help="输出路径；默认去掉源文件扩展名")
    p.add_argument("--cc", help="C 编译器（默认依次查找 clang、gcc、cc；也支持 CC 环境变量）")
    p.add_argument("--emit-c", metavar="PATH", help="额外保存可审阅的独立 C99 源码")
    p = sub.add_parser("generate", help="检查意图文档入口（尚未连接 LLM）")
    p.add_argument("document")
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
            source = Path(args.document).read_text(encoding="utf-8-sig")
            if not source.rstrip().endswith(GENERATION_MARKER):
                raise RuError("意图文档应以「如是我言」结尾", category="生成输入错误")
            raise RuError("已识别意图文档，但尚未连接 LLM 提供方；没有发送文档、生成代码或执行代码。", category="生成功能未配置")
        source = read_source(args.source)
        program = parse(source)
        validate(program)
        if args.command == "run":
            Interpreter().execute(program)
        elif args.command == "check":
            Compiler(program, name).compile()
            print(f"检查通过：{name}")
        elif args.command == "build":
            output = args.output or str(Path(args.source).with_suffix("")) + (".exe" if os.name == "nt" else "")
            result, compiler = build(program, args.source, output, args.cc, args.emit_c)
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
