"""Practical-library Python/standalone JavaScript parity and hard boundaries."""
import io
import json
import math
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter
from rulang.js_compiler import JSCompiler
from rulang.modules import load_module_graph

NODE = shutil.which('node') or shutil.which('nodejs')
PRELUDE = "文 取 外言 '如:文本'. 数学 取 外言 '如:数学'. 随 取 外言 '如:随机'.\n"


@unittest.skipUnless(NODE, 'Node.js unavailable')
class PracticalJavaScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()

    def graph(self, source):
        return load_module_graph(str(self.folder/'source.ru'), parse(source))

    def python(self, graph, data=''):
        output = io.StringIO()
        Interpreter(io.StringIO(data), output).execute(
            graph[graph.root], source_path=graph.root, modules=graph)
        return output.getvalue()

    def javascript(self, graph, data='', full=False):
        code = JSCompiler(graph[graph.root], graph.root, modules=graph,
                          full_runtime=full).compile()
        target = self.folder/('full.js' if full else 'pruned.js')
        target.write_text(code, encoding='utf-8')
        result = subprocess.run([NODE, str(target)], input=data.encode(),
                                capture_output=True, timeout=30, cwd='/',
                                env={**os.environ, 'PATH':'/nonexistent'})
        return result.returncode, result.stdout.decode(), result.stderr.decode()

    def parity(self, source, expected=None, data=''):
        graph = self.graph(source)
        interpreted = self.python(graph, data)
        if expected is not None:
            self.assertEqual(interpreted, expected)
        for full in (False, True):
            with self.subTest(full_runtime=full):
                self.assertEqual(self.javascript(graph, data, full), (0, interpreted, ''))

    def test_literal_text_and_ascii_whitespace(self):
        self.parity(PRELUDE + r"""
显 文 其 拆分 ',甲,,乙,' ','. 显 文 其 拆分 'aaa' 'aa'.
显 (文 其 拆分 '' ',') 其 量. 显 文 其 拆分 '如😀é😀' '😀'.
显 文 其 替换 'aaa' 'aa' 'aaaa'. 显 文 其 替换 '甲甲乙' '甲' ''.
显 文 其 替换 文:'$a$a' 旧:'$a' 新文:'$&'.
显 '['+(文 其 去空白 ' \t\r\n\v\f甲 乙\f\v\r\n\t ')+']'.
显 '['+(文 其 去空白 ' \t　甲  \n')+']'.
显 '['+(文 其 去空白 ' \t\r\n\v\f')+']'.
""".replace('\\v', '\v').replace('\\f', '\f'), '[, 甲, , 乙, ]\n[, a]\n1\n[如, é, ]\naaaaa\n乙\n$&$&\n[甲 乙]\n[　甲 ]\n[]\n')

    def test_fixed_decimal_goldens(self):
        values = [(1.25, 1, '1.3'), (-1.25, 1, '-1.3'),
                  (2.675, 2, '2.67'), (-2.675, 2, '-2.67'),
                  (0.0, 2, '0.00'), (-0.0, 2, '-0.00'),
                  (-0.00001, 2, '-0.00'), (9.999, 2, '10.00'),
                  (0.5, 0, '1'), (-0.5, 0, '-1'),
                  (1.0000000000000002, 15, '1.000000000000000'),
                  (5e-324, 15, '0.000000000000000')]
        source = PRELUDE + ''.join(f'显 文 其 定点 ({repr(v)}) {p}.' for v, p, _ in values)
        self.parity(source, ''.join(expected+'\n' for _, _, expected in values))

    def test_fixed_random_binary64_and_largest_finite(self):
        rng = random.Random(120042)
        values = [sys.float_info.max, -sys.float_info.max,
                  sys.float_info.min, -sys.float_info.min,
                  math.nextafter(0.5, 0), math.nextafter(0.5, 1)]
        while len(values) < 600:
            value = struct.unpack('>d', rng.getrandbits(64).to_bytes(8, 'big'))[0]
            if math.isfinite(value):
                values.append(value)
        source = PRELUDE + """
竞 取 外言 '如:竞'. 入 取 竞 其 读入.
循 值 取 入 其 数. 若 值 == 空 则 破. 然
    位数 取 入 其 数. 显 文 其 定点 值 位数.
环
"""
        data = '\n'.join(f'{value!r} {index % 16}' for index, value in enumerate(values))
        self.parity(source, data=data)

    def test_math_rounding_and_domains(self):
        self.parity(PRELUDE + """
显 数学 其 平方根 9. 显 数学 其 平方根 (-0).
显 数学 其 幂 0 0. 显 数学 其 幂 (-2) 3. 显 数学 其 幂 2 (-2).
显 数学 其 幂 (-0) 3. 显 数学 其 幂 1e-300 2.
显 数学 其 向下取整 (-1.2). 显 数学 其 向上取整 (-0.2).
显 数学 其 四舍五入 2.5. 显 数学 其 四舍五入 (-2.5).
显 数学 其 四舍五入 0.49999999999999994.
显 数学 其 四舍五入 (-0.49999999999999994).
显 数学 其 四舍五入 4503599627370495.5.
显 数学 其 四舍五入 4503599627370497.
显 数学 其 向下取整 (-0). 显 数学 其 向上取整 (-0).
显 数学 其 四舍五入 (-0).
""", '3\n-0\n1\n-8\n0.25\n-0\n0\n-2\n-0\n3\n-3\n0\n-0\n4.5035996273705e+15\n4.5035996273705e+15\n-0\n-0\n-0\n')

    def test_pcg_official_seed_42_stream_54_goldens(self):
        # Official pcg32_srandom_r(..., 42, 54) reference sequence, in decimal.
        golden = [0xa15c02b7, 0x7b47f409, 0xba1d3330,
                  0x83d2f293, 0xbfa4784b, 0xcbed606e]
        self.parity(PRELUDE + """
源 取 随 其 造源 42. 显 源 其 整数 (-0) (-0).
空列 取 []. 单列 取 [1]. 甲 取 源 其 洗牌 空列. 乙 取 源 其 洗牌 单列.
显 甲 == 空列. 显 乙 == 单列. 显 乙.
循 6 次 显 源 其 整数 0 4294967295. 环
""", '0\n假\n假\n[1]\n'+''.join(str(value)+'\n' for value in golden))

    def test_pcg_rejection_path_and_state_aliasing(self):
        self.parity(PRELUDE + """
源 取 随 其 造源 42. 别 取 源. 独 取 随 其 造源 42.
显 源 其 整数 0 2147483648. 显 别 其 整数 0 2147483648.
显 源 其 整数 0 2147483648. 显 别 其 整数 0 4294967295.
显 独 其 整数 0 4294967295.
显 源 其 整数 9007199254740991 9007199254740991.
显 源 其 整数 (-9007199254740991) (-9007199254740991).
""", '559678134\n974992175\n64156306\n3215226955\n2707161783\n9.00719925474099e+15\n-9.00719925474099e+15\n')

    def test_random_shuffle_and_safe_integer_ranges(self):
        self.parity(PRELUDE + """
源 取 随 其 造源 4294967295. 原 取 [0,1,2,3,4,5,6,7,8,9].
显 源 其 洗牌 原. 显 原.
循 30 次
  显 文 其 定点 (源 其 整数 (-9007199254740991) (-9007194959773696)) 0.
  显 文 其 定点 (源 其 整数 9007194959773696 9007199254740991) 0.
  显 源 其 整数 (-2147483648) 2147483647.
环
内 取 [7]. 单 取 [内]. 副 取 源 其 洗牌 单.
显 副 == 单. 显 副[0] == 内. 副[0][0] 取 8. 显 内.
""")

    def test_invalid_random_calls_do_not_advance_state(self):
        # A Ru runtime error terminates its program. Catch it in the host test
        # harness to inspect the otherwise unreachable post-failure state.
        invalid = [('整数', [2, 1]), ('整数', [0, 4294967296]),
                   ('整数', [0.5, 1]), ('整数', [0, 9007199254740992]),
                   ('整数', [False, 1]), ('整数', [0]), ('洗牌', ['abc'])]
        owner = Interpreter(io.StringIO(), io.StringIO())
        node = parse('显 0.')[0]
        helper = owner.global_scope.get('__实用', node.token)
        expected = []
        for name, values in invalid:
            source = owner.member(node, helper, '造源', [(None, 42.0)])
            args = [(None, float(value) if type(value) in (int, float) else value)
                    for value in values]
            with self.assertRaises(RuError):
                owner.member(node, source, name, args)
            expected.append(int(owner.member(node, source, '整数', [(None, 0.0), (None, 4294967295.0)])))
        self.assertEqual(expected, [0xa15c02b7]*len(invalid))
        script = (ROOT/'rulang/runtime.js').read_text(encoding='utf-8') + '\n' + """
const m = R.module('direct-runtime-test.ru'), loc = [1,1];
const helper = R.get(m,m.scope,'__实用',loc);
const invoke = (receiver,name,args) => R.member(m,receiver,name,()=>args.map(v=>[null,v]),loc);
const result = [];
for (const [name,args] of INVALID) {
  const source = invoke(helper,'造源',[42]); let rejected = false;
  try { invoke(source,name,args); } catch (error) {
    if (!(error instanceof R.RuError)) throw error;
    rejected = true;
  }
  if (!rejected) throw new Error('invalid random call was accepted');
  result.push(invoke(source,'整数',[0,4294967295]));
}
process.stdout.write(JSON.stringify(result));
""".replace('INVALID', json.dumps(invalid, ensure_ascii=False))
        target = self.folder/'state-validation.js'
        target.write_text(script, encoding='utf-8')
        result = subprocess.run([NODE, str(target)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), expected)

    def test_array_mutation_identity_and_equality(self):
        self.parity("""
内 取 [7]. 列 取 [空,内,0,假,2,2]. 别 取 列.
显 列 其 查 空. 显 列 其 查 内. 显 列 其 查 [7].
显 列 其 查 0. 显 列 其 查 假. 显 列 其 查 2. 显 列 其 查 9.
显 (列 其 删 位:1) == 内. 显 别. 显 别 其 弹. 显 列.
显 列 其 删 0. 显 列. 显 [] 其 查 1.
""", '0\n1\n空\n2\n3\n4\n空\n真\n[空, 0, 假, 2, 2]\n2\n[空, 0, 假, 2]\n空\n[0, 假, 2]\n空\n')

    def test_array_find_snapshot_and_element_left(self):
        self.parity("""
列 取 [].
形 项: 值 为 数.
  算 同 另一: 显 其 值. 列 其 删 0. 得 其 值 == 另一 其 值. 法
象
列 其 增 (新 项 值:1). 列 其 增 (新 项 值:2). 列 其 增 (新 项 值:3).
显 列 其 查 (新 项 值:3). 显 列.
""", '1\n2\n3\n2\n[]\n')

    def test_array_find_panic_propagates(self):
        self.parity("""
形 项: 算 同 另一: 卒 '停'. 法 象
列 取 [(新 项)]. 试 显 列 其 查 (新 项). 救 原因 显 原因. 终.
显 列 其 量.
""", '停\n1\n')

    def test_wrapper_references_and_all_imports(self):
        self.parity("""
尽取 外言 '如:文本'. 格式 取 算 定点. 显 格式 位数:2 值:1.25.
尽取 外言 '如:数学'. 平 取 算 平方根. 显 平 16. 显 整除 (-7) 3.
尽取 外言 '如:随机'. 制 取 算 造源. 源 取 制 42. 显 源 其 整数 上:10 下:1.
""", '1.25\n4\n-2\n4\n')

    def test_validation_errors_have_language_diagnostics(self):
        failures = [
            ("文 其 拆分 'a' ''.", '不能为空'),
            ("文 其 替换 'a' '' 'b'.", '不能为空'),
            ("文 其 定点 1 (-1).", '范围内整数'),
            ("文 其 定点 1 16.", '范围内整数'),
            ("文 其 定点 1 0.5.", '范围内整数'),
            ("数学 其 平方根 (-1).", '不能为负数'),
            ("数学 其 幂 (-2) 0.5.", '须为整数'),
            ("数学 其 幂 0 (-1).", '不能为负数'),
            ("数学 其 幂 1e308 2.", '不是有限数'),
            ("随 其 造源 (-1).", '范围内整数'),
            ("随 其 造源 4294967296.", '范围内整数'),
            ("源 取 随 其 造源 0. 源 其 整数 0 4294967296.", '范围不超过'),
            ("源 取 随 其 造源 0. 源 其 整数 2 1.", '范围不超过'),
            ("源 取 随 其 造源 0. 源 其 整数 0.5 1.", '范围内整数'),
            ("源 取 随 其 造源 0. 源 其 整数 0 9007199254740992.", '范围内整数'),
            ("源 取 随 其 造源 0. 源 其 整数 假 1.", '须为有限数'),
            ("源 取 随 其 造源 0. 源 其 洗牌 'abc'.", '须为阵'),
            ("[] 其 弹.", '索引越界'),
            ("[1] 其 删 (-1).", '索引越界'),
            ("[1] 其 删 1.", '索引越界'),
            ("[1] 其 删 0.5.", '索引须为整数'),
            ("[1] 其 删 假.", '索引须为整数'),
            ("形 项: 算 同 另一: 得 1. 法 象 [(新 项)] 其 查 (新 项).", '须返回事实'),
        ]
        for source, diagnostic in failures:
            with self.subTest(source=source):
                graph = self.graph(PRELUDE+source)
                with self.assertRaises(RuError):
                    self.python(graph)
                for full in (False, True):
                    status, out, error = self.javascript(graph, full=full)
                    self.assertEqual(status, 1, (out, error))
                    self.assertIn('运行错误', error)
                    self.assertIn(diagnostic, error)
                    self.assertNotRegex(error, 'ReferenceError|TypeError:|RangeError:')

    def test_optional_bridge_pruning_and_reserved_name(self):
        source = '列 取 [1,2]. 显 列 其 弹. 显 列 其 查 1.'
        graph = self.graph(source)
        code = JSCompiler(graph[graph.root], graph.root, modules=graph).compile()
        self.assertNotIn('class PracticalRandom', code)
        self.assertNotIn('function fixedText', code)
        self.assertNotIn('const practicalTypes', code)
        self.parity(source, '2\n0\n')
        for source in ('__实用 取 1.', '算 __实用: 得 1. 法', '形 __实用: 象'):
            with self.subTest(source=source), self.assertRaises(RuError):
                JSCompiler(parse(source)).compile()


if __name__ == '__main__':
    unittest.main()
