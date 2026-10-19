"""Read-only static registry protocol and an explicitly local publisher.

No upload, authentication, hooks, or network-write functionality exists here.
"""
from contextlib import contextmanager
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tarfile
import tempfile
from urllib.parse import quote, unquote, urljoin, urlsplit

from .frontend import KEYWORDS

_METADATA_LIMIT = 2 * 1024 * 1024
_ARCHIVE_LIMIT = 32 * 1024 * 1024
_SOURCE_LIMIT = 64 * 1024 * 1024
_ENTRY_LIMIT = 10000
_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z", re.ASCII)
_EXCLUDED = {".git", ".hg", ".svn", ".ru", ".ru-cache", ".cache",
             "__pycache__", "node_modules", ".venv", "venv"}


def _error(message):
    # Keep imports lazy: explicit dependency sync itself uses this client.
    from .package_sources import _error as package_error
    return package_error(message)


def _name(value):
    if (not isinstance(value, str) or not value or len(value) > 200
            or not (value[0] == "_" or value[0].isalpha())
            or not all(c == "_" or c.isalnum() for c in value)
            or value in KEYWORDS or value in ("如见", "如观", "如竞")):
        raise _error("目录包名必须是合法的单一标识符")
    return value


def _version(value):
    if not isinstance(value, str) or len(value) > 80 or not _VERSION.fullmatch(value):
        raise _error("目录版本必须是三段数字版本")
    return value


def _https(value):
    from .package_sources import validate_https_url
    return validate_https_url(value)


def _url_parts(value):
    try:
        return urlsplit(value)
    except ValueError as exc:
        raise _error("目录地址格式无效") from exc


def _has_scheme(value):
    if os.name == "nt" and re.match(r"^[A-Za-z]:[\\/]", value):
        return False
    return bool(_url_parts(value).scheme)


def _relative(value):
    """Validate a URL-relative path before joining or decoding a local path."""
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise _error("目录文件路径无效")
    parts = _url_parts(value)
    decoded = unquote(value)
    if (parts.scheme or parts.netloc or parts.query or parts.fragment
            or "?" in value or "#" in value
            or value.startswith("/") or "\\" in value or "\\" in decoded
            or re.search(r"%2f|%5c", value, re.IGNORECASE)
            or "%" in decoded or any(ord(c) < 32 or ord(c) == 127 for c in decoded)
            or any(p in ("", ".", "..") for p in decoded.split("/"))
            or decoded.startswith("/") or ":" in decoded):
        raise _error("目录文件路径不得包含绝对路径、穿越或查询参数")
    return value


def _archive_location(value):
    if isinstance(value, str) and _url_parts(value).scheme:
        return _https(value)
    return _relative(value)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _error("目录 JSON 含重复字段")
        result[key] = value
    return result


def _decode(data):
    if not isinstance(data, bytes) or len(data) > _METADATA_LIMIT:
        raise _error("目录元数据过大或不是字节数据")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise _error("目录 JSON 无效") from exc
    if not isinstance(value, dict) or type(value.get("format")) is not int or value["format"] != 1:
        raise _error("不支持的目录元数据格式；需 format: 1")
    return value


def _validate_dependencies(value):
    from .package_sources import validate_dependency
    if not isinstance(value, dict) or len(value) > _ENTRY_LIMIT:
        raise _error("目录依赖必须是别名到来源的典")
    for alias, descriptor in value.items():
        _name(alias)
        validate_dependency(descriptor)
    return value


def _record(value):
    from .package_sources import validate_constraint
    if not isinstance(value, dict):
        raise _error("目录版本记录必须是典")
    digest = value.get("sha256")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise _error("目录版本缺少有效 SHA-256 摘要")
    result = copy.deepcopy(value)
    result["sha256"] = digest.lower()
    result["archive"] = _archive_location(value.get("archive"))
    result["dependencies"] = _validate_dependencies(value.get("dependencies", {}))
    requires = value.get("requires", "")
    if not isinstance(requires, str):
        raise _error("目录需如言约束必须是字符串")
    if requires:
        validate_constraint(requires)
    result["requires"] = requires
    return result


