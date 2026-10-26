"""First-class lexical closures: interpreter/native parity and GC ownership."""
import gc
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import weakref

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.compiler import Compiler
from rulang.frontend import RuError, parse, validate
from rulang.interpreter import Interpreter
from rulang.modules import load_module_graph

CC = (shutil.which(os.environ['CC']) if os.environ.get('CC') else
      next((shutil.which(c) for c in ('clang', 'gcc', 'cc') if shutil.which(c)), None))

COUNTER = '''
算 制数 起 为 数:
    值 取 起.
    算 加 步 为 数:
        值 取 值 + 步.
        得 值.
    法
    得 算 加.
法
'''

CASES = [
    ('two_factories', COUNTER + "甲 取 制数 10. 乙 取 制数 100. 显 (甲 1). 显 (甲 2). 显 (乙 5). 显 (甲 3).", '11\n13\n105\n16\n'),
    ('captured_parameter', "算 制 起 为 数: 算 加: 起 取 起+1. 得 起. 法 得 算 加. 法 甲 取 制 4. 显 甲(). 显 甲().", '5\n6\n'),
    ('sibling_shared_cell', "算 制: 值 取 0. 作 改 新值 为 数: 值 取 新值. 为 算 看: 得 值. 法 得 [作 改, 算 看]. 法 组 取 制. 组[0] 7. 显 组[1](). 组[0] 新值:9. 显 组[1]().", '7\n9\n'),
    ('parent_mutates_after_capture', "算 制: 值 取 1. 算 看: 得 值. 法 回 取 算 看. 值 取 8. 得 回. 法 回调 取 制. 显 回调().", '8\n'),
    ('escaping_recursion', "算 制: 算 阶 根 为 数: 若 根 <= 1 则 得 1. 然 得 根*(阶 根-1). 法 得 算 阶. 法 回调 取 制. 显 (回调 6).", '720\n'),
    ('mutual_recursion', "算 制: 算 偶 数值 为 数: 若 数值 == 0 则 得 1. 然 得 奇 数值-1. 法 算 奇 数值 为 数: 若 数值 == 0 则 得 0. 然 得 偶 数值-1. 法 得 算 偶. 法 回调 取 制. 显 (回调 10). 显 (回调 9).", '1\n0\n'),
    ('forward_nested_reference', "算 制: 得 算 后. 算 后: 得 7. 法 法 回调 取 制. 显 回调().", '7\n'),
    ('three_lexical_levels', "算 外 起 为 数: 算 中 步 为 数: 算 内: 起 取 起+步. 得 起. 法 得 算 内. 法 得 算 中. 法 工厂 取 外 10. 甲 取 工厂 2. 乙 取 工厂 3. 显 甲(). 显 乙(). 显 甲().", '12\n15\n17\n'),
    ('lexical_not_dynamic', "算 制: 值 取 5. 算 看: 得 值. 法 得 算 看. 法 算 用 回调 为 算: 值 取 99. 得 回调(). 法 回调 取 制. 显 (用 回调).", '5\n'),
    ('global_shadow_preserved', "值 取 100. 算 制: 值 取 1. 算 加: 值 取 值+1. 得 值. 法 得 算 加. 法 回调 取 制. 显 回调(). 显 值. 算 普通: 值 取 值+1. 得 值. 法 显 普通. 显 值.", '2\n100\n101\n100\n'),
    ('parameter_shadows_capture', "算 制: 值 取 10. 算 看: 得 值. 法 算 改 值 为 数: 值 取 值+1. 得 值. 法 得 [算 改, 算 看]. 法 组 取 制. 显 (组[0] 2). 显 组[1]().", '3\n10\n'),
    ('higher_order_named', COUNTER + "算 应用 回调 为 算 左 为 数 右 为 数: 得 (回调 左)+(回调 步:右). 法 回调 取 制数 0. 显 (应用 右:3 回调:回调 左:2).", '7\n'),
    ('procedure_values', "算 制 起 为 数: 作 报 步 为 数: 起 取 起+步. 显 起. 为 得 作 报. 法 作 用 回调 为 作: 回调 2. 为 回调 取 制 10. 用 回调. 回调 3. 显 回调.", '12\n15\n<作 报>\n'),
    ('zero_argument_procedure', "作 报: 显 '好'. 为 回调 取 作 报. 回调(). 显 回调() == 空.", '好\n好\n真\n'),
    ('reference_identity', "算 制: 算 内: 得 1. 法 得 算 内. 法 甲 取 制. 别名 取 甲. 乙 取 制. 显 甲 == 别名. 显 甲 == 乙. 显 非 甲. 显 甲. 显 [甲,甲].", '真\n假\n假\n<算 内>\n[<算 内>, <算 内>]\n'),
    ('reference_no_autocall', "算 报: 显 '调用'. 得 4. 法 甲 取 算 报. 乙 取 算 报. 显 甲 == 乙. 显 甲(). 显 报.", '真\n调用\n4\n调用\n4\n'),
    ('generic_targets', COUNTER + "列 取 [制数 2]. 显 (列[0] 3). 显 ((制数 10) 5). 显 ((算 制数) 20) 1.", '5\n15\n21\n'),
    ('function_fields', "形 盒: 回调 为 算. 动作 为 作. 象 算 加 值 为 数: 得 值+1. 法 作 报: 显 '作'. 为 盒值 取 新 盒 回调:(算 加) 动作:(作 报). 显 (盒值 其 回调 4). (盒值 其 动作)().", '5\n作\n'),
    ('typed_callable_arrays', "算 加 值 为 数: 得 值+2. 法 算 用 列 为 算 阵: 得 列[0] 3. 法 显 (用 [算 加]).", '5\n'),
    ('bound_method', "形 计: 值 为 数. 算 加 步 为 数: 其 值 取 其 值+步. 得 其 值. 法 象 对象 取 新 计 值:2. 回调 取 算 对象 其 加. 对象 取 空. 显 (回调 3). 显 (回调 4).", '5\n9\n'),
    ('nested_self_capture', "形 计: 值 为 数. 算 制 步 为 数: 算 加: 其 值 取 其 值+步. 得 其 值. 法 得 算 加. 法 象 对象 取 新 计 值:2. 回调 取 对象 其 制 3. 对象 取 空. 显 回调(). 显 回调().", '5\n8\n'),
    ('inherited_bound_method', "形 基: 值 为 数. 算 看: 得 其 值. 法 象 形 子 如 基: 算 看: 得 其 值+1. 法 象 对象 取 新 子 值:7. 回调 取 算 对象 其 看. 显 回调().", '8\n'),
    ('rescue_escape', "列 取 []. 试 卒 '因'. 救 原因 算 看: 原因 取 原因+'!'. 得 原因. 法 列 其 增 算 看. 终. 显 列[0](). 显 列[0]().", '因!\n因!!\n'),
    ('rescue_shadows_capture', "算 制: 值 取 1. 列 取 []. 试 卒 '因'. 救 原因 值 取 10. 算 看: 值 取 值+1. 得 值. 法 列 其 增 算 看. 终. 算 外看: 得 值. 法 得 [列[0], 算 外看]. 法 组 取 制. 显 组[0](). 显 组[1]().", '11\n1\n'),
    ('panic_escape_keeps_capture', "列 取 []. 作 制 存 为 阵: 值 取 40. 算 加: 值 取 值+1. 得 值. 法 存 其 增 算 加. 卒 '跳出'. 为 试 制 列. 救 原因 显 原因. 终. 显 列[0](). 显 列[0]().", '跳出\n41\n42\n'),
    ('callable_argument_order', "算 报 值 为 数: 显 值. 得 值. 法 算 合 左 为 数 右 为 数: 得 左*10+右. 法 回调 取 算 合. 显 (回调 右:(报 2) 左:(报 1)).", '2\n1\n12\n'),
]

