"""Real AOT-compiled Ru interpretation, notebook lifecycle and provenance."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import test_rushu_kernel as reference
from rulang.llvm_toolchain import LLVMToolchain
from rulang.frontend import RuError
from rushu.kernel import KernelError, Session
from tools.bootstrap import ROOT, bootstrap, compile_native

try:
    TOOLCHAIN = LLVMToolchain()
except RuError:
    TOOLCHAIN = None


class NativeKernelTests(reference.KernelTests):
    @classmethod
    def setUpClass(cls):
        if TOOLCHAIN is None:
            raise unittest.SkipTest('LLVM 14 toolchain required for the native Ru interpreter')
        selected = os.environ.get('RU_TEST_NATIVE_KERNEL')
        if selected:
            cls.binary = Path(selected).resolve()
            return
        # Own this fixture: another test module may already have run and
        # cleaned up its compiler stages before full discovery reaches us.
        temporary = tempfile.TemporaryDirectory(prefix='ru-native-kernel-tests-')
        cls.addClassCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        bootstrap(directory)
        suffix = '.exe' if sys.platform == 'win32' else ''
        cls.binary = directory/('interpreter'+suffix)
        # Native Ru frontend processes every imported Ru source. The host may
        # prepare C primitives and invoke LLVM, but cannot parse or execute Ru.
        with patch('rulang.frontend.parse', side_effect=AssertionError('Python parser')), \
                patch('rulang.interpreter.Interpreter.execute', side_effect=AssertionError('Python interpreter')), \
                patch('rulang.modules.load_module_graph', side_effect=AssertionError('Python module loader')):
            compile_native(directory/('stage3'+suffix), ROOT/'rushu/native/kernel.ru',
                           cls.binary, TOOLCHAIN, interpreter_host=True)

    def setUp(self):
        self.session = Session(native_kernel=self.binary)
        self.addCleanup(self.session.close)

    def test_spawn_shared_state_counter_echo_and_separate_notebooks(self):
        from rushu.native_kernel import NativeProcess
        self.assertIsInstance(self.session.process, NativeProcess)
        first = self.run_cell("值 取 40. 显 '你好😀'.", 'first')
        self.assertEqual(reference.output(first), '你好😀\n')
        self.assertEqual(reference.output(self.run_cell('值+2.', 'second')), '42\n')
        other = Session(native_kernel=self.binary)
        self.addCleanup(other.close)
        other.execute('显 值.', 'isolated')
        failed = reference.wait_for(other)
        self.assertEqual(failed['events'][-1]['status'], 'error')
        self.assertIn('未定义名称', failed['events'][0]['message'])

    def test_native_execution_cannot_fall_back_to_python(self):
        with patch('rulang.frontend.parse', side_effect=AssertionError('Python parser')), \
                patch('rulang.interpreter.Interpreter.execute', side_effect=AssertionError('Python interpreter')):
            result = self.run_cell('算 阶乘 值: 若 值 <= 1 则 得 1. 然. 得 值*(阶乘 (值-1)). 法. 显 阶乘 8.')
        self.assertEqual(reference.output(result), '40320\n')

    def test_elif_lazy_evaluation_cross_cell_scope_and_precise_errors(self):
        with patch('rulang.frontend.parse', side_effect=AssertionError('Python parser')), \
                patch('rulang.interpreter.Interpreter.execute', side_effect=AssertionError('Python interpreter')):
            result=self.run_cell("算 问 号 答: 显 号. 得 答. 法. "
                "若 问 1 假 则 值 取 99. 另若 问 2 真 则 值 取 7. "
                "另若 1/0 则 值 取 98. 另 值 取 97. 然.", 'chain')
            self.assertEqual(reference.output(result),'1\n2\n')
            self.assertEqual(result['events'][-1]['status'],'ok')
            result=self.run_cell('显 值. 若 假 则 另 若 假 则 另若 真 则 显 3. 然. 显 4. 然.')
            self.assertEqual(reference.output(result),'7\n3\n4\n')
            failed=self.run_cell('若 假 则\n另若 1/0 则 显 9.\n然.', 'condition')
        error=next(e for e in failed['events'] if e['type']=='error')
        self.assertEqual(error['line'],2)
        self.assertEqual(error['diagnostic']['source']['cell_id'],'condition')
        self.assertEqual(reference.output(self.run_cell('显 值.')),'7\n')
        for source,line,col in (('另若 取 1.',1,1),
                                ('若 假 则\n另\n  另若 真 则 然.',3,3),
                                ('算 甲 另若: 得 1. 法.',1,5),
                                ('若 假 则 另若 真 则 然. 然.',1,17)):
            with self.subTest(source=source):
                failed=self.run_cell(source)
                self.assertEqual(failed['events'][-1]['status'],'error')
                error=next(e for e in failed['events'] if e['type']=='error')
                self.assertEqual((error['line'],error['col']),(line,col))
        self.assertEqual(reference.output(self.run_cell('另若值 取 8. 显 另若值.')),'8\n')

    def test_elif_oversized_chain_is_rejected_and_session_recovers(self):
        failed=self.run_cell('若 假 则 '+'另若 假 则 '*1000+'然.')
        self.assertEqual(failed['events'][-1]['status'],'error')
        error=next(e for e in failed['events'] if e['type']=='error')
        self.assertIn('嵌套过深',error['message'])
        self.assertEqual(reference.output(self.run_cell('显 42.')),'42\n')

    def test_old_closures_objects_and_source_survive_redefinition(self):
        self.run_cell("算 平方 值: 得 值*值. 法. 旧 取 算 平方.", 'definition')
        self.run_cell("算 平方 值: 得 值+值. 法.", 'replacement')
        self.assertEqual(reference.output(self.run_cell('显 旧 5. 显 平方 5.')), '25\n10\n')
        self.run_cell("算 造: 值 取 0. 算 加: 值 取 值+1. 得 值. 法. 得 算 加. 法. 计 取 造.")
        self.assertEqual(reference.output(self.run_cell('显 计(). 显 计().')), '1\n2\n')
        self.run_cell('算 错处:\n 显 未定义.\n法.', 'source')
        failed = self.run_cell('错处.', 'caller')
        error = next(e for e in failed['events'] if e['type'] == 'error')
        self.assertEqual(error['diagnostic']['source']['cell_id'], 'source')
        self.assertEqual(error['line'], 2)

    def test_arithmetic_and_guest_errors_preserve_prior_side_effects(self):
        for expression in ('1/0', '1e308*1e308', "'错' 为 数", '[][0]', '[1][1.5]'):
            result = self.run_cell('已做 取 7. 显 '+expression+'.')
            self.assertEqual(result['events'][-1]['status'], 'error', result)
            self.assertEqual(reference.output(self.run_cell('显 已做.')), '7\n')
        failed = self.run_cell("试: 显 1/0. 救 因: 显 '不应捕获'. 终.")
        self.assertEqual(reference.output(failed), '')
        self.assertEqual(reference.output(self.run_cell("试: 卒 '原因'. 救 因: 显 因. 终.")), '原因\n')

    def test_identity_aliases_and_cycles(self):
        result = self.run_cell("列 取 [1]. 别名 取 列. 别名[0] 取 9. 显 列. 显 列 == 别名. 显 列 == [9]. 列 其 增 列. 显 列.")
        self.assertEqual(reference.output(result), '[9]\n真\n假\n[9, <循环>]\n[9, <循环>]\n')
        result = self.run_cell('次数 取 [0]. 形 盒: 算 同 另一: 次数[0] 取 次数[0]+1. 得 真. 法. 象. 甲 取 新 盒. 显 甲 == 甲. 显 次数[0].')
        self.assertEqual(reference.output(result), '真\n1\n')

    def test_native_program_is_independent_of_python_and_source_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            copied = Path(temp)/self.binary.name
            shutil.copy2(self.binary, copied)
            source = Path(temp)/'输入😀.ru'
            source.write_text("显 '原生解释'. 显 6*7. "
                "算 造: 值 取 0. 算 加: 值 取 值+1. 得 值. 法. 得 算 加. 法. "
                "循 8 次 环列 取 []. 环列 其 增 环列. 计 取 造. 首 取 计(). 最后 取 计(). 环. 显 最后.", encoding='utf-8')
            environment = {**os.environ, 'PATH': '', 'RU_GC_THRESHOLD': '1', 'RU_GC_STATS': '1'}
            result = subprocess.run([str(copied), str(source)], cwd=temp, env=environment,
                                    capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual((result.returncode, result.stdout), (0, '原生解释\n42\n2\n'), result.stderr)
            self.assertIn('live=0', result.stderr)

    def test_nul_and_deep_recursion_are_recoverable(self):
        result = self.run_cell("显 'a\x00b'.")
        self.assertEqual(result['events'][-1]['status'], 'error')
        result = self.run_cell('算 递: 得 递. 法. 递.')
        self.assertEqual(result['events'][-1]['status'], 'error', result)
        result = self.run_cell('若 真 则 '*350+'显 1.'+' 然.'*350)
        self.assertEqual(result['events'][-1]['status'], 'error', result)
        self.assertEqual(reference.output(self.run_cell('显 42.')), '42\n')

    def test_shared_standard_library_golden_programs(self):
        cases = json.loads((ROOT/'bootstrap/validation/practical.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)/'libraries.ru'
            for case in cases:
                with self.subTest(case=case['name']):
                    source.write_text(case['source'], encoding='utf-8')
                    result = subprocess.run([str(self.binary), str(source), str(ROOT/'rulang/stdlib')],
                                            capture_output=True, text=True, encoding='utf-8', timeout=30)
                    self.assertEqual((result.returncode, result.stdout), (0, case['stdout']), result.stderr)

    def test_static_dependency_errors_precede_execution_and_import_is_lazy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = (root/'missing.ru').as_posix()
            failed = self.run_cell(f"显 '不应执行'. 若 假 则 模 取 外言 '{missing}'. 然.")
            self.assertEqual(reference.output(failed), '')
            self.assertEqual(failed['events'][-1]['status'], 'error')
            (root/'leaf.ru').write_text("显 '仅初始化一次'. 值 取 [1].", encoding='utf-8')
            (root/'left.ru').write_text("模 取 外言 'leaf.ru'.", encoding='utf-8')
            (root/'right.ru').write_text("模 取 外言 './leaf.ru'.", encoding='utf-8')
            first = self.run_cell(f"若 假 则 模 取 外言 '{root.as_posix()}/leaf.ru'. 然. 显 '惰性'.")
            self.assertEqual(reference.output(first), '惰性\n')
            both = self.run_cell(f"左 取 外言 '{root.as_posix()}/left.ru'. 右 取 外言 '{root.as_posix()}/right.ru'. 显 (左 其 模) == (右 其 模).")
            self.assertEqual(reference.output(both), '仅初始化一次\n真\n')

    def test_numeric_literal_errors_are_static_and_slice_errors_are_local(self):
        for code in ("显 '不应执行'. 显 1e9999.", "显 [1][0:9].", "显 '字'[-1:]."):
            result = self.run_cell(code)
            self.assertEqual(result['events'][-1]['status'], 'error', result)
            self.assertEqual(reference.output(result), '')
            self.assertEqual(reference.output(self.run_cell('显 7.')), '7\n')
        for declaration in ('若 真 则 算 局: 得 1. 法. 然.',
                            '段: 形 局: 象. 落.', '算 参数 值 值: 得 1. 法.',
                            '吾 言 声明.','形 数: 象.'):
            failed = self.run_cell("显 '不应执行'. "+declaration)
            self.assertEqual(failed['events'][-1]['status'], 'error', failed)
            self.assertEqual(reference.output(failed), '')

    def test_long_pairs_display_and_equality_do_not_consume_host_call_stack(self):
        result = self.run_cell('甲 取 空. 乙 取 空. 循 800 次 甲 取 1 对 甲. 乙 取 1 对 乙. 环. 显 甲 == 乙. 文 取 甲 为 句. 显 文 其 量.')
        self.assertEqual(result['events'][-1]['status'], 'ok', result)
        self.assertTrue(reference.output(result).startswith('真\n'))

    def test_real_http_service_executes_native_cells_and_stops_them(self):
        import threading
        import urllib.request
        from rushu.server import make_server
        server = make_server(native_kernel=self.binary)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(path, body):
            req = urllib.request.Request(server.origin+path, data=json.dumps(body).encode(),
                headers={'X-Rushu-Token': server.token, 'Content-Type': 'application/json',
                         'Origin': server.origin})
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.load(response)
        try:
            snapshot = request('/api/sessions', {})
            identifier = snapshot['id']
            request('/api/sessions/'+identifier+'/execute', {'code': '值 取 6. 显 值*7.', 'cell_id': 'http'})
            session = server.sessions.get(identifier)
            self.assertEqual(reference.output(reference.wait_for(session)), '42\n')
            request('/api/sessions/'+identifier+'/execute', {'code': '循 环', 'cell_id': 'stop'})
            snapshot = request('/api/sessions/'+identifier+'/stop', {})
            self.assertEqual(snapshot['state'], 'idle')
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_checked_files_and_field_assignment_do_not_escape_to_host_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            one = json.dumps(str(Path(temp)/'甲😀.txt'), ensure_ascii=False)
            two = json.dumps(str(Path(temp)/'乙😀.txt'), ensure_ascii=False)
            result = self.run_cell(f"件甲 取 新 件 路径:{one}. 果 取 件甲 其 写 内容:'原生文件'. 显 果 其 结果. 显 (件甲 其 读) 其 值. 件甲 其 路径 取 {two}. 显 (件甲 其 在) 其 值.")
            self.assertEqual(reference.output(result), '成功\n原生文件\n假\n')
            failed = self.run_cell('件甲 其 路径 取 7.')
            self.assertEqual(failed['events'][-1]['status'], 'error')
            self.assertEqual(reference.output(self.run_cell('显 (件甲 其 在) 其 结果.')), '成功\n')

    def test_file_entrypoint_and_notebook_do_not_share_entry_invocation(self):
        source = "算 元初 外参 为 句 阵: 显 外参. 得 7. 法."
        result = self.run_cell(source)
        self.assertEqual(reference.output(result), '')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'entry.ru'
            path.write_text(source, encoding='utf-8')
            result = subprocess.run([str(self.binary), str(path), str(ROOT/'rulang/stdlib'), '甲😀', '42'],
                                    capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual((result.returncode, result.stdout), (7, '[甲😀, 42]\n'), result.stderr)

    def test_invalid_wire_metadata_cannot_execute_a_cell_or_desynchronize_frames(self):
        records = []
        for source, name in (("显 '不应执行'.".encode(), b'bad\0source'),
                             ('显 42.'.encode(), '来源😀'.encode())):
            records.append(f'RU2 E {len(source)} {len(name)}\n'.encode()+source+name)
        result = subprocess.run([str(self.binary), '--stdio', str(ROOT/'rulang/stdlib')],
            input=b''.join(records)+b'RU2 Q 0 0\n', capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [json.loads(line) for line in result.stdout.decode().splitlines()]
        self.assertEqual(''.join(e['text'] for e in events if e['type']=='output'), '42\n')
        self.assertEqual([e['status'] for e in events if e['type']=='done'], ['error','ok'])

    def graphics_event(self, event, *, expected_error=False):
        identity = self.session.snapshot()
        time.sleep(.04)
        self.session.dispatch_graphics(identity['graphics']['canvas_id'], identity['cell_id'],
            identity['execution_count'], identity['generation'], event)
        deadline = time.monotonic()+12
        while time.monotonic() < deadline:
            result = self.session.poll(identity['cursor'])
            if result['state'] == 'dead':
                self.fail(repr(result))
            if not result['graphics_busy'] and not result.get('more'):
                errors = [e for e in result['events'] if e['type']=='error']
                self.assertEqual(bool(errors), expected_error, result)
                return result
            time.sleep(.01)
        self.fail('native graphics timed out: '+repr(self.session.poll()))

    @staticmethod
    def graphics_scenes(result):
        return [{key: value for key, value in e.items() if key not in
                 ('canvas_id','seq','cell_id','execution_count','generation')}
                for e in result['events'] if e['type']=='graphics']

    def test_graphics_primitives_and_callback_scenes_match_python(self):
        from rulang.graphics_runtime import GraphicsHost
        from rulang.interpreter import Interpreter
        from rulang.frontend import parse
        source = """观 取 外言 '如:观'. 图 取 观 其 画布 320 240.
