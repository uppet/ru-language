"""Bundled-only declaration pruning: reachability and conservative fallbacks."""
import copy
import io
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.frontend import Node, RuError, parse
from rulang.interpreter import Interpreter
from rulang.modules import load_module_graph, resolve_import
from rulang.stdlib_pruning import prune_bundled_stdlib


PRELUDE = "竞 取 外言 '如:竞赛'.\n"
BUNDLED = resolve_import('如:竞赛', '/tmp/pruning-main.ru')
ALL_NAMES = {n.data['name'] for n in parse(Path(BUNDLED).read_text(encoding='utf-8'))}


class BundledDeclarationPruningTests(unittest.TestCase):
    def graph(self, source, directory=None):
        path = str(Path(directory or '/tmp') / 'pruning-main.ru')
        return load_module_graph(path, parse(source))

    def pruned(self, source):
        graph = self.graph(source)
        result = prune_bundled_stdlib(graph[graph.root], graph.root, graph)
        return result, graph

    def names(self, result):
        return {n.data['name'] for n in result[BUNDLED]}

    def assert_names(self, source, expected):
        result, _ = self.pruned(source)
        self.assertEqual(self.names(result), set(expected))
        return result

    def assert_equivalent(self, source, expected, stdin=''):
        result, graph = self.pruned(source)
        for modules in (graph, result):
            output = io.StringIO()
            interpreter = Interpreter(io.StringIO(stdin), output)
            interpreter.execute(modules[graph.root], source_path=graph.root, modules=modules)
            self.assertEqual(output.getvalue(), expected)

    def test_simple_module_access_and_direct_import(self):
        self.assert_names(PRELUDE + "显 (竞 其 小 3 4).", {'小'})
        self.assert_names("显 ((外言 '如:竞赛') 其 大 3 4).", {'大'})
        self.assert_equivalent(PRELUDE + "显 (竞 其 小 3 4).", '3\n')

    def test_import_all_and_transitive_function_dependency(self):
        source = "尽 取 外言 '如:竞赛'. 显 整除 (-7) 3."
        self.assert_names(source, {'整除', '取整'})
        self.assert_equivalent(source, '-2\n')

    def test_unused_import_and_unused_alias(self):
        self.assert_names("外言 '如:竞赛'. 显 42.", set())
        self.assert_names(PRELUDE + '显 42.', set())
        self.assert_equivalent(PRELUDE + '显 42.', '42\n')

    def test_first_class_member_and_import_all_references(self):
        member = PRELUDE + "分 取 算 竞 其 拆词. 另名 取 分. 显 (另名 'a b')."
        self.assert_names(member, {'拆词'})
        self.assert_equivalent(member, '[a, b]\n')
        imported = "尽 取 外言 '如:竞赛'. 分 取 算 拆词. 显 (分 'a b')."
        self.assert_names(imported, {'拆词'})
        self.assert_equivalent(imported, '[a, b]\n')

    def test_alias_chains_and_dormant_functions_are_roots(self):
        source = PRELUDE + "别名 取 竞. 二名 取 别名. 算 未调用: 得 二名 其 字列 'ab'. 法 显 (二名 其 大 2 3)."
        result, graph = self.pruned(source)
        self.assertEqual(self.names(result), {'字列', '大'})
        self.assertEqual(result[graph.root], graph[graph.root])
        self.assert_equivalent(source, '3\n')

    def test_aliases_bound_in_functions_and_branches(self):
        source = "算 求: 若 1 则 竞 取 外言 '如:竞赛'. 然 别名 取 竞. 得 别名 其 小 2 3. 法 显 求."
        self.assert_names(source, {'小'})
        self.assert_equivalent(source, '2\n')

    def test_closures_keep_selected_exports_without_escaping_module(self):
        source = PRELUDE + "算 制: 算 比 左 为 数 右 为 数: 得 竞 其 小 左 右. 法 得 算 比. 法 比较 取 制. 显 比较 2 3."
        self.assert_names(source, {'小'})
        self.assert_equivalent(source, '2\n')

    def test_module_value_escape_falls_back(self):
        samples = (
            PRELUDE + '显 竞.',
            PRELUDE + '容 取 [竞].',
            PRELUDE + '容 取 竞 对 1.',
            PRELUDE + '算 制: 得 竞. 法',
            "算 制: 得 外言 '如:竞赛'. 法",
            PRELUDE + '算 用 值 为 件: 得 值. 法 用 竞.',
            PRELUDE + '形 盒: 值 为 件. 象 容 取 新 盒 值:竞.',
            PRELUDE + '容 取 [0]. 容[0] 取 竞.',
            PRELUDE + '竞 1.',
            PRELUDE + '显 竞 == 竞.',
        )
        for source in samples:
            with self.subTest(source=source):
                self.assert_names(source, ALL_NAMES)

    def test_module_alias_escape_falls_back(self):
        self.assert_names(PRELUDE + '甲 取 竞. 乙 取 甲. 容 取 [乙].', ALL_NAMES)
        # Shadowing makes this conservative, never unsound: the spelling alone
        # cannot prove that every runtime use ceased to refer to the module.
        self.assert_names(PRELUDE + '算 用 竞 为 数: 得 竞. 法', ALL_NAMES)

    def test_all_binding_and_declaration_names_are_roots(self):
        samples = (
            PRELUDE + '小 取 1.',
            PRELUDE + '算 小: 得 1. 法',
            PRELUDE + '算 用 小 为 数: 得 0. 法',
            PRELUDE + "试 卒 'x'. 救 小 显 1. 终",
            PRELUDE + '形 盒: 小 为 数. 象',
        )
        for source in samples:
            with self.subTest(source=source):
                self.assert_names(source, {'小'})

    def test_runtime_import_all_and_protected_binding_errors_are_preserved(self):
        samples = (
            "小 取 1. 尽 取 外言 '如:竞赛'.",
            "尽 取 外言 '如:竞赛'. 算 用: 小 取 1. 得 0. 法 显 用.",
            "尽 取 外言 '如:竞赛'. 显 小 1.",
        )
        for source in samples:
            with self.subTest(source=source):
                result, graph = self.pruned(source)
                observed = []
                for modules in (graph, result):
                    output = io.StringIO()
                    interpreter = Interpreter(io.StringIO(), output)
                    with self.assertRaises(RuError) as context:
                        interpreter.execute(modules[graph.root], source_path=graph.root, modules=modules)
                    error = context.exception
                    observed.append((error.message, error.line, error.col,
                                     error.category, error.source_name, output.getvalue()))
                self.assertEqual(observed[0], observed[1])

    def test_unrelated_shadowing_does_not_remove_dependency(self):
        source = PRELUDE + '算 用: 小 取 99. 得 竞 其 小 2 3. 法 显 用.'
        self.assert_names(source, {'小'})
        self.assert_equivalent(source, '2\n')

    def test_original_graph_and_ast_not_mutated(self):
        source = PRELUDE + '显 (竞 其 小 2 3).'
        graph = self.graph(source)
        before = copy.deepcopy(graph)
        result = prune_bundled_stdlib(graph[graph.root], graph.root, graph)
        self.assertEqual(graph, before)
        self.assertEqual(graph.sources, before.sources)
        self.assertIsNot(result, graph)
        for path in graph:
            self.assertIsNot(result[path], graph[path])
        self.assertIs(result[BUNDLED][0], next(n for n in graph[BUNDLED] if n.data['name'] == '小'))
        result[graph.root].append(parse('显 99.')[0])
        self.assertEqual(graph, before)

    def test_user_modules_side_effects_and_unused_functions_are_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            lib = Path(directory).resolve() / 'user.ru'
            lib.write_text("显 '初始化'. 算 不用: 得 1. 法", encoding='utf-8')
            source = PRELUDE + "模 取 外言 'user.ru'. 显 (竞 其 小 2 3)."
            graph = self.graph(source, directory)
            result = prune_bundled_stdlib(graph[graph.root], graph.root, graph)
            self.assertEqual(self.names(result), {'小'})
            self.assertEqual(result[str(lib)], graph[str(lib)])
            self.assertEqual(set(result), set(graph))
            output = io.StringIO()
            Interpreter(io.StringIO(), output).execute(result[graph.root], source_path=graph.root, modules=result)
            self.assertEqual(output.getvalue(), '初始化\n2\n')

    def test_reexported_functions_and_module_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            lib = Path(directory).resolve() / 'relay.ru'
            for declaration, expression in (
                    ("尽 取 外言 '如:竞赛'.", '模 其 小 2 3'),
                    ("库 取 外言 '如:竞赛'.", '模 其 库 其 小 2 3')):
                with self.subTest(declaration=declaration):
                    lib.write_text(declaration, encoding='utf-8')
                    graph = self.graph("模 取 外言 'relay.ru'. 显 (" + expression + ').', directory)
                    result = prune_bundled_stdlib(graph[graph.root], graph.root, graph)
                    self.assertEqual(self.names(result), {'小'})
                    self.assertEqual(result[str(lib)], graph[str(lib)])

    def test_reexported_module_escape_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            lib = Path(directory).resolve() / 'relay.ru'
            lib.write_text("库 取 外言 '如:竞赛'.", encoding='utf-8')
            for expression in ('模', '模 其 库'):
                graph = self.graph("模 取 外言 'relay.ru'. 容 取 [" + expression + '].', directory)
                result = prune_bundled_stdlib(graph[graph.root], graph.root, graph)
                self.assertEqual(self.names(result), ALL_NAMES)

    def test_same_basename_user_library_is_never_pruned(self):
        with tempfile.TemporaryDirectory() as directory:
            lib = Path(directory).resolve() / '竞赛.ru'
            lib.write_text(Path(BUNDLED).read_text(encoding='utf-8'), encoding='utf-8')
            graph = self.graph("竞 取 外言 './竞赛.ru'. 显 (竞 其 小 2 3).", directory)
            result = prune_bundled_stdlib(graph[graph.root], graph.root, graph)
            self.assertEqual(result, graph)
            self.assertEqual(len(result[str(lib)]), len(ALL_NAMES))

    def test_substituted_stdlib_ast_and_side_effects_are_never_pruned(self):
        graph = self.graph(PRELUDE + '显 (竞 其 小 2 3).')
        originals = graph[BUNDLED]
        substitutions = (
            originals + parse("显 '初始化'."),
            originals + parse('算 自定义: 得 0. 法'),
            parse('算 小 左 为 数 右 为 数: 得 99. 法'),
        )
        for substitute in substitutions:
            with self.subTest(substitute=substitute):
                graph[BUNDLED] = substitute
                result = prune_bundled_stdlib(graph[graph.root], graph.root, graph)
                self.assertEqual(result[BUNDLED], substitute)

    def test_unresolved_import_or_unknown_syntax_fails_closed(self):
        graph = self.graph(PRELUDE)
        graph[graph.root].append(Node('future_reflection', graph[graph.root][0].token, {}))
        result = prune_bundled_stdlib(graph[graph.root], graph.root, graph)
        self.assertEqual(self.names(result), ALL_NAMES)
        graph = self.graph(PRELUDE)
        del graph[graph.root][0].data['expr'].data['resolved']
        result = prune_bundled_stdlib(graph[graph.root], graph.root, graph)
        self.assertEqual(self.names(result), ALL_NAMES)

    def test_no_module_graph_returns_fresh_root_only_mapping(self):
        program = parse('显 42.')
        self.assertEqual(prune_bundled_stdlib(program, '<源码>', None), {'<源码>': program})


if __name__ == '__main__':
    unittest.main()