CASES.extend([
    ('pair_callable_projection', "算 回: 得 7. 法 对值 取 (算 回) 对 空. 显 (对值 其 囫)().", '7\n'),
    ('field_callee_before_arguments', "形 盒: 回调 为 算. 象 算 甲 值 为 数: 得 100+值. 法 算 乙 值 为 数: 得 200+值. 法 对象 取 新 盒 回调:(算 甲). 算 改: 对象 其 回调 取 算 乙. 得 1. 法 显 (对象 其 回调 改). 显 (对象 其 回调 2).", '101\n202\n'),
    ('callee_before_arguments', "算 外: 算 甲 值 为 数: 得 100+值. 法 算 乙 值 为 数: 得 200+值. 法 回调 取 算 甲. 算 改: 回调 取 算 乙. 得 1. 法 显 (回调 改). 显 (回调 2). 得 0. 法 外.", '101\n202\n'),
    ('index_callee_before_arguments', "算 甲 值 为 数: 得 100+值. 法 算 乙 值 为 数: 得 200+值. 法 列 取 [算 甲]. 算 改: 列[0] 取 算 乙. 得 1. 法 显 (列[0] 改). 显 (列[0] 2).", '101\n202\n'),
    ('captured_local_value_preserves_declared_type', "形 物: 值 为 数. 象 类型 取 0. 算 外: 类型 取 1. 算 看 值 为 物: 得 (值 其 值)+类型-1. 法 得 算 看. 法 回调 取 外. 显 (回调 (新 物 值:7)).", '7\n'),
    ('argument_panic_stops_later_evaluation', "算 合 左 为 句 右 为 句: 得 左+右. 法 算 坏: 卒 '停'. 法 算 后: 显 '不应'. 得 ''. 法 回调 取 算 合. 试 显 (回调 坏 后). 救 原因 显 原因. 终.", '停\n'),
])