图 其 保存. 图 其 平移 70 40. 图 其 缩放 2 3. 图 其 裁剪 0 0 70 50.
图 其 保存. 图 其 变换 1 0 0 1 5 7. 图 其 裁剪 0 0 40 30.
图 其 填色 (观 其 颜色 255 170 0 128). 图 其 描边 空. 图 其 背景 '#FFFFFF80'.
图 其 线 (1/3) (2/3) 99999.99999999999 1e-20.
图 其 三角形 0 0 20 0 10 20. 点 取 [[0,0],[30,0],[30,20]]. 图 其 多边形 点. 点[0][0] 取 99.
图 其 矩形 1 2 3 4. 图 其 椭圆 1 2 3 4. 图 其 扇形 1 2 3 4 (-1) 7.
图 其 弧 1 2 3 4 8 (-9). 图 其 贝塞尔 1 2 3 4 5 6 7 8.
图 其 文字对齐 '中' '基线'. 图 其 文字 '变换😀' 1 2. 图 其 描边 '#000000'. 图 其 线 1 2 3 4.
图 其 折线 [[1,2],[3,4]]. 图 其 恢复. 图 其 矩形 0 0 10 10.
图 其 取消裁剪. 图 其 重置变换. 图 其 旋转 0. 图 其 缩放 (-1) 0. 图 其 矩形 0 0 10 10.
图 其 恢复. 图 其 矩形 0 0 10 10. 次数 取 [0].
图 其 每帧 (作 帧: 次数[0] 取 次数[0]+1. 图 其 矩形 帧 次数[0] 10 10. 为).
图 其 鼠标移动 (作 横 纵: 图 其 矩形 横 纵 10 10. 为).
图 其 鼠标松开 (作 横 纵 键: 图 其 线 横 纵 键 4. 为).
图 其 按键 (作 键: 若 键 == '😀\n键' 则 显 次数[0]. 然. 为).
图 其 松键 (作 键: 图 其 文字 键 2 3. 为).
"""
        events = [{'type':'frame'}, {'type':'frame'}, {'type':'mouse_move','x':31,'y':42,'button':0},
                  {'type':'mouse_up','x':3,'y':4,'button':2},
                  {'type':'key_down','key':'😀\n键'}, {'type':'key_up','key':'😀\n键'}]
        expected = []
        host = GraphicsHost(Interpreter(), expected.append)
        self.addCleanup(host.close)
        host.interpreter.execute(parse(source)); host.flush()
        for event in events:
            host.handle(event)
        with patch('rulang.graphics_runtime.GraphicsHost.create', side_effect=AssertionError('Python canvas')), \
                patch('rulang.graphics_runtime.GraphicsHost.handle', side_effect=AssertionError('Python callback')):
            actual = self.graphics_scenes(self.run_cell(source, 'graphics'))
            for event in events:
                actual.extend(self.graphics_scenes(self.graphics_event(event)))
        expected = [{k:v for k,v in e.items() if k!='canvas_id'} for e in expected if e['type']=='graphics']
        self.assertEqual(actual, expected)

    def test_graphics_cache_is_immutable_once_per_canvas_and_old_handles_expire(self):
        result = self.run_cell("""观 取 外言 '如:观'. 图 取 观 其 画布 100 80. 次数 取 [0]. 逃 取 [空].
