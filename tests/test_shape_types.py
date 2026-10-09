"""Shape names denote types, while constructed instances remain ordinary values."""
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.compiler import Compiler
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter
from rulang.js_compiler import JSCompiler
from rulang.modules import load_module_graph

CC = (shutil.which(os.environ['CC']) if os.environ.get('CC') else
      next((shutil.which(c) for c in ('clang', 'gcc', 'cc') if shutil.which(c)), None))
NODE = shutil.which('node') or shutil.which('nodejs')
SHAPE = '形 学生: 年龄 为 数. 象\n'
DIAGNOSTIC = '形名「学生」不能作为普通值'
VALUE_USES = [
    ('alias', '别名 取 学生.'),
    ('display', '显 学生.'),
    ('argument', '算 接受 值 为 阵: 得 0. 法 接受 学生.'),
    ('return', '算 工厂: 得 学生. 法 显 工厂.'),
    ('array', '列 取 [学生].'),
    ('pair', '值 取 学生 对 空.'),
    ('equality', '显 学生 == 学生.'),
    ('inequality', '显 学生 != 空.'),
    ('truth', '显 非 学生.'),
    ('convert_string', '显 学生 为 句.'),
    ('convert_array', '显 学生 为 阵.'),
    ('append', '列 取 []. 列 其 增 学生.'),
    ('anonymous_return', '回 取 算: 得 学生. 法. 显 回().'),
    ('named_closure_return', '算 外: 算 内: 得 学生. 法 得 算 内. 法 回 取 外. 显 回().'),
]

INSTANCES = SHAPE + '''
形 班: 学员 为 学生 阵. 象
形 高生 如 学生: 象
算 制 年 为 数: 得 新 高生 年龄:年. 法
算 查 对象 为 学生: 得 对象 其 年龄. 法
算 制回 年 为 数:
    对象 取 制 年.
    得 算: 对象 其 年龄 取 对象 其 年龄+1. 得 对象. 法.
法
工厂 取 算 制. 列 取 [(工厂 17)]. 别名 取 列[0].
显 查 别名. 显 别名 == 列[0].
班级 取 新 班 学员:列. 显 查 (班级 其 学员)[0].
回调 取 制回 20. 显 查 回调(). 显 查 回调().
'''