ERRORS = [
    "算 加 值 为 数: 得 值. 法 回调 取 作 加.",
    "作 报: 显 1. 为 回调 取 算 报.",
    "值 取 3. 回调 取 算 值.",
    "值 取 3. 值().",
    "回调 取 算 读.",
    "回调 取 算 读取 其 读.",
    "列 取 []. 回调 取 作 列 其 增.",
    "值 取 3. 值 2.",
    "算 加 值 为 数: 得 值. 法 回调 取 算 加. 回调().",
    "算 加 值 为 数: 得 值. 法 回调 取 算 加. 回调 1 2.",
    "算 加 值 为 数: 得 值. 法 回调 取 算 加. 回调 错名:1.",
    "算 加 值 为 数: 得 值. 法 回调 取 算 加. 回调 '错'.",
    "算 用 回调 为 算: 得 回调(). 法 作 报: 显 1. 为 用 (作 报).",
    "作 用 回调 为 作: 回调(). 为 算 回: 得 1. 法 用 (算 回).",
    "形 盒: 回调 为 算. 象 作 报: 显 1. 为 盒值 取 新 盒 回调:(作 报).",
    "算 用 列 为 算 阵: 得 1. 法 作 报: 显 1. 为 用 [作 报].",
    "算 制: 算 内: 得 不存在. 法 得 算 内. 法 回调 取 制. 回调().",
]

STRESS = '''
算 制 起 为 数:
    环列 取 [].
    算 加: 起 取 起+1. 得 起. 法
    环列 其 增 算 加.
    环列 其 增 环列.
    得 算 加.
法
作 中断 存 为 阵:
    临时 取 制 7.
    存 其 增 临时.
    卒 '逃出'.
为
回调 取 制 0.
循 3000 次
    回调 取 制 10.
    列 取 [].
    试 中断 列. 救 原因
        若 列[0]() != 8 则 卒 '捕获损坏'. 然
    终.
    列 取 空.
环
显 回调().
回调 取 空.
'''


