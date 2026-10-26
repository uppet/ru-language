"""如观 C 图形运行时与 Python GraphicsHost 的帧 parity 测试。

同一批如观程序分别跑两遍：
- Python：Interpreter + GraphicsHost（假时钟 now_seconds，auto_load/auto_services 关，
  services=() 与 record host 的空服务表对齐），脚本驱动事件
- C：Compiler 出 C 源码 + cc 链 rulang/hosts/record_host.c（虚拟时钟 + stdin 脚本协议：
  {"set_now":t} / {"advance":dt} / {"event":{...}}）

比对两端 type=="graphics" 的帧 JSON 完全一致（数字 rel_tol=1e-12；键集合逐层比对）。
帧事件不进脚本：C 侧由 app_run 按虚拟时钟自调度，Python 侧 driver 按同样的
next_frame 递推模拟（帧事件在到达时刻触发，next_frame=触发时刻+1/fps）。
时间值（经过秒/间隔秒）不做跨宿主逐值 parity，用例只用帧号等确定性成员。

需要环境里有 C 编译器（clang/gcc/cc）；无则整文件 skip。
"""
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rulang.compiler import Compiler
from rulang.frontend import RuError, parse
from rulang.graphics_runtime import GraphicsHost
from rulang.interpreter import Interpreter
from rulang.modules import load_module_graph

CC = shutil.which('clang') or shutil.which('gcc') or shutil.which('cc')
RECORD_HOST = ROOT / 'rulang' / 'hosts' / 'record_host.c'

CANVAS = "观 取 外言 '如:观'. 图 取 观 其 画布 320 200. "


def compile_c(source, workdir):
    src = workdir / 'program.ru'
    src.write_text(source, encoding='utf-8')
    program = parse(source)
    modules = load_module_graph(src, program)
    return Compiler(program, str(src), modules=modules).compile()


def run_c(source, script_lines):
    """编译 + 链 record host + 用脚本驱动；返回 (frames, CompletedProcess)。"""
    with tempfile.TemporaryDirectory() as directory:
        workdir = Path(directory)
        c_path = workdir / 'program.c'
        c_path.write_text(compile_c(source, workdir), encoding='utf-8')
        exe = workdir / 'program'
        build = subprocess.run(
            [CC, '-O1', '-std=gnu99', '-I', str(ROOT), str(c_path),
             str(RECORD_HOST), *([] if sys.platform == 'win32' else ['-lm']), '-o', str(exe)],
            capture_output=True, text=True)
        if build.returncode != 0:
            raise AssertionError(f"C 编译失败:\n{build.stderr}")
        script = ''.join(json.dumps(line, ensure_ascii=False) + '\n'
                         for line in script_lines)
        run = subprocess.run([str(exe)], input=script, capture_output=True,
                             text=True, timeout=30)
        frames = []
        for line in run.stdout.splitlines():
            if line.startswith('FRAME '):
                frames.append(json.loads(line[6:]))
        return frames, run


def run_python(source, script_lines):
    """Python GraphicsHost 跑同一程序与同一脚本；返回 graphics 帧列表。"""
    events = []
    clock = [0.0]
    host = GraphicsHost(Interpreter(), events.append,
                        now_seconds=lambda: clock[0],
                        auto_load=False, auto_services=False, services=())
    host.interpreter.execute(parse(source))
    host.flush()
    next_frame = [0.0]

    def pump():
        canvas = host.canvas
        while (canvas is not None and not canvas.closed and canvas.running
               and 'frame' in canvas.callbacks
               and next_frame[0] <= clock[0] + 1e-9):
            host.handle({'type': 'frame'})
            next_frame[0] = clock[0] + 1.0 / canvas.fps

    pump()
    for step in script_lines:
        if 'set_now' in step:
            clock[0] = step['set_now']
        elif 'advance' in step:
            clock[0] += step['advance']
        else:
            host.handle(dict(step['event']))
        pump()
    return [event for event in events if event.get('type') == 'graphics']


