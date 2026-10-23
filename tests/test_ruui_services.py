"""如UI 宿主服务通道（档服务／服务告／服务回）：双端行为与校验测试。"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
sys.path.insert(0, str(ROOT))

from rulang.browser_compiler import compile_browser
from rulang.frontend import RuError, parse
from rulang.graphics_runtime import GraphicsHost
from rulang.interpreter import Interpreter

AD = """
尽取 外言 '如UI'.

状 取 [''].
机 取 新 应用 宽: 360 高: 640 构: (算:
    得 列 [
        (文 (状[0])),
        (钮 '查' (作:
            若 (机 其 能 '档') 则 状[0] 取 '有档'. 另 状[0] 取 '无档'. 然.
            为))
    ].
法).
机 其 运行.
"""

WRITE = """
尽取 外言 '如UI'.

状 取 [''].
机 取 新 应用 宽: 360 高: 640 构: (算:
    得 列 [
        (文 (状[0])),
        (钮 '存' (作:
            档 取 (机 其 服务 '档').
            档 其 写 '便笺.txt' '你好' (作 果 误:
                若 果 则 状[0] 取 '已存'. 另 状[0] 取 ('败' + 误). 然.
                为).
            为))
    ].
法).
机 其 运行.
"""

APPEND = """
尽取 外言 '如UI'.

状 取 [''].
机 取 新 应用 宽: 360 高: 640 构: (算:
    得 列 [
        (文 (状[0])),
        (钮 '添' (作:
            档 取 (机 其 服务 '档').
            档 其 添写 '便笺.txt' '世界' (作 果 误:
                若 果 则 状[0] 取 '已添'. 另 状[0] 取 ('败' + 误). 然.
                为).
            为))
    ].
法).
机 其 运行.
"""

LISTDIR = """
尽取 外言 '如UI'.

状 取 [''].
机 取 新 应用 宽: 360 高: 640 构: (算:
    得 列 [
        (文 (状[0])),
        (钮 '列' (作:
            档 取 (机 其 服务 '档').
            档 其 列 '.' (作 果 名表 误:
                若 果 则
                    合 取 ''.
                    位 取 0.
                    循 名表 其 量 次
                        合 取 合 + (名表 其 位 位) + '/'.
                        位 取 位 + 1.
                    环.
                    状[0] 取 合.
                另
                    状[0] 取 ('败' + 误).
                然.
                为).
            为))
    ].
法).
机 其 运行.
"""

RAW_REQUEST = """
尽取 外言 '如UI'.

