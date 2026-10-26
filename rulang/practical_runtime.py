"""Primitives for bundled text, math and deterministic random libraries."""
from .execution_budget import checked_member, checked_operation
from .execution_budget import charge, bulk, check_budget, guard_budget, items as budget_items
# PCG32 algorithm: Copyright 2014 Melissa O'Neill; Apache License 2.0.
# See docs/third-party-notices.md and https://www.apache.org/licenses/LICENSE-2.0.
import math
from .frontend import Node, Token, bind_arguments
from .contest_runtime import ASCII_WHITESPACE, _BUILTIN_OWNER
_TYPES = None
_MASK64 = (1 << 64) - 1
_MASK32 = (1 << 32) - 1
_SAFE = (1 << 53) - 1

def install_practical(owner):
    from .interpreter import Instance, RuType, Scope
    global _TYPES
    if _TYPES is None:
        _TYPES = {}
        for kind, name in (("helpers", "实用工具"), ("random", "随机源")):
            node = Node("type", Token("IDENT", name, 0, 0),
                        {"name": name, "parent": None, "fields": [], "methods": []})
            typ = RuType(_BUILTIN_OWNER, node, fields={}, methods={}, state=2)
            typ.practical_kind = kind
            _TYPES[kind] = typ
    parent = Scope(owner.global_scope.parent)
    parent.values["__实用"] = Instance(_TYPES["helpers"], {})
    owner.global_scope.parent = parent

class _Random:
    """PCG-XSH-RR 64/32, fixed stream 54, explicit modular arithmetic."""
    def __init__(self, seed):
        self.state = 0
        self.next()
        self.state = (self.state + seed) & _MASK64
        self.next()
    def next(self):
        old = self.state
        self.state = (old * 6364136223846793005 + 109) & _MASK64
        shifted = (((old >> 18) ^ old) >> 27) & _MASK32
        rotation = old >> 59
        return ((shifted >> rotation) | (shifted << ((-rotation) & 31))) & _MASK32
    def bounded(self, count):
        if count == 1:
            return 0
        threshold = (1 << 32) % count
        while True:
            charge("helper_item")
            value = self.next()
            if value >= threshold:
                return value % count

@checked_operation
def fixed_text(value, places):
    """Round the exact binary64 rational, half away from zero."""
    numerator, denominator = abs(value).as_integer_ratio()
    quotient, remainder = divmod(numerator * 10 ** places, denominator)
    if remainder * 2 >= denominator:
        quotient += 1
    text = str(quotient).rjust(places + 1, "0")
    if places:
        text = text[:-places] + "." + text[-places:]
    return ("-" if math.copysign(1.0, value) < 0 else "") + text

_PARAMS = {
    "正弦": ["弧度"], "余弦": ["弧度"], "角度转弧度": ["角度"],
    "弧度转角度": ["弧度"], "方向角": ["纵", "横"],
    "拆分": ["文", "隔"], "替换": ["文", "旧", "新文"], "去空白": ["文"],
    "定点": ["值", "位数"], "平方根": ["值"], "幂": ["底数", "指数"],
    "向下取整": ["值"], "向上取整": ["值"], "四舍五入": ["值"], "造源": ["种子"],
}

@checked_member('practical_kind')
def practical_member(owner, n, receiver, name, args):
    from .interpreter import Instance
    if not isinstance(receiver, Instance):
        return False, None
    kind = getattr(receiver.type, "practical_kind", None)
    if kind is None:
        return False, None
    charge("call")
    fail = lambda message: owner.fail(n, message)
    def number(value, label):
        if not isinstance(value, float) or not math.isfinite(value):
            fail(label + "须为有限数")
        return value
    def integer(value, label, low, high):
        number(value, label)
        if value != math.trunc(value) or not low <= value <= high:
            fail(label + "须为范围内整数")
        return int(value)
    if kind == "random":
        params = {"整数": ["下", "上"], "洗牌": ["列"]}
        if name not in params:
            fail("未知随机源成员：" + name)
        bound = bind_arguments(name, args, params[name], fail)
        if name == "整数":
            low = integer(bound["下"], "下", -_SAFE, _SAFE)
            high = integer(bound["上"], "上", -_SAFE, _SAFE)
            count = high - low + 1
            if not 1 <= count <= 1 << 32:
                fail("随机整数须满足下不大于上且范围不超过 4294967296 项")
            return True, float(low + receiver.practical_state.bounded(count))
        original = bound["列"]
        if not isinstance(original, list):
            fail("洗牌的列须为阵")
        if len(original) > 1 << 32:
            fail("洗牌的列超过随机范围限制")
        bulk(len(original))
        result = original[:]
        for index in range(len(result) - 1, 0, -1):
            charge("helper_item")
            target = receiver.practical_state.bounded(index + 1)
            result[index], result[target] = result[target], result[index]
        return True, result
    if name not in _PARAMS:
        fail("未知实用库成员：" + name)
    bound = bind_arguments(name, args, _PARAMS[name], fail)
    if name in ("拆分", "替换", "去空白"):
        for label, value in bound.items():
            charge("helper_item")
            if not isinstance(value, str):
                fail(label + "须为句")
        if name == "去空白":
            bulk(len(bound["文"]))
            return True, bound["文"].strip(ASCII_WHITESPACE)
        separator = bound["隔"] if name == "拆分" else bound["旧"]
        if separator == "":
            fail(("隔" if name == "拆分" else "旧") + "不能为空句")
        bulk(len(bound["文"]) + len(separator) + (len(bound["新文"]) if name != "拆分" else 0))
        return True, (bound["文"].split(separator) if name == "拆分"
                      else bound["文"].replace(separator, bound["新文"]))
    if name == "造源":
        seed = integer(bound["种子"], "种子", 0, _MASK32)
        result = Instance(_TYPES["random"], {})
        result.practical_state = _Random(seed)
        return True, result
    if name == "定点":
        value = number(bound["值"], "值")
        places = integer(bound["位数"], "位数", 0, 15)
        return True, fixed_text(value, places)
    if name == "方向角":
        result = math.atan2(number(bound["纵"], "纵"), number(bound["横"], "横"))
    elif name in ("正弦", "余弦", "角度转弧度", "弧度转角度"):
        label = "角度" if name == "角度转弧度" else "弧度"
        value = number(bound[label], label)
        if name == "正弦":
            result = math.sin(value)
        elif name == "余弦":
            result = math.cos(value)
        elif name == "角度转弧度":
            result = value * (math.pi / 180.0)
        else:
            result = value * (180.0 / math.pi)
    elif name == "幂":
        base, exponent = number(bound["底数"], "底数"), number(bound["指数"], "指数")
        if base < 0 and exponent != math.trunc(exponent):
            fail("负底数的指数须为整数")
        if base == 0 and exponent < 0:
            fail("零的指数不能为负数")
        try:
            result = math.pow(base, exponent)
        except (OverflowError, ValueError):
            fail("幂的结果不是有限数")
    else:
        value = number(bound["值"], "值")
        if name == "平方根":
            if value < 0:
                fail("平方根的值不能为负数")
            result = math.sqrt(value)
        else:
            if name == "向下取整":
                result = float(math.floor(value))
            elif name == "向上取整":
                result = float(math.ceil(value))
            else:
                magnitude = abs(value)
                integral = math.floor(magnitude)
                result = float(integral + (magnitude - integral >= 0.5))
                result = math.copysign(result, value)
            if result == 0:
                result = math.copysign(0.0, value)
    if not math.isfinite(result):
        fail(name + "的结果不是有限数")
    return True, result
