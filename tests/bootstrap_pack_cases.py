"""Fixed-output owned-result argument-pack cases; no benchmark or native claims."""
from bootstrap_slot_cases import CASES as SLOT_CASES, combined as slot_combined

EXTRA_CASES = [
    ('single_complex_argument_retained_through_callee_gc', """
算 守 值: 循 50 次 垃圾 取 ['pressure', ['nested']]. 环. 得 值. 法.
显 (守 ['single', ['kept']]).
显 (守 (真 或 (1/0))).
""", '[single, [kept]]\n真\n'),
    ('contiguous_heap_args_and_escaping_closure', """
算 接 甲 乙 丙: 循 30 次 垃圾 取 ['gc']. 环. 得 [甲,乙,丙]. 法.
显 (接 'first' 'second' 'third').
算 藏 值: 得 算: 得 值. 法. 法.
闭包 取 藏 ['escaped', ['inner']].
循 30 次 垃圾 取 ['pressure']. 环.
显 闭包().
""", '[first, second, third]\n[escaped, [inner]]\n'),
    ('complex_middle_result_and_multicomplex_fallback', """
算 回 值: 得 值. 法.
算 合 甲 乙: 得 [甲,乙]. 法.
显 (合 (真 或 (回 假)) (回 ['rhs'])).
显 (合 (回 ['left']) (回 ['right'])).
""", '[真, [rhs]]\n[[left], [right]]\n'),
    ('single_argument_panic_recovery_closure_survives', """
算 制 值:
 试 卒 'reason'. 救 原因
  得 算: 得 [值,原因]. 法.
 终.
法.
闭包 取 制 ['arg-root'].
循 30 次 垃圾 取 ['pressure']. 环.
显 闭包().
""", '[[arg-root], reason]\n'),
]
CASES = SLOT_CASES + EXTRA_CASES


def combined():
    source, expected = slot_combined()
    for name, code, output in EXTRA_CASES:
        source += '\n显 ' + repr(name) + '.\n段:\n' + code + '\n落.\n'
        expected += name + '\n' + output
    return source, expected


def sections(stdout):
    result, position = {}, 0
    for index, (name, _, _) in enumerate(CASES):
        marker = name + '\n'
        if not stdout.startswith(marker, position):
            raise AssertionError('missing/out-of-order pack case marker: ' + name)
        start = position + len(marker)
        end = len(stdout) if index + 1 == len(CASES) else stdout.find(CASES[index+1][0]+'\n', start)
        if end < 0:
            raise AssertionError('missing next pack case marker')
        result[name] = stdout[start:end]
        position = end
    return result
