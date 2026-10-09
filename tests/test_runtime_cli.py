"""Default pruned builds and opt-in full-runtime diagnostic outputs."""
import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.cli import build, main, make_parser
from rulang.compiler import Compiler
from rulang.frontend import RuError, parse
from rulang.js_compiler import JSCompiler
from rulang.modules import load_module_graph

CC = (shutil.which(os.environ['CC']) if os.environ.get('CC') else
      next((shutil.which(c) for c in ('clang', 'gcc', 'cc') if shutil.which(c)), None))
NODE = shutil.which('node')


class RuntimeBuildCLI(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.source = self.root / 'main.ru'
        self.source.write_text("尽 取 外言 '如:竞赛'. 显 小 3 4.\n", encoding='utf-8')

    def cli(self, *args):
        return subprocess.run([sys.executable, ROOT / 'ru', *args],
                              capture_output=True, text=True, timeout=60)

    def test_full_runtime_is_explicit_and_supported_by_both_targets(self):
        parser = make_parser()
        for target in ('c', 'js'):
            with self.subTest(target=target):
                self.assertFalse(parser.parse_args(['build', 'main.ru', '--target', target]).full_runtime)
                self.assertTrue(parser.parse_args(['build', 'main.ru', '--target', target,
                                                   '--full-runtime']).full_runtime)
        self.assertIn('--full-runtime', self.cli('build', '--help').stdout)

    def test_flag_is_not_a_check_or_generate_option(self):
        for command, source in (('check', 'main.ru'), ('generate', 'intent.md')):
            with self.subTest(command=command), contextlib.redirect_stderr(io.StringIO()), \
                 self.assertRaises(SystemExit) as caught:
                make_parser().parse_args([command, source, '--full-runtime'])
            self.assertEqual(caught.exception.code, 2)

    def test_js_build_api_and_cli_emit_requested_mode_without_execution(self):
        program = parse(self.source.read_text(encoding='utf-8'))
        modules = load_module_graph(self.source, program)
        outputs = []
        for full in (False, True):
            with self.subTest(full=full):
                output = self.root / ('full.js' if full else 'pruned.js')
                expected = JSCompiler(program, str(self.source), modules=modules,
                                      full_runtime=full).compile()
                with patch('rulang.cli.subprocess.run', side_effect=AssertionError('execute')), \
                     patch.dict(os.environ, {'PATH': '', 'CC': '/not/a/compiler'}):
                    build(program, self.source, output, modules=modules, target='js', full_runtime=full)
                    self.assertEqual(output.read_text(encoding='utf-8'), expected)
                    with contextlib.redirect_stdout(io.StringIO()) as status:
                        args = ['build', str(self.source), '--target', 'js', '-o', str(output)]
                        self.assertEqual(main(args + (['--full-runtime'] if full else [])), 0)
                    self.assertIn('未执行', status.getvalue())
                    self.assertEqual(output.read_text(encoding='utf-8'), expected)
                outputs.append(expected)
        self.assertNotIn('function fileIO(', outputs[0])
        self.assertNotIn('class Scanner', outputs[0])
        self.assertIn('function fileIO(', outputs[1])
        self.assertIn('class Scanner', outputs[1])
        self.assertLess(len(outputs[0].encode('utf-8')), len(outputs[1].encode('utf-8')))
        if NODE:
            self.source.unlink()
            for name in ('pruned.js', 'full.js'):
                result = subprocess.run([NODE, self.root / name], capture_output=True, text=True, timeout=10)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '3\n', ''))

    @unittest.skipUnless(CC, 'A C99 compiler is required')
    def test_c_build_emits_requested_mode_and_both_are_standalone(self):
        program = parse(self.source.read_text(encoding='utf-8'))
        modules = load_module_graph(self.source, program)
        outputs, programs = [], []
        for full in (False, True):
            with self.subTest(full=full):
                name = 'full' if full else 'pruned'
                binary, cfile = self.root / name, self.root / (name + '.c')
                result = self.cli('build', str(self.source), '-o', str(binary), '--emit-c', str(cfile),
                                  '--cc', CC, *(['--full-runtime'] if full else []))
                self.assertEqual(result.returncode, 0, result.stderr)
                code = cfile.read_text(encoding='utf-8')
                self.assertEqual(code, Compiler(program, str(self.source), modules=modules,
                                                full_runtime=full).compile())
                standalone = self.root / (name + '-standalone')
                compiled = subprocess.run([CC, '-std=c99', '-O2', str(cfile), '-lm', '-o', str(standalone)],
                                          capture_output=True, text=True, timeout=60)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                outputs.append(code)
                programs.extend((binary, standalone))
                cfile.unlink()
        self.assertLess(len(outputs[0].encode('utf-8')), len(outputs[1].encode('utf-8')))
        self.source.unlink()
        for binary in programs:
            result = subprocess.run([binary], cwd=self.root, env={**os.environ, 'PATH': ''},
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '3\n', ''))

    def test_both_modes_reject_original_declaration_conflicts_before_publish(self):
        self.source.write_text("尽 取 外言 '如:竞赛'. 算 小: 得 1. 法 显 42.", encoding='utf-8')
        errors = []
        for target in ('c', 'js'):
            for full in (False, True):
                with self.subTest(target=target, full=full):
                    output = self.root / ('out.' + target)
                    output.write_text('keep original', encoding='utf-8')
                    result = self.cli('build', str(self.source), '--target', target, '-o', str(output),
                                      *(['--full-runtime'] if full else []))
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, '')
                    self.assertIn('尽取名称冲突', result.stderr)
                    self.assertEqual(output.read_text(encoding='utf-8'), 'keep original')
                    errors.append(result.stderr)
        self.assertEqual(len(set(errors)), 1)
        self.assertEqual(list(self.root.glob('.ru-build-*')), [])

    def test_full_runtime_keeps_existing_output_path_protection(self):
        for target in ('c', 'js'):
            with self.subTest(target=target), self.assertRaisesRegex(RuError, '不能覆盖'):
                build(parse(self.source.read_text(encoding='utf-8')), self.source, self.source,
                      target=target, full_runtime=True)

    def test_js_still_rejects_c_only_options_in_full_mode(self):
        with patch('rulang.cli.read_source', side_effect=AssertionError('read')), \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            main(['build', 'missing.ru', '--target', 'js', '--full-runtime', '--emit-c', 'out.c'])
        self.assertEqual(caught.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
