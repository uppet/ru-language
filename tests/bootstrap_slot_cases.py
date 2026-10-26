"""Focused slot-ownership fixtures, each checked against fixed output and old lowering."""
CASES = [
    ('panic_check_success_keeps_outer_arguments', """
算 等 值: 得 值. 法.
算 合 甲 乙 丙: 得 甲+乙+丙. 法.
显 (合 'left' (等 'middle') (等 'right')).
显 ['head', (等 ['nested', 'array']), 'tail'].
""", 'leftmiddleright\n[head, [nested, array], tail]\n'),
    ('prepared_receiver_survives_argument_and_reentry', """
形 报告: 算 合 值: 得 值+10. 法. 象.
对象 取 新 报告. 容器 取 [对象].
算 改: 容器[0] 取 空. 得 2. 法.
显 容器[0] 其 合 (改()).
""", '12\n'),
    ('named_pack_contiguity_and_source_order', """
算 报 值: 显 值. 得 值. 法.
算 合 左 中 右: 得 左*100+中*10+右. 法.
显 (合 右:(报 3) 左:(报 1) 中:(报 2)).
""", '3\n1\n2\n123\n'),
    ('return_array_copy_before_frame_cleanup', """
算 返 值: 得 ['left', [值, 'nested'], 'right']. 法.
列 取 返 'owned'. 显 列.
显 (返 'temporary')[1][0].
循 100 次 临时 取 返 'pressure'. 环.
显 列[1][1].
""", '[left, [owned, nested], right]\ntemporary\nnested\n'),
    ('panic_suppresses_remaining_args_then_resumes', """
算 坏: 卒 'stop'. 法.
算 后: 显 'BAD'. 得 3. 法.
算 合 左 右: 得 左+右. 法.
试 显 (合 坏 后). 救 原因 显 原因. 终.
显 (合 4 5).
""", 'stop\n9\n'),
    ('nested_rescue_return_and_break', """
算 返: 试 卒 'outer'. 救 外因 试 卒 'inner'. 救 内因 得 [外因,内因]. 终. 终. 法.
显 返.
循 试 卒 'break'. 救 原因 显 原因. 破. 终. 环.
显 'after'.
""", '[outer, inner]\nbreak\nafter\n'),
    ('counted_nested_loops_branches_scalar_liveness', """
数值 取 0. 次数 取 4.
循 次数 次
 次数 取 1.
 循 3 次
  若 数值 % 2 == 0 则 数值 取 数值+1. 另 数值 取 数值+2. 然.
 环.
环.
显 数值.
""", '23\n'),
    ('closures_env_escape_recursion_and_self', """
算 制 起: 算 增 步: 起 取 起+步. 得 起. 法. 得 算 增. 法.
回调 取 制 2. 显 (回调 3). 显 (回调 4).
算 应用 回调 左 右: 得 (回调 左)+(回调 右). 法.
显 (应用 右:2 回调:回调 左:1).
算 阶 值: 若 值 <= 1 则 得 1. 然. 得 值*(阶 (值-1)). 法.
显 (阶 6).
形 计: 值 为 数. 算 制 步: 算 增: 其 值 取 其 值+步. 得 其 值. 法. 得 算 增. 法. 象.
对象 取 新 计 值:2. 内 取 对象 其 制 3. 对象 取 空. 显 内(). 显 内().
""", '5\n9\n22\n720\n5\n8\n'),
    ('scope_rescue_closure_escapes', """
容器 取 [空]. 段: 值 取 ['kept']. 容器[0] 取 算: 得 值. 法. 落.
显 容器[0]().
试 卒 'reason'. 救 原因 算 看: 原因 取 原因+'!'. 得 原因. 法. 容器[0] 取 算 看. 终.
显 容器[0](). 显 容器[0]().
""", '[kept]\nreason!\nreason!!\n'),
    ('runtime_reentrant_callbacks_map_cycles', """
形 点: 值 为 数. 算 同 另一: 得 其 值 == 另一 其 值. 法. 算 印: 得 其 值. 法. 象.
表 取 {}. 甲 取 新 点 值:3. 乙 取 新 点 值:3.
表 其 增 甲 'same'. 显 表[乙].
算 双 值: 得 值*2. 法.
列 取 [3,1,2]. 显 (列 其 排序) 其 另成 (算 双).
环列 取 []. 环列 其 增 环列. 显 环列.
""", 'same\n[2, 4, 6]\n[<循环>]\n'),
    ('short_circuit_map_nested_values_and_assignment', """
算 等 值: 得 值. 法.
显 假 且 (等 (1/0)). 显 真 或 (等 (1/0)).
表 取 {'k': (等 ['v'])}. 显 表['k'][0].
列 取 [[1], [2]]. 列[(等 0)] 取 (等 [3]). 显 列.
""", '假\n真\nv\n[[3], [2]]\n'),
    ('early_finish_unreachable_branch_and_zero_arg_pack', """
作 前: 段: 试 完. 救 原因 显 'BAD'. 终. 落. 显 'BAD'. 为.
算 零: 得 ['zero']. 法.
前. 若 假 则 显 'BAD'. 另 显 零(). 然.
显 'done'.
""", '[zero]\ndone\n'),
    ('return_break_other_branch_remains_correct', """
算 分支 旗:
 若 旗 则 得 ['early']. 另 值 取 ['late']. 显 值. 然.
 得 ['after'].
法.
显 (分支 真). 显 (分支 假).
值 取 0. 循 5 次
 若 值 == 2 则 破. 另 值 取 值+1. 然.
环. 显 值.
""", '[early]\n[late]\n[after]\n2\n'),
]

def combined():
    # Classes are top-level-only; these three uniquely named fixture types have
    # no dependency on a case-local binding, so keep them in the module header.
    import re
    types, sections = [], []
    for name, code, _ in CASES:
        types.extend(re.findall(r'形 .*?象\.', code, re.S))
        code = re.sub(r'形 .*?象\.', '', code, flags=re.S)
        sections.append("显 '" + name + "'.\n段:\n" + code + '\n落.\n')
    source = '\n'.join(types + sections)
    expected = ''.join(name + '\n' + expected for name, _, expected in CASES)
    return source, expected
