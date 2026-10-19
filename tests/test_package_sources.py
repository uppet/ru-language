"""Explicit acquisition, offline resolution, version and archive security tests."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from rulang.frontend import RuError
from rulang.package_sources import (
    validate_constraint, version_satisfies, validate_dependency,
    safe_extract_archive, sync_dependencies, resolve_cached_dependency,
)


def manifest(root, name='工程', version='1.0.0', dependencies='典: 成'):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'src').mkdir(exist_ok=True)
    (root / 'src' / '力学.ru').write_text('吾 言 ' + name + ' 其 力学.\n值 取 7.\n', encoding='utf-8')
    (root / '集录.ru').write_text(
        "典: '名' 对 '" + name + "'. '版' 对 '" + version +
        "'. '公开' 对 ['力学']. '依赖' 对 " + dependencies + '. 成.\n', encoding='utf-8')


def tar_bytes(entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for name, value in entries:
            item = tarfile.TarInfo(name)
            if value is None:
                item.type = tarfile.SYMTYPE
                item.linkname = '../outside'
                archive.addfile(item)
            else:
                item.size = len(value)
                archive.addfile(item, io.BytesIO(value))
    return stream.getvalue()


class Constraints(unittest.TestCase):
    def test_exact_and_comparison_interval(self):
        self.assertTrue(version_satisfies('1.2.3', '1.2.3'))
        self.assertTrue(version_satisfies('1.9.0', '>=1.0.0 <2.0.0'))
        self.assertFalse(version_satisfies('2.0.0', '>=1.0.0 <2.0.0'))
        self.assertTrue(version_satisfies('1.2.3', '=1.2.3'))

    def test_unsupported_constraints_rejected(self):
        for value in ('*', '^1.0.0', '~1.0.0', '1.2', '1.0.0 || 2.0.0',
                      '>=1.0.0,<2.0.0', '1.0.0-beta', '', '01.0.0', '>= 1.0.0'):
            with self.subTest(value=value), self.assertRaises(RuError):
                validate_constraint(value)

    def test_source_identity_preserves_ssh_path_semantics(self):
        from rulang.package_sources import _git_identity
        self.assertEqual(_git_identity('git@EXAMPLE.com:/srv/lib.git'),
                         _git_identity('ssh://git@example.com:22/srv/lib.git'))
        self.assertNotEqual(_git_identity('git@example.com:srv/lib.git'),
                            _git_identity('ssh://git@example.com/srv/lib.git'))
        self.assertEqual(_git_identity('https://EXAMPLE.com:443/lib.git/'),
                         _git_identity('https://example.com/lib.git'))

    def test_sources_are_exclusive_and_secure(self):
        for dependency in ({'路径': '../lib'}, {'Git': 'https://example.com/lib.git', '引用': 'v1', '子目录': 'pkg'},
                           {'Git': 'git@example.com:org/lib.git'},
                           {'目录': 'https://example.com/registry', '包': '力学', '版': '>=1.0.0 <2.0.0'}):
            validate_dependency(dependency)
        for dependency in ({'Git': 'file:///tmp/a'}, {'Git': 'https://user:secret@example.com/a'},
                           {'Git': 'https://example.com/a?token=secret'}, {'Git': 'https://example.com/a', '子目录': '../a'},
                           {'Git': 'https://example.com/a', '引用': '--upload-pack=evil'},
                           {'路径': '../a', 'Git': 'https://example.com/a'},
                           {'目录': 'http://example.com', '包': '甲', '版': '1.0.0'}):
            with self.subTest(dependency=dependency), self.assertRaises(RuError) as error:
                validate_dependency(dependency)
            self.assertNotIn('secret', str(error.exception))


class Archives(unittest.TestCase):
    def test_valid_tar_and_zip(self):
        for kind in ('tar', 'zip'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                if kind == 'tar':
                    data = tar_bytes([('src/main.ru', b'hello')])
                else:
                    output = io.BytesIO()
                    with zipfile.ZipFile(output, 'w') as archive:
                        archive.writestr('src/main.ru', b'hello')
                    data = output.getvalue()
                safe_extract_archive(data, Path(temp) / 'out')
                self.assertEqual((Path(temp) / 'out/src/main.ru').read_bytes(), b'hello')

    def test_traversal_links_duplicates_and_windows_paths(self):
        for entries in ([('../escape', b'x')], [('/absolute', b'x')], [('C:/absolute', b'x')],
                        [('src\\evil', b'x')], [('link', None)], [('a', b'x'), ('a', b'y')],
                        [('A', b'x'), ('a', b'y')], [('a', b'x'), ('a/b', b'y')]):
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(RuError):
                    safe_extract_archive(tar_bytes(entries), Path(temp) / 'out')
                self.assertFalse((Path(temp) / 'escape').exists())

    def test_zip_symlink_and_size_cap(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            item = zipfile.ZipInfo('link')
            item.external_attr = 0o120777 << 16
            archive.writestr(item, '../secret')
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(RuError):
            safe_extract_archive(output.getvalue(), Path(temp) / 'out')
        with tempfile.TemporaryDirectory() as temp, patch('rulang.package_sources.MAX_UNPACKED_BYTES', 3), self.assertRaises(RuError):
            safe_extract_archive(tar_bytes([('large', b'1234')]), Path(temp) / 'out')


class TransportTests(unittest.TestCase):
    def test_https_redirect_cannot_downgrade_or_add_credentials(self):
        from rulang.package_sources import _SecureRedirect
        from urllib.request import Request
        redirect = _SecureRedirect()
        for target in ['http://example.com/a', 'file:///tmp/a', 'https://user:secret@example.com/a', 'https://example.com/a?token=secret']:
            with self.subTest(target=target), self.assertRaises(RuError) as error:
                redirect.redirect_request(Request('https://example.com/a'), None, 302, 'redirect', {}, target)
            self.assertNotIn('secret', str(error.exception))

    def test_download_is_bounded_with_and_without_content_length(self):
        from rulang.package_sources import download_bytes
        class Response(io.BytesIO):
            url = 'https://example.com/archive'
            headers = {}
        class Opener:
            def open(self, request, timeout): return Response(b'12345')
        with patch('rulang.package_sources.build_opener', return_value=Opener()):
            with self.assertRaises(RuError):
                download_bytes('https://example.com/archive', limit=4)
            self.assertEqual(download_bytes('https://example.com/archive', limit=5), b'12345')

    def test_invalid_url_does_not_reach_transport(self):
        from rulang.package_sources import download_bytes
        with patch('rulang.package_sources.build_opener', side_effect=AssertionError('transport')):
            for url in ['https://example.com/a?', 'https://example.com/a#', 'https://example.com:bad/a']:
                with self.subTest(url=url), self.assertRaises(RuError):
                    download_bytes(url)


class Synchronization(unittest.TestCase):
    def test_paths_are_relative_to_manifest_and_marked_mutable(self):
        from rulang.packages import load_manifest
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest(root / 'lib', name='库')
            manifest(root / 'app', dependencies="典: '别名' 对 典: '路径' 对 '../lib'. 成. 成")
            lock = sync_dependencies(root / 'app', cache_dir=root / 'cache')
            self.assertEqual(lock['format'], 2)
            self.assertTrue(lock['packages'][0]['mutable'])
            self.assertEqual(resolve_cached_dependency(load_manifest(root / 'app'), '别名', {'路径': '../lib'}), (root / 'lib').resolve())
            self.assertTrue((root / 'app/集锁.json').is_file())

    def test_missing_remote_cache_never_fetches(self):
        from rulang.packages import load_manifest
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            descriptor = {'Git': 'https://example.com/lib.git'}
            manifest(root, dependencies="典: '别名' 对 典: 'Git' 对 'https://example.com/lib.git'. 成. 成")
            with patch('rulang.package_sources.download_bytes', side_effect=AssertionError('network')), \
                 patch('rulang.package_sources.subprocess.run', side_effect=AssertionError('git')), \
                 self.assertRaisesRegex(RuError, 'ru deps sync'):
                resolve_cached_dependency(load_manifest(root), '别名', descriptor)

    def test_lock_rejects_changed_manifest(self):
        from rulang.packages import load_manifest
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest(root / 'app')
            sync_dependencies(root / 'app', cache_dir=root / 'cache')
            (root / 'app/集录.ru').write_text((root / 'app/集录.ru').read_text(encoding='utf-8') + '\n', encoding='utf-8')
            with self.assertRaisesRegex(RuError, 'ru deps sync'):
                resolve_cached_dependency(load_manifest(root / 'app'), '甲', {'Git': 'https://example.com/a'})

    def test_registry_download_hash_and_offline_cache(self):
        from rulang.packages import load_manifest
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest(root / 'lib', name='库')
            data = tar_bytes([(path.relative_to(root / 'lib').as_posix(), path.read_bytes())
                              for path in (root / 'lib').rglob('*') if path.is_file()])
            metadata = {'sha256': hashlib.sha256(data).hexdigest()}
            class Client:
                def versions(self, name): return ['1.0.0']
                def download(self, name, version): return data, metadata
            manifest(root / 'app', dependencies="典: '别名' 对 典: '目录' 对 'https://registry.example'. '包' 对 '库'. '版' 对 '>=1.0.0 <2.0.0'. 成. 成")
            descriptor = {'目录': 'https://registry.example', '包': '库', '版': '>=1.0.0 <2.0.0'}
            with patch('rulang.package_registry.RegistryClient', return_value=Client()):
                lock = sync_dependencies(root / 'app', cache_dir=root / 'cache')
            with patch('rulang.package_sources.download_bytes', side_effect=AssertionError('network')):
                cached = resolve_cached_dependency(load_manifest(root / 'app'), '别名', descriptor, cache_dir=root / 'cache')
            self.assertEqual(load_manifest(cached).name, '库')
            self.assertEqual(lock['packages'][0]['sha256'], metadata['sha256'])
            (cached / 'src/力学.ru').write_text('tampered', encoding='utf-8')
            with self.assertRaisesRegex(RuError, 'ru deps sync'):
                resolve_cached_dependency(load_manifest(root / 'app'), '别名', descriptor, cache_dir=root / 'cache')
            with patch('rulang.package_registry.RegistryClient', return_value=Client()):
                sync_dependencies(root / 'app', cache_dir=root / 'cache')
            repaired = resolve_cached_dependency(load_manifest(root / 'app'), '别名', descriptor, cache_dir=root / 'cache')
            self.assertIn('吾 言 库', (repaired / 'src/力学.ru').read_text(encoding='utf-8'))


class GraphAndGitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / 'cache'

    def archive(self, name='库', version='1.0.0', dependencies='典: 成'):
        path = self.root / ('fixture-' + name + version)
        manifest(path, name=name, version=version, dependencies=dependencies)
        return tar_bytes([(item.relative_to(path).as_posix(), item.read_bytes())
                          for item in path.rglob('*') if item.is_file()])

    def test_git_ref_subdir_full_commit_and_no_implicit_fetch(self):
        from rulang.packages import load_manifest
        descriptor = {'Git': 'https://example.com/lib.git', '引用': 'release', '子目录': 'packages/lib'}
        manifest(self.root / 'app', dependencies="典: '甲' 对 典: 'Git' 对 'https://example.com/lib.git'. '引用' 对 'release'. '子目录' 对 'packages/lib'. 成. 成")
        data, calls = self.archive(), []
        def command(args, cwd, **kwargs):
            calls.append(args)
            if args[0] == 'rev-parse': return b'a' * 40 + b'\n'
            if args[0] == 'archive': return data
            return b''
        with patch('rulang.package_sources._git_command', side_effect=command):
            lock = sync_dependencies(self.root / 'app', cache_dir=self.cache)
        self.assertEqual(lock['packages'][0]['commit'], 'a' * 40)
        self.assertEqual(calls[-1][-1], 'a' * 40 + ':packages/lib')
        self.assertEqual(calls[1][-1], 'release')
        with patch('rulang.package_sources._git_command', side_effect=AssertionError('offline')):
            result = resolve_cached_dependency(load_manifest(self.root / 'app'), '甲', descriptor, cache_dir=self.cache)
        self.assertEqual(load_manifest(result).name, '库')
        self.assertFalse((result / '.git').exists())

    def test_same_git_source_different_commit_conflicts_and_preserves_lock(self):
        app = self.root / 'app'
        manifest(app)
        sync_dependencies(app, cache_dir=self.cache)
        before = (app / '集锁.json').read_bytes()
        manifest(app, dependencies="典: '甲' 对 典: 'Git' 对 'https://example.com/a'. '引用' 对 'one'. 成. '乙' 对 典: 'Git' 对 'https://example.com/a'. '引用' 对 'two'. 成. 成")
        def fetch(descriptor, staging):
            safe_extract_archive(self.archive(), staging)
            return ('a' if descriptor['引用'] == 'one' else 'b') * 40
        with patch('rulang.package_sources._fetch_git', side_effect=fetch), self.assertRaisesRegex(RuError, '不同版本|多版本'):
            sync_dependencies(app, cache_dir=self.cache, update=True)
        self.assertEqual((app / '集锁.json').read_bytes(), before)
        self.assertFalse(any(self.cache.glob('.ru-stage-*')))

    def test_registry_intersecting_constraints_select_single_common_version(self):
        manifest(self.root / 'app', dependencies="典: '甲' 对 典: '路径' 对 '../first'. 成. '乙' 对 典: '路径' 对 '../second'. 成. 成")
        for directory, name, constraint in [('first', '第一', '>=1.0.0 <3.0.0'), ('second', '第二', '<2.0.0')]:
            manifest(self.root / directory, name=name, dependencies="典: '库别名' 对 典: '目录' 对 'https://registry.example'. '包' 对 '库'. '版' 对 '" + constraint + "'. 成. 成")
        archives = {version: self.archive(version=version) for version in ['1.0.0', '2.0.0']}
        class Client:
            def versions(self, name): return list(archives)
            def download(self, name, version):
                data = archives[version]
                return data, {'sha256': hashlib.sha256(data).hexdigest()}
        with patch('rulang.package_registry.RegistryClient', return_value=Client()):
            lock = sync_dependencies(self.root / 'app', cache_dir=self.cache)
        records = [record for record in lock['packages'] if record['kind'] == 'registry']
        self.assertEqual([record['version'] for record in records], ['1.0.0'])

    def test_registry_disjoint_constraints_rejected(self):
        manifest(self.root / 'app', dependencies="典: '甲' 对 典: '目录' 对 'https://registry.example'. '包' 对 '库'. '版' 对 '1.0.0'. 成. '乙' 对 典: '目录' 对 'https://registry.example'. '包' 对 '库'. '版' 对 '2.0.0'. 成. 成")
        archives = {version: self.archive(version=version) for version in ['1.0.0', '2.0.0']}
        class Client:
            def versions(self, name): return ['1.0.0', '2.0.0']
            def download(self, name, version):
                data = archives[version]
                return data, {'sha256': hashlib.sha256(data).hexdigest()}
        with patch('rulang.package_registry.RegistryClient', return_value=Client()), self.assertRaisesRegex(RuError, '约束冲突'):
            sync_dependencies(self.root / 'app', cache_dir=self.cache)
        self.assertFalse((self.root / 'app/集锁.json').exists())

    def test_hash_mismatch_never_publishes_cache_or_lock(self):
        manifest(self.root / 'app', dependencies="典: '甲' 对 典: '目录' 对 'https://registry.example'. '包' 对 '库'. '版' 对 '1.0.0'. 成. 成")
        data = self.archive()
        class Client:
            def versions(self, name): return ['1.0.0']
            def download(self, name, version): return data, {'sha256': 'a' * 64}
        with patch('rulang.package_registry.RegistryClient', return_value=Client()), self.assertRaisesRegex(RuError, 'SHA-256'):
            sync_dependencies(self.root / 'app', cache_dir=self.cache)
        self.assertEqual(list(self.cache.iterdir()), [])
        self.assertFalse((self.root / 'app/集锁.json').exists())

    def test_transitive_remote_resolution_uses_project_lock_offline(self):
        from rulang.packages import load_manifest
        app = self.root / 'app'
        manifest(app, dependencies="典: '中间' 对 典: '目录' 对 'https://registry.example'. '包' 对 '中包'. '版' 对 '1.0.0'. 成. 成")
        child_descriptor = {'目录': 'https://registry.example', '包': '末包', '版': '1.0.0'}
        archives = {
            '中包': self.archive('中包', dependencies="典: '末端' 对 典: '目录' 对 'https://registry.example'. '包' 对 '末包'. '版' 对 '1.0.0'. 成. 成"),
            '末包': self.archive('末包')}
        class Client:
            def versions(self, name): return ['1.0.0']
            def download(self, name, version):
                data = archives[name]
                return data, {'sha256': hashlib.sha256(data).hexdigest()}
        with patch('rulang.package_registry.RegistryClient', return_value=Client()):
            sync_dependencies(app, cache_dir=self.cache)
        with patch('rulang.package_sources.download_bytes', side_effect=AssertionError('network')), \
             patch('rulang.package_sources._git_command', side_effect=AssertionError('git')):
            owner = load_manifest(app)
            middle = load_manifest(resolve_cached_dependency(owner, '中间', owner.dependencies['中间'], cache_dir=self.cache))
            leaf = resolve_cached_dependency(middle, '末端', child_descriptor, project_root=app, cache_dir=self.cache)
            self.assertEqual(load_manifest(leaf).name, '末包')

    def test_nested_remote_path_dependency_cannot_escape_archive(self):
        root = self.root / 'fixture'
        manifest(root, name='库', dependencies="典: '子包' 对 典: '路径' 对 'nested'. 成. 成")
        manifest(root / 'nested', name='嵌套', dependencies="典: '越界' 对 典: '路径' 对 '../../escape'. 成. 成")
        data = tar_bytes([(path.relative_to(root).as_posix(), path.read_bytes())
                          for path in root.rglob('*') if path.is_file()])
        manifest(self.root / 'app', dependencies="典: '甲' 对 典: 'Git' 对 'https://example.com/a'. 成. 成")
        def fetch(descriptor, staging):
            safe_extract_archive(data, staging)
            return 'a' * 40
        with patch('rulang.package_sources._fetch_git', side_effect=fetch), self.assertRaisesRegex(RuError, '归档边界'):
            sync_dependencies(self.root / 'app', cache_dir=self.cache)
        self.assertFalse((self.root / 'app/集锁.json').exists())

    def test_registry_metadata_dependencies_must_match_archive(self):
        manifest(self.root / 'app', dependencies="典: '甲' 对 典: '目录' 对 'https://registry.example'. '包' 对 '库'. '版' 对 '1.0.0'. 成. 成")
        data = self.archive()
        class Client:
            def versions(self, name): return ['1.0.0']
            def download(self, name, version):
                return data, {'sha256': hashlib.sha256(data).hexdigest(), 'dependencies': {'隐藏': {'路径': 'hidden'}}}
        with patch('rulang.package_registry.RegistryClient', return_value=Client()), self.assertRaisesRegex(RuError, '元数据.*依赖'):
            sync_dependencies(self.root / 'app', cache_dir=self.cache)

    def test_git_command_ignores_ambient_unsafe_config(self):
        from rulang.package_sources import _git_command
        import shutil
        if shutil.which('git') is None:
            self.skipTest('Git unavailable')
        work = self.root / 'git'
        work.mkdir()
        # This is a real, network-free subprocess invocation. A hostile global
        # helper/config path must not be consulted by package acquisition.
        with patch.dict('os.environ', {'GIT_CONFIG_GLOBAL': '/must/not/read', 'GIT_TRACE': '1'}):
            self.assertIn(b'Initialized empty Git repository', _git_command(['init', '--bare', '.'], work))


class LockBindingReviewTests(unittest.TestCase):
    def setUp(self):
        import copy
        from rulang.packages import load_manifest
        self.copy = copy.deepcopy
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / 'app'
        self.cache = self.root / 'cache'
        self.descriptor = {'目录': 'https://example.test/registry', '包': '库', '版': '1.0.0'}
        manifest(self.app, dependencies="典: '别名' 对 典: '目录' 对 'https://example.test/registry'. '包' 对 '库'. '版' 对 '1.0.0'. 成. 成")
        manifest(self.root / 'lib', name='库')
        data = tar_bytes([(path.relative_to(self.root / 'lib').as_posix(), path.read_bytes())
                          for path in (self.root / 'lib').rglob('*') if path.is_file()])
        class Client:
            def versions(self, name): return ['1.0.0']
            def download(self, name, version): return data, {'sha256': hashlib.sha256(data).hexdigest()}
        with patch('rulang.package_registry.RegistryClient', return_value=Client()):
            self.lock = sync_dependencies(self.app, cache_dir=self.cache)
        self.owner = load_manifest(self.app)
        resolve_cached_dependency(self.owner, '别名', self.descriptor, cache_dir=self.cache)

    def reject(self, lock):
        (self.app / '集锁.json').write_text(json.dumps(lock, ensure_ascii=False), encoding='utf-8')
        with patch('rulang.package_sources.download_bytes', side_effect=AssertionError('network')), \
             patch('rulang.package_sources._git_command', side_effect=AssertionError('git')), \
             self.assertRaisesRegex(RuError, 'ru deps sync'):
            resolve_cached_dependency(self.owner, '别名', self.descriptor, cache_dir=self.cache)

    def test_cache_key_and_tree_hash_cannot_substitute_another_package(self):
        from rulang.package_sources import _tree_hash
        fake = self.cache / ('e' * 64) / 'package'
        manifest(fake, name='恶包', version='9.0.0')
        lock = self.copy(self.lock)
        lock['packages'][0].update(cache_key='e' * 64, tree_sha256=_tree_hash(fake))
        self.reject(lock)

    def test_edge_target_identity_must_match_source(self):
        lock = self.copy(self.lock)
        lock['edges'][0]['identity'] = 'registry:https://other.test#恶包'
        self.reject(lock)

    def test_locked_record_metadata_must_match_descriptor_and_cache_key(self):
        for key, value in [('kind', 'git'), ('url', 'https://other.test'), ('name', '恶包'),
                           ('version', '9.0.0'), ('sha256', 'e' * 64), ('mutable', True)]:
            with self.subTest(key=key):
                lock = self.copy(self.lock)
                lock['packages'][0][key] = value
                self.reject(lock)

    def test_cached_manifest_must_match_locked_package_even_with_updated_tree_hash(self):
        from rulang.package_sources import _tree_hash
        lock = self.copy(self.lock)
        root = self.cache / lock['packages'][0]['cache_key'] / 'package'
        manifest(root, name='恶包', version='9.0.0')
        lock['packages'][0]['tree_sha256'] = _tree_hash(root)
        self.reject(lock)

    def test_git_commit_and_key_are_bound(self):
        from rulang.package_sources import _validate_cached, _tree_hash, _sha
        identity, commit = 'git:https://example.test/repo#', 'a' * 40
        key = _sha((identity + '\0' + commit).encode())
        root = self.cache / key / 'package'
        manifest(root, name='库')
        record = {'identity': identity, 'kind': 'git', 'url': 'https://example.test/repo',
                  'commit': commit, 'subdir': '', 'mutable': False, 'name': '库', 'version': '1.0.0',
                  'cache_key': key, 'tree_sha256': _tree_hash(root)}
        self.assertEqual(_validate_cached(record, self.cache), root)
        for field, value in [('commit', 'b' * 40), ('url', 'https://other.test/repo'), ('subdir', 'nested')]:
            changed = dict(record, **{field: value})
            with self.subTest(field=field), self.assertRaisesRegex(RuError, 'ru deps sync'):
                _validate_cached(changed, self.cache)

    def test_git_ssh_encoded_or_dot_paths_are_rejected(self):
        from rulang.package_sources import _git_identity
        for url in ['ssh://git@example.test/%72epo.git', 'ssh://git@%65xample.test/repo.git',
                    'ssh://git@example.test/base/../repo.git', 'ssh://git@example.test/./repo.git']:
            with self.subTest(url=url), self.assertRaises(RuError):
                _git_identity(url)

    def test_registry_dot_and_percent_path_aliases_are_rejected(self):
        from rulang.package_registry import RegistryClient
        from rulang.package_sources import _source_identity
        for suffix in ['/registry/.', '/registry/../registry', '/registry/%2e',
                       '/registry/%2E%2E/registry', '/%72egistry', '/registry/%2fchild',
                       '/registry//child']:
            url = 'https://example.test' + suffix
            with self.subTest(url=url):
                with self.assertRaises(RuError):
                    _source_identity(self.owner, dict(self.descriptor, 目录=url))
                with self.assertRaises(RuError):
                    RegistryClient(url, fetcher=lambda url: self.fail('transport invoked'))


class PackageCliTests(unittest.TestCase):
    def test_parser_preserves_old_commands_and_adds_explicit_tools(self):
        from rulang.cli import make_parser
        parser = make_parser()
        self.assertEqual(parser.parse_args(['deps', 'sync']).directory, '.')
        self.assertEqual(parser.parse_args(['run', 'main.ru', 'hello']).args, ['hello'])
        parsed = parser.parse_args(['registry', 'download', '工程', '1.0.0', '--registry', './registry', '-o', './out.tar.gz'])
        self.assertEqual(parsed.registry_command, 'download')

    def test_sync_cli_and_local_publish_roundtrip(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest(root / 'app')
            process = subprocess.run([sys.executable, '-m', 'rulang', 'deps', 'sync', str(root / 'app')], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            registry = root / 'registry'
            process = subprocess.run([sys.executable, '-m', 'rulang', 'registry', 'publish', str(root / 'app'), '--registry', str(registry)], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            process = subprocess.run([sys.executable, '-m', 'rulang', 'registry', 'versions', '工程', '--registry', str(registry)], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout), ['1.0.0'])
            output = root / 'archive.tar.gz'
            command = [sys.executable, '-m', 'rulang', 'registry', 'download', '工程', '1.0.0', '--registry', str(registry), '-o', str(output)]
            process = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            before = output.read_bytes()
            process = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(process.returncode, 1)
            self.assertEqual(output.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
