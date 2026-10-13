"""Conservative C-runtime pruning, full-runtime parity, and exact P1010 output.

The scanner supports the bundled headers' ordinary top-level C functions; it
is not a general C parser or preprocessor. Tests intentionally retain opaque
top-level declarations, macro references and all platform alternatives.
"""
import copy
from functools import lru_cache
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.c_runtime import (
    mask_noncode, member_names, prune_functions, runtime_source,
    specialize_members,
)
from rulang.compiler import Compiler
from rulang.frontend import parse
from rulang.modules import load_module_graph

CC = (shutil.which(os.environ['CC']) if os.environ.get('CC') else
      next((shutil.which(c) for c in ('gcc', 'clang', 'cc') if shutil.which(c)), None))
FIXTURE = ROOT / 'tests' / 'fixtures' / 'contest' / 'p1010.ru'
GC_STATS = re.compile(r'RU_GC live=(\d+) freed=(\d+) collections=(\d+)\n?')


def generate(source, source_name='/runtime-pruning.ru', *, full=False, graph=None):
    graph = graph if graph is not None else load_module_graph(source_name, parse(source))
    return Compiler(graph[graph.root], graph.root, modules=graph,
                    full_runtime=full).compile()


def build(generated, directory, stem):
    cfile, binary = Path(directory).resolve() / (stem + '.c'), Path(directory).resolve() / stem
    cfile.write_text(generated, encoding='utf-8')
    # In particular P1010 must build as portable standalone C99 without libm,
    # project include directories, generated support files or warning fixes.
    result = subprocess.run(
        [CC, '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
         '-Wno-unused-function', '-pedantic', str(cfile),
         *(['-lm'] if '#define RU_ENABLE_MODULO 1' in generated or any(name in generated for name in ('ru_practical_pow', 'ru_practical_sqrt', 'ru_practical_round', 'ru_random_integer')) else []),
         '-o', str(binary)],
        capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise AssertionError(result.stderr)
    return binary


def run(binary, stdin='', *, cwd=None, force_gc=True):
    env = {**os.environ, 'RU_GC_STATS': '1'}
    env.pop('RU_GC_THRESHOLD', None)
    if force_gc:
        env['RU_GC_THRESHOLD'] = '1'
    return subprocess.run([str(binary)], input=stdin, capture_output=True,
                          text=True, env=env, cwd=cwd, timeout=15)


@lru_cache(maxsize=None)
def p1010_oracle(value):
    """Independent binary-decomposition oracle; no fixture/source rewriting."""
    if value == 0:
        return '0'
    terms = []
    for exponent in range(value.bit_length() - 1, -1, -1):
        if value & (1 << exponent):
            terms.append('2' if exponent == 1
                         else '2(' + p1010_oracle(exponent) + ')')
    return '+'.join(terms)


class RuntimeScannerTests(unittest.TestCase):
    def test_mask_hides_comments_literals_and_preserves_offsets(self):
        source = r'''/* hidden_call() { */
static int visible(void) {
    const char *s = "escaped \\\" hidden_string() // }";
    char brace = '}'; char quote = '\'';
    // invisible() { "
    return real_call(); /* trailing() */
}
'''
        masked = mask_noncode(source)
        self.assertEqual(len(masked), len(source))
        self.assertEqual([i for i, c in enumerate(source) if c == '\n'],
                         [i for i, c in enumerate(masked) if c == '\n'])
        for name in ('hidden_call', 'hidden_string', 'invisible', 'trailing'):
            self.assertNotIn(name, masked)
        self.assertIn('visible(void)', masked)
        self.assertIn('real_call()', masked)
        self.assertEqual(masked.count('{'), 1)
        self.assertEqual(masked.count('}'), 1)

    def test_strings_comments_and_root_literals_do_not_keep_functions(self):
        source = '''static int dead(void) { return 9; }
static int also_dead(void) { return 8; }
/* dead() is just documentation. */
static int live(void) {
    const char *text = "dead() { also_dead }";
    /* also_dead(); } */
    return text[0];
}
'''
        result = prune_functions(source, 'live(); /* dead(); */ "also_dead";')
        self.assertIn('static int live(void)', result)
        self.assertIn('"dead() { also_dead }"', result)
        self.assertNotIn('static int dead(void)', result)
        self.assertNotIn('static int also_dead(void)', result)

    def test_address_taken_functions_and_global_tables_are_roots(self):
        source = '''static int leaf(void) { return 1; }
static int callback(void) { return leaf(); }
static int table_callback(void) { return 2; }
static int unused(void) { return 3; }
static int (*table[])(void) = {table_callback};
static int entry(void) {
    int (*function)(void) = &callback;
    return function();
}
'''
        result = prune_functions(source, 'entry();')
        for name in ('leaf', 'callback', 'table_callback', 'entry'):
            self.assertIn('static int ' + name + '(void)', result)
        self.assertIn('static int (*table[])(void) = {table_callback};', result)
        self.assertNotIn('static int unused(void)', result)

    def test_macro_bodies_conservatively_root_helpers(self):
        source = '''#define APPLY(value) macro_helper(value)
static int macro_leaf(int value) { return value; }
static int macro_helper(int value) { return macro_leaf(value); }
static int dead(int value) { return value; }
'''
        result = prune_functions(source, '')
        self.assertIn('#define APPLY(value) macro_helper(value)', result)
        self.assertIn('static int macro_helper', result)
        self.assertIn('static int macro_leaf', result)
        self.assertNotIn('static int dead', result)

    def test_same_name_platform_branches_keep_both_dependencies(self):
        source = '''static int windows_helper(void) { return 1; }
static int posix_helper(void) { return 2; }
#ifdef _WIN32
static int platform(void) { return windows_helper(); }
#else
static int platform(void) { return posix_helper(); }
#endif
static int dead(void) { return 3; }
'''
        result = prune_functions(source, 'platform();')
        self.assertEqual(result.count('static int platform(void)'), 2)
        for name in ('windows_helper', 'posix_helper'):
            self.assertIn('static int ' + name + '(void)', result)
        for directive in ('#ifdef _WIN32', '#else', '#endif'):
            self.assertIn(directive, result)
        self.assertNotIn('static int dead(void)', result)

    def test_reachable_cycle_keeps_prototypes_unreachable_cycle_disappears(self):
        source = '''static int first(void);
static int second(void);
static int dead_first(void);
static int dead_second(void);
static int first(void) { return second(); }
static int second(void) { return first(); }
/* Documentation for an unreachable helper. */
static int dead_first(void) { return dead_second(); }
static int dead_second(void) { return dead_first(); }
'''
        result = prune_functions(source, 'first();')
        for name in ('first', 'second'):
            self.assertIn('static int ' + name + '(void);', result)
            self.assertIn('static int ' + name + '(void) {', result)
        self.assertNotIn('dead_first', result)
        self.assertNotIn('dead_second', result)
        self.assertNotIn('Documentation for an unreachable helper', result)
        self.assertEqual(prune_functions(source, '').strip(), '')

    def test_nonfunction_declarations_and_attached_live_comments_stay_readable(self):
        source = '''typedef int Counter;
static Counter count;
/* Keep the implementation documentation. */
static Counter live(void)
{
    count += 1;
    return count;
}
'''
        self.assertEqual(prune_functions(source, 'live();'), source)

    def test_unbalanced_recognized_function_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'Unbalanced.*broken'):
            prune_functions('static int broken(void) { return 1;', '')

    def test_member_markers_select_all_receivers_with_used_spelling(self):
        source = '''prefix
/* RU_MEMBERS: 行,写 */
writer_implementation
/* RU_END_MEMBERS */
/* RU_MEMBERS: 行 */
reader_implementation
/* RU_END_MEMBERS */
/* RU_MEMBERS: 排序 */
unused_sort
/* RU_END_MEMBERS */
suffix
'''
        self.assertEqual(specialize_members(source, {'行'}),
                         'prefix\nwriter_implementation\nreader_implementation\nsuffix\n')
        self.assertEqual(specialize_members(source, set()), 'prefix\nsuffix\n')

    def test_implicit_contains_dispatch_is_a_member_root(self):
        program = parse("显 'abc' 其 含 'a'. 列 取 []. 列 其 增 1.")
        self.assertEqual(member_names(program), {'含', '增'})

    def test_full_runtime_keeps_unused_functions_and_resolves_features(self):
        full = runtime_source({}, '', full=True)
        for name in ('ru_io_list(', 'ru_contest_sort(', 'v_pair(', 'ru_enter('):
            self.assertIn(name, full)
        for marker in ('RU_FEATURE:', 'RU_ELSE_FEATURE', 'RU_END_FEATURE'):
            self.assertNotIn(marker, full)
        self.assertGreater(len(full.encode('utf-8')), 70000)


