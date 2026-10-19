"""Registry protocol -> verified cache -> shared offline language graph."""
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from rulang.cli import build
from rulang.frontend import RuError
from rulang.interpreter import Interpreter
from rulang.modules import load_module_graph
from rulang.package_registry import publish_local
from rulang.package_sources import sync_dependencies

CC = os.environ.get('CC') or shutil.which('gcc') or shutil.which('cc')
NODE = shutil.which('node')


class PackagePipelineTests(unittest.TestCase):
    def test_real_registry_contract_to_offline_three_backend_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            lib, app, registry = root / 'lib', root / 'app', root / 'registry'
            (lib / 'src').mkdir(parents=True)
            app.mkdir()
            (lib / '集录.ru').write_text("{'名':'工程','版':'1.0.0','公开':['力学']}.", encoding='utf-8')
            (lib / 'src/力学.ru').write_text("吾 言 工程 其 力学. 显 '初始化'. 值 取 7.", encoding='utf-8')
            publish_local(lib, registry)
            (app / '集录.ru').write_text("{'名':'应用','依赖':{'物理':{'目录':'https://registry.example.test/ru','包':'工程','版':'1.0.0'}}}.", encoding='utf-8')
            main = app / 'main.ru'
            main.write_text('甲 取 外言 物理 其 力学. 乙 取 外言 物理 其 力学. 显 乙 其 值.', encoding='utf-8')
            calls = []
            def fetch(url, limit):
                calls.append(url)
                parsed = urlsplit(url)
                self.assertEqual(parsed.netloc, 'registry.example.test')
                self.assertTrue(parsed.path.startswith('/ru/'))
                data = (registry / unquote(parsed.path[len('/ru/'):])).read_bytes()
                self.assertLessEqual(len(data), limit)
                return data
            with patch('rulang.package_sources.download_bytes', side_effect=fetch):
                sync_dependencies(app, cache_dir=root / 'cache')
            self.assertTrue(any('/packages/' in url for url in calls))
            self.assertTrue(any('/archives/' in url for url in calls))
            # Cached code remains available after its publishing source is gone.
            shutil.rmtree(lib)
            with patch.dict(os.environ, {'RU_PACKAGE_CACHE': str(root / 'cache')}), \
                 patch('rulang.package_sources.download_bytes', side_effect=AssertionError('implicit network')), \
                 patch('rulang.package_sources._git_command', side_effect=AssertionError('implicit Git')):
                graph = load_module_graph(main)
                self.assertEqual(len(graph), 2)
                output = io.StringIO()
                Interpreter(stdout=output).execute(graph[graph.root], source_path=main, modules=graph)
                self.assertEqual(output.getvalue(), '初始化\n7\n')
                binaries = []
                if CC:
                    binary = root / 'program.exe'
                    build(graph[graph.root], main, binary, cc=CC, modules=graph)
                    binaries.append([str(binary)])
                if NODE:
                    script = root / 'program.js'
                    build(graph[graph.root], main, script, target='js', modules=graph)
                    binaries.append([NODE, str(script)])
            # Standalone products must not consult sources or caches at runtime.
            shutil.rmtree(root / 'cache')
            shutil.rmtree(app)
            for command in binaries:
                result = subprocess.run(command, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '初始化\n7\n')

    def test_moved_project_restores_locked_transitive_package_in_new_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            original, moved = root / 'original', root / 'moved'
            app, bridge = original / 'app', original / 'bridge'
            library, registry = root / 'library', root / 'registry'
            old_cache, new_cache = root / 'old-cache', root / 'new-cache'
            app.mkdir(parents=True)
            (bridge / 'src').mkdir(parents=True)
            (library / 'src').mkdir(parents=True)
            (app / '集录.ru').write_text("{'名':'应用','依赖':{'本地':{'路径':'../bridge'}}}.", encoding='utf-8')
            (app / 'main.ru').write_text('桥 取 外言 本地 其 代理. 显 桥 其 值.', encoding='utf-8')
            (bridge / '集录.ru').write_text("{'名':'桥','公开':['代理'],'依赖':{'物理':{'目录':'https://registry.example.test/ru','包':'工程','版':'>=1.0.0 <2.0.0'}}}.", encoding='utf-8')
            (bridge / 'src/代理.ru').write_text('吾 言 桥 其 代理. 工 取 外言 物理 其 力学. 值 取 工 其 值.', encoding='utf-8')

            def publish(version, value):
                (library / '集录.ru').write_text("{'名':'工程','版':'" + version + "','公开':['力学']}.", encoding='utf-8')
                (library / 'src/力学.ru').write_text('吾 言 工程 其 力学. 值 取 ' + str(value) + '.', encoding='utf-8')
                publish_local(library, registry)

            def fetch(url, limit):
                parsed = urlsplit(url)
                self.assertEqual(parsed.netloc, 'registry.example.test')
                self.assertTrue(parsed.path.startswith('/ru/'))
                data = (registry / unquote(parsed.path[len('/ru/'):])).read_bytes()
                self.assertLessEqual(len(data), limit)
                return data

            publish('1.0.0', 7)
            with patch('rulang.package_sources.download_bytes', side_effect=fetch):
                sync_dependencies(app, cache_dir=old_cache)
            lock_bytes = (app / '集锁.json').read_bytes()
            publish('1.1.0', 99)
            shutil.copytree(original, moved)
            shutil.rmtree(original)
            shutil.rmtree(old_cache)
            app, main = moved / 'app', moved / 'app/main.ru'
            with patch('rulang.package_sources.download_bytes', side_effect=fetch), \
                 patch('rulang.package_registry.RegistryClient.versions', side_effect=AssertionError('locked version selection')):
                sync_dependencies(app, cache_dir=new_cache, locked=True)
            self.assertEqual((app / '集锁.json').read_bytes(), lock_bytes)
            self.assertNotIn(str(original).encode(), lock_bytes)
            self.assertNotIn(str(old_cache).encode(), lock_bytes)
            with patch.dict(os.environ, {'RU_PACKAGE_CACHE': str(new_cache)}), \
                 patch('rulang.package_sources.download_bytes', side_effect=AssertionError('implicit network')), \
                 patch('rulang.package_sources._git_command', side_effect=AssertionError('implicit Git')):
                # Default sync also preserves a valid selection and uses the cache.
                sync_dependencies(app)
                self.assertEqual((app / '集锁.json').read_bytes(), lock_bytes)
                graph = load_module_graph(main)
                self.assertEqual(len(graph), 3)
                output = io.StringIO()
                Interpreter(stdout=output).execute(graph[graph.root], source_path=main, modules=graph)
                self.assertEqual(output.getvalue(), '7\n')
                binaries = []
                if CC:
                    binary = root / 'moved-program.exe'
                    build(graph[graph.root], main, binary, cc=CC, modules=graph)
                    binaries.append([str(binary)])
                if NODE:
                    script = root / 'moved-program.js'
                    build(graph[graph.root], main, script, target='js', modules=graph)
                    binaries.append([NODE, str(script)])
            shutil.rmtree(moved)
            shutil.rmtree(new_cache)
            for command in binaries:
                result = subprocess.run(command, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '7\n')

    def test_dormant_missing_remote_import_reports_sync_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '集录.ru').write_text("{'名':'应用','依赖':{'物理':{'Git':'https://example.test/repo.git'}}}.", encoding='utf-8')
            main = root / 'main.ru'
            main.write_text('算 未用: 得 外言 物理 其 力学. 法.', encoding='utf-8')
            with patch('rulang.package_sources.download_bytes', side_effect=AssertionError('implicit network')), \
                 patch('rulang.package_sources._git_command', side_effect=AssertionError('implicit Git')), \
                 self.assertRaisesRegex(RuError, 'ru deps sync'):
                load_module_graph(main)
