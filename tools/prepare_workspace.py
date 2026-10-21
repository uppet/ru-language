#!/usr/bin/env python3
"""Prepare a checkout; download project-local Windows LLVM only on request."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rulang.toolchain_environment import llvm_environment

TOOLS = ('clang', 'llvm-as', 'llvm-link', 'opt', 'llvm-dis', 'llc')
INSTALL = 'llvm-14'


class PreparationError(Exception):
    pass


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def download(package, cache):
    destination = cache / package['filename']
    if destination.is_file() and checksum(destination) == package['sha256']:
        return destination
    print('下载：' + package['filename'], flush=True)
    request = urllib.request.Request(package['url'], headers={'User-Agent': 'ru-workspace-prepare'})
    with tempfile.NamedTemporaryFile(prefix='.download-', dir=cache, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                shutil.copyfileobj(response, stream, 1024 * 1024)
        except BaseException:
            stream.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        if temporary.stat().st_size != package['size'] or checksum(temporary) != package['sha256']:
            raise PreparationError('下载文件大小或 SHA-256 不符：' + package['filename'])
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def extract_package(archive, package, destination):
    """Copy only required executables, DLLs, Clang resources and licenses."""
    with tarfile.open(archive, 'r:bz2') as bundle:
        for item in bundle:
            path = PurePosixPath(item.name)
            if path.is_absolute() or '..' in path.parts or '\\' in item.name or ':' in item.name:
                raise PreparationError('工具包含无效路径：' + item.name)
            relative = None
            if path.parts[:2] == ('Library', 'bin') and len(path.parts) == 3:
                if path.name in {name + '.exe' for name in TOOLS} or path.suffix.lower() == '.dll':
                    relative = Path('bin') / path.name
            elif path.parts[:3] == ('Library', 'lib', 'clang'):
                relative = Path(*path.parts[1:])
            elif path.parts[:2] == ('info', 'licenses'):
                relative = Path('share/licenses') / package['name'] / Path(*path.parts[2:])
            if relative is not None:
                if item.isdir():
                    continue
                if not item.isfile():
                    raise PreparationError('所需工具含不支持的链接或设备：' + item.name)
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(item) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)


def run(command, *, cwd=None):
    try:
        result = subprocess.run([str(arg) for arg in command], cwd=cwd, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', env=llvm_environment(), timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PreparationError('无法运行工具：' + str(error)) from None
    if result.returncode:
        raise PreparationError('工具执行失败：' + str(command[0]) + '\n' + (result.stderr or result.stdout))
    return result.stdout


def check_toolchain(directory):
    versions = {}
    for name in TOOLS:
        executable = directory / 'bin' / (name + '.exe')
        if not executable.is_file():
            raise PreparationError('工具包不完整：' + str(executable))
        version = run([executable, '--version'])
        marker = 'clang version 14.' if name == 'clang' else 'LLVM version 14.'
        if marker not in version:
            raise PreparationError(name + ' 不是所需的 LLVM 14')
        versions[name] = version.splitlines()[0]
    return versions


def smoke_test(directory):
    """Exercise the real Windows SDK, every LLVM stage, link and execution."""
    executable = {name: directory / 'bin' / (name + '.exe') for name in TOOLS}
    with tempfile.TemporaryDirectory(prefix='.llvm-check-', dir=directory.parent) as work:
        work = Path(work)
        (work/'main.c').write_text('#include <math.h>\n#include <stdio.h>\n#include <windows.h>\n'
                                  'int main(void) { return GetCurrentProcessId() == 0; }\n', encoding='utf-8')
        run([executable['clang'], '-std=c99', '-S', '-emit-llvm', work/'main.c', '-o', work/'main.ll'])
        run([executable['llvm-as'], work/'main.ll', '-o', work/'main.bc'])
        run([executable['llvm-link'], work/'main.bc', '-o', work/'linked.bc'])
        run([executable['opt'], '-verify', '-disable-output', work/'linked.bc'])
        run([executable['opt'], '-passes=default<O2>', work/'linked.bc', '-o', work/'opt.bc'])
        run([executable['llvm-dis'], work/'opt.bc', '-o', work/'opt.ll'])
        run([executable['llc'], '-filetype=obj', work/'opt.bc', '-o', work/'main.obj'])
        run([executable['clang'], work/'main.obj', '-o', work/'main.exe'])
        run([work/'main.exe'], cwd=work)


def prepare_llvm(workspace, manifest=None):
    workspace = Path(workspace).resolve()
    manifest = manifest or json.loads((ROOT/'tools/llvm-windows-packages.json').read_text(encoding='utf-8'))
    local = workspace / '.build_tools'
    destination, cache = local / INSTALL, local / 'downloads'
    cache.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not (destination/'packages.json').is_file() or json.loads(
                (destination/'packages.json').read_text(encoding='utf-8')) != manifest:
            raise PreparationError('已有工具目录不属于当前固定版本；请另行保留或移走：' + str(destination))
        check_toolchain(destination)
    else:
        with tempfile.TemporaryDirectory(prefix='.prepare-llvm-', dir=local) as staging:
            staging = Path(staging)
            for package in manifest:
                print('预备工具包：' + package['filename'], flush=True)
                extract_package(download(package, cache), package, staging)
            check_toolchain(staging)
            (staging/'packages.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            staging.rename(destination)
    try:
        smoke_test(destination)
    except PreparationError as error:
        raise PreparationError('LLVM 工具已保存，但原生编译/链接/运行检查失败。请检查 Visual Studio C++ '
                               'Build Tools 与 Windows SDK；完整错误：\n' + str(error)) from None
    print('LLVM 14 工具及 Windows 原生构建、运行检查通过：' + str(destination), flush=True)
    return destination


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-llvm', action='store_true', help='显式下载并检查 Windows x64 LLVM 14，保存至 .build_tools')
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        parser.error('需要 Python 3.10+')
    print('工作目录：' + str(ROOT))
    print('Python：' + sys.version.split()[0] + '；' + sys.platform + ' / ' + platform.machine())
    if not args.with_llvm:
        print('未请求下载。Windows 可加 --with-llvm 准备项目本地 LLVM 14。')
        return 0
    if sys.platform != 'win32' or platform.machine() not in ('AMD64', 'x86_64'):
        parser.error('--with-llvm 当前用于 Windows x64；WSL/Linux 请安装本机 clang-14 和 llvm-14。')
    try:
        prepare_llvm(ROOT)
    except (PreparationError, OSError, urllib.error.URLError, tarfile.TarError) as error:
        print('预备失败：' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
