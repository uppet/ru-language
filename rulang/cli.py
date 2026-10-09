"""Command-line entry point, C/JavaScript compilation and incremental REPL."""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from . import __version__
from .compiler import Compiler
from .frontend import Incomplete, RuError, parse, validate
from .interpreter import Interpreter
from .io_runtime import read_stream_line
from .modules import load_module_graph, read_source, reject_generation_document
from .generation import DEFAULT_TIMEOUT, generate


class _GenerationProgress:
    """Only fixed local stages and elapsed times may enter verbose output."""
    INTERVAL = 10.0
    STAGES = frozenset((
        "读取意图文档", "检查生成配置", "发送生成请求", "等待提供方响应",
        "收到提供方响应", "检查生成源码", "生成源码检查完成", "发布生成文件",
    ))

    def __init__(self, enabled):
        self.enabled = enabled
        self.stream = sys.stderr
        self.started = time.monotonic()
        self.stage_started = self.started
        self.current_stage = None
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.thread = None

    def __enter__(self):
        if self.enabled:
            self.thread = threading.Thread(
                target=self._wait_updates, name="ru-generate-progress", daemon=True,
            )
            self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join()

    def _write(self, message, now):
        try:
            print(f"[生成 {max(0, now - self.started):.1f}s] {message}",
                  file=self.stream, flush=True)
        except (OSError, UnicodeError, ValueError):
            # A closed diagnostic stream must neither leak an exception nor
            # turn a successful paid request into an apparent request failure.
            self.stopped.set()

    def stage(self, stage):
        # Defense in depth: never display provider text, config, or a URL even
        # if a future caller accidentally passes it as a progress message.
        if not self.enabled or not isinstance(stage, str) or stage not in self.STAGES:
            return
        with self.lock:
            if self.stopped.is_set():
                return
            now = time.monotonic()
            self.current_stage = stage
            self.stage_started = now
            self._write(stage, now)

    def _wait_updates(self):
        while not self.stopped.wait(self.INTERVAL):
            with self.lock:
                if self.stopped.is_set():
                    return
                if self.current_stage == "等待提供方响应":
                    now = time.monotonic()
                    waited = max(0, now - self.stage_started)
                    self._write(f"等待提供方响应（已等待 {waited:.1f}s）", now)


def report(error, name, source=""):
    name = getattr(error, "source_name", name)
    source = getattr(error, "source_text", "") or source
    print(f"{name}:{error.line}:{error.col}: {error.category}：{error.message}", file=sys.stderr)
    lines = [] if getattr(error, "suppress_source", False) else source.splitlines()
    if 0 < error.line <= len(lines):
        print("  " + lines[error.line-1], file=sys.stderr)


def compiler_command(selected, windows=None):
    """Accept an executable path verbatim, or a quoted compiler command."""
    if os.path.isfile(selected):
        return [selected]
    windows = os.name == "nt" if windows is None else windows
    try:
        parts = shlex.split(selected, posix=not windows)
    except ValueError as error:
        raise RuError("编译器命令引号不完整", category="编译错误") from error
    if windows:
        parts = [part[1:-1] if len(part) >= 2 and part[0] == part[-1] and part[0] in "\"'" else part for part in parts]
    return parts


