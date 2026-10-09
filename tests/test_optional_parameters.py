"""RU008: omitted parameter annotations preserve arity and backend semantics."""
import copy
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rulang.compiler import Compiler
from rulang.frontend import Incomplete, RuError, parse, validate
from rulang.interpreter import Interpreter
from rulang.js_compiler import JSCompiler
import test_closures as closures
import test_javascript as javascript
import test_shape_types as shapes


CASES = [
    ('named_function_values', '''
形 盒: 值 为 数. 象
算 回 值: 得 值. 法
显 回 空 == 空. 显 回 3. 显 回 '好'. 显 回 [1,'二',空].
显 (回 (1 对 2)) 其 囫. 显 (回 (新 盒 值:8)) 其 值.
显 (回 (算: 得 9. 法))(). (回 (作: 显 '作'. 为))().
''', '真\n3\n好\n[1, 二, 空]\n1\n8\n9\n作\n'),
    ('named_procedure', "作 报 值: 显 值. 为 报 空. 报 '好'. 报 [1,2].", '空\n好\n[1, 2]\n'),
    ('anonymous_function', "回 取 算 值: 得 值. 法. 显 回 空 == 空. 显 回 '好'. 显 回 [1,2].", '真\n好\n[1, 2]\n'),
    ('anonymous_procedure', "报 取 作 值: 显 值. 为. 报 空. 报 '好'.", '空\n好\n'),
    ('mixed_whitespace', "算 合 左 中 为 数 右: 得 [左,中,右]. 法 显 合 '甲' 2 空.", '[甲, 2, 空]\n'),
    ('mixed_commas', "合 取 算 左, 中 为 数, 右,: 得 [左,中,右]. 法. 显 合 右:空 中:2 左:'甲'.", '[甲, 2, 空]\n'),
    ('typed_array_followed_by_untyped', "算 合 列 为 数 阵 阵 后: 得 [列[0][0],后]. 法 显 合 [[3]] '好'.", '[3, 好]\n'),
    ('methods_and_bound_references', '''
形 盒: 值 为 数.
    算 回 参数: 得 参数. 法
    作 报 参数: 显 参数. 为
象
对象 取 新 盒 值:4. 显 对象 其 回 空 == 空.
回调 取 算 对象 其 回. 动作 取 作 对象 其 报.
显 回调 '好'. 动作 [1,2].
''', '真\n好\n[1, 2]\n'),
    ('nested_named_closure', '算 制 起: 算 加 步: 起 取 起+步. 得 起. 法 得 算 加. 法 回 取 制 3. 显 回 2. 显 回 步:4.', '5\n9\n'),
    ('anonymous_closure_mutation', '算 制 起: 得 算 步: 起 取 起+步. 得 起. 法. 法 回 取 制 3. 显 回 2. 显 回 步:4.', '5\n9\n'),
    ('recursion', '算 阶 值: 若 值 <= 1 则 得 1. 然 得 值*(阶 值-1). 法 显 阶 6.', '720\n'),
    ('escaping_nested_recursion', '算 制: 算 阶 值: 若 值 <= 1 则 得 1. 然 得 值*(阶 值-1). 法 得 算 阶. 法 回 取 制. 显 回 6.', '720\n'),
    ('unparenthesized_callback', '算 用 回调: 得 回调 4. 法 显 用 算 值: 得 值+1. 法.', '5\n'),
    ('standalone_reference_calls', '算 回 值: 显 值. 得 值. 法 作 报 值: 显 值. 为 参数 取 7. 算 回 参数. 算 回 值:8. 作 报 参数. 作 报 值:9.', '7\n8\n7\n9\n'),
    ('expression_reference_named_calls', '算 回 值: 得 值. 法 算 加 值: 得 值+10. 法 显 算 回 值:1. 结果 取 算 回 值:2. 显 结果. 显 (算 回 值:3). 显 加 (算 回 值:4).', '1\n2\n3\n14\n'),
    ('expression_procedure_named_calls', '作 报 值: 显 值. 为 算 用 值: 得 值 == 空. 法 显 作 报 值:1. 结果 取 作 报 值:2. 显 结果 == 空. (作 报 值:3). 显 用 (作 报 值:4).', '1\n空\n2\n真\n3\n4\n真\n'),
    ('reference_conversion', "算 回 值: 得 值. 法 作 报 值: 显 值. 为 显 算 回 为 句. 显 作 报 为 句. 显 算 回 '为'. 作 报 ':'.", '<算 回>\n<作 报>\n为\n:\n'),
    ('matching_override', '形 父: 算 查 值: 得 值. 法 象 形 子 如 父: 算 查 值: 得 值+1. 法 象 显 (新 子) 其 查 4.', '5\n'),
    ('named_argument_evaluation_order', '算 报 值: 显 值. 得 值. 法 算 合 左 右 为 数: 得 左*10+右. 法 显 合 右:(报 2) 左:(报 1).', '2\n1\n12\n'),
]