def _index(value):
    entries = value.get("packages")
    if not isinstance(entries, list) or len(entries) > _ENTRY_LIMIT:
        raise _error("目录索引 packages 必须是包列表")
    seen = set()
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise _error("目录索引包条目必须是典")
        name = _name(entry.get("name"))
        description = entry.get("description", "")
        if not isinstance(description, str) or name in seen:
            raise _error("目录索引介绍无效或包含重复包名")
        seen.add(name)
        result.append({"name": name, "description": description})
    return result


def _package(value, expected):
    if _name(value.get("name")) != expected:
        raise _error("目录返回的包名与请求不符")
    versions = value.get("versions")
    if not isinstance(versions, dict) or len(versions) > _ENTRY_LIMIT:
        raise _error("目录 versions 必须是版本到元数据的典")
    if not isinstance(value.get("description", ""), str):
        raise _error("目录包介绍必须是字符串")
    result = copy.deepcopy(value)
    result["versions"] = {_version(v): _record(record) for v, record in versions.items()}
    return result


class RegistryClient:
    """HTTPS static reader. Tests can inject a fetcher(url) -> bytes."""

    def __init__(self, base_url, *, fetcher=None):
        self.base_url = _https(base_url).rstrip("/") + "/"
        self.fetcher = fetcher

    def _read(self, path, *, limit=_METADATA_LIMIT):
        target = _archive_location(path)
        url = _https(target if _url_parts(target).scheme else urljoin(self.base_url, target))
        try:
            if self.fetcher is None:
                from .package_sources import download_bytes
                data = download_bytes(url, limit=limit)
            else:
                data = self.fetcher(url)
        except (OSError, ValueError) as exc:
            raise _error("无法读取目录文件") from exc
        if not isinstance(data, bytes) or len(data) > limit:
            raise _error("目录下载超过大小限制或内容类型无效")
        return data

    def search(self, query=""):
        if not isinstance(query, str):
            raise _error("搜索词必须是字符串")
        entries = _index(_decode(self._read("index.json")))
        needle = query.casefold()
        return [entry for entry in entries
                if needle in entry["name"].casefold() or needle in entry["description"].casefold()]

    def info(self, name):
        name = _name(name)
        return _package(_decode(self._read("packages/" + quote(name, safe="") + ".json")), name)

    def versions(self, name):
        return sorted(self.info(name)["versions"], key=lambda v: tuple(map(int, v.split("."))))

    def _version_record(self, name, version):
        _version(version)
        records = self.info(name)["versions"]
        if version not in records:
            raise _error(f"目录中不存在 {name} 的版本 {version}")
        return dict(records[version], name=name, version=version)

    def dependencies(self, name, version):
        return self._version_record(name, version)["dependencies"]

    def download(self, name, version):
        record = self._version_record(name, version)
        data = self._read(record["archive"], limit=_ARCHIVE_LIMIT)
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise _error(f"包 {name} {version} 下载的 SHA-256 摘要不符")
        return data, record


class LocalRegistry(RegistryClient):
    """The same protocol read from a local directory, never the network."""

    def __init__(self, root):
        path = Path(root).expanduser()
        if path.is_symlink():
            raise _error("本地目录根不得是符号链接")
        self.root = path.resolve()

    def _read(self, path, *, limit=_METADATA_LIMIT):
        # Local fixtures may not turn reads into network requests.
        _relative(path)
        target = self.root.joinpath(*unquote(path).split("/"))
        current = self.root
        for segment in target.relative_to(self.root).parts:
            current = current / segment
            if current.is_symlink():
                raise _error("本地目录文件不得是符号链接")
        if not target.resolve().is_relative_to(self.root):
            raise _error("本地目录文件越过目录边界")
        try:
            with target.open("rb") as handle:
                data = handle.read(limit + 1)
        except OSError as exc:
            raise _error("无法读取本地目录文件") from exc
        if len(data) > limit:
            raise _error("本地目录文件超过大小限制")
        return data