def build(program, source_path, output, cc=None, emit_c=None, modules=None, target="c", full_runtime=False):
    if target not in ("c", "js"):
        raise RuError("编译目标须为 c 或 js", category="编译错误")
    if target == "js" and (cc is not None or emit_c is not None):
        raise RuError("JavaScript 目标不能使用 --cc 或 --emit-c", category="编译错误")
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
    if target == "js":
        from .js_compiler import JSCompiler
        generated = JSCompiler(program, str(source_path), modules=modules, full_runtime=full_runtime).compile()
        output.parent.mkdir(parents=True, exist_ok=True)
        # Generation does not invoke Node or run user code. Publish only the
        # complete artifact, preserving any previous output on compile failure.
        with tempfile.TemporaryDirectory(prefix=".ru-build-", dir=output.parent) as temp:
            script = Path(temp) / "program.js"
            with script.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(generated)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(script, output)
        return output, "JavaScript (Node.js)"
    generated = Compiler(program, str(source_path), modules=modules, full_runtime=full_runtime).compile()
    if emit_c:
        cpath.parent.mkdir(parents=True, exist_ok=True)
        cpath.write_text(generated, encoding="utf-8")
    selected = cc or os.environ.get("CC")
    command = compiler_command(selected) if selected else None
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
        print(f"如 {__version__} · 元初实现 · 语句以 . 结束 · :help 查看帮助 · :退 / :quit 退出")
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
                if command in (":退", ":quit", ":q", ":exit"):
                    return 0
                if command == ":reset":
                    interpreter = Interpreter()
                    if interactive:
                        print("已清空变量与函数")
                elif command == ":help":
                    print("显 ‘你好’. | 数值 取 3. | 数值 + 4.\n支持多行块；:reset 清空状态；:退 / :quit / :q / :exit 退出（命令不加句点）；Ctrl-C 取消当前输入／执行")
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
    parser = argparse.ArgumentParser(prog="ru", description=f"如 {__version__}：中文关键词语言，带 REPL、C99 原生与 JavaScript 编译后端")
    parser.add_argument("--version", action="version", version=f"如 {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("repl", help="启动保留状态的多行 REPL")
    for name, help_text in (("run", "解释执行 .ru 文件"), ("check", "检查语法与函数调用")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("source")
        if name == "run":
            p.add_argument("args", nargs=argparse.REMAINDER, help="传给元初的外参；可使用 -- 分隔")
    p = sub.add_parser("build", help="编译为独立原生程序或 Node.js JavaScript")
    p.add_argument("source")
    p.add_argument("-o", "--output", help="输出路径；C 默认去掉源文件扩展名，JS 默认为同名 .js")
    p.add_argument("--target", choices=("c", "js"), default="c", help="编译目标：c（默认）或 js（Node.js）")
    p.add_argument("--cc", help="C 编译器（默认依次查找 clang、gcc、cc；也支持 CC 环境变量）")
    p.add_argument("--emit-c", metavar="PATH", help="额外保存可审阅的独立 C99 源码")
    p.add_argument("--full-runtime", action="store_true", help="保留完整运行时及已导入标准库声明，供诊断对比")
    p = sub.add_parser("generate", help="显式发送意图文档至 Responses API，检查并保存源码（默认不执行）")
    p.add_argument("document")
    destination = p.add_mutually_exclusive_group()
    destination.add_argument("--stdout", action="store_true", help="将完整检查后的源码写入标准输出，不创建输出文件；诊断写入标准错误")
    destination.add_argument("-o", "--output", help="新建输出文件：ru 目标须为 .ru，js 目标须为 .js 或 .cjs；默认不覆盖，--force 可替换普通产物")
    p.add_argument("--force", action="store_true", help="检查成功后原子替换已有的普通输出文件；不覆盖意图、依赖或符号链接，不能与 --stdout 同用")
    p.add_argument("--run", action="store_true", help="生成、检查并保存成功后立即运行；ru 使用解释器，js 使用 Node.js；不能与 --stdout 同用")
    p.add_argument("--target", choices=("ru", "js"), default="ru", help="保存检查后的 ru 源码（默认），或将其本地编译为 js；默认不执行")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="连接／读取超时秒数，默认 1800（半小时）；须为有限正数，无固定上限，不自动重试")
    p.add_argument("--verbose", action="store_true", help="在标准错误显示真实生成阶段及耗时；等待响应时约每 10 秒更新，不显示进度百分比、密钥或通信原文")
    return parser


def main(argv=None):
    # Keep UTF-8 source/output usable in terminals whose system locale differs.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.command == "generate" and args.force and args.stdout:
        parser.error("--force 不能与 --stdout 同时使用")
    if args.command == "generate" and args.run and args.stdout:
        parser.error("--run 不能与 --stdout 同时使用")
    if args.command == "build" and args.target == "js" and (args.cc is not None or args.emit_c is not None):
        parser.error("--target js 不能使用 --cc 或 --emit-c")
    if args.command in (None, "repl"):
        return repl()
    source, name = "", getattr(args, "source", getattr(args, "document", "<输入>"))
    try:
        if args.command == "generate":
            node = None
            if args.run and args.target == "js":
                node = shutil.which("node")
                if node is None:
                    raise RuError("未找到 Node.js（node）；--target js --run 需要 Node.js。请安装并加入 PATH；未发送生成请求。", category="运行错误")
            with _GenerationProgress(args.verbose) as progress:
                result = generate(args.document, args.output, args.timeout, target=args.target,
                                  stdout=args.stdout, progress=progress.stage if args.verbose else None,
                                  **({"force": True} if args.force else {}))
            if args.stdout:
                sys.stdout.write(result)
                print("已生成并检查；未执行，请先审阅源码。", file=sys.stderr)
                return 0
            if args.run:
                # Publish first, then run exactly that artifact. Execution uses
                # normal streams and may fail without removing the saved file.
                name = str(result)
                if args.target == "js":
                    print(f"已生成、检查并编译：{result}\n正在使用 Node.js 运行。", file=sys.stderr, flush=True)
                    try:
                        return subprocess.run([node, str(result)]).returncode
                    except OSError:
                        raise RuError("无法启动 Node.js；请检查 node 是否仍可执行。生成文件已保留。", category="运行错误") from None
                print(f"已生成并检查：{result}\n正在运行。", file=sys.stderr, flush=True)
            elif args.target == "js":
                print(f"已生成、检查并编译：{result}\n未执行；请先审阅 JavaScript，再使用 node 运行。")
            else:
                print(f"已生成并检查：{result}\n未执行；请先审阅源码，再使用 ru run 或 ru build。")
            if not args.run:
                return 0
        source = read_source(name)
        program = parse(source)
        modules = load_module_graph(name, program)
        modules.sources[modules.root] = source
        if args.command in ("run", "generate"):
            interpreter = Interpreter()
            interpreter.execute(program, source_path=modules.root, modules=modules)
            # argparse already consumes the optional separator. A second --
            # is an actual program argument and must be preserved.
            return interpreter.execute_entry(args.args if args.command == "run" else [])
        elif args.command == "check":
            Compiler(program, modules.root, modules=modules).compile()
            print(f"检查通过：{name}")
        elif args.command == "build":
            output = args.output or (str(Path(args.source).with_suffix(".js")) if args.target == "js"
                                     else str(Path(args.source).with_suffix("")) + (".exe" if os.name == "nt" else ""))
            result, compiler = build(program, args.source, output, args.cc, args.emit_c,
                                     modules=modules, target=args.target, full_runtime=args.full_runtime)
            if args.target == "js":
                print(f"已编译：{result}\n运行目标：{compiler}；未执行")
            else:
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
