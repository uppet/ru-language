"""Map read shorthand parity; assignment and slicing remain sequence-only."""
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from rulang.cli import build
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter

NODE = shutil.which('node') or shutil.which('nodejs')
CC = bool(os.environ.get('CC')) or any(shutil.which(c) for c in ('cc', 'gcc', 'clang'))


class MapIndexContract:
    backend = 'python'
    full_runtime = False

    def run_source(self, source):
        out = io.StringIO()
        try:
            if self.backend == 'python':
                Interpreter(io.StringIO(), out).execute(parse(source))
                return 0, out.getvalue(), ''
            with tempfile.TemporaryDirectory() as folder:
                binary, _ = build(parse(source), Path(folder)/'case.ru',
                                  Path(folder)/'case', target=self.backend,
                                  full_runtime=self.full_runtime)
                command = [NODE, str(binary)] if self.backend == 'js' else [str(binary)]
                result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=20)
                return result.returncode, result.stdout, result.stderr
        except RuError as error:
            return 1, out.getvalue(), str(error)

    def output(self, source, expected):
        self.assertEqual(self.run_source(source), (0, expected, ''))

    def error(self, source, pattern):
        status, out, error = self.run_source(source)
        self.assertEqual(status, 1, (out, error))
        self.assertRegex(error, pattern)
        return out

    def test_user_example_missing_and_false_values(self):
        self.output("戏 取 典： '心' 对 0. '意' 对 1. 成. 显 戏['心']. 显 戏['意']. 显 戏['缺']. "
                    "物 取 典: '假' 对 假. '空' 对 空. 成. 显 物['假']. 显 物['空']. 显 (典: 成)['缺'].",
                    '0\n1\n空\n假\n空\n空\n')

    def test_fact_number_and_fraction_keys(self):
        self.output("物 取 典: 真 对 '真键'. 1 对 '数键'. 假 对 '假键'. 0 对 '零键'. -2.5 对 '负键'. 成. "
                    "显 物[真]. 显 物[1]. 显 物[假]. 显 物[-0]. 显 物[-2.5]. 显 物[2.5].",
                    '真键\n数键\n假键\n零键\n负键\n空\n')

    def test_nested_maps_arrays_and_shared_value(self):
        self.output("物 取 典: '列' 对 [7]. '内' 对 典: '值' 对 8. 成. 成. "
                    "阵值 取 [物]. 显 物['列'][0]. 显 阵值[0]['内']['值']. "
                    "物['列'][0] 取 9. 显 阵值[0]['列'][0].",
                    '7\n8\n9\n')

    def test_sequence_behavior_without_map_runtime(self):
        self.output("列值 取 [1,2]. 列值[0] 取 3. 显 列值[0]. 显 列值[0:2]. 显 '中文😀'[2]. 显 '中文😀'[1:3].",
                    '3\n[3, 2]\n😀\n文😀\n')
        for source in ("显 [1][真].", "显 '文'['0'].", '显 [1][1].', '显 3[0].'):
            with self.subTest(source=source):
                self.error(source, '索引|阵或句')

    def test_read_evaluates_receiver_and_key_once_in_order(self):
        self.output("算 表: 显 '表'. 得 典: '心' 对 7. 成. 法 算 键: 显 '键'. 得 '心'. 法 显 (表)[键].",
                    '表\n键\n7\n')

    def test_invalid_key_uses_map_errors_even_when_empty(self):
        for key in ('空', '[]', '典: 成', '1 对 2', '算: 得 1. 法'):
            with self.subTest(key=key):
                self.error('物 取 典: 成. 显 物[('+key+')].', '典.*键')

    def test_assignment_and_slicing_rejected_before_rhs(self):
        out = self.error("算 值: 显 '不可求值'. 得 9. 法 物 取 典: '心' 对 0. 成. 物['心'] 取 值.", '赋值|修改阵')
        self.assertEqual(out, '')
        for operation in ('显 物[:].', '显 物[0:1].', '显 物 其 位 0.', '显 物 其 段 0 1.'):
            with self.subTest(operation=operation):
                self.error('物 取 典: 成. '+operation, '阵或句|未知.*成员|没有成员')

    def test_custom_collision_keys_use_same_lookup(self):
        self.output("形 键形: 值 为 数. 算 同 另一: 得 其 值 == 另一 其 值. 法 算 印: 得 0. 法 象 "
                    "物 取 典: (新 键形 值:1) 对 7. (新 键形 值:2) 对 8. 成. "
                    "显 物[新 键形 值:1]. 显 物[新 键形 值:2]. 显 物[新 键形 值:3]. "
                    "显 物[新 键形 值:1] == (物 其 查 (新 键形 值:1)).", '7\n8\n空\n真\n')

    def test_custom_key_protocol_errors(self):
        for methods, pattern in (('', '同'), ('算 同 另一: 得 真. 法', '印'),
                                 ('算 同 另一: 得 真. 法 算 印: 得 真. 法', '安全整数'),
                                 ('算 同 另一: 得 1. 法 算 印: 得 0. 法', '事实')):
            with self.subTest(methods=methods):
                # Last case needs an existing key to invoke 同.
                literal = '(新 键形) 对 1.' if pattern == '事实' else ''
                self.error('形 键形: '+methods+' 象 物 取 典: '+literal+' 成. 显 物[新 键形].', pattern)

    def test_hash_and_equality_panic_propagate(self):
        self.output("形 键形: 算 同 另一: 卒 '同比较'. 法 算 印: 得 0. 法 象 "
                    "物 取 典: (新 键形) 对 1. 成. 试 显 物[新 键形]. 救 原因 显 原因. 终. "
                    "形 坏键: 算 同 另一: 得 真. 法 算 印: 卒 '印计算'. 法 象 "
                    "试 显 物[新 坏键]. 救 原因 显 原因. 终. 显 '继续'.", '同比较\n印计算\n继续\n')

    def test_mutation_guards_hash_and_equality(self):
        for method in ('印', '同'):
            with self.subTest(method=method), patch.dict(os.environ, {'RU_GC_THRESHOLD': '1'}):
                same = "物 其 增 '新' 2. 得 真." if method == '同' else '得 真.'
                hash_body = "物 其 增 '新' 2. 得 0." if method == '印' else '得 0.'
                literal = '(新 键形) 对 1.' if method == '同' else ''
                self.error('物 取 典: 成. 形 键形: 算 同 另一: '+same+' 法 算 印: '+hash_body+
                           ' 法 象 '+('物 其 增 (新 键形) 1. ' if literal else '')+'显 物[新 键形].', '修改')

    def test_gc_roots_through_key_callbacks_and_temporary_receiver(self):
        source = """形 键形:
            值 为 数.
            算 同 另一: 循 30 次 废 取 [1,2,3]. 环 得 其 值 == 另一 其 值. 法
            算 印: 循 30 次 废 取 典: '废' 对 [1,2]. 成. 环 得 0. 法
        象
        算 制: 表 取 典: (新 键形 值:1) 对 [7]. 成. 得 表. 法
        列值 取 (制)[新 键形 值:1].
        循 30 次 废 取 制. 环
        显 列值[0]. 显 (制)[新 键形 值:1][0]."""
        with patch.dict(os.environ, {'RU_GC_THRESHOLD': '1'}):
            self.output(source, '7\n7\n')