def client_for(source):
    """Select an HTTPS reader or local reader without protocol fallback."""
    if isinstance(source, os.PathLike):
        return LocalRegistry(source)
    if not isinstance(source, str) or not source:
        raise _error("目录来源必须是本地路径或 HTTPS 地址")
    if _has_scheme(source):
        return RegistryClient(source)
    return LocalRegistry(source)


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".publish-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _writer_lock(root):
    lock = root / ".publish-lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise _error("本地目录正在发布；若上次进程中断，请先核查并移除 .publish-lock") from exc
    try:
        yield
    finally:
        lock.rmdir()


def _validate_bundled_dependencies(manifest, boundary):
    """Validate path-only dependency edges entirely inside extracted bytes."""
    from .packages import load_manifest
    from .package_sources import MAX_PACKAGES, _native_path
    boundary = Path(boundary).resolve()
    visited, active = set(), set()

    def visit(owner):
        identity = Path(owner.path).resolve()
        if identity in active:
            raise _error("发布包内的路径依赖存在循环")
        if identity in visited:
            return
        if len(visited) + len(active) >= MAX_PACKAGES:
            raise _error("发布包内的路径依赖数量超过限制")
        active.add(identity)
        for path in owner.public.values():
            path = Path(path).resolve()
            if not path.is_relative_to(boundary) or not path.is_file():
                raise _error("归档内依赖的公开入口缺失或越过归档边界")
        for descriptor in owner.dependencies.values():
            if "路径" not in descriptor:
                continue
            if _native_path(descriptor["路径"]).is_absolute():
                raise _error("发布归档不能包含绝对路径依赖")
            target = (Path(owner.root) / descriptor["路径"]).resolve()
            if not target.is_relative_to(boundary):
                raise _error("发布包的路径依赖不能越过归档边界")
            child = load_manifest(target)
            if not Path(child.root).resolve().is_relative_to(boundary):
                raise _error("发布包的路径依赖不能越过归档边界")
            visit(child)
        active.remove(identity)
        visited.add(identity)

    visit(manifest)


def _archive_package(package_dir):
    from .packages import load_manifest
    from .package_sources import safe_extract_archive
    directory = Path(package_dir).expanduser()
    if directory.is_symlink() or (directory / "集录.ru").is_symlink():
        raise _error("待发布包及清单不得是符号链接")
    manifest = load_manifest(directory)
    root = Path(manifest.root).resolve()
    # Manifest resolution canonicalizes paths. Inspect the lexical package tree
    # too, so an in-bound symlink used as the declared source root cannot hide.
    for parent, directories, names in os.walk(root, followlinks=False):
        for name in directories + names:
            if (Path(parent) / name).is_symlink():
                raise _error("待发布包不得包含符号链接")
        directories[:] = [name for name in directories if name not in _EXCLUDED]
    source_root = Path(manifest.source_root)
    if not source_root.is_absolute():
        source_root = root / source_root
    # Test lexical paths before resolving to avoid hiding source-root links.
    if not source_root.is_relative_to(root):
        raise _error("源码根越过包边界")
    current = root
    for part in source_root.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise _error("源码根不得包含符号链接")
    if not source_root.is_dir():
        raise _error("源码根不存在或不是目录")
    files = [Path(manifest.path)]
    for parent, directories, names in os.walk(source_root, followlinks=False):
        directory = Path(parent)
        for name in directories + names:
            if (directory / name).is_symlink():
                raise _error("发布源码不得包含符号链接")
        directories[:] = sorted(name for name in directories if name not in _EXCLUDED)
        for name in sorted(names):
            path = directory / name
            if path.suffix == ".ru" and path != Path(manifest.path):
                files.append(path)
    if len(files) > _ENTRY_LIMIT:
        raise _error("发布包文件数超过限制")
    files = files[:1] + sorted(files[1:], key=lambda p: p.relative_to(root).as_posix())
    included = {p.resolve() for p in files}
    for public_file in manifest.public.values():
        path = Path(public_file)
        if not path.is_absolute():
            path = root / path
        if path.resolve() not in included:
            raise _error("公开入口不在发布源码中")
    output = io.BytesIO()
    total = 0
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for path in files:
                if not path.is_file() or path.is_symlink():
                    raise _error("发布内容必须是普通文件")
                with path.open("rb") as handle:
                    data = handle.read(_SOURCE_LIMIT - total + 1)
                total += len(data)
                if total > _SOURCE_LIMIT:
                    raise _error("发布源码超过大小限制")
                entry = tarfile.TarInfo(path.relative_to(root).as_posix())
                entry.size, entry.mode, entry.mtime = len(data), 0o644, 0
                archive.addfile(entry, io.BytesIO(data))
    data = output.getvalue()
    if len(data) > _ARCHIVE_LIMIT:
        raise _error("发布归档超过大小限制")
    with tempfile.TemporaryDirectory(prefix="ru-publish-check-") as temporary:
        safe_extract_archive(data, Path(temporary))
        checked = load_manifest(Path(temporary))
        if (checked.name, checked.version) != (manifest.name, manifest.version):
            raise _error("归档清单与待发布包不符")
        _validate_bundled_dependencies(checked, Path(temporary))
    return manifest, data


