"""Standalone Node.js backend parity, diagnostics, and checked I/O.

The shared language case matrices deliberately exercise the same programs as
Python/C. Every subprocess has a timeout; host files stay in temporary folders.
"""
import io
import math
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter
from rulang.modules import load_module_graph
import test_closures as closures
import test_contest as contest
import test_extensions as extensions
import test_panic as panic
import test_ru as core

NODE = shutil.which('node') or shutil.which('nodejs')
EXAMPLE_SOURCES = tuple(sorted((ROOT / 'examples').rglob('*.ru')))
# Native examples are Python-only. Keep their structural and denial checks
# separate from Node parity, rather than silently excluding their coverage.
NATIVE_EXAMPLE_SOURCES = tuple(path for path in EXAMPLE_SOURCES
                               if ROOT / 'examples' / 'native' in path.parents)
PORTABLE_EXAMPLE_SOURCES = tuple(path for path in EXAMPLE_SOURCES
                                 if path not in NATIVE_EXAMPLE_SOURCES)

POWER_DECOMPOSITION = contest.PRELUDE + """
算 分 数值 为 数:
    若 数值 == 0 则 得 '0'. 然
    幂 取 1. 阶 取 0.
    循 若 幂*2 > 数值 则 破. 然 幂 取 幂*2. 阶 取 阶+1. 环
    若 阶 == 0 则 文 取 '2(0)'.
    另 若 阶 == 1 则 文 取 '2'. 另 文 取 '2('+(分 阶)+')'. 然 然
    余 取 数值-幂.
    若 余 > 0 则 文 取 文+'+'+(分 余). 然
    得 文.
法
入 取 竞 其 读入. 出 取 竞 其 蓄出.
出 其 行 (分 (入 其 数)). 出 其 清.
"""


def quote(value):
    return "'" + str(value).replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r') + "'"


def compiled(source, folder, name='case', source_path=None, graph=None):
    from rulang.js_compiler import JSCompiler
    path = str(source_path or Path(folder).resolve() / (name + '.ru'))
    graph = graph if graph is not None else load_module_graph(path, parse(source))
    output = Path(folder).resolve() / (name + '.js')
    output.write_text(JSCompiler(graph[graph.root], graph.root, modules=graph).compile(), encoding='utf-8')
    return output, graph


def node_run(path, data='', args=(), cwd=None, env=None, timeout=20):
    raw = data.encode('utf-8') if isinstance(data, str) else data
    result = subprocess.run([NODE, str(path), *args], input=raw, capture_output=True,
                            cwd=cwd, env=env, timeout=timeout)
    # Preserve CR/LF precisely rather than using subprocess's universal newlines.
    return result.returncode, result.stdout.decode('utf-8'), result.stderr.decode('utf-8')


def interpreted(graph, data='', args=()):
    raw = data.encode('utf-8') if isinstance(data, str) else data
    output, errors = io.StringIO(), io.StringIO()
    runtime = Interpreter(io.BytesIO(raw), output, stderr=errors)
    runtime.execute(graph[graph.root], source_path=graph.root, modules=graph)
    status = runtime.execute_entry(list(args))
    return status, output.getvalue(), errors.getvalue()


