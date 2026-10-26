"""Continue is real backend control flow, not a callback/return simulation."""
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from rulang.browser_compiler import compile_browser
from rulang.cli import build
from rulang.compiler import Compiler
from rulang.frontend import parse, RuError
from rulang.interpreter import Interpreter
from rulang.js_compiler import JSCompiler
from rulang.llvm_compiler import LLVMCompiler
from rulang.llvm_toolchain import find_clang, LLVMToolchain

NODE = shutil.which('node') or shutil.which('nodejs')
CC = bool(os.environ.get('CC')) or any(shutil.which(c) for c in ('cc', 'gcc', 'clang'))
try:
    LLVM = bool(find_clang() and LLVMToolchain(find_clang()))
except RuError:
    LLVM = False


class ContinueContract:
    backend = 'python'

    def output(self, source, expected):
        if self.backend == 'python':
            out = io.StringIO()
            Interpreter(stdout=out).execute(parse(source))
            self.assertEqual(out.getvalue(), expected)
            return
        with tempfile.TemporaryDirectory(prefix='ru-continue-') as folder:
            root = Path(folder)
            if self.backend == 'browser':
                (root/'program.mjs').write_text(compile_browser(source), encoding='utf-8')
                runner = root/'run.mjs'
                runner.write_text("import create from './program.mjs';const events=[];"
                                  "create({emit:e=>events.push(e)});"
                                  "console.log(JSON.stringify(events));", encoding='utf-8')
                result = subprocess.run([NODE, str(runner)], capture_output=True, text=True,
                                        encoding='utf-8', timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(''.join(e.get('text', '') for e in json.loads(result.stdout)), expected)
            else:
                binary, _ = build(parse(source), root/'case.ru', root/'case', target=self.backend)
                command = [NODE, str(binary)] if self.backend == 'js' else [str(binary)]
                env = dict(os.environ)
                if self.backend in ('c', 'llvm'):
                    env.update(RU_GC_THRESHOLD='1', RU_GC_STATS='1')
                result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=20, env=env)
                self.assertEqual((result.returncode, result.stdout), (0, expected), result.stderr)
                if self.backend in ('c', 'llvm'):
                    self.assertRegex(result.stderr, r'^RU_GC live=0 freed=\d+ collections=\d+\s*$')
                else:
                    self.assertEqual(result.stderr, '')

    def test_counted_continue_advances_and_count_evaluated_once(self):
        self.output("算 次数: 显 'count'. 得 4. 法. 序 取 0. "
                    "循 (次数) 次 序 取 序+1. 续. 显 99. 环. 显 序.", 'count\n4\n')

    def test_infinite_and_innermost_counted_loop(self):
        self.output("外 取 0. 内 取 0. 循 外 取 外+1. 若 外 > 3 则 破. 然. "
                    "循 2 次 内 取 内+1. 续. 显 99. 环. "
                    "若 外 < 3 则 续. 然. 显 外. 环. 显 内.", '3\n6\n')

    def test_scope_cleanup_and_escaping_closure(self):
        self.output("列 取 []. 序 取 0. 循 3 次 序 取 序+1. "
                    "{ 局 取 序. 列 其 增 算: 得 局. 法. 续. } 显 99. 环. "
                    "显 列[0](). 显 列[1](). 显 列[2]().", '1\n2\n3\n')

    def test_continue_from_try_and_rescue_leaves_correct_handler(self):
        self.output("序 取 0. 试 循 4 次 序 取 序+1. "
                    "试 若 序 == 1 则 { 续. } 然. 卒 'inner'. "
                    "救 因 若 序 < 4 则 { 续. } 然. 卒 'outer'. 终. "
                    "显 99. 环. 救 因 显 因. 终. 显 序.", 'outer\n4\n')

    def test_zero_count_and_finish_are_distinct(self):
        self.output("循 0 次 续. 环. 作 停: 循 3 次 完. 环. 显 99. 为. "
                    "停. 作 报: 序 取 0. 循 3 次 序 取 序+1. 续. 环. 显 序. 为. "
                    "报. 显 'done'.", '3\ndone\n')

    def test_callback_owns_loop_and_cannot_continue_caller(self):
        self.output("[1,2] 其 逐位 回调:(作 位, 值: "
                    "循 2 次 若 值 == 1 则 续. 然. 显 值. 环. 完. 为). 显 'done'.",
                    '2\n2\ndone\n')


class ContinuePythonTests(ContinueContract, unittest.TestCase):
    pass


@unittest.skipUnless(CC, 'C compiler required')
class ContinueCTests(ContinueContract, unittest.TestCase):
    backend = 'c'