状 取 [''].
机 取 新 应用 宽: 360 高: 640 构: (算: 得 列 [(文 (状[0]))]. 法).
机 其 运行.
画布 取 (机 其 图)[0].
画布 其 服务回 (作 号 果 值 误: 状[0] 取 误. 为).
画布 其 服务请 号: 900 服务: '测' 操作: '写' 径: 'x' 文: '' 旗: 假.
"""

NOTEPAD = (ROOT / 'examples' / 'ruui-notepad.ru').read_text(encoding='utf-8')


def texts(commands):
    return [c.get('text') for c in commands if c.get('op') == 'text']


def find_rect(commands, fill):
    for command in commands:
        if command.get('op') == 'rect' and command.get('fill') == fill:
            return command
    raise AssertionError(f'rect {fill} not found')


def center(rect):
    return rect['x'] + rect['width'] / 2, rect['y'] + rect['height'] / 2


def tap(x, y):
    return [{'type': 'mouse_down', 'x': x, 'y': y, 'button': 0},
            {'type': 'mouse_up', 'x': x, 'y': y, 'button': 0},
            {'type': 'frame'}]


def run_python(source, inputs=(), cwd=None):
    """Run on the Python host; cwd controls where 档 writes land."""
    events = []
    host = GraphicsHost(Interpreter(), events.append)
    old = os.getcwd()
    try:
        if cwd is not None:
            os.chdir(cwd)
        host.interpreter.execute(parse(source))
        host.flush()
        for event in inputs:
            host.handle(event)
        return [e for e in events if e['type'] == 'graphics']
    finally:
        os.chdir(old)
        host.close()


def run_python_host(source, inputs=(), cwd=None):
    """Like run_python but returns (events, host) with host still open."""
    events = []
    host = GraphicsHost(Interpreter(), events.append)
    old = os.getcwd()
    if cwd is not None:
        os.chdir(cwd)
    try:
        host.interpreter.execute(parse(source))
        host.flush()
        for event in inputs:
            host.handle(event)
        return [e for e in events if e['type'] == 'graphics'], host
    finally:
        os.chdir(old)


def run_javascript(source, inputs=(), bridge=None):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / 'program.mjs').write_text(compile_browser(source), encoding='utf-8')
        bridge_js = (',' + bridge) if bridge else ""
        (path / 'run.mjs').write_text(
            "import create from './program.mjs';const events=[];"
            "const runtime=create({emit:e=>events.push(e)" + bridge_js + "});"
            "const canvas_id=events.find(e=>e.type==='graphics').canvas_id;"
            + "for(const event of " + json.dumps(inputs)
            + ")runtime.dispatch({canvas_id,event});"
            + "console.log(JSON.stringify(events.filter(e=>e.type==='graphics')));",
            encoding='utf-8')
        result = subprocess.run([NODE, str(path / 'run.mjs')], text=True,
                                capture_output=True, timeout=15)
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def button_pos(events, color='#4677ff'):
    return center(find_rect(events[-1]['commands'], color))


class RuUIAdTests(unittest.TestCase):
    def test_ad_python_enables_dang_after_first_flush(self):
        events = run_python(AD)
        # 首个场景先于广告送达（flush 先出帧后排水），故首帧仍 无档。
        self.assertEqual(texts(events[-1]['commands'])[0], '')
        x, y = button_pos(events)
        events = run_python(AD, tap(x, y))
        self.assertEqual(texts(events[-1]['commands'])[0], '有档')

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_ad_js_matches_python(self):
        # 无桥＝无档（诚实失败：广告为空表）；注入假桥广告 ['档'] 证明投递通路。
        events = run_javascript(AD)
        x, y = button_pos(events)
        events = run_javascript(AD, tap(x, y))
        self.assertEqual(texts(events[-1]['commands'])[0], '无档')
        events = run_javascript(AD, tap(x, y),
                                bridge="services:()=>['档']")
        self.assertEqual(texts(events[-1]['commands'])[0], '有档')


class RuUIDangTests(unittest.TestCase):
    def test_write_append_overwrite_python(self):
        with tempfile.TemporaryDirectory() as directory:
            x = y = None
            events = run_python(WRITE, cwd=directory)
            x, y = button_pos(events)
            run_python(WRITE, tap(x, y), cwd=directory)
            with open(os.path.join(directory, '便笺.txt'), encoding='utf-8') as stream:
                self.assertEqual(stream.read(), '你好')
            run_python(APPEND, tap(x, y), cwd=directory)
            with open(os.path.join(directory, '便笺.txt'), encoding='utf-8') as stream:
                self.assertEqual(stream.read(), '你好世界')
            run_python(WRITE, tap(x, y), cwd=directory)
            with open(os.path.join(directory, '便笺.txt'), encoding='utf-8') as stream:
                self.assertEqual(stream.read(), '你好')

    def test_write_status_python(self):
        with tempfile.TemporaryDirectory() as directory:
            events = run_python(WRITE, cwd=directory)
            x, y = button_pos(events)
            events = run_python(WRITE, tap(x, y), cwd=directory)
            self.assertEqual(texts(events[-1]['commands'])[0], '已存')

    @unittest.skipUnless(NODE, 'Node required for JS parity')
    def test_write_js_honest_failure_without_bridge(self):
        # 无桥浏览器：服务请求排队，下一拍事件自动回失败（诚实失败哲学）。
        events = run_javascript(WRITE)
        x, y = button_pos(events)
        events = run_javascript(WRITE, tap(x, y) + [{'type': 'frame'}])
        self.assertIn('宿主无此服务：档', texts(events[-1]['commands'])[0])

    def test_list_python(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'b.txt').write_text('b', encoding='utf-8')
            Path(directory, 'a.txt').write_text('a', encoding='utf-8')
            events = run_python(LISTDIR, cwd=directory)
            x, y = button_pos(events)
            events = run_python(LISTDIR, tap(x, y), cwd=directory)
            self.assertEqual(texts(events[-1]['commands'])[0], 'a.txt/b.txt/')

    def test_unknown_service_rejected_python(self):
        with tempfile.TemporaryDirectory() as directory:
            events = run_python(RAW_REQUEST, [{'type': 'frame'}], cwd=directory)
            self.assertEqual(texts(events[-1]['commands'])[0], '宿主无此服务：测')


class RuUIServiceEventValidationTests(unittest.TestCase):
    def open_host(self):
        events = []
        host = GraphicsHost(Interpreter(), events.append)
        host.interpreter.execute(parse(AD))
        host.flush()
        return events, host

    def test_response_without_callback_ignored(self):
        # 旧库不注册 服务回：服务邮件按清理噪音静默忽略（不报错）。
        _, host = self.open_host()
        try:
            host.handle({'type': 'service_response', 'id': 1, 'ok': True,
                         'value': None, 'error': None})
        finally:
            host.close()

    def test_response_unknown_handle_ignored(self):
        events, host = self.open_host()
        try:
            host.handle({'type': 'service_response', 'id': 999, 'ok': True,
                         'value': 'x', 'error': None})
            # 未知句柄不产生任何用户可见效果，也不报错。
        finally:
            host.close()

    def test_response_bad_ok_rejected(self):
        _, host = self.open_host()
        try:
            with self.assertRaises(RuError):
                host.handle({'type': 'service_response', 'id': 1, 'ok': 'yes',
                             'value': None, 'error': None})
        finally:
            host.close()

    def test_response_bad_error_rejected(self):
        _, host = self.open_host()
        try:
            with self.assertRaises(RuError):
                host.handle({'type': 'service_response', 'id': 1, 'ok': False,
                             'value': None, 'error': ''})
        finally:
            host.close()

    def test_ad_oversize_rejected(self):
        _, host = self.open_host()
        try:
            with self.assertRaises(RuError):
                host.handle({'type': 'service_ad', 'services': '档' * 5000})
        finally:
            host.close()


class RuUINotepadExampleTests(unittest.TestCase):
    def test_notepad_first_frame_parity(self):
        events = run_python(NOTEPAD)
        self.assertEqual(texts(events[-1]['commands'])[0], '记事')
        if NODE:
            js = run_javascript(NOTEPAD)
            self.assertEqual(events[-1]['commands'], js[-1]['commands'])


if __name__ == '__main__':
    unittest.main()
