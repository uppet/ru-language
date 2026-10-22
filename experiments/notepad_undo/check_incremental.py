"""Exercise real Ru checkpoint code against a fresh full-policy oracle per edit."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

RU = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RU), str(RU/'tests')]
from experiments.mi_source.test_source import compile_c
from experiments.notepad_undo.check_policy import literal
from rulang.compiler import Compiler
from rulang.frontend import parse
from rulang.modules import load_module_graph

DRIVER = '''
竞 取 外言 '如:竞'.
次数 取 [0,0,0,0].
算 扫描 文 为 句 缓 旧折:
    字们 取 竞 其 字列 文. 偏们 取 [0]. 字位 取 0. 字节 取 0. 行数 取 1. 前CR 取 假.
    循 字们 其 量 次
        字 取 字们[字位]. 字节 取 字节+(策 其 字节数 字). 偏们 其 增 字节. 字位 取 字位+1.
        若 字 == '\\r' 或 (字 == '\\n' 且 非 前CR) 则 行数 取 行数+1. 然
        前CR 取 字 == '\\r'.
    环
    态 取 策 其 新状态. 起态 取 增 其 开始 缓 字节 行数. 折们 取 {}.
    若 起态 != 空 则
        脏行 取 0. 子 取 0.
        循 字们 其 量 次
            字 取 字们[子].
            若 偏们[子+1] > 缓['dirtyEnd'] 则 破. 然
            若 字 == '\n' 或 (字 == '\r' 且 (子+1 == (字们 其 量) 或 字们[子+1] != '\n')) 则 脏行 取 脏行+1. 然
            子 取 子+1.
        环
        缓 其 增 'dirtyLine' 脏行.
        态 取 起态. 行位 取 0.
        循 旧折 其 量 次 折们 其 增 行位 旧折[行位]. 行位 取 行位+1. 环
    然
    位 取 0. 读量 取 0.
    循 若 偏们[位] >= 态[23] 则 破. 然 位 取 位+1. 环
    循
        末态 取 增 其 观察 缓 态.
        若 末态 != 空 则 态 取 末态. 破. 然
        目标 取 增 其 读末 缓 态[23] (态[23]+1024). 末 取 位.
        循 若 末 >= (字们 其 量) 或 偏们[末+1] > 目标 则 破. 然 末 取 末+1. 环
        读量 取 读量+偏们[末]-偏们[位].
        循
            果 取 策 其 喂入 态 文[位:末] (末 == (字们 其 量)).
            列 取 果['folds']. 子 取 0.
            循 列 其 量 次
                项 取 列[子]. 行位 取 项[0].
                循 项[1] 次 折们 其 增 行位 ([项[2],项[3]]). 行位 取 行位+1. 环
                子 取 子+1.
            环
            位 取 位+果['used'].
            若 位 == 末 且 (非 果['finished']) 则 破. 然
            若 果['finished'] 则 破. 然
        环
        若 态[2] 则 破. 然
    环
    增 其 完成 缓 态.
    得 [缓,折们,态,读量].
法
算 核对 文 为 句 缓 旧折 名 为 句 需复用 为 事实:
    果 取 扫描 文 缓 旧折. 全 取 扫描 文 (增 其 新缓存) ({}).
    若 (果[1] 其 量) != (全[1] 其 量) 则 卒 ('line count mismatch '+名). 然
    位 取 0.
    循 全[1] 其 量 次
        甲 取 果[1][位]. 乙 取 全[1][位].
        若 甲 == 空 或 乙 == 空 或 甲[0] != 乙[0] 或 甲[1] != 乙[1] 则 卒 ('fold mismatch '+名+' line '+(位 为 句)). 然
        位 取 位+1.
    环
    若 非 (增 其 同态 果[2] 全[2]) 或 果[2][23] != 全[2][23] 则 卒 ('final state mismatch '+名). 然
    若 需复用 且 缓['reused'] <= 0 则 卒 ('expected convergence '+名). 然
    若 (缓['points'] 其 量) > 128 则 卒 'checkpoint bound exceeded'. 然
    次数[0] 取 次数[0]+1. 次数[1] 取 次数[1]+(全[1] 其 量).
    若 缓['reused'] > 0 则 次数[2] 取 次数[2]+1. 然
    若 缓['base'] != 空 则 卒 'completed cache retained a history chain'. 然
    显 ('CASE_PASS '+名).
    得 果.
法
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--app-root', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    app, out = args.app_root.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    baseline = subprocess.check_output(['git', '-C', str(app), 'show',
        'd964ea9f7e27065aa5bbcced8d6c7526a6224dd1:src/markdown_policy.ru'])
    (out/'baseline.ru').write_bytes(baseline)
    source = '策 取 外言 '+literal((out/'baseline.ru').as_posix())+'.\n'
    source += '增 取 外言 '+literal((app/'src/markdown_incremental.ru').as_posix())+'.\n'+DRIVER
    fixtures = [
        ('fence', '# Heading\n\n~~~\n'+'code text\n'*3400+'codebody'),
        ('backtick', '# Heading\n\n```ru\n'+'code text\n'*3400+'```\n## next\nbody'),
        ('paragraph', '# Heading\n'+'plain text\n'*1900+'---\nbody'),
        ('unicode', '# 标题😀\r\n\r\n~~~\r\n'+('中😀内容\r\n'*600)+'~~~\r\nbody'),
        ('html', '# head\n<script>\n'+('opaque\n'*700)+'</script>\nbody'),
        ('containers', '# head\n\n> quoted\n\n'+('plain\n'*700)+'\n# next\nbody'),
        ('singleline', 'a'*4300),
        ('empty', ''),
    ]
    count = 0
    for name, text in fixtures:
        source += f'文本 取 {literal(text)}. 果 取 核对 文本 (增 其 新缓存) ({{}}) {literal(name+" base")} 假.\n'
        current = text
        # Consecutive edit and undo revisions; include edits after a nonzero
        # checkpoint, structural fence changes, CRLF and Unicode byte deltas.
        edits = [(min(8, len(text)), '', 'x'), (min(8, len(text)), 'x', ''),
                 (min(1800, len(text)), '', '中😀'), (min(1800, len(text)), '中😀', ''),
                 (min(12, len(text)), '', '\n'), (min(12, len(text)), '\n', '')]
        if '~~~' in text:
            pos = text.index('~~~')
            edits += [(pos, '~', ''), (pos, '', '~')]
        if '```' in text:
            pos = text.index('```')
            edits += [(pos, '`', ''), (pos, '', '`')]
        for step, (pos, removed, inserted) in enumerate(edits):
            assert current[pos:pos+len(removed)] == removed
            new = current[:pos]+inserted+current[pos+len(removed):]
            delta_lines = new.count('\n') - current.count('\n')
            length = len((removed or inserted).encode('utf-8'))
            kind = 2 if removed else 1
            need = name in ('fence', 'backtick') and step < 2
            source += '旧印 取 果[0][\'points\'] 为 句.\n'
            source += f'缓 取 增 其 修订 果[0] {len(current[:pos].encode("utf-8"))} {length} ({delta_lines}) {kind} 假.\n'
            source += f'果新 取 核对 {literal(new)} 缓 果[1] {literal(name+" edit "+str(step))} '+('真' if need else '假')+'.\n'
            source += "若 旧印 != (果[0]['points'] 为 句) 则 卒 'checkpoint alias mutation'. 然 果 取 果新.\n"
            current = new
            count += 1
    source += '''
缓 取 增 其 新缓存. 态 取 策 其 新状态. 位 取 0.
循 300 次 态[23] 取 位*16384. 增 其 记点 缓 态 真. 位 取 位+1. 环
若 (缓['points'] 其 量) != 128 则 卒 'checkpoint cap control'. 然
缓 其 增 'ready' 真. 缓 其 增 'length' 5000000.
若 (增 其 修订 缓 8 1 0 1 真)['base'] != 空 则 卒 'pending revision reused'. 然
若 (增 其 修订 缓 8 1 1 1 假)['base'] != 空 则 卒 'line-changing revision reused'. 然
若 (增 其 修订 缓 8 1 0 3 假)['base'] != 空 则 卒 'ambiguous event reused'. 然
显 ('REVISIONS '+(次数[0] 为 句)). 显 ('FOLD_LINES '+(次数[1] 为 句)). 显 ('REUSED_REVISIONS '+(次数[2] 为 句)). 显 'INCREMENTAL_PASS'.
'''
    entry = out/'oracle.ru'; entry.write_text(source, encoding='utf-8', newline='\n')
    ast = parse(source); graph = load_module_graph(entry, ast)
    compiler = Compiler(ast, str(entry), modules=graph)
    binary = compile_c(compiler.compile(), out)
    run = subprocess.run([str(binary)], capture_output=True, text=True, encoding='utf-8', timeout=240,
                         env=dict(os.environ, RU_GC_THRESHOLD='1024', RU_GC_STATS='1'))
    (out/'stdout.log').write_text(run.stdout, encoding='utf-8')
    (out/'stderr.log').write_text(run.stderr, encoding='utf-8')
    assert run.returncode == 0 and 'INCREMENTAL_PASS' in run.stdout, (run.stdout[-2000:], run.stderr[-2000:])
    assert 'RU_GC live=0' in run.stderr
    result = {'passed': True, 'edits': count, 'stdout': run.stdout, 'gc_live_zero': True,
              'windows_execution': sys.platform == 'win32',
              'oracle_sha256': hashlib.sha256(baseline).hexdigest(),
              'incremental_sha256': hashlib.sha256((app/'src/markdown_incremental.ru').read_bytes()).hexdigest()}
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
