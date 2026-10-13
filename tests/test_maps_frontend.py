"""Map/fact syntax, editor-facing continuation and ordinary member grammar."""
import io
import unittest

from rulang.compiler import Compiler
from rulang.frontend import Incomplete, RuError, parse, validate
from rulang.interpreter import Interpreter
from rulang.js_compiler import JSCompiler


class MapsFactsFrontend(unittest.TestCase):
    def test_unicode_literals_and_annotations(self):
        source = '算 回 表 为 典 值 为 事实： 得 表。 法 表 取 典：‘上’ 对 真。成。显（回 表 假）其 查 ‘上’。'
        program = parse(source)
        validate(program)
        self.assertEqual(program[1].data['expr'].kind, 'map')
        output = io.StringIO()
        Interpreter(stdout=output).execute(program)
        self.assertEqual(output.getvalue(), '真\n')

    def test_incomplete_map_waits_for_closer(self):
        for source in ('表 取 典:', '表 取 典: 1 对', '表 取 典: 1 对 2.', '显 典: 成'):
            with self.subTest(source=source), self.assertRaises(Incomplete):
                parse(source)

    def test_new_reserved_words_and_longest_names(self):
        for word in ('典', '成', '真', '假'):
            with self.subTest(word=word), self.assertRaises(RuError):
                parse(word + ' 取 1.')
        validate(parse('典册 取 1. 成就 取 2. 真假 取 3.'))
        with self.assertRaises(RuError):
            validate(parse('形 事实: 象'))

    def test_member_names_dispatch_by_receiver(self):
        source = '''
形 盒: 增 为 算. 位 为 数.
    算 查 左 右: 得 左+右. 法
    算 量 个: 得 个. 法
象
物 取 新 盒 增:(算 甲 乙: 得 甲*乙. 法) 位:7.
显 物 其 查 2 3.
显 物 其 量 9.
显 物 其 增 3 4.
显 物 其 位.
列 取 []. 列 其 增 1+2. 显 列.
'''
        program = parse(source)
        output = io.StringIO()
        Interpreter(stdout=output).execute(program)
        self.assertEqual(output.getvalue(), '5\n9\n12\n7\n[3]\n')
        Compiler(program).compile()
        JSCompiler(program).compile()

    def test_compilation_never_invokes_key_protocol(self):
        source = '''
形 键形:
    算 同 另一: 卒 '不得编译期执行同'. 法
    算 印: 卒 '不得编译期执行印'. 法
象
表 取 典: (新 键形) 对 1. 成.
'''
        program = parse(source)
        Compiler(program).compile()
        JSCompiler(program).compile()

    def test_map_repl_state_and_fact_echo(self):
        output = io.StringIO()
        interpreter = Interpreter(stdout=output)
        interpreter.execute(parse('表 取 典: 成.'), echo=True)
        interpreter.execute(parse("表 其 增 '甲' 假."), echo=True)
        interpreter.execute(parse("表 其 查 '甲'."), echo=True)
        interpreter.execute(parse("表 其 逐目 作 键 值: 完. 为."), echo=True)
        self.assertEqual(output.getvalue(), '{甲: 假}\n假\n空\n')