def interpreted(source, source_path=None, modules=None):
    output = io.StringIO()
    interpreter = Interpreter(io.StringIO(), output)
    interpreter.execute(parse(source), source_path=source_path, modules=modules)
    return output.getvalue()


def native(source, directory, stem='case', source_path=None, modules=None,
           extra_flags=(), inspect_heap=False, remove_sources=(), input_data=''):
    program = modules[str(Path(source_path).resolve())] if modules is not None else parse(source)
    generated = Compiler(program, str(source_path or '<闭包测试>'), modules=modules).compile()
    if inspect_heap:
        generated = generated.replace('ru_shutdown(); return status;',
            'ru_gc(); fprintf(stderr, "BEFORE_SHUTDOWN live=%zu freed=%zu\\n", ru_live, ru_freed); ru_shutdown(); return status;')
    path, binary = Path(directory).resolve()/(stem+'.c'), Path(directory).resolve()/stem
    path.write_text(generated, encoding='utf-8')
    built = subprocess.run([CC, '-std=c99', '-O1', '-g', '-Wall', '-Wextra',
        '-Werror', '-Wno-unused-function', '-pedantic', *extra_flags,
        str(path), *([] if sys.platform == 'win32' else ['-lm']), '-o', str(binary)], capture_output=True, text=True)
    if built.returncode:
        raise AssertionError(built.stderr)
    for source_file in remove_sources:
        Path(source_file).unlink()
    return subprocess.run([str(binary)], input=input_data, capture_output=True, text=True, timeout=45,
        env={**os.environ, 'RU_GC_THRESHOLD':'1', 'RU_GC_STATS':'1'})


