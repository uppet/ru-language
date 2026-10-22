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
from .diagnostics import diagnostic, display_text
from .frontend import Incomplete, RuError, parse, validate, style_issues
from .interpreter import Interpreter
from .io_runtime import read_stream_line
from .modules import load_module_graph, read_source, reject_generation_document
from .generation import DEFAULT_TIMEOUT, GenerationSummary, generate, max_output_tokens_argument
from .prompts import export_prompt


class _GenerationProgress:
    """Fixed stages and locally allowlisted, redacted summaries on stderr."""
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
        if not self.enabled or not isinstance(stage, str) or (stage not in self.STAGES and not isinstance(stage, GenerationSummary)):
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
    print(diagnostic(error, name)["formatted"], file=sys.stderr)
    lines = [] if getattr(error, "suppress_source", False) or not getattr(error, "location_known", True) else source.splitlines()
    if 0 < error.line <= len(lines):
        print("  " + display_text(lines[error.line-1]), file=sys.stderr)


def report_style(modules, *, strict=False):
    """Inspect the unpruned source graph after successful compilation/validation.

    The loader canonicalizes import identities, so repeated imports produce
    one diagnostic set. Never read files again or modify the supplied AST.
    """
    failed = False
    for path, source in modules.sources.items():
        for issue in style_issues(source):
            print(diagnostic(issue, path, severity="error" if strict else "warning")["formatted"],
                  file=sys.stderr)
            failed = True
    return failed and strict


class _StyleRejected(Exception):
    """The complete style diagnostic set has already been printed."""


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


