"""Portable fixture guards, independent of cc availability and UTF8-mode env.

These inspect test Python only; no application AST processing or acceptance
adapter. The cp1252 model verifies fixture IO, not compiler execution.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def check_text_io(source):
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        path_io = node.func.attr in ('read_text', 'write_text')
        process = (node.func.attr == 'run' and isinstance(node.func.value, ast.Name)
                   and node.func.value.id == 'subprocess'
                   and any(k.arg == 'text' and isinstance(k.value, ast.Constant)
                           and k.value.value is True for k in node.keywords))
        if path_io or process:
            if not any(k.arg == 'encoding' and isinstance(k.value, ast.Constant)
                       and k.value.value == 'utf-8' for k in node.keywords):
                raise ValueError('fixture text IO must explicitly select utf-8')


def check_temp_roots(source):
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == 'Path' and len(node.args) == 1):
            continue
        arg = node.args[0]
        temporary = ((isinstance(arg, ast.Name) and arg.id in ('tmp', 'temp'))
                     or (isinstance(arg, ast.Attribute) and arg.attr == 'name'))
        if temporary:
            parent = parents.get(node)
            if not (isinstance(parent, ast.Attribute) and parent.attr == 'resolve'
                    and isinstance(parents.get(parent), ast.Call)):
                raise ValueError('temporary fixture root must resolve before protocol use')


class DenseFixturePortabilityTests(unittest.TestCase):
    def test_all_dense_test_text_io_explicit_even_without_cc(self):
        for path in sorted((ROOT/'tests').glob('test_bootstrap_dense*.py')):
            with self.subTest(path=path.name):
                source = path.read_text(encoding='utf-8')
                check_text_io(source)
                check_temp_roots(source)

    def test_implicit_encoding_regressions_rejected(self):
        for source in ("p.read_text()", "p.write_text('中文😀')",
                       "subprocess.run(['x'],capture_output=True,text=True)"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                check_text_io(source)

    def test_relative_temporary_root_regressions_rejected(self):
        for source in ('Path(cls.tmp.name)', 'Path(self.temp.name)', 'Path(tmp)', 'Path(temp)'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                check_temp_roots(source)

    def test_helper_fixture_under_cp1252_defaults(self):
        from tests import test_bootstrap_dense_helper as helper
        original_read, original_write = Path.read_text, Path.write_text
        def ansi_read(path, encoding=None, errors=None):
            return original_read(path, encoding=encoding or 'cp1252', errors=errors)
        def ansi_write(path, data, encoding=None, errors=None):
            return original_write(path, data, encoding=encoding or 'cp1252', errors=errors)
        # Direct fixture setup is deliberate: do not inherit the class's cc skip.
        cls = helper.BootstrapDenseHelperTests
        with patch.object(Path, 'read_text', ansi_read), patch.object(Path, 'write_text', ansi_write), \
             patch.object(helper.subprocess, 'run', return_value=SimpleNamespace(returncode=0,stdout='',stderr='')):
            try:
                cls.setUpClass()
                self.assertTrue(cls.directory.is_absolute())
                self.assertIn('字节', cls.contracts[0]['params'])
                harness = (cls.directory/'driver.ru').read_bytes().decode('utf-8')
                self.assertIn('前端 取 外言', harness)
            finally:
                if hasattr(cls, 'tmp'):
                    cls.tmp.cleanup()
