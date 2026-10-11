"""RU-011/012: explicit procedure completion and null results on every backend."""
import io
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rulang.frontend import Incomplete, RuError, parse, validate
from rulang.compiler import Compiler
from rulang.interpreter import Interpreter
from rulang.js_compiler import JSCompiler
from rulang.modules import load_module_graph
from rulang.stdlib_pruning import prune_bundled_stdlib
import test_closures as closures
import test_javascript as javascript
import test_runtime_pruning as pruning

CASES = [
    ('natural', "作 停: 为 显 停. 显 停 == 空. 显 停 == ''. 显 非 停. 显 [停, 停 对 空].", '空\n真\n假\n真\n[空, (空 对 空)]\n'),
    ('null_parameter', '作 停: 完. 为 算 用 值 为 空: 得 值 == 空. 法 显 用 停.', '真\n'),
    ('early', "作 停: 显 1. 完. 显 2. 为 显 停. 显 3.", '1\n空\n3\n'),
    ('punctuation', '作 停：完。显 9。为 显 停。', '空\n'),
    ('branch', '作 停 值 为 事实: 若 值 则 完. 另 显 7. 然 显 8. 为 显 停 真. 显 停 假.', '空\n7\n8\n空\n'),
    ('loops', '作 停: 循 3 次 循 显 1. 完. 环 显 2. 环 显 3. 为 显 停.', '1\n空\n'),
    ('try_body', "作 停: 试 循 完. 环 救 因 显 '不应捕获'. 终. 显 9. 为 试 显 停. 救 因 显 因. 终.", '空\n'),
    ('rescue', "作 停: 试 卒 '外'. 救 外因 循 2 次 试 卒 '内'. 救 内因 显 外因+内因. 完. 终. 环 终. 显 9. 为 显 停.", '外内\n空\n'),
    ('nested_procedures', '作 外: 作 内: 完. 显 9. 为 显 内. 显 2. 完. 显 3. 为 显 外.', '空\n2\n空\n'),
    ('nested_function', '作 外: 算 内: 得 5. 法 显 内. 完. 为 显 外.', '5\n空\n'),
    ('anonymous', '回 取 作: 完. 显 9. 为. 显 回(). 显 (作: 为)().', '空\n空\n'),
    ('nested_literal', '算 制: 得 作: 内 取 作: 完. 为. 内(). 显 2. 完. 为. 法 回 取 制. 显 回().', '2\n空\n'),
    ('method', '形 盒: 作 停: 完. 显 9. 为 象 盒值 取 新 盒. 显 盒值 其 停. 回 取 作 盒值 其 停. 显 回().', '空\n空\n'),
    ('whole_identifiers', '完成 取 3. 完毕 取 4. 作 完事: 显 完成+完毕. 完. 为 显 完事.', '7\n空\n'),
    ('return_unchanged', "算 空句: 得 ''. 法 算 空值: 得 空. 法 显 空句 == ''. 显 空值 == 空.", '真\n真\n'),
    ('recursion', '作 递 层 为 数: 若 层 == 0 则 完. 然 显 (递 层-1). 完. 为 显 递 3.', '空\n空\n空\n空\n'),
    ('escaped_closure', "存 取 []. 作 制: 值 取 40. 试 卒 '因'. 救 原因 存 其 增 算: 值 取 值+1. 得 原因 对 值. 法. 完. 终. 为 显 制. 显 存[0](). 显 存[0]().", '空\n(因 对 41)\n(因 对 42)\n'),
    ('panic_unchanged', "作 停: 卒 '真正错误'. 完. 为 试 停. 救 因 显 因. 终.", '真正错误\n'),
]

INVALID = [
    '完.', '循 完. 环', '若 1 则 完. 然', "试 完. 救 因 终.",
    '算 求: 完. 得 1. 法', '回 取 算: 完. 得 1. 法.',
    '作 外: 算 内: 完. 得 1. 法 完. 为',
    '作 外: 回 取 算: 完. 得 1. 法. 完. 为',
    '作 外: 算 内: 作 合法: 完. 为 完. 得 1. 法 为',
    '作 停: 完 1. 为', '作 停: 完 空. 为', "作 停: 完 ''. 为",
    '作 停: 得 空. 为', '完 取 1.',
]

STRESS = """
存 取 [].
作 制:
    值 取 [40]. 值 其 增 值.
    试 卒 '外'. 救 外因
        循 2 次
            试 卒 '内'. 救 内因
                存 其 增 算: 值[0] 取 值[0]+1. 得 值[0] 对 外因+内因. 法.
                完.
            终.
        环
    终.
为
循 500 次
    制.
    若 存[0]() != (41 对 '外内') 则 卒 '捕获损坏'. 然
    存 取 [].
环
显 制.
显 存[0]().
存 取 空.
"""

