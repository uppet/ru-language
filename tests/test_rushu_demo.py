"""The shipped notebook remains executable with the unmodified language."""
import io
import json
import shutil
import subprocess
from pathlib import Path
import unittest

from rulang.frontend import parse
from rulang.interpreter import Interpreter


class NotebookDemoTests(unittest.TestCase):
    def test_first_book_current_language(self):
        path = Path(__file__).resolve().parents[1] / 'rushu/examples/first-book.rushu.json'
        book = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual((book['format'], book['version']), ('rushu-notebook', 1))
        output = io.StringIO()
        runtime = Interpreter(stdin=io.StringIO('12\n30\n'), stdout=output)
        for cell in book['cells']:
            self.assertIsNone(cell['execution_count'])
            self.assertEqual(cell['outputs'], [])
            if cell['type'] == 'code':
                runtime.execute(parse(cell['source']), echo=True)
        self.assertEqual(output.getvalue(), '10\n15\n25\n20\n真\n2\n输入第一数：输入第二数：42\n')

    @unittest.skipUnless(shutil.which('node'), 'Node is needed to load the welcome book')
    def test_default_welcome_book_current_language(self):
        root = Path(__file__).resolve().parents[1]
        source = subprocess.check_output([
            'node', '--input-type=module', '-e',
            "import {welcomeBook} from './rushu/static/notebook.mjs'; "
            "console.log(JSON.stringify(welcomeBook()));",
        ], cwd=root, text=True)
        book = json.loads(source)
        output = io.StringIO()
        runtime = Interpreter(stdout=output)
        for cell in book['cells']:
            if cell['type'] == 'code':
                runtime.execute(parse(cell['source']), echo=True)
        self.assertEqual(output.getvalue(), '你好，如书\n你好，如书\n81\n你好，如书\n真\n')

    def test_redefinition_preserves_old_function_value(self):
        output = io.StringIO()
        runtime = Interpreter(stdout=output)
        for code in ['基数 取 2.', '算 倍 值 为 数: 得 值 * 基数. 法',
                     '旧倍 取 算 倍.', '算 倍 值 为 数: 得 值 * 3. 法',
                     '基数 取 4.', '显 (旧倍 2). 显 (倍 2).']:
            runtime.execute(parse(code), echo=True)
        self.assertEqual(output.getvalue(), '8\n6\n')


if __name__ == '__main__':
    unittest.main()