def publish_local(package_dir, registry_dir):
    """Validate then publish locally; a version can never be overwritten.

    Individual files replace atomically. Archives precede metadata, and the
    search index commits last. A failure rolls back writes under a writer lock.
    """
    if isinstance(registry_dir, str) and _has_scheme(registry_dir):
        raise _error("发布仅支持本地目录，不支持网络发布")
    path = Path(registry_dir).expanduser()
    if path.is_symlink():
        raise _error("发布目录不得是符号链接")
    root = path.resolve()
    try:
        manifest, archive = _archive_package(package_dir)
        _name(manifest.name)
        _version(manifest.version)
        digest = hashlib.sha256(archive).hexdigest()
        record = _record({"archive": "archives/" + digest + ".tar.gz", "sha256": digest,
                          "dependencies": manifest.dependencies, "requires": manifest.requires or ""})
        root.mkdir(parents=True, exist_ok=True)
        with _writer_lock(root):
            client = LocalRegistry(root)
            index_path = root / "index.json"
            index = _index(_decode(client._read("index.json"))) if index_path.exists() else []
            package_path = root / "packages" / (manifest.name + ".json")
            if package_path.exists():
                package = client.info(manifest.name)
            else:
                package = {"format": 1, "name": manifest.name, "description": "", "versions": {}}
            if manifest.version in package["versions"]:
                raise _error(f"版本 {manifest.name} {manifest.version} 已存在；版本不可变")
            package["versions"][manifest.version] = record
            if not any(item["name"] == manifest.name for item in index):
                index.append({"name": manifest.name, "description": package.get("description", "")})
            index.sort(key=lambda item: item["name"])
            updates = [(root / record["archive"], archive),
                       (package_path, _json_bytes(package)),
                       (index_path, _json_bytes({"format": 1, "packages": index}))]
            # Validate all destination parents before any write.
            for target, _ in updates:
                current = root
                for part in target.relative_to(root).parts:
                    current = current / part
                    if current.is_symlink():
                        raise _error("发布目录内不得包含符号链接")
            completed = []
            try:
                for target, data in updates:
                    old = None
                    if target.exists():
                        limit = _ARCHIVE_LIMIT if target == updates[0][0] else _METADATA_LIMIT
                        with target.open("rb") as handle:
                            old = handle.read(limit + 1)
                        if len(old) > limit:
                            raise _error("已有目录文件超过大小限制")
                    if target == updates[0][0] and old is not None:
                        if old != data:
                            raise _error("目录已有同摘要但不同内容的归档")
                        continue
                    _atomic_write(target, data)
                    completed.append((target, old))
            except BaseException:
                for target, old in reversed(completed):
                    if old is None:
                        target.unlink(missing_ok=True)
                    else:
                        _atomic_write(target, old)
                raise
        return dict(record, name=manifest.name, version=manifest.version)
    except OSError as exc:
        raise _error("本地发布失败：" + str(exc)) from exc
