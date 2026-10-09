"""Contextual statement blocks and statement-only Pascal assignment aliases."""
import unittest
from pathlib import Path
import tempfile
from rulang.frontend import Incomplete, Node, RuError, lex, parse, validate
from test_map_index_read import MapIndexContract, NODE, CC


class ScopedSyntaxTests(unittest.TestCase):
    def test_equivalent_delimiters(self):
        def shape(value):
            if isinstance(value, Node):
                return value.kind, shape(value.data)
            if isinstance(value, dict):
                return {k: shape(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [shape(v) for v in value]
            return value
        self.assertEqual(shape(parse('段：甲 取 1。落。')), shape(parse('｛甲 := 1。｝')))
        self.assertEqual(parse('{}')[0].kind, 'scope')
        self.assertEqual(parse('显 {}.')[0].data['expr'].kind, 'map')
        self.assertEqual(parse('({}).')[0].data['expr'].kind, 'map')

    def test_contextual_names(self):
        source = "段 取 1. 落 取 2. 段落 取 3. 段: 落 取 4. 显 落. 落. 显 'abc' 其 段 始:0 终:1."
        validate(parse(source))
        self.assertEqual([t.value for t in lex('x:=1. y：=2.') if t.value == ':='], [':=', ':='])

    def test_quoted_assignment_markers_are_call_arguments(self):
        for text in ('取', ':=', '落'):
            expression = parse("报 '" + text + "'.")[0].data['expr']
            self.assertEqual(expression.kind, 'call')
            self.assertEqual(expression.data['args'][0][1].kind, 'string')

    def test_incomplete_blocks(self):
        for source in ('{', '{ 显 1.', '段:', '段: 显 1.', '段: 落'):
            with self.subTest(source=source), self.assertRaises(Incomplete):
                parse(source)

    def test_structural_restrictions(self):
        for body in ('形 盒: 象', "尽 取 外言 'other.ru'.", '得 1.', '完.', '破.'):
            for template in ('{ %s }', '段: %s 落.'):
                with self.subTest(body=body, template=template), self.assertRaises(RuError):
                    validate(parse(template % body))
        for source in ('算 甲: 段: 得 1. 落. 法', '作 甲: { 完. } 为', '循 { 破. } 环'):
            validate(parse(source))
        for source in ('循 { 算 甲: 破. 法 } 环', '{ 若 真 则 算 甲: 得 1. 法 然 }'):
            with self.assertRaises(RuError):
                validate(parse(source))

    def test_assignment_is_not_expression_or_import_all_alias(self):
        for source in ('显 (甲 := 1).', '甲 := (乙 := 2).', '尽 := 外言 "a.ru".', '甲 : = 1.', '甲 :＝ 1.'):
            with self.subTest(source=source), self.assertRaises(RuError):
                parse(source)


class AssignmentAliasContract:
    backend = 'python'
    full_runtime = False
    run_source = MapIndexContract.run_source
    output = MapIndexContract.output
    error = MapIndexContract.error

    def test_all_assignment_targets_and_maps(self):
        self.output("形 盒: 值 为 数. 象 甲 := 1. 列 := [甲]. 列[0] := 2. "
                    "列 其 位 位:0 := 3. 物 := 新 盒 值:4. 物 其 值 := 5. "
                    "表 ：= {'心':物 其 值}.  "
                    "显 列[0]. 显 物 其 值. 显 表['心'].", '3\n5\n5\n')

    def test_import_binding_alias_and_module_block_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            module = Path(folder) / 'scope.ru'
            module.write_text('袋 := []. { 值 := 3. 算 加: 值 := 值+1. 得 值. 法 袋 其 增 算 加. }', encoding='utf-8')
            path = str(module).replace('\\', '/').replace("'", "\\'")
            self.output("模块 := 外言 '" + path + "'. 显 模块 其 袋[0](). 显 模块 其 袋[0]().", '4\n5\n')

    def test_illegal_target_remains_illegal_before_rhs(self):
        self.assertEqual(self.error("算 右: 显 '不应'. 得 1. 法 表 := {}. 表['心'] := 右.", '赋值|修改阵'), '')

    def test_alias_obeys_block_and_closure_scope(self):
        self.output("值 := 10. 存 := []. { 值 := 1. "
                    "算 加: 值 := 值+1. 得 值. 法 存 其 增 算 加. } "
                    "显 存[0](). 显 存[0](). 显 值. "
                    "段：值 ：= 30。 显 值。 落。 显 值。", '2\n3\n10\n30\n10\n')


class PythonAssignmentAliasTests(AssignmentAliasContract, unittest.TestCase):
    pass


@unittest.skipUnless(NODE, 'Node.js unavailable')
class JSAssignmentAliasTests(AssignmentAliasContract, unittest.TestCase):
    backend = 'js'


@unittest.skipUnless(CC, 'C compiler unavailable')
class CAssignmentAliasTests(AssignmentAliasContract, unittest.TestCase):
    backend = 'c'


@unittest.skipUnless(CC, 'C compiler unavailable')
class CFullAssignmentAliasTests(AssignmentAliasContract, unittest.TestCase):
    backend = 'c'
    full_runtime = True


@unittest.skipUnless(NODE, 'Node.js unavailable')
class JSFullAssignmentAliasTests(AssignmentAliasContract, unittest.TestCase):
    backend = 'js'
    full_runtime = True
