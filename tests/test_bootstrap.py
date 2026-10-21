"""Real native Ru self-compilation, source processing and artifact protection."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rulang.frontend import RuError
from rulang.llvm_toolchain import LLVMToolchain
from rulang.toolchain_environment import llvm_environment
from tools.bootstrap import ROOT, bootstrap, compile_native, digest

try:
    TOOLCHAIN = LLVMToolchain()
except RuError:
    TOOLCHAIN = None

_STAGES = None


def prepared_stages():
    """Build once per process; all three classes share the frozen generation."""
    global _STAGES
    if _STAGES is None:
        temporary = tempfile.TemporaryDirectory(prefix='ru-selfhost-')
        unittest.addModuleCleanup(temporary.cleanup)
        directory = Path(temporary.name)/'stages'
        with contextlib.redirect_stdout(io.StringIO()):
            report = bootstrap(directory)
        _STAGES = directory, report
    return _STAGES


class BootstrapTests(unittest.TestCase):
    stage_number = 3

    @classmethod
    def setUpClass(cls):
        if TOOLCHAIN is None:
            raise unittest.SkipTest('LLVM 14 Linux/Windows x86-64 toolchain required')
        cls.directory, cls.report = prepared_stages()
        suffix = '.exe' if sys.platform == 'win32' else ''
        cls.compiler = cls.directory/('stage'+str(cls.stage_number)+suffix)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=self.directory)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root/'输入 程序😀.ru'
        self.binary, self.ir = self.root/'program.exe', self.root/'program.ll'

    def build(self, source):
        self.source.write_text(source, encoding='utf-8')
        # The later-stage driver must not quietly fall back to a host frontend.
        with patch('rulang.cli.build', side_effect=AssertionError('Python stage0 build')), \
                patch('rulang.frontend.parse', side_effect=AssertionError('Python parser')), \
                patch('rulang.compiler.Compiler.compile', side_effect=AssertionError('C frontend')), \
                patch('rulang.llvm_compiler.LLVMCompiler.compile', side_effect=AssertionError('Python LLVM frontend')), \
                patch('rulang.modules.load_module_graph', side_effect=AssertionError('Python module loader')):
            compile_native(self.compiler, self.source, self.binary, TOOLCHAIN, emit_llvm=self.ir)

    def run_program(self, *, arguments=(), input='', stress=False):
        environment = {**os.environ, 'PATH':''}
        if stress:
            environment.update(RU_GC_THRESHOLD='1', RU_GC_STATS='1')
        return subprocess.run([str(self.binary), *arguments], input=input, cwd=self.root,
                              env=environment, capture_output=True, text=True, encoding='utf-8', timeout=30)

    def test_self_compilation_reaches_exact_native_frontend_fixed_point(self):
        self.assertTrue(self.report['fixed_point'])
        first, second = self.report['stages']
        for key in ('source_ir_sha256', 'metadata_sha256'):
            self.assertEqual(first[key], second[key])
        self.assertEqual(self.report['source_sha256'], digest((ROOT/'bootstrap/compiler.ru').read_bytes()))
        content = self.compiler.read_bytes()
        self.assertEqual(content[:2] if sys.platform == 'win32' else content[:4],
                         b'MZ' if sys.platform == 'win32' else b'\x7fELF')

    def test_numeric_precision_truth_unicode_and_containers(self):
        self.build("""
显 9007199254740993 == 9007199254740992.
显 1e-324 == 0. 显 3.141592653589793 > 3.14159265358979.
显 1.7976931348623157e308 == 1.7976931348623158e308.
显 0e999999999999999999999 == 0. 显 1e-999999999999999999999 == 0. 显 5e-324 > 0.
显 (0 为 事实). 显 非 空.
文 取 '甲😀é'. 显 文 其 量. 显 文[1:3].
表 取 {'甲':1,'乙':2}. 表 其 增 '甲' 7. 显 表['甲'].
列 取 [1,2]. 列[0] 取 9. 显 列.
""")
        result = self.run_program(stress=True)
        self.assertEqual((result.returncode, result.stdout),
                         (0, '真\n'*9+'3\n😀é\n7\n[9, 2]\n'), result.stderr)
        self.assertIn('live=0', result.stderr)

    def test_closures_recursion_and_argument_evaluation_order(self):
        self.build("""
