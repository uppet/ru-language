"""The canonical whole-token import statement and explicit legacy migration."""
import json
import subprocess
import sys
from pathlib import Path
import re
import tempfile
import unittest

from rulang.browser_compiler import compile_browser
from rulang.frontend import Incomplete, KEYWORDS, RuError, lex, parse, validate
from rulang.generation import generation_system_prompt
from rulang.modules import load_module_graph
from test_map_index_read import CC, NODE, MapIndexContract


class ImportAllSyntaxTests(unittest.TestCase):
    def test_canonical_statement_preserves_import_ast(self):
        for source in ("尽取 外言 '如:数学'.", '尽取\n外言 “如:数学”。',
                       "尽取 解. 说明 释. 外言 '如:数学'.",
                       "尽取 (外言 '如:数学')."):
            with self.subTest(source=source):
                program = parse(source)
                validate(program)
                self.assertEqual(len(program), 1)
                self.assertEqual(program[0].kind, 'import_all')
                self.assertEqual(program[0].token.value, '尽取')
                self.assertEqual(program[0].data['expr'].kind, 'import')
                self.assertEqual(program[0].data['expr'].data['path'], '如:数学')

    def test_legacy_spelling_always_gives_migration_at_original_token(self):
        for separator in (' ', '\t', '\n', ' 解. 注释 释. ', ' # 注释\n'):
            source = "\n  尽" + separator + "取 外言 'missing.ru'."
            with self.subTest(separator=separator), self.assertRaises(RuError) as caught:
                parse(source)
            self.assertNotIsInstance(caught.exception, Incomplete)
            self.assertRegex(caught.exception.message, '旧语法.*已停用.*尽取 外言.*连写')
            self.assertEqual((caught.exception.line, caught.exception.col), (2, 3))
        for wrapper in ('算 回: %s 得 1. 法', '若 真 则 %s 然', '{ %s }'):
            with self.subTest(wrapper=wrapper), self.assertRaisesRegex(RuError, '旧语法.*尽取 外言'):
                parse(wrapper % "尽 取 外言 'missing.ru'.")

    def test_whole_names_and_non_aliases(self):
        names = ('尽取值', '尽取器', '未尽取', '_尽取', '尽取2', 'α尽取', '𠀀尽取', '尽取²',
                 '进取', '言')
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(lex(name)[0].value, name)
                self.assertNotIn(name, KEYWORDS)
                validate(parse(name + ' 取 1. 显 ' + name + '.'))
        self.assertEqual(parse("进取 外言 '如:数学'.")[0].data['expr'].kind, 'call')
        self.assertEqual(parse("言 '如:数学'.")[0].data['expr'].kind, 'call')
        for source in ("尽取 言 '如:数学'.", "尽取 '如:数学'.", '尽取 模块.',
                       "尽 := 外言 '如:数学'.", "尽取 := 外言 '如:数学'.",
                       "尽取 取 外言 '如:数学'.", "显 (尽取 外言 '如:数学')."):
            with self.subTest(source=source), self.assertRaises(RuError):
                parse(source)

    def test_new_and_legacy_keywords_remain_reserved(self):
        for name in ('尽取', '尽'):
            self.assertIn(name, KEYWORDS)
            for template in ('%s 取 1.', '算 %s: 得 1. 法', '算 回 %s: 得 1. 法',
                             '形 %s: 象', '形 盒: %s 为 数. 象', '显 模块 其 %s.'):
                with self.subTest(name=name, template=template), self.assertRaises(RuError):
                    parse(template % name)

    def test_top_level_only_for_all_nested_statement_contexts(self):
        statement = "尽取 外言 '如:数学'."
        for template in ('若 真 则 %s 然', '循 1 次 %s 环',
                         '算 回: %s 得 1. 法', '作 回: %s 为',
                         '形 盒: 算 回: %s 得 1. 法 象',
                         '试 %s 救 错 显 错. 终', '试 显 1. 救 错 %s 终',
                         '段: %s 落.', '{ %s }',
                         '回 取 算: %s 得 1. 法.'):
            with self.subTest(template=template), self.assertRaisesRegex(RuError, '尽取 外言.*顶层'):
                validate(parse(template % statement))

    def test_strings_comments_and_longer_names_do_not_import(self):
        source = "显 '尽 取 外言'. # 尽取 外言 'bad.ru'.\n解. 尽 取 外言 'bad.ru'. 释. 尽取值 取 2."
        self.assertEqual([n.kind for n in parse(source)], ['print', 'bind'])

    def test_static_resolution_and_legacy_rejection_do_not_run_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'lib.ru').write_text('显 1/0.', encoding='utf-8')
            source = root / 'main.ru'
            source.write_text("尽取 外言 'lib.ru'.", encoding='utf-8')
            graph = load_module_graph(source)
            self.assertEqual(len(graph), 2)
            self.assertEqual(graph[graph.root][0].kind, 'import_all')
            source.write_text("尽 取 外言 'does-not-exist.ru'.", encoding='utf-8')
            with self.assertRaisesRegex(RuError, '旧语法.*尽取 外言'):
                load_module_graph(source)

    def test_cli_targets_report_migration_before_reading_module_or_running_code(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'legacy.ru'
            source.write_text("显 '不应输出'.\n尽 取 外言 'missing.ru'.", encoding='utf-8')
            commands = [('run',), ('check', '--target', 'python'),
                        ('check', '--target', 'c'),
                        ('build', '--target', 'c'), ('build', '--target', 'js')]
            for command in commands:
                with self.subTest(command=command):
                    result = subprocess.run([sys.executable, str(root / 'ru'), *command, str(source)],
                                            capture_output=True, text=True, encoding='utf-8', timeout=10)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(result.stdout, '')
                    self.assertIn(str(source) + ':2:1:', result.stderr)
                    self.assertRegex(result.stderr, '旧语法.*已停用.*尽取 外言')
                    self.assertNotIn('无法读取外言', result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [source])

    def test_browser_rejects_legacy_spelling_at_frontend(self):
        with self.assertRaisesRegex(RuError, '旧语法.*尽取 外言'):
            compile_browser("尽 取 外言 '如:数学'.")

    @unittest.skipUnless(NODE, 'Node.js unavailable')
    def test_browser_standard_module_import_runs_as_esm(self):
        javascript = compile_browser("尽取 外言 '如:数学'. 显 平方根 16. 显 余弦 0.")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'program.mjs').write_text(javascript, encoding='utf-8')
            (root / 'run.mjs').write_text(
                "import create from './program.mjs'; const events=[];"
                "create({emit:event=>events.push(event)});"
                "console.log(JSON.stringify(events));", encoding='utf-8')
            result = subprocess.run([NODE, str(root / 'run.mjs')], capture_output=True,
                                    text=True, encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(''.join(event.get('text', '') for event in json.loads(result.stdout)), '4\n1\n')

    def test_generation_knowledge_and_executable_fences_use_canonical_spelling(self):
        for target in ('cli', 'rushu', 'ruguan', 'rushu-browser-js', 'ruguan-browser-js'):
            with self.subTest(target=target):
                prompt = generation_system_prompt(target)
                self.assertIn("'尽取' '外言' 外言目标", prompt)
                self.assertRegex(prompt, r"外言目标\s*= 字符串 \| 模块名")
                self.assertRegex(prompt, r"模块名\s*= 名称 \{ '其' 名称 \}")
                self.assertIn('旧式 `尽 取 外言` 已停用', prompt)
                self.assertIn('单字 `尽` 继续保留用于迁移诊断', prompt)
                self.assertNotIn("'尽' '取' '外言'", prompt)
                for example in re.findall(r'^```ru\s*\n(.*?)^```', prompt, re.M | re.S):
                    self.assertNotRegex(example, r'尽\s+取')


class ImportAllRuntimeContract:
    run_source = MapIndexContract.run_source
    output = MapIndexContract.output
    error = MapIndexContract.error
    backend = 'python'
    full_runtime = False

    def test_standard_library_import_and_assignment_are_separate(self):
        self.output("尽取 外言 '如:数学'. 值 := 平方根 16. 显 值. 显 余弦 0.", '4\n1\n')

    def test_retired_spelling_is_rejected_before_any_statement_executes(self):
        self.assertEqual(self.error("显 '不应输出'. 尽 取 外言 '如:数学'.", '旧语法.*尽取 外言'), '')

    def test_long_identifiers_remain_callable_and_bindable(self):
        self.output('算 尽取值 值: 得 值+1. 法 尽取器 := 4. 显 尽取值 尽取器.', '5\n')

    def test_import_collision_rules_remain(self):
        self.error("尽取 外言 '如:数学'. 尽取 外言 '如:竞'.", '冲突')
        self.error("尽取 外言 '如:数学'. 算 回 小: 得 小. 法 显 回 1.", '参数名|冲突')


class PythonImportAllTests(ImportAllRuntimeContract, unittest.TestCase):
    pass


@unittest.skipUnless(NODE, 'Node.js unavailable')
class JavaScriptImportAllTests(ImportAllRuntimeContract, unittest.TestCase):
    backend = 'js'


@unittest.skipUnless(CC, 'C compiler unavailable')
class NativeImportAllTests(ImportAllRuntimeContract, unittest.TestCase):
    backend = 'c'


if __name__ == '__main__':
    unittest.main()