def compare_value(test, expected, actual, path=''):
    if isinstance(expected, bool) or isinstance(actual, bool):
        test.assertEqual(expected, actual, path)
    elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        test.assertTrue(
            math.isclose(expected, actual, rel_tol=1e-12, abs_tol=1e-12),
            f"{path}: {expected!r} != {actual!r}")
    elif isinstance(expected, dict) and isinstance(actual, dict):
        test.assertEqual(set(expected), set(actual), f"{path} 键集合")
        for key in expected:
            compare_value(test, expected[key], actual[key], f"{path}.{key}")
    elif isinstance(expected, list) and isinstance(actual, list):
        test.assertEqual(len(expected), len(actual), f"{path} 长度")
        for index, (e_item, a_item) in enumerate(zip(expected, actual)):
            compare_value(test, e_item, a_item, f"{path}[{index}]")
    else:
        test.assertEqual(expected, actual, path)


@unittest.skipUnless(CC, "需要 clang/gcc/cc")
class CGraphicsParityTests(unittest.TestCase):
    def assert_parity(self, source, script=(), normalize=True):
        py_frames = run_python(source, list(script))
        c_frames, run = run_c(source, list(script))
        if normalize:
            for frame in py_frames:
                frame['canvas_id'] = 'c'
        self.assertEqual(run.returncode, 0,
                         f"C 程序退出码 {run.returncode}:\n{run.stderr}")
        self.assertEqual(
            len(py_frames), len(c_frames),
            f"帧数不等：Python {len(py_frames)} 帧 vs C {len(c_frames)} 帧\n"
            f"Python: {json.dumps(py_frames, ensure_ascii=False)[:800]}\n"
            f"C: {json.dumps(c_frames, ensure_ascii=False)[:800]}")
        for index, (py_frame, c_frame) in enumerate(zip(py_frames, c_frames)):
            compare_value(self, py_frame, c_frame, f"frame[{index}]")

    def test_static_shapes_and_style(self):
        self.assert_parity(CANVAS +
            "图 其 背景 '#FFFFFF'. 图 其 填色 '#112233'. 图 其 描边 '#AA11CC'."
            "图 其 线宽 3. 图 其 矩形 1 2 30 40. 图 其 椭圆 5 6 7 8."
            "图 其 椭圆 9 10 11 11. 图 其 线 1 2 3 4. 图 其 三角形 1 2 3 4 5 6."
            "图 其 多边形 [[1,2],[3,4],[5,6]]. 图 其 折线 [[1,2],[3,4]]."
            "图 其 贝塞尔 1 2 3 4 5 6 7 8. 图 其 弧 1 2 3 4 5 6."
            "图 其 扇形 1 2 3 4 5 6. 图 其 文字 '你好' 5 6."
            "图 其 填色 空. 图 其 矩形 1 1 5 5.")

    def test_transforms_clips_state(self):
        self.assert_parity(CANVAS +
            "图 其 填色 '#000000'. 图 其 保存. 图 其 平移 10 20."
            "图 其 旋转 0.5. 图 其 缩放 2 3. 图 其 矩形 1 1 4 4. 图 其 恢复."
            "图 其 变换 1 0.5 0 1 5 5. 图 其 矩形 2 2 4 4. 图 其 重置变换."
            "图 其 裁剪 0 0 50 50. 图 其 矩形 3 3 5 5. 图 其 取消裁剪."
            "图 其 矩形 4 4 6 6. 图 其 文字对齐 '中' '基线'. 图 其 文字 '甲' 1 1."
            "图 其 文字对齐 '右' '下'. 图 其 文字 '乙' 2 2. 图 其 字号 24."
            "图 其 线宽 2.5. 图 其 矩形 5 5 7 7.")

    def test_mouse_key_touch_resize_callbacks(self):
        self.assert_parity(CANVAS +
            "图 其 每帧 (作 帧: 图 其 矩形 帧 0 5 5. 为)."
            "图 其 鼠标按下 (作 横 纵 键: 图 其 椭圆 横 纵 3 3. 为)."
            "图 其 鼠标移动 (作 横 纵: 图 其 线 0 0 横 纵. 为)."
            "图 其 鼠标松开 (作 横 纵 键: 图 其 矩形 横 纵 2 2. 为)."
            "图 其 按键 (作 键: 图 其 文字 键 1 1. 为)."
            "图 其 松键 (作 键: 图 其 文字 键 2 2. 为)."
            "图 其 触下 (作 号 横 纵: 图 其 椭圆 横 纵 号 号. 为)."
            "图 其 触移 (作 号 横 纵: 图 其 椭圆 横 纵 号 号. 为)."
            "图 其 触松 (作 号 横 纵: 图 其 椭圆 横 纵 号 号. 为)."
            "图 其 改尺寸 (作 宽 高: 图 其 矩形 0 0 宽 高. 为).",
            [{'advance': 0.05},
             {'event': {'type': 'mouse_down', 'x': 7, 'y': 8, 'button': 0}},
             {'event': {'type': 'mouse_move', 'x': 9, 'y': 10}},
             {'event': {'type': 'key_down', 'key': 'ArrowLeft'}},
             {'event': {'type': 'key_up', 'key': 'ArrowRight'}},
             {'event': {'type': 'mouse_up', 'x': 11, 'y': 12, 'button': 2}},
             {'event': {'type': 'touch_start', 'id': 1, 'x': 13, 'y': 14}},
             {'event': {'type': 'touch_move', 'id': 1, 'x': 15, 'y': 16}},
             {'event': {'type': 'touch_end', 'id': 1, 'x': 17, 'y': 18}},
             {'event': {'type': 'resize', 'width': 200, 'height': 100}},
             {'advance': 0.05}])

    def test_frame_counter(self):
        self.assert_parity(CANVAS +
            "图 其 每帧 (作 帧: 图 其 背景 '#101010'. 图 其 文字 (帧 为 句) 5 5. 为).",
            [{'advance': 0.04}, {'advance': 0.04}, {'advance': 0.04}])

    def test_pause_resume_and_size(self):
        # 停/继续/尺寸 成员在事件之间运行：两段脚本各自成帧。
        self.assert_parity(CANVAS +
            "图 其 每帧 (作 帧: 图 其 矩形 帧 0 5 5. 为). 图 其 停."
            "图 其 尺寸 100 50. 图 其 矩形 1 1 10 10. 图 其 继续.",
            [{'advance': 0.05}, {'advance': 0.05}])

    def test_cache_draw_release(self):
        self.assert_parity(CANVAS +
            "像 取 图 其 缓存 20 10 (作 层: 层 其 矩形 1 2 3 4. 层 其 填色 '#112233'. 为)."
            "图 其 贴图 像 0 0. 图 其 贴图 像 20 10.")

    def test_image_request_ready(self):
        self.assert_parity(CANVAS +
            "图 其 图请求 1 'assets/pic.png'."
            "图 其 图就绪 (作 号 宽 高: 图 其 文字 (宽 为 句) 1 1. 为)."
            "图 其 图失败 (作 号 错: 图 其 文字 错 1 1. 为).",
            [{'event': {'type': 'image_ready', 'id': 1, 'width': 64, 'height': 32}}])

    def test_image_request_failed(self):
        self.assert_parity(CANVAS +
            "图 其 图请求 7 'missing.png'."
            "图 其 图就绪 (作 号 宽 高: 图 其 文字 (宽 为 句) 1 1. 为)."
            "图 其 图失败 (作 号 错: 图 其 文字 错 1 1. 为).",
            [{'event': {'type': 'image_failed', 'id': 7, 'error': '没找着'}}])

    def test_file_request_ready(self):
        self.assert_parity(CANVAS +
            "图 其 件请求 3 'data.txt' '文'."
            "图 其 件就绪 (作 号 文: 图 其 文字 文 1 1. 为)."
            "图 其 件失败 (作 号 错: 图 其 文字 错 1 1. 为).",
            [{'event': {'type': 'file_ready', 'id': 3, 'text': '内容'}}])

    def test_file_request_failed(self):
        self.assert_parity(CANVAS +
            "图 其 件请求 4 'data.bin' 'base64'."
            "图 其 件就绪 (作 号 文: 图 其 文字 文 1 1. 为)."
            "图 其 件失败 (作 号 错: 图 其 文字 错 1 1. 为).",
            [{'event': {'type': 'file_failed', 'id': 4, 'error': '读不了'}}])

    def test_text_input_events(self):
        # 注意：连续回调注册之间要夹普通绘制语句——前端在特定语句序列下会吞掉
        # 后续匿名回调（Python/C 两侧同表现，见 C 运行时 parity 调试记录）。
        self.assert_parity(CANVAS +
            "图 其 入焦点 1 1 100 20 '初' 0."
            "图 其 矩形 0 0 1 1."
            "图 其 键按下 (作 键: 图 其 矩形 1 1 2 2. 为)."
            "图 其 字符 (作 文: 图 其 矩形 2 2 2 2. 为)."
            "图 其 剪贴 (作 文: 图 其 矩形 3 3 2 2. 为)."
            "图 其 组开始 (作: 图 其 矩形 4 4 2 2. 为)."
            "图 其 组更新 (作 文 标: 图 其 矩形 5 5 2 2. 为)."
            "图 其 组结束 (作 文: 图 其 矩形 6 6 2 2. 为)."
            "图 其 入更新 '改后' 2."
            "图 其 矩形 7 7 1 1. 图 其 入失焦.",
            [{'event': {'type': 'text_key', 'key': '退格'}},
             {'event': {'type': 'text_char', 'text': '甲'}},
             {'event': {'type': 'text_paste', 'text': '贴贴'}},
             {'event': {'type': 'text_comp_start'}},
             {'event': {'type': 'text_comp_update', 'text': '组', 'cursor': 1}},
             {'event': {'type': 'text_comp_end', 'text': '定'}}])

    def test_close_member(self):
        self.assert_parity(CANVAS +
            "图 其 背景 '#000000'. 图 其 关闭.")