算 阶乘 值: 若 值 <= 1 则 得 1. 然. 得 值*(阶乘 (值-1)). 法.
算 造:
 值 取 0. 算 加: 值 取 值+1. 得 值. 法. 得 算 加.
法.
算 示 值: 显 值. 得 值. 法.
算 差 左 右: 得 左-右. 法.
计 取 造. 显 计(). 显 计(). 显 阶乘 6.
显 差 右:(示 1) 左:(示 2).
列 取 [1,2,3]. 显 列 其 另成 算 值: 得 值*2. 法.
盒 取 [空].
段:
 值 取 9. 算 局递 次数: 若 次数 == 0 则 得 值. 然. 得 局递 (次数-1). 法.
 盒[0] 取 算 局递.
落.
显 (盒[0]) 2.
""")
        result = self.run_program(stress=True)
        self.assertEqual((result.returncode,result.stdout),(0,'1\n2\n720\n1\n2\n1\n[2, 4, 6]\n9\n'),result.stderr)
        self.assertIn('live=0',result.stderr)

    def test_objects_inheritance_and_shared_identity(self):
        self.build("""
形 基础:
 值 为 数. 算 加 增量: 得 其 值+增量. 法.
 算 取算: 得 算: 得 其 值. 法. 法.
象.
形 派生 如 基础:
 名 为 句. 算 加 增量: 得 其 值+增量+1. 法.
 算 取算: 得 算: 得 其 值+1. 法. 法.
象.
物 取 新 派生 值:4 名:'😀'. 另名 取 物. 另名 其 值 取 7.
显 物 其 名. 显 物 其 加 2.
回 取 物 其 取算. 显 回().
""")
        result = self.run_program(stress=True)
        self.assertEqual((result.returncode,result.stdout),(0,'😀\n10\n8\n'),result.stderr)

    def test_callable_reference_ambiguity_comments_and_reexports(self):
        (self.root/'base.ru').write_text('算 加 值: 得 值+1. 法.',encoding='utf-8')
        (self.root/'facade.ru').write_text("尽取 外言 'base.ru'.",encoding='utf-8')
        self.build("""﻿
批。 注释里的 算 假名: 显 '错误'. 法.
解。 ‘带引号的注释’ 释。
尽取 外言 'facade.ru'.
显 算 加 值:4.
显（加 5）。
显 '😀\\n甲'.
算 吾 值: 显 值. 得 值. 法. 言 取 9. 吾 言.
""")
        result = self.run_program(stress=True)
        self.assertEqual((result.returncode,result.stdout),(0,'5\n6\n😀\n甲\n9\n'),result.stderr)

    def test_lazy_modules_failure_cache_scope_and_panic(self):
        (self.root/'child.ru').write_text("显 '初始化'. 卒 '模块失败'.",encoding='utf-8')
        self.build("""
