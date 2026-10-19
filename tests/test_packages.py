"""Package language contract is specified before implementation."""
import io
from pathlib import Path
import tempfile
import unittest

from rulang.frontend import RuError, parse, validate
from rulang.interpreter import Interpreter
from rulang.modules import load_module_graph


class PackageSyntaxTests(unittest.TestCase):
    def test_optional_declaration_and_static_chain(self):
        program = parse('吾 言 工程 其 力学. 力 取 外言 工程 其 力学.')
        validate(program)
        self.assertEqual(program[0].kind, 'module_decl')
        self.assertEqual(program[0].data['name'], ('工程', '力学'))
        imported = program[1].data['expr']
        self.assertEqual(imported.kind, 'import')
        self.assertEqual(imported.data['name'], ('工程', '力学'))

    def test_context_names_remain_ordinary(self):
        output = io.StringIO()
        Interpreter(stdout=output).execute(parse('吾 取 3. 言 取 4. 显 吾 + 言.'))
        self.assertEqual(output.getvalue(), '7\n')
        self.assertEqual(parse('算 吾 言: 得 言. 法. 显 吾 4.')[1].kind, 'print')

    def test_declaration_only_once_at_top_level(self):
        for source in ('吾 言 工程. 吾 言 工程.', '段: 吾 言 工程. 落.',
                       '算 做: 吾 言 工程. 得 1. 法.'):
            with self.subTest(source=source), self.assertRaises(RuError):
                validate(parse(source))

    def test_named_import_member_needs_grouping(self):
        self.assertEqual(parse('显 (外言 工程 其 力学) 其 值.')[0].data['expr'].kind, 'member')
        self.assertEqual(parse('外言 工程 其 力学 其 值.')[0].data['expr'].data['name'],
                         ('工程', '力学', '值'))


class PackageManifestTests(unittest.TestCase):
    def load(self, text):
        from rulang.packages import load_manifest
        self.path.write_text(text, encoding='utf-8')
        return load_manifest(self.path)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / '集录.ru'

    def test_static_manifest_and_relative_public_names(self):
        manifest = self.load("典: '名' 对 '工程'. '版' 对 '1.0.0'. '公开' 对 ['力学', '流体/管道']. 成.")
        self.assertEqual(manifest.name, '工程')
        self.assertEqual(manifest.public[('工程', '力学')], self.path.parent / 'src/力学.ru')
        self.assertEqual(manifest.public[('工程', '流体', '管道')], self.path.parent / 'src/流体/管道.ru')

    def test_explicit_map_paths_are_manifest_relative(self):
        manifest = self.load("{'名':'工程', '版':'1.0.0', '公开':{'力学':'src/力学.ru'}}.")
        self.assertEqual(manifest.public[('工程', '力学')], self.path.parent / 'src/力学.ru')

    def test_manifest_path_alias_retains_canonical_public_identity(self):
        from rulang.packages import load_manifest
        original = self.load("{'名':'工程','公开':['力学','流体/管道']}.")
        parent = self.path.parent / 'spelling-parent'
        parent.mkdir()
        alias = parent / '..' / '集录.ru'
        manifest = load_manifest(alias)
        self.assertEqual(manifest.path, self.path)
        self.assertEqual(manifest.root, self.path.parent)
        self.assertEqual(manifest.public, original.public)
        self.assertEqual(manifest.public[('工程', '力学')], self.path.parent / 'src/力学.ru')

    def test_manifest_never_evaluates_code_and_reports_positions(self):
        for text, line in (("典:\n'名' 对 '工程'.\n'名' 对 '另'. 成.", 3),
                           ("{'名':'工程',\n'错误':1}.", 2),
                           ("{'名':'工程',\n'版':(读)}.", 2),
                           ("{'名':'工程',\n'公开':7}.", 2)):
            with self.subTest(text=text), self.assertRaises(RuError) as caught:
                self.load(text)
            self.assertEqual(caught.exception.line, line)
            self.assertEqual(caught.exception.source_name, str(self.path))


class LocalPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.app, self.lib = self.root / 'app', self.root / 'lib'
        for folder in (self.app, self.lib / 'src'):
            folder.mkdir(parents=True)
        self.write(self.lib / '集录.ru', "{'名':'工程','版':'1.0.0','公开':['力学']}.")
        self.write(self.app / '集录.ru', "{'名':'应用','版':'1.0.0','依赖':{'工':{'路径':'../lib'}}}.")
        self.write(self.lib / 'src/力学.ru', '吾 言 工程 其 力学. 显 1. 数组 取 [0].')

    def write(self, path, source):
        path.write_text(source, encoding='utf-8')
        return path

    def graph(self, source):
        return load_module_graph(self.write(self.app / 'main.ru', source))

    def test_alias_and_path_share_one_instance(self):
        graph = self.graph("甲 取 外言 工 其 力学. 乙 取 外言 '../lib/src/力学.ru'. 甲 其 数组[0] 取 7. 显 乙 其 数组[0].")
        self.assertEqual(len(graph), 2)
        output = io.StringIO()
        Interpreter(stdout=output).execute(graph[graph.root], source_path=graph.root, modules=graph)
        self.assertEqual(output.getvalue(), '1\n7\n')

    def test_explicit_host_absolute_dependency_keeps_public_boundary(self):
        self.write(self.app / '集录.ru', "{'名':'应用','依赖':{'工':{'路径':'" + self.lib.as_posix() + "'}}}.")
        graph = self.graph('甲 取 外言 工 其 力学. 显 甲 其 数组[0].')
        output = io.StringIO()
        Interpreter(stdout=output).execute(graph[graph.root], source_path=graph.root, modules=graph)
        self.assertEqual(output.getvalue(), '1\n0\n')
        self.write(self.lib / 'src/秘密.ru', '值 取 9.')
        with self.assertRaisesRegex(RuError, '公开'):
            self.graph("外言 '" + (self.lib / 'src/秘密.ru').as_posix() + "'.")

    def test_alias_does_not_change_author_declaration(self):
        self.write(self.lib / 'src/力学.ru', '吾 言 工 其 力学. 值 取 1.')
        with self.assertRaisesRegex(RuError, '声明'):
            self.graph('外言 工 其 力学.')

    def test_private_and_undeclared_paths_rejected(self):
        self.write(self.lib / 'src/秘密.ru', '值 取 2.')
        for code in ("外言 '../lib/src/秘密.ru'.", '外言 工 其 秘密.', '外言 工程 其 力学.'):
            with self.subTest(code=code), self.assertRaises(RuError):
                self.graph(code)
        self.write(self.app / '集录.ru', "{'名':'应用','版':'1.0.0'}.")
        with self.assertRaisesRegex(RuError, '依赖'):
            self.graph("外言 '../lib/src/力学.ru'.")

    def test_self_named_import_and_optional_legacy_declaration(self):
        self.write(self.lib / 'src/力学.ru', '值 取 2.')
        graph = load_module_graph(self.write(self.lib / 'main.ru', '甲 取 外言 工程 其 力学. 显 甲 其 值.'))
        self.assertEqual(len(graph), 2)

    def test_path_cannot_escape_via_symlink(self):
        secret = self.write(self.root / 'secret.ru', '值 取 9.')
        try:
            (self.lib / 'src/逃逸.ru').symlink_to(secret)
        except OSError:
            self.skipTest('symlinks unavailable')
        with self.assertRaises(RuError):
            load_module_graph(self.write(self.lib / 'main.ru', "外言 'src/逃逸.ru'."))

    def test_declared_name_is_checked_on_path_import(self):
        self.write(self.lib / 'src/力学.ru', '吾 言 工程 其 其他. 值 取 1.')
        with self.assertRaisesRegex(RuError, '声明'):
            self.graph("外言 '../lib/src/力学.ru'.")

    def test_explicit_public_mapping_has_only_one_named_identity(self):
        self.write(self.lib / '集录.ru', "{'名':'工程','公开':{'力学':'src/内部.ru'}}.")
        self.write(self.lib / 'src/内部.ru', '吾 言 工程 其 力学. 值 取 1.')
        self.assertEqual(len(self.graph('外言 工 其 力学.')), 2)
        with self.assertRaisesRegex(RuError, '正式名称'):
            load_module_graph(self.write(self.lib / 'main.ru', '外言 工程 其 内部.'))

    def test_manifest_file_symlink_cannot_replace_package_owner(self):
        from rulang.packages import find_manifest, load_manifest
        self.path = self.root / 'linked'
        self.path.mkdir()
        try:
            (self.path / '集录.ru').symlink_to(self.lib / '集录.ru')
        except OSError:
            self.skipTest('symlinks unavailable')
        for action in (lambda: load_manifest(self.path),
                       lambda: load_manifest(self.path / '集录.ru'),
                       lambda: find_manifest(self.path / 'main.ru')):
            with self.subTest(action=action), self.assertRaisesRegex(RuError, '符号链接'):
                action()

    def test_direct_interpreter_checks_named_declaration_with_source_path(self):
        source = self.lib / 'src/力学.ru'
        from rulang.compiler import Compiler
        from rulang.js_compiler import JSCompiler
        actions = (lambda: Interpreter().execute(parse('吾 言 其他.'), source_path=source),
                   lambda: Compiler(parse('吾 言 其他.'), str(source)).compile(),
                   lambda: JSCompiler(parse('吾 言 其他.'), str(source)).compile())
        for action in actions:
            with self.subTest(action=action), self.assertRaisesRegex(RuError, '声明'):
                action()

    def test_cycle_retains_existing_error(self):
        self.write(self.lib / 'src/力学.ru', "外言 '力学.ru'.")
        with self.assertRaisesRegex(RuError, '循环'):
            self.graph('外言 工 其 力学.')


if __name__ == '__main__':
    unittest.main()