class CGraphicsErrorParityTests(unittest.TestCase):
    """成员失败时两端报错消息逐字一致（运行错误 类别）。"""

    def assert_error_parity(self, body):
        source = CANVAS + body
        message = None
        try:
            run_python(source, [])
        except RuError as error:
            message = error.message if hasattr(error, 'message') else str(error)
        self.assertIsNotNone(message, f"Python 侧未报错: {body}")
        with tempfile.TemporaryDirectory() as directory:
            workdir = Path(directory)
            c_path = workdir / 'program.c'
            c_path.write_text(compile_c(source, workdir), encoding='utf-8')
            exe = workdir / 'program'
            # Windows 上 clang 以 MSVC 为 backend：getenv 触发 _CRT deprecation，
            # 必须静默才能 -Werror-free 编译 runtime.h（既有债）。
            build = subprocess.run(
                [CC, '-O1', '-std=gnu99', '-D_CRT_SECURE_NO_WARNINGS',
                 '-I', str(ROOT), str(c_path),
                 str(RECORD_HOST), *([] if sys.platform == 'win32' else ['-lm']), '-o', str(exe)],
                capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(exe)], capture_output=True, text=True,
                                 timeout=30)
        self.assertNotEqual(run.returncode, 0, f"C 侧未报错: {body}")
        self.assertIn(message, run.stderr,
                      f"消息不等：Python {message!r} vs C {run.stderr!r}")

    def test_bad_color(self):
        self.assert_error_parity("图 其 填色 'red'.")

    def test_bad_line_width(self):
        self.assert_error_parity("图 其 线宽 0.")

    def test_bad_fps(self):
        self.assert_error_parity("图 其 帧率 31.")

    def test_restore_without_save(self):
        self.assert_error_parity("图 其 恢复.")


if __name__ == '__main__':
    unittest.main()
