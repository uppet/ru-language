"""Symbolic map literals share the existing AST and all runtime map semantics."""
import unittest

from rulang.frontend import Incomplete, RuError, lex, parse
from test_map_index_read import MapIndexContract, NODE, CC


class SymbolMapContract:
    backend = 'python'
    full_runtime = False
    run_source = MapIndexContract.run_source
    output = MapIndexContract.output
    error = MapIndexContract.error

    def test_user_example_empty_missing_duplicate_and_fact_keys(self):
        self.output("戏 取 {'心': 0, '意': 1, '心': 2, 真: '事实', 1: '数'}. "
                    "显 戏['心']. 显 戏['意']. 显 戏['缺']. 显 戏[真]. 显 戏[1]. "
                    "显 {} 其 量. 显 {'空':空}['空']. 显 {'假':假}['假'].",
                    '2\n1\n空\n事实\n数\n0\n空\n假\n')

    def test_nested_multiline_and_both_literal_forms(self):
        self.output("""表 取 ｛
            ‘内’： {'阵': [1, 2,], '旧': 典: '值' 对 7. 成,},
            ‘空’：｛｝，
        ｝。
        显 表['内']['阵'][1]. 显 表['内']['旧']['值']. 显 表['空'] 其 量.
        旧 取 典: '新' 对 {'值':8}. 成. 显 旧['新']['值'].
        """, '2\n7\n0\n8\n')

    def test_expression_keys_values_and_named_call_disambiguation(self):
        self.output("""
算 加 左 右: 得 左+右. 法
算 回 表: 得 表. 法
键 取 '值'.
表 取 {键: (加 左:2 右:3), (加 1 2): 4+5, '切': [6,7][0:1]}.
显 表['值']. 显 表[3]. 显 表['切'][0].
显 (回 表:{'名':8})['名']. 显 (回 {'位':9})['位'].
显 [{'阵':10}][0]['阵'].
""", '5\n9\n6\n8\n9\n10\n')

    def test_source_evaluation_order_and_new_identity(self):
        self.output("""
算 记 值: 显 值. 得 值. 法
表 取 {(记 '甲'): (记 1), (记 '甲'): (记 2)}.
显 表['甲']. 显 {} == {}.
""", '甲\n1\n甲\n2\n2\n假\n')

    def test_object_hash_protocol_and_original_key(self):
        self.output("""
形 键形:
    值 为 数. 标签 为 句.
    算 同 另一: 得 其 值 == 另一 其 值. 法
    算 印: 得 其 值. 法
象
甲 取 新 键形 值:1 标签:'原'. 乙 取 新 键形 值:1 标签:'新'.
表 取 {甲: 2, 乙: 3}.
显 表 其 量. 显 表[乙].
表 其 列 作 键 值: 显 键 其 标签. 显 值. 为.
""", '1\n3\n原\n3\n')

    def test_closure_constructor_and_shared_value(self):
        self.output("""
形 盒: 值 为 数. 象
列值 取 [1].
表 取 {'算':算 值: 得 值+1. 法, '作':作 值: 显 值. 为,
         '物':(新 盒 值:3), '列':列值}.
显 表['算'] 7. 表['作'] 9. 显 表['物'] 其 值.
列值[0] 取 5. 显 表['列'][0].
""", '8\n9\n3\n5\n')

    def test_invalid_keys_use_existing_protocol(self):
        for key in ('空', '[]', '{}', '(1 对 2)', '(算: 得 1. 法)'):
            with self.subTest(key=key):
                self.error('显 {' + key + ':1}.', '键|印|同')


class PythonSymbolMapTests(SymbolMapContract, unittest.TestCase):
    pass


@unittest.skipUnless(CC, 'C compiler required')
class CSymbolMapTests(SymbolMapContract, unittest.TestCase):
    backend = 'c'


@unittest.skipUnless(CC, 'C compiler required')
class FullCSymbolMapTests(CSymbolMapTests):
    full_runtime = True


@unittest.skipUnless(NODE, 'Node.js required')
class JavaScriptSymbolMapTests(SymbolMapContract, unittest.TestCase):
    backend = 'js'


@unittest.skipUnless(NODE, 'Node.js required')
class FullJavaScriptSymbolMapTests(JavaScriptSymbolMapTests):
    full_runtime = True


class SymbolMapFrontendTests(unittest.TestCase):
    def test_same_ast(self):
        def structure(value):
            if hasattr(value, 'kind'):
                return value.kind, structure(value.data)
            if isinstance(value, dict):
                return {key: structure(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [structure(item) for item in value]
            return value
        self.assertEqual(structure(parse("表 取 {'心':0,'意':1}.")),
                         structure(parse("表 取 典: '心' 对 0. '意' 对 1. 成.")))

    def test_fullwidth_tokens(self):
        self.assertEqual([t.value for t in lex('｛｝：，')[:-1]], ['{', '}', ':', ','])

    def test_incomplete_requests_continuation(self):
        for source in ('表 取 {', "表 取 {'心'", "表 取 {'心':", "表 取 {'心':0", "表 取 {'心':0,", '显 {}'):
            with self.subTest(source=source), self.assertRaises(Incomplete):
                parse(source)

    def test_malformed_literals(self):
        for source in ("显 {,}.", "显 {'心' 0}.", "显 {'心':}.",
                       "显 {'心':0 '意':1}.", "显 {'心':0,,}.",
                       "显 {'心':0.}.", "显 {'心':0]."):
            with self.subTest(source=source), self.assertRaises(RuError):
                parse(source)

    def test_comments_and_non_string_punctuation(self):
        program = parse("表 取 { # 注释\n ':': 1, 解. } : , 释. '}':2,}. 显 表['}'].")
        self.assertEqual(len(program[0].data['expr'].data['entries']), 2)

    def test_calls_keep_array_comma_strategy(self):
        program = parse("表 取 {'甲': 加 1,2}.")
        value = program[0].data['expr'].data['entries'][0][1]
        self.assertEqual(value.kind, 'call')
        self.assertEqual(len(value.data['args']), 2)
