"""Source labels can be mapped without changing imports or source contents."""
import contextlib
import copy
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from rulang.cli import build, main
from rulang.compiler import Compiler, cstr
from rulang.frontend import RuError, parse
from rulang.js_compiler import JSCompiler
from rulang.modules import load_module_graph
from rulang.source_paths import SourcePathMapper

ROOT = Path(__file__).resolve().parents[1]
CC = next((shutil.which(c) for c in ('cc', 'gcc', 'clang') if shutil.which(c)), None)


class SourcePrefixMapTests(unittest.TestCase):
    def test_longest_prefix_component_boundary_and_later_equal_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            mapper = SourcePathMapper([f'{root}=first', f'{root}/sub=deep', f'{root}=last'])
            self.assertEqual(mapper(str(root / 'sub' / 'entry.ru')), 'deep/entry.ru')
            self.assertEqual(mapper(str(root / 'entry.ru')), 'last/entry.ru')
            neighbor = str(root) + '-neighbor/entry.ru'
            self.assertEqual(mapper(neighbor), neighbor)
            self.assertEqual(mapper('<源码>'), '<源码>')

    def test_windows_paths_are_host_independent_case_insensitive_components(self):
        # These are foreign lexical paths, not network shares to probe on CI.
        with patch('rulang.source_paths._WINDOWS_HOST', False):
            mapper = SourcePathMapper([r'C:\Build=app', r'c:/build/Sub=part'])
            self.assertEqual(mapper(r'c:\BUILD\SUB\Entry.ru'), 'part/Entry.ru')
            self.assertEqual(mapper('C:/build/Other.ru'), 'app/Other.ru')
            self.assertEqual(mapper(r'C:\Builder\Entry.ru'), r'C:\Builder\Entry.ru')
            self.assertEqual(mapper(r'D:\Build\Entry.ru'), r'D:\Build\Entry.ru')
            unc = SourcePathMapper([r'\\Server\Share\Code=src'])
            self.assertEqual(unc('//server/SHARE/code/Entry.ru'), 'src/Entry.ru')
            self.assertEqual(unc('//server/other/code/Entry.ru'), '//server/other/code/Entry.ru')

    def test_windows_lexical_comparison_does_not_expand_sharp_s_to_ss(self):
        with patch('rulang.source_paths._WINDOWS_HOST', False):
            mapper = SourcePathMapper([r'C:\Straße=src'])
            self.assertEqual(mapper(r'c:\STRAßE\Entry.ru'), 'src/Entry.ru')
            self.assertEqual(mapper(r'C:\STRASSE\Entry.ru'), r'C:\STRASSE\Entry.ru')

    def test_windows_host_resolves_absolute_prefixes_like_module_loading(self):
        def resolve(path):
            return path.replace(r'C:\junction', r'C:\real').replace(
                r'\\server\share\junction', r'\\server\share\real')

        with patch('rulang.source_paths._WINDOWS_HOST', True), \
                patch('rulang.source_paths._resolve_host_path', side_effect=resolve) as canonicalize:
            mapper = SourcePathMapper([r'C:\junction=src'])
            self.assertEqual(mapper(r'C:\real\Entry.ru'), 'src/Entry.ru')
            self.assertEqual(canonicalize.call_args_list[0].args, (r'C:\junction',))
            unc = SourcePathMapper([r'\\server\share\junction=network'])
            self.assertEqual(unc(r'\\server\share\real\Entry.ru'), 'network/Entry.ru')
        with patch('rulang.source_paths._WINDOWS_HOST', False), \
                patch('rulang.source_paths._resolve_host_path', side_effect=AssertionError('foreign resolve')):
            self.assertEqual(SourcePathMapper([r'C:\build=src'])(r'C:\build\Entry.ru'), 'src/Entry.ru')

    @unittest.skipIf(os.name == 'nt', 'POSIX paths are case sensitive')
    def test_posix_case_and_windows_prefix_do_not_mix(self):
        mapper = SourcePathMapper(['/Build=src', r'C:\Build=win'])
        self.assertEqual(mapper('/Build/file.ru'), 'src/file.ru')
        self.assertEqual(mapper('/build/file.ru'), '/build/file.ru')

    def test_relative_prefix_empty_replacement_and_literal_replacement(self):
        mapper = SourcePathMapper(['.='])
        self.assertEqual(mapper(str(Path.cwd() / 'entry.ru')), 'entry.ru')
        self.assertEqual(mapper(str(Path.cwd())), '.')
        self.assertEqual(SourcePathMapper(['.=标签=值'])(str(Path.cwd() / 'entry.ru')), '标签=值/entry.ru')
        self.assertEqual(SourcePathMapper([str(Path.cwd()) + '=/'])(str(Path.cwd() / 'entry.ru')), '/entry.ru')

    def test_invalid_maps_fail_clearly(self):
        for specifications in (['missing'], ['=new'], ['old=bad\nlabel'], [None],
                               [r'C:relative=new'], ['C:=new'], 'old=new'):
            with self.subTest(specifications=specifications), self.assertRaisesRegex(RuError, '源码路径映射'):
                SourcePathMapper(specifications)

    def test_unresolvable_prefix_is_a_build_diagnostic_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source, output = root / 'entry.ru', root / 'program.exe'
            source.write_text('显 1.', encoding='utf-8')
            output.write_bytes(b'keep existing output')
            for error in (OSError('unreadable prefix'), RuntimeError('symlink loop')):
                with self.subTest(error=type(error).__name__):
                    stderr = io.StringIO()
                    with patch('rulang.source_paths.Path', side_effect=error), \
                            patch('rulang.cli.subprocess.run', side_effect=AssertionError('compile')), \
                            contextlib.redirect_stderr(stderr):
                        status = main(['build', str(source), '--source-prefix-map', '.=src', '-o', str(output)])
                    self.assertEqual(status, 1)
                    self.assertIn('源码路径映射无法解析路径', stderr.getvalue())
                    self.assertNotIn('Traceback', stderr.getvalue())
                    self.assertEqual(output.read_bytes(), b'keep existing output')

    def test_api_and_cli_reject_javascript_before_reading_source(self):
        with self.assertRaisesRegex(RuError, '只适用于 C'):
            JSCompiler(parse('显 1.'), source_prefix_maps=['.=src'])
        with self.assertRaisesRegex(RuError, '只适用于 C'):
            build(parse('显 1.'), 'missing.ru', 'out.js', target='js', source_prefix_maps=['.=src'])
        with patch('rulang.cli.read_source', side_effect=AssertionError('read')), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            main(['build', '--target', 'js', '--source-prefix-map', '.=src', 'missing.ru'])
        self.assertEqual(caught.exception.code, 2)

    def test_compile_errors_keep_original_source_and_excerpt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            main_path, child = root / 'entry.ru', root / 'child.ru'
            main_path.write_text("外言 'child.ru'.", encoding='utf-8')
            text = '算 合 左 右: 得 左+右. 法\n显 合 1.\n'
            child.write_text(text, encoding='utf-8')
            graph = load_module_graph(main_path)
            with self.assertRaises(RuError) as caught:
                Compiler(graph[graph.root], graph.root, modules=graph,
                         source_prefix_maps=[f'{root}=public']).compile()
            self.assertEqual(caught.exception.source_name, str(child))
            self.assertEqual(caught.exception.source_text, text)
            self.assertEqual(caught.exception.line, 2)

    def test_pruning_and_native_callback_labels_preserve_graph_and_user_strings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            entry, child = root / 'entry.ru', root / 'callback.ru'
            child.write_text("密 取 外言 '如:密'.\n算 回 值: 得 值. 法\n"
                "签 取 密 其 签名 (密 其 i32) ([密 其 i32]) 'cdecl'.\n"
                "回调 取 密 其 回调 签 (算 回) 0.\n", encoding='utf-8')
            source = "数学 取 外言 '如:数学'. 外言 'callback.ru'. 显 'literal-build-path'."
            entry.write_text(source, encoding='utf-8')
            graph = load_module_graph(entry)
            original = copy.deepcopy(graph)
            for full in (False, True):
                with self.subTest(full=full):
                    compiler = Compiler(graph[graph.root], graph.root, modules=graph, full_runtime=full,
                        allow_native=True, source_prefix_maps=[f'{root}=app', f'{ROOT}=tool'])
                    generated = compiler.compile()
                    self.assertIn('ru_source = "app/callback.ru"', generated)
                    self.assertIn('ru_source = "app/entry.ru"', generated)
                    self.assertNotIn(str(root).replace('\\', '\\\\'), generated)
                    self.assertIn('literal-build-path', generated)
                    self.assertEqual(compiler.source_texts, original.sources)
                    self.assertEqual(list(compiler.modules), list(graph))
            self.assertEqual(repr(graph), repr(original))
            literal = str(root / 'payload.ru')
            code = Compiler(parse('显 ' + repr(literal) + '.'), str(entry),
                            source_prefix_maps=[f'{root}=app']).compile()
            self.assertIn(cstr(literal), code, 'explicit mappings must not redact user string values')

    @unittest.skipUnless(CC, 'a C99 compiler is required')
    def test_unmapped_long_source_paths_retain_runtime_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / ('long-source-location-' * 4)
            root.mkdir()
            entry, child = root / 'entry.ru', root / 'child.ru'
            child.write_text("作 失败:\n卒 'failure'.\n为.\n", encoding='utf-8')
            entry.write_text("模 取 外言 'child.ru'. 模 其 失败.", encoding='utf-8')
            graph = load_module_graph(entry)
            for full in (False, True):
                with self.subTest(full=full):
                    code = Compiler(graph[graph.root], graph.root, modules=graph,
                                    full_runtime=full).compile()
                    self.assertIn('ru_source = ' + cstr(str(child)), code)
                    self.assertIn('ru_source = ' + cstr(str(entry)), code)
                    cfile, binary = root / 'program.c', root / 'program.exe'
                    cfile.write_text(code, encoding='utf-8')
                    built = subprocess.run([CC, '-std=c99', str(cfile), '-o', str(binary), '-lm'],
                                           capture_output=True, text=True, timeout=60)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=20)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn(str(child) + ':2:', result.stderr)
                    self.assertIn('failure', result.stderr)

    @unittest.skipUnless(CC, 'a C99 compiler is required')
    def test_cli_build_maps_runtime_import_labels_and_panic_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            entry, child = root / 'entry.ru', root / 'child.ru'
            child.write_text("作 失败:\n卒 'failure'.\n为\n", encoding='utf-8')
            entry.write_text("模 取 外言 'child.ru'. 模 其 失败.", encoding='utf-8')
            output, emitted = root / 'program.exe', root / 'program.c'
            with contextlib.redirect_stdout(io.StringIO()):
                status = main(['build', str(entry), '--source-prefix-map', f'{root}=first',
                    '--source-prefix-map', f'{root}=public', '--emit-c', str(emitted),
                    '--cc', CC, '-o', str(output)])
            self.assertEqual(status, 0)
            code = emitted.read_text(encoding='utf-8')
            self.assertNotIn(cstr(str(root))[1:-1], code)
            result = subprocess.run([str(output)], text=True, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 1)
            self.assertIn('public/child.ru:2:', result.stderr)
            self.assertNotIn(str(root), result.stderr)
            self.assertNotIn('first/', result.stderr)


if __name__ == '__main__':
    unittest.main()
