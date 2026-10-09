"""Checked I/O parity. All filesystem mutations stay in self-created temp dirs."""
import errno
import gc
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import weakref

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rulang.cli import build
from rulang.compiler import Compiler
from rulang.frontend import parse
from rulang.interpreter import Interpreter
from rulang import io_runtime

CC = next((shutil.which(name) for name in ("clang", "gcc", "cc") if shutil.which(name)), None)


def quote(value):
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


class CheckedIOTests(unittest.TestCase):
    def engines(self, make_source, expected, stdin=b"", setup=None, gc_stress=False):
        for engine in ("python", "native"):
            if engine == "native" and not CC:
                continue
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                data = root / "data"
                data.mkdir()
                if setup:
                    setup(data)
                source = make_source(data)
                if engine == "python":
                    output, errors = io.StringIO(), io.StringIO()
                    owner = Interpreter(io.BytesIO(stdin), output, stderr=errors)
                    owner.execute(parse(source))
                    actual, diagnostic = output.getvalue(), errors.getvalue()
                else:
                    binary, _ = build(parse(source), root / "test.ru", root / "program")
                    env = dict(os.environ)
                    if gc_stress:
                        env.update(RU_GC_THRESHOLD="1", RU_GC_STATS="1")
                    result = subprocess.run([binary], input=stdin, capture_output=True,
                                            timeout=15, env=env)
                    self.assertEqual(result.returncode, 0, result.stderr.decode())
                    actual, diagnostic = result.stdout.decode(), result.stderr.decode()
                    if gc_stress:
                        self.assertRegex(diagnostic, r"RU_GC live=0 freed=\d+ collections=\d+")
                self.assertEqual(actual, expected)
                if not gc_stress:
                    self.assertEqual(diagnostic, "")

    def test_file_roundtrip_append_truncate_delete(self):
        def source(path):
            return f"""
文档 取 新 件 路径:{quote(path/'你好.txt')}.
显 (文档 其 在) 其 值.
应 取 文档 其 写 内容:'甲😀\n'. 显 应 其 结果. 显 应 其 值. 显 应 其 错误信息 == ''.
显 (文档 其 在) 其 值.
应 取 文档 其 写 追加:1 内容:'乙'. 显 应 其 结果.
显 (文档 其 读) 其 值.
文档 其 写 '末'. 显 (文档 其 读) 其 值.
显 (文档 其 除) 其 值. 显 (文档 其 在) 其 值.
应 取 文档 其 读. 显 应 其 结果. 显 应 其 值. 显 应 其 错误信息 其 含 'errno'.
"""
        self.engines(source, "假\n成功\n空\n真\n真\n成功\n甲😀\n乙\n末\n空\n假\n失败\n空\n真\n")

    def test_result_is_normal_typed_mutable_object(self):
        source = """
算 查 回 为 件作成果: 得 回 其 值. 法
应 取 新 件作成果. 显 应 其 结果. 显 应 其 错误信息 == ''.
应 其 值 取 [1,'二']. 显 (查 应)[1]. 应 其 结果 取 '用户'. 显 应 其 结果.
应 其 值 取 应. 显 应 其 值 == 应.
文档 取 新 件. 显 文档 其 路径 == ''. 显 (文档 其 读) 其 结果.
目录 取 新 录. 显 目录 其 路径.
"""
        self.engines(lambda _: source, "成功\n真\n二\n用户\n真\n真\n失败\n.\n", gc_stress=True)

    def test_list_sorted_regular_files_and_empty(self):
        def setup(path):
            (path/'乙.txt').write_text('乙', encoding='utf-8')
            (path/'a.txt').write_text('a', encoding='utf-8')
            (path/'子录').mkdir()
            (path/'子录'/'不可列.txt').write_text('nested', encoding='utf-8')
        def source(path):
            return f"""
目录 取 新 录 路径:{quote(path)}. 应 取 目录 其 列. 显 应 其 结果.
列值 取 应 其 值. 显 列值 其 量. 显 (列值[0] 其 读) 其 值. 显 (列值[1] 其 读) 其 值.
空录 取 新 录 路径:{quote(path/'子录'/'..'/'empty')}.
空件 取 新 件 路径:{quote(path)}. 显 (空件 其 在) 其 值. 显 (空件 其 除) 其 结果.
"""
        self.engines(source, "成功\n2\na\n乙\n假\n失败\n", setup=setup, gc_stress=True)
        self.engines(lambda p: f"显 ((新 录 路径:{quote(p)}) 其 列) 其 值 其 量.", "0\n")

    @unittest.skipUnless(hasattr(os, 'symlink'), 'symlinks unavailable')
    def test_symlink_policy(self):
        def setup(path):
            (path/'base').write_text('原', encoding='utf-8')
            (path/'link').symlink_to(path/'base')
            (path/'dangling').symlink_to(path/'absent')
            (path/'subdir').mkdir()
            (path/'dirlink').symlink_to(path/'subdir', target_is_directory=True)
        def source(path):
            return f"""
目录 取 新 录 路径:{quote(path)}. 显 (目录 其 列) 其 值 其 量.
链接 取 新 件 路径:{quote(path/'link')}. 显 (链接 其 读) 其 值.
链接 其 写 内容:'新'. 显 ((新 件 路径:{quote(path/'base')}) 其 读) 其 值.
显 (链接 其 除) 其 结果. 显 ((新 件 路径:{quote(path/'base')}) 其 在) 其 值.
失链 取 新 件 路径:{quote(path/'dangling')}. 显 (失链 其 在) 其 值. 显 (失链 其 除) 其 结果.
"""
        self.engines(source, "2\n原\n新\n成功\n真\n假\n成功\n", setup=setup)

    def test_failures_are_values_and_do_not_create_invalid_writes(self):
        def setup(path):
            (path/'badutf8').write_bytes(b'\xff\xfe')
            (path/'nul').write_bytes(b'a\x00b')
            (path/'existing').write_text('safe', encoding='utf-8')
        def source(path):
            return f"""
文档 取 新 件 路径:{quote(path/'missing'/'x')}.
显 (文档 其 读) 其 结果. 显 (文档 其 写 内容:'x') 其 结果. 显 (文档 其 在) 其 值.
目录 取 新 录 路径:{quote(path/'existing')}. 显 (目录 其 列) 其 结果.
文档 其 路径 取 {quote(path/'badutf8')}. 显 (文档 其 读) 其 结果.
文档 其 路径 取 {quote(path/'nul')}. 显 (文档 其 读) 其 结果.
文档 其 路径 取 空. 显 (文档 其 在) 其 结果.
文档 其 路径 取 {quote(path/'existing')}.
显 (文档 其 写 内容:3) 其 结果. 显 (文档 其 写 内容:'damage' 追加:2) 其 结果.
显 (文档 其 读) 其 值.
"""
        self.engines(source, "失败\n失败\n假\n失败\n失败\n失败\n失败\n失败\n失败\nsafe\n", setup=setup)

    def test_stdin_lines_empty_lines_and_eof(self):
        source = """
显 (读取 其 读) 其 值. 显 (读取 其 读) 其 值. 显 (读取 其 读) 其 值.
应 取 读取 其 读. 显 应 其 结果. 显 应 其 值 == 空. 显 应 其 错误信息 == ''.
"""
        self.engines(lambda _: source, "甲😀\n\n尾\n成功\n真\n真\n", stdin='甲😀\r\n\n尾'.encode())
        self.engines(lambda _: "显 (读取 其 读) 其 结果.", "失败\n", stdin=b'bad\xff\n')
        self.engines(lambda _: "显 (读取 其 读) 其 结果.", "失败\n", stdin=b'bad\x00\n')

    def test_stdout_no_implicit_newline(self):
        self.engines(lambda _: "应 取 显出 其 写 内容:'甲😀'. 显 应 其 结果. 显 应 其 值. 显 应 其 错误信息 == ''.", "甲😀成功\n空\n真\n")

    def test_stderr_no_implicit_newline(self):
        source = "应 取 错误 其 写 内容:'诊断😀'. 显 应 其 结果."
        output, errors = io.StringIO(), io.StringIO()
        Interpreter(io.StringIO(), output, stderr=errors).execute(parse(source))
        self.assertEqual((output.getvalue(), errors.getvalue()), ('成功\n', '诊断😀'))
        if CC:
            with tempfile.TemporaryDirectory() as temp:
                binary, _ = build(parse(source), Path(temp)/'test.ru', Path(temp)/'program')
                result = subprocess.run([binary], capture_output=True, text=True, timeout=10)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '成功\n', '诊断😀'))

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'requires POSIX FIFO')
    def test_special_files_fail_without_blocking(self):
        self.engines(lambda p: f"文档 取 新 件 路径:{quote(p/'pipe')}. 显 (文档 其 读) 其 结果. 显 (文档 其 在) 其 值. 显 (文档 其 除) 其 结果.",
                     '失败\n假\n失败\n', setup=lambda p: os.mkfifo(p/'pipe'))

    def test_gc_stress_with_result_and_listing_roots(self):
        def source(path):
            return f"""
文件 取 新 件 路径:{quote(path/'data')}. 目录 取 新 录 路径:{quote(path)}.
循 80 次
文件 其 写 内容:'😀甲乙'. 应 取 文件 其 读.
若 应 其 值 != '😀甲乙' 则 显 'bad'. 然
列值 取 (目录 其 列) 其 值. 若 列值 其 量 != 1 则 显 'bad'. 然
环
显 (文件 其 读) 其 值.
"""
        self.engines(source, '😀甲乙\n', gc_stress=True)

    @unittest.skipIf(os.name == 'nt', 'requires POSIX pipes')
    def test_closed_stdout_pipe_is_checked_failure(self):
        source = "应 取 显出 其 写 内容:'测试'. 错误 其 写 内容:应 其 结果."
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'test.ru'
            path.write_text(source, encoding='utf-8')
            commands = [[sys.executable, str(ROOT/'ru'), 'run', str(path)]]
            if CC:
                binary, _ = build(parse(source), path, Path(temp)/'program')
                commands.append([str(binary)])
            for command in commands:
                with self.subTest(command=command):
                    read_fd, write_fd = os.pipe()
                    os.close(read_fd)
                    try:
                        result = subprocess.run(command, stdout=write_fd, stderr=subprocess.PIPE, timeout=10)
                    finally:
                        os.close(write_fd)
                    self.assertEqual((result.returncode, result.stderr), (0, '失败'.encode()))

    def test_cli_line_errors_preserve_adjacent_lines_and_legacy_reads(self):
        cases = [
            ("循 3 次 应 取 读取 其 读. 显 应 其 结果. 显 应 其 值. 环", b'good\nbad\xff\nafter\n',
             '成功\ngood\n失败\n空\n成功\nafter\n'),
            ("显 读. 显 (读取 其 读) 其 值. 显 读.", b'first\nsecond\nthird\n',
             'first\nsecond\nthird\n'),
        ]
        with tempfile.TemporaryDirectory() as temp:
            for index, (source, data, expected) in enumerate(cases):
                path = Path(temp)/f'case{index}.ru'
                path.write_text(source, encoding='utf-8')
                commands = [[sys.executable, str(ROOT/'ru'), 'run', str(path)]]
                if CC:
                    binary, _ = build(parse(source), path, Path(temp)/f'program{index}')
                    commands.append([str(binary)])
                for command in commands:
                    with self.subTest(command=command, index=index):
                        result = subprocess.run(command, input=data, capture_output=True, timeout=10)
                        self.assertEqual((result.returncode, result.stdout.decode(), result.stderr), (0, expected, b''))
        # The REPL itself and language reads must use one shared buffered reader.
        result = subprocess.run([sys.executable, str(ROOT/'ru'), 'repl'],
                                input=b"x "+'取 读取 其 读.\n'.encode()+b"data\n"+'显 x 其 值.\n'.encode()+b":quit\n",
                                capture_output=True, timeout=10)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b'data\n', b''))

    @unittest.skipIf(os.name == 'nt' or getattr(os, 'geteuid', lambda: 0)() == 0,
                     'actual mode denial requires unprivileged POSIX execution; errno injection always tested')
    def test_actual_file_permissions_are_preserved(self):
        def setup(path):
            file = path/'locked'
            file.write_text('private', encoding='utf-8')
            file.chmod(0)
        self.engines(lambda p: f"文档 取 新 件 路径:{quote(p/'locked')}. 显 (文档 其 读) 其 结果. 显 (文档 其 写 内容:'x') 其 结果.",
                     '失败\n失败\n', setup=setup)

    def test_builtin_types_cross_module_boundaries_without_exports(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'text').write_text('跨模块', encoding='utf-8')
            (root/'lib.ru').write_text("算 内容 文件 为 件: 得 文件 其 读. 法 算 解包 应 为 件作成果: 得 应 其 值. 法", encoding='utf-8')
            source = f"尽 取 外言 'lib.ru'. 文档 取 新 件 路径:{quote(root/'text')}. 显 解包 (内容 文档)."
            path = root/'test.ru'
            path.write_text(source, encoding='utf-8')
            commands = [[sys.executable, str(ROOT/'ru'), 'run', str(path)]]
            if CC:
                binary, _ = build(parse(source), path, root/'program')
                commands.append([str(binary)])
            for command in commands:
                result = subprocess.run(command, capture_output=True, text=True, timeout=10)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '跨模块\n', ''))

    def test_qualified_module_members_do_not_include_builtin_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'lib.ru').write_text('值 取 1.', encoding='utf-8')
            for name in io_runtime.IO_BUILTIN_NAMES:
                source = f"模 取 外言 'lib.ru'. 显 模 其 {name}."
                path = root/'test.ru'
                path.write_text(source, encoding='utf-8')
                commands = [[sys.executable, str(ROOT/'ru'), 'run', str(path)]]
                if CC:
                    binary, _ = build(parse(source), path, root/'program')
                    commands.append([str(binary)])
                for command in commands:
                    with self.subTest(name=name, command=command):
                        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
                        self.assertEqual((result.returncode, result.stdout), (1, ''))
                        self.assertIn(f'未知成员：{name}', result.stderr)

    def test_qualified_module_members_preserve_explicit_exports(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'lib.ru').write_text("""
算 文件 路径 为 句: 得 新 件 路径:路径. 法
算 目录: 得 新 录. 法 算 成果: 得 新 件作成果. 法
输入口 取 读取. 输出口 取 显出. 错误口 取 错误.
值 取 7. 文字 取 '跨模块'. 算 加值 项 为 数: 得 值 + 项. 法
""", encoding='utf-8')
            source = f"""
模 取 外言 'lib.ru'.
文档 取 模 其 文件 路径:{quote(root/'missing')}.
显 (文档 其 在) 其 值.
显 (模 其 目录) 其 路径.
显 (模 其 成果) 其 结果.
显 ((模 其 输入口) 其 读) 其 值.
(模 其 输出口) 其 写 内容:'输出'. (模 其 错误口) 其 写 内容:'诊断'.
显 模 其 文字. 显 模 其 值. 显 模 其 加值 5. 显 模 其 加值 项:6.
"""
            path = root/'test.ru'
            path.write_text(source, encoding='utf-8')
            commands = [[sys.executable, str(ROOT/'ru'), 'run', str(path)]]
            if CC:
                binary, _ = build(parse(source), path, root/'program')
                commands.append([str(binary)])
            for command in commands:
                with self.subTest(command=command):
                    result = subprocess.run(command, input='输入\n', capture_output=True, text=True,
                                            timeout=10, env=dict(os.environ, RU_GC_THRESHOLD='1'))
                    self.assertEqual((result.returncode, result.stdout, result.stderr),
                                     (0, '假\n.\n成功\n输入\n输出跨模块\n7\n12\n13\n', '诊断'))

    def test_builtin_registry_does_not_retain_interpreters(self):
        owner = Interpreter(io.StringIO(), io.StringIO())
        reference = weakref.ref(owner)
        del owner
        gc.collect()
        self.assertIsNone(reference())

    def test_python_short_write_flush_close_and_read_errors(self):
        class FakeFile:
            def __init__(self, failure):
                self.failure, self.closed = failure, False
            def write(self, value):
                return len(value)-1 if self.failure == 'short' else len(value)
            def read(self):
                if self.failure == 'read':
                    raise OSError(errno.EIO, 'read failure')
                return b'ok'
            def flush(self):
                if self.failure == 'flush':
                    raise OSError(errno.ENOSPC, 'flush failure')
            def close(self):
                self.closed = True
                if self.failure == 'close':
                    raise OSError(errno.EIO, 'close failure')
        for failure in ('short', 'flush', 'close', 'read'):
            with self.subTest(failure=failure):
                fake = FakeFile(failure)
                output = io.StringIO()
                source = "文档 取 新 件 路径:'unused'. 应 取 文档 其 " + ('读' if failure == 'read' else "写 内容:'text'") + ". 显 应 其 结果. 显 应 其 错误信息 其 含 'errno'."
                with mock.patch.object(io_runtime, '_open_regular', return_value=fake):
                    Interpreter(io.StringIO(), output).execute(parse(source))
                self.assertEqual(output.getvalue(), '失败\n真\n')
                self.assertTrue(fake.closed)
        for operation in ('stat', 'open'):
            output = io.StringIO()
            source = "文档 取 新 件 路径:'unused'. 应 取 文档 其 " + ('在' if operation == 'stat' else '读') + ". 显 应 其 结果. 显 应 其 错误信息 其 含 'errno 13'."
            with mock.patch.object(io_runtime.os, operation, side_effect=PermissionError(errno.EACCES, 'denied')):
                Interpreter(io.StringIO(), output).execute(parse(source))
            self.assertEqual(output.getvalue(), '失败\n真\n')

    @unittest.skipUnless(CC, 'C compiler unavailable')
    def test_native_short_write_flush_close_and_read_errors(self):
        wrappers = {
            'short': 'static size_t test_write(const void*p,size_t s,size_t n,FILE*f){return fwrite(p,s,n?n-1:0,f);}\n#define fwrite test_write\n',
            'flush': 'static int test_flush(FILE*f){int r=fflush(f);(void)r;errno=ENOSPC;return EOF;}\n#define fflush test_flush\n',
            'close': 'static int test_close(FILE*f){int r=fclose(f);(void)r;errno=EIO;return EOF;}\n#define fclose test_close\n',
            'read': 'static size_t test_read(void*p,size_t s,size_t n,FILE*f){(void)p;(void)s;(void)n;(void)f;errno=EIO;return 0;}\nstatic int test_error(FILE*f){(void)f;return 1;}\n#define fread test_read\n#define ferror test_error\n',
            'permission': 'static int test_stat(const char*p,struct stat*s){(void)p;(void)s;errno=EACCES;return -1;}\n#define stat(...) test_stat(__VA_ARGS__)\n',
        }
        for failure, wrapper in wrappers.items():
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path = root/'data'
                path.write_text('old', encoding='utf-8')
                operation = '读' if failure == 'read' else '在' if failure == 'permission' else "写 内容:'text'"
                source = f"文档 取 新 件 路径:{quote(path)}. 应 取 文档 其 {operation}. 显 应 其 结果. 显 应 其 错误信息 其 含 'errno'."
                code = Compiler(parse(source)).compile()
                # Injection is confined to generated runtime I/O, not language print.
                prefix = '#include <errno.h>\n#include <sys/stat.h>\n' + wrapper
                code = code.replace('#ifndef RU_IO_RUNTIME_H', prefix+'\n#ifndef RU_IO_RUNTIME_H', 1)
                cfile, binary = root/'program.c', root/'program'
                cfile.write_text(code, encoding='utf-8')
                compiled = subprocess.run([CC, '-std=c99', '-Werror=implicit-function-declaration', str(cfile), '-lm', '-o', str(binary)], capture_output=True, text=True)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                result = subprocess.run([binary], capture_output=True, text=True, timeout=10)
                self.assertEqual((result.returncode, result.stdout), (0, '失败\n真\n'), result.stderr)


if __name__ == '__main__':
    unittest.main()
