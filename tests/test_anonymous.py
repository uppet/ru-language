"""Anonymous 算/作 literals: grammar, lexical closures, and backend parity."""
import copy
import gc
import io
from pathlib import Path
import re
import sys
import tempfile
import unittest
import weakref

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rulang.compiler import Compiler
from rulang.frontend import Incomplete, RuError, parse, validate
from rulang.interpreter import Interpreter
from rulang.js_compiler import JSCompiler
from rulang.modules import load_module_graph
import test_closures as closures
import test_javascript as javascript
import test_runtime_pruning as pruning


COUNTER = '''
算 制数 起 为 数:
    得 算 步 为 数:
        起 取 起 + 步.
        得 起.
    法.
法
'''

CASES = [
    ('square', '平方 取 算 值 为 数: 得 值 * 值. 法. 显 (平方 7).', '49\n'),
    ('reference_conversion_preserved', "算 回: 显 '不应调用'. 得 1. 法 作 报: 显 '不应调用'. 为 显 算 回 为 句. 显 作 报 为 句.", '<算 回>\n<作 报>\n'),
    ('mixed_parameter_types', '形 盒: 值 为 数. 象 合 取 算 物 为 盒 回 为 算 列 为 数 阵: 得 (回 (物 其 值))+列[0]. 法. 显 (合 (新 盒 值:4), (算 根 为 数: 得 根*2. 法), [3]).', '11\n'),
    ('procedure_parameter_type', "用 取 作 动 为 作: 动(). 为. 用 (作: 显 '好'. 为).", '好\n'),
    ('nested_array_parameter_type', '回 取 算 列 为 数 阵 阵: 得 列[0][1]. 法. 显 (回 [[1,2]]).', '2\n'),
    ('trailing_parameter_comma', '合 取 算 左 为 数, 右 为 数,: 得 左+右. 法. 显 (合 2 3).', '5\n'),
    ('zero_literal_positional_argument', '算 用 回调 为 算: 得 回调(). 法 显 用 算: 得 7. 法.', '7\n'),
    ('zero_procedure_positional_argument', "作 用 回调 为 作: 回调(). 为 用 作: 显 '好了'. 为.", '好了\n'),
    ('standalone_literal_is_not_called', '值 取 1. 作: 值 为 数. 显 99. 为. 显 值.', '1\n'),
    ('reference_string_arguments', "算 回声 值 为 句: 得 值. 法 显 算 回声 '为'. 显 算 回声 ':'. 作 报 值 为 句: 显 值. 为 作 报 '为'. 作 报 ':'.", '为\n:\n为\n:\n'),
    ('literal_only_runtime_features', '回 取 算 值 为 数: 列 取 [值%3]. 列 其 增 9. 得 列 其 量. 法. 显 (回 7).', '2\n'),
    ('typed_procedure', "问候 取 作 名 为 句: 显 ('你好，' + 名). 为. 问候 '世界'.", '你好，世界\n'),
    ('zero_calls', "报到 取 作: 显 '到了'. 为. 报到(). 显 报到() == 空. 回答 取 算: 得 42. 法. 显 回答().", '到了\n到了\n真\n42\n'),
    ('named_arguments', '差 取 算 左 为 数 右 为 数: 得 左-右. 法. 显 (差 右:2 左:9).', '7\n'),
    ('comma_parameters', '合 取 算 左 为 数, 右 为 数: 得 左+右. 法. 显 (合 2, 3).', '5\n'),
    ('immediate_calls', '显 ((算 值 为 数: 得 值+1. 法) 4). 显 (算: 得 8. 法)().', '5\n8\n'),
    ('literal_array_and_index', "列 取 [算 值 为 数: 得 值+2. 法, 作: 显 '作'. 为]. 显 (列[0] 3). 列[1](). 列[0] 取 算: 得 9. 法. 显 列[0]().", '5\n作\n9\n'),
    ('literal_pair', '对值 取 (算: 得 7. 法) 对 空. 显 (对值 其 囫)().', '7\n'),
    ('positional_callback', '算 用 回调 为 算 值 为 数: 得 回调 值. 法 显 (用 (算 根 为 数: 得 根*2. 法) 6).', '12\n'),
    ('named_callback', '算 用 回调 为 算 值 为 数: 得 回调 值. 法 显 (用 值:6 回调:(算 根 为 数: 得 根+3. 法)).', '9\n'),
    ('unparenthesized_callback', '算 用 回调 为 算: 得 回调 5. 法 显 用 算 值 为 数: 得 值+1. 法.', '6\n'),
    ('callback_body_call_context', '算 加 值 为 数: 得 值+2. 法 算 用 回调 为 算: 得 回调 3. 法 显 (用 (算 值 为 数: 得 加 值. 法)).', '5\n'),
    ('typed_callback_array', '算 用 列 为 算 阵: 得 列[0] 3. 法 显 (用 [算 值 为 数: 得 值+2. 法]).', '5\n'),
    ('returned_mutating_closure', COUNTER + '甲 取 制数 10. 乙 取 制数 100. 显 (甲 1). 显 (甲 2). 显 (乙 5). 显 (甲 3).', '11\n13\n105\n16\n'),
    ('sibling_shared_cell', '算 制: 值 取 0. 得 [作 新值 为 数: 值 取 新值. 为, 算: 得 值. 法]. 法 组 取 制. 组[0] 7. 显 组[1](). 组[0] 新值:9. 显 组[1]().', '7\n9\n'),
    ('named_anonymous_shared_cell', '算 制: 值 取 0. 算 看: 得 值. 法 得 [作 新值 为 数: 值 取 新值. 为, 算 看]. 法 组 取 制. 组[0] 7. 显 组[1]().', '7\n'),
    ('parent_mutates_after_capture', '算 制: 值 取 1. 回 取 算: 得 值. 法. 值 取 8. 得 回. 法 回调 取 制. 显 回调().', '8\n'),
    ('three_lexical_levels', '算 外 起 为 数: 得 算 步 为 数: 得 算: 起 取 起+步. 得 起. 法. 法. 法 工厂 取 外 10. 甲 取 工厂 2. 乙 取 工厂 3. 显 甲(). 显 乙(). 显 甲().', '12\n15\n17\n'),
    ('lexical_not_dynamic', '算 制: 值 取 5. 得 算: 得 值. 法. 法 算 用 回调 为 算: 值 取 99. 得 回调(). 法 回调 取 制. 显 (用 回调).', '5\n'),
    ('parameter_shadows_capture', '算 制: 值 取 10. 得 [算 值 为 数: 值 取 值+1. 得 值. 法, 算: 得 值. 法]. 法 组 取 制. 显 (组[0] 2). 显 组[1]().', '3\n10\n'),
    ('fresh_identity', '算 制: 得 算: 得 1. 法. 法 甲 取 制. 别名 取 甲. 乙 取 制. 显 甲 == 别名. 显 甲 == 乙. 显 非 甲. 显 甲. 显 [甲,甲].', '真\n假\n假\n<算 <匿名>>\n[<算 <匿名>>, <算 <匿名>>]\n'),
    ('loop_evaluation_is_fresh', '列 取 []. 循 2 次 列 其 增 算: 得 7. 法. 环 显 列[0] == 列[1]. 显 列[0](). 显 列[1]().', '假\n7\n7\n'),
    ('flow_literal_placement', "列 取 []. 若 1 则 列 其 增 算: 得 1. 法. 然 循 1 次 列 其 增 算: 得 2. 法. 环 试 列 其 增 算: 得 3. 法. 救 原因 终. 显 列[0](). 显 列[1](). 显 列[2]().", '1\n2\n3\n'),
    ('nested_named_function', '工厂 取 算 起 为 数: 算 加 步 为 数: 起 取 起+步. 得 起. 法 得 算: 得 加 2. 法. 法. 回调 取 工厂 3. 显 回调(). 显 回调().', '5\n7\n'),
    ('forward_nested_reference', '工厂 取 算: 得 算 后. 算 后: 得 7. 法 法. 回调 取 工厂(). 显 回调().', '7\n'),
    ('nested_named_recursion', '工厂 取 算: 算 阶 根 为 数: 若 根 <= 1 则 得 1. 然 得 根*(阶 根-1). 法 得 算 值 为 数: 得 阶 值. 法. 法. 回调 取 工厂(). 显 (回调 6).', '720\n'),
    ('own_loop_break', '回调 取 算: 值 取 0. 循 3 次 值 取 值+1. 破. 环 得 值. 法. 显 回调().', '1\n'),
    ('procedure_inner_function_return', '报 取 作: 回 取 算: 得 4. 法. 显 回(). 为. 报().', '4\n'),
    ('rescue_capture', "列 取 []. 试 卒 '因'. 救 原因 列 其 增 算: 原因 取 原因+'!'. 得 原因. 法. 终. 显 列[0](). 显 列[0]().", '因!\n因!!\n'),
    ('panic_escape_keeps_capture', "列 取 []. 作 制 存 为 阵: 值 取 40. 存 其 增 算: 值 取 值+1. 得 值. 法. 卒 '跳出'. 为 试 制 列. 救 原因 显 原因. 终. 显 列[0](). 显 列[0]().", '跳出\n41\n42\n'),
    ('object_callback_fields', "形 盒: 回调 为 算. 动作 为 作. 象 盒值 取 新 盒 回调:(算 值 为 数: 得 值+1. 法) 动作:(作: 显 '作'. 为). 显 (盒值 其 回调 4). (盒值 其 动作)().", '5\n作\n'),
    ('method_self_capture', '形 计: 值 为 数. 算 制 步 为 数: 得 算: 其 值 取 其 值+步. 得 其 值. 法. 法 象 对象 取 新 计 值:2. 回调 取 对象 其 制 3. 对象 取 空. 显 回调(). 显 回调().', '5\n8\n'),
    ('nested_method_self_capture', '形 计: 值 为 数. 算 制: 得 算 步 为 数: 得 作: 其 值 取 其 值+步. 显 其 值. 为. 法. 法 象 对象 取 新 计 值:2. 工厂 取 对象 其 制. 回调 取 工厂 3. 对象 取 空. 工厂 取 空. 回调(). 回调().', '5\n8\n'),
    ('argument_evaluation_order', '算 报 值 为 数: 显 值. 得 值. 法 回调 取 算 左 为 数 右 为 数: 得 左*10+右. 法. 显 (回调 右:(报 2) 左:(报 1)).', '2\n1\n12\n'),
    ('callee_before_arguments', '列 取 [算 值 为 数: 得 100+值. 法]. 算 改: 列[0] 取 算 值 为 数: 得 200+值. 法. 得 1. 法 显 (列[0] 改). 显 (列[0] 2).', '101\n202\n'),
    ('named_references_preserved', "算 加 值 为 数: 得 值+1. 法 作 报: 显 '好'. 为 甲 取 算 加. 乙 取 作 报. 显 (甲 4). 乙().", '5\n好\n'),
    ('contest_sort_callback', "竞 取 外言 '如:竞赛'. 显 (竞 其 排序 [3,1,2,1] (算 左 为 数 右 为 数: 得 右-左. 法)).", '[3, 2, 1, 1]\n'),
]