class InterpreterMapIndexTests(MapIndexContract, unittest.TestCase):
    pass


@unittest.skipUnless(CC, 'C compiler required')
class NativeMapIndexTests(MapIndexContract, unittest.TestCase):
    backend = 'c'


@unittest.skipUnless(CC, 'C compiler required')
class FullNativeMapIndexTests(NativeMapIndexTests):
    full_runtime = True


@unittest.skipUnless(NODE, 'Node.js required')
class JavaScriptMapIndexTests(MapIndexContract, unittest.TestCase):
    backend = 'js'


@unittest.skipUnless(NODE, 'Node.js required')
class FullJavaScriptMapIndexTests(JavaScriptMapIndexTests):
    full_runtime = True


class MapIndexPruningTests(unittest.TestCase):
    def test_optional_javascript_index_dispatch(self):
        from rulang.js_compiler import JSCompiler
        branch = "if (receiver instanceof RuMap) return mapMember(m,receiver,'查',[[null,i]],loc);"
        sequence_source = "显 [7][0]."
        map_source = "显 (典: '键' 对 7. 成)['键']."
        self.assertNotIn(branch, JSCompiler(parse(sequence_source)).compile())
        self.assertIn(branch, JSCompiler(parse(map_source)).compile())
        self.assertIn(branch, JSCompiler(parse(sequence_source), full_runtime=True).compile())


class RushuMapIndexTests(unittest.TestCase):
    def test_map_read_across_notebook_cells(self):
        from rushu.kernel import Session
        from test_rushu_kernel import wait_for, output
        session = Session()
        self.addCleanup(session.close)
        session.execute("戏 取 典： '心' 对 0. '意' 对 1. 成.", 'definition')
        first = wait_for(session)
        self.assertEqual(first['events'][-1]['status'], 'ok')
        session.execute("显 戏['心']. 显 戏['缺'].", 'lookup')
        second = wait_for(session, after=first['cursor'])
        self.assertEqual(second['events'][-1]['status'], 'ok')
        self.assertEqual(output(second), '0\n空\n')


if __name__ == '__main__':
    unittest.main()