若 假 则 模 取 外言 'child.ru'. 然.
循 2 次 试: 模 取 外言 'child.ru'. 救 原因: 显 原因. 终. 环.
值 取 3. 段: 值 取 4. 显 值. 落. 显 值.
循 4 次 试: 卒 '恢复'. 救 原因: 显 原因. 破. 终. 环.
盒 取 [空].
试: 卒 '七'. 救 原因: 算 内: 得 原因. 法. 盒[0] 取 算 内. 终.
显 (盒[0])().
""")
        result = self.run_program(stress=True)
        self.assertEqual((result.returncode,result.stdout),(0,'初始化\n模块失败\n模块失败\n4\n3\n恢复\n七\n'),result.stderr)

    def test_entry_arguments_independent_ir_and_deleted_source(self):
        self.build("算 元初 参数 为 句 阵: 显 参数[0]. 得 7. 法.")
        self.source.unlink()
        result = self.run_program(arguments=('如😀',))
        self.assertEqual((result.returncode,result.stdout),(7,'如😀\n'),result.stderr)
        rebuilt = self.root/'rebuilt.exe'
        command = TOOLCHAIN.clang+[str(self.ir),'-o',str(rebuilt),*TOOLCHAIN.link_flags]
        result = subprocess.run(command,capture_output=True,text=True,encoding='utf-8',env=llvm_environment(),timeout=120)
        self.assertEqual(result.returncode,0,result.stderr)
        result = subprocess.run([str(rebuilt),'独立'],cwd=self.root,env={**os.environ,'PATH':''},
                                capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual((result.returncode,result.stdout),(7,'独立\n'),result.stderr)

    def test_native_frontend_runs_in_empty_directory_without_python_or_project(self):
        compiler = self.root/'compiler.exe'
        shutil.copyfile(self.compiler,compiler)
        compiler.chmod(0o755)
        self.source.write_text("显 '无宿主前端😀'.",encoding='utf-8')
        program, metadata, sources = (self.root/name for name in ('frontend.ll','metadata.c','sources.json'))
        result = subprocess.run([str(compiler),str(self.source),str(program),str(metadata),
                                 TOOLCHAIN.triple,TOOLCHAIN.data_layout,str(self.root),str(sources)],
                                cwd=self.root,env={**os.environ,'PATH':''},capture_output=True,
                                text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('define void @boot_m_0_llvm',program.read_text(encoding='utf-8'))
        self.assertEqual([Path(path).resolve() for path in json.loads(sources.read_text(encoding='utf-8'))],[self.source])
        result = subprocess.run([TOOLCHAIN.tools['llvm-as'],str(program),'-o',str(self.root/'program.bc')],
                                capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_source_errors_and_llvm_failure_preserve_previous_artifacts(self):
        self.binary.write_bytes(b'previous executable')
        self.ir.write_bytes(b'previous IR')
        for source in ('显 .', '若 假 则 未知 1. 然.', "若 假 则 模 取 外言 '如:密'. 然.",
                       '显 1e999.', '显 1.7976931348623159e308.', '显 其.', '作 错: 得 1. 为.',
                       '若 假 则 算 错: 得 1. 法. 然.', '段: 形 错: 象. 落.',
                       '形 错: 值 为 数. 值 为 数. 象.',
                       '形 甲: 算 同名 值 为 数: 得 值. 法. 象. 形 乙 如 甲: 算 同名 别名 为 数: 得 别名. 法. 象.'):
            self.source.write_text(source,encoding='utf-8')
            with self.subTest(source=source), patch.object(TOOLCHAIN,'compile',side_effect=AssertionError('LLVM started')), \
                    self.assertRaises(RuntimeError):
                compile_native(self.compiler,self.source,self.binary,TOOLCHAIN,emit_llvm=self.ir)
            self.assertEqual(self.binary.read_bytes(),b'previous executable')
            self.assertEqual(self.ir.read_bytes(),b'previous IR')
        self.source.write_text('显 1.',encoding='utf-8')
        with patch.object(TOOLCHAIN,'compile',side_effect=RuError('tool failure')), self.assertRaises(RuError):
            compile_native(self.compiler,self.source,self.binary,TOOLCHAIN,emit_llvm=self.ir)
        self.assertEqual(self.binary.read_bytes(),b'previous executable')
        self.assertEqual(self.ir.read_bytes(),b'previous IR')
        self.assertEqual(list(self.root.glob('.ru-bootstrap-*')),[])

    def test_root_and_imported_source_aliases_cannot_be_overwritten(self):
        child = self.root/'child.ru'
        child.write_text('值 取 1.',encoding='utf-8')
        self.source.write_text("模 取 外言 'child.ru'. 显 模 其 值.",encoding='utf-8')
        with self.assertRaises(ValueError):
            compile_native(self.compiler,self.source,self.source,TOOLCHAIN)
        with patch.object(TOOLCHAIN,'compile',side_effect=AssertionError('LLVM started')), self.assertRaises(ValueError):
            compile_native(self.compiler,self.source,child,TOOLCHAIN)
        self.assertEqual(child.read_text(encoding='utf-8'),'值 取 1.')
        original = self.source.read_bytes()
        result = subprocess.run([str(self.compiler),str(self.source),str(self.source),str(self.root/'metadata.c'),
                                 TOOLCHAIN.triple,TOOLCHAIN.data_layout,str(ROOT/'rulang/stdlib')],
                                capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.source.read_bytes(),original)

    def test_short_circuit_procedures_loop_unwind_and_panic_order(self):
        self.build("""