class ClosureTests(unittest.TestCase):
    def test_interpreter_cases(self):
        for name, source, expected in CASES:
            with self.subTest(name=name):
                self.assertEqual(interpreted(source), expected)

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_native_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, source, expected in CASES:
                with self.subTest(name=name):
                    result = native(source, directory, name)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, expected)
                    self.assertIn('RU_GC live=0 ', result.stderr)

    def test_interpreter_errors(self):
        for source in ERRORS:
            with self.subTest(source=source), self.assertRaises(RuError):
                interpreted(source)

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_native_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            for index, source in enumerate(ERRORS):
                with self.subTest(index=index):
                    try:
                        result = native(source, directory, 'error'+str(index))
                    except RuError:
                        continue
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('运行错误', result.stderr)
                    self.assertIn('RU_GC live=0 ', result.stderr)

    def test_declaration_structure(self):
        invalid = [
            '算 外: 算 内: 得 1. 法 算 内: 得 2. 法 得 0. 法',
            '算 外: 若 1 则 算 内: 得 1. 法 然 得 0. 法',
            '算 外: 循 1 次 算 内: 得 1. 法 环 得 0. 法',
            '算 外: 试 算 内: 得 1. 法 救 原因 终. 得 0. 法',
            '算 外: 作 内: 得 1. 为 得 0. 法',
            '循 1 次 算 外: 破. 得 0. 法 环',
            '算 外: 形 内: 象 得 0. 法',
        ]
        for source in invalid:
            with self.subTest(source=source), self.assertRaises(RuError):
                validate(parse(source))

    def test_undefined_calls_remain_lexically_checked(self):
        for source in (
            '算 无关: 假 取 1. 得 0. 法 算 坏: 得 假 1. 法',
            '算 外: 试 卒 "因". 救 原因 内取 取 1. 终. 得 内取 2. 法',
        ):
            with self.subTest(source=source), self.assertRaises(RuError):
                Compiler(parse(source)).compile()

    def test_repl_closure_persists_across_submissions(self):
        source = (COUNTER + '\n甲 取 制数 4.\n甲 3.\n甲 2.\n'
                  '甲.\n:reset\n甲 1.\n:退\n')
        result = subprocess.run([sys.executable, '-m', 'rulang', 'repl'],
            input=source, text=True, capture_output=True, cwd=ROOT, timeout=20)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '7\n9\n<算 加>\n')
        self.assertIn('甲', result.stderr)

    def test_builtin_zero_call_and_repl_procedure_echo(self):
        output = io.StringIO()
        interpreter = Interpreter(io.StringIO('甲\n乙\n'), output)
        interpreter.execute(parse("作 报: 为 报. 读 提示: ''. 读()."), echo=True)
        self.assertEqual(output.getvalue(), '甲\n乙\n')
        if CC:
            with tempfile.TemporaryDirectory() as directory:
                result = native('显 读().', directory, 'zero-read', input_data='甲\n')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '甲\n')

    def test_module_factory_and_reference_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            child = Path(directory).resolve()/'factory.ru'
            child.write_text("基 取 100. 算 制 起 为 数: 值 取 起. 算 加 步 为 数: 值 取 值+步. 得 值+基. 法 得 算 加. 法", encoding='utf-8')
            root = Path(directory).resolve()/'main.ru'
            source = "基 取 999. 模块 取 外言 'factory.ru'. 工厂 取 算 模块 其 制. 回调 取 工厂 2. 另一引用 取 算 模块 其 制. 显 工厂 == 另一引用. 显 (回调 3). 显 (回调 4)."
            root.write_text(source, encoding='utf-8')
            modules = load_module_graph(root)
            self.assertEqual(interpreted(source, root, modules), '真\n105\n109\n')
            if CC:
                result = native(source, directory, 'modules', root, modules, remove_sources=(root, child))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '真\n105\n109\n')

    def test_closure_escapes_failed_module_initializer(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory).resolve()
            (folder/'shared.ru').write_text('存 取 [].', encoding='utf-8')
            (folder/'broken.ru').write_text(
                "桥 取 外言 'shared.ru'. 基 取 7. "
                "算 制 起 为 数: 算 看: 得 起+基. 法 得 算 看. 法 "
                "桥 其 存 其 增 (制 5). 卒 '失败'.", encoding='utf-8')
            root = folder/'main.ru'
            source = ("共享 取 外言 'shared.ru'. 循 3 次 "
                "试 坏模块 取 外言 'broken.ru'. 救 原因 显 原因. 终. 环 "
                "显 共享 其 存 其 量. 回调 取 共享 其 存[0]. 显 回调().")
            root.write_text(source, encoding='utf-8')
            modules = load_module_graph(root)
            expected = '失败\n失败\n失败\n1\n12\n'
            self.assertEqual(interpreted(source, root, modules), expected)
            if CC:
                result = native(source, directory, 'failed-module', root, modules)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)
                self.assertIn('RU_GC live=0 ', result.stderr)

    def test_interpreter_cycles_reclaimed(self):
        output = io.StringIO()
        interpreter = Interpreter(io.StringIO(), output)
        interpreter.execute(parse(COUNTER + '回调 取 制数 3.'))
        callback = interpreter.global_scope.values['回调']
        reference = weakref.ref(callback)
        interpreter.execute(parse('回调 取 空.'))
        del callback
        gc.collect()
        self.assertIsNone(reference())

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_gc_reclaims_inactive_cycles_before_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            result = native(STRESS, directory, 'stress', inspect_heap=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '11\n')
            match = re.search(r'BEFORE_SHUTDOWN live=(\d+) freed=(\d+)', result.stderr)
            self.assertIsNotNone(match, result.stderr)
            self.assertLess(int(match[1]), 100, result.stderr)
            self.assertGreater(int(match[2]), 20000, result.stderr)
            self.assertIn('RU_GC live=0 ', result.stderr)


if __name__ == '__main__':
    unittest.main()
