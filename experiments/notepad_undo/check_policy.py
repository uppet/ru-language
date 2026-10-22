"""Full-state differential against the unchanged wip policy, feed by feed."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

RU = Path(__file__).resolve().parents[2]
BASE = 'd964ea9f7e27065aa5bbcced8d6c7526a6224dd1'
sys.path[:0] = [str(RU), str(RU/'tests')]
from experiments.mi_source.test_source import compile_c
from rulang.compiler import Compiler
from rulang.frontend import parse
from rulang.llvm_compiler import LLVMCompiler
from rulang.llvm_toolchain import LLVMToolchain
from rulang.modules import load_module_graph


def literal(text):
    if len(text.encode('utf-8')) > 3000:
        return '(' + '+'.join(literal(text[i:i+512]) for i in range(0, len(text), 512)) + ')'
    return "'" + text.replace('\\', '\\\\').replace("'", "\\'").replace('\r', '\\r').replace('\n', '\\n').replace('\t', '\\t') + "'"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--app-root', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--target', choices=('c', 'llvm', 'c-llvm'), required=True)
    args = ap.parse_args()
    app, out = args.app_root.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    original = subprocess.check_output(['git', '-C', str(app), 'show', BASE+':src/markdown_policy.ru'])
    baseline = out/'baseline.ru'; baseline.write_bytes(original)
    source = "甲模 取 外言 " + literal(baseline.as_posix()) + ".\n乙模 取 外言 " + literal((app/'src/markdown_policy.ru').as_posix()) + ".\n密模 取 外言 " + literal((app/'src/markdown_dense.ru').as_posix()) + ".\n"
    fixture = (app/'tests/markdown_policy.ru').read_text(encoding='utf-8')
    source += fixture[fixture.index('算 同全态'):fixture.index('作 核输入边界')]
    source += '''
次数 取 [0,0,0].
作 接入 甲 乙 文 为 句 末 为 事实:
    位 取 0.
    循
        旗甲 取 甲[19]. 旗乙 取 乙[19]. 栈甲 取 甲[3]. 栈乙 取 乙[3].
        头甲 取 []. 头乙 取 []. 头位 取 0.
        循 栈甲 其 量 次 头甲 其 增 栈甲[头位]. 头乙 其 增 栈乙[头位]. 头位 取 头位+1. 环
        果甲 取 甲模 其 喂入 甲 文[位:] 末.
        果乙 取 密模 其 喂入 乙 文[位:] 末.
        若 非 (同全态 甲 乙) 则 卒 'full 24-slot state mismatch'. 然
        键们 取 ['used','line','bytes','finished']. 项 取 0.
        循 4 次 若 果甲[键们[项]] != 果乙[键们[项]] 则 卒 'return mismatch'. 然 项 取 项+1. 环
        若 (果甲['folds'] 为 句) != (果乙['folds'] 为 句) 则 卒 'fold ranges mismatch'. 然
        若 (旗甲 == 甲[19]) != (旗乙 == 乙[19]) 或 (栈甲 == 甲[3]) != (栈乙 == 乙[3]) 则 卒 'alias identity mismatch'. 然
        若 (旗甲 为 句) != (旗乙 为 句) 或 (头甲 为 句) != (头乙 为 句) 则 卒 'retained alias mismatch'. 然
        次数[0] 取 次数[0]+1.
        用 取 果甲['used']. 位 取 位+用.
        若 (果甲['folds'] 其 量) >= 60 则 次数[2] 取 次数[2]+1. 然
        若 位 == (文 其 量) 且 (非 末 或 果甲['finished']) 则 破. 然
        若 用 == 0 且 (果甲['folds'] 其 量) == 0 则 卒 'no progress'. 然
    环
为
作 拒绝 甲 乙 文 为 句 末 为 事实:
    错 取 ['', ''].
    试 甲模 其 喂入 甲 文 末. 救 原因 错[0] 取 原因 为 句. 终
    试 密模 其 喂入 乙 文 末. 救 原因 错[1] 取 原因 为 句. 终
    若 错[0] == '' 或 错[0] != 错[1] 或 非 (同全态 甲 乙) 则 卒 'error order/state mismatch'. 然
    次数[1] 取 次数[1]+1.
为
作 块分 文 为 句 块 为 数:
    甲 取 甲模 其 新状态. 乙 取 乙模 其 新状态. 位 取 0.
    循
        末 取 位+块. 若 末 > (文 其 量) 则 末 取 文 其 量. 然
        接入 甲 乙 文[位:末] (末 == (文 其 量)). 位 取 末.
        若 位 == (文 其 量) 则 破. 然
    环
    接入 甲 乙 '' 真. 拒绝 甲 乙 'x' 真. 拒绝 甲 乙 '' 假.
为
作 切分 文 为 句:
    切 取 0.
    循 (文 其 量)+1 次
        甲 取 甲模 其 新状态. 乙 取 乙模 其 新状态.
        接入 甲 乙 文[:切] 假. 接入 甲 乙 文[切:] 真.
        切 取 切+1.
    环
为
'''
    cases = [ast.literal_eval(b) for b in re.findall(r"^核例 '(?:[^'\\]|\\.)*' ('(?:[^'\\]|\\.)*')", fixture, re.M)]
    for text in cases: source += '切分 ' + literal(text) + '.\n'
    long_cases = ['a'*2300, 'A'*2100, 'a'*80+' '*1200, 'a'*80+'Z'*1200,
                  'a'*80+'`'*60, 'a'*80+'<ScRiPt'+'z'*1100+'>tail',
                  '# h\n'+'a'*2100+'\r\n---', 'a'*100+'中😀'+'b'*1200,
                  '~~~\n'+'a'*2100+'\r\n~~~\n', '```\r\n'+('a中😀'*400)+'\n```',
                  ''.join('# h\nbody\n' for _ in range(100))]
    long_cases += [('# h\nbody\n'*n)+'~~~\n'+('  safe\n\ttext\n'*90)+'~~~\n' for n in (28,29,30)]
    long_cases += ['~~~\n'+('plain\n'*100)+'  ~~~~\n# next\nbody',
                   '```\n'+('plain\n'*100)+'``\ntext\n```\n',
                   '~~~\n'+('plain\n'*100)+'    ~~~~\n~~~\n',
                   '~~~\n'+('plain\n'*100)+'中\n>\r\n~~~\n']
    # Exact edit/revision text sequence, including both undo revisions.
    base = 'a'*2300
    long_cases += [base[:8]+'x'+base[8:], base, base[:8]+'x'+base[8:], base]
    for text in long_cases:
        for n in (1,2,11,31,32,127,1024): source += f'块分 {literal(text)} {n}.\n'
    for char in ('a', '\x7f', '\x80', '\u07ff', '\u0800', '\uffff', '\U00010000', '😀'):
        source += f"甲 取 甲模 其 新状态. 乙 取 乙模 其 新状态. 拒绝 甲 乙 {literal(char*1025)} 假. 接入 甲 乙 {literal(char*1024)} 真. 拒绝 甲 乙 {literal(char*1025)} 假.\n"
    source += "若 次数[2] == 0 则 卒 'range pause not exercised'. 然\n显 ('FULL_STATE_RETURNS '+(次数[0] 为 句)). 显 ('ERROR_CHECKS '+(次数[1] 为 句)). 显 ('RANGE_PAUSES '+(次数[2] 为 句)). 显 'DIFFERENTIAL_PASS'.\n"
    entry = out/'oracle.ru'; entry.write_text(source, encoding='utf-8', newline='\n')
    ast_nodes = parse(source); graph = load_module_graph(entry, ast_nodes)
    cls = LLVMCompiler if args.target == 'llvm' else Compiler
    compiler = cls(ast_nodes, str(entry), modules=graph, mi_manifest=app/'experiments/markdown-dense-manifest.json',
                   mi_backend='llvm' if args.target == 'c-llvm' else 'c')
    if args.target == 'llvm':
        toolchain = LLVMToolchain(); ir = compiler.compile(toolchain.triple, toolchain.data_layout); c = compiler.runtime_c()
    else: c = compiler.compile()
    # Test-only boundary instrumentation, outside the validated pure kernel IR.
    pattern = r'(static RuMiResult ru_mi_kernel_1\([^\n]*\) \{\n)'
    c, count = re.subn(pattern, r'\1    test_mi_calls++;\n', c)
    assert count == 1
    match = re.search(r'static RuMiResult ru_mi_kernel_3\(([^\n]*)\) \{', c)
    assert match
    end, depth = match.end(), 1
    while depth:
        if c[end] == '{': depth += 1
        elif c[end] == '}': depth -= 1
        end += 1
    arguments = ','.join(re.findall(r'\bp\d+\b', match[1]))
    inner = c[match.start():end].replace('ru_mi_kernel_3(', 'test_batch_inner(', 1)
    wrapper = (f'\nstatic RuMiResult ru_mi_kernel_3({match[1]}) {{\n'
               f'    RuMiResult r=test_batch_inner({arguments}); ++test_batch_calls;\n'
               '    if (!r.status && r.value) { ++test_batch_hits; }\n    return r;\n}\n')
    c = c[:match.start()] + inner + wrapper + c[end:]
    c = '#include <stdint.h>\nstatic uint64_t test_mi_calls,test_batch_calls,test_batch_hits;\n' + c
    main_wrapper = '\nint main(int argc,char **argv) { int status=test_program_main(argc,argv); fprintf(stderr,"MI_KERNEL_CALLS=%llu BATCH_CALLS=%llu BATCH_HITS=%llu\\n",(unsigned long long)test_mi_calls,(unsigned long long)test_batch_calls,(unsigned long long)test_batch_hits); return status; }\n'
    if args.target in ('llvm', 'c-llvm'):
        if args.target == 'llvm':
            ir = ir.replace('define i32 @main(', 'define i32 @test_program_main(', 1)
            c += '\nint test_program_main(int,char **);\n' + main_wrapper
        else:
            toolchain = LLVMToolchain()
            ir = compiler.mi_plan.compute_source('llvm')
            c = '#define main test_program_main\n' + c + '\n#undef main\n' + main_wrapper
        binary, _ = toolchain.compile(ir, c, out)
    else:
        c = '#define main test_program_main\n' + c + '\n#undef main\n' + main_wrapper
        binary = compile_c(c, out)
    result = subprocess.run([str(binary)], capture_output=True, text=True, encoding='utf-8', timeout=300,
                            env=dict(os.environ, RU_GC_STATS='1'))
    (out/'stdout.log').write_text(result.stdout, encoding='utf-8'); (out/'stderr.log').write_text(result.stderr, encoding='utf-8')
    assert result.returncode == 0, (result.stdout[-1000:], result.stderr[-2000:])
    assert 'DIFFERENTIAL_PASS' in result.stdout and 'RU_GC live=0' in result.stderr
    calls = re.search(r'MI_KERNEL_CALLS=(\d+)', result.stderr); assert calls and int(calls[1]) > 0
    batch = re.search(r'BATCH_CALLS=(\d+) BATCH_HITS=(\d+)', result.stderr)
    assert batch and int(batch[2]) > 0
    receipt = {'passed':True,'target':args.target,'stdout':result.stdout,'kernel_calls':int(calls[1]),
               'oracle_sha256':hashlib.sha256(original).hexdigest(), 'gc_live_zero':True,
               'test_only_kernel_boundary_counter':True, 'windows_abi_execution':sys.platform=='win32'}
    receipt.update(batch_calls=int(batch[1]), batch_hits=int(batch[2]))
    (out/'result.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
