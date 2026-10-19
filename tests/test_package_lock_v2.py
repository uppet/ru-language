"""Portable, exact lock restoration; every fixture is local and transport-injected."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from rulang.frontend import RuError
from rulang.packages import load_manifest
from rulang.package_sources import sync_dependencies, resolve_cached_dependency, safe_extract_archive
from test_package_sources import manifest, tar_bytes


class PortableLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / 'work/app'
        self.cache = self.root / 'cache-one'
        self.descriptor = {'目录': 'https://example.test/registry', '包': '库', '版': '>=1.0.0 <3.0.0'}
        self.archives = {}
        self.available = ['1.0.0']
        self.downloads, self.version_calls = [], []
        for version in ['1.0.0', '2.0.0']:
            path = self.root / ('lib-' + version)
            manifest(path, name='库', version=version)
            self.archives[version] = tar_bytes([(file.relative_to(path).as_posix(), file.read_bytes())
                                               for file in path.rglob('*') if file.is_file()])
        outer = self
        class Client:
            def versions(self, name):
                outer.version_calls.append(name)
                return outer.available[:]
            def download(self, name, version):
                outer.downloads.append((name, version))
                data = outer.archives[version]
                return data, {'sha256': hashlib.sha256(data).hexdigest()}
        self.client_patch = patch('rulang.package_registry.RegistryClient', return_value=Client())
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        manifest(self.app, dependencies="典: '别名' 对 典: '目录' 对 'https://example.test/registry'. '包' 对 '库'. '版' 对 '>=1.0.0 <3.0.0'. 成. 成")

    def sync(self, **kwargs):
        return sync_dependencies(self.app, cache_dir=self.cache, **kwargs)

    def lock_bytes(self):
        return (self.app / '集锁.json').read_bytes()

    def test_format_two_contains_no_machine_root_or_cache(self):
        lock = self.sync()
        self.assertEqual(lock['format'], 2)
        self.assertNotIn('root', lock)
        self.assertNotIn('cache', lock)
        self.assertEqual(lock['owners']['root']['locator'], {'kind': 'project'})
        text = self.lock_bytes().decode()
        self.assertNotIn(str(self.root), text)
        record = lock['packages'][0]
        self.assertEqual(lock['owners'][record['owner']]['locator'],
                         {'kind': 'cache', 'cache_key': record['cache_key'], 'path': '.'})

    def test_existing_default_and_locked_keep_version_and_bytes_without_network(self):
        self.sync()
        before = self.lock_bytes()
        self.available = ['1.0.0', '2.0.0']
        self.version_calls.clear()
        self.downloads.clear()
        self.sync()
        self.sync(locked=True)
        self.assertEqual(self.lock_bytes(), before)
        self.assertEqual(self.version_calls, [])
        self.assertEqual(self.downloads, [])

    def test_update_is_the_only_operation_that_reselects(self):
        self.sync()
        before = self.lock_bytes()
        self.available = ['1.0.0', '2.0.0']
        lock = self.sync(update=True)
        self.assertEqual(lock['packages'][0]['version'], '2.0.0')
        self.assertNotEqual(self.lock_bytes(), before)

    def test_move_project_and_empty_cache_restore_exact_version(self):
        self.sync()
        before = self.lock_bytes()
        moved = self.root / 'moved'
        shutil.move(str(self.app.parent), moved)
        self.app = moved / 'app'
        self.cache = self.root / 'cache-two'
        self.available = ['2.0.0']
        self.version_calls.clear()
        self.downloads.clear()
        self.sync(locked=True)
        self.assertEqual(self.lock_bytes(), before)
        self.assertEqual(self.version_calls, [])
        self.assertEqual(self.downloads, [('库', '1.0.0')])
        cached = resolve_cached_dependency(load_manifest(self.app), '别名', self.descriptor, cache_dir=self.cache)
        self.assertEqual(load_manifest(cached).version, '1.0.0')

    def test_current_environment_cache_is_used_after_move(self):
        self.sync()
        new_cache = self.root / 'current-cache'
        with patch.dict(os.environ, {'RU_PACKAGE_CACHE': str(new_cache)}):
            sync_dependencies(self.app, locked=True)
            cached = resolve_cached_dependency(load_manifest(self.app), '别名', self.descriptor)
        self.assertTrue(cached.is_relative_to(new_cache))

    def test_missing_lock_and_mutually_exclusive_modes_fail_without_fetch(self):
        with self.assertRaisesRegex(RuError, '锁'):
            self.sync(locked=True)
        with self.assertRaises(RuError):
            self.sync(locked=True, update=True)
        self.assertEqual(self.version_calls, [])
        self.assertEqual(self.downloads, [])
        self.assertFalse((self.app / '集锁.json').exists())

    def test_old_format_and_corruption_require_explicit_update(self):
        for content in [b'{"format": 1, "root": "/old/machine"}', b'{broken']:
            (self.app / '集锁.json').write_bytes(content)
            for mode in ({}, {'locked': True}):
                with self.subTest(content=content, mode=mode), self.assertRaisesRegex(RuError, '--update'):
                    self.sync(**mode)
                self.assertEqual(self.lock_bytes(), content)
        self.assertEqual(self.version_calls, [])
        self.assertEqual(self.downloads, [])
        self.assertEqual(self.sync(update=True)['format'], 2)

    def test_changed_manifest_fails_without_silent_resolution(self):
        self.sync()
        before = self.lock_bytes()
        path = self.app / '集录.ru'
        path.write_text(path.read_text(encoding='utf-8') + '\n', encoding='utf-8')
        self.version_calls.clear()
        self.downloads.clear()
        with self.assertRaisesRegex(RuError, '--update'):
            self.sync()
        self.assertEqual(self.lock_bytes(), before)
        self.assertEqual(self.version_calls, [])
        self.assertEqual(self.downloads, [])

    def test_changed_registry_archive_fails_and_keeps_lock_and_old_good_cache(self):
        lock = self.sync()
        before = self.lock_bytes()
        good_cache = self.cache
        original_tree = good_cache / lock['packages'][0]['cache_key'] / 'package/src/力学.ru'
        original_data = original_tree.read_bytes()
        self.cache = self.root / 'empty-cache'
        self.archives['1.0.0'] = self.archives['2.0.0']
        with self.assertRaisesRegex(RuError, 'SHA|摘要|锁'):
            self.sync(locked=True)
        self.assertEqual(self.lock_bytes(), before)
        self.assertEqual(original_tree.read_bytes(), original_data)
        self.assertFalse((self.cache / lock['packages'][0]['cache_key']).exists())

    def test_damaged_cache_is_repaired_from_same_locked_artifact(self):
        lock = self.sync()
        before = self.lock_bytes()
        source = self.cache / lock['packages'][0]['cache_key'] / 'package/src/力学.ru'
        source.write_text('changed', encoding='utf-8')
        self.available = ['2.0.0']
        self.version_calls.clear()
        self.downloads.clear()
        self.sync(locked=True)
        self.assertEqual(self.lock_bytes(), before)
        self.assertEqual(self.version_calls, [])
        self.assertEqual(self.downloads, [('库', '1.0.0')])
        self.assertIn('吾 言 库', source.read_text(encoding='utf-8'))

    def test_regular_file_cache_damage_is_repaired_without_leftovers(self):
        lock = self.sync()
        before = self.lock_bytes()
        entry = self.cache / lock['packages'][0]['cache_key']
        shutil.rmtree(entry)
        entry.write_bytes(b'corrupted cache entry')
        self.available = ['2.0.0']
        self.version_calls.clear()
        self.downloads.clear()
        self.sync(locked=True)
        self.assertEqual(self.lock_bytes(), before)
        self.assertEqual(self.version_calls, [])
        self.assertEqual(self.downloads, [('库', '1.0.0')])
        self.assertEqual(list(self.cache.iterdir()), [entry])
        self.assertEqual(resolve_cached_dependency(load_manifest(self.app), '别名', self.descriptor,
                                                  cache_dir=self.cache), entry / 'package')

    def test_failed_cache_publish_preserves_original_even_when_rollback_fails(self):
        for rollback_fails in (False, True):
            with self.subTest(rollback_fails=rollback_fails):
                self.cache = self.root / ('rollback-cache-' + str(rollback_fails))
                lock = self.sync()
                before = self.lock_bytes()
                entry = self.cache / lock['packages'][0]['cache_key']
                source = Path('package/src/力学.ru')
                original = b'locally damaged cache retained for recovery'
                (entry / source).write_bytes(original)
                actual_replace, calls = os.replace, []

                def fail_replace(src, dst):
                    calls.append((src, dst))
                    if len(calls) == 2 or rollback_fails and len(calls) == 3:
                        raise OSError('injected cache publish/rollback failure')
                    return actual_replace(src, dst)

                with patch('rulang.package_sources.os.replace', side_effect=fail_replace):
                    with self.assertRaises(RuError) as error:
                        self.sync(locked=True)
                self.assertEqual(len(calls), 3)
                self.assertEqual(self.lock_bytes(), before)
                self.assertEqual(list(self.cache.glob('.ru-stage-*')), [])
                if rollback_fails:
                    backups = list(self.cache.glob('.ru-damaged-*'))
                    self.assertEqual(len(backups), 1)
                    self.assertEqual((backups[0] / source).read_bytes(), original)
                    self.assertIn('备份保留', str(error.exception))
                    self.assertIn(str(backups[0]), str(error.exception))
                else:
                    self.assertEqual(list(self.cache.iterdir()), [entry])
                    self.assertEqual((entry / source).read_bytes(), original)

    def test_sibling_paths_and_aliases_move_without_absolute_owner_paths(self):
        library = self.app.parent / 'lib'
        manifest(library, name='本地', dependencies="典: '远端' 对 典: '目录' 对 'https://example.test/registry'. '包' 对 '库'. '版' 对 '>=1.0.0 <3.0.0'. 成. 成")
        manifest(self.app, dependencies="典: '甲' 对 典: '路径' 对 '../lib'. 成. '乙' 对 典: '路径' 对 '../lib'. 成. 成")
        lock = self.sync()
        path_records = [p for p in lock['packages'] if p['kind'] == 'path']
        self.assertEqual(len(path_records), 1)
        self.assertTrue(path_records[0]['portable'])
        self.assertEqual(lock['owners'][path_records[0]['owner']]['locator'], {'kind': 'via', 'owner': 'root', 'alias': '乙'})
        self.assertNotIn(str(self.root), self.lock_bytes().decode())
        before = self.lock_bytes()
        moved = self.root / 'moved'
        shutil.move(str(self.app.parent), moved)
        self.app = moved / 'app'
        self.cache = self.root / 'empty-cache'
        self.sync(locked=True)
        self.assertEqual(self.lock_bytes(), before)
        owner = load_manifest(moved / 'lib')
        cached = resolve_cached_dependency(owner, '远端', owner.dependencies['远端'], project_root=self.app, cache_dir=self.cache)
        self.assertEqual(load_manifest(cached).version, '1.0.0')

    def test_native_absolute_path_descriptor_preserved_and_marked_nonportable(self):
        library = self.root / 'outside-library'
        manifest(library, name='本地')
        descriptor = {'路径': str(library)}
        (self.app / '集录.ru').write_text(json.dumps({'名': '工程', '版': '1.0.0', '依赖': {'外部': descriptor}}, ensure_ascii=False) + '.', encoding='utf-8')
        lock = self.sync()
        record = lock['packages'][0]
        self.assertFalse(record['portable'])
        self.assertNotIn('path', record)
        self.assertEqual(lock['edges'][0]['descriptor'], descriptor)
        self.assertEqual(lock['owners'][record['owner']]['locator'], {'kind': 'via', 'owner': 'root', 'alias': '外部'})
        self.sync(locked=True)

    def test_foreign_drive_path_is_not_interpreted_as_relative(self):
        from rulang.package_sources import validate_dependency
        if os.name == 'nt':
            self.skipTest('POSIX-only foreign-drive check')
        for value in ['D:\\library', 'D:/library', '\\\\server\\share\\library']:
            with self.subTest(value=value), self.assertRaises(RuError):
                validate_dependency({'路径': value})

    def test_windows_drive_and_unc_lexical_contract_without_relpath(self):
        from pathlib import PureWindowsPath
        from rulang.package_sources import validate_dependency, _native_path
        with patch('rulang.package_sources.os.name', 'nt'), patch('rulang.package_sources.Path', PureWindowsPath):
            for value in ['D:\\library', 'D:/library', '\\\\server\\share\\library']:
                with self.subTest(value=value):
                    validate_dependency({'路径': value})
                    self.assertTrue(_native_path(value).is_absolute())
            for value in ['D:library', '\\library']:
                with self.subTest(value=value), self.assertRaises(RuError):
                    validate_dependency({'路径': value})

    def test_locator_edge_and_cache_tampering_fail_closed(self):
        lock = self.sync()
        record = lock['packages'][0]
        for mutation in ('locator', 'edge', 'cache_key', 'manifest', 'owner_cycle', 'extra_owner'):
            changed = copy.deepcopy(lock)
            if mutation == 'locator': changed['owners'][record['owner']]['locator']['path'] = '../escape'
            elif mutation == 'edge': changed['edges'][0]['identity'] = 'registry:https://evil.test#恶'
            elif mutation == 'cache_key': changed['packages'][0]['cache_key'] = 'e' * 64
            elif mutation == 'manifest': changed['owners']['root']['manifest_sha256'] = 'e' * 64
            elif mutation == 'owner_cycle': changed['owners'][record['owner']]['locator'] = {'kind': 'via', 'owner': record['owner'], 'alias': '别名'}
            else: changed['owners']['unused'] = copy.deepcopy(changed['owners']['root'])
            encoded = json.dumps(changed, ensure_ascii=False).encode()
            (self.app / '集锁.json').write_bytes(encoded)
            with self.subTest(mutation=mutation), self.assertRaises(RuError):
                self.sync(locked=True)
            self.assertEqual(self.lock_bytes(), encoded)


class AdditionalLockSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app, self.cache = self.root / 'app', self.root / 'cache'
        manifest(self.app, dependencies="典: '甲' 对 典: 'Git' 对 'https://example.test/repo'. '引用' 对 'main'. 成. 成")
        fixture = self.root / 'fixture'
        manifest(fixture, name='远包', dependencies="典: '内包' 对 典: '路径' 对 'nested'. 成. 成")
        manifest(fixture / 'nested', name='嵌套')
        self.data = tar_bytes([(path.relative_to(fixture).as_posix(), path.read_bytes())
                               for path in fixture.rglob('*') if path.is_file()])
        self.fetch_calls = []
        def fetch(descriptor, staging):
            self.fetch_calls.append(dict(descriptor))
            safe_extract_archive(self.data, staging)
            return 'a' * 40
        self.fetch_patch = patch('rulang.package_sources._fetch_git', side_effect=fetch)
        self.fetch_patch.start()
        self.addCleanup(self.fetch_patch.stop)
        self.lock = sync_dependencies(self.app, cache_dir=self.cache)
        self.before = (self.app / '集锁.json').read_bytes()

    def write(self, lock):
        data = json.dumps(lock, ensure_ascii=False).encode()
        (self.app / '集锁.json').write_bytes(data)
        return data

    def test_nested_remote_path_owner_is_bound_to_cache_anchor_after_relocation(self):
        remote = next(p for p in self.lock['packages'] if p['kind'] == 'git')
        nested = next(p for p in self.lock['packages'] if p['kind'] == 'path')
        self.assertEqual(self.lock['owners'][nested['owner']]['locator'],
                         {'kind': 'cache', 'cache_key': remote['cache_key'], 'path': 'nested'})
        new_app, new_cache = self.root / 'moved-app', self.root / 'new-cache'
        shutil.move(str(self.app), new_app)
        shutil.rmtree(self.cache)
        sync_dependencies(new_app, cache_dir=new_cache, locked=True)
        self.assertEqual((new_app / '集锁.json').read_bytes(), self.before)
        root = resolve_cached_dependency(load_manifest(new_app), '甲', load_manifest(new_app).dependencies['甲'], cache_dir=new_cache)
        self.assertEqual(load_manifest(root / 'nested').name, '嵌套')
        self.assertEqual(self.fetch_calls[-1]['引用'], 'a' * 40)

    def test_duplicate_edges_packages_or_forged_owner_fail_before_transport(self):
        mutations = []
        value = copy.deepcopy(self.lock); value['edges'].append(copy.deepcopy(value['edges'][0])); mutations.append(value)
        value = copy.deepcopy(self.lock); value['packages'].append(copy.deepcopy(value['packages'][0])); mutations.append(value)
        value = copy.deepcopy(self.lock); value['owners']['orphan'] = copy.deepcopy(value['owners']['root']); mutations.append(value)
        value = copy.deepcopy(self.lock); value['packages'][0]['owner'] = 'root'; mutations.append(value)
        for index, value in enumerate(mutations):
            before = self.write(value)
            with self.subTest(index=index), patch('rulang.package_sources._fetch_git', side_effect=AssertionError('transport')), self.assertRaises(RuError):
                sync_dependencies(self.app, cache_dir=self.cache, locked=True)
            self.assertEqual((self.app / '集锁.json').read_bytes(), before)

    def test_duplicate_json_owner_key_is_rejected_without_transport(self):
        malformed = b'{"format":2,"owners":{},"owners":{},"packages":[],"edges":[]}'
        (self.app / '集锁.json').write_bytes(malformed)
        with patch('rulang.package_sources._fetch_git', side_effect=AssertionError('transport')), self.assertRaisesRegex(RuError, '--update'):
            sync_dependencies(self.app, cache_dir=self.cache, locked=True)
        self.assertEqual((self.app / '集锁.json').read_bytes(), malformed)

    def test_wrong_locked_tree_does_not_replace_previously_valid_cache(self):
        record = next(p for p in self.lock['packages'] if p['kind'] == 'git')
        source = self.cache / record['cache_key'] / 'package/src/力学.ru'
        original = source.read_bytes()
        changed = copy.deepcopy(self.lock)
        next(p for p in changed['packages'] if p['kind'] == 'git')['tree_sha256'] = 'e' * 64
        before = self.write(changed)
        with self.assertRaises(RuError):
            sync_dependencies(self.app, cache_dir=self.cache, locked=True)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual((self.app / '集锁.json').read_bytes(), before)

    def test_wrong_locked_manifest_name_or_version_does_not_replace_good_cache(self):
        remote = next(p for p in self.lock['packages'] if p['kind'] == 'git')
        source = self.cache / remote['cache_key'] / 'package/src/力学.ru'
        original = source.read_bytes()
        for field, replacement in [('name', '别包'), ('version', '9.0.0')]:
            changed = copy.deepcopy(self.lock)
            next(p for p in changed['packages'] if p['kind'] == 'git')[field] = replacement
            before = self.write(changed)
            with self.subTest(field=field), self.assertRaises(RuError):
                sync_dependencies(self.app, cache_dir=self.cache, locked=True)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual((self.app / '集锁.json').read_bytes(), before)

    def test_fetch_returning_a_different_commit_is_rejected(self):
        shutil.rmtree(self.cache)
        def wrong(descriptor, staging):
            safe_extract_archive(self.data, staging)
            return 'b' * 40
        with patch('rulang.package_sources._fetch_git', side_effect=wrong), self.assertRaisesRegex(RuError, 'commit'):
            sync_dependencies(self.app, cache_dir=self.cache, locked=True)
        self.assertEqual((self.app / '集锁.json').read_bytes(), self.before)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_missing_source_version_fails_without_version_selection(self):
        # Missing Git artifacts are covered separately; this verifies a missing
        # exact registry version cannot select the newer available version.
        app = self.root / 'registry-app'
        manifest(app, dependencies="典: '甲' 对 典: '目录' 对 'https://example.test/registry'. '包' 对 '远包'. '版' 对 '>=1.0.0 <3.0.0'. 成. 成")
        outer = self
        class Initial:
            def versions(self, name): return ['1.0.0']
            def download(self, name, version): return outer.data, {'sha256': hashlib.sha256(outer.data).hexdigest()}
        cache = self.root / 'registry-cache'
        with patch('rulang.package_registry.RegistryClient', return_value=Initial()):
            sync_dependencies(app, cache_dir=cache)
        before = (app / '集锁.json').read_bytes()
        shutil.rmtree(cache)
        class Missing:
            def versions(self, name): raise AssertionError('must not reselect')
            def download(self, name, version):
                if version != '1.0.0': raise AssertionError('wrong version')
                raise RuError('版本已移除', category='包错误')
        with patch('rulang.package_registry.RegistryClient', return_value=Missing()), self.assertRaises(RuError):
            sync_dependencies(app, cache_dir=cache, locked=True)
        self.assertEqual((app / '集锁.json').read_bytes(), before)

    def test_remote_archive_absolute_path_is_rejected_even_if_target_exists(self):
        outside = self.root / 'outside'
        manifest(outside, name='外包')
        app = self.root / 'absolute-app'
        manifest(app, dependencies="典: '甲' 对 典: 'Git' 对 'https://example.test/other'. 成. 成")
        def fetch(descriptor, staging):
            manifest(staging, name='远包')
            path = staging / '集录.ru'
            path.write_text(json.dumps({'名': '远包', '版': '1.0.0', '依赖': {'外部': {'路径': str(outside)}}}, ensure_ascii=False) + '.', encoding='utf-8')
            return 'b' * 40
        with patch('rulang.package_sources._fetch_git', side_effect=fetch), self.assertRaisesRegex(RuError, '绝对路径'):
            sync_dependencies(app, cache_dir=self.root / 'absolute-cache')
        self.assertFalse((app / '集锁.json').exists())

    def test_path_sources_remain_mutable_but_changed_path_manifest_requires_update(self):
        local_app, local_lib = self.root / 'local-app', self.root / 'local-lib'
        manifest(local_app, dependencies="典: '甲' 对 典: '路径' 对 '../local-lib'. 成. 成")
        manifest(local_lib, name='本地')
        sync_dependencies(local_app, cache_dir=self.cache)
        before = (local_app / '集锁.json').read_bytes()
        (local_lib / 'src/力学.ru').write_text('值 取 9.', encoding='utf-8')
        sync_dependencies(local_app, cache_dir=self.cache, locked=True)
        self.assertEqual((local_app / '集锁.json').read_bytes(), before)
        manifest(local_lib, name='本地', version='2.0.0')
        with self.assertRaisesRegex(RuError, '--update'):
            sync_dependencies(local_app, cache_dir=self.cache, locked=True)
        self.assertEqual((local_app / '集锁.json').read_bytes(), before)

    def test_symlink_aliases_keep_one_real_path_owner(self):
        library, link, app = self.root / 'local', self.root / 'link', self.root / 'aliases'
        manifest(library, name='本地')
        try:
            link.symlink_to(library, target_is_directory=True)
        except OSError:
            self.skipTest('directory symlinks unavailable')
        manifest(app, dependencies="典: '甲' 对 典: '路径' 对 '../local'. 成. '乙' 对 典: '路径' 对 '../link'. 成. 成")
        lock = sync_dependencies(app, cache_dir=self.cache)
        self.assertEqual(len(lock['packages']), 1)
        self.assertEqual(len({edge['identity'] for edge in lock['edges']}), 1)
        sync_dependencies(app, cache_dir=self.cache, locked=True)

    def test_portability_is_independent_of_first_alias_and_propagates(self):
        library = self.root / 'portable-lib'
        manifest(library, name='本地', dependencies="典: '子' 对 典: '路径' 对 'child'. 成. 成")
        manifest(library / 'child', name='子包')
        results = []
        for index, dependencies in enumerate([
            {'A': {'路径': '../portable-lib'}, 'Z': {'路径': str(library)}},
            {'A': {'路径': str(library)}, 'Z': {'路径': '../portable-lib'}}]):
            app = self.root / ('portable-app-' + str(index))
            manifest(app)
            (app / '集录.ru').write_text(json.dumps({'名': '工程', '版': '1.0.0', '依赖': dependencies}, ensure_ascii=False) + '.', encoding='utf-8')
            lock = sync_dependencies(app, cache_dir=self.cache)
            results.append({p['name']: p['portable'] for p in lock['packages'] if p['kind'] == 'path'})
            self.assertEqual(results[-1], {'本地': False, '子包': False})
            child = next(p for p in lock['packages'] if p['name'] == '子包')
            child['portable'] = True
            (app / '集锁.json').write_text(json.dumps(lock, ensure_ascii=False), encoding='utf-8')
            with self.assertRaises(RuError):
                sync_dependencies(app, cache_dir=self.cache, locked=True)
        self.assertEqual(results[0], results[1])

    def test_publisher_rejects_absolute_dependency_even_inside_package(self):
        from rulang.package_registry import publish_local, _validate_bundled_dependencies
        package = self.root / 'publish-absolute'
        manifest(package, name='发布')
        nested = package / 'src/nested'
        manifest(nested, name='内包')
        (package / '集录.ru').write_text(json.dumps({'名': '发布', '版': '1.0.0',
            '依赖': {'内': {'路径': str(nested)}}}, ensure_ascii=False) + '.', encoding='utf-8')
        with self.assertRaisesRegex(RuError, '绝对路径'):
            _validate_bundled_dependencies(load_manifest(package), package)
        with self.assertRaisesRegex(RuError, '绝对路径'):
            publish_local(package, self.root / 'registry-absolute')
        self.assertFalse((self.root / 'registry-absolute').exists())

    def test_cli_modes_are_explicit_and_restore_does_not_claim_lock_write(self):
        import subprocess
        import sys
        env = dict(os.environ, RU_PACKAGE_CACHE=str(self.cache))
        command = [sys.executable, '-m', 'rulang', 'deps', 'sync', str(self.app)]
        process = subprocess.run(command + ['--locked'], capture_output=True, text=True, env=env)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertNotIn('已写入', process.stdout)
        self.assertEqual((self.app / '集锁.json').read_bytes(), self.before)
        process = subprocess.run(command + ['--locked', '--update'], capture_output=True, text=True, env=env)
        self.assertEqual(process.returncode, 2)


class GitLockedRestoreTests(unittest.TestCase):
    def test_branch_movement_does_not_replace_locked_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, cache = root / 'app', root / 'cache'
            manifest(app, dependencies="典: '别名' 对 典: 'Git' 对 'https://example.test/repo'. '引用' 对 'main'. '子目录' 对 'pkg'. 成. 成")
            manifest(root / 'lib', name='库')
            data = tar_bytes([(path.relative_to(root / 'lib').as_posix(), path.read_bytes()) for path in (root / 'lib').rglob('*') if path.is_file()])
            calls = []
            def fetch(descriptor, staging):
                calls.append(dict(descriptor))
                safe_extract_archive(data, staging)
                return descriptor['引用'] if len(descriptor['引用']) == 40 else 'a' * 40
            with patch('rulang.package_sources._fetch_git', side_effect=fetch):
                lock = sync_dependencies(app, cache_dir=cache)
                before = (app / '集锁.json').read_bytes()
                shutil.rmtree(cache)
                sync_dependencies(app, cache_dir=cache, locked=True)
            self.assertEqual(calls[-1]['引用'], 'a' * 40)
            self.assertEqual(calls[-1]['子目录'], 'pkg')
            self.assertEqual((app / '集锁.json').read_bytes(), before)
            self.assertEqual(lock['packages'][0]['commit'], 'a' * 40)

    def test_unavailable_pinned_commit_never_falls_back_to_branch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, cache = root / 'app', root / 'cache'
            manifest(app, dependencies="典: '别名' 对 典: 'Git' 对 'https://example.test/repo'. '引用' 对 'main'. 成. 成")
            def initial(descriptor, staging):
                manifest(staging, name='库')
                return 'a' * 40
            with patch('rulang.package_sources._fetch_git', side_effect=initial):
                sync_dependencies(app, cache_dir=cache)
            before = (app / '集锁.json').read_bytes()
            shutil.rmtree(cache)
            calls = []
            def fail(descriptor, staging):
                calls.append(descriptor['引用'])
                raise RuError('旧 commit 不可获取', category='包错误')
            with patch('rulang.package_sources._fetch_git', side_effect=fail), self.assertRaises(RuError):
                sync_dependencies(app, cache_dir=cache, locked=True)
            self.assertEqual(calls, ['a' * 40])
            self.assertEqual((app / '集锁.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
