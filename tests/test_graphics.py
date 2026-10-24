"""Real Ru callbacks and bounded declarative scenes, with no JavaScript eval."""
import gc
import time
import io
import unittest
import sys
import tracemalloc
import weakref
from unittest.mock import patch

from rulang.frontend import parse, RuError
from rulang.interpreter import Interpreter
from rulang.graphics_runtime import GraphicsHost
from rulang.compiler import Compiler
from rulang.js_compiler import JSCompiler


class GraphicsTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.output = io.StringIO()
        self.interpreter = Interpreter(stdout=self.output)
        self.host = GraphicsHost(self.interpreter, self.events.append)
    def tearDown(self):
        self.host.close()
    def run_ru(self, source):
        self.interpreter.execute(parse(source))
        self.host.flush()
    def canvas(self, code=''):
        self.run_ru("观 取 外言 '如:观'. 图 取 观 其 画布 320 200. " + code)
    def test_static_commands_and_null_style(self):
        self.canvas("图 其 背景 '#FFFFFF'. 图 其 填色 空. 图 其 描边 '#AA11CC'. 图 其 线宽 3. 图 其 矩形 1 2 30 40. 图 其 填色 '#000000'. 图 其 字号 24. 图 其 文字 '你好<script>' 5 6. 图 其 线 1 2 3 4.")
        commands = self.events[-1]['commands']
        self.assertEqual([c['op'] for c in commands], ['background','rect','text','line'])
        self.assertEqual(commands[1]['fill'], '')
        self.assertEqual(commands[1]['stroke'], '#aa11cc')
        self.assertEqual(commands[2]['text'], '你好<script>')
        self.assertEqual(self.host.snapshot()['handlers'], [])
    def test_callbacks_share_real_ru_data_and_state(self):
        self.run_ru("数据 取 [10,20,30]. 位置 取 [0,0]. 键名 取 [''].")
        self.canvas("图 其 每帧 (作 帧: 图 其 背景 '#ffffff'. 图 其 矩形 帧 0 数据[1] 10. 为). 图 其 鼠标按下 (作 横 纵 键: 位置[0] 取 横. 位置[1] 取 纵. 数据[1] 取 99. 为). 图 其 按键 (作 键: 键名[0] 取 键. 为).")
        self.host.handle({'type':'frame'})
        self.assertEqual(self.events[-1]['commands'][1]['width'],20)
        self.host.handle({'type':'mouse_down','x':17,'y':29,'button':0})
        self.host.handle({'type':'key_down','key':'ArrowLeft'})
        self.host.handle({'type':'frame'})
        self.assertEqual(self.events[-1]['commands'][1]['width'],99)
        self.assertEqual(self.events[-1]['commands'][1]['x'],2)
        self.assertEqual(self.interpreter.global_scope.values['位置'],[17.,29.])
        self.assertEqual(self.interpreter.global_scope.values['键名'],['ArrowLeft'])
    def test_static_interaction_pause_resume_and_close(self):
        self.canvas("图 其 鼠标移动 (作 横 纵: 图 其 椭圆 横 纵 10 10. 为).")
        self.host.handle({'type':'mouse_move','x':12,'y':13})
        self.assertEqual(self.events[-1]['commands'][0]['x'],12)
        self.run_ru("图 其 每帧 (作 帧: 图 其 线 帧 0 1 1. 为). 图 其 停.")
        self.assertFalse(self.host.snapshot()['running'])
        with self.assertRaisesRegex(RuError,'未启用'): self.host.handle({'type':'frame'})
        self.host.handle({'type':'mouse_move','x':1,'y':2})
        self.run_ru('图 其 继续.')
        self.assertTrue(self.host.snapshot()['running'])
        self.host.handle({'type':'frame'})
        self.run_ru('图 其 关闭.')
        self.assertIsNone(self.host.snapshot())
        self.assertEqual(self.events[-1]['type'],'graphics_closed')
        with self.assertRaisesRegex(RuError,'已关闭'): self.run_ru('图 其 宽.')
    def test_new_canvas_releases_callbacks_and_old_instance_invalid(self):
        self.canvas('图 其 每帧 (作 帧: 图 其 线 0 0 帧 1. 为).')
        old = self.host.canvas
        self.run_ru('图二 取 观 其 画布 20 20.')
        self.assertTrue(old.closed)
        self.assertEqual(old.callbacks,{})
        self.assertEqual(old.commands,[])
        with self.assertRaisesRegex(RuError,'已关闭'): self.run_ru('图 其 背景 \'#000000\'.')
        self.host.begin_execution()
        self.assertIsNone(self.host.snapshot())
    def test_validation(self):
        for code in ("观 其 画布 0 1.","观 其 画布 1 2049.","观 其 画布 1.2 1.",
                     "图 其 填色 'red'.", "图 其 帧率 31.", "图 其 线宽 0.",
                     "图 其 每帧 1.", "图 其 按键 (作: 为).", "图 其 字号 257."):
            with self.subTest(code=code):
                self.host.close()
                self.canvas()
                with self.assertRaises(RuError): self.run_ru(code)
    def test_cpu_limit_closes_graphics_and_preserves_context(self):
        self.run_ru('保留 取 7.')
        self.canvas('图 其 每帧 (作 帧: 循 环. 为).')
        with self.assertRaisesRegex(RuError,'预算'): self.host.handle({'type':'frame'})
        self.assertIsNone(self.host.snapshot())
        self.assertEqual(self.interpreter.global_scope.values['保留'],7.)
    def test_callback_limits_are_tenfold_with_other_quotas_unchanged(self):
        from rulang import graphics_runtime as runtime
        from rushu.kernel import GRAPHICS_TIMEOUT
        self.assertEqual(runtime.MAX_CALLBACK_SECONDS, 1.0)
        self.assertEqual(runtime.MAX_CALLBACK_LINES, 500000)
        self.assertEqual(GRAPHICS_TIMEOUT, 10.0)
        self.assertEqual(GRAPHICS_TIMEOUT / runtime.MAX_CALLBACK_SECONDS, 10)
        self.assertEqual(runtime.MAX_GRAPHICS_MEMORY, 64 * 1024 * 1024)
        self.assertEqual(runtime.MAX_COMMANDS, 2048)
        self.assertEqual(runtime.MAX_FRAME_BYTES, 262144)

    def test_callback_above_old_wall_budget_survives(self):
        self.canvas('图 其 每帧 (作 帧: 图 其 线 帧 0 1 1. 为).')
        invoke = self.interpreter.invoke_value
        def delayed(*args):
            time.sleep(.15)
            return invoke(*args)
        started = time.monotonic()
        with patch.object(self.interpreter, 'invoke_value', side_effect=delayed):
            self.host.handle({'type': 'frame'})
        self.assertGreaterEqual(time.monotonic() - started, .15)
        self.assertIsNotNone(self.host.snapshot())
        self.assertEqual(self.events[-1]['commands'][0]['x1'], 1)

    def test_new_wall_budget_still_closes_callback(self):
        self.canvas('图 其 每帧 (作 帧: 图 其 线 0 0 1 1. 为).')
        invoke = self.interpreter.invoke_value
        def delayed(*args):
            time.sleep(1.05)
            return invoke(*args)
        with patch.object(self.interpreter, 'invoke_value', side_effect=delayed):
            with self.assertRaisesRegex(RuError, '时间预算.*阈值 1 秒'):
                self.host.handle({'type': 'frame'})
        self.assertIsNone(self.host.snapshot())
        self.run_ru('显 42.')
        self.assertEqual(self.output.getvalue(), '42\n')

    def test_line_budget_survives_old_limit_and_stops_at_new_limit(self):
        self.canvas('图 其 每帧 (作 帧: 图 其 线 0 0 1 1. 为).')
        invoke = self.interpreter.invoke_value
        def traced_work(*args):
            # Two traced Python lines per iteration; elapsed time is isolated.
            for _ in range(30000):
                pass
            return invoke(*args)
        with patch('rulang.graphics_runtime.time.monotonic', return_value=0):
            with patch.object(self.interpreter, 'invoke_value', side_effect=traced_work):
                self.host.handle({'type': 'frame'})
            self.assertIsNotNone(self.host.snapshot())
            self.run_ru('图 其 每帧 (作 帧: 循 环. 为).')
            with self.assertRaisesRegex(RuError, '执行行预算.*阈值 500000 行'):
                self.host.handle({'type': 'frame'})
        self.assertIsNone(self.host.snapshot())

    def test_exact_trace_counter_boundaries_and_check_cadence(self):
        # Supply exact line events without tracing unittest/mock infrastructure.
        # Production sys.settrace still covers all Python frames unchanged.
        for count in (0, 127, 128, 129, 499999, 500000, 500001, 500096):
            with self.subTest(count=count):
                self.canvas('图 其 每帧 (作 帧: 为).')
                traces = []
                seen = 0
                def invoke(*args):
                    nonlocal seen
                    trace = traces[0]
                    for seen in range(1, count + 1):
                        trace(None, 'line', None)
                with patch('rulang.graphics_runtime.sys.settrace', side_effect=traces.append), \
                     patch('rulang.graphics_runtime.time.monotonic', return_value=0), \
                     patch.object(self.interpreter, 'invoke_value', side_effect=invoke):
                    if count <= 500000:
                        self.host.handle({'type': 'frame'})
                        self.assertIsNotNone(self.host.canvas)
                    else:
                        with self.assertRaisesRegex(RuError, '500000 行'):
                            self.host.handle({'type': 'frame'})
                        self.assertIsNone(self.host.canvas)
                self.assertEqual(seen, count)
                self.assertEqual(len(traces), 2)  # install and restore on both paths
        # The previous implementation checks at multiples of 128, so the first
        # in-callback failure is 500096; final check catches shorter overruns.
        self.canvas('图 其 每帧 (作 帧: 为).')
        traces = []
        seen = 0
        def invoke(*args):
            nonlocal seen
            for seen in range(1, 500200):
                traces[0](None, 'line', None)
        with patch('rulang.graphics_runtime.sys.settrace', side_effect=traces.append), \
             patch('rulang.graphics_runtime.time.monotonic', return_value=0), \
             patch.object(self.interpreter, 'invoke_value', side_effect=invoke):
            with self.assertRaisesRegex(RuError, '500000 行'):
                self.host.handle({'type': 'frame'})
        self.assertEqual(seen, 500096)

    def test_canvas_parameter_schema_is_immutable(self):
        from rulang.graphics_runtime import CANVAS_PARAMS
        with self.assertRaises(TypeError):
            CANVAS_PARAMS['文字'] = ('横',)
        self.assertTrue(all(isinstance(params, tuple) for params in CANVAS_PARAMS.values()))

    def test_memory_limit(self):
        self.canvas('图 其 每帧 (作 帧: 图 其 线 0 0 1 1. 为).')
        with patch('rulang.graphics_runtime.MAX_GRAPHICS_MEMORY',-1):
            with self.assertRaisesRegex(RuError,'内存'): self.host.handle({'type':'frame'})
        self.assertIsNone(self.host.snapshot())
    def test_real_ru_allocations_trigger_memory_budget(self):
        # Exercise real Ru concatenation allocations; lower the same production
        # accounting threshold so the test does not reserve tens of MiB.
        self.canvas("图 其 每帧 (作 帧: 文 取 '" + 'x' * 8192 + "'. 循 9 次 文 取 文 + 文. 环 为).")
        with patch('rulang.graphics_runtime.MAX_GRAPHICS_MEMORY', 1024 * 1024):
            with self.assertRaisesRegex(RuError, '内存'):
                self.host.handle({'type':'frame'})
        self.assertIsNone(self.host.snapshot())

    def test_command_limit(self):
        self.canvas()
        with patch('rulang.graphics_runtime.MAX_COMMANDS',1):
            self.run_ru('图 其 线 0 0 1 1.')
            with self.assertRaisesRegex(RuError,'2048'): self.run_ru('图 其 线 1 1 2 2.')
    def test_callback_exception_closes_and_does_not_break_python(self):
        self.canvas('图 其 每帧 (作 帧: 显 未定义. 为).')
        with self.assertRaises(RuError): self.host.handle({'type':'frame'})
        self.run_ru('显 42.')
        self.assertEqual(self.output.getvalue(),'42\n')
    def test_cli_and_compilers_explicitly_reject(self):
        source="尽取 外言 '如:观'. 图 取 画布 20 20."
        with self.assertRaisesRegex(RuError,'仅在如书'): Interpreter().execute(parse(source))
        # C 后端已支持如观图形运行时（见 tests/test_ruui_c_graphics_parity.py），
        # 只有 JS 后端仍显式拒绝。
        with self.assertRaisesRegex(RuError,'如书 Python'): JSCompiler(parse(source)).compile()
        self.assertTrue(Compiler(parse(source)).compile())
    def test_documentation_and_interactive_data_book_repeat(self):
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        blocks = re.findall(r"```ru\n(.*?)```", (root / 'docs/ruguan-guide.md').read_text(), re.S)
        for source in blocks:
            for _ in range(2):
                self.host.begin_execution()
                self.run_ru(source)
                if self.host.snapshot()['running']:
                    self.host.handle({'type':'frame'})
        self.run_ru('数据 取 [10,20,30].')
        source = (root / 'rushu/examples/ruguan/interactive-bars.ru').read_text()
        for _ in range(2):
            self.host.begin_execution()
            self.run_ru(source)
            self.host.handle({'type':'mouse_down','x':70,'y':180,'button':0})
            self.assertEqual(self.interpreter.global_scope.values['数据'][0],15.)
            self.assertEqual(self.events[-1]['commands'][1]['height'],75.)
            self.host.handle({'type':'key_down','key':'r'})
            self.assertEqual(self.interpreter.global_scope.values['数据'],[10.,20.,30.])

    def test_callback_can_replace_canvas_and_publish_new_scene(self):
        self.canvas("图 其 每帧 (作 帧: 新图 取 观 其 画布 40 50. 新图 其 矩形 1 2 3 4. 为).")
        old_id = self.host.canvas_id
        self.host.handle({'type': 'frame'})
        self.assertNotEqual(self.host.canvas_id, old_id)
        self.assertEqual(self.events[-1]['type'], 'graphics')
        self.assertEqual(self.events[-1]['canvas_id'], self.host.canvas_id)
        self.assertEqual(self.events[-1]['commands'][0]['op'], 'rect')

    def test_same_cell_draw_and_close_publishes_static_then_releases_tracing(self):
        self.assertFalse(tracemalloc.is_tracing())
        self.canvas("图 其 矩形 1 2 3 4. 图 其 关闭.")
        self.assertEqual([event['type'] for event in self.events], ['graphics', 'graphics_closed'])
        self.assertEqual(self.events[0]['commands'][0]['op'], 'rect')
        self.assertFalse(tracemalloc.is_tracing())
        self.assertFalse(self.host.owns_tracing)
        self.assertIsNone(self.host.canvas)

    def test_exception_keeps_last_frame_without_publishing_partial_drawing(self):
        self.canvas("图 其 矩形 1 2 3 4. 图 其 每帧 (作 帧: 图 其 线 9 9 9 9. 显 未定义. 为).")
        previous = [event for event in self.events if event['type'] == 'graphics']
        with self.assertRaises(RuError):
            self.host.handle({'type': 'frame'})
        self.assertEqual([event for event in self.events if event['type'] == 'graphics'], previous)
        self.assertEqual(self.events[-1]['type'], 'graphics_closed')

    def test_closed_canvas_releases_anonymous_callback_function(self):
        self.canvas("图 其 每帧 (作 帧: 图 其 矩形 帧 1 2 3. 为).")
        reference = weakref.ref(self.host.canvas.callbacks['frame'][0])
        self.host.close()
        gc.collect()
        self.assertIsNone(reference())

    def test_callback_never_tightens_process_address_space_limit(self):
        try:
            import resource
        except ImportError:
            self.skipTest('POSIX resource limits unavailable')
        if not hasattr(resource, 'RLIMIT_AS'):
            self.skipTest('RLIMIT_AS unavailable')
        original_trace = sys.gettrace()
        with patch.object(resource, 'setrlimit') as setter:
            self.canvas("图 其 每帧 (作 帧: 图 其 线 0 0 1 1. 为).")
            self.host.handle({'type': 'frame'})
            self.run_ru("图 其 每帧 (作 帧: 显 未定义. 为).")
            with self.assertRaises(RuError):
                self.host.handle({'type': 'frame'})
        setter.assert_not_called()
        self.assertIs(sys.gettrace(), original_trace)

    def test_local_same_named_module_is_not_reserved(self):
        import tempfile
        from pathlib import Path
        from rulang.modules import load_module_graph
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '如观.ru').write_text('算 数值: 得 7. 法', encoding='utf-8')
            main = root / 'main.ru'
            main.write_text("观 取 外言 './如观.ru'. 显 观 其 数值.", encoding='utf-8')
            graph = load_module_graph(main)
            for compiler in (Compiler, JSCompiler):
                self.assertTrue(compiler(graph[graph.root], str(main), modules=graph).compile())
            (root / 'wrapper.ru').write_text("观 取 外言 '如:观'.", encoding='utf-8')
            main.write_text("外 取 外言 './wrapper.ru'.", encoding='utf-8')
            graph = load_module_graph(main)
            # wrapper 直接引用保留模块 如:观：JS 拒绝，C 已支持图形运行时。
            self.assertTrue(Compiler(graph[graph.root], str(main), modules=graph).compile())
            with self.assertRaisesRegex(RuError, '如书 Python'):
                JSCompiler(graph[graph.root], str(main), modules=graph).compile()

    def test_no_callbacks_no_implicit_frame(self):
        self.canvas("图 其 背景 '#ffffff'.")
        before = len(self.events)
        self.host.flush()
        self.assertEqual(len(self.events),before)
        self.assertFalse(self.host.snapshot()['running'])


if __name__ == '__main__': unittest.main()