算 坏: 卒 '停止'. 法.
算 后: 显 '不应执行'. 得 9. 法.
算 合 左 右: 得 左+右. 法.
显 假 且 (后()). 显 真 或 (后()). 显 0 为 事实.
计数 取 [0].
循 4 次
 段: 试: 计数[0] 取 计数[0]+1. 破. 救 原因: 显 原因. 终. 落.
 显 '不应执行'.
环.
显 计数[0].
试: 显 合 (坏()) (后()). 救 原因: 显 原因. 终.
作 提前: 段: 试: 完. 救 原因: 显 原因. 终. 落. 为.
提前. 显 '完成'.
""")
        result = self.run_program(stress=True)
        self.assertEqual((result.returncode,result.stdout),(0,'假\n真\n真\n1\n停止\n完成\n'),result.stderr)
        self.assertIn('live=0',result.stderr)

    def test_checked_unicode_file_io_and_standard_input(self):
        (self.root/'bad-utf8').write_bytes(b'\xff')
        self.build("""
文档 取 新 件 路径:'文件😀.txt'.
显 (文档 其 写 内容:'甲😀') 其 结果.
显 (文档 其 写 内容:'乙' 追加:1) 其 结果.
显 (文档 其 读) 其 值.
显 (文档 其 除) 其 结果. 显 (文档 其 在) 其 值.
显 ((新 件 路径:'bad-utf8') 其 读) 其 结果.
显 ((新 件 路径:'不存在') 其 读) 其 结果.
显 (读取 其 读) 其 值. 显 (读取 其 读) 其 值.
显 (读取 其 读) 其 值 == 空.
""")
        result = self.run_program(input='输入😀\r\n\n',stress=True)
        self.assertEqual((result.returncode,result.stdout),
                         (0,'成功\n成功\n甲😀乙\n成功\n假\n失败\n失败\n输入😀\n\n真\n'),result.stderr)
        self.assertIn('live=0',result.stderr)
        self.assertFalse((self.root/'文件😀.txt').exists())

    def test_receiver_selection_precedes_argument_mutation(self):
        self.build("""