# Reject these even if the literal is never evaluated or invoked. In particular,
# an enclosing loop/function cannot grant break/return permission to its body.
STRUCTURAL_ERRORS = [
    ('duplicate_parameters', '回 取 算 值 为 数 值 为 数: 得 值. 法.'),
    ('builtin_parameter', '回 取 算 读 为 数: 得 1. 法.'),
    ('named_function_parameter', '算 已有: 得 1. 法 回 取 算 已有 为 数: 得 1. 法.'),
    ('type_parameter', '形 盒: 象 回 取 算 盒 为 数: 得 1. 法.'),
    ('nested_function_parameter', '回 取 算 内 为 数: 算 内: 得 1. 法 得 1. 法.'),
    ('undefined_parameter_type', '回 取 算 值 为 不存在: 得 值. 法.'),
    ('procedure_return', '回 取 作: 得 1. 为.'),
    ('nested_procedure_return', '算 外: 得 作: 得 1. 为. 法'),
    ('break_without_loop', '回 取 算: 破. 得 1. 法.'),
    ('break_crosses_literal_boundary', '循 1 次 回 取 算: 破. 得 1. 法. 环'),
    ('break_crosses_nested_boundary', '回 取 算: 循 1 次 内 取 作: 破. 为. 环 得 0. 法.'),
    ('self_outside_method', '回 取 算: 得 其 值. 法.'),
    ('nested_type', '回 取 算: 形 内: 象 得 0. 法.'),
    ('nested_import_all', "回 取 算: 尽 取 外言 '如:竞赛'. 得 0. 法."),
    ('conditional_named_declaration', '回 取 算: 若 1 则 算 内: 得 1. 法 然 得 0. 法.'),
    ('protected_binding', '算 已有: 得 1. 法 回 取 算: 已有 取 2. 得 0. 法.'),
]