ERRORS = [
    ('named_missing', '算 回 值: 得 值. 法 回().'),
    ('named_extra', '算 回 值: 得 值. 法 回 1 2.'),
    ('named_duplicate', '算 回 值: 得 值. 法 回 值:1 值:2.'),
    ('named_unknown', '算 回 值: 得 值. 法 回 错:1.'),
    ('anonymous_missing', '回 取 算 值: 得 值. 法. 回().'),
    ('anonymous_extra', '回 取 算 值: 得 值. 法. 回 1 2.'),
    ('anonymous_unknown', '回 取 算 值: 得 值. 法. 回 错:1.'),
    ('procedure_missing', '作 报 值: 显 值. 为 报().'),
    ('method_missing', '形 盒: 算 回 值: 得 值. 法 象 (新 盒) 其 回().'),
    ('explicit_number', "算 回 任意 值 为 数: 得 值. 法 回 空 '错'."),
    ('explicit_string', '回 取 算 任意 值 为 句: 得 值. 法. 回 空 2.'),
    ('explicit_array', "算 回 任意 值 为 数 阵: 得 值. 法 回 空, [1,'错']."),
    ('explicit_callable', '算 回 任意 值 为 算: 得 值(). 法 回 空 (作: 为).'),
    ('explicit_shape', '形 盒: 象 算 回 任意 值 为 盒: 得 值. 法 回 空 2.'),
    ('shape_not_first_class', '形 盒: 象 算 回 值: 得 值. 法 回 盒.'),
    ('anonymous_shape_not_first_class', '形 盒: 象 回 取 算 值: 得 值. 法. 回 盒.'),
]


ERROR_DIAGNOSTICS = {
    'named_missing': '缺少「值」', 'named_extra': '需要 1 个位置实参',
    'named_duplicate': '重复的实参：值', 'named_unknown': '未知「错」',
    'anonymous_missing': '缺少「值」', 'anonymous_extra': '需要 1 个位置实参',
    'anonymous_unknown': '未知', 'procedure_missing': '缺少「值」',
    'method_missing': '缺少「值」', 'explicit_number': '须为数',
    'explicit_string': '须为句', 'explicit_array': '须为数 阵',
    'explicit_callable': '须为算', 'explicit_shape': '须为盒',
    'shape_not_first_class': '不能作为普通值',
    'anonymous_shape_not_first_class': '不能作为普通值',
}


