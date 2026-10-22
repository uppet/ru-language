"""Direct LLVM code generation, private ABI, ownership and CLI publication."""
import contextlib
import io
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rulang.cli import build, main
from rulang.compiler import Compiler
from rulang.frontend import RuError, node, parse
from rulang.llvm_compiler import LLVMCompiler
from rulang.llvm_toolchain import LLVMToolchain, find_clang, tool_error
from rulang.modules import load_module_graph
from rulang.toolchain_environment import llvm_environment
from test_elif import ElifContract

ROOT = Path(__file__).resolve().parents[1]
LLVM_CLANG = find_clang()
try:
    HAS_LLVM = bool(LLVM_CLANG and LLVMToolchain(LLVM_CLANG))
except RuError:
    HAS_LLVM = False


class LLVMValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'main.ru'
        self.source.write_text('显 1.', encoding='utf-8')

    def test_direct_lowering_does_not_invoke_c_codegen_or_external_tools(self):
        program = parse('算 平方 值 为 数: 得 值*值. 法. 显 (平方 9).')
        with patch.object(Compiler, 'compile', side_effect=AssertionError('AST to C invoked')), \
                patch('subprocess.run', side_effect=AssertionError('external tool invoked')):
            ir = LLVMCompiler(program).compile()
            self.assertIn('define void @ru_function_', ir)
            self.assertIn('call void @rul_binary', ir)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['check', str(self.source), '--target', 'llvm']), 0)

    def test_unknown_ast_is_rejected_even_in_dead_code(self):
        program = parse('若 假 则 显 1. 然.')
        program[0].data['yes'].append(node('future_syntax', program[0].token))
        with self.assertRaisesRegex(RuError, 'LLVM AOT 尚不支持语法节点') as caught:
            LLVMCompiler(program).compile()
        self.assertEqual(caught.exception.line, 1)

    def test_invalid_calls_in_dead_code_keep_source_location(self):
        with self.assertRaisesRegex(RuError, '未定义函数') as caught:
            LLVMCompiler(parse('若 假 则\n  未知 1.\n然.')).compile()
        self.assertEqual((caught.exception.line, caught.exception.col), (2, 3))

    def test_native_and_graphics_are_explicitly_rejected(self):
        for source in ("密 取 外言 '如:密'.", "图 取 外言 '如:观'."):
            with self.subTest(source=source), self.assertRaises(RuError):
                LLVMCompiler(parse(source)).compile()

    def test_argument_options_rejected_before_reading_sources(self):
        commands = [
            ['build', 'missing.ru', '--target', 'c', '--emit-llvm', 'out.ll'],
            ['build', 'missing.ru', '--target', 'js', '--llvm-clang', 'clang-14'],
        ]
        for option in ('--allow-native', '--emit-c', '--cc', '--source-prefix-map'):
            command = ['build', 'missing.ru', '--target', 'llvm', option]
            if option != '--allow-native':
                command.append('unused')
            commands.append(command)
        for command in commands:
            with self.subTest(command=command), patch('rulang.cli.read_source', side_effect=AssertionError('read')), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main(command)
            self.assertEqual(caught.exception.code, 2)

    def test_output_paths_cannot_alias_root_dependency_or_each_other(self):
        dependency = self.root/'child.ru'
        dependency.write_text('值 取 2.', encoding='utf-8')
        text = "模 取 外言 'child.ru'. 显 模 其 值."
        self.source.write_text(text, encoding='utf-8')
        graph = load_module_graph(self.source)
        output = self.root/'program'
        alias = self.root/'alias.ll'
        pairs = [(self.source,None),(dependency,None),(output,self.source),
                 (output,dependency),(output,output)]
        try:
            alias.symlink_to(dependency)
        except OSError:
            pass  # Windows may require privileges; ordinary aliases still run.
        else:
            pairs.append((output,alias))
        for native, ir in pairs:
            with self.subTest(native=native, ir=ir), patch('subprocess.run', side_effect=AssertionError('tools')), \
                    self.assertRaises(RuError):
                build(graph[graph.root], self.source, native, modules=graph, target='llvm', emit_llvm=ir)
        self.assertEqual(self.source.read_text(encoding='utf-8'), text)
        self.assertEqual(dependency.read_text(encoding='utf-8'), '值 取 2.')

    def test_compile_and_style_failures_preserve_both_outputs(self):
        binary, ir = self.root/'program', self.root/'program.ll'
        binary.write_bytes(b'previous binary')
        ir.write_bytes(b'previous IR')
        for source, extra in (('未知 1.', {}), ('显 1.', {'clang':'missing-llvm-clang'})):
            with self.subTest(source=source), self.assertRaises(RuError):
                from rulang.llvm_toolchain import build_llvm
                program = parse(source)
                graph = load_module_graph(self.source, program)
                build_llvm(program, self.source, binary, modules=graph, emit_llvm=ir, **extra)
            self.assertEqual(binary.read_bytes(), b'previous binary')
            self.assertEqual(ir.read_bytes(), b'previous IR')
        self.source.write_text('若 真 则 显 1. 然', encoding='utf-8')
        with patch('subprocess.run', side_effect=AssertionError('tools')), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['build',str(self.source),'--target','llvm','--strict-style',
                                   '-o',str(binary),'--emit-llvm',str(ir)]),1)
        self.assertEqual(binary.read_bytes(), b'previous binary')
        self.assertEqual(ir.read_bytes(), b'previous IR')
        self.assertEqual(list(self.root.glob('.ru-build-*')), [])

    def test_llvm_tool_failures_are_diagnostics_not_tracebacks(self):
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('llvm-as',120)), \
                self.assertRaisesRegex(RuError, '120 秒'):
            LLVMToolchain.run(['llvm-as-14'])
        with patch('subprocess.run', return_value=subprocess.CompletedProcess(['opt'],1,'','invalid IR')), \
                self.assertRaisesRegex(RuError, 'invalid IR'):
            LLVMToolchain.run(['opt-14'])

    def test_wrong_version_or_platform_is_not_silently_accepted(self):
        with patch('rulang.llvm_toolchain.sys.platform','linux'), \
                patch('rulang.llvm_toolchain.platform.machine',return_value='x86_64'), \
                patch.object(LLVMToolchain,'run',return_value='clang version 18.0.0'), \
                self.assertRaisesRegex(RuError,'LLVM 14'):
            LLVMToolchain('clang')
        def run(command, input=None):
            if '-emit-llvm' in command:
                return 'target triple = "aarch64-apple-darwin"\ntarget datalayout = "e"\n'
            return 'clang version 14.0.0\nLLVM version 14.0.0'
        with patch('rulang.llvm_toolchain.sys.platform','linux'), \
                patch('rulang.llvm_toolchain.platform.machine',return_value='x86_64'), \
                patch.object(LLVMToolchain,'run',side_effect=run), patch('shutil.which',return_value='/tools/llvm-tool'), \
                self.assertRaisesRegex(RuError,'x86-64'):
            LLVMToolchain('clang')

    def test_unsupported_host_reports_platform_before_tools_and_preserves_outputs(self):
        binary, ir = self.root/'program', self.root/'program.ll'
        binary.write_bytes(b'previous binary')
        ir.write_bytes(b'previous IR')
        for host, machine in (('win32','ARM64'), ('darwin','arm64'), ('linux','aarch64')):
            error = io.StringIO()
            with self.subTest(host=host, machine=machine), \
                    patch('rulang.llvm_toolchain.sys.platform',host), \
                    patch('rulang.llvm_toolchain.platform.machine',return_value=machine), \
                    patch('shutil.which',side_effect=AssertionError('tool search')), \
                    patch('subprocess.run',side_effect=AssertionError('tool execution')), \
                    contextlib.redirect_stderr(error):
                self.assertEqual(main(['build',str(self.source),'--target','llvm',
                                       '-o',str(binary),'--emit-llvm',str(ir)]),1)
                self.assertIn('Linux/Windows x86-64',error.getvalue())
                self.assertEqual(binary.read_bytes(),b'previous binary')
                self.assertEqual(ir.read_bytes(),b'previous IR')
                self.assertEqual(list(self.root.glob('.ru-build-*')),[])