class ShapeTypeTests(unittest.TestCase):
    def graph(self, folder, files):
        for name, source in files.items():
            path = Path(folder) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding='utf-8')
        return load_module_graph(Path(folder) / 'main.ru')

    def interpreted(self, graph):
        output = io.StringIO()
        engine = Interpreter(io.StringIO(), output)
        engine.execute(graph[graph.root], source_path=graph.root, modules=graph)
        return output.getvalue()

    def assert_engines(self, files, expected):
        with tempfile.TemporaryDirectory() as folder:
            graph = self.graph(folder, files)
            self.assertEqual(self.interpreted(graph), expected)
            for full in (False, True):
                for backend, available in ((Compiler, CC), (JSCompiler, NODE)):
                    if not available:
                        continue
                    with self.subTest(backend=backend.__name__, full=full):
                        generated = backend(graph[graph.root], graph.root, modules=graph,
                                            full_runtime=full).compile()
                        stem = Path(folder) / (backend.__name__ + str(full))
                        if backend is Compiler:
                            source = stem.with_suffix('.c')
                            source.write_text(generated, encoding='utf-8')
                            built = subprocess.run([CC, '-std=c99', '-O1', '-Wall', '-Wextra',
                                '-Werror', '-Wno-unused-function', '-pedantic', str(source),
                                '-lm', '-o', str(stem)], text=True, capture_output=True, timeout=60)
                            self.assertEqual(built.returncode, 0, built.stderr)
                            command = [str(stem)]
                        else:
                            source = stem.with_suffix('.js')
                            source.write_text(generated, encoding='utf-8')
                            command = [NODE, str(source)]
                        result = subprocess.run(command, text=True, capture_output=True, timeout=20,
                            env={**os.environ, 'RU_GC_THRESHOLD': '1', 'RU_GC_STATS': '1'})
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout, expected)
                        if backend is Compiler:
                            self.assertIn('RU_GC live=0 ', result.stderr)

    def test_instances_factories_closures_and_typed_arrays(self):
        self.assert_engines({'main.ru': INSTANCES}, '17\n1\n17\n21\n22\n')

    def assert_rejected_engines(self, files, diagnostic):
        """Accept static rejection or a clean runtime error in either compiler."""
        with tempfile.TemporaryDirectory() as folder:
            graph = self.graph(folder, files)
            with self.assertRaises(RuError) as caught:
                self.interpreted(graph)
            self.assertIn(diagnostic, caught.exception.message)
            for full in (False, True):
                for backend, available in ((Compiler, CC), (JSCompiler, NODE)):
                    if not available:
                        continue
                    with self.subTest(backend=backend.__name__, full=full):
                        try:
                            generated = backend(graph[graph.root], graph.root,
                                modules=graph, full_runtime=full).compile()
                        except RuError as error:
                            self.assertIn(diagnostic, error.message)
                            continue
                        target = Path(folder) / 'rejected'
                        if backend is Compiler:
                            source = target.with_suffix('.c')
                            source.write_text(generated, encoding='utf-8')
                            built = subprocess.run([CC, '-std=c99', str(source), '-lm',
                                '-o', str(target)], text=True, capture_output=True, timeout=60)
                            self.assertEqual(built.returncode, 0, built.stderr)
                            command = [str(target)]
                        else:
                            source = target.with_suffix('.js')
                            source.write_text(generated, encoding='utf-8')
                            command = [NODE, str(source)]
                        result = subprocess.run(command, text=True, capture_output=True,
                            timeout=20, env={**os.environ, 'RU_GC_THRESHOLD': '1', 'RU_GC_STATS': '1'})
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(diagnostic, result.stderr)
                        self.assertEqual(result.stdout, '')
                        self.assertNotIn('Traceback', result.stderr)
                        if backend is Compiler:
                            self.assertIn('RU_GC live=0 ', result.stderr)

    def test_imports_do_not_hide_undefined_annotations(self):
        for expression in (
            '形 盒: 项 为 未知. 象 显 新 盒.',
            '形 盒: 项 为 未知 阵 阵. 象 显 新 盒 项:[[]].',
            '算 接 值 为 未知 阵: 得 1. 法 显 接 [].',
            '算 接 值 为 未知 阵 阵: 得 1. 法 显 接 [[]].',
            '回 取 算 值 为 未知 阵 阵: 得 1. 法. 显 回 [[]].',
        ):
            with self.subTest(expression=expression):
                self.assert_rejected_engines({'empty.ru': '',
                    'main.ru': "尽 取 外言 'empty.ru'. " + expression}, '未定义类型：未知')

    def test_forward_declared_nested_array_method_types(self):
        self.assert_engines({'main.ru': '''
形 父: 算 查 值 为 学生 阵 阵: 得 值 其 量. 法 象
形 子 如 父: 算 查 值 为 学生 阵 阵: 得 值 其 量+1. 法 象
形 盒: 项 为 学生 阵 阵. 象
形 学生: 象
对象 取 新 盒 项:[[(新 学生)]].
显 (新 子) 其 查 (对象 其 项).
'''}, '2\n')

    def test_imported_nested_array_annotations_require_executed_import(self):
        for declaration in (
            '形 盒: 项 为 学生 阵 阵. 象',
            '形 盒: 算 查 值 为 学生 阵 阵: 得 1. 法 象',
        ):
            with self.subTest(declaration=declaration):
                self.assert_rejected_engines({'models.ru': SHAPE,
                    'main.ru': declaration + " 尽 取 外言 'models.ru'."}, '未定义类型：学生')
                self.assert_engines({'models.ru': SHAPE,
                    'main.ru': "尽 取 外言 'models.ru'. " + declaration + ' 显 1.'}, '1\n')

    def test_imported_function_annotation_is_resolved_before_empty_array_match(self):
        declaration = '算 接 值 为 学生 阵 阵: 得 1. 法 '
        self.assert_rejected_engines({'models.ru': SHAPE,
            'main.ru': declaration + "显 接 [[]]. 尽 取 外言 'models.ru'."}, '未定义类型：学生')
        self.assert_engines({'models.ru': SHAPE,
            'main.ru': declaration + "尽 取 外言 'models.ru'. 显 接 [[]]."}, '1\n')

    def test_shape_value_uses_have_precise_diagnostics(self):
        for name, expression in VALUE_USES:
            with self.subTest(case=name):
                source = SHAPE + expression
                for backend in (Interpreter, Compiler, JSCompiler):
                    with self.subTest(backend=backend.__name__):
                        with self.assertRaises(RuError) as caught:
                            if backend is Interpreter:
                                backend(io.StringIO(), io.StringIO()).execute(parse(source))
                            else:
                                backend(parse(source)).compile()
                        self.assertIn(DIAGNOSTIC, caught.exception.message)
                        self.assertIn('新 学生', caught.exception.message)
                        self.assertEqual(caught.exception.line, 2)

    def test_builtin_shapes_are_not_values(self):
        for name in ('件', '录', '件作成果'):
            for backend in (Interpreter, Compiler, JSCompiler):
                with self.subTest(name=name, backend=backend.__name__):
                    with self.assertRaises(RuError) as caught:
                        source = parse('别名 取 ' + name + '.')
                        if backend is Interpreter:
                            backend(io.StringIO(), io.StringIO()).execute(source)
                        else:
                            backend(source).compile()
                    self.assertIn('不能作为普通值', caught.exception.message)

    def test_imported_shapes_and_instance_factories(self):
        self.assert_engines({
            'models.ru': SHAPE + '算 制 年 为 数: 得 新 学生 年龄:年. 法',
            'relay.ru': "尽 取 外言 'models.ru'.",
            'main.ru': "尽 取 外言 'relay.ru'. 模 取 外言 'models.ru'. "
                       '形 高生 如 学生: 象 算 查 物 为 学生: 得 物 其 年龄. 法 '
                       '显 查 (新 高生 年龄:18). 显 查 (模 其 制 19).',
        }, '18\n19\n')

    def test_factory_and_callable_annotations_use_defining_module(self):
        self.assert_engines({
            'models.ru': SHAPE + '算 制: 得 新 学生 年龄:19. 法 '
                        '算 查 物 为 学生: 得 物 其 年龄. 法 '
                        '算 制回: 得 算 物 为 学生: 得 物 其 年龄+1. 法. 法',
            'main.ru': SHAPE + "模 取 外言 'models.ru'. 对象 取 模 其 制. "
                       '显 模 其 查 对象. 回调 取 模 其 制回. 显 回调 对象.',
        }, '19\n20\n')

    def test_qualified_module_shape_is_not_a_value(self):
        for expression in ('别名 取 模 其 学生.', '显 [模 其 学生].',
                           '显 (模 其 学生) == 空.', '显 (模 其 学生) 为 句.'):
            with tempfile.TemporaryDirectory() as folder:
                graph = self.graph(folder, {'models.ru': SHAPE,
                    'main.ru': "模 取 外言 'models.ru'. " + expression})
                with self.assertRaises(RuError) as caught:
                    self.interpreted(graph)
                self.assertIn(DIAGNOSTIC, caught.exception.message)
                for full in (False, True):
                    for backend, available in ((Compiler, CC), (JSCompiler, NODE)):
                        if not available:
                            continue
                        with self.subTest(expression=expression, backend=backend.__name__, full=full):
                            # A dynamic module member may be diagnosed at runtime.
                            try:
                                generated = backend(graph[graph.root], graph.root,
                                    modules=graph, full_runtime=full).compile()
                            except RuError as error:
                                self.assertIn(DIAGNOSTIC, error.message)
                                continue
                            target = Path(folder) / 'rejected'
                            if backend is Compiler:
                                source = target.with_suffix('.c')
                                source.write_text(generated, encoding='utf-8')
                                built = subprocess.run([CC, '-std=c99', str(source), '-lm',
                                    '-o', str(target)], text=True, capture_output=True, timeout=60)
                                self.assertEqual(built.returncode, 0, built.stderr)
                                command = [str(target)]
                            else:
                                source = target.with_suffix('.js')
                                source.write_text(generated, encoding='utf-8')
                                command = [NODE, str(source)]
                            result = subprocess.run(command, text=True, capture_output=True,
                                timeout=20, env={**os.environ, 'RU_GC_THRESHOLD': '1', 'RU_GC_STATS': '1'})
                            self.assertNotEqual(result.returncode, 0)
                            self.assertIn(DIAGNOSTIC, result.stderr)
                            self.assertEqual(result.stdout, '')
                            self.assertNotIn('Traceback', result.stderr)
                            if backend is Compiler:
                                self.assertIn('RU_GC live=0 ', result.stderr)

    def test_shared_imported_type_override_remains_valid(self):
        self.assert_engines({
            'types.ru': SHAPE,
            'base.ru': "尽 取 外言 'types.ru'. 形 父: 算 查 值 为 学生: 得 值 其 年龄. 法 象",
            'main.ru': "尽 取 外言 'base.ru'. 形 子 如 父: 算 查 值 为 学生: 得 (值 其 年龄)+1. 法 象 "
                       '显 (新 子) 其 查 (新 学生 年龄:18).',
        }, '19\n')

    def test_distinct_declared_types_reject_override(self):
        for suffix in ('', ' 阵'):
            source = ('形 甲: 象 形 乙: 象 '
                      f'形 父: 算 查 值 为 甲{suffix}: 得 1. 法 象 '
                      f'形 子 如 父: 算 查 值 为 乙{suffix}: 得 2. 法 象')
            for backend in (Interpreter, Compiler, JSCompiler):
                with self.subTest(suffix=suffix, backend=backend.__name__):
                    with self.assertRaises(RuError) as caught:
                        if backend is Interpreter:
                            backend(io.StringIO(), io.StringIO()).execute(parse(source))
                        else:
                            backend(parse(source)).compile()
                    self.assertIn('覆写方法', caught.exception.message)

    def test_distinct_same_named_declaration_types_reject_override(self):
        # A parent's annotation belongs to its defining module, not the child.
        base = Interpreter(io.StringIO(), io.StringIO())
        base.execute(parse(SHAPE + '形 父: 算 查 值 为 学生: 得 1. 法 象'))
        child = Interpreter(io.StringIO(), io.StringIO())
        child.types['父'] = base.types['父']
        with self.assertRaises(RuError) as caught:
            child.execute(parse(SHAPE + '形 子 如 父: 算 查 值 为 学生: 得 2. 法 象'))
        self.assertIn('覆写方法', caught.exception.message)

    def test_redefined_same_named_type_rejects_override(self):
        engine = Interpreter(io.StringIO(), io.StringIO())
        engine.execute(parse(SHAPE + '形 父: 算 查 值 为 学生: 得 1. 法 象'))
        engine.execute(parse(SHAPE))
        with self.assertRaises(RuError) as caught:
            engine.execute(parse('形 子 如 父: 算 查 值 为 学生: 得 2. 法 象'))
        self.assertIn('覆写方法', caught.exception.message)

    def test_redefined_type_keeps_inherited_and_bound_method_identity(self):
        output = io.StringIO()
        engine = Interpreter(io.StringIO(), output)
        engine.execute(parse(SHAPE + '''
形 父: 算 查 值 为 学生 阵 阵: 得 1. 法 象
形 子 如 父: 象
旧 取 新 学生. 对象 取 新 子. 引 取 算 对象 其 查.
'''))
        engine.execute(parse(SHAPE))
        engine.execute(parse('显 对象 其 查 [[旧]]. 显 引 [[旧]].'))
        self.assertEqual(output.getvalue(), '1\n1\n')
        for expression in ('显 对象 其 查 [[(新 学生)]].', '显 引 [[(新 学生)]].'):
            with self.subTest(expression=expression):
                with self.assertRaises(RuError) as caught:
                    engine.execute(parse(expression))
                self.assertIn('实参「值」须为学生 阵 阵', caught.exception.message)

    def test_builtin_array_override_identity_across_modules(self):
        self.assert_engines({
            'base.ru': '形 父: 算 查 值 为 件 阵: 得 值 其 量. 法 象',
            'main.ru': "尽 取 外言 'base.ru'. "
                       '形 子 如 父: 算 查 值 为 件 阵: 得 值 其 量+1. 法 象 '
                       '显 (新 子) 其 查 [(新 件)].',
        }, '2\n')

    def test_same_spelled_imported_shape_conflicts_with_local_declaration(self):
        with tempfile.TemporaryDirectory() as folder:
            graph = self.graph(folder, {'base.ru': SHAPE,
                'main.ru': "尽 取 外言 'base.ru'. " + SHAPE})
            for backend in (Interpreter, Compiler, JSCompiler):
                with self.subTest(backend=backend.__name__):
                    with self.assertRaises(RuError) as caught:
                        if backend is Interpreter:
                            self.interpreted(graph)
                        else:
                            backend(graph[graph.root], graph.root, modules=graph).compile()
                    self.assertIn('冲突', caught.exception.message)

    def test_repl_rejects_shape_value_and_keeps_type_available(self):
        commands = SHAPE + '别名 取 学生.\n显 (新 学生 年龄:18) 其 年龄.\n:quit\n'
        result = subprocess.run([sys.executable, str(ROOT / 'ru'), 'repl'], input=commands,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '18\n')
        self.assertIn(DIAGNOSTIC, result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_notebook_rejects_shape_value_and_recovers(self):
        from rushu.kernel import Session
        session = Session()
        self.addCleanup(session.close)

        def cell(source):
            after = session.snapshot()['cursor']
            session.execute(source, 'shape-test')
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                result = session.poll(after)
                if result['state'] == 'idle':
                    return result
                self.assertNotEqual(result['state'], 'dead', result)
                time.sleep(.01)
            self.fail('Notebook cell timed out')

        self.assertEqual(cell(SHAPE)['events'][-1]['status'], 'ok')
        failed = cell('别名 取 学生.')
        self.assertEqual(failed['events'][-1]['status'], 'error')
        self.assertTrue(any(DIAGNOSTIC in event.get('message', '') for event in failed['events']))
        result = cell('显 (新 学生 年龄:18) 其 年龄.')
        self.assertEqual(result['events'][-1]['status'], 'ok')
        self.assertEqual(''.join(e['text'] for e in result['events'] if e['type'] == 'output'), '18\n')


if __name__ == '__main__':
    unittest.main()