class JavaScriptCompileTests(unittest.TestCase):
    def test_generates_javascript_without_requiring_node(self):
        from rulang import __version__
        from rulang.js_compiler import JSCompiler
        code = JSCompiler(parse("显 '你好😀'."), 'source.ru').compile()
        self.assertIsInstance(code, str)
        self.assertIn(__version__, code)
        self.assertIn('source.ru', code)
        self.assertNotIn('child_process', code)

    def test_python_only_native_examples_validate_and_explicitly_reject_node(self):
        from rulang.js_compiler import JSCompiler
        self.assertGreaterEqual(len(NATIVE_EXAMPLE_SOURCES), 3)
        self.assertEqual(set(EXAMPLE_SOURCES), set(PORTABLE_EXAMPLE_SOURCES) | set(NATIVE_EXAMPLE_SOURCES))
        self.assertFalse(set(PORTABLE_EXAMPLE_SOURCES) & set(NATIVE_EXAMPLE_SOURCES))
        for source_path in NATIVE_EXAMPLE_SOURCES:
            with self.subTest(example=str(source_path.relative_to(ROOT))):
                # Same non-executing parse/validate graph used by check --target
                # python, including the native bundle's transitive imports.
                graph = load_module_graph(source_path)
                with self.assertRaisesRegex(RuError, 'Node.js.*不支持') as caught:
                    JSCompiler(graph[graph.root], graph.root, modules=graph).compile()
                self.assertEqual(caught.exception.category, '能力错误')
                output = io.StringIO()
                with self.assertRaisesRegex(RuError, '原生能力默认关闭'):
                    Interpreter(stdout=output).execute(graph[graph.root], source_path=graph.root, modules=graph)
                self.assertEqual(output.getvalue(), '')

    def test_rejects_structurally_invalid_programs(self):
        from rulang.js_compiler import JSCompiler
        sources = extensions.STRUCTURAL_ERRORS + [
            '破.', '得 1.', '作 错: 得 1. 为',
            '算 同 值 为 数 值 为 数: 得 1. 法',
            '算 外: 若 1 则 算 内: 得 1. 法 然 得 0. 法',
            '试 算 内: 得 1. 法 救 原因 终.',
            '算 元初: 得 0. 法',
            '作 元初 参数 为 句 阵: 显 1. 为',
        ]
        for source in sources:
            with self.subTest(source=source), self.assertRaises(RuError):
                JSCompiler(parse(source)).compile()

    def test_undefined_calls_are_lexically_checked(self):
        from rulang.js_compiler import JSCompiler
        for source in (
            '算 无关: 假 取 1. 得 0. 法 算 坏: 得 假 1. 法',
            '算 外: 试 卒 "因". 救 原因 内取 取 1. 终. 得 内取 2. 法',
            '算 差 左 为 数 右 为 数: 得 左-右. 法 显 (差 1).',
            '算 差 左 为 数 右 为 数: 得 左-右. 法 显 (差 错:1 右:2).',
        ):
            with self.subTest(source=source), self.assertRaises(RuError):
                JSCompiler(parse(source)).compile()

    def test_unknown_ast_constructs_are_rejected_not_silently_omitted(self):
        from rulang.js_compiler import JSCompiler
        for expression in (False, True):
            program = parse('显 1.')
            target = program[0].data['expr'] if expression else program[0]
            target.kind = 'future_expression' if expression else 'future_statement'
            with self.subTest(expression=expression), self.assertRaises(RuError):
                JSCompiler(program).compile()
        for source, key in (('显 1+2.', 'op'), ('显 -1.', 'op'), ('显 1 为 数.', 'target')):
            program = parse(source)
            program[0].data['expr'].data[key] = 'future_operator'
            with self.subTest(source=source), self.assertRaises(RuError):
                JSCompiler(program).compile()

    def test_unused_optional_runtime_is_omitted(self):
        from rulang.js_compiler import JSCompiler
        code = JSCompiler(parse("显 '你好😀'."), 'hello.ru').compile()
        self.assertNotIn('function fileIO(', code)
        self.assertNotIn('class Scanner', code)
        self.assertLess(len(code.encode('utf-8')), 32 * 1024)

    def test_small_runtime_budget_covers_posix_and_windows_source_labels(self):
        from rulang.js_compiler import JSCompiler
        for source_name in ('/src/hello.ru', r'C:\src\hello.ru'):
            with self.subTest(source_name=source_name):
                code = JSCompiler(parse("显 '你好😀'."), source_name).compile()
                self.assertLess(len(code.encode('utf-8')), 32 * 1024)
                self.assertIn('function argsBind(', code)
                self.assertIn('若并列阵元素，请括起调用', code)
                self.assertGreater(len(code.splitlines()), 500)

    def test_builtin_type_annotations_keep_checked_io(self):
        from rulang.js_compiler import JSCompiler
        for kind in ('件', '录', '件作成果', '件 阵', '录 阵', '件作成果 阵'):
            source = f"算 接受 参数 为 {kind}: 得 1. 法 显 '好'."
            with self.subTest(kind=kind):
                code = JSCompiler(parse(source)).compile()
                self.assertIn('function fileIO(', code)
                self.assertNotIn('class Scanner', code)

    def test_compact_contest_runtime_omits_checked_filesystem_io(self):
        with tempfile.TemporaryDirectory() as folder:
            path, _ = compiled(POWER_DECOMPOSITION, folder)
            code = path.read_text(encoding='utf-8')
            self.assertIn('class Scanner', code)
            self.assertNotIn('function fileIO(', code)
            self.assertLess(len(code.encode('utf-8')), 45 * 1024)