class ProcedureFinishTests(unittest.TestCase):
    def test_ast_punctuation_and_incomplete(self):
        for punctuation in ('.', '。'):
            statement = parse('作 停: 完'+punctuation+' 为')[0].data['body'][0]
            self.assertEqual(statement.kind, 'finish')
            self.assertEqual(statement.data, {})
        with self.assertRaises(Incomplete):
            parse('作 停: 完')

    def test_invalid_in_all_frontends(self):
        for source in INVALID:
            for engine in (lambda p: validate(p), lambda p: Interpreter().execute(p),
                           lambda p: Compiler(p).compile(), lambda p: JSCompiler(p).compile()):
                with self.subTest(source=source, engine=engine), self.assertRaises(RuError):
                    engine(parse(source))

    def test_interpreter(self):
        for name, source, expected in CASES:
            with self.subTest(name=name):
                self.assertEqual(closures.interpreted(source), expected)

    @unittest.skipUnless(closures.CC, 'C compiler unavailable')
    def test_native(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, source, expected in CASES:
                with self.subTest(name=name):
                    result = closures.native(source, directory, name)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, expected)
                    self.assertIn('RU_GC live=0 ', result.stderr)

    @unittest.skipUnless(javascript.NODE, 'Node unavailable')
    def test_javascript(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, source, expected in CASES:
                with self.subTest(name=name):
                    path, _ = javascript.compiled(source, directory, name)
                    self.assertEqual(javascript.node_run(path), (0, expected, ''))

    def test_migration_rejects_string_parameter(self):
        source = "作 停: 为 算 用 值 为 句: 得 值. 法 显 用 停."
        with self.assertRaisesRegex(RuError, '须为句，实际收到空'):
            closures.interpreted(source)
        with tempfile.TemporaryDirectory() as directory:
            if closures.CC:
                result = closures.native(source, directory, 'migration')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('须为句，实际收到空', result.stderr)
            if javascript.NODE:
                path, _ = javascript.compiled(source, directory, 'migration')
                status, _, error = javascript.node_run(path)
                self.assertNotEqual(status, 0)
                self.assertIn('须为句，实际收到空', error)

    def test_cli_multiline_repl_recovers_after_invalid_finish(self):
        result = subprocess.run([sys.executable, str(ROOT / 'ru'), 'repl'],
            input='作 停:\n完.\n为\n停.\n显 停.\n空.\n完.\n显 8.\n',
            text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '空\n空\n8\n')
        self.assertIn('「完」只能出现在「作」定义内', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_repl_echo_is_suppressed_by_call_kind_not_null(self):
        output = io.StringIO()
        engine = Interpreter(stdout=output)
        engine.execute(parse('作 停: 完. 为 作 自然: 为 回 取 作 停. 形 盒: 作 停: 完. 为 象 盒值 取 新 盒.'))
        for source in ('停.', '自然.', '回().', '盒值 其 停.', '(作: 完. 为)().'):
            engine.execute(parse(source), echo=True)
        self.assertEqual(output.getvalue(), '')
        engine.execute(parse('空. 显 停. 显 自然. 显 回(). 显 盒值 其 停. 算 求: 得 空. 法 求.'), echo=True)
        self.assertEqual(output.getvalue(), '空\n' * 6)

    @unittest.skipUnless(closures.CC and javascript.NODE, 'C compiler and Node required')
    def test_full_pruned_and_forced_gc(self):
        expected = '空\n(41 对 外内)\n'
        self.assertEqual(closures.interpreted(STRESS), expected)
        with tempfile.TemporaryDirectory() as directory:
            for full in (False, True):
                binary = pruning.build(pruning.generate(STRESS, full=full), directory, 'stress'+str(full))
                result = pruning.run(binary)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)
                self.assertIn('RU_GC live=0 ', result.stderr)
                js = JSCompiler(parse(STRESS), full_runtime=full).compile()
                path = Path(directory).resolve() / ('stress'+str(full)+'.js')
                path.write_text(js, encoding='utf-8')
                self.assertEqual(javascript.node_run(path), (0, expected, ''))

    def test_finish_does_not_disable_bundled_pruning(self):
        source = "竞 取 外言 '如竞'. 作 停: 显 (竞 其 小 3 4). 完. 为 停."
        graph = load_module_graph('/finish-pruning.ru', parse(source))
        result = prune_bundled_stdlib(graph[graph.root], graph.root, graph)
        library = next(path for path in result if path != graph.root)
        self.assertEqual({n.data['name'] for n in result[library]}, {'小'})

    @unittest.skipUnless(closures.CC and javascript.NODE, 'C compiler and Node required')
    def test_module_procedures(self):
        with tempfile.TemporaryDirectory() as directory:
            child = Path(directory).resolve() / 'child.ru'
            root = Path(directory).resolve() / 'main.ru'
            child.write_text('作 提前: 完. 显 9. 为 作 自然: 为', encoding='utf-8')
            source = "模 取 外言 'child.ru'. 显 模 其 提前. 显 模 其 自然."
            graph = load_module_graph(str(root), parse(source))
            self.assertEqual(closures.interpreted(source, str(root), graph), '空\n空\n')
            result = closures.native(source, directory, 'module', str(root), graph)
            self.assertEqual((result.returncode, result.stdout), (0, '空\n空\n'), result.stderr)
            path, _ = javascript.compiled(source, directory, 'module', str(root), graph)
            self.assertEqual(javascript.node_run(path), (0, '空\n空\n', ''))

if __name__ == '__main__':
    unittest.main()
