"""C binding-cache semantics and standalone contest source budgets."""
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from rulang.compiler import Compiler
from rulang.frontend import parse
from rulang.interpreter import Interpreter
from rulang.modules import load_module_graph
from test_runtime_pruning import CC, ROOT, run


class UncachedCompiler(Compiler):
    _cache_local_bindings = False


def build(code, directory, name):
    source = Path(directory)/(name+'.c')
    binary = Path(directory)/(name+('.exe' if os.name == 'nt' else ''))
    source.write_text(code, encoding='utf-8', newline='\n')
    command = [CC, '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
               '-Wno-unused-function', '-pedantic', str(source), '-o', str(binary)]
    if os.name == 'nt':
        command += ['-D_CRT_SECURE_NO_WARNINGS']
    else:
        command += ['-lm']
    result = subprocess.run(command, capture_output=True, timeout=60)
    if result.returncode:
        raise AssertionError((result.stdout+result.stderr).decode('utf-8', errors='replace'))
    return binary


SOURCE = """
值 取 10.
算 局部:
 显 值. 值 取 ['local']. 显 值.
 算 改: 值 取 ['changed']. 得 值. 法.
 显 改(). 显 值.
 循 3 次
  段: 值 取 ['block']. 显 值. 落.
  试 卒 'caught'. 救 原因 值 取 [原因]. 显 值. 终.
  显 值.
 环.
 得 算: 得 值. 法.
法.
留 取 局部(). 显 值.
循 30 次 垃圾 取 ['pressure',[]]. 环.
显 留().
算 递归 数值:
 若 数值 == 0 则 得 0. 然.
 下 取 递归 (数值-1). 得 下+数值.
法.
显 (递归 12).
算 外:
 项 取 1.
 算 内: 显 项. 项 取 项+1. 显 项. 得 项. 法.
 显 内(). 显 项. 得 算 内.
法.
变 取 外(). 显 变().
算 重入 回调 数值:
 若 数值 == 0 则 得 ['end']. 然.
 本地 取 [数值]. 丢 取 回调 回调 (数值-1). 得 本地.
法.
显 (重入 (算 重入) 20).
"""


def generate(source, compiler=Compiler, full=False):
    graph = load_module_graph('/c-bindings.ru', parse(source))
    return compiler(graph[graph.root], graph.root, modules=graph,
                    full_runtime=full).compile()


class CBindingSourceTests(unittest.TestCase):
    def test_unused_cache_support_does_not_grow_existing_sources(self):
        for source in ['显 1.', '值 取 1. 值 取 值+1. 显 值.',
                       '算 一次 值: 得 值. 法. 显 (一次 7).',
                       '算 看: 段: 值 取 1. 显 值+值. 落. 得 0. 法. 显 看().',
                       '算 外 起: 值 取 起. 算 内: 值 取 值+1. 得 值. 法. '
                       '得 算 内. 法. 闭包 取 外 0. 显 闭包().']:
            with self.subTest(source=source):
                cached = generate(source)
                self.assertEqual(cached, generate(source, UncachedCompiler))
                self.assertNotIn('RuBindingCache', cached)

    def test_frequency_stays_within_64k_without_pointless_parameter_caches(self):
        source = (ROOT/'tests/fixtures/contest/frequency.ru').read_text(encoding='utf-8')
        graph = load_module_graph('/frequency.ru', parse(source))
        output = Compiler(graph[graph.root], graph.root, modules=graph,
            source_prefix_maps=[graph.root+'=/frequency.ru',
                                str(ROOT/'rulang/stdlib')+'=/ru/stdlib']).compile()
        self.assertLess(len(output.encode('utf-8')), 65536)
        self.assertNotIn('RuBindingCache', output)


@unittest.skipUnless(CC, 'C compiler required')
class CBindingExecutionTests(unittest.TestCase):
    def test_mutation_shadowing_captures_recursion_and_reentry_with_gc(self):
        output = io.StringIO()
        Interpreter(io.StringIO(), output).execute(parse(SOURCE))
        with tempfile.TemporaryDirectory() as temporary:
            for full in (False, True):
                with self.subTest(full=full):
                    code = generate(SOURCE, full=full)
                    self.assertIn('env_cget(env, &ru_b', code)
                    self.assertIn('env_cbind(env, &ru_b', code)
                    result = run(build(code, temporary, 'bindings'))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, output.getvalue())
                    self.assertRegex(result.stderr, r'^RU_GC live=0 freed=\d+ collections=\d+\s*$')

    def test_reserved_names_and_missing_values_keep_original_diagnostics(self):
        sources = [
            "尽取 外言 '如:竞'. 算 测: 小 取 1. 小 取 2. 得 0. 法. 显 测().",
            '算 测: 显 值. 值 取 1. 得 值. 法. 显 测().',
        ]
        with tempfile.TemporaryDirectory() as temporary:
            for index, source in enumerate(sources):
                results = []
                for compiler in (UncachedCompiler, Compiler):
                    code = generate(source, compiler)
                    binary = build(code, temporary, 'failure')
                    result = subprocess.run([str(binary)], capture_output=True,
                        text=True, encoding='utf-8', timeout=15, env=os.environ.copy())
                    results.append((result.returncode, result.stdout, result.stderr))
                with self.subTest(case=index):
                    self.assertNotEqual(results[0][0], 0)
                    self.assertEqual(results[0], results[1])

    def test_escaped_values_and_panic_cleanup(self):
        source = """
算 制 值:
 局部 取 [值].
 试
  局部 取 ['kept',局部].
  卒 'reason'.
 救 原因
  得 算: 得 [局部,原因]. 法.
 终.
法.
闭包 取 制 ['root'].
循 50 次 废 取 ['gc',[]]. 环.
显 闭包().
"""
        with tempfile.TemporaryDirectory() as temporary:
            result = run(build(generate(source), temporary, 'escape'))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '[[kept, [[root]]], reason]\n')
            self.assertIn('RU_GC live=0 ', result.stderr)
