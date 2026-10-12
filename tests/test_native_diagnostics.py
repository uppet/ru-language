"""GCC-style native diagnostics preserve paths and only report known locations."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

from rulang.compiler import Compiler
from rulang.frontend import parse
from rulang.js_compiler import JSCompiler
from rulang.modules import load_module_graph

CC = shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
NODE = shutil.which('node') or shutil.which('nodejs')


class NativeDiagnosticTests(unittest.TestCase):
    def run_program(self, backend, source, source_name, graph=None):
        compiler = Compiler if backend == 'c' else JSCompiler
        program = graph[graph.root] if graph is not None else parse(source)
        code = compiler(program, source_name, modules=graph).compile()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ('program.' + backend)
            path.write_text(code, encoding='utf-8')
            if backend == 'c':
                binary = Path(directory) / 'program'
                build = subprocess.run([CC, '-std=c99', str(path), '-lm', '-o', str(binary)],
                                       capture_output=True, text=True, timeout=30)
                self.assertEqual(build.returncode, 0, build.stderr)
                command = [str(binary)]
            else:
                command = [NODE, str(path)]
            return subprocess.run(command, capture_output=True, text=True, timeout=10)

    def check_paths(self, backend):
        paths = [(name, name) for name in ('/tmp/含 空格/错误.ru', r'C:\Users\中文 名\错误.ru', '<测试>')]
        paths.append(('/tmp/换\n行\r制\t表\x1b[31m\u202e\u061c\u200e\u2066\u2028\u2029.ru',
                      r'/tmp/换\n行\r制\t表\u001b[31m\u202e\u061c\u200e\u2066\u2028\u2029.ru'))
        for name, display_name in paths:
            for source, location, category in (
                ('\n  显 1/0.', ':2' if backend == 'c' else ':2:6', '运行错误'),
                ("\n  卒 '原因😀'.", ':2:3', '未救之卒'),
            ):
                with self.subTest(backend=backend, path=name, category=category):
                    result = self.run_program(backend, source, name)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, '')
                    self.assertTrue(result.stderr.startswith(display_name + location + ': error: ' + category + '：'), result.stderr)
                    self.assertNotIn('Traceback', result.stderr)
                    self.assertEqual(result.stderr.count('\n'), 1)

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_c_paths_and_known_locations(self):
        self.check_paths('c')

    @unittest.skipUnless(NODE, 'Node.js unavailable')
    def test_javascript_paths_and_known_locations(self):
        self.check_paths('js')

    def check_module(self, backend):
        with tempfile.TemporaryDirectory(prefix='如 模块 ') as directory:
            root = Path(directory) / '入口.ru'
            child = Path(directory) / '子 模块.ru'
            source = "子 取 外言 '子 模块.ru'.\n"
            root.write_text(source, encoding='utf-8')
            for body, location in (('\n  显 1/0.', ':2' if backend == 'c' else ':2:6'),
                                   ("\n  卒 '模块原点'.", ':2:3')):
                child.write_text(body, encoding='utf-8')
                graph = load_module_graph(root, parse(source))
                result = self.run_program(backend, source, str(root), graph)
                self.assertEqual(result.returncode, 1)
                self.assertTrue(result.stderr.startswith(str(child) + location + ': error: '), result.stderr)

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_c_import_keeps_original_filename(self):
        self.check_module('c')

    @unittest.skipUnless(NODE, 'Node.js unavailable')
    def test_javascript_import_keeps_original_filename(self):
        self.check_module('js')

    @unittest.skipUnless(NODE, 'Node.js unavailable')
    def test_javascript_host_failure_does_not_invent_a_location(self):
        code = JSCompiler(parse(''), '<测试>').compile() + '\nR.finish(new Error("host failure"));'
        result = subprocess.run([NODE, '-e', code], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, '<程序>: error: 运行错误：host failure\n')

    @unittest.skipUnless(NODE, 'Node.js unavailable')
    def test_javascript_retains_raw_structured_source(self):
        name = '/tmp/原\n始\u202e.ru'
        compiler = JSCompiler(parse(''), name)
        code = compiler.compile()
        code += ('\nconst failure = new R.RuError({path:' + json.dumps(name) + '},"bad",[7,8]);'
                 'R.finish(failure);process.stdout.write(failure.source);')
        result = subprocess.run([NODE, '-e', code], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, name)
        self.assertEqual(compiler.source_name, name)
        self.assertEqual(result.stderr, r'/tmp/原\n始\u202e.ru:7:8: error: 运行错误：bad' + '\n')
