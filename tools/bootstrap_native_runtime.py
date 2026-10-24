"""Fixed native runtime assembly; deliberately no source/ABI-plan inputs.

Typed native call and callback definitions belong to the Ru frontend's versioned
metadata output, not to this host. Never pass application source to this module.
"""
import re
from pathlib import Path

from rulang.c_runtime import _FEATURE, _MAP_REGION
from rulang.native_c_runtime import integrate_io, integrate_runtime

NATIVE_PROTOCOL = 'bootstrap-native-v1'
NATIVE_FLAG = '--allow-native=' + NATIVE_PROTOCOL
NATIVE_TRIPLE = 'x86_64-pc-windows-msvc'
NATIVE_MARKER = '/* RU_BOOTSTRAP_NATIVE_V1 ' + NATIVE_TRIPLE + ' */\n'

def supported_native_triple(triple):
    return re.fullmatch(r'x86_64-pc-windows-msvc(?:[0-9]+(?:\.[0-9]+)*)?', triple) is not None

def native_marker(triple):
    if not supported_native_triple(triple):
        raise ValueError('unsupported bootstrap native Windows target')
    return '/* RU_BOOTSTRAP_NATIVE_V1 ' + triple + ' */\n'
BASE_HEADERS = ('runtime.h', 'io_runtime.h', 'contest_runtime.h', 'practical_runtime.h', 'llvm_runtime.h')
NATIVE_HEADERS = ('native_types.h', 'native_platform_win64.h', 'native_runtime.h')


def fixed_native_runtime():
    directory = Path(__file__).resolve().parents[1]/'rulang'
    headers = [(directory/name).read_text(encoding='utf-8') for name in BASE_HEADERS[:-1]]
    headers[0] = integrate_runtime(headers[0])
    headers[1] = integrate_io(headers[1])
    headers.append((directory/'native_runtime.h').read_text(encoding='utf-8'))
    # Identical full-runtime feature expansion, with no source pruning/analysis.
    source = _FEATURE.sub(lambda m: m[2], _MAP_REGION.sub(lambda m: m[1], '\n'.join(headers)))
    source = re.sub(r'/\* RU_(?:MEMBERS: [^*]*|OPERATORS: [^*]*|END_MEMBERS) \*/\n', '', source)
    return source + '\n' + (directory/'llvm_runtime.h').read_text(encoding='utf-8')
