#!/usr/bin/env python3
"""AOT-compile Ru's persistent AST interpreter using the native Ru frontend."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rulang.frontend import RuError
from rulang.llvm_toolchain import LLVMToolchain
from tools.bootstrap import compile_native


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    suffix = '.exe' if sys.platform == 'win32' else ''
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path,
                        default=ROOT/'bin/bootstrap'/sys.platform/('stage3'+suffix))
    parser.add_argument('--llvm-clang')
    parser.add_argument('-o', '--output', type=Path, default=ROOT/'bin/rushu'/('native-kernel'+suffix))
    args = parser.parse_args(argv)
    if not args.compiler.is_file():
        parser.error('native stage3 compiler not found; first run python3 tools/bootstrap.py bootstrap')
    try:
        evidence = compile_native(args.compiler, ROOT/'rushu/native/kernel.ru', args.output,
                                  LLVMToolchain(args.llvm_clang), interpreter_host=True)
    except (RuError, OSError, ValueError, RuntimeError) as error:
        parser.exit(1, str(error)+'\n')
    print(f'Ru AST kernel: {args.output.resolve()} ({evidence["seconds"]:.2f}s)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