RUNTIME_ERRORS = [
    ('missing_argument', '回 取 算 值 为 数: 得 值. 法. 回().'),
    ('extra_argument', '回 取 算 值 为 数: 得 值. 法. 回 1 2.'),
    ('unknown_argument', '回 取 算 值 为 数: 得 值. 法. 回 错名:1.'),
    ('wrong_argument_type', "回 取 算 值 为 数: 得 值. 法. 回 '错'."),
    ('procedure_as_function', '算 用 回 为 算: 得 回(). 法 用 (作: 显 1. 为).'),
    ('function_as_procedure', '作 用 回 为 作: 回(). 为 用 (算: 得 1. 法).'),
    ('wrong_array_element', '算 用 列 为 算 阵: 得 1. 法 用 [作: 显 1. 为].'),
    ('undefined_captured_name', '回 取 算: 得 不存在. 法. 回().'),
]

STRESS = '''
算 制 起 为 数:
    环列 取 [].
    回 取 算: 起 取 起+1. 得 起. 法.
    环列 其 增 回.
    环列 其 增 环列.
    得 回.
法
作 中断 存 为 阵:
    临时 取 制 7.
    存 其 增 临时.
    卒 '逃出'.
为
回调 取 制 0.
循 500 次
    回调 取 制 10.
    列 取 [].
    试 中断 列. 救 原因
        若 列[0]() != 8 则 卒 '捕获损坏'. 然
    终.
    列 取 空.
环
显 回调().
回调 取 空.
'''


