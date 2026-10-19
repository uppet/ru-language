"""Offline contracts and safety checks for the static package registry."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock
from urllib.parse import quote

from rulang.frontend import RuError
from rulang.package_registry import (LocalRegistry, RegistryClient, client_for,
                                     publish_local)


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


class RegistryClientTests(unittest.TestCase):
    def setUp(self):
        self.base = "https://registry.example.test/root/"
        self.archive = b"fixture archive"
        self.record = {"archive": "archives/fixture.tar.gz",
                       "sha256": hashlib.sha256(self.archive).hexdigest(),
                       "requires": ">=0.21.0 <1.0.0", "dependencies": {}}
        self.package = {"format": 1, "name": "工程", "description": "基础力学",
                        "versions": {"1.2.0": copy.deepcopy(self.record),
                                     "1.10.0": copy.deepcopy(self.record)}}
        self.index = {"format": 1, "packages": [
            {"name": "工程", "description": "基础力学"},
            {"name": "别包", "description": "其他"}]}
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        if url == self.base + "index.json":
            return encoded(self.index)
        if url == self.base + "packages/" + quote("工程", safe="") + ".json":
            return encoded(self.package)
        if url == self.base + "archives/fixture.tar.gz":
            return self.archive
        raise OSError("fixture not found")

    def client(self):
        return RegistryClient(self.base.rstrip("/"), fetcher=self.fetch)

    def test_contract_search_info_versions_dependencies_download(self):
        client = self.client()
        self.assertEqual(client.search("力学"), [self.index["packages"][0]])
        self.assertEqual(client.search("工程"), [self.index["packages"][0]])
        self.assertEqual(client.search("missing"), [])
        self.assertEqual(client.info("工程")["name"], "工程")
        self.assertEqual(client.versions("工程"), ["1.2.0", "1.10.0"])
        self.assertEqual(client.dependencies("工程", "1.10.0"), {})
        data, metadata = client.download("工程", "1.10.0")
        self.assertEqual(data, self.archive)
        self.assertEqual(metadata["sha256"], self.record["sha256"])
        self.assertIn("%E5%B7%A5%E7%A8%8B.json", "\n".join(self.calls))

    def test_fetcher_errors_become_package_errors(self):
        with self.assertRaises(RuError) as caught:
            self.client().info("不存在")
        self.assertEqual(caught.exception.category, "包错误")

    def test_mismatched_digest_rejected(self):
        self.archive = b"tampered"
        with self.assertRaisesRegex(RuError, "SHA-256|SHA256|摘要"):
            self.client().download("工程", "1.2.0")

    def test_unsafe_base_urls_rejected_before_fetch(self):
        for url in ["http://registry.test", "file:///tmp/registry", "https://a:b@registry.test", "https://registry.test/?token=secret", "https://registry.test/#frag"]:
            with self.subTest(url=url), self.assertRaises(RuError):
                RegistryClient(url, fetcher=self.fetch)
        self.assertEqual(self.calls, [])

    def test_invalid_names_never_reach_fetcher(self):
        for name in ["../escape", "a/b", "a%2fb", "a?token=x", "a#frag", "", "a b", "1name"]:
            with self.subTest(name=name), self.assertRaises(RuError):
                self.client().info(name)
        self.assertEqual(self.calls, [])

    def test_remote_identity_and_version_validated(self):
        self.package["name"] = "另名"
        with self.assertRaises(RuError):
            self.client().info("工程")
        self.package["name"] = "工程"
        self.package["versions"]["../bad"] = self.record
        with self.assertRaises(RuError):
            self.client().versions("工程")

    def test_bad_metadata_rejected(self):
        original = copy.deepcopy(self.package)
        for key, value in [("sha256", "wrong"), ("archive", "http://unsafe.test/a"),
                           ("archive", "../outside.tar.gz"), ("archive", "//other.test/a"),
                           ("archive", "archives/%2e%2e/outside.tar.gz"),
                           ("archive", "archives/a?token=x"),
                           ("dependencies", []), ("requires", "~1.0")]:
            self.package = copy.deepcopy(original)
            self.package["versions"]["1.2.0"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(RuError):
                self.client().download("工程", "1.2.0")

    def test_absolute_https_archive_supported(self):
        self.package["versions"]["1.2.0"]["archive"] = self.base + "archives/fixture.tar.gz"
        self.assertEqual(self.client().download("工程", "1.2.0")[0], self.archive)

    def test_duplicate_json_keys_rejected(self):
        client = RegistryClient(self.base, fetcher=lambda url: b'{"format":1,"format":1,"packages":[]}')
        with self.assertRaises(RuError):
            client.search("")

    def test_duplicate_field_diagnostic_does_not_echo_remote_key(self):
        client = RegistryClient(self.base, fetcher=lambda url: b'{"private-token":1,"private-token":2}')
        with self.assertRaises(RuError) as caught:
            client.search("")
        self.assertNotIn("private-token", str(caught.exception))

    def test_bad_index_rejected(self):
        for value in [{"format": 2, "packages": []},
                      {"format": True, "packages": []},
                      {"format": 1, "packages": [{"name": "../escape"}]},
                      {"format": 1, "packages": [{"name": "工程"}, {"name": "工程"}]}]:
            self.index = value
            with self.subTest(value=value), self.assertRaises(RuError):
                self.client().search("")

    def test_dependencies_are_validated_and_returned(self):
        deps = {"别名": {"目录": "https://other.example.test", "包": "别包", "版": ">=1.0.0 <2.0.0"}}
        self.package["versions"]["1.2.0"]["dependencies"] = deps
        self.assertEqual(self.client().dependencies("工程", "1.2.0"), deps)
        self.package["versions"]["1.2.0"]["dependencies"] = {"别名": {"路径": ".", "Git": "https://git.example.test/repo"}}
        with self.assertRaises(RuError):
            self.client().dependencies("工程", "1.2.0")

    def test_metadata_size_limit(self):
        client = RegistryClient(self.base, fetcher=lambda url: b" " * (2 * 1024 * 1024 + 1))
        with self.assertRaises(RuError):
            client.search("")

    def test_malformed_archive_url_has_package_diagnostic(self):
        for location in ["https://[broken", "//[broken", "archives/a#", "archives/a?", "archives/%252e%252e/x", "archives/a%2fb"]:
            self.package["versions"]["1.2.0"]["archive"] = location
            self.calls.clear()
            with self.subTest(location=location), self.assertRaises(RuError):
                self.client().download("工程", "1.2.0")
            self.assertEqual(len(self.calls), 1, "invalid archive location must not be fetched")

    def test_noncanonical_version_rejected(self):
        self.package["versions"]["01.0.0"] = self.record
        with self.assertRaises(RuError):
            self.client().versions("工程")

    def test_unknown_version_is_diagnostic(self):
        with self.assertRaises(RuError):
            self.client().dependencies("工程", "9.0.0")


class LocalRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "package"
        self.registry = self.root / "registry"
        self.package.mkdir()
        (self.package / "src").mkdir()
        self.manifest("1.0.0")
        (self.package / "src/力学.ru").write_text("吾 言 工程 其 力学.\n取 常数 为 3.\n", encoding="utf-8")

    def manifest(self, version):
        (self.package / "集录.ru").write_text(
            "典:\n'名' 对 '工程'.\n'版' 对 '" + version + "'.\n"
            "'需如言' 对 '>=0.21.0 <1.0.0'.\n'公开' 对 ['力学'].\n成.\n",
            encoding="utf-8")

    def test_publish_roundtrip_and_manifest_only_source_archive(self):
        (self.package / "README.md").write_text("not published")
        (self.package / "集锁.json").write_text("{}")
        (self.package / "secret.txt").write_text("not published")
        (self.package / "src/__pycache__").mkdir()
        (self.package / "src/__pycache__/hidden.ru").write_text("not published")
        record = publish_local(self.package, self.registry)
        self.assertEqual(record["name"], "工程")
        self.assertEqual(record["version"], "1.0.0")
        client = LocalRegistry(self.registry)
        self.assertEqual(client.versions("工程"), ["1.0.0"])
        self.assertEqual(client.search("工程")[0]["name"], "工程")
        data, meta = client.download("工程", "1.0.0")
        self.assertEqual(hashlib.sha256(data).hexdigest(), meta["sha256"])
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            self.assertEqual(archive.getnames(), ["集录.ru", "src/力学.ru"])
        self.assertIsInstance(client_for(str(self.registry)), LocalRegistry)
        self.assertIsInstance(client_for("https://registry.example.test"), RegistryClient)

    def test_versions_are_immutable(self):
        publish_local(self.package, self.registry)
        original = {str(p.relative_to(self.registry)): p.read_bytes()
                    for p in self.registry.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(RuError, "已存在|不可变"):
            publish_local(self.package, self.registry)
        current = {str(p.relative_to(self.registry)): p.read_bytes()
                   for p in self.registry.rglob("*") if p.is_file()}
        self.assertEqual(current, original)

    def test_new_version_keeps_old_archive(self):
        first = publish_local(self.package, self.registry)
        self.manifest("1.1.0")
        publish_local(self.package, self.registry)
        self.assertEqual(LocalRegistry(self.registry).versions("工程"), ["1.0.0", "1.1.0"])
        self.assertEqual(LocalRegistry(self.registry).download("工程", "1.0.0")[1]["sha256"], first["sha256"])

    def test_archive_bytes_are_deterministic(self):
        first = publish_local(self.package, self.registry)
        second = publish_local(self.package, self.root / "other-registry")
        self.assertEqual(first["sha256"], second["sha256"])

    def test_symlink_source_rejected(self):
        outside = self.root / "private.ru"
        outside.write_text("secret")
        (self.package / "src/secret.ru").symlink_to(outside)
        with self.assertRaises(RuError):
            publish_local(self.package, self.registry)
        self.assertFalse(self.registry.exists())

    def test_symlink_manifest_rejected(self):
        manifest = self.package / "集录.ru"
        moved = self.root / "elsewhere.ru"
        manifest.rename(moved)
        manifest.symlink_to(moved)
        with self.assertRaises(RuError):
            publish_local(self.package, self.registry)

    def test_corrupt_manifest_cannot_publish(self):
        (self.package / "集录.ru").write_text("显 123.\n", encoding="utf-8")
        with self.assertRaises(RuError):
            publish_local(self.package, self.registry)
        self.assertFalse(self.registry.exists())

    def test_local_archive_symlink_escape_rejected(self):
        record = publish_local(self.package, self.registry)
        archive = self.registry / record["archive"]
        outside = self.root / "outside.tar.gz"
        archive.rename(outside)
        archive.symlink_to(outside)
        with self.assertRaises(RuError):
            LocalRegistry(self.registry).download("工程", "1.0.0")

    def test_publish_failure_rolls_back_metadata(self):
        publish_local(self.package, self.registry)
        original = {str(p.relative_to(self.registry)): p.read_bytes()
                    for p in self.registry.rglob("*") if p.is_file()}
        self.manifest("1.1.0")
        import rulang.package_registry as module
        real_replace = module.os.replace
        def fail_index(source, target):
            if Path(target).name == "index.json":
                raise OSError("injected metadata failure")
            return real_replace(source, target)
        with mock.patch.object(module.os, "replace", side_effect=fail_index):
            with self.assertRaises(RuError):
                publish_local(self.package, self.registry)
        current = {str(p.relative_to(self.registry)): p.read_bytes()
                   for p in self.registry.rglob("*") if p.is_file()}
        self.assertEqual(current, original)

    def test_inbound_source_root_symlink_rejected(self):
        (self.package / "src").rename(self.package / "real")
        (self.package / "src").symlink_to("real", target_is_directory=True)
        with self.assertRaises(RuError):
            publish_local(self.package, self.registry)

    def test_missing_public_source_rejected(self):
        (self.package / "src/力学.ru").unlink()
        with self.assertRaises(RuError):
            publish_local(self.package, self.registry)
        self.assertFalse(self.registry.exists())

    def test_writer_lock_does_not_delete_existing_registry(self):
        self.registry.mkdir()
        (self.registry / ".publish-lock").mkdir()
        sentinel = self.registry / "keep.txt"
        sentinel.write_text("retained")
        with self.assertRaises(RuError):
            publish_local(self.package, self.registry)
        self.assertEqual(sentinel.read_text(), "retained")
        self.assertTrue((self.registry / ".publish-lock").is_dir())

    def test_symlink_metadata_directory_rejected_before_writes(self):
        self.registry.mkdir()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (self.registry / "packages").symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(RuError):
            publish_local(self.package, self.registry)
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertFalse((self.registry / "archives").exists())

    def test_local_registry_never_fetches_absolute_archive_url(self):
        record = publish_local(self.package, self.registry)
        metadata_path = self.registry / "packages/工程.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["versions"][record["version"]]["archive"] = "https://example.test/file.tar.gz"
        metadata_path.write_bytes(encoded(metadata))
        with mock.patch("rulang.package_sources.download_bytes", side_effect=AssertionError("network used")):
            with self.assertRaises(RuError):
                LocalRegistry(self.registry).download("工程", "1.0.0")

    def dependency_manifest(self, path, name, dependencies):
        path.parent.mkdir(parents=True, exist_ok=True)
        entries = []
        for alias, relative in dependencies.items():
            entries.append("'" + alias + "' 对 典: '路径' 对 '" + relative + "'. 成.")
        text = ("典: '名' 对 '" + name + "'. '版' 对 '1.0.0'. "
                "'依赖' 对 典: " + " ".join(entries) + " 成. 成.")
        path.write_text(text, encoding="utf-8")

    def test_external_path_dependency_cannot_publish(self):
        self.dependency_manifest(self.root / "external/集录.ru", "外部", {})
        self.dependency_manifest(self.package / "集录.ru", "工程", {"外部": "../external"})
        with self.assertRaises(RuError):
            publish_local(self.package, self.registry)
        self.assertFalse(self.registry.exists())

    def test_missing_bundled_path_dependency_cannot_publish(self):
        self.dependency_manifest(self.package / "集录.ru", "工程", {"缺失": "src/missing"})
        with self.assertRaises(RuError):
            publish_local(self.package, self.registry)
        self.assertFalse(self.registry.exists())

    def test_valid_bundled_path_dependencies_publish_without_network(self):
        self.dependency_manifest(self.package / "集录.ru", "工程", {"内层": "src/inner"})
        self.dependency_manifest(self.package / "src/inner/集录.ru", "内层包", {"更深": "../deep"})
        self.dependency_manifest(self.package / "src/deep/集录.ru", "深层包", {})
        with mock.patch("rulang.package_sources.sync_dependencies", side_effect=AssertionError("sync used")), mock.patch("rulang.package_sources.download_bytes", side_effect=AssertionError("network used")):
            publish_local(self.package, self.registry)
        data, _ = LocalRegistry(self.registry).download("工程", "1.0.0")
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            self.assertIn("src/inner/集录.ru", archive.getnames())
            self.assertIn("src/deep/集录.ru", archive.getnames())

    def test_nested_path_dependency_escape_cannot_publish(self):
        self.dependency_manifest(self.package / "集录.ru", "工程", {"内层": "src/inner"})
        self.dependency_manifest(self.package / "src/inner/集录.ru", "内层包", {"外部": "../../../external"})
        self.dependency_manifest(self.root / "external/集录.ru", "外部包", {})
        with self.assertRaises(RuError):
            publish_local(self.package, self.registry)
        self.assertFalse(self.registry.exists())

    def test_cyclic_bundled_path_dependencies_cannot_publish(self):
        self.dependency_manifest(self.package / "集录.ru", "工程", {"内层": "src/inner"})
        self.dependency_manifest(self.package / "src/inner/集录.ru", "内层包", {"外层": "../.."})
        with self.assertRaisesRegex(RuError, "循环"):
            publish_local(self.package, self.registry)
        self.assertFalse(self.registry.exists())

    def test_invalid_bundled_manifest_cannot_publish(self):
        self.dependency_manifest(self.package / "集录.ru", "工程", {"内层": "src/inner"})
        path = self.package / "src/inner/集录.ru"
        path.parent.mkdir(parents=True)
        path.write_text("显 123.", encoding="utf-8")
        with self.assertRaises(RuError):
            publish_local(self.package, self.registry)
        self.assertFalse(self.registry.exists())

    def test_network_publish_destination_rejected(self):
        with self.assertRaises(RuError):
            publish_local(self.package, "https://registry.example.test")


if __name__ == "__main__":
    unittest.main()