@unittest.skipUnless(NODE, 'Node.js unavailable')
class JavaScriptParityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()

    def assert_output(self, source, expected, data='', args=(), status=0, name='case'):
        path, _ = compiled(source, self.folder, name)
        actual = node_run(path, data, args)
        self.assertEqual(actual, (status, expected, ''))

    def assert_error(self, source, data='', name='bad', category='运行错误'):
        try:
            path, graph = compiled(source, self.folder, name)
        except RuError:
            # Statically rejecting an invalid program is also permitted.
            with self.assertRaises(RuError):
                graph = load_module_graph(self.folder / (name + '.ru'), parse(source))
                interpreted(graph, data)
            return
        status, output, error = node_run(path, data)
        self.assertEqual(status, 1, (output, error))
        self.assertIn(category, error)
        self.assertTrue(any(origin + ':' in error for origin in graph), error)
        self.assertRegex(error, r':\d+:\d+: error: ')
        self.assertNotIn('Traceback', error)
        self.assertNotIn('ReferenceError', error)
        self.assertNotIn('TypeError:', error)
        self.assertNotIn('RangeError:', error)

    def test_core_language_cases(self):
        for name, source, data, expected in core.SUCCESS_CASES:
            with self.subTest(case=name):
                self.assert_output(source, expected, data, name=name)

    def test_collections_objects_and_inheritance(self):
        for name, source, expected in extensions.SUCCESS_CASES:
            with self.subTest(case=name):
                self.assert_output(source, expected, name=name)

    def test_closures_and_bound_methods(self):
        for name, source, expected in closures.CASES:
            with self.subTest(case=name):
                self.assert_output(source, expected, name=name)

    def test_panic_control_flow_and_scope(self):
        for name, source, expected in panic.CASES:
            with self.subTest(case=name):
                self.assert_output(source, expected, name=name)

    def test_contest_library_cases(self):
        for name, source, expected in contest.CASES:
            with self.subTest(case=name):
                self.assert_output(source, expected, name=name)

    def test_core_runtime_errors(self):
        for name, source, data in core.ERROR_CASES:
            with self.subTest(case=name):
                self.assert_error(source, data, name=name)

    def test_collection_object_and_closure_errors(self):
        cases = extensions.RUNTIME_ERRORS + [(f'closure_{i}', s) for i, s in enumerate(closures.ERRORS)]
        cases += [(f'contest_{i}', contest.PRELUDE + s) for i, s in enumerate(contest.ERRORS)]
        for name, source in cases:
            with self.subTest(case=name):
                self.assert_error(source, name=name)

    def test_nonpanic_errors_cannot_be_rescued(self):
        for source in ("试 显 1/0. 救 原因 显 '不应'. 终.",
                       "试 卒 3. 救 原因 显 '不应'. 终.",
                       "试 显 [1][2]. 救 原因 显 '不应'. 终."):
            with self.subTest(source=source):
                self.assert_error(source)
                path, _ = compiled(source, self.folder)
                self.assertEqual(node_run(path)[1], '')

    def test_uncaught_panic_reports_source_location(self):
        path, _ = compiled("显 '先'.\n卒 '原因😀'.", self.folder, 'panic_origin')
        status, output, error = node_run(path)
        self.assertEqual((status, output), (1, '先\n'))
        self.assertIn('panic_origin.ru:2:1: error: 未救之卒：原因😀', error)

    def test_assignment_checks_target_before_rhs(self):
        prefix = "算 副作用: 显 '不应执行'. 得 2. 法 "
        for suffix in ("列 取 [1]. 列[2] 取 副作用.",
                       "列 取 [1]. 列[-1] 取 副作用.",
                       "列 取 1. 列[0] 取 副作用.",
                       "列 取 '甲'. 列[0] 取 副作用.",
                       "形 盒: 值 为 数. 象 盒值 取 新 盒. 盒值 其 未知 取 副作用.",
                       "算 生 列 为 阵: 列 其 增 8. 得 9. 法 列 取 []. 列[0] 取 (生 列)."):
            with self.subTest(source=suffix):
                path, _ = compiled(prefix + suffix, self.folder)
                status, output, error = node_run(path)
                self.assertEqual((status, output), (1, ''))
                self.assertIn('运行错误', error)

    def test_number_formatting_matches_fifteen_significant_digits(self):
        numbers = [0.0, -0.0, 1e-7, 1e-6, 1e-5, 1e-4, 1e14, 1e15,
                   1e20, 1e21, 1e-100, 1e308, 5e-324, 98.01, 1.234567890123456,
                   999999999999999.5, -0.00009999999999999995]
        rng = random.Random(9302026)
        while len(numbers) < 400:
            number = struct.unpack('>d', rng.getrandbits(64).to_bytes(8, 'big'))[0]
            if math.isfinite(number):
                numbers.append(number)
        source = '\n'.join(f'显 {number!r}.' for number in numbers)
        expected = ''.join(format(number, '.15g') + '\n' for number in numbers)
        self.assert_output(source, expected)

    def test_unicode_comparisons_use_codepoints_not_utf16_units(self):
        source = ("显 '𐀀' > '\uffff'. 显 '😀' > '\ue000'. "
                  "显 'a😀' > 'a\uffff'. 显 'é👩‍💻' 其 量. "
                  "显 'é👩‍💻'[2:5]. 显 'a😀b' 其 含 '😀'.")
        self.assert_output(source, '真\n真\n真\n5\n👩‍💻\n真\n')

    def test_javascript_special_names_and_string_escaping(self):
        source = ("__proto__ 取 1. constructor 取 2. prototype 取 3. "
                  "算 toString 值 为 数: 得 值+__proto__. 法 "
                  "显 (toString constructor)+prototype. "
                  + '显 ' + quote("quotes '\" and \\ newline\n\u2028\u2029 ${notJS} </script> 😀") + '.')
        path, graph = compiled(source, self.folder)
        self.assertEqual(node_run(path), interpreted(graph))

    def test_shared_pair_dag_and_cyclic_display(self):
        source = ("左 取 0 对 空. 右 取 0 对 空. 循 30 次 左 取 左 对 左. "
                  "右 取 右 对 右. 环 显 左 == 右. 列 取 []. 列 其 增 列. 显 列.")
        self.assert_output(source, '真\n[<循环>]\n')

    def test_closure_and_panic_allocation_stress(self):
        self.assert_output(closures.STRESS, '11\n', name='closure_stress')
        self.assert_output(panic.STRESS, '底返\n', name='panic_stress')

    def test_named_arity_error_retains_missing_unknown_names_and_counts(self):
        source = '算 合 左 右: 得 左+右. 法 别名 取 算 合.\n显 别名 多:1 余:2.'
        path, graph = compiled(source, self.folder)
        status, output, error = node_run(path)
        self.assertEqual((status, output), (1, ''))
        for fragment in ('函数「合」', '缺少「左、右」', '未知「多、余」',
                         '需要 2 个实参', '收到 2 个', graph.root + ':2:'):
            self.assertIn(fragment, error)
        self.assertNotIn('若并列阵元素', error)

    def test_entry_arguments_exit_status_and_invalid_returns(self):
        source = "显 '顶层'. 算 元初 外参 为 句 阵: 显 外参 其 量. 显 外参[0]. 显 外参[1]. 得 7. 法"
        self.assert_output(source, '顶层\n2\n甲😀\n--flag\n', args=('甲😀', '--flag'), status=7)
        self.assert_output('算 元初 参数 为 句 阵: 显 参数 其 量. 得 0. 法', '0\n')
        for value in ('-1', '256', '0.5', "'0'", '空'):
            with self.subTest(value=value):
                self.assert_error(f'算 元初 参数 为 句 阵: 得 {value}. 法', name='bad_entry')

    def test_examples_match_interpreter(self):
        inputs = {
            'add.ru': '20\n22\n', 'conversation.ru': '你好\n再见\n',
            'contest_sum_eof.ru': '1 2\n-4 10\n',
            'contest_prefix_sum.ru': '4 3\n1 2 3 4\n1 4\n2 3\n4 4\n',
            'contest_line_words.ru': '甲 乙\n\n😀\n',
            'contest_stable_records.ru': '4 1\n甲 2\n乙 1\n丙 2\n丁 -1\n',
        }
        for source_path in PORTABLE_EXAMPLE_SOURCES:
            with self.subTest(example=str(source_path.relative_to(ROOT))):
                source = source_path.read_text(encoding='utf-8')
                path, graph = compiled(source, self.folder, source_path.stem, source_path=source_path)
                data = inputs.get(source_path.name, '')
                self.assertEqual(node_run(path, data, ('如😀', '--flag'), cwd=ROOT),
                                 interpreted(graph, data, ('如😀', '--flag')))

    def test_randomized_contest_programs(self):
        rng = random.Random(20260930)
        programs = {}
        for name in ('sum_eof', 'prefix_sum', 'stable_records'):
            source_path = ROOT / 'examples' / ('contest_' + name + '.ru')
            programs[name] = compiled(source_path.read_text(encoding='utf-8'), self.folder,
                                      name, source_path=source_path)[0]
        for turn in range(8):
            pairs = [(rng.randrange(-10000, 10000), rng.randrange(-10000, 10000)) for _ in range(turn)]
            data = '\r\n'.join(f'{a} {b}' for a, b in pairs)
            cases = [('sum_eof', data, ''.join(f'{a+b}\n' for a, b in pairs))]
            values = [rng.randrange(-10000, 10000) for _ in range(20)]
            ranges = [sorted((rng.randrange(1, 21), rng.randrange(1, 21))) for _ in range(turn)]
            data = f'20 {turn}\n' + ' '.join(map(str, values)) + '\n' + ''.join(f'{a} {b}\n' for a, b in ranges)
            cases.append(('prefix_sum', data, ''.join(f'{sum(values[a-1:b])}\n' for a, b in ranges)))
            records = [('名' + str(i) + '😀', rng.randrange(-3, 4)) for i in range(turn * 4)]
            direction = rng.choice((-1, 1))
            data = f'{len(records)} {direction}\n' + ''.join(f'{name} {score}\n' for name, score in records)
            expected = ''.join(f'{name} {score}\n' for name, score in sorted(records, key=lambda r: r[1] * direction))
            cases.append(('stable_records', data, expected))
            for name, data, expected in cases:
                with self.subTest(program=name, turn=turn):
                    self.assertEqual(node_run(programs[name], data), (0, expected, ''))

    def write_modules(self, files):
        for name, source in files.items():
            path = self.folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding='utf-8')
        return self.folder / 'main.ru'

    def assert_modules(self, files, expected, args=(), status=0):
        main = self.write_modules(files)
        graph = load_module_graph(main)
        path, _ = compiled(files['main.ru'], self.folder, source_path=main, graph=graph)
        self.assertEqual(interpreted(graph, args=args), (status, expected, ''))
        for file in self.folder.rglob('*.ru'):
            file.unlink()
        self.assertEqual(node_run(path, args=args, cwd='/', env={**os.environ, 'PATH': ''}), (status, expected, ''))

    def test_standalone_modules_cache_scope_inheritance_and_entry(self):
        self.assert_modules({
            'main.ru': "基 取 999. 模 取 外言 'sub/factory.ru'. 别 取 外言 'sub/../sub/factory.ru'. "
                       "显 模 == 别. 工厂 取 算 模 其 制. 回调 取 工厂 2. 显 (回调 3). "
                       "尽取 外言 'base.ru'. 形 子 如 父: 算 读取: 得 其 值*2. 法 象 "
                       "对象 取 新 子 值:3. 显 对象 其 双读. "
                       "算 元初 参数 为 句 阵: 显 参数[0]. 得 7. 法",
            'sub/factory.ru': "显 '初始化'. 基 取 100. 算 制 起 为 数: 值 取 起. "
                              "算 加 步 为 数: 值 取 值+步. 得 值+基. 法 得 算 加. 法 "
                              "算 元初 参数 为 句 阵: 卒 '不能运行库入口'. 法",
            'base.ru': "形 父: 值 为 数. 算 读取: 得 其 值. 法 算 双读: 得 (其 读取)*2. 法 象",
        }, '初始化\n真\n105\n12\n甲😀\n', args=('甲😀',), status=7)

    def test_import_all_aliasing_and_diamond(self):
        self.assert_modules({
            'main.ru': "尽取 外言 'common.ru'. 值 取 2. 列 其 增 3. "
                       "甲 取 外言 'a.ru'. 乙 取 外言 'b.ru'. 显 (甲 其 共) == (乙 其 共). "
                       "显 甲 其 共 其 值. 显 甲 其 共 其 列. 显 值.",
            'a.ru': "共 取 外言 'common.ru'.", 'b.ru': "共 取 外言 'common.ru'.",
            'common.ru': "显 '一次'. 值 取 1. 列 取 [1].",
        }, '一次\n真\n1\n[1, 3]\n2\n')

    def test_imported_io_factories_keep_runtime_for_the_whole_graph(self):
        main = self.write_modules({
            'main.ru': "模 取 外言 'lib.ru'. 文件 取 模 其 文件. "
                       "显 (文件 其 在) 其 结果. (模 其 输出口) 其 写 内容:'好'.",
            'lib.ru': '算 文件: 得 新 件. 法 输出口 取 显出.',
        })
        path, graph = compiled(main.read_text(encoding='utf-8'), self.folder, source_path=main)
        code = path.read_text(encoding='utf-8')
        self.assertIn('function fileIO(', code)
        self.assertNotIn('class Scanner', code)
        expected = (0, '失败\n好', '')
        self.assertEqual(interpreted(graph), expected)
        for file in self.folder.rglob('*.ru'):
            file.unlink()
        self.assertEqual(node_run(path, cwd='/', env={**os.environ, 'PATH': ''}), expected)

    def test_custom_read_write_methods_and_legacy_read_need_no_checked_io(self):
        source = ("形 用户: 算 读: 得 '自定义'. 法 作 写 内容 为 句: 显 内容. 为 象 "
                  "对象 取 新 用户. 显 对象 其 读. 对象 其 写 '输出'. 显 读.")
        path, graph = compiled(source, self.folder)
        code = path.read_text(encoding='utf-8')
        self.assertNotIn('function fileIO(', code)
        self.assertNotIn('class Scanner', code)
        expected = (0, '自定义\n输出\n输入😀\n', '')
        self.assertEqual(interpreted(graph, '输入😀\n'), expected)
        self.assertEqual(node_run(path, '输入😀\n'), expected)

    def test_builtin_names_inside_literals_remain_plain_text(self):
        # A conservative feature scan may keep optional code for these words.
        text = '__如竞 件 录 件作成果 读取 显出 错误'
        self.assert_output('显 ' + quote(text) + '.', text + '\n')

    def test_builtin_instances_are_per_module_but_types_are_shared(self):
        self.assert_modules({
            'main.ru': "模 取 外言 'lib.ru'. 显 (模 其 输入口) == 读取. "
                       "显 (模 其 输出口) == 显出. 显 (模 其 错误口) == 错误. "
                       "显 (模 其 竞具) == __如竞. 算 查 文档 为 件: 得 1. 法 显 查 (模 其 文件).",
            'lib.ru': "算 输入口: 得 读取. 法 算 输出口: 得 显出. 法 "
                      "算 错误口: 得 错误. 法 算 竞具: 得 __如竞. 法 算 文件: 得 新 件. 法",
        }, '假\n假\n假\n假\n1\n')

    def test_compact_recursive_contest_program(self):
        path, graph = compiled(POWER_DECOMPOSITION, self.folder)
        for value in (1, 2, 3, 137, 1315, 20000):
            with self.subTest(value=value):
                self.assertEqual(node_run(path, str(value)), interpreted(graph, str(value)))

    def test_failed_module_initializer_keeps_escaped_closures(self):
        self.assert_modules({
            'main.ru': "共享 取 外言 'shared.ru'. 循 3 次 试 坏模块 取 外言 'broken.ru'. "
                       "救 原因 显 原因. 终. 环 显 共享 其 存 其 量. 回调 取 共享 其 存[0]. 显 回调().",
            'shared.ru': '存 取 [].',
            'broken.ru': "桥 取 外言 'shared.ru'. 基 取 7. 算 制 起 为 数: 算 看: 得 起+基. "
                         "法 得 算 看. 法 桥 其 存 其 增 (制 5). 卒 '失败'.",
        }, '失败\n失败\n失败\n1\n12\n')

    def test_cached_module_panic_preserves_origin(self):
        main = self.write_modules({
            'main.ru': "试 模 取 外言 'middle.ru'. 救 原因 终. 模 取 外言 'middle.ru'.",
            'middle.ru': "模 取 外言 'bad.ru'.", 'bad.ru': "显 '一次'.\n卒 '初始化失败'.",
        })
        path, _ = compiled(main.read_text(encoding='utf-8'), self.folder, source_path=main)
        status, output, error = node_run(path)
        self.assertEqual((status, output), (1, '一次\n'))
        self.assertIn(str(self.folder / 'bad.ru') + ':2:1: error: 未救之卒：初始化失败', error)

    def test_builtin_parent_is_not_exported_by_modules(self):
        from rulang.io_runtime import IO_BUILTIN_NAMES
        for name in IO_BUILTIN_NAMES:
            with self.subTest(name=name):
                main = self.write_modules({'main.ru': f"模 取 外言 'lib.ru'. 显 模 其 {name}.", 'lib.ru': '值 取 1.'})
                path, _ = compiled(main.read_text(encoding='utf-8'), self.folder, source_path=main)
                status, output, error = node_run(path)
                self.assertEqual((status, output), (1, ''))
                self.assertIn('未知成员：' + name, error)

    def test_checked_file_roundtrip_and_invalid_writes(self):
        data = self.folder / '你好😀.txt'
        source = f"""
文档 取 新 件 路径:{quote(data)}.
显 (文档 其 在) 其 值.
应 取 文档 其 写 内容:'甲😀\n'. 显 应 其 结果. 显 应 其 值.
显 (文档 其 写 追加:1 内容:'乙') 其 结果. 显 (文档 其 读) 其 值.
显 (文档 其 写 内容:3) 其 结果. 显 (文档 其 写 内容:'damage' 追加:2) 其 结果.
显 (文档 其 读) 其 值.
显 (文档 其 除) 其 结果. 显 (文档 其 在) 其 值.
应 取 文档 其 读. 显 应 其 结果. 显 应 其 值. 显 应 其 错误信息 其 含 'errno'.
"""
        self.assert_output(source, '假\n成功\n空\n成功\n甲😀\n乙\n失败\n失败\n甲😀\n乙\n成功\n假\n失败\n空\n真\n')
        self.assertFalse(data.exists())

    def test_checked_io_result_is_typed_mutable_object(self):
        source = "算 查 回 为 件作成果: 得 回 其 值. 法 应 取 新 件作成果. 显 应 其 结果. "
        source += "应 其 值 取 [1,'二']. 显 (查 应)[1]. 应 其 结果 取 '用户'. 显 应 其 结果. "
        source += "应 其 值 取 应. 显 应 其 值 == 应. 显 (新 件) 其 路径 == ''. 显 (新 录) 其 路径."
        self.assert_output(source, '成功\n二\n用户\n真\n真\n.\n')

    def test_invalid_file_utf8_nul_and_nonfiles_are_checked_failures(self):
        (self.folder / 'badutf8').write_bytes(b'\xff\xfe')
        (self.folder / 'nul').write_bytes(b'a\x00b')
        (self.folder / 'directory').mkdir()
        for path in (self.folder / 'badutf8', self.folder / 'nul', self.folder / 'directory'):
            with self.subTest(path=path.name):
                self.assert_output(f"显 ((新 件 路径:{quote(path)}) 其 读) 其 结果.", '失败\n')
        self.assert_output(f"显 ((新 件 路径:{quote(self.folder / 'directory')}) 其 在) 其 值.", '假\n')

    def test_directory_listing_is_sorted_and_regular_only(self):
        listing = self.folder / 'listing'
        listing.mkdir()
        for name in ('乙.txt', 'a.txt', '😀.txt', '\uffff.txt'):
            (listing / name).write_text(name, encoding='utf-8')
        (listing / 'subdir').mkdir()
        source = f"列 取 ((新 录 路径:{quote(listing)}) 其 列) 其 值. 显 列 其 量. 位 取 0. 循 列 其 量 次 显 (列[位] 其 读) 其 值. 位 取 位+1. 环"
        self.assert_output(source, '4\na.txt\n乙.txt\n\uffff.txt\n😀.txt\n')

    @unittest.skipUnless(hasattr(os, 'symlink'), 'symlinks unavailable')
    def test_checked_symlink_policy(self):
        target, link, dangling = (self.folder / name for name in ('target', 'link', 'dangling'))
        target.write_text('原', encoding='utf-8')
        link.symlink_to(target)
        dangling.symlink_to(self.folder / 'absent')
        source = f"链接 取 新 件 路径:{quote(link)}. 显 (链接 其 读) 其 值. 链接 其 写 '新'. 显 ((新 件 路径:{quote(target)}) 其 读) 其 值. 显 (链接 其 除) 其 结果. 显 ((新 件 路径:{quote(target)}) 其 在) 其 值. 失链 取 新 件 路径:{quote(dangling)}. 显 (失链 其 在) 其 值. 显 (失链 其 除) 其 结果."
        self.assert_output(source, '原\n新\n成功\n真\n假\n成功\n')
        self.assertTrue(target.exists())
        self.assertFalse(link.is_symlink())
        self.assertFalse(dangling.is_symlink())

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'requires POSIX FIFO')
    def test_special_files_fail_without_blocking(self):
        fifo = self.folder / 'fifo'
        os.mkfifo(fifo)
        self.assert_output(f"文件 取 新 件 路径:{quote(fifo)}. 显 (文件 其 读) 其 结果. 显 (文件 其 在) 其 值. 显 (文件 其 除) 其 结果.", '失败\n假\n失败\n')

    def test_stdin_checked_utf8_recovery_and_legacy_reads(self):
        source = '循 3 次 应 取 读取 其 读. 显 应 其 结果. 显 应 其 值. 环'
        for invalid in (b'\xff', b'\x00', b'\xc0\x80', b'\xed\xa0\x80', b'\xf4\x90\x80\x80'):
            with self.subTest(invalid=invalid):
                self.assert_output(source, '成功\ngood\n失败\n空\n成功\nafter\n', b'good\n' + invalid + b'\nafter\n')
        self.assert_output('显 读. 显 (读取 其 读) 其 值. 显 读.', '甲\n\n尾\n', '甲\r\n\n尾')
        self.assert_output('应 取 读取 其 读. 显 应 其 结果. 显 应 其 值 == 空. 显 应 其 错误信息 == \'\'.', '成功\n真\n真\n')
        # UTF-8 BOM is a codepoint in input, never stripped as a decoder option.
        self.assert_output('显 读.', '\ufeffhello\n', b'\xef\xbb\xbfhello\n')
        self.assert_output("显 (读取 其 读) 其 值.", '\ufeffhello\n', b'\xef\xbb\xbfhello\n')

    def test_checked_stdout_and_stderr_have_no_implicit_newline(self):
        source = "应 取 显出 其 写 内容:'甲😀'. 显 应 其 结果. 显 应 其 值. 错误 其 写 内容:'诊断😀'."
        path, _ = compiled(source, self.folder)
        self.assertEqual(node_run(path), (0, '甲😀成功\n空\n', '诊断😀'))

    @unittest.skipIf(os.name == 'nt', 'requires POSIX pipes')
    def test_closed_pipe_is_checked_failure_or_fatal_for_legacy_print(self):
        cases = [("应 取 显出 其 写 内容:'测试'. 错误 其 写 内容:应 其 结果.", 0, '失败'),
                 ("试 显 '测试'. 救 原因 显 '不可救'. 终.", 1, '运行错误：输出失败')]
        for source, expected_status, diagnostic in cases:
            with self.subTest(source=source):
                path, _ = compiled(source, self.folder)
                reader, writer = os.pipe()
                os.close(reader)
                try:
                    result = subprocess.run([NODE, str(path)], stdout=writer, stderr=subprocess.PIPE, timeout=10)
                finally:
                    os.close(writer)
                self.assertEqual(result.returncode, expected_status)
                self.assertIn(diagnostic, result.stderr.decode('utf-8'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
