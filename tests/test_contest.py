"""Bundled contest library: real input, two backends, and standalone judge C."""
import io
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.compiler import Compiler
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter
from rulang.modules import load_module_graph, resolve_import

CC = (shutil.which(os.environ['CC']) if os.environ.get('CC') else
      next((shutil.which(c) for c in ('gcc', 'clang', 'cc') if shutil.which(c)), None))
PRELUDE = "竞 取 外言 '如:竞赛'.\n"


def graph_for(source, path):
    return load_module_graph(path, parse(source))


def interpreted(source, data='', path='/tmp/contest-test.ru'):
    graph = graph_for(source, path)
    output = io.StringIO()
    runtime = Interpreter(io.StringIO(data), output)
    runtime.execute(graph[graph.root], source_path=graph.root, modules=graph)
    return output.getvalue()


def compile_native(source, directory, name='case', extra_flags=(), source_path=None):
    path = source_path or str(Path(directory).resolve()/(name+'.ru'))
    graph = graph_for(source, path)
    cfile, binary = Path(directory).resolve()/(name+'.c'), Path(directory).resolve()/(name + ('.exe' if os.name == 'nt' else ''))
    cfile.write_text(Compiler(graph[graph.root], graph.root, modules=graph).compile(), encoding='utf-8')
    result = subprocess.run([CC, '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-function', '-pedantic', *extra_flags, str(cfile), '-o', str(binary)],
        capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return binary, cfile


def native_run(binary, data='', force_gc=True, timeout=30):
    env = {**os.environ, 'RU_GC_STATS':'1'}
    if force_gc:
        env['RU_GC_THRESHOLD'] = '1'
    result = subprocess.run([str(binary)],
                            input=data.encode('utf-8') if isinstance(data, str) else data,
                            capture_output=True, timeout=timeout, env=env)
    if isinstance(data, str):
        result.stdout = result.stdout.decode('utf-8')
        result.stderr = result.stderr.decode('utf-8')
    return result


CASES = [
    ('scanner', PRELUDE + "入 取 竞  其  扫句 '  -12 +3.5e1\\r\\n\\n末行'. 显 入  其  数. 显 入  其  数. 显 入  其  行. 显 入  其  行. 显 入  其  行. 显 入  其  行 == 空. 显 入  其  词 == 空.", '-12\n35\n\n\n末行\n真\n真\n'),
    ('mixed_delimiter', PRELUDE + "入 取 竞  其  扫句 '甲 乙\\r\\n尾\\r'. 显 入  其  词. 显 入  其  行. 显 入  其  行. 显 入  其  行 == 空.", '甲\n 乙\n尾\r\n真\n'),
    ('split_join', PRELUDE + "显 (竞  其  拆词 '  一\\t二\\n三 四  '). 显 (竞  其  拆行 '\\r\\n一\\n\\n末\\r'). 显 (竞  其  拆行 ''). 显 (竞  其  拆行 '一\\n'). 显 (竞  其  字列 '如😀é'). 显 (竞  其  合句 ['甲','乙',''] '/').", '[一, 二, 三 四]\n[, 一, , 末\r]\n[]\n[一]\n[如, 😀, e, ́]\n甲/乙/\n'),
    ('numbers', PRELUDE + "显 (竞  其  小 4 (-2)). 显 (竞  其  大 4 (-2)). 显 (竞  其  绝对 (-4)). 显 (竞  其  取整 (-3.8)). 显 (竞  其  整除 (-7) 3). 显 (竞  其  整除 7 (-3)). 显 (竞  其  取整 1e20). 显 (竞  其  取整 (-0.5)). 显 (竞  其  取整 (-0)).", '-2\n4\n4\n-3\n-2\n-2\n1e+20\n-0\n-0\n'),
    ('writer', PRELUDE + "出 取 竞  其  蓄出. 出  其  写 '甲'. 出  其  行 12. 出  其  行 ''. 出  其  行 '😀'. 出  其  清. 出  其  清.", '甲12\n\n😀\n'),
    ('sort_closure', PRELUDE + "算 制序 方向 为 数: 算 比 左 为 数 右 为 数: 得 (左-右)*方向. 法 得 算 比. 法 原 取 [3,1,2,1]. 显 (竞  其  排序 原 (制序 (-1))). 显 原.", '[3, 2, 1, 1]\n[3, 1, 2, 1]\n'),
    ('stable_records', PRELUDE + "形 项: 键 为 数. 名 为 句. 象 算 比 左 为 项 右 为 项: 得 左 其 键-右 其 键. 法 原 取 [(新 项 键:2 名:'甲'),(新 项 键:1 名:'乙'),(新 项 键:2 名:'丙')]. 排 取 竞 其 排序 原 (算 比). 显 排[0] 其 名. 显 排[1] 其 名. 显 排[2] 其 名. 显 原[0] 其 名.", '乙\n甲\n丙\n甲\n'),
    ('sort_panic', PRELUDE + "原 取 [3,2,1]. 算 比 左 为 数 右 为 数: 卒 '停'. 法 试 竞 其 排序 原 (算 比). 救 原因 显 原因. 终. 显 原.", '停\n[3, 2, 1]\n'),
    ('sort_snapshot', PRELUDE + "原 取 [3,2,1]. 算 比 左 为 数 右 为 数: 原[0] 取 99. 得 左-右. 法 显 (竞 其 排序 原 (算 比)). 显 原.", '[1, 2, 3]\n[99, 2, 1]\n'),
    ('module_ref', PRELUDE + "分 取 算 竞 其 拆词. 显 (分 'a b'). 尽 取 外言 '如:竞赛'. 显 (合句 ['a','b'] ':').", '[a, b]\na:b\n'),
]

ERRORS = [
    "入 取 竞 其 扫句 '1abc'. 显 入 其 数.",
    "入 取 竞 其 扫句 '1e999'. 显 入 其 数.",
    "入 取 竞 其 扫句 'nan'. 显 入 其 数.",
    "入 取 竞 其 扫句 '１２'. 显 入 其 数.",
    "入 取 竞 其 扫句 ''. 入 其 词 1.",
    "竞 其 扫句 1.",
    "竞 其 合句 ['a',1] ','.",
    "出 取 竞 其 蓄出. 出 其 写 1.",
    "出 取 竞 其 蓄出. 出 其 行 [].",
    "算 比 左 为 数 右 为 数: 得 '错'. 法 竞 其 排序 [2,1] (算 比).",
    "作 比 左 为 数 右 为 数: 显 左. 为 竞 其 排序 [2,1] (作 比).",
    "竞 其 整除 1 0.",
    "__竞赛 取 1.",
]


class ContestLibraryTests(unittest.TestCase):
    def test_interpreter_cases(self):
        for name, source, expected in CASES:
            with self.subTest(name=name):
                self.assertEqual(interpreted(source), expected)

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_native_cases_without_libm(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, source, expected in CASES:
                with self.subTest(name=name):
                    binary, _ = compile_native(source, directory, name)
                    result = native_run(binary)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    # Binary capture preserves literal CR as well as newline bytes.
                    self.assertEqual(result.stdout, expected)
                    self.assertIn('RU_GC live=0 ', result.stderr)

    def test_interpreter_errors(self):
        for source in ERRORS:
            with self.subTest(source=source), self.assertRaises(RuError):
                interpreted(PRELUDE+source)

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_native_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            for index, source in enumerate(ERRORS):
                with self.subTest(index=index):
                    try:
                        binary, _ = compile_native(PRELUDE+source, directory, 'bad'+str(index))
                    except RuError:
                        continue
                    result = native_run(binary)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('错误', result.stderr)
                    self.assertIn('RU_GC live=0 ', result.stderr)

    def test_reserved_import_alias_and_unknown_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory).resolve()/'如:竞赛'
            fake.write_text("卒 'local collision'.", encoding='utf-8')
            main = str(Path(directory).resolve()/'main.ru')
            self.assertNotEqual(resolve_import('如:竞赛', main), str(fake))
            self.assertEqual(interpreted(PRELUDE+"显 (竞 其 小 2 3).", path=main), '2\n')
            with self.assertRaisesRegex(RuError, '未知的标准外言'):
                graph_for("外言 '如:不存在'.", main)
            # The explicit relative path is still a local file, rather than an alias.
            self.assertEqual(resolve_import('./如:竞赛', main), str(fake))

    def test_ascii_whitespace_and_eof(self):
        source = PRELUDE+"入 取 竞 其 读入. 循 值 取 入 其 词. 若 值 == 空 则 破. 然 显 值. 环"
        self.assertEqual(interpreted(source, ' \t\r\n\v\f甲\u00a0乙 z'), '甲\u00a0乙\nz\n')
        self.assertEqual(interpreted(source, ''), '')

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_invalid_input_and_large_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            source = PRELUDE+"入 取 竞 其 读入. 显 入 其 词."
            binary, _ = compile_native(source, directory)
            for data in (b'abc\xff\n', b'abc\x00z', b'\xf0\x80\x80\x80'):
                with self.subTest(data=data):
                    result = native_run(binary, data)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, b'')
                    self.assertIn('错误'.encode(), result.stderr)
            source = PRELUDE+"出 取 竞 其 蓄出. 循 22000 次 出 其 写 '如😀'. 环 出 其 行 7. 出 其 清."
            expected = '如😀'*22000+'7\n'
            self.assertEqual(interpreted(source), expected)
            binary, _ = compile_native(source, directory, 'writer')
            result = native_run(binary)
            self.assertEqual(result.stdout, expected)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('RU_GC live=0 ', result.stderr)

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_standalone_c11_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            binary, cfile = compile_native(PRELUDE+"入 取 竞 其 读入. 显 (入 其 数)+(入 其 数).", directory)
            copy = Path(directory).resolve()/'submission.c'
            copy.write_bytes(cfile.read_bytes())
            binary.unlink(); cfile.unlink()
            result = subprocess.run([CC, '-std=c11', '-O2', str(copy), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], input='20 22', capture_output=True, text=True,
                                    cwd='/', env={**os.environ, 'PATH':'/nonexistent'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '42\n')


    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_original_problems_randomized_differential(self):
        rng = random.Random(20260930)
        names = ['sum_eof', 'prefix_sum', 'line_words', 'stable_records']
        with tempfile.TemporaryDirectory() as directory:
            programs = {}
            for name in names:
                path = ROOT/'examples'/('contest_'+name+'.ru')
                source = path.read_text(encoding='utf-8')
                binary, _ = compile_native(source, directory, name, source_path=str(path))
                programs[name] = (source, binary)
            for turn in range(16):
                pairs = [(rng.randint(-1000000,1000000),rng.randint(-1000000,1000000)) for _ in range(turn)]
                pair_data = '\r\n'.join(f'{left} {right}' for left,right in pairs)
                pair_expected = ''.join(str(left+right)+'\n' for left,right in pairs)
                n, q = rng.randint(1,40), rng.randint(0,40)
                values = [rng.randint(-10000,10000) for _ in range(n)]
                ranges = [(rng.randint(1,n),rng.randint(1,n)) for _ in range(q)]
                ranges = [(min(a,b),max(a,b)) for a,b in ranges]
                prefix_data = f'{n} {q}\n'+' '.join(map(str,values))+'\n'+''.join(f'{a} {b}\n' for a,b in ranges)
                prefix_expected = ''.join(str(sum(values[a-1:b]))+'\n' for a,b in ranges)
                lines = ['', '甲  乙', '\t😀\t如', 'a b c', '   ', '终'][:rng.randint(0,6)]
                line_data = '\r\n'.join(lines)
                physical_lines = line_data.split('\n')
                if not line_data:
                    physical_lines = []
                elif line_data.endswith('\n'):
                    physical_lines.pop()
                import re
                line_expected = ''.join(str(len(re.findall(r'[^ \t\r\n\v\f]+', line)))+'\n' for line in physical_lines)
                direction = rng.choice((-1,1))
                records = [('名'+str(index)+'😀',rng.randint(-5,5)) for index in range(turn*2)]
                sort_data = f'{len(records)} {direction}\n'+''.join(f'{name} {score}\n' for name,score in records)
                sort_expected = ''.join(f'{name} {score}\n' for name,score in sorted(records,key=lambda item:item[1]*direction))
                for name,data,expected in [('sum_eof',pair_data,pair_expected),('prefix_sum',prefix_data,prefix_expected),
                                           ('line_words',line_data,line_expected),('stable_records',sort_data,sort_expected)]:
                    with self.subTest(problem=name,turn=turn):
                        source,binary = programs[name]
                        self.assertEqual(interpreted(source,data),expected)
                        result = native_run(binary,data)
                        self.assertEqual(result.returncode,0,result.stderr)
                        self.assertEqual(result.stdout,expected)
                        self.assertIn('RU_GC live=0 ',result.stderr)

    def test_reader_and_writer_host_failures(self):
        source = PRELUDE+"入 取 竞 其 读入."
        for data in (b'bad\xff', b'bad\0', b'\xc0\x80'):
            graph = graph_for(source,'/tmp/invalid-contest-input.ru')
            with self.subTest(data=data),self.assertRaises(RuError):
                Interpreter(io.BytesIO(data),io.StringIO()).execute(graph[graph.root],source_path=graph.root,modules=graph)
        class Broken(io.StringIO):
            def flush(self):
                raise OSError('deliberate failure')
        for command in ("出 其 清.", "出 其 写 'x'. 出 其 清."):
            source = PRELUDE+"出 取 竞 其 蓄出. "+command
            graph = graph_for(source,'/tmp/broken-contest-output.ru')
            with self.subTest(command=command),self.assertRaisesRegex(RuError,'输出失败'):
                Interpreter(io.StringIO(),Broken()).execute(graph[graph.root],source_path=graph.root,modules=graph)

    def test_writer_explicit_flush_and_private_exports(self):
        self.assertEqual(interpreted(PRELUDE+"出 取 竞 其 蓄出. 出 其 写 'held'."),'')
        graph = graph_for(PRELUDE,'/tmp/contest-exports.ru')
        runtime = Interpreter(io.StringIO(),io.StringIO())
        runtime.execute(graph[graph.root],source_path=graph.root,modules=graph)
        exports = runtime.global_scope.values['竞'].exports()
        self.assertNotIn('__竞赛',exports)
        self.assertEqual(set(exports),{'读入','扫句','拆词','拆行','字列','合句','排序','取整','小','大','绝对','整除','蓄出'})



    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_large_sort_default_gc_budget_scales_with_live_edges(self):
        source = PRELUDE+"""入 取 竞 其 读入. 列 取 [].
算 比 左 为 数 右 为 数: 得 左-右. 法
循 值 取 入 其 数. 若 值 == 空 则 破. 然 列 其 增 值. 环
序 取 竞 其 排序 列 (算 比). 显 序[0]. 显 序[4095].
"""
        data = ' '.join(map(str,range(4095,-1,-1)))
        import re
        with tempfile.TemporaryDirectory() as directory:
            binary,_ = compile_native(source,directory,'gc-budget')
            counts = []
            for threshold in (None,'256'):
                env = {**os.environ,'RU_GC_STATS':'1'}
                env.pop('RU_GC_THRESHOLD',None)
                if threshold is not None:
                    env['RU_GC_THRESHOLD'] = threshold
                result = subprocess.run([str(binary)],input=data,capture_output=True,text=True,env=env,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout,'0\n4095\n')
                self.assertIn('RU_GC live=0 ',result.stderr)
                counts.append(int(re.search(r'collections=(\d+)',result.stderr).group(1)))
            # Structural collector-work regression, never a timing assertion.
            self.assertLess(counts[0]*2,counts[1])



    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_recorded_model_responses_end_to_end(self):
        from collections import Counter
        from test_generation import MockResponses,response_for
        from rulang.generation import generate,LOCAL_TEST_API_KEY
        source = (ROOT/'tests/fixtures/contest/frequency.ru').read_text(encoding='utf-8')
        intent = ROOT/'tests/fixtures/contest/frequency.md'
        specification = (ROOT/'rulang/language-spec.md').read_bytes()
        with tempfile.TemporaryDirectory() as directory,MockResponses(response_for(source)) as server:
            config = Path(directory).resolve()/'config.json'
            config.write_text('{}',encoding='utf-8')
            destination = Path(directory).resolve()/'generated.ru'
            output = generate(intent,destination,environ={'RU_LANG_CONFIG':str(config),
                'RU_LLM_API_KEY':LOCAL_TEST_API_KEY,'RU_LLM_BASE_URL':server.base,'RU_LLM_MODEL':'fixed-contest-fixture'})
            self.assertEqual(output.read_text(encoding='utf-8'),source)
            self.assertEqual(len(server.requests),1)
            payload = server.requests[0][2]
            prompt = payload['input'][0]['content'][0]['text']
            self.assertIn(specification.decode('utf-8'),prompt)
            self.assertIn(hashlib.sha256(specification).hexdigest(),prompt)
            self.assertIn("外言 '如:竞赛'",prompt)
            self.assertIn('比较',prompt)
            self.assertEqual(payload['tools'],[])
            binary,_ = compile_native(source,directory,'generated-frequency',source_path=str(output))
            rng = random.Random(5050930)
            cases = [[],[0],[1000000,-1000000,0,1000000],[7]*60]
            cases.extend([[rng.randint(-20,20) for _ in range(rng.randrange(81))] for _ in range(124)])
            for index,values in enumerate(cases):
                counts = Counter(values)
                expected = ''.join(f'{value} {counts[value]}\n' for value in sorted(counts))
                separator = (' ','\t','\r\n','\v','\f')[index%5]
                data = str(len(values))+'\n'+separator.join(map(str,values))
                with self.subTest(case=index):
                    self.assertEqual(interpreted(source,data),expected)
                    result = native_run(binary,data)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual(result.stdout,expected)
                    self.assertIn('RU_GC live=0 ',result.stderr)


if __name__ == '__main__':
    unittest.main()