class AnonymousSyntaxTests(unittest.TestCase):
    def test_function_literal_ast_and_reference_disambiguation(self):
        program = parse('回 取 算 值 为 数: 得 值*值. 法. 作 报: 为 动 取 作 报.')
        literal = program[0].data['expr']
        self.assertEqual(literal.kind, 'function_literal')
        self.assertEqual(literal.data['name'], '<匿名>')
        self.assertEqual(literal.data['params'], [('值', '数')])
        self.assertFalse(literal.data['procedure'])
        self.assertEqual(literal.data['body'][0].kind, 'return')
        self.assertEqual(literal.token.value, '算')
        self.assertEqual(program[2].data['expr'].kind, 'function_ref')
        procedure = parse('回 取 作: 显 1. 为.')[0].data['expr']
        self.assertEqual(procedure.kind, 'function_literal')
        self.assertEqual(procedure.data['name'], '<匿名>')
        self.assertEqual(procedure.data['params'], [])
        self.assertTrue(procedure.data['procedure'])

    def test_reference_conversion_remains_distinct_from_literal(self):
        for keyword in ('算', '作'):
            with self.subTest(keyword=keyword):
                converted = parse(f'显 {keyword} 已有 为 句.')[0].data['expr']
                self.assertEqual(converted.kind, 'convert')
                self.assertEqual(converted.data['target'], '句')
                reference = converted.data['expr']
                self.assertEqual(reference.kind, 'function_ref')
                self.assertEqual(reference.data['procedure'], keyword == '作')
                self.assertEqual(reference.data['expr'].data['name'], '已有')

    def test_complete_typed_headers_are_literals(self):
        headers = [
            ('值 为 数', [('值', '数')]),
            ('名 值 为 数', [('名', ''), ('值', '数')]),
            ('左 为 数 右 为 数', [('左', '数'), ('右', '数')]),
            ('物 为 盒', [('物', '盒')]),
            ('回 为 算 动 为 作', [('回', '算'), ('动', '作')]),
            ('列 为 数 阵 阵', [('列', '数 阵 阵')]),
            ('列 为 算 阵', [('列', '算 阵')]),
            ('左 为 数, 右 为 数,', [('左', '数'), ('右', '数')]),
        ]
        for keyword, end in (('算', '法'), ('作', '为')):
            for header, params in headers:
                with self.subTest(keyword=keyword, header=header):
                    literal = parse(f'回调 取 {keyword} {header}: {end}.')[0].data['expr']
                    self.assertEqual(literal.kind, 'function_literal')
                    self.assertEqual(literal.data['params'], params)
                    self.assertEqual(literal.data['procedure'], keyword == '作')

    def test_standalone_literal_with_conversion_body(self):
        program = parse('值 取 1. 作: 值 为 数. 为.')
        self.assertEqual(len(program), 2)
        self.assertEqual(program[1].kind, 'expr')
        literal = program[1].data['expr']
        self.assertEqual(literal.kind, 'function_literal')
        self.assertTrue(literal.data['procedure'])
        self.assertEqual(literal.data['body'][0].data['expr'].kind, 'convert')

    def test_literal_terminator_does_not_consume_containing_expression(self):
        for source in (
            '回 取 [算: 得 1. 法, 算: 得 2. 法].',
            '显 (算: 得 1. 法)().',
            '回 取 (算: 得 1. 法) 对 空.',
            '回 取 算: 得 算: 得 1. 法. 法.',
        ):
            with self.subTest(source=source):
                validate(parse(source))

    def test_missing_colon_or_mismatched_end_is_rejected(self):
        for source in (
            '回 取 算 值 为 数 得 值. 法.',
            '回 取 作 名 为 句 显 名. 为.',
            '回 取 算 得 1. 法.',
            '回 取 作 显 1. 为.',
            '回 取 算: 得 1. 为.',
            '回 取 作: 显 1. 法.',
        ):
            with self.subTest(source=source), self.assertRaises(RuError):
                parse(source)

    def test_missing_end_is_incomplete_for_repl(self):
        for source in ('回 取 算: 得 1.', '回 取 作: 显 1.',
                       '回 取 算 值 为 数: 得 值.'):
            with self.subTest(source=source), self.assertRaises(Incomplete):
                parse(source)

    def test_incomplete_literal_headers_remain_continuable_in_repl(self):
        headers = ('x 为 算', 'x 为 数 阵', 'x 为 数 y 为 数',
                   'x 为 数,', 'x 为', 'x 为 数 y')
        for keyword in ('算', '作'):
            for header in headers:
                source = f'f 取 {keyword} {header}'
                with self.subTest(source=source), self.assertRaises(Incomplete):
                    parse(source)

    def test_structural_errors_in_all_consumers(self):
        for name, source in STRUCTURAL_ERRORS:
            for consumer in (validate, lambda p: Compiler(p).compile(),
                             lambda p: JSCompiler(p).compile()):
                with self.subTest(name=name, consumer=consumer), self.assertRaises(RuError):
                    consumer(parse(source))

    def test_compilers_do_not_mutate_literal_ast(self):
        program = parse(COUNTER + '回 取 制数 3. 显 (回 2).')
        before = copy.deepcopy(program)
        Compiler(program).compile()
        self.assertEqual(program, before)
        JSCompiler(program).compile()
        self.assertEqual(program, before)