class RuntimeGenerationTests(unittest.TestCase):
    def test_minimal_runtime_removes_unused_subsystems(self):
        pruned, full = generate('显 42.'), generate('显 42.', full=True)
        for name in ('ru_io_list(', 'ru_contest_sort(', 'v_pair('):
            self.assertIn(name, full)
            self.assertNotIn(name, pruned)
        self.assertLess(len(pruned.encode('utf-8')), len(full.encode('utf-8')))
        for marker in ('RU_FEATURE:', 'RU_ELSE_FEATURE', 'RU_END_FEATURE', 'RU_MEMBERS:'):
            self.assertNotIn(marker, pruned)

    def test_io_annotation_and_literal_detection_remain_conservative(self):
        for source in ("显 '件'.", '算 看 列 为 件 阵: 得 列. 法 显 1.'):
            with self.subTest(source=source):
                self.assertIn('static RuClass ru_io_file_class', generate(source))

    def test_compilation_does_not_mutate_graph_or_write_artifacts(self):
        source = "尽 取 外言 '如:竞'. 显 小 2 3."
        with tempfile.TemporaryDirectory() as directory:
            graph = load_module_graph(str(Path(directory).resolve() / 'main.ru'), parse(source))
            before = copy.deepcopy(graph)
            for full in (False, True):
                generated = generate(source, full=full, graph=graph)
                self.assertIn('Standalone C99', generated)
                self.assertEqual(graph, before)
                self.assertEqual(graph.sources, before.sources)
                self.assertEqual(list(Path(directory).resolve().iterdir()), [])

    def test_exact_p1010_is_under_fifty_thousand_utf8_bytes_and_readable(self):
        source = FIXTURE.read_text(encoding='utf-8')
        # Supplying a short root name makes the size check independent of the
        # caller's cwd/root filename. The actual fixture is read, never edited.
        generated = generate(source, source_name='/p1010.ru')
        self.assertLess(len(generated.encode('utf-8')), 50000)
        self.assertGreater(len(generated.splitlines()), 400)
        self.assertIn('/* Generated by ru ', generated)
        self.assertIn('static Val ', generated)
        self.assertIn('\n    ', generated)
        self.assertNotRegex(generated, r'(?m)^\s*#\s*include\s*"')


