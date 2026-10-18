"""Optional syntax stays compatible; canonical statement dots are linted separately."""
import dataclasses
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rulang.diagnostics import SourceOrigin, diagnostic
from rulang.frontend import Node, Parser, RuError, parse, style_issues

ROOT = Path(__file__).resolve().parents[1]
CC = next((shutil.which(c) for c in ('gcc', 'clang', 'cc') if shutil.which(c)), None)
NODE = shutil.which('node')


def semantics(value):
    if isinstance(value, Node):
        return value.kind, semantics(value.data)
    if isinstance(value, dict):
        return {k: semantics(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [semantics(v) for v in value]
    return value


def add_dots(source):
    lines = source.splitlines(keepends=True)
    for issue in reversed(style_issues(source)):
        index = issue.col - 1
        line = lines[issue.line - 1]
        lines[issue.line - 1] = line[:index] + '.' + line[index:]
    return ''.join(lines)


class StatementStyleParserTests(unittest.TestCase):
    def test_every_optional_statement_closer_has_one_precise_finding(self):
        for source, closer in (
            ('算 甲: 得 1. 法', '法'), ('作 甲: 完. 为', '为'),
            ('形 甲: 值 为 数. 象', '象'), ('若 真 则 显 1. 然', '然'),
            ('循 2 次 显 1. 环', '环'), ('试: 卒 1. 救 原因: 显 原因. 终', '终'),
            ('{ 值 取 1. }', '}'),
        ):
            with self.subTest(source=source):
                issues = style_issues(source)
                self.assertEqual(len(issues), 1)
                self.assertEqual((issues[0].line, issues[0].col), (1, len(source) + 1))
                self.assertIn('「' + closer + '」', issues[0].message)
                self.assertEqual(issues[0].code, 'missing-statement-dot')
                self.assertEqual(style_issues(source + '.'), [])
                self.assertEqual(style_issues(source + '。'), [])

    def test_collecting_style_does_not_change_the_ast(self):
        source = '''形 甲:
    算 值: 若 真 则 得 1. 另 得 2. 然 法
象
算 乙:
    循 1 次 { 显 2. } 环
    得 空.
法
'''
        ordinary = parse(source)
        collected = Parser(source, collect_style=True).parse()
        self.assertEqual(dataclasses.asdict(ordinary[0]), dataclasses.asdict(collected[0]))
        self.assertEqual(ordinary, collected)
        self.assertEqual(len(style_issues(source)), 6)
        canonical = add_dots(source)
        self.assertEqual(style_issues(canonical), [])
        self.assertEqual(semantics(ordinary), semantics(parse(canonical)))

    def test_anonymous_values_maps_arrays_and_references_do_not_own_dots(self):
        source = '''甲 取 算 值: 得 值 + 1. 法.
乙 取 作: 完. 为.
列 取 [(算: 得 1. 法), (作: 完. 为), {'键': 2}].
表 取 典:
    '算' 对 (算: 得 3. 法).
    '列' 对 [1,2].
成.
算 回 值:1.
'''
        self.assertEqual(style_issues(source), [])
        self.assertEqual(parse(source), Parser(source, collect_style=True).parse())

    def test_named_declarations_inside_anonymous_bodies_still_warn(self):
        source = '闭包 取 算: 算 子: 得 1. 法 得 算 子. 法.'
        issues = style_issues(source)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].col, source.index('法') + 2)
        self.assertEqual(style_issues(add_dots(source)), [])

    def test_statement_braces_are_distinct_from_map_expression_braces(self):
        source = "表 取 {'x':1}. { 别表 取 {'y':(算: 得 2. 法)}. }"
        self.assertEqual(len(style_issues(source)), 1)
        self.assertEqual(style_issues(source)[0].col, len(source) + 1)
        self.assertEqual(style_issues(source + '。'), [])

    def test_comments_and_multiline_separators_follow_real_token_boundaries(self):
        for comment in ('# 法. 象. }\n', '// 法.\n', '批. 然.\n', '解. 法.\n 象. 释.'):
            with self.subTest(comment=comment):
                self.assertEqual(style_issues('算 甲: 得 1. 法 ' + comment + '\n。'), [])
                missing = style_issues('算 甲: 得 1. 法 ' + comment + '\n显 2.')
                self.assertEqual(len(missing), 1)
                self.assertEqual((missing[0].line, missing[0].col), (1, 12))
        self.assertEqual(style_issues("显 '法 然 象 环 终 }'. 名法 取 1."), [])

    def test_chinese_punctuation_and_unicode_columns(self):
        source = '形 甲：\n 算 值：得 1。法\n象。'
        issues = style_issues(source)
        self.assertEqual([(x.line, x.col) for x in issues], [(2, 11)])
        self.assertEqual(style_issues(add_dots(source)), [])
        self.assertEqual(style_issues('｛ 显 1。 ｝。'), [])

    def test_speculative_abandoned_nodes_and_cached_declarations_are_not_duplicated(self):
        abandoned = '算 回 值:1. 若 真 则 显 2. 然'
        parser = Parser(abandoned, collect_style=True)
        result = parser.parse()
        self.assertGreater(len(parser.missing_dots), len(style_issues(abandoned)))
        self.assertEqual(len(style_issues(abandoned)), 1)
        self.assertEqual(result, parse(abandoned))

        class CacheProbe(Parser):
            hits = 0
            def callable_parse(self, kind, parse_body):
                if (kind, self.i, self.call_allowed) in self.callable_cache:
                    self.hits += 1
                return super().callable_parse(kind, parse_body)

        cached = '算 回 值:1. 算 子: 得 2. 法'
        parser = CacheProbe(cached, collect_style=True)
        self.assertEqual(parser.parse(), parse(cached))
        self.assertGreater(parser.hits, 0)
        self.assertEqual(len(style_issues(cached)), 1)

    def test_missing_required_dot_is_still_a_syntax_error(self):
        for source in ('显 1', '段: 显 1. 落', '甲 取 算: 得 1. 法', '表 取 典: 成'):
            with self.subTest(source=source), self.assertRaises(RuError):
                style_issues(source)

    def test_optional_colons_are_not_part_of_this_style_rule(self):
        self.assertEqual(style_issues('形 甲 象. 试 卒 1. 救 原因 显 原因. 终.'), [])

    def test_structured_warning_preserves_origin_and_escapes_controls(self):
        issue = style_issues('算 甲: 得 1. 法')[0]
        origin = SourceOrigin.cell('session', 'cell', 1, 2, 'source')
        detail = diagnostic(issue, origin=origin, severity='warning')
        self.assertEqual(detail['severity'], 'warning')
        self.assertEqual(detail['code'], 'missing-statement-dot')
        self.assertEqual(detail['source']['cell_id'], 'cell')
        self.assertIn(':1:12: warning: ', detail['formatted'])
        self.assertEqual(diagnostic(RuError('bad'))['severity'], 'error')
        fresh = style_issues('{}')[0]
        self.assertNotIn('\n', diagnostic(fresh, 'bad\nname.ru', severity='warning')['formatted'])
        with self.assertRaises(ValueError):
            diagnostic(issue, severity='anything')


class StatementStyleCLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / 'main.ru'
        self.source.write_text('算 值:\n 得 42.\n法\n显 值.\n', encoding='utf-8')

    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'ru'), *map(str, args)],
                              cwd=self.root, capture_output=True, text=True, timeout=60)

    def test_check_default_warns_without_changing_exit_or_stdout(self):
        for target in ('c', 'python'):
            with self.subTest(target=target):
                result = self.cli('check', self.source, '--target', target)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('检查通过', result.stdout)
                self.assertNotIn('warning:', result.stdout)
                self.assertEqual(len(result.stderr.splitlines()), 1)
                self.assertIn(f'{self.source}:3:2: warning: 书写规范', result.stderr)

    def test_strict_check_rejects_style_only_and_accepts_its_canonical_form(self):
        for target in ('c', 'python'):
            with self.subTest(target=target):
                result = self.cli('check', '--strict-style', '--target', target, self.source)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertIn(f'{self.source}:3:2: error: 书写规范', result.stderr)
        self.source.write_text(add_dots(self.source.read_text(encoding='utf-8')), encoding='utf-8')
        result = self.cli('check', self.source, '--strict-style')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')

    def test_imported_findings_use_original_path_and_are_deduplicated(self):
        dep = self.root / 'dep.ru'
        dep.write_text('算 值: 得 9. 法\n', encoding='utf-8')
        self.source.write_text("甲 取 外言 'dep.ru'. 乙 取 外言 './dep.ru'.\n", encoding='utf-8')
        for strict in (False, True):
            result = self.cli('check', self.source, *(['--strict-style'] if strict else []))
            self.assertEqual(result.returncode, 1 if strict else 0, result.stderr)
            self.assertEqual(len(result.stderr.splitlines()), 1)
            self.assertIn(f'{dep}:1:12:', result.stderr)
            self.assertNotIn(f'{self.source}:', result.stderr)

    def test_incomplete_or_invalid_import_is_not_disguised_as_a_style_error(self):
        dep = self.root / 'bad.ru'
        dep.write_text('算 甲: 得 1. 法\n显 2', encoding='utf-8')
        self.source.write_text("外言 './bad.ru'.", encoding='utf-8')
        result = self.cli('check', self.source, '--strict-style')
        self.assertEqual(result.returncode, 1)
        self.assertIn('语法错误', result.stderr)
        self.assertNotIn('书写规范', result.stderr)
        self.assertNotIn('warning:', result.stderr)
        self.assertIn(str(dep), result.stderr)

    def test_compile_semantic_errors_take_precedence_over_style(self):
        self.source.write_text('算 值: 得 新 未定义形. 法', encoding='utf-8')
        for command, options in (('check', []), ('build', ['--target', 'c']),
                                  ('build', ['--target', 'js'])):
            for strict in (False, True):
                with self.subTest(command=command, options=options, strict=strict):
                    result = self.cli(command, self.source, *options,
                                      *(['--strict-style'] if strict else []))
                    self.assertEqual(result.returncode, 1)
                    self.assertNotIn('书写规范', result.stderr)
                    self.assertNotIn('warning:', result.stderr)
                    self.assertIn('未定义形', result.stderr)

    def test_strict_build_does_not_publish_outputs_or_call_external_compiler(self):
        for target in ('c', 'js'):
            with self.subTest(target=target):
                output, cfile = self.root / ('program.' + target), self.root / 'out.c'
                output.write_bytes(b'preserve-output')
                cfile.write_bytes(b'preserve-c')
                extra = ['--cc', 'compiler-must-not-run', '--emit-c', cfile] if target == 'c' else []
                result = self.cli('build', self.source, '--target', target, '--strict-style',
                                  '-o', output, *extra)
                self.assertEqual(result.returncode, 1)
                self.assertIn('书写规范', result.stderr)
                self.assertEqual(output.read_bytes(), b'preserve-output')
                self.assertEqual(cfile.read_bytes(), b'preserve-c')
                self.assertEqual(result.stdout, '')

    def test_default_js_build_warns_but_emits_only_javascript(self):
        output = self.root / 'out.js'
        result = self.cli('build', self.source, '--target', 'js', '-o', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('warning: 书写规范', result.stderr)
        self.assertNotIn('warning:', result.stdout)
        self.assertNotIn('完整语句结束后建议写句点', output.read_text(encoding='utf-8'))
        if NODE:
            executed = subprocess.run([NODE, str(output)], capture_output=True, text=True, timeout=10)
            self.assertEqual((executed.returncode, executed.stdout, executed.stderr), (0, '42\n', ''))

    @unittest.skipUnless(CC, 'requires a C compiler')
    def test_default_c_build_warns_but_program_and_emitted_c_are_clean(self):
        output, emitted = self.root / 'out.exe', self.root / 'out.c'
        result = self.cli('build', self.source, '--cc', CC, '--emit-c', emitted, '-o', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('warning: 书写规范', result.stderr)
        self.assertNotIn('完整语句结束后建议写句点', emitted.read_text(encoding='utf-8'))
        executed = subprocess.run([str(output)], capture_output=True, text=True, timeout=10)
        self.assertEqual((executed.returncode, executed.stdout, executed.stderr), (0, '42\n', ''))

    def test_run_and_prompt_stdout_do_not_acquire_style_diagnostics(self):
        result = self.cli('run', self.source)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '42\n', ''))
        for command in ('rushu-prompt', 'ruguan-prompt'):
            result = self.cli(command)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            self.assertNotIn(': warning:', result.stdout)

    def test_help_documents_strict_style_only_on_check_and_build(self):
        for command in ('check', 'build'):
            self.assertIn('--strict-style', self.cli(command, '--help').stdout)
        self.assertNotIn('--strict-style', self.cli('run', '--help').stdout)


if __name__ == '__main__':
    unittest.main()
