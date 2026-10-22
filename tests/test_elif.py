"""Single-closer condition chains preserve the existing nested-if contract."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from rulang.browser_compiler import compile_browser
from rulang.cli import build
from rulang.diagnostics import SourceOrigin
from rulang.frontend import Incomplete, KEYWORDS, Node, Parser, RuError, lex, parse, style_issues, validate
from rulang.interpreter import Interpreter

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node') or shutil.which('nodejs')
CC = bool(os.environ.get('CC')) or any(shutil.which(c) for c in ('cc', 'gcc', 'clang'))


def semantics(value):
    if isinstance(value, Node):
        return value.kind, semantics(value.data)
    if isinstance(value, dict):
        return {k: semantics(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [semantics(v) for v in value]
    return value


class ElifSyntaxTests(unittest.TestCase):
    def test_same_ast_as_explicit_nesting(self):
        compact = '若 假 则 显 1. 另若 假 则 显 2. 另若 真 则 显 3. 另 显 4. 然.'
        nested = '若 假 则 显 1. 另 若 假 则 显 2. 另 若 真 则 显 3. 另 显 4. 然. 然. 然.'
        self.assertEqual(semantics(parse(compact)), semantics(parse(nested)))

    def test_whole_keyword_not_prefix_and_space_not_erased(self):
        self.assertIn('另若', KEYWORDS)
        source = '另若 另 若 另若值 前另若 _另若 另若2'
        self.assertEqual([t.value for t in lex(source)][:-1], source.split())
        validate(parse('另若值 取 1. 前另若 取 2. _另若 取 3. 另若2 取 4.'))
        self.assertEqual(lex('另若(真)')[0].value, '另若')
        self.assertEqual(lex('另若真')[0].value, '另若真')

    def test_reserved_name_in_all_declaration_positions(self):
        for source in ('另若 取 1.', '算 另若: 得 1. 法.', '算 甲 另若: 得 1. 法.',
                       '形 另若: 象.', '形 盒: 另若 为 数. 象.',
                       '显 物 其 另若.', '吾 言 另若.', '甲 取 算 另若: 得 1. 法.'):
            with self.subTest(source=source), self.assertRaises(RuError):
                parse(source)

    def test_strings_and_comments_do_not_become_branch_markers(self):
        source = "若 假 则 显 '另若'. 解. 另若 假 则 然 释. 另若 真 则 显 '另'. 然."
        self.assertEqual(len(parse(source)), 1)
        spaced = '若 假 则 另 解. keep nesting 释. 若 真 则 然. 然.'
        self.assertEqual(parse(spaced)[0].data['no'][0].token.value, '若')
        with self.assertRaises(Incomplete):
            parse('若 假 则 另\n若 真 则 然.')

    def test_fullwidth_and_adjacent_punctuation(self):
        source = '若(假)则 显 1。另若(真)则 显 2。另 显 3。然。'
        validate(parse(source))
        self.assertEqual(style_issues(source), [])

    def test_only_one_style_closer(self):
        source = '若 假 则 另若 假 则 另若 真 则 然'
        issues = style_issues(source)
        self.assertEqual([(i.line, i.col) for i in issues], [(1, len(source)+1)])
        self.assertEqual(style_issues(source+'.'), [])
        nested = '若 假 则 另若 真 则 若 真 则 然 然'
        self.assertEqual(len(style_issues(nested)), 2)

    def test_token_locations_and_origin_survive_lowering(self):
        origin = SourceOrigin('elif.ru')
        program = parse('若 假 则\n另若 假 则\n  另若 真 则 显 7.\n然.', source_origin=origin)
        branch = program[0].data['no'][0]
        self.assertEqual((branch.token.value, branch.token.line, branch.token.col), ('另若', 2, 1))
        self.assertEqual(branch.token.source_origin, origin)
        last = branch.data['no'][0]
        self.assertEqual((last.token.value, last.token.line, last.token.col), ('另若', 3, 3))

    def test_misplaced_branch_precise_location(self):
        for source, line, col in (
            ('另若 真 则 然.', 1, 1),
            ('若 假 则\n另\n  另若 真 则 然.', 3, 3),
            ('若 真 则 然.\n另若 真 则 然.', 2, 1),
            ('若 真 则 {\n另若 真 则 然. } 然.', 2, 1),
        ):
            with self.subTest(source=source), self.assertRaises(RuError) as caught:
                parse(source)
            self.assertEqual((caught.exception.line, caught.exception.col), (line, col))
            self.assertIn('另若', str(caught.exception))

    def test_missing_condition_then_and_extra_closers_rejected(self):
        for source in ('若 假 则 另若 则 然.', '若 假 则 另若 真 显 1. 然.',
                       '若 假 则 另若 真 则 然. 然.',
                       '若 假 则 另 另 显 1. 然.'):
            with self.subTest(source=source), self.assertRaises(RuError):
                parse(source)

    def test_incomplete_prefixes_for_repl(self):
        for source in ('若 假 则', '若 假 则 另若', '若 假 则 另若 真',
                       '若 假 则 另若 真 则', '若 假 则 另若 真 则 显 1.',
                       '若 假 则 另若 真 则 另'):
            with self.subTest(source=source), self.assertRaises(Incomplete):
                parse(source)

    def test_repl_waits_for_single_closer(self):
        source = '若 假 则\n显 1.\n另若 真 则\n显 2.\n另\n显 3.\n然.\n显 4.\n'
        result = subprocess.run([sys.executable, str(ROOT/'ru'), 'repl'], input=source,
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '2\n4\n', ''))

    def test_chain_respects_equivalent_nesting_budget(self):
        for count in (1, 40, 120, 126, 127, 128, 129, 1000):
            compact = '若 假 则 ' + '另若 假 则 '*(count-1) + '另 显 7. 然.'
            nested = '若 假 则 另 '*count + '显 7. ' + '然. '*count
            accepted = []
            for source in (compact, nested):
                try:
                    validate(parse(source))
                    accepted.append(True)
                except RuError as error:
                    self.assertIn('嵌套过深', str(error))
                    accepted.append(False)
            self.assertEqual(accepted[0], accepted[1], count)

    def test_parser_depth_restored_after_failure(self):
        parser = Parser('若 假 则 ' + '另若 假 则 '*1000)
        with self.assertRaises(RuError):
            parser.parse()
        self.assertEqual(parser.depth, 0)

    def test_structural_validation_applies_to_all_branches(self):
        for body in ('得 1.', '完.', '破.', '形 盒: 象.', '算 甲: 得 1. 法.',
                     "尽取 外言 'missing.ru'."):
            with self.subTest(body=body), self.assertRaises(RuError):
                validate(parse('若 真 则 另若 假 则 '+body+' 然.'))


class ElifIntegrationTests(unittest.TestCase):
    def test_import_all_conditional_callable_exports(self):
        import test_conditional_exports
        checker = test_conditional_exports.ConditionalExportTests()
        checker.check_engines(
            '若 假 则 回 取 算 值: 得 99. 法. '
            '另若 真 则 回 取 算 值: 得 值+1. 法. 然.',
            "尽取 外言 'lib.ru'. 显 回 2. 显 回 值:4.", '3\n5\n')

    def test_real_notebook_spawn_and_cross_cell_state(self):
        import test_rushu_kernel
        from rushu.kernel import Session
        session = Session()
        self.addCleanup(session.close)
        session.execute('若 假 则 值 取 99. 另若 真 则 值 取 7. 然.', 'branch')
        first = test_rushu_kernel.wait_for(session)
        self.assertEqual(first['events'][-1]['status'], 'ok')
        cursor = first['cursor']
        session.execute('显 值.', 'next')
        second = test_rushu_kernel.wait_for(session, after=cursor)
        self.assertEqual(test_rushu_kernel.output(second), '7\n')
        self.assertEqual(second['events'][-1]['status'], 'ok')

    def test_condition_failure_reports_elif_source_line(self):
        source = '若 假 则\n另若 1 / 0 则 显 7.\n然.'
        origin = SourceOrigin.cell('test', 'condition', 3, 1, source)
        with self.assertRaises(RuError) as caught:
            Interpreter(stdout=io.StringIO()).execute(parse(source, source_origin=origin))
        self.assertEqual(caught.exception.line, 2)
        self.assertEqual(caught.exception.source_origin, origin)



class ElifContract:
    backend = 'python'
    full_runtime = False

    def output(self, source, expected):
        if self.backend == 'python':
            out = io.StringIO()
            Interpreter(io.StringIO(), out).execute(parse(source))
            self.assertEqual(out.getvalue(), expected)
            return
        with tempfile.TemporaryDirectory(prefix='ru-elif-') as folder:
            path = Path(folder)
            if self.backend == 'browser':
                (path/'program.mjs').write_text(compile_browser(source), encoding='utf-8')
                runner = path/'run.mjs'
                runner.write_text("import create from './program.mjs';const events=[];"
                                  "create({emit:e=>events.push(e)});"
                                  "console.log(JSON.stringify(events));", encoding='utf-8')
                result = subprocess.run([NODE, str(runner)], capture_output=True, text=True,
                                        encoding='utf-8', timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(''.join(e.get('text', '') for e in json.loads(result.stdout)), expected)
            else:
                binary, _ = build(parse(source), path/'case.ru', path/'case', target=self.backend,
                                  full_runtime=self.full_runtime)
                command = [NODE, str(binary)] if self.backend == 'js' else [str(binary)]
                result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=20)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ''))

    def test_order_single_evaluation_and_lazy_skips(self):
        self.output("算 问 号 答: 显 号. 得 答. 法 "
                    "若 问 1 假 则 显 99. 另若 问 2 真 则 显 7. "
                    "另若 问 3 真 则 显 98. 另 显 97. 然. "
                    "若 真 则 显 8. 另若 1 / 0 则 显 96. 然.", '1\n2\n7\n8\n')

    def test_existing_truth_empty_branches_and_no_else(self):
        self.output("若 空 则 另若 假 则 另若 0 则 显 1. 另 显 99. 然. "
                    "若 假 则 另若 空 则 显 98. 然. "
                    "若 真 则 另若 真 则 显 97. 然. 显 2.", '1\n2\n')

    def test_shared_scope_and_explicit_scope_closure(self):
        self.output("值 取 1. 若 假 则 值 取 99. 另若 真 则 值 取 2. 新值 取 3. 然. "
                    "显 值. 显 新值. 列 取 []. { 值 取 4. "
                    "若 假 则 另若 真 则 列 其 增 算: 值 取 值+1. 得 值. 法. 然. } "
                    "显 列[0](). 显 列[0](). 显 值.", '2\n3\n5\n6\n2\n')

    def test_nested_and_legacy_branches(self):
        self.output("若 假 则 显 99. 另若 真 则 "
                    "若 假 则 另若 真 则 显 1. 然. "
                    "另 显 98. 然. "
                    "若 假 则 显 97. 另 若 假 则 另若 真 则 显 2. 然. 显 3. 然.", '1\n2\n3\n')

    def test_return_finish_break_and_rescue(self):
        self.output("算 求 值: 若 值 == 1 则 得 1. 另若 值 == 2 则 得 2. 另 得 3. 然. 法. "
                    "作 报: 若 假 则 另若 真 则 完. 然. 显 99. 为. 报. 显 求 2. "
                    "循 3 次 若 假 则 另若 真 则 { 破. } 然. 显 98. 环. "
                    "试 若 假 则 另若 真 则 卒 '因'. 然. 救 原因 显 原因. 终. 显 4.", '2\n因\n4\n')

    def test_long_chain_with_false_conditions(self):
        self.output('若 假 则 ' + '另若 假 则 '*90 + '另若 真 则 显 7. 然.', '7\n')


class ElifPythonTests(ElifContract, unittest.TestCase):
    pass


@unittest.skipUnless(CC, 'C compiler required')
class ElifCTests(ElifContract, unittest.TestCase):
    backend = 'c'


@unittest.skipUnless(CC, 'C compiler required')
class ElifFullCTests(ElifCTests):
    full_runtime = True


@unittest.skipUnless(NODE, 'Node.js required')
class ElifJSTests(ElifContract, unittest.TestCase):
    backend = 'js'


@unittest.skipUnless(NODE, 'Node.js required')
class ElifFullJSTests(ElifJSTests):
    full_runtime = True


@unittest.skipUnless(NODE, 'Node.js required')
class ElifBrowserTests(ElifContract, unittest.TestCase):
    backend = 'browser'


if __name__ == '__main__':
    unittest.main()
