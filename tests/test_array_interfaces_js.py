"""Array algorithms in Node (full/pruned) and browser ESM synthetic hosts."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from rulang.browser_compiler import compile_browser
from rulang.frontend import parse
from rulang.js_compiler import JSCompiler
from rulang.modules import load_module_graph

NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'Node required')
class ArrayInterfacesJavaScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_source(self, source, mode):
        if mode == 'browser':
            javascript = compile_browser(source)
            (self.root/'program.mjs').write_text(javascript, encoding='utf-8')
            runner = self.root/'run.mjs'
            runner.write_text("import create from './program.mjs';const events=[];"
                              "try{create({emit:e=>events.push(e)});console.log(JSON.stringify({events}));}"
                              "catch(error){console.log(JSON.stringify({events,error:error.diagnostic}));}", encoding='utf-8')
            proc = subprocess.run([NODE, str(runner)], capture_output=True, text=True, timeout=15)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(proc.stdout)
            return ''.join(e.get('text', '') for e in result['events']), result.get('error')
        graph = load_module_graph(str(self.root/'source.ru'), parse(source))
        javascript = JSCompiler(graph[graph.root], graph.root, modules=graph,
                                full_runtime=mode == 'full').compile()
        runner = self.root/'run.cjs'
        runner.write_text(javascript, encoding='utf-8')
        proc = subprocess.run([NODE, str(runner)], capture_output=True, text=True, timeout=15)
        return proc.stdout, proc.stderr if proc.returncode else None

    def success(self, source, expected):
        for mode in ('pruned', 'full', 'browser'):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_source(source, mode), (expected, None))

    def failure(self, source, message):
        for mode in ('pruned', 'full', 'browser'):
            with self.subTest(mode=mode):
                output, error = self.run_source(source, mode)
                self.assertIsNotNone(error)
                self.assertIn(message, error['message'] if isinstance(error, dict) else error)

    def test_default_numbers_unicode_and_fresh_arrays(self):
        self.success("""
列 取 [3,1,2,1]. 新列 取 列 其 排序. 显 新列. 显 列.
显 ['😀','\ue000','a','𐀀'] 其 排序.
零 取 []. 零另 取 零 其 排序. 零另 其 增 4. 显 零.
单 取 [5]. 单另 取 单 其 排序. 单另 其 增 6. 显 单.
""", '[1, 1, 2, 3]\n[3, 1, 2, 1]\n[a, \ue000, 𐀀, 😀]\n[]\n[5]\n')

    def test_explicit_stable_sort_and_snapshot(self):
        self.success("""
列 取 [[1,10],[0,20],[1,30],[0,40]].
算 先 左 右: 列 其 增 [9,99]. 得 左[0] < 右[0]. 法
新列 取 列 其 排序 先于:算 先. 显 新列.
新列[0][1] 取 70. 显 列[1].
""", '[[0, 20], [0, 40], [1, 10], [1, 30]]\n[0, 70]\n')

    def test_map_snapshot_sharing_null_and_nested(self):
        self.success("""
列 取 [[1],[2]].
算 转 元: 列 其 增 [9]. 得 元. 法
新列 取 列 其 另成 算法:算 转. 显 新列. 新列[0][0] 取 8. 显 列[0].
显 [1,2] 其 另成 算 元: 得 空. 法.
显 [1,2] 其 另成 算 元: 得 [元]. 法.
""", '[[1], [2]]\n[8]\n[空, 空]\n[[1], [2]]\n')

    def test_shape_protocol_and_explicit_override(self):
        self.success("""
形 项:
值 为 数.
算 先于 彼: 得 其 值 < 彼 其 值. 法
象
甲 取 新 项 值:3. 乙 取 新 项 值:1.
列 取 [甲,乙] 其 排序. 显 列[0] 其 值.
显 [真,空,1] 其 排序 算 左 右: 得 假. 法.
""", '1\n[真, 空, 1]\n')

    def test_invalid_default_and_protocol(self):
        for value in ('[真]', '[空]', '[[1]]', '[1,"a"]'):
            with self.subTest(value=value):
                self.failure('显 '+value+' 其 排序.', '默认排序须为')
        self.failure('形 项: 值 为 数. 象 显 [新 项 值:1] 其 排序.', '形的「先于」须为接受 1 个参数的算')

    def test_callback_preflight_even_empty(self):
        for source, message in (
            ('显 [] 其 排序 空.', '「先于」须为接受 2 个参数的算'),
            ('显 [] 其 排序 算 元: 得 真. 法.', '「先于」须为接受 2 个参数的算'),
            ('显 [] 其 另成 作 元: 完. 为.', '「算法」须为接受 1 个参数的算'),
            ('显 [] 其 另成 算 左 右: 得 空. 法.', '「算法」须为接受 1 个参数的算'),
            ('显 [2,1] 其 排序 算 左 右: 得 0. 法.', '「先于」须返回事实'),
        ):
            with self.subTest(source=source):
                self.failure(source, message)

    def test_named_parameter_validation(self):
        self.failure('显 [] 其 另成.', '缺少「算法」')
        self.failure('显 [] 其 排序 比较:空.', '未知「比较」')

    def test_browser_callback_diagnostics_and_budget(self):
        _, error = self.run_source('显 [1] 其 另成 算 元:\n 得 1 / 0.\n法.', 'browser')
        self.assertEqual(error['line'], 2)
        self.assertEqual(error['source_name'], '<如书 JS>')
        _, error = self.run_source('显 [1] 其 另成 算 元: 循 环 得 元. 法.', 'browser')
        self.assertIn('500000 步预算', error['message'])
        # Building the input stays below the limit; native comparisons also
        # consume the browser budget, even without user callbacks.
        _, error = self.run_source('列 取 []. 循 70000 次 列 其 增 1. 环 显 列 其 排序.', 'browser')
        self.assertIn('500000 步预算', error['message'])

    def test_array_and_map_iteration_snapshots(self):
        self.success("""
列 取 [[1],[2],[3]].
显 列 其 逐位 回调:(作 位 元: 显 位. 显 元. 列 其 弹. 元[0] := 元[0]+10. 为).
显 列.
典列 取 {'甲':[1],'乙':[2]}.
显 典列 其 逐目 (算 目 相: 显 目. 显 相. 典列 其 除 目. 得 [9]. 法).
显 典列 其 量.
""", '0\n[1]\n1\n[2]\n2\n[3]\n空\n[]\n甲\n[1]\n乙\n[2]\n空\n0\n')

    def test_iteration_callback_errors_and_map_migration(self):
        self.failure('显 [] 其 逐位 (算 元: 得 元. 法).', '阵的逐位回调须为接受两个参数的算或作')
        self.failure("显 {} 其 逐目 (作 元: 完. 为).", '典的逐目回调须为接受两个参数的算或作')
        self.failure("典列 取 {}. 典列 其 列 (作 目 相: 完. 为).", '典的「列」已改名为「逐目」')

    def test_unused_pruning_and_browser_metering(self):
        code = JSCompiler(parse('显 1.'), '<test>').compile()
        self.assertNotIn('function arrayAlgorithm', code)
        self.assertLess(len(code.encode('utf-8')), 32768)
        for member in ('排序', '另成 算 元: 得 元. 法'):
            code = JSCompiler(parse('显 [] 其 '+member+'.'), '<test>').compile()
            self.assertIn('function arrayAlgorithm', code)
        self.assertIn('browserTick(m,loc);', compile_browser('显 [2,1] 其 排序.'))


if __name__ == '__main__':
    unittest.main()