点 取 [[1,2],[3,4],[5,6]]. 图 其 填色 '#ffffff'. 图 其 平移 9 9.
像 取 图 其 缓存 20 10 (作 层: 逃[0] 取 层. 次数[0] 取 次数[0]+1.
 层 其 保存. 层 其 平移 2 3. 层 其 裁剪 0 0 8 8. 层 其 多边形 点. 层 其 恢复. 为).
点[0][0] 取 99. 图 其 贴图 像 0 0.
图 其 每帧 (作 帧: 图 其 贴图 像 0 0. 图 其 贴图 像 帧 2. 显 次数[0]. 为).
""", 'cache')
        self.assertEqual(result['events'][-1]['status'], 'ok', result)
        scene = self.graphics_scenes(result)[-1]
        self.assertEqual(scene['commands'][0]['transform'], [1,0,0,1,9,9])
        recipe = scene['resources'][0]['commands'][0]
        self.assertEqual(recipe['points'][0], [1,2])
        self.assertEqual(recipe['fill'], '#4677ff')
        self.assertEqual(recipe['transform'], [1,0,0,1,2,3])
        for _ in range(2):
            result = self.graphics_event({'type':'frame'})
            self.assertEqual(reference.output(result), '1\n')
            self.assertEqual(len(self.graphics_scenes(result)[-1]['resources']), 1)
        result = self.run_cell('显 像 其 宽. 显 像 其 高. 另图 取 观 其 画布 20 20. 另图 其 贴图 像 0 0.')
        self.assertEqual(reference.output(result), '20\n10\n')
        self.assertEqual(result['events'][-1]['status'], 'error')
        self.assertIsNone(result['graphics'])
        result = self.run_cell('逃[0] 其 宽.')
        self.assertIn('已关闭', next(e['message'] for e in result['events'] if e['type']=='error'))

    def test_graphics_close_race_input_failure_and_new_cell_detachment(self):
        source = "观 取 外言 '如:观'. 图 取 观 其 画布 10 10. 值 取 7. 图 其 每帧 (作 帧: 图 其 矩形 帧 1 2 3. 为)."
        result = self.run_cell(source, 'scene')
        self.assertIsNotNone(result['graphics'], result)
        canvas = result['graphics']['canvas_id']
        with self.session.lock:
            self.session.dispatch_graphics(canvas, 'scene', 1, 1, {'type':'frame'})
            pending = self.session.dispatch_graphics(canvas, 'scene', 1, 1, {'type':'close'})
            self.assertTrue(pending['graphics_close_pending'])
        deadline = time.monotonic()+5
        while self.session.snapshot()['graphics_busy'] and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertIsNone(self.session.snapshot()['graphics'])
        self.assertEqual(reference.output(self.run_cell('显 值.')), '7\n')
        with self.assertRaises(KernelError):
            self.session.dispatch_graphics(canvas, 'scene', 1, 1, {'type':'close'})
        result = self.run_cell("图 取 观 其 画布 10 10. 图 其 每帧 (作 帧: 显 读. 为).", 'input')
        result = self.graphics_event({'type':'frame'}, expected_error=True)
        self.assertIsNone(result['graphics'])
        self.assertFalse(any(e['type']=='input_request' for e in result['events']))
        self.assertTrue(any('如观回调不能请求交互输入' in e.get('message','') for e in result['events']))
        self.assertEqual(self.session.snapshot()['generation'], 1)

    def test_graphics_callback_soft_budget_closes_canvas_and_preserves_state(self):
        result = self.run_cell("观 取 外言 '如:观'. 图 取 观 其 画布 10 10. 值 取 17. 图 其 每帧 (作 帧: 循 环. 为).", 'budget')
        self.assertIsNotNone(result['graphics'], result)
        started = time.monotonic()
        result = self.graphics_event({'type':'frame'}, expected_error=True)
        self.assertLess(time.monotonic()-started, 5)
        self.assertIsNone(result['graphics'])
        self.assertTrue(any('预算' in e.get('message','') for e in result['events']), result)
        self.assertEqual(reference.output(self.run_cell('显 值.')), '17\n')
        self.assertEqual(self.session.snapshot()['generation'], 1)

    def test_continue_cannot_evade_native_graphics_budget(self):
        result = self.run_cell("观 取 外言 '如:观'. 图 取 观 其 画布 10 10. 值 取 23. 图 其 每帧 (作 帧: 循 续. 环. 为).", 'continue-budget')
        self.assertIsNotNone(result['graphics'], result)
        started = time.monotonic()
        result = self.graphics_event({'type':'frame'}, expected_error=True)
        self.assertLess(time.monotonic()-started, 5)
        self.assertIsNone(result['graphics'])
        self.assertTrue(any('预算' in e.get('message','') for e in result['events']), result)
        self.assertEqual(reference.output(self.run_cell('显 值.')), '23\n')
        self.assertEqual(self.session.snapshot()['generation'], 1)

    def test_graphics_monotonic_time_pause_resume_and_event_cache_restriction(self):
        from test_graphics_time_transport import SOURCE
        result = self.run_cell(SOURCE, 'timing')
        self.assertIsNotNone(result['graphics'], result)
        def command(result):
            return self.graphics_scenes(result)[-1]['commands'][0]
        initial = command(result)
        self.assertEqual((initial['x'],initial['y']), (0,0))
        first = command(self.graphics_event({'type':'frame'}))
        self.assertGreater(first['x'], 0)
        self.assertEqual((first['y'],first['width']), (0,1))
        key = command(self.graphics_event({'type':'key_down','key':'x'}))
        self.assertEqual((key['y'],key['width']), (0,99))
        second = command(self.graphics_event({'type':'frame'}))
        self.assertAlmostEqual(second['y'],second['x']-first['x'],places=8)
        self.assertGreater(second['y'],second['x']-key['x'])
        paused = self.graphics_event({'type':'key_down','key':'p'})
        self.assertFalse(paused['graphics']['running'])
        self.graphics_event({'type':'key_down','key':'r'})
        resumed = command(self.graphics_event({'type':'frame'}))
        self.assertEqual(resumed['y'],0)
        self.assertGreater(resumed['x'],second['x'])
        self.run_cell("观 取 外言 '如:观'. 图 取 观 其 画布 10 10. 图 其 按键 (作 键: 另图 取 观 其 画布 10 10. 另图 其 缓存 1 1 (作 层: 为). 为).", 'cache-phase')
        failed = self.graphics_event({'type':'key_down','key':'x'}, expected_error=True)
        self.assertTrue(any('初始化' in e.get('message','') for e in failed['events']), failed)
        self.assertIsNone(failed['graphics'])

    def test_graphics_invalid_members_and_resource_budgets_are_recoverable(self):
        prefix = "观 取 外言 '如:观'. 图 取 观 其 画布 100 80. "
        cases = ("图 其 填色 '#gg0000'.", "图 其 文字对齐 [] '中'.", "图 其 矩形 0 0 (-1) 2.",
                 '图 其 保存.', '图 其 恢复.', '循 65 次 图 其 保存. 环.',
                 '循 33 次 图 其 裁剪 0 0 2 2. 环.',
                 '循 2049 次 图 其 矩形 0 0 1 1. 环.',
                 '循 9 次 像 取 图 其 缓存 1 1 (作 层: 为). 环.',
                 '像 取 图 其 缓存 2048 2048 (作 层: 为). 像二 取 图 其 缓存 1 1 (作 层: 为).',
                 '图 其 缓存 1 1 (作 层: 图 其 填色 空. 为).',
                 '图 其 缓存 1 1 (作 层: 层 其 贴图 空 0 0. 为).')
        for code in cases:
            with self.subTest(source=code):
                result = self.run_cell(prefix+code, 'invalid')
                self.assertEqual(result['events'][-1]['status'], 'error', result)
                self.assertIsNone(result['graphics'])
                self.assertEqual(reference.output(self.run_cell('显 42.')), '42\n')

    def test_graphics_existing_examples_initialize_animate_and_handle_input(self):
        examples = sorted((ROOT/'rushu/examples/ruguan').glob('*.ru'))
        self.assertEqual(len(examples), 12)
        for path in examples:
            with self.subTest(example=path.name):
                self.session.reset('restart')
                if path.name == 'interactive-bars.ru':
                    self.run_cell('数据 取 [10,20,30].', 'data')
                result = self.run_cell(path.read_text(encoding='utf-8'), path.stem)
                self.assertEqual(result['events'][-1]['status'], 'ok', result)
                self.assertIsNotNone(result['graphics'], result)
                if path.name == 'cached-solar-system.ru':
                    self.assertEqual(len(self.graphics_scenes(result)[-1]['resources'][0]['commands']), 515)
                if result['graphics']['running'] and 'frame' in result['graphics']['handlers']:
                    result = self.graphics_event({'type':'frame'})
                    self.assertTrue(self.graphics_scenes(result), result)
                    if path.name == 'cached-solar-system.ru':
                        self.assertEqual(len(self.graphics_scenes(result)[-1]['commands']), 28)
                if 'mouse_move' in result['graphics']['handlers']:
                    self.graphics_event({'type':'mouse_move','x':30,'y':40,'button':0})

    def test_graphics_utf8_bytes_and_combined_recipe_commands_are_bounded(self):
        text = "'"+'画'*4096+"'"
        prefix = "观 取 外言 '如:观'. 图 取 观 其 画布 100 80. 文 取 "+text+'. '
        cases = (
            ('循 24 次 图 其 文字 文 0 0. 环.', '256 KiB'),
            ('像 取 图 其 缓存 20 10 (作 层: 循 12 次 层 其 文字 文 0 0. 环. 为).', '128 KiB'),
            ('像 取 图 其 缓存 20 10 (作 层: 循 10 次 层 其 文字 文 0 0. 环. 为). '
             '图 其 贴图 像 0 0. 循 12 次 图 其 文字 文 0 0. 环.', '完整绘图帧'),
            ('像一 取 图 其 缓存 1 1 (作 层: 层 其 描边 空. 循 800 次 层 其 线 0 0 1 1. 环. 为). '
             '像二 取 图 其 缓存 1 1 (作 层: 层 其 描边 空. 循 800 次 层 其 线 0 0 1 1. 环. 为). '
             '图 其 贴图 像一 0 0. 图 其 贴图 像二 0 0. 循 447 次 图 其 贴图 像一 0 0. 环.',
             '根命令与引用缓存配方'))
        for code, message in cases:
            with self.subTest(budget=message):
                failed = self.run_cell(prefix+code, 'bytes')
                self.assertEqual(failed['events'][-1]['status'],'error',failed)
                self.assertTrue(any(message in e.get('message','') for e in failed['events']), failed)
                self.assertIsNone(failed['graphics'])
                self.assertEqual(self.graphics_scenes(failed), [])
                self.assertEqual(reference.output(self.run_cell('显 42.')), '42\n')

    def test_graphics_callback_heap_growth_budget_is_recoverable(self):
        source = ("大 取 ['"+'x'*1024+"']. 观 取 外言 '如:观'. 图 取 观 其 画布 10 10. "
                  "图 其 每帧 (作 帧: 循 17 次 大[0] 取 大[0]+大[0]. 环. 为).")
        result = self.run_cell(source, 'memory')
        self.assertIsNotNone(result['graphics'], result)
        failed = self.graphics_event({'type':'frame'}, expected_error=True)
        self.assertTrue(any('内存超过分配预算' in e.get('message','') for e in failed['events']), failed)
        self.assertIsNone(failed['graphics'])
        self.assertEqual(self.session.snapshot()['generation'],1)
        self.assertEqual(reference.output(self.run_cell("大 取 ['']. 显 42.")), '42\n')

    def test_graphics_watchdog_replaces_a_native_process_blocked_on_os_input(self):
        # A native transport fixture deliberately blocks in getchar after a
        # callback request. Guest evaluation is covered by the actual Ru tests;
        # this independently exercises Popen termination, pipes and the timer.
        code = r'''
#include <stdio.h>
static void receive(void) {
    char header[100],kind;unsigned long long a,b;
    if(!fgets(header,sizeof(header),stdin)||sscanf(header,"RU2 %c %llu %llu",&kind,&a,&b)!=3)return;
    while(a--)getchar();while(b--)getchar();
}
int main(void) {
    puts("{\"type\":\"ready\",\"protocol\":2,\"engine\":\"ru-ast\"}");fflush(stdout);
    receive();
    puts("{\"type\":\"graphics\",\"canvas_id\":\"blocked\",\"width\":10,\"height\":10,\"fps\":30,\"running\":true,\"handlers\":[\"frame\"],\"commands\":[]}");
    puts("{\"type\":\"done\",\"status\":\"ok\"}");fflush(stdout);
    receive();while(1)getchar();
}
'''
        with tempfile.TemporaryDirectory(prefix='ru-native-watchdog-') as temp:
            source = Path(temp)/'blocked.c'
            binary = Path(temp)/('blocked.exe' if sys.platform=='win32' else 'blocked')
            source.write_text(code, encoding='utf-8')
            TOOLCHAIN.run(TOOLCHAIN.clang+['-std=c99',str(source),'-o',str(binary),*TOOLCHAIN.link_flags])
            session = Session(native_kernel=binary)
            try:
                session.execute('', 'blocked')
                reference.wait_for(session)
                pid = session.process.pid
                started = time.monotonic()
                session.dispatch_graphics('blocked','blocked',1,1,{'type':'frame'})
                deadline = started+18
                while session.snapshot()['generation']==1 and time.monotonic()<deadline:
                    time.sleep(.02)
                result = session.poll()
                self.assertEqual(result['generation'],2,result)
                self.assertEqual(result['execution_count'],0)
                self.assertNotEqual(session.process.pid,pid)
                self.assertIsNone(result['graphics'])
                self.assertFalse(result['graphics_busy'])
                self.assertGreaterEqual(time.monotonic()-started,10)
                self.assertTrue(any('上下文已清空' in e.get('message','') for e in result['events']))
            finally:
                session.close()
