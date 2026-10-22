"""Actual Windows controls: compare every fold after real edits and Undo."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

RU = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RU))
from experiments.notepad_undo.check_policy import literal
from rulang.compiler import Compiler
from rulang.frontend import parse
from rulang.llvm_toolchain import LLVMToolchain
from rulang.modules import load_module_graph

SOURCE = r'''
次数 取 [0].
算 全同 甲 乙:
    行数 取 (窗 其 发送 甲 2154 0 0) 其 数.
    若 行数 != (窗 其 发送 乙 2154 0 0) 其 数 则 卒 'native line count mismatch'. 然
    位 取 0.
    循 行数 次
        若 ((窗 其 发送 甲 2223 位 0) 其 数) != ((窗 其 发送 乙 2223 位 0) 其 数) 则 卒 ('native fold mismatch line '+(位 为 句)). 然
        若 ((窗 其 发送 甲 2228 位 0) 其 数) != ((窗 其 发送 乙 2228 位 0) 其 数) 则 卒 'native visibility mismatch'. 然
        位 取 位+1.
    环
    若 (编 其 文本 甲) != (编 其 文本 乙) 则 卒 'native text mismatch'. 然
    次数[0] 取 次数[0]+1.
    得 真.
法
算 改动 柄 始 为 数 末 为 数 文 为 句 启用 为 事实:
    (折 其 _增量策略) 其 增 'enabled' 启用.
    窗 其 发送 柄 2078 0 0. 窗 其 发送 柄 2160 始 末. 窗 其 发文 柄 2170 0 文. 窗 其 发送 柄 2079 0 0.
    得 折 其 排空 柄.
法
算 回退 柄 启用 为 事实:
    (折 其 _增量策略) 其 增 'enabled' 启用.
    窗 其 发送 柄 2176 0 0.
    得 折 其 排空 柄.
法
算 元初 参数 为 句 阵:
    (折 其 _密扫描策略) 其 增 'enabled' 真.
    库 取 密 其 动态库 ((窗 其 目录)+'Scintilla.dll').
    实例 取 窗 其 成功 ((窗 其 GetModuleHandleW) 其 调用 [空]) 'instance'.
    类名 取 密 其 UTF16 'RuNotepad.IncrementalFixture'.
    回调 取 密 其 回调 (窗 其 WNDPROC) (算 基 其 过程) 0.
    类 取 (窗 其 WNDCLASS) 其 新建.
    类 其 写 'size' ((窗 其 WNDCLASS) 其 大小). 类 其 写 'proc' (回调 其 地址).
    类 其 写 'instance' 实例. 类 其 写 'name' (类名 其 地址).
    窗 其 成功 ((窗 其 RegisterClassExW) 其 调用 [类]) 'register incremental fixture'.
    父 取 窗 其 控制 空 实例 'RuNotepad.IncrementalFixture' 'incremental correctness' 13565952 0.
    甲 取 编 其 创建 父 实例 1. 乙 取 编 其 创建 父 实例 2.
    文位 取 0.
    循 文们 其 量 次
        文 取 文们[文位].
        (折 其 _增量策略) 其 增 'enabled' 真. 基 其 准备 甲 文. 折 其 排空 甲.
        (折 其 _增量策略) 其 增 'enabled' 假. 基 其 准备 乙 文. 折 其 排空 乙.
        全同 甲 乙.
        态 取 改动 甲 8 8 'x' 真. 改动 乙 8 8 'x' 假. 全同 甲 乙.
        若 文位 == 0 且 态['readBytes'] >= 态['length'] 则 卒 'native convergence was not exercised'. 然
        回退 甲 真. 回退 乙 假. 全同 甲 乙.
        若 文位 == 0 则
            # Restore an actual nonzero checkpoint, well past the first block.
            改动 甲 20000 20000 'Q' 真. 改动 乙 20000 20000 'Q' 假. 全同 甲 乙.
            回退 甲 真. 回退 乙 假. 全同 甲 乙.
        然
        改动 甲 1000 1000 'Z' 真. 改动 乙 1000 1000 'Z' 假. 全同 甲 乙.
        回退 甲 真. 回退 乙 假. 全同 甲 乙.
        改动 甲 12 13 '' 真. 改动 乙 12 13 '' 假. 全同 甲 乙.
        回退 甲 真. 回退 乙 假. 全同 甲 乙.
        改动 甲 8 8 '\n' 真. 改动 乙 8 8 '\n' 假. 全同 甲 乙.
        回退 甲 真. 回退 乙 假. 全同 甲 乙.
        # Multiple notifications before a completed scan must fall back.
        (折 其 _增量策略) 其 增 'enabled' 真.
        窗 其 发送 甲 2160 8 8. 窗 其 发文 甲 2170 0 'x'.
        窗 其 发送 甲 2160 9 9. 窗 其 发文 甲 2170 0 'y'. 折 其 排空 甲.
        (折 其 _增量策略) 其 增 'enabled' 假.
        窗 其 发送 乙 2160 8 8. 窗 其 发文 乙 2170 0 'x'.
        窗 其 发送 乙 2160 9 9. 窗 其 发文 乙 2170 0 'y'. 折 其 排空 乙. 全同 甲 乙.
        文位 取 文位+1.
    环
    折 其 遗忘 甲. 折 其 遗忘 乙.
    若 (折 其 _增量们) 其 量 != 0 则 卒 'forgotten owner retained a checkpoint cache'. 然
    窗 其 成功 ((窗 其 DestroyWindow) 其 调用 [父]) 'destroy incremental fixture'.
    窗 其 成功 ((窗 其 UnregisterClassW) 其 调用 [类名,实例]) 'unregister incremental fixture'.
    类 其 关闭. 类名 其 关闭. 回调 其 关闭.
    显 ('NATIVE_ALL_FOLDS '+(次数[0] 为 句)). 显 'INCREMENTAL_NATIVE_PASS'.
    得 0.
法
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--app-root', type=Path, required=True)
    ap.add_argument('--runtime', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    if sys.platform != 'win32': ap.error('actual Windows execution only')
    app, runtime, out = args.app_root.resolve(), args.runtime.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = ''
    for name, path in [('密', '如:密'), ('窗', str(app/'src/win32.ru')),
                       ('编', str(app/'src/editor.ru')), ('折', str(app/'src/markdown_syntax.ru')),
                       ('基', str(app/'tests/markdown_native.ru'))]:
        source += name+' 取 外言 '+literal(path.replace('\\', '/'))+'.\n'
    fixtures = ['# Heading\n\n~~~\n'+'code text\n'*2100+'codebody',
                '# Heading\n'+'plain text\n'*600+'---\nbody',
                '# Heading\n\n~~~\n'+'中😀内容\r\n'*500+'~~~\r\nbody',
                '# Heading\n\n~~~\n'+'code text\n'*130+'# fake\n~~~\n## next\nbody']
    source += '文们 取 ['+','.join(map(literal, fixtures))+'].\n'
    source += SOURCE
    entry = out/'fixture.ru'; entry.write_text(source, encoding='utf-8', newline='\n')
    ast = parse(source); graph = load_module_graph(entry, ast)
    compiler = Compiler(ast, str(entry), modules=graph, allow_native=True,
        mi_manifest=app/'experiments/markdown-dense-manifest.json', mi_backend='llvm')
    generated = compiler.compile()
    toolchain = LLVMToolchain()
    toolchain.link_flags += ['-luser32', '-lshell32']
    binary, _ = toolchain.compile(compiler.mi_plan.compute_source('llvm'), generated, out)
    for name in ('Scintilla.dll', 'Lexilla.dll', 'RuSyntax.dll'):
        shutil.copyfile(runtime/name, out/name)
    run = subprocess.run([str(binary)], capture_output=True, text=True, encoding='utf-8', timeout=180,
                         env=dict(os.environ, RU_GC_STATS='1'))
    (out/'stdout.log').write_text(run.stdout, encoding='utf-8')
    (out/'stderr.log').write_text(run.stderr, encoding='utf-8')
    assert run.returncode == 0 and 'INCREMENTAL_NATIVE_PASS' in run.stdout, (run.stdout[-1000:], run.stderr[-2000:])
    assert 'RU_GC live=0' in run.stderr
    result = {'passed': True, 'stdout': run.stdout, 'gc_live_zero': True,
              'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
