"""LLVM 14 / Linux and Windows x86-64 AOT driver. Never executes user programs."""
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

from .frontend import RuError
from .llvm_compiler import LLVMCompiler
from .toolchain_environment import llvm_environment


def tool_error(message):
    error = RuError(message, category='LLVM 编译错误')
    error.location_known = False
    return error


def find_clang():
    if sys.platform == 'win32':
        local = Path(__file__).resolve().parents[1]/'.build_tools/llvm-14/bin/clang.exe'
        if local.is_file():
            return str(local)
    return shutil.which('clang-14') or shutil.which('clang')


class LLVMToolchain:
    """Use matching assembler, linker, optimizer, disassembler and Clang.

    M1 deliberately targets the installed, tested LLVM 14 typed-pointer dialect.
    A newer opaque-pointer dialect is a separate compatibility change, rather
    than silently passing LLVM 14 IR/bitcode between incompatible tool versions.
    """
    def __init__(self, selected=None):
        if (not (sys.platform.startswith('linux') or sys.platform == 'win32')
                or platform.machine() not in ('x86_64', 'AMD64')):
            raise tool_error('LLVM AOT 当前仅支持 Linux/Windows x86-64 本机目标；其他目标尚未验收。')
        from .cli import compiler_command
        selected = selected or os.environ.get('RU_LLVM_CLANG')
        if selected:
            self.clang = compiler_command(selected)
        else:
            found = find_clang()
            self.clang = [found] if found else []
        if not self.clang:
            raise tool_error('未找到 LLVM 14 Clang；Windows 可运行 python3 tools/prepare_workspace.py --with-llvm，'
                             'Linux 请安装 clang-14 和 llvm-14；也可用 --llvm-clang 指定路径。')
        version = self.run(self.clang + ['--version'])
        if not re.search(r'clang version 14\.', version):
            raise tool_error('LLVM AOT M1 需要 Clang/LLVM 14 的有类型指针 IR；请选择 clang-14。')
        self.version = version.splitlines()[0]
        resolved = shutil.which(self.clang[0]) or self.clang[0]
        directory = Path(resolved).resolve().parent
        self.tools = {}
        for name in ('llvm-as', 'llvm-link', 'opt', 'llvm-dis', 'llc'):
            suffix = '.exe' if sys.platform == 'win32' else ''
            candidates = [directory/(name+'-14'+suffix), directory/(name+suffix)]
            found = next((str(path) for path in candidates if path.is_file() and os.access(path, os.X_OK)), None)
            found = found or shutil.which(name+'-14')
            if not found:
                raise tool_error(f'未找到同版本工具 {name}-14；请安装完整 LLVM 14 工具链。')
            if not re.search(r'LLVM version 14\.', self.run([found, '--version'])):
                raise tool_error(f'{name} 与 Clang 不匹配；LLVM AOT M1 要求全部为 LLVM 14。')
            self.tools[name] = found
        probe = self.run(self.clang + ['-S', '-emit-llvm', '-x', 'c', '-', '-o', '-'], input='')
        triple = re.search(r'^target triple = "([^"]+)"', probe, re.M)
        layout = re.search(r'^target datalayout = "([^"]+)"', probe, re.M)
        target = r'x86_64-[\w.-]*windows-msvc[\w.-]*' if sys.platform == 'win32' else r'x86_64-[\w.-]*linux[\w.-]*'
        if not triple or not layout or 'x32' in triple[1] or not re.fullmatch(target, triple[1]):
            raise tool_error('LLVM AOT 当前仅支持 Linux/Windows x86-64 本机目标；Clang 目标与宿主不匹配。')
        self.triple, self.data_layout = triple[1], layout[1]
        self.link_flags = [] if sys.platform == 'win32' else ['-lm']

    @staticmethod
    def run(command, input=None):
        try:
            result = subprocess.run(command, input=input, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', env=llvm_environment(), timeout=120)
        except OSError as error:
            raise tool_error(f'无法启动 LLVM 工具 {command[0]}：{error}') from None
        except subprocess.TimeoutExpired:
            raise tool_error(f'LLVM 工具 {command[0]} 超过 120 秒，已停止。') from None
        if result.returncode:
            raise tool_error(f'LLVM 工具 {command[0]} 失败：\n' + (result.stderr or result.stdout).strip())
        return result.stdout

    def compile(self, program, runtime, directory, full_runtime=False):
        directory = Path(directory)
        ll, c = directory/'program.ll', directory/'runtime.c'
        ll.write_text(program, encoding='utf-8', newline='\n')
        c.write_text(runtime, encoding='utf-8', newline='\n')
        user_bc, runtime_bc = directory/'program.bc', directory/'runtime.bc'
        linked, optimized = directory/'linked.bc', directory/'optimized.bc'
        native, saved_ir = directory/'program.exe', directory/'standalone.ll'
        self.run([self.tools['llvm-as'], str(ll), '-o', str(user_bc)])
        self.run(self.clang + ['-std=c99', '-O2', '-fno-fast-math', '-ffp-contract=off',
                              '-emit-llvm', '-c', str(c), '-o', str(runtime_bc)])
        self.run([self.tools['llvm-link'], str(user_bc), str(runtime_bc), '-o', str(linked)])
        self.run([self.tools['opt'], '-verify', '-disable-output', str(linked)])
        passes = 'default<O2>' if full_runtime else 'internalize,default<O2>,globaldce'
        self.run([self.tools['opt'], '-passes='+passes, '-internalize-public-api-list=main',
                  str(linked), '-o', str(optimized)])
        self.run([self.tools['opt'], '-verify', '-disable-output', str(optimized)])
        self.run([self.tools['llvm-dis'], str(optimized), '-o', str(saved_ir)])
        # The module has already been optimized/instrumented. Clang's IR input
        # pipeline can run sanitizer passes again on runtime bitcode. llc only
        # generates the native object; Clang then performs a link-only step.
        obj = directory/'program.o'
        self.run([self.tools['llc'], '-filetype=obj', '-relocation-model=pic',
                  str(optimized), '-o', str(obj)])
        self.run(self.clang + [str(obj), '-o', str(native), *self.link_flags])
        return native, saved_ir


def build_llvm(program, source_path, output, *, modules, clang=None, emit_llvm=None,
               full_runtime=False, style_check=None):
    source_path, output = Path(source_path).resolve(), Path(output).resolve()
    source_paths = {Path(path).resolve() for path in modules} | {source_path}
    destinations = [output]
    if emit_llvm is not None:
        destinations.append(Path(emit_llvm).resolve())
    if len(set(destinations)) != len(destinations):
        raise tool_error('LLVM IR 输出和程序输出必须使用不同路径。')
    if any(path in source_paths for path in destinations):
        raise tool_error('LLVM 输出路径不能覆盖源文件或外言依赖。')
    if any(path.is_dir() for path in destinations):
        raise tool_error('LLVM 输出路径不能是目录。')
    compiler = LLVMCompiler(program, str(source_path), modules=modules, full_runtime=full_runtime)
    compiler.compile()  # Validate the entire program before starting tools.
    if style_check is not None:
        style_check()
    toolchain = LLVMToolchain(clang)
    generated = compiler.compile(toolchain.triple, toolchain.data_layout)
    runtime = compiler.runtime_c()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ru-build-', dir=output.parent) as temporary:
        native, saved_ir = toolchain.compile(generated, runtime, temporary, full_runtime=full_runtime)
        # All tools and both verifiers have succeeded before any publication.
        # Each artifact is staged on its destination filesystem, then replaced
        # atomically. Publishing multiple paths is not a filesystem transaction.
        if emit_llvm is not None:
            ir_path = destinations[1]
            ir_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.ru-build-', dir=ir_path.parent) as stage:
                staged = Path(stage)/'program.ll'
                shutil.copyfile(saved_ir, staged)
                os.replace(staged, ir_path)
        os.replace(native, output)
    return output, toolchain.version