class OptionalParameterSyntaxTests(unittest.TestCase):
    def test_headers_have_explicit_omission_sentinel(self):
        headers = [
            ('值', [('值', '')]),
            ('左 右', [('左', ''), ('右', '')]),
            ('左, 右,', [('左', ''), ('右', '')]),
            ('左 右 为 数 后', [('左', ''), ('右', '数'), ('后', '')]),
            ('左 为 数, 右, 后 为 句,', [('左', '数'), ('右', ''), ('后', '句')]),
            ('列 为 数 阵 阵 后', [('列', '数 阵 阵'), ('后', '')]),
        ]
        for keyword, end in (('算', '法'), ('作', '为')):
            for header, expected in headers:
                with self.subTest(keyword=keyword, header=header):
                    named = parse(f'{keyword} 回 {header}: {end}')[0]
                    anonymous = parse(f'回 取 {keyword} {header}: {end}.')[0].data['expr']
                    self.assertEqual(named.data['params'], expected)
                    self.assertEqual(anonymous.kind, 'function_literal')
                    self.assertEqual(anonymous.data['params'], expected)

    def test_reference_disambiguation(self):
        for keyword in ('算', '作'):
            with self.subTest(keyword=keyword):
                expr = parse(f'回 取 {keyword} 已有.')[0].data['expr']
                self.assertEqual(expr.kind, 'function_ref')
                expr = parse(f'显 {keyword} 已有 为 句.')[0].data['expr']
                self.assertEqual(expr.kind, 'convert')
                self.assertEqual(expr.data['expr'].kind, 'function_ref')

    def test_repeated_named_reference_calls_parse_without_exponential_backtracking(self):
        # A named reference call also resembles an untyped declaration prefix.
        # Independent declarations after it must not cause repeated speculative
        # parsing of the entire remaining program. Isolate the timeout so a
        # parser regression cannot hang the test runner.
        source = ('作 报 内容: 显 内容. 为\n' +
                  '作 报 内容:1.\n' * 100 +
                  '算 后 值: 得 值. 法\n显 后 2.\n')
        result = subprocess.run(
            [sys.executable, '-c',
             'import sys; from rulang.frontend import parse; '
             'print(len(parse(sys.stdin.read())))'],
            input=source, cwd=ROOT, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '103\n')

    def test_speculative_references_do_not_bypass_nesting_limit(self):
        source = ('作 报 内容: 显 内容. 为\n' +
                  '作 报 内容:1.\n' * 20 +
                  '显 ' + '(' * 140 + '1' + ')' * 140 + '.')
        script = (
            'import sys\nfrom rulang.frontend import parse, RuError\n'
            'try:\n    parse(sys.stdin.read())\n'
            'except RuError as error:\n    print(error.message)\n'
            'else:\n    raise AssertionError("nesting limit was bypassed")\n')
        result = subprocess.run([sys.executable, '-c', script], input=source,
                                cwd=ROOT, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('嵌套过深', result.stdout)
        self.assertNotIn('RecursionError', result.stderr)

    def test_incomplete_bodies_are_continuable(self):
        for source in ('算 回 值:', '作 报 值:', '回 取 算 值:',
                       '回 取 作 值:', '算 回 左 右 为', '回 取 算 左 右 为',
                       '回 取 作 内容: 显 内容.'):
            with self.subTest(source=source), self.assertRaises(Incomplete):
                parse(source)

    def test_invalid_parameters_and_explicit_types(self):
        sources = [
            '算 回 值 值: 得 值. 法',
            '回 取 算 值, 值 为 数: 得 值. 法.',
            '作 报 读: 为',
            '形 盒: 象 算 回 盒: 得 1. 法',
            '算 已有: 得 1. 法 算 回 已有: 得 1. 法',
            '算 回 内: 算 内: 得 1. 法 得 1. 法',
            '算 回 值 为 不存在: 得 值. 法',
            '回 取 算 值 为 不存在 阵: 得 值. 法.',
            '算 回 值 为: 得 值. 法',
            '算 回 值 为 数 为 句: 得 值. 法',
            '算 回 1: 得 1. 法',
            '回 取 算 值: 得 值. 为.',
        ]
        for source in sources:
            for consumer in (validate, lambda p: Compiler(p).compile(),
                             lambda p: JSCompiler(p).compile()):
                with self.subTest(source=source, consumer=consumer), self.assertRaises(RuError):
                    consumer(parse(source))

    def test_compilers_preserve_ast(self):
        program = parse('算 制 起: 得 算 步 为 数 后: 得 [起+步,后]. 法. 法')
        original = copy.deepcopy(program)
        Compiler(program).compile()
        self.assertEqual(program, original)
        JSCompiler(program).compile()
        self.assertEqual(program, original)

    def test_override_requires_exact_annotation_and_parameter_signature(self):
        for parent, child in (('值', '值 为 数'), ('值 为 数', '值'),
                              ('值', '别名'), ('值 后 为 数', '值 后')):
            source = (f'形 父: 算 回 {parent}: 得 1. 法 象 '
                      f'形 子 如 父: 算 回 {child}: 得 2. 法 象')
            for backend in (Interpreter, Compiler, JSCompiler):
                with self.subTest(parent=parent, child=child, backend=backend.__name__):
                    with self.assertRaises(RuError) as caught:
                        if backend is Interpreter:
                            backend(io.StringIO(), io.StringIO()).execute(parse(source))
                        else:
                            backend(parse(source)).compile()
                    self.assertIn('覆写方法', caught.exception.message)


class OptionalParameterParityTests(unittest.TestCase):
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

    def test_interpreter_errors(self):
        for name, source in ERRORS:
            with self.subTest(name=name):
                parse(source)  # An unrelated syntax failure is not a runtime regression test.
                with self.assertRaises(RuError) as caught:
                    closures.interpreted(source)
                self.assertIn(ERROR_DIAGNOSTICS[name], caught.exception.message)

    @unittest.skipUnless(closures.CC, 'C compiler unavailable')
    def test_native_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, source in ERRORS:
                with self.subTest(name=name):
                    try:
                        result = closures.native(source, directory, name)
                    except RuError as error:
                        self.assertIn(ERROR_DIAGNOSTICS[name], error.message)
                        continue
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('运行错误', result.stderr)
                    self.assertIn(ERROR_DIAGNOSTICS[name], result.stderr)
                    self.assertIn('RU_GC live=0 ', result.stderr)

    @unittest.skipUnless(javascript.NODE, 'Node.js unavailable')
    def test_javascript_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, source in ERRORS:
                with self.subTest(name=name):
                    try:
                        output, _ = javascript.compiled(source, directory, name)
                    except RuError as error:
                        self.assertIn(ERROR_DIAGNOSTICS[name], error.message)
                        continue
                    status, _, error = javascript.node_run(output)
                    self.assertEqual(status, 1, error)
                    self.assertIn('运行错误', error)
                    self.assertIn(ERROR_DIAGNOSTICS[name], error)
                    self.assertNotIn('Traceback', error)

    @unittest.skipUnless(closures.CC, 'C compiler unavailable')
    def test_native_untyped_closure_gc_stress(self):
        source = '''
算 制 起:
    环列 取 [].
    回 取 算 步: 起 取 起+步. 得 起. 法.
    环列 其 增 回. 环列 其 增 环列.
    得 回.
法
回调 取 制 0.
循 500 次 回调 取 制 10. 显值 取 回调 1. 环
显 回调 2. 回调 取 空.
'''
        with tempfile.TemporaryDirectory() as directory:
            result = closures.native(source, directory, 'stress')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '13\n')
        self.assertIn('RU_GC live=0 ', result.stderr)