def build(program, source_path, output, cc=None, emit_c=None, modules=None, target="c", full_runtime=False, allow_native=False, source_prefix_maps=(), style_check=None, emit_llvm=None, llvm_clang=None, mi_manifest=None, assets=None):
    if target not in ("c", "js", "llvm", "ui"):
        raise RuError("编译目标须为 c、js、llvm 或 ui", category="编译错误")
    if target != 'llvm' and (emit_llvm is not None or llvm_clang is not None):
        raise RuError('--emit-llvm 和 --llvm-clang 只适用于 LLVM 目标', category='编译错误')
    if mi_manifest and target not in ('c', 'llvm'):
        raise RuError('密实验普通桥仅支持 C／LLVM；JS 语义内核请用实验生成器', category='能力错误')
    if target == 'llvm' and (cc is not None or emit_c is not None or (allow_native and not mi_manifest)):
        raise RuError('LLVM AOT M1 不支持 --cc、--emit-c 或 --allow-native；编译器请用 --llvm-clang 指定', category='能力错误')
    if target == "ui" and (cc is not None or emit_c is not None):
        raise RuError("如UI 网页目标不能使用 --cc 或 --emit-c", category="编译错误")
    if target == "ui" and allow_native:
        raise RuError("--allow-native 只适用于 C 编译目标", category="能力错误")
    if target == "ui" and source_prefix_maps:
        raise RuError("源码路径映射只适用于 C 编译目标", category="编译错误")
    if target == "js" and (cc is not None or emit_c is not None):
        raise RuError("JavaScript 目标不能使用 --cc 或 --emit-c", category="编译错误")
    if source_prefix_maps and target != 'c':
        raise RuError('源码路径映射只适用于 C 编译目标', category='编译错误')
    if allow_native and target != "c" and not (target == 'llvm' and mi_manifest):
        raise RuError("--allow-native 只适用于本地 Windows x64 Python 运行或 C 原生编译；JavaScript 不支持", category="能力错误")
    source_path = Path(source_path).resolve()
    modules = load_module_graph(source_path, program) if modules is None else modules
    output = Path(output).resolve()
    source_paths = {Path(path).resolve() for path in modules} | {source_path}
    if mi_manifest:
        source_paths.add(Path(mi_manifest).resolve())
    if output in source_paths:
        raise RuError("输出路径不能覆盖源文件或外言依赖", category="编译错误")
    if target == 'llvm':
        from .llvm_toolchain import build_llvm
        return build_llvm(program, source_path, output, modules=modules, clang=llvm_clang,
                          emit_llvm=emit_llvm, full_runtime=full_runtime, style_check=style_check,
                          mi_manifest=mi_manifest, allow_native=allow_native)
    if emit_c:
        cpath = Path(emit_c).resolve()
        if cpath in source_paths or cpath == output:
            raise RuError("C 输出、程序输出、源文件及外言依赖必须使用不同路径", category="编译错误")
    if target == "js":
        from .js_compiler import JSCompiler
        generated = JSCompiler(program, str(source_path), modules=modules, full_runtime=full_runtime).compile()
        if style_check is not None:
            style_check()
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
    if target == "ui":
        from .app_builder import build_app_html
        generated = build_app_html(source_path.read_text(encoding="utf-8"), title=source_path.stem, assets_dir=assets)
        if style_check is not None:
            style_check()
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".ru-build-", dir=output.parent) as temp:
            page = Path(temp) / "app.html"
            with page.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(generated)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(page, output)
        return output, "如UI 网页（自包含 HTML）"
    generated = Compiler(program, str(source_path), modules=modules, full_runtime=full_runtime, allow_native=allow_native,
                         source_prefix_maps=source_prefix_maps, mi_manifest=mi_manifest).compile()
    if style_check is not None:
        style_check()
    if emit_c:
        cpath.parent.mkdir(parents=True, exist_ok=True)
        cpath.write_text(generated, encoding="utf-8")
    selected = cc or os.environ.get("CC")
    command = compiler_command(selected) if selected else None
    compiler_environment = None
    if not command:
        found = next((shutil.which(c) for c in ("clang", "gcc", "cc") if shutil.which(c)), None)
        if found is None and sys.platform == 'win32':
            from .llvm_toolchain import find_clang
            from .toolchain_environment import llvm_environment
            found = find_clang()
            compiler_environment = llvm_environment()
        if not found:
            raise RuError("未找到 C 编译器。请安装 Clang/GCC，或用 --cc 指定路径；REPL 和 ru run 不需要 C 编译器。", category="编译错误")
        command = [found]
    output.parent.mkdir(parents=True, exist_ok=True)
    # Compile beside the destination, then replace atomically only on success.
    with tempfile.TemporaryDirectory(prefix=".ru-build-", dir=output.parent) as temp:
        temp = Path(temp)
        # Use an explicit executable suffix even on a POSIX build host. MinGW
        # otherwise appends .exe to -o program, leaving no file at that path.
        # Native POSIX compilers accept this temporary name too; the published
        # destination remains exactly the path selected by the caller.
        cfile, binary = temp / "program.c", temp / "program.exe"
        cfile.write_text(generated, encoding="utf-8")
        invocation = command + ["-std=c99", "-O2", "-Wall", "-Wextra", "-Wno-unused-function", str(cfile), "-o", str(binary)]
        if sys.platform != 'win32':
            invocation.append('-lm')
        try:
            completed = subprocess.run(invocation, capture_output=True, text=True,
                                       env=compiler_environment, timeout=120)
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
            report(RuError("程序执行超出解释器资源上限（结构嵌套过深），请拆分为较小的步骤", category="运行错误"), "<repl>")
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
    parser = argparse.ArgumentParser(prog="ru", description=f"如 {__version__}：中文关键词语言，带 REPL、C99、LLVM AOT 与 JavaScript 编译后端")
    parser.add_argument("--version", action="version", version=f"如 {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("repl", help="启动保留状态的多行 REPL")
    for name, help_text in (("run", "解释执行 .ru 文件"), ("check", "检查语法与函数调用")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("source")
        if name == "check":
            p.add_argument("--strict-style", action="store_true", help="将缺少完整语句结束句点的书写提示作为错误；默认只在标准错误提示")
            p.add_argument("--target", choices=("c", "python", "llvm"), default="c", help="c（默认）或 llvm 检查可编译性；python 仅解析和验证模块，不执行代码或加载 DLL")
            p.add_argument("--allow-native", action="store_true", help="允许静态检查 Windows x64 原生 C 编译；不执行代码或加载 DLL")
        if name == "run":
            p.add_argument("--allow-native", action="store_true", help="信任本地原生代码，开启 Windows x64 ABI；须放在源文件路径之前")
            p.add_argument("args", nargs=argparse.REMAINDER, help="传给元初的外参；可使用 -- 分隔")
    p = sub.add_parser("build", help="编译为独立原生程序或 Node.js JavaScript")
    p.add_argument("source")
    p.add_argument("--strict-style", action="store_true", help="将缺少完整语句结束句点的书写提示作为错误；默认只在标准错误提示")
    p.add_argument("-o", "--output", help="输出路径；C 默认去掉源文件扩展名，JS 默认为同名 .js")
    p.add_argument("--target", choices=("c", "js", "llvm", "ui"), default="c", help="编译目标：c（默认）、js（Node.js）、llvm（LLVM 14 / Linux、Windows x86-64 AOT）或 ui（如UI 自包含网页，浏览器打开即交互）")
    p.add_argument("--assets", metavar="目录", help="仅 --target ui：内嵌资产目录，供 件目/图载/件载 以相对路径访问；图像转 data URL、文本内联、其余转 base64，总量 ≤16 MiB")
    p.add_argument("--cc", help="C 编译器（默认依次查找 clang、gcc、cc；也支持 CC 环境变量）")
    p.add_argument("--emit-c", metavar="PATH", help="额外保存可审阅的独立 C99 源码")
    p.add_argument("--emit-llvm", metavar="PATH", help="仅 LLVM：保存已链接运行时、验证并优化的独立 .ll，可由 clang-14 复编")
    p.add_argument("--experimental-mi-manifest", help="显式内部密算清单（C／LLVM 实验，不定义公开密语法）")
    p.add_argument("--llvm-clang", metavar="COMMAND", help="仅 LLVM：指定 LLVM 14 Clang（也可设置 RU_LLVM_CLANG）")
    p.add_argument("--full-runtime", action="store_true", help="保留完整运行时及已导入标准库声明，供诊断对比")
    p.add_argument("--allow-native", action="store_true", help="信任原生代码，编译含 Windows x64 ABI 的独立程序；默认关闭，产物不依赖 Python")
    p.add_argument("--source-prefix-map", action="append", default=[], metavar="OLD=NEW",
                   help="仅 C：重写产物的运行时源码路径；可重复，最长目录前缀优先，同长后者优先；不改源码正文")
    p = sub.add_parser("generate", help="显式发送意图文档至 Responses API，检查并保存源码（默认不执行）")
    p.add_argument("document")
    destination = p.add_mutually_exclusive_group()
    destination.add_argument("--stdout", action="store_true", help="将完整检查后的源码写入标准输出，不创建输出文件；诊断写入标准错误")
    destination.add_argument("-o", "--output", help="新建输出文件：ru 目标须为 .ru，js 目标须为 .js 或 .cjs；默认不覆盖，--force 可替换普通产物")
    p.add_argument("--force", action="store_true", help="检查成功后原子替换已有的普通输出文件；不覆盖意图、依赖或符号链接，不能与 --stdout 同用")
    p.add_argument("--run", action="store_true", help="生成、检查并保存成功后立即运行；ru 使用解释器，js 使用 Node.js；不能与 --stdout 同用")
    p.add_argument("--target", choices=("ru", "js"), default="ru", help="保存检查后的 ru 源码（默认），或将其本地编译为 js；默认不执行")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="连接／读取超时秒数，默认 1800（半小时）；须为有限正数，无固定上限，不自动重试")
    p.add_argument("--max-output-tokens", type=max_output_tokens_argument, help="显式输出 token 正整数预算；优先于环境与配置，默认省略并使用提供方未知默认值")
    p.add_argument("--verbose", action="store_true", help="在标准错误显示真实生成阶段及耗时；等待响应时约每 10 秒更新，不显示进度百分比、密钥或通信原文")
    for name in ("rushu-prompt", "ruguan-prompt"):
        p = sub.add_parser(name, help="离线导出当前版本的系统提示词（含完整语言规范）")
        p.add_argument("--target", choices=("python", "browser-js"), default="python", help="提示运行环境：默认 Python 代码格，或显式浏览器 JS 代码格")
        p.add_argument("-o", "--output", default="-", metavar="PATH", help="UTF-8 输出文件；省略或 - 为标准输出")
        p.add_argument("--force", action="store_true", help="原子替换已有普通文件；不可用于标准输出、符号链接或规范原文")
    p = sub.add_parser("deps", help="显式同步包依赖；普通运行／检查／编译不联网")
    commands = p.add_subparsers(dest="deps_command", required=True)
    sync = commands.add_parser("sync", help="读取集录.ru，获取依赖并原子写入集锁.json")
    sync.add_argument("directory", nargs="?", default=".")
    mode = sync.add_mutually_exclusive_group()
    mode.add_argument("--locked", action="store_true", help="要求已有 format 2 锁，精确恢复且不改锁文件")
    mode.add_argument("--update", action="store_true", help="显式重新解析引用／版本范围，并原子更新依赖锁")
    p = sub.add_parser("registry", help="静态包目录客户端与仅本地发布原型")
    commands = p.add_subparsers(dest="registry_command", required=True)
    for action in ("search", "info", "versions", "dependencies", "download"):
        command = commands.add_parser(action)
        command.add_argument("--registry", required=True, help="显式 HTTPS 目录 URL 或本地静态目录")
        if action == "search":
            command.add_argument("query", nargs="?", default="")
        else:
            command.add_argument("package")
        if action in ("dependencies", "download"):
            command.add_argument("version")
        if action == "download":
            command.add_argument("-o", "--output", required=True, help="新建已验证的归档文件；不覆盖已有文件")
    publish = commands.add_parser("publish", help="仅写本地目录；不提供网络写入或部署")
    publish.add_argument("directory", nargs="?", default=".")
    publish.add_argument("--registry", required=True, help="本地静态目录路径")
    return parser


def main(argv=None):
    # Keep UTF-8 source/output usable in terminals whose system locale differs.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.command in ("rushu-prompt", "ruguan-prompt") and args.force and args.output == "-":
        parser.error("--force 需要 -o / --output 指定实际文件")
    if args.command == "generate" and args.force and args.stdout:
        parser.error("--force 不能与 --stdout 同时使用")
    if args.command == "generate" and args.run and args.stdout:
        parser.error("--run 不能与 --stdout 同时使用")
    if args.command == "build" and args.target == "js" and (args.cc is not None or args.emit_c is not None):
        parser.error("--target js 不能使用 --cc 或 --emit-c")
    if args.command == 'build' and args.target == 'js' and args.source_prefix_map:
        parser.error('--source-prefix-map 只适用于 --target c')
    if args.command == 'build' and args.target != 'llvm' and (args.emit_llvm is not None or args.llvm_clang is not None):
        parser.error('--emit-llvm 和 --llvm-clang 只适用于 --target llvm')
    if args.command == 'build' and args.target == 'llvm' and (args.cc is not None or args.emit_c is not None or (args.allow_native and not args.experimental_mi_manifest) or args.source_prefix_map):
        parser.error('LLVM AOT M1 不支持 --cc、--emit-c、--allow-native 或 --source-prefix-map；编译器请用 --llvm-clang 指定')
    if args.command == 'build' and args.assets and args.target != 'ui':
        parser.error('--assets 只适用于 --target ui')
    if args.command in (None, "repl"):
        return repl()
    source, name = "", getattr(args, "source", getattr(args, "document", "<输入>"))
    try:
        if args.command == "deps":
            from .package_sources import sync_dependencies
            lock = sync_dependencies(args.directory, locked=args.locked, update=args.update)
            print(f"依赖同步完成：{len(lock['packages'])} 个来源包；锁定依赖已就绪")
            return 0
        if args.command == "registry":
            import json
            from .package_registry import client_for, publish_local
            from .package_sources import _error
            if args.registry_command == "publish":
                if "://" in args.registry:
                    raise _error("发布仅支持本地静态目录路径，不提供网络写入")
                result = publish_local(args.directory, args.registry)
            else:
                client = client_for(args.registry)
                action = args.registry_command
                if action == "search":
                    result = client.search(args.query)
                elif action == "info":
                    result = client.info(args.package)
                elif action == "versions":
                    result = client.versions(args.package)
                elif action == "dependencies":
                    result = client.dependencies(args.package, args.version)
                else:
                    data, result = client.download(args.package, args.version)
                    output = Path(args.output)
                    if output.exists() or output.is_symlink():
                        raise _error("下载输出已存在；请指定新的文件路径")
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(prefix=".ru-download-", dir=output.parent, delete=False) as stream:
                        temporary = Path(stream.name)
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    try:
                        # Hard-link publish is atomic and refuses a concurrent
                        # destination, unlike replace which could overwrite it.
                        os.link(temporary, output)
                    finally:
                        temporary.unlink(missing_ok=True)
                    print(f"已校验并下载：{output}")
                    return 0
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command in ("rushu-prompt", "ruguan-prompt"):
            result = export_prompt(args.command.removesuffix("-prompt"), args.output, force=args.force, runtime_target=args.target)
            if args.output == "-":
                if hasattr(sys.stdout, "reconfigure"):
                    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
                sys.stdout.write(result)
                sys.stdout.flush()
            return 0
        if args.command == "generate":
            node = None
            if args.run and args.target == "js":
                node = shutil.which("node")
                if node is None:
                    raise RuError("未找到 Node.js（node）；--target js --run 需要 Node.js。请安装并加入 PATH；未发送生成请求。", category="运行错误")
            with _GenerationProgress(args.verbose) as progress:
                result = generate(args.document, args.output, args.timeout, target=args.target,
                                  stdout=args.stdout, progress=progress.stage if args.verbose else None,
                                  **({"force": True} if args.force else {}),
                                  **({"max_output_tokens": args.max_output_tokens} if args.max_output_tokens is not None else {}))
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
        def check_style():
            if report_style(modules, strict=args.strict_style):
                raise _StyleRejected()
        if args.command in ("run", "generate"):
            interpreter = Interpreter(allow_native=args.command == "run" and args.allow_native)
            interpreter.execute(program, source_path=modules.root, modules=modules)
            # argparse already consumes the optional separator. A second --
            # is an actual program argument and must be preserved.
            return interpreter.execute_entry(args.args if args.command == "run" else [])
        elif args.command == "check":
            if args.target == "c":
                Compiler(program, modules.root, modules=modules, allow_native=args.allow_native).compile()
            elif args.target == 'llvm' and not args.allow_native:
                from .llvm_compiler import LLVMCompiler
                LLVMCompiler(program, modules.root, modules=modules).compile()
            elif args.allow_native:
                raise RuError("check --allow-native 只用于 C 目标；Python 源码检查无需授予原生能力", category="能力错误")
            check_style()
            print(f"检查通过：{name}" + ("（Python 模块语法验证；未执行代码或加载 DLL）" if args.target == "python" else ""))
        elif args.command == "build":
            output = args.output or (str(Path(args.source).with_suffix(".js")) if args.target == "js"
                                     else str(Path(args.source).with_suffix(".html")) if args.target == "ui"
                                     else str(Path(args.source).with_suffix("")) + (".exe" if os.name == "nt" else ""))
            result, compiler = build(program, args.source, output, args.cc, args.emit_c,
                                     modules=modules, target=args.target, full_runtime=args.full_runtime, allow_native=args.allow_native,
                                     source_prefix_maps=args.source_prefix_map, style_check=check_style,
                                     emit_llvm=args.emit_llvm, llvm_clang=args.llvm_clang,
                                     mi_manifest=args.experimental_mi_manifest, assets=args.assets)
            if args.target == "js":
                print(f"已编译：{result}\n运行目标：{compiler}；未执行")
            elif args.target == 'llvm':
                host = 'Windows' if sys.platform == 'win32' else 'Linux'
                print(f'已编译：{result}\nLLVM 工具链：{compiler}；{host} x86-64；未执行')
            elif args.target == "ui":
                print(f"已编译：{result}\n运行目标：{compiler}；未执行。用浏览器打开即可交互。")
            else:
                print(f"已编译：{result}\nC 编译器：{compiler}")
        return 0
    except _StyleRejected:
        return 1
    except RuError as error:
        report(error, name, source)
        return 1
    except RecursionError:
        report(RuError("程序执行超出解释器资源上限（结构嵌套过深），请拆分为较小的步骤", category="运行错误"), name)
        return 1
    except (OSError, UnicodeError) as error:
        failure = RuError(str(error), category="文件／编码错误")
        failure.location_known = False
        report(failure, name)
        return 1
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
