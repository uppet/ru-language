"""RU003: expected/received types agree across Python, native C, and Node."""
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.cli import build
from rulang.frontend import RuError, parse
from rulang.interpreter import Interpreter

NODE = shutil.which('node') or shutil.which('nodejs')
HAS_CC = any(shutil.which(c) for c in ('clang', 'gcc', 'cc'))


def argument_case(expected, expression, actual, prelude=''):
    source = prelude + f'算 接收 参数 为 {expected}: 得 1. 法 接收 ({expression}).'
    message = f'函数「接收」的实参「参数」须为{expected}，实际收到{actual}'
    return source, message


CASES = [
    argument_case('数', "'一'", '句'),
    argument_case('句', '1', '数'),
    argument_case('数', '空', '空'),
    argument_case('数', '1 对 2', '对'),
    argument_case('数', '[1]', '阵'),
    argument_case('学生', '1', '数', '形 学生: 象 '),
    argument_case('学生', '新 教师', '教师', '形 学生: 象 形 教师: 象 '),
    argument_case('数', '新 学生', '学生', '形 学生: 象 '),
    argument_case('算', '1', '数'),
    argument_case('作', '1', '数'),
    argument_case('算', '作 报', '作', '作 报: 显 1. 为 '),
    argument_case('作', '算 回', '算', '算 回: 得 1. 法 '),
    argument_case('数 阵', "[1,'二']", '阵'),
    argument_case('数 阵', '1', '数'),
    argument_case('学生 阵', '[1]', '阵', '形 学生: 象 '),
    argument_case('算 阵', '[1]', '阵'),
    ('形 盒: 年龄 为 数. 象 值 取 新 盒 年龄:\'老\'.',
     '字段「年龄」须为数，实际收到句'),
    ('形 盒: 年龄 为 数. 象 值 取 新 盒. 值 其 年龄 取 \'老\'.',
     '字段「年龄」须为数，实际收到句'),
    ('形 学生: 象 形 盒: 对象 为 学生. 象 值 取 新 盒 对象:1.',
     '字段「对象」须为学生，实际收到数'),
    ('形 盒: 回调 为 算. 象 值 取 新 盒. 值 其 回调 取 1.',
     '字段「回调」须为算，实际收到数'),
    ('形 盒: 列 为 数 阵. 象 值 取 新 盒 列:[\'一\'].',
     '字段「列」须为数 阵，实际收到阵'),
    ('形 盒: 算 接收 参数 为 数: 得 参数. 法 象 值 取 新 盒. 值 其 接收 \'一\'.',
     '函数「接收」的实参「参数」须为数，实际收到句'),
]


class TypeDiagnostics(unittest.TestCase):
    def assert_diagnostic(self, message, expected):
        self.assertIn(expected, message)
        self.assertNotIn('请显式使用', message)
        self.assertNotIn('转换', message)

    def test_interpreter(self):
        for source, expected in CASES:
            with self.subTest(source=source):
                runtime = Interpreter(io.StringIO(), io.StringIO())
                with self.assertRaises(RuError) as error:
                    runtime.execute(parse(source))
                self.assert_diagnostic(error.exception.message, expected)

    def check_compiled(self, target):
        with tempfile.TemporaryDirectory() as temp:
            for index, (source, expected) in enumerate(CASES):
                with self.subTest(target=target, source=source):
                    path, _ = build(parse(source), Path(temp)/f'case{index}.ru',
                                    Path(temp)/f'case{index}', target=target)
                    command = [NODE, str(path)] if target == 'js' else [str(path)]
                    result = subprocess.run(command, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assert_diagnostic(result.stderr, expected)

    @unittest.skipUnless(HAS_CC, 'C compiler unavailable')
    def test_native(self):
        self.check_compiled('c')

    @unittest.skipUnless(NODE, 'Node.js unavailable')
    def test_javascript(self):
        self.check_compiled('js')


if __name__ == '__main__':
    unittest.main()