@unittest.skipUnless(HAS_LLVM, 'LLVM 14 Linux/Windows x86-64 toolchain required')
class LLVMExecutionTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'Windows SDK environment regression')
    def test_posix_include_and_library_lists_do_not_hide_windows_sdk(self):
        foreign = {'INCLUDE': 'c:/msys64/usr/include/:c:/msys64/include/:',
                   'LIB': 'c:/msys64/usr/lib/:', 'CPATH': '/usr/include:/mingw64/include'}
        source, binary = "显 'Windows SDK😀'.", self.root/'program.exe'
        self.source.write_text(source, encoding='utf-8')
        with patch.dict(os.environ, foreign):
            build(parse(source), self.source, binary, target='llvm')
            for name, value in foreign.items():
                self.assertEqual(os.environ[name], value)
        result = subprocess.run([str(binary)], capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual((result.returncode, result.stdout), (0, 'Windows SDK😀\n'), result.stderr)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'main.ru'
        self.counter = 0

    def run_source(self, source, *, stdin='', args=(), env=None, target='llvm'):
        self.source.write_text(source, encoding='utf-8')
        self.counter += 1
        binary, _ = build(parse(source), self.source, self.root/f'program-{self.counter}.exe', target=target)
        result = subprocess.run([str(binary),*args],input=stdin,capture_output=True,text=True,
                                cwd=self.root,env=env,timeout=20)
        return result

    def test_numeric_truth_unicode_and_short_circuit(self):
        source = """
显 0 为 事实. 显 '' 为 事实. 显 [] 为 事实. 显 {} 为 事实.
显 空 == 假. 显 真 == 1. 显 (-7)%3. 显 -0.
显 假 且 (1/0). 显 真 或 (1/0). 显 空 或 9.
文 取 '甲😀é乙'. 显 文 其 量. 显 文[1]. 显 文[1:3].
显 9007199254740991. 显 1.0000000000000002 == 1.
"""
        result = self.run_source(source)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'真\n真\n真\n真\n假\n假\n-1\n-0\n假\n真\n真\n4\n😀\n😀é\n9.00719925474099e+15\n假\n')

    def test_closures_scopes_recursion_and_named_evaluation_order(self):
        source = """
算 阶乘 值 为 数:
 若 值 <= 1 则 得 1. 然.
 得 值*(阶乘 (值-1)).
法.
算 造 起点:
 数值 取 起点.
 算 增加 步: 数值 取 数值+步. 得 数值. 法.
 得 算 增加.
法.
算 报 值: 显 值. 得 值. 法.
算 合 左 右: 得 左*10+右. 法.
显 (阶乘 6). 甲 取 造 1. 乙 取 造 10.
显 (甲 2). 显 (乙 3). 显 (甲 4).
显 (合 右:(报 2) 左:(报 1)).
容器 取 [空]. 段: 值 取 5. 容器[0] 取 算: 得 值. 法. 落.
显 容器[0]().
"""
        result = self.run_source(source,env={**os.environ,'RU_GC_THRESHOLD':'1'})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'720\n3\n13\n7\n2\n1\n12\n5\n')

    def test_loops_unwinding_and_panic_suppresses_later_arguments(self):
        source = """
算 坏: 卒 '停止'. 法.
算 后: 显 '不应执行'. 得 9. 法.
算 合 左 右: 得 左+右. 法.
计数 取 0.
循 4 次
 段:
  试:
   若 计数 == 1 则 破. 然.
   计数 取 计数+1.
  救 原因: 显 原因. 终.
 落.
 计数 取 计数+1.
环.
显 计数.
试: 显 (合 (坏()) (后())). 救 原因: 显 原因. 终.
作 提前: 段: 试: 完. 救 原因: 显 原因. 终. 落. 为.
提前. 显 '完成'.
"""
        llvm = self.run_source(source,env={**os.environ,'RU_GC_THRESHOLD':'1','RU_GC_STATS':'1'})
        c = self.run_source(source,target='c')
        self.assertEqual((llvm.returncode,llvm.stdout),(c.returncode,c.stdout))
        self.assertEqual(llvm.returncode,0,llvm.stderr)
        self.assertNotIn('不应执行',llvm.stdout)
        self.assertIn('live=0',llvm.stderr)

    def test_objects_maps_callbacks_and_cycles_under_gc_pressure(self):
        source = """
形 点:
 值 为 数.
 算 同 另一: 得 其 值 == 另一 其 值. 法.
 算 印: 得 其 值. 法.
象.
表 取 {}. 甲 取 新 点 值:3. 乙 取 新 点 值:3.
表 其 增 甲 '同键'. 显 表[乙].
阵列 取 [3,1,2]. 新列 取 阵列 其 排序. 显 新列.
算 双倍 值: 得 值*2. 法.
显 新列 其 另成 (算 双倍).
自环 取 []. 自环 其 增 自环. 显 自环.
"""
        result = self.run_source(source,env={**os.environ,'RU_GC_THRESHOLD':'1','RU_GC_STATS':'1'})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'同键\n[1, 2, 3]\n[2, 4, 6]\n[<循环>]\n')
        self.assertIn('live=0',result.stderr)

    def test_receiver_is_selected_before_argument_mutates_it(self):
        source = """
形 报告: 算 合 值: 得 值+10. 法. 象.
对象 取 新 报告. 容器 取 [对象].
算 改: 容器[0] 取 空. 得 2. 法.
显 容器[0] 其 合 (改()).
"""
        result = self.run_source(source)
        self.assertEqual((result.returncode,result.stdout),(0,'12\n'),result.stderr)

    def test_invalid_assignment_does_not_evaluate_rhs(self):
        result = self.run_source("算 副作用: 显 '错误副作用'. 得 3. 法. 列 取 []. 列[0] 取 副作用.")
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stdout,'')
        self.assertIn('main.ru',result.stderr)

    def test_runtime_errors_and_entry_arguments(self):
        for value, fragment in (('1/0','除数不能为零'),('1e308*1e308','有限'),("假+1",'数字')):
            with self.subTest(value=value):
                result = self.run_source('显 '+value+'.')
                self.assertNotEqual(result.returncode,0)
                self.assertIn(fragment,result.stderr)
        source = "算 元初 参数 为 句 阵: 显 参数[0]. 显 参数[1]. 得 7. 法."
        result = self.run_source(source,args=('如😀','--flag'))
        self.assertEqual((result.returncode,result.stdout),(7,'如😀\n--flag\n'))

    def test_modules_initialize_lazily_once_and_cache_failure(self):
        (self.root/'child.ru').write_text("显 '初始化'. 值 取 4. 卒 '模块失败'.",encoding='utf-8')
        source = """
若 假 则 模 取 外言 'child.ru'. 然.
循 2 次
 试: 模 取 外言 'child.ru'. 救 原因: 显 原因. 终.
环.
"""
        result = self.run_source(source,env={**os.environ,'RU_GC_THRESHOLD':'1'})
        self.assertEqual((result.returncode,result.stdout),(0,'初始化\n模块失败\n模块失败\n'),result.stderr)

    def test_binary_and_saved_ir_are_independent_of_project_and_sources(self):
        child = self.root/'child.ru'
        child.write_text("值 取 '独立运行😀'.",encoding='utf-8')
        text = "模 取 外言 'child.ru'. 显 模 其 值."
        self.source.write_text(text,encoding='utf-8')
        ir, binary = self.root/'saved.ll', self.root/'native.exe'
        with patch.object(Compiler,'compile',side_effect=AssertionError('C codegen invoked')):
            build(parse(text),self.source,binary,target='llvm',emit_llvm=ir)
        self.source.unlink(); child.unlink()
        clean = self.root/'empty'; clean.mkdir()
        environment = {**os.environ,'PATH':''}
        result = subprocess.run([str(binary)],capture_output=True,text=True,cwd=clean,env=environment,timeout=10)
        self.assertEqual((result.returncode,result.stdout),(0,'独立运行😀\n'),result.stderr)
        content = binary.read_bytes()
        if sys.platform == 'win32':
            self.assertEqual(content[:2],b'MZ')
            offset = int.from_bytes(content[60:64], 'little')
            self.assertEqual(content[offset:offset+4],b'PE\0\0')
        else:
            self.assertEqual(content[:4],b'\x7fELF')
        relinked = clean/'relinked.exe'
        flags = [] if sys.platform == 'win32' else ['-lm']
        result = subprocess.run([LLVM_CLANG,str(ir),'-o',str(relinked),*flags],capture_output=True,text=True,
                                cwd=clean,env=llvm_environment(),timeout=120)
        self.assertEqual(result.returncode,0,result.stderr)
        result = subprocess.run([str(relinked)],capture_output=True,text=True,cwd=clean,env=environment,timeout=10)
        self.assertEqual((result.returncode,result.stdout),(0,'独立运行😀\n'),result.stderr)

    def test_tool_failure_preserves_existing_binary_and_ir(self):
        binary, ir = self.root/'native', self.root/'saved.ll'
        binary.write_bytes(b'old binary'); ir.write_bytes(b'old IR')
        original = LLVMToolchain.run
        for stage in ('llvm-as', 'llvm-link', 'opt', 'llvm-dis', 'llc', 'program.exe'):
            def failing(command, input=None):
                if stage in str(command[0]) and '--version' not in command:
                    raise tool_error('injected failure')
                if stage == 'program.exe' and any(Path(str(part)).name == 'program.exe' for part in command):
                    raise tool_error('injected failure')
                return original(command,input=input)
            with self.subTest(stage=stage), patch.object(LLVMToolchain,'run',side_effect=failing), self.assertRaises(RuError):
                build(parse('显 1.'),self.source,binary,target='llvm',emit_llvm=ir)
            self.assertEqual(binary.read_bytes(),b'old binary')
            self.assertEqual(ir.read_bytes(),b'old IR')
            self.assertEqual(list(self.root.glob('.ru-build-*')),[])

    def test_malformed_ir_is_rejected_by_real_assembler_before_publication(self):
        binary, ir = self.root/'native', self.root/'saved.ll'
        binary.write_bytes(b'old binary'); ir.write_bytes(b'old IR')
        original = LLVMCompiler.compile
        def malformed(compiler, *args, **kwargs):
            return original(compiler,*args,**kwargs).replace('ret i32 %status','ret i64 %status')
        with patch.object(LLVMCompiler,'compile',malformed), self.assertRaisesRegex(RuError,'llvm-as'):
            build(parse('显 1.'),self.source,binary,target='llvm',emit_llvm=ir)
        self.assertEqual(binary.read_bytes(),b'old binary')
        self.assertEqual(ir.read_bytes(),b'old IR')

    def test_cli_build_in_unicode_paths_and_explicit_clang(self):
        self.source.write_text("显 '命令行😀'.",encoding='utf-8')
        binary, ir = self.root/'路径 空格'/'程序.exe', self.root/'路径 空格'/'程序.ll'
        command=[sys.executable,str(ROOT/'ru'),'build',str(self.source),'--target','llvm',
                 '--llvm-clang',LLVM_CLANG,'-o',str(binary),'--emit-llvm',str(ir)]
        result=subprocess.run(command,capture_output=True,text=True,timeout=120)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('LLVM 工具链',result.stdout)
        self.assertTrue(ir.exists())
        result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
        self.assertEqual((result.returncode,result.stdout),(0,'命令行😀\n'),result.stderr)

    def test_imported_compile_error_retains_dependency_source(self):
        child=self.root/'child.ru'
        child.write_text('显 1.\n未知 2.',encoding='utf-8')
        self.source.write_text("模 取 外言 'child.ru'.",encoding='utf-8')
        error=io.StringIO()
        with contextlib.redirect_stderr(error):
            status=main(['check',str(self.source),'--target','llvm'])
        self.assertEqual(status,1)
        self.assertIn(str(child)+':2:1',error.getvalue())
        self.assertIn('未知 2.',error.getvalue())

    def test_instrumented_runtime_is_not_instrumented_twice_at_native_codegen(self):
        clang=LLVM_CLANG
        resource=subprocess.run([clang,'--print-resource-dir'],capture_output=True,text=True,check=True).stdout.strip()
        if not (Path(resource)/'lib/linux/libclang_rt.asan-x86_64.a').exists():
            self.skipTest('Clang 14 ASan runtime not installed')
        source="""算 造: 值 取 1. 算 加: 值 取 值+1. 得 值. 法. 得 算 加. 法.
计 取 造. 列 取 []. 列 其 增 列.
循 100 次 表 取 {'环':列,'值':(计())}. 试: 卒 '恢复'. 救 原因: 显 原因. 终. 环.
显 计().
"""
        self.source.write_text(source,encoding='utf-8')
        binary=self.root/'sanitized'
        # Clang 14's ASan PIE startup also intermittently segfaults for an
        # empty C main on this WSL host. Use a fixed image for this runtime
        # regression; normal builds keep the toolchain's default PIE policy.
        build(parse(source),self.source,binary,target='llvm',
              llvm_clang=clang+' -fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie')
        result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30,
                              env={**os.environ,'RU_GC_THRESHOLD':'1','RU_GC_STATS':'1'})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'恢复\n'*100+'102\n')
        self.assertIn('live=0',result.stderr)


@unittest.skipUnless(HAS_LLVM, 'LLVM 14 toolchain required')
class LLVMElifTests(ElifContract, unittest.TestCase):
    backend = 'llvm'


if __name__ == '__main__':
    unittest.main()