class OptionalParameterIntegrationTests(unittest.TestCase):
    graph = shapes.ShapeTypeTests.graph
    interpreted = shapes.ShapeTypeTests.interpreted
    assert_engines = shapes.ShapeTypeTests.assert_engines
    assert_rejected_engines = shapes.ShapeTypeTests.assert_rejected_engines

    def test_imported_types_with_mixed_parameters(self):
        self.assert_engines({
            'models.ru': '形 盒: 值 为 数. 象 算 制 值: 得 新 盒 值:值. 法 '
                         '算 查 物 为 盒 后: 得 [(物 其 值),后]. 法 '
                         '算 制回: 得 算 物 为 盒 后: 得 [(物 其 值),后]. 法. 法',
            'main.ru': "模 取 外言 'models.ru'. 物 取 模 其 制 4. "
                       '显 模 其 查 物 空. 回 取 模 其 制回. 显 回 物 5.',
        }, '[4, 空]\n[4, 5]\n')

    def test_import_does_not_hide_unknown_explicit_annotation(self):
        self.assert_rejected_engines({
            'empty.ru': '',
            'main.ru': "尽 取 外言 'empty.ru'. 算 回 任意 值 为 未知 阵: 得 1. 法 显 回 空, [].",
        }, '未定义类型：未知')

    def test_imported_shape_is_still_not_first_class(self):
        self.assert_rejected_engines({
            'models.ru': '形 盒: 象',
            'main.ru': "模 取 外言 'models.ru'. 算 回 值: 得 值. 法 回 (模 其 盒).",
        }, '不能作为普通值')

    def test_repl_untyped_definition_and_explicit_type_error_recovery(self):
        commands = ("算 回 值: 得 值. 法\n显 回 空 == 空.\n显 回 '好'.\n"
                    "算 数回 值 为 数: 得 值. 法\n数回 '错'.\n显 回 7.\n:quit\n")
        result = subprocess.run([sys.executable, str(ROOT / 'ru'), 'repl'],
                                input=commands, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '真\n好\n7\n')
        self.assertIn('须为数', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_notebook_untyped_definition_across_cells(self):
        from rushu.kernel import Session
        session = Session()
        self.addCleanup(session.close)

        def cell(source):
            after = session.snapshot()['cursor']
            session.execute(source, 'optional-parameter-test')
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                result = session.poll(after)
                if result['state'] == 'idle':
                    return result
                self.assertNotEqual(result['state'], 'dead', result)
                time.sleep(.01)
            self.fail('Notebook cell timed out')

        self.assertEqual(cell('算 回 值: 得 值. 法')['events'][-1]['status'], 'ok')
        result = cell("显 回 空 == 空. 显 回 '好'.")
        self.assertEqual(result['events'][-1]['status'], 'ok')
        self.assertEqual(''.join(e['text'] for e in result['events'] if e['type'] == 'output'), '真\n好\n')
        self.assertEqual(cell('回().')['events'][-1]['status'], 'error')
        self.assertEqual(cell('显 回 7.')['events'][-1]['status'], 'ok')


if __name__ == '__main__':
    unittest.main()