形 报告: 算 合 值: 得 值+10. 法. 象.
对象 取 新 报告. 容器 取 [对象].
算 改: 容器[0] 取 空. 得 2. 法.
显 容器[0] 其 合 (改()).
""")
        result = self.run_program(stress=True)
        self.assertEqual((result.returncode,result.stdout),(0,'12\n'),result.stderr)

    def test_ordinary_errors_are_not_rescued_and_preserve_origin(self):
        for expression,fragment in (('1/0','除数不能为零'),('1e308*1e308','有限'),('假+1','数字')):
            with self.subTest(expression=expression):
                self.build("显 '先前副作用'.\n试: 显 "+expression+". 救 原因: 显 '不应恢复'. 终.\n显 '不应继续'.")
                result = self.run_program()
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(result.stdout,'先前副作用\n')
                self.assertIn(fragment,result.stderr)
                self.assertIn(self.source.name+':2:',result.stderr)
                self.assertNotIn('Traceback',result.stderr)

    def test_invalid_assignment_does_not_evaluate_rhs(self):
        self.build("算 副作用: 显 '不应执行'. 得 3. 法. 列 取 []. 列[0] 取 副作用.")
        result = self.run_program()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stdout,'')
        self.assertIn(self.source.name+':1:',result.stderr)

    def test_relative_module_diamond_aliases_and_owner_scope(self):
        library = self.root/'库😀'
        library.mkdir()
        (library/'base.ru').write_text("显 '初始化'. 值 取 40. 算 加 数值: 得 值+数值. 法.",encoding='utf-8')
        (library/'facade.ru').write_text("尽取 外言 'base.ru'.",encoding='utf-8')
        self.build("""
若 假 则 模 取 外言 '库😀/base.ru'. 然.
显 '开始'.
甲 取 外言 '库😀/facade.ru'. 乙 取 外言 '库😀/../库😀/base.ru'.
值 取 99. 显 甲 其 加 2. 显 乙 其 值.
""")
        result = self.run_program(stress=True)
        self.assertEqual((result.returncode,result.stdout),(0,'开始\n初始化\n42\n40\n'),result.stderr)

    def test_dependency_errors_are_checked_before_execution(self):
        child = self.root/'child.ru'
        cases = (("# 注释\n未知 1.",'child.ru:2:'),
                 ("# 注释\n显 ).",'child.ru:2:'),
                 ("模 取 外言 '输入 程序😀.ru'.",'循环外言'),
                 ("模 取 外言 'missing.ru'.",'missing.ru'))
        for source,fragment in cases:
            with self.subTest(source=source):
                child.write_text(source,encoding='utf-8')
                self.source.write_text("显 '不应执行'. 若 假 则 模 取 外言 'child.ru'. 然.",encoding='utf-8')
                self.binary.write_bytes(b'previous executable')
                with patch.object(TOOLCHAIN,'compile',side_effect=AssertionError('LLVM started')), \
                        self.assertRaises(RuntimeError) as caught:
                    compile_native(self.compiler,self.source,self.binary,TOOLCHAIN)
                self.assertIn(fragment,str(caught.exception))
                self.assertNotIn('不应执行',str(caught.exception))
                self.assertEqual(self.binary.read_bytes(),b'previous executable')

    def test_compile_error_locations_and_capability_boundaries(self):
        cases = (('显 1.\n未知 1.','未定义'),('显 1.\n破.','破不能'),
                 ('显 1.\n得 1.','得只能'),('显 1.\n完.','完只能'),
                 ("显 1.\n模 取 外言 '如:观'.",'不支持'),
                 ("显 1.\n模 取 外言 '如:密'.",'不支持'))
        for source,fragment in cases:
            with self.subTest(source=source):
                self.source.write_text(source,encoding='utf-8')
                with self.assertRaises(RuntimeError) as caught:
                    compile_native(self.compiler,self.source,self.binary,TOOLCHAIN)
                self.assertIn(self.source.name+':2:',str(caught.exception))
                self.assertIn(fragment,str(caught.exception))


def practical_golden(case):
    def test(self):
        self.build(case['source'])
        result = self.run_program(stress=True)
        self.assertEqual((result.returncode,result.stdout),(0,case['stdout']),result.stderr)
        self.assertIn('live=0',result.stderr)
    return test


for _case in json.loads((ROOT/'bootstrap/validation/practical.json').read_text(encoding='utf-8')):
    setattr(BootstrapTests,'test_practical_'+_case['name'],practical_golden(_case))


class BootstrapStage1Tests(BootstrapTests):
    stage_number = 1


class BootstrapStage2Tests(BootstrapTests):
    stage_number = 2


if __name__ == '__main__':
    unittest.main()