@unittest.skipUnless(NODE, 'Node.js required')
class ContinueJSTests(ContinueContract, unittest.TestCase):
    backend = 'js'


@unittest.skipUnless(NODE, 'Node.js required')
class ContinueBrowserTests(ContinueContract, unittest.TestCase):
    backend = 'browser'


@unittest.skipUnless(LLVM, 'LLVM 14 toolchain required')
class ContinueLLVMTests(ContinueContract, unittest.TestCase):
    backend = 'llvm'


class ContinueLoweringTests(unittest.TestCase):
    def test_llvm_counted_continue_targets_increment(self):
        ir = LLVMCompiler(parse('循 3 次 续. 环.')).compile()
        self.assertRegex(ir, r'br label %loop_increment\d+')
        self.assertRegex(ir, r'loop_increment\d+:\n(?:.*\n)*?  .* = add i64 .*?, 1\n')

    def test_llvm_infinite_continue_targets_header(self):
        ir = LLVMCompiler(parse('循 续. 环.')).compile()
        self.assertNotIn('loop_increment', ir)
        self.assertGreaterEqual(len(re.findall(r'br label %loop_check\d+', ir)), 2)

    def test_c_releases_exited_scopes_before_continue(self):
        c = Compiler(parse('循 2 次 { 续. } 环.')).compile()
        self.assertRegex(c, r'env_free\(ru_scope_env_\d+\);\s+continue;')

    def test_invalid_cross_function_continue_rejected_by_every_compiler(self):
        sources = ('续.', '循 2 次 作 错: 续. 为. 环.',
                   '循 2 次 回 取 作: 续. 为. 环.')
        for source in sources:
            for compiler in (Compiler, JSCompiler, LLVMCompiler):
                with self.subTest(source=source, compiler=compiler.__name__), self.assertRaises(RuError):
                    compiler(parse(source)).compile()


# Keep native fixture loading in the child executables/interpreter. The parent
# only compiles the DLL, so Windows can remove it after the children have exited.
import test_native_c_backend as native_acceptance
import llvm_callback_cases as llvm_acceptance


class ContinueNativeContract:
    callbacks = native_acceptance.NativeCWindowsAcceptanceTests.callbacks
    program = native_acceptance.NativeCWindowsAcceptanceTests.program

    def test_native_callback_continue_preserves_frame_and_outer_loop(self):
        body = self.callbacks() + """
回 取 密 其 回调 签 (算 值:
    序 取 0. 总 取 [0].
    循 4 次
        序 取 序+1.
        试
            若 序 == 1 则 { 续. } 然.
            若 序 == 2 则 卒 'skip'. 然.
            总[0] 取 总[0]+(确认 (回声 其 调用 [序])) 其 数.
        救 因
            { 续. }
        终.
    环.
    得 总[0]+(值 其 数).
法) (-7).
循 2 次
    果 取 原生调 其 调用 [回,10].
    断言 ((果 其 回调错误) == 空) '续逃出回调'.
    显 (果 其 值) 其 数.
    断言 (非 (密 其 回调中)) '回调深度未恢复'.
环.
显 (确认 (返回数 其 调用 [])) 其 数.
显 (确认 (回声 其 调用 [19])) 其 数.
回 其 关闭.
显 'clean'.
"""
        self.assert_native_parity(body, '17\n17\n2\n19\nclean\n')


@unittest.skipUnless(native_acceptance.WINDOWS_X64, 'real Windows x64 native callback required')
class ContinueNativeCTests(ContinueNativeContract, native_acceptance.NativeExecutableMixin, unittest.TestCase):
    assert_native_parity = native_acceptance.NativeCWindowsAcceptanceTests.assert_native_parity

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.fixture = Path(directory.name)/'continue-bridge.dll'
        result = native_acceptance.bounded_run([*cls.compiler, '-std=c99', '-shared', '-O2',
            '-Wall', '-Wextra', '-Werror', '-pedantic',
            str(native_acceptance.ROOT/'tests/fixtures/native/c_backend_bridge.c'),
            '-o', str(cls.fixture)], timeout=90)
        if result.returncode:
            raise AssertionError(result.stderr)


@unittest.skipUnless(native_acceptance.WINDOWS_X64 and LLVM, 'real Windows x64 LLVM 14 callback required')
class ContinueNativeLLVMTests(ContinueNativeContract, unittest.TestCase):
    build_executable = llvm_acceptance.LLVMCallbackTests.build_executable
    run_executable = llvm_acceptance.LLVMCallbackTests.run_executable
    assert_native_parity = llvm_acceptance.LLVMCallbackTests.assert_native_parity

    @classmethod
    def setUpClass(cls):
        llvm_acceptance.LLVMCallbackTests.setUpClass.__func__(cls)