class AnonymousParityTests(unittest.TestCase):
    def test_interpreter_cases(self):
        for name, source, expected in CASES:
            with self.subTest(name=name):
                self.assertEqual(closures.interpreted(source), expected)

    @unittest.skipUnless(closures.CC, 'C compiler unavailable')
    def test_native_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, source, expected in CASES:
                with self.subTest(name=name):
                    result = closures.native(source, directory, name)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, expected)
                    self.assertIn('RU_GC live=0 ', result.stderr)

    @unittest.skipUnless(javascript.NODE, 'Node.js unavailable')
    def test_javascript_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, source, expected in CASES:
                with self.subTest(name=name):
                    output, _ = javascript.compiled(source, directory, name)
                    self.assertEqual(javascript.node_run(output), (0, expected, ''))

    def test_interpreter_runtime_errors(self):
        for name, source in RUNTIME_ERRORS:
            with self.subTest(name=name), self.assertRaises(RuError):
                closures.interpreted(source)

    @unittest.skipUnless(closures.CC, 'C compiler unavailable')
    def test_native_runtime_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, source in RUNTIME_ERRORS:
                with self.subTest(name=name):
                    try:
                        result = closures.native(source, directory, name)
                    except RuError:
                        continue
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('运行错误', result.stderr)
                    self.assertIn('RU_GC live=0 ', result.stderr)

    @unittest.skipUnless(javascript.NODE, 'Node.js unavailable')
    def test_javascript_runtime_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, source in RUNTIME_ERRORS:
                with self.subTest(name=name):
                    try:
                        output, _ = javascript.compiled(source, directory, name)
                    except RuError:
                        continue
                    status, _, error = javascript.node_run(output)
                    self.assertEqual(status, 1, error)
                    self.assertIn('运行错误', error)
                    self.assertRegex(error, r':\d+:\d+:')
                    self.assertNotIn('Traceback', error)
                    self.assertNotIn('ReferenceError', error)
                    self.assertNotIn('TypeError:', error)

    def test_module_literal_preserves_owning_globals(self):
        with tempfile.TemporaryDirectory() as directory:
            child = Path(directory).resolve() / 'factory.ru'
            child.write_text('基 取 100. ' + COUNTER.replace('得 起.', '得 起+基.'), encoding='utf-8')
            root = Path(directory).resolve() / 'main.ru'
            source = "基 取 999. 模 取 外言 'factory.ru'. 回调 取 模 其 制数 2. 显 (回调 3). 显 (回调 4)."
            root.write_text(source, encoding='utf-8')
            graph = load_module_graph(root)
            expected = '105\n109\n'
            self.assertEqual(closures.interpreted(source, root, graph), expected)
            if javascript.NODE:
                output, _ = javascript.compiled(source, directory, 'module', root, graph)
                self.assertEqual(javascript.node_run(output), (0, expected, ''))
            if closures.CC:
                result = closures.native(source, directory, 'module', root, graph,
                                         remove_sources=(root, child))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)
                self.assertIn('RU_GC live=0 ', result.stderr)