@unittest.skipUnless(CC, 'C compiler unavailable')
class RuntimeParityTests(unittest.TestCase):
    def assert_clean(self, result):
        stats = GC_STATS.findall(result.stderr)
        self.assertEqual(len(stats), 1, result.stderr)
        self.assertEqual(stats[0][0], '0', result.stderr)
        self.assertGreater(int(stats[0][2]), 0, result.stderr)

    def compare(self, source, expected=None, stdin='', *, graph=None, success=True):
        with tempfile.TemporaryDirectory() as directory:
            results = []
            for full in (False, True):
                generated = generate(source, full=full, graph=graph)
                binary = build(generated, directory, 'full' if full else 'pruned')
                result = run(binary, stdin)
                self.assert_clean(result)
                results.append((result.returncode, result.stdout,
                                GC_STATS.sub('', result.stderr)))
            self.assertEqual(results[0], results[1])
            if success:
                self.assertEqual(results[0][0], 0, results[0][2])
            else:
                self.assertNotEqual(results[0][0], 0)
                self.assertRegex(results[0][2], '错误|未救之卒')
            if expected is not None:
                self.assertEqual(results[0][1], expected)
            return results[0]

    def test_functions_closures_objects_arrays_pairs_and_dispatch(self):
        # Representative semantics from test_closures/test_panic/test_contest,
        # compared to the independently retained full runtime, with forced GC.
        cases = [
            ('recursive_function', '算 阶 数值 为 数: 若 数值 <= 1 则 得 1. 然 得 数值*(阶 数值-1). 法 显 阶 6.', '720\n'),
            ('captured_cell', '算 制 起 为 数: 算 加: 起 取 起+1. 得 起. 法 得 算 加. 法 甲 取 制 4. 显 甲(). 显 甲().', '5\n6\n'),
            ('bound_method', '形 计: 值 为 数. 算 加 步 为 数: 其 值 取 其 值+步. 得 其 值. 法 象 对象 取 新 计 值:2. 回调 取 算 对象 其 加. 对象 取 空. 显 (回调 3). 显 (回调 4).', '5\n9\n'),
            ('cyclic_array', "列 取 [1,'二']. 列 其 增 列. 显 列[1]. 显 列 其 量. 显 列[2] == 列.", '二\n3\n真\n'),
            ('pair_callable', '算 回: 得 7. 法 对值 取 (算 回) 对 空. 显 (对值 其 囫)(). 显 对值 其 囵 == 空.', '7\n真\n'),
            ('contains_operator', "显 '甲乙' 其 含 '乙'. 形 盒: 算 含 句 为 句: 得 句. 法 象 显 (新 盒) 其 含 '好'.", '真\n好\n'),
            ('try_without_panic', "试 显 '正常'. 救 原因 显 '不应执行'. 终. 显 '之后'.", '正常\n之后\n'),
            ('nested_panic', "试 试 卒 '内'. 救 内因 显 内因. 卒 内因+'外'. 终. 救 外因 显 外因. 终. 显 '后'.", '内\n内外\n后\n'),
            ('contest_sort_panic', "竞 取 外言 '如:竞'. 原 取 [3,2,1]. 算 比 左 为 数 右 为 数: 卒 '停'. 法 试 竞 其 排序 原 (算 比). 救 原因 显 原因. 终. 显 原.", '停\n[3, 2, 1]\n'),
            ('contest_sort_closure', "竞 取 外言 '如:竞'. 算 制 方向 为 数: 算 比 左 为 数 右 为 数: 得 (左-右)*方向. 法 得 算 比. 法 显 (竞 其 排序 [3,1,2,1] (制 (-1))).", '[3, 2, 1, 1]\n'),
        ]
        for name, source, expected in cases:
            with self.subTest(name=name):
                self.compare(source, expected)

    def test_strict_minimal_hello_read_and_modulo(self):
        self.compare("显 '你好'.", '你好\n')
        self.compare('显 读.', '输入\n', stdin='输入\n')
        self.compare('显 7%3.', '1\n')

    def test_checked_io_preserves_stdout_stderr_and_input(self):
        source = "显 (读取 其 读) 其 值. 应 取 显出 其 写 内容:'甲😀'. 显 应 其 结果. 错误 其 写 内容:'诊断😀'."
        _, _, stderr = self.compare(source, '输入\n甲😀成功\n', stdin='输入\n')
        self.assertEqual(stderr, '诊断😀')

    def test_checked_filesystem_io(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory).resolve() / 'roundtrip.txt').replace('\\', '\\\\').replace("'", "\\'")
            source = f"文档 取 新 件 路径:'{path}'. 文档 其 写 '甲😀'. 显 (文档 其 读) 其 值. 显 (文档 其 除) 其 结果."
            self.compare(source, '甲😀\n成功\n')
            self.assertFalse((Path(directory).resolve() / 'roundtrip.txt').exists())

    def test_user_module_side_effects_reexports_and_unused_function_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            module = Path(directory).resolve() / 'helper.ru'
            module.write_text("显 '初始化'. 尽 取 外言 '如:竞'. 算 不用: 得 99. 法", encoding='utf-8')
            source = "模 取 外言 'helper.ru'. 显 模 其 小 2 3. 再 取 外言 'helper.ru'. 显 再 其 不用."
            graph = load_module_graph(str(Path(directory).resolve() / 'main.ru'), parse(source))
            # Loading is compile-time; neither generated executable may need
            # even this user module's source file after the graph is loaded.
            module.unlink()
            self.compare(source, '初始化\n2\n99\n', graph=graph)

    def test_runtime_errors_preserve_status_output_and_core_diagnostic(self):
        cases = [
            '显 1/0.',
            '显 [1][4].',
            "显 '此前'. 卒 '未捕获'.",
            "竞 取 外言 '如:竞'. 入 取 竞 其 扫句 '1abc'. 显 入 其 数.",
            "算 加 值 为 数: 得 值. 法 回调 取 算 加. 回调 '错'.",
            '显 __如竞 其 量.',
        ]
        for source in cases:
            with self.subTest(source=source):
                self.compare(source, success=False)


