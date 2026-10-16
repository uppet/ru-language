"""Native ABI checking preserves dependency source excerpts without execution."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rulang.cli import main
from rulang.compiler import Compiler
from rulang.frontend import RuError, parse
from rulang.modules import load_module_graph
from rulang.native_c import NativeCPlan


class NativeCSourceDiagnosticTests(unittest.TestCase):
    def test_dependency_error_uses_dependency_text_and_location(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'entry.ru'
            child = Path(directory) / 'binding.ru'
            source = "外言 './binding.ru'.\n显 'unrelated-root-line'.\n"
            dependency = ("密 取 外言 '如:密'.\n"
                          "签 取 密 其 签名 (密 其 i32) (读) 'cdecl'.\n")
            root.write_text(source, encoding='utf-8')
            child.write_text(dependency, encoding='utf-8')
            for full in (False, True):
                with self.subTest(full=full), self.assertRaises(RuError) as caught:
                    graph = load_module_graph(root)
                    Compiler(graph[graph.root], graph.root, modules=graph,
                             full_runtime=full, allow_native=True)
                self.assertEqual(caught.exception.source_name, str(child.resolve()))
                self.assertEqual(caught.exception.source_text, dependency)
                self.assertEqual(caught.exception.line, 2)
            stderr, stdout = io.StringIO(), io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
                status = main(['check', '--target', 'c', '--allow-native', str(root)])
            self.assertEqual(status, 1)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn(str(child.resolve()) + ':2:', stderr.getvalue())
            self.assertIn(dependency.splitlines()[1], stderr.getvalue())
            self.assertNotIn('unrelated-root-line', stderr.getvalue())
            self.assertNotIn('Traceback', stderr.getvalue())

    def test_pruned_reanalysis_keeps_original_source_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'entry.ru'
            source = "数学 取 外言 '如:数学'. 密 取 外言 '如:密'. 显 (密 其 i32) 其 大小.\n"
            root.write_text(source, encoding='utf-8')
            graph = load_module_graph(root)
            seen = []

            def analyze(modules):
                seen.append((dict(modules), dict(modules.sources)))
                return NativeCPlan(modules)

            with patch('rulang.native_c.NativeCPlan', side_effect=analyze):
                Compiler(graph[graph.root], graph.root, modules=graph,
                         allow_native=True).compile()
            self.assertGreaterEqual(len(seen), 2, 'fixture must exercise stdlib pruning')
            self.assertNotEqual(sum(map(len, seen[0][0].values())),
                                sum(map(len, seen[-1][0].values())))
            for _, sources in seen:
                self.assertEqual(sources, graph.sources)

    def test_supplied_root_ast_is_the_analyzed_program(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'entry.ru'
            root.write_text("密 取 外言 '如:密'.\n", encoding='utf-8')
            graph = load_module_graph(root)
            replacement = parse("密 取 外言 '如:密'.\n签 取 密 其 签名 (读) ([]) 'cdecl'.")
            replacement[0].data['expr'].data['resolved'] = next(
                path for path in graph if path != graph.root)
            with self.assertRaisesRegex(RuError, '无法静态确定'):
                Compiler(replacement, graph.root, modules=graph, allow_native=True)


if __name__ == '__main__':
    unittest.main()