class AnonymousOwnershipTests(unittest.TestCase):
    def test_interpreter_cycles_reclaimed(self):
        runtime = Interpreter(io.StringIO(), io.StringIO())
        runtime.execute(parse(COUNTER + '回调 取 制数 3.'))
        callback = runtime.global_scope.values['回调']
        reference = weakref.ref(callback)
        runtime.execute(parse('回调 取 空.'))
        del callback
        gc.collect()
        self.assertIsNone(reference())

    @unittest.skipUnless(closures.CC, 'C compiler unavailable')
    def test_gc_reclaims_anonymous_cycles_before_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            result = closures.native(STRESS, directory, 'stress', inspect_heap=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '11\n')
            match = re.search(r'BEFORE_SHUTDOWN live=(\d+) freed=(\d+)', result.stderr)
            self.assertIsNotNone(match, result.stderr)
            self.assertLess(int(match[1]), 100, result.stderr)
            self.assertGreater(int(match[2]), 2000, result.stderr)
            self.assertIn('RU_GC live=0 ', result.stderr)

    @unittest.skipUnless(closures.CC, 'C compiler unavailable')
    def test_pruned_and_full_runtime_with_forced_gc(self):
        selected = {'returned_mutating_closure', 'sibling_shared_cell',
                    'method_self_capture', 'nested_method_self_capture',
                    'panic_escape_keeps_capture', 'contest_sort_callback',
                    'literal_only_runtime_features'}
        with tempfile.TemporaryDirectory() as directory:
            for name, source, expected in CASES + [('stress', STRESS, '11\n')]:
                if name not in selected and name != 'stress':
                    continue
                results = []
                for full in (False, True):
                    with self.subTest(name=name, full=full):
                        generated = pruning.generate(source, full=full)
                        binary = pruning.build(generated, directory, name + str(full))
                        result = pruning.run(binary)
                        self.assertIn('RU_GC live=0 ', result.stderr)
                        clean_error = pruning.GC_STATS.sub('', result.stderr)
                        results.append((result.returncode, result.stdout, clean_error))
                        self.assertEqual(results[-1], (0, expected, ''))
                self.assertEqual(results[0], results[1])

    def test_features_used_only_inside_literal_are_retained(self):
        source = "回 取 算 值 为 数: 列 取 [值%3]. 列 其 增 9. 得 列 其 量. 法. 显 (回 7)."
        code = pruning.generate(source)
        self.assertIn('#define RU_ENABLE_MODULO 1', code)
        self.assertNotIn('ru_io_list(', code)
        self.assertNotIn('ru_contest_sort(', code)
        self.assertLess(len(code), len(pruning.generate(source, full=True)))
        self.assertNotIn('function fileIO(', JSCompiler(parse(source)).compile())
        self.assertNotIn('class Scanner', JSCompiler(parse(source)).compile())
        # Callable annotations buried inside an expression still select I/O.
        typed = '回 取 算 值 为 件: 得 1. 法. 显 1.'
        self.assertIn('static RuClass ru_io_file_class', pruning.generate(typed))
        self.assertIn('function fileIO(', JSCompiler(parse(typed)).compile())


if __name__ == '__main__':
    unittest.main()