@unittest.skipUnless(CC, 'C compiler unavailable')
class P1010RuntimePruningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = FIXTURE.read_text(encoding='utf-8')
        cls.pruned = build(generate(source, '/p1010.ru'), cls.directory.name, 'pruned')
        cls.full = build(generate(source, '/p1010.ru', full=True), cls.directory.name, 'full')

    def check_result(self, result, value):
        self.assertEqual(result.returncode, 0, (value, result.stderr))
        self.assertEqual(result.stdout, p1010_oracle(value) + '\n', value)
        self.assertRegex(result.stderr, r'^RU_GC live=0 freed=\d+ collections=\d+\n$')

    def test_exact_fixture_exhaustive_one_through_twenty_thousand(self):
        # Execute the original generated program once per input. There is no
        # changed input driver, edited fixture, substituted algorithm or batch
        # harness. This exercises initialization, scanner/writer and shutdown
        # for every valid problem input, including every forced-GC lifetime.
        for value in range(1, 20001):
            self.check_result(run(self.pruned, str(value) + '\n'), value)

    def test_full_pruned_boundary_parity_and_standalone_empty_working_directory(self):
        values = set(range(33)) | {137, 1315, 19999, 20000}
        values.update(value for exponent in range(1, 15)
                      for value in ((1 << exponent) - 1, 1 << exponent, (1 << exponent) + 1)
                      if value <= 20000)
        with tempfile.TemporaryDirectory() as empty:
            for value in sorted(values):
                with self.subTest(value=value):
                    pruned = run(self.pruned, str(value) + '\n', cwd=empty)
                    full = run(self.full, str(value) + '\n', cwd=empty)
                    self.check_result(pruned, value)
                    self.check_result(full, value)
                    self.assertEqual((pruned.returncode, pruned.stdout),
                                     (full.returncode, full.stdout))
            self.assertEqual(list(Path(empty).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
