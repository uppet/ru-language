"""Call-count diagnostics explain grouping without changing call boundaries."""
import io
import sys
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from rulang.compiler import Compiler
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter
from rulang.js_compiler import JSCompiler
from rulang.modules import load_module_graph

CC = next((shutil.which(c) for c in ('cc', 'gcc', 'clang') if shutil.which(c)), None)
NODE = shutil.which('node')
HINT = '若并列阵元素，请括起调用'


class CallArityDiagnosticTests(unittest.TestCase):
    def check(self, source, *, name=None, expected=None, received=None, hint=False,
              line=2, dependency=None, output=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            main, child = root / 'entry.ru', root / 'dependency.ru'
            main.write_text(source, encoding='utf-8')
            if dependency is not None:
                child.write_text(dependency, encoding='utf-8')
            graph = load_module_graph(main)
            error_path = str(child if dependency is not None else main)

            def assert_message(message):
                self.assertIn('函数「' + name + '」', message)
                self.assertIn('需要 ' + str(expected) + ' 个', message)
                self.assertIn('收到 ' + str(received) + ' 个', message)
                self.assertEqual(HINT in message, hint)

            stdout = io.StringIO()
            engine = Interpreter(stdout=stdout)
            if name:
                with self.assertRaises(RuError) as caught:
                    engine.execute(graph[graph.root], source_path=graph.root, modules=graph)
                assert_message(caught.exception.message)
                self.assertEqual(caught.exception.source_name, error_path)
                self.assertEqual(caught.exception.line, line)
            else:
                engine.execute(graph[graph.root], source_path=graph.root, modules=graph)
                self.assertEqual(stdout.getvalue(), output)
            for backend, executable in ((Compiler, CC), (JSCompiler, NODE)):
                if not executable:
                    continue
                with self.subTest(backend=backend.__name__):
                    generated = backend(graph[graph.root], graph.root, modules=graph).compile()
                    artifact = root / ('program.c' if backend is Compiler else 'program.js')
                    artifact.write_text(generated, encoding='utf-8')
                    if backend is Compiler:
                        binary = root / 'program.exe'
                        compiled = subprocess.run([CC, '-std=c99', '-O1', '-Wall', '-Wextra',
                            '-Werror', '-Wno-unused-function', '-pedantic', str(artifact), *([] if sys.platform == 'win32' else ['-lm']),
                            '-o', str(binary)], text=True, capture_output=True, timeout=60)
                        self.assertEqual(compiled.returncode, 0, compiled.stderr)
                        command = [str(binary)]
                    else:
                        command = [NODE, str(artifact)]
                    result = subprocess.run(command, text=True, capture_output=True, timeout=20,
                        env={**os.environ, 'RU_GC_THRESHOLD': '1'})
                    self.assertEqual(result.returncode, 1 if name else 0, result.stderr)
                    if name:
                        assert_message(result.stderr)
                        self.assertIn(error_path + ':' + str(line) + ':', result.stderr)
                    else:
                        self.assertEqual(result.stdout, output)
                        self.assertEqual(result.stderr, '')

    def test_array_member_call_reports_excess_and_conditional_grouping_hint(self):
        self.check("表 取 {'键': 7}.\n显 [表 其 查 '键', 9].",
                   name='查', expected=1, received=2, hint=True)

    def test_grouped_member_call_remains_two_array_elements(self):
        ambiguous = parse("显 [表 其 查 '键', 9].")[0].data['expr']
        grouped = parse("显 [(表 其 查 '键'), 9].")[0].data['expr']
        self.assertEqual(len(ambiguous.data['items']), 1)
        self.assertEqual(len(ambiguous.data['items'][0].data['args']), 2)
        self.assertEqual(len(grouped.data['items']), 2)
        self.check("表 取 {'键': 7}.\n显 [(表 其 查 '键'), 9].", output='[7, 9]\n')

    def test_zero_and_missing_positional_arguments_keep_counts_without_hint(self):
        prefix = '算 合 左 右: 得 左+右. 法 别名 取 算 合.\n'
        for call, received in (('别名().', 0), ('别名 1.', 1)):
            with self.subTest(call=call):
                self.check(prefix + call, name='合', expected=2, received=received)

    def test_unknown_named_argument_keeps_counts_without_grouping_hint(self):
        self.check('算 合 左 右: 得 左+右. 法 别名 取 算 合.\n别名 左:1 错:2.',
                   name='合', expected=2, received=2)

    def test_zero_parameter_members_name_the_member_and_actual_count(self):
        for receiver, member in (("{'键': 7}", '量'), ('[7]', '量'), ('(7 对 9)', '囫')):
            with self.subTest(member=member, receiver=receiver):
                self.check('值 取 ' + receiver + '.\n显 值 其 ' + member + ' 1.',
                           name=member, expected=0, received=1, hint=True)

    def test_imported_runtime_call_uses_its_own_source_location(self):
        self.check("模 取 外言 'dependency.ru'.\n模 其 执行.", name='查', expected=1,
                   received=2, hint=True, line=3,
                   dependency="作 执行:\n表 取 {'键': 7}.\n显 [表 其 查 '键', 9].\n为")


if __name__ == '__main__':
    unittest.main()
