"""Explicit, bounded dependency acquisition; ordinary imports are strictly offline.

Only ``sync_dependencies`` performs network I/O. The lock records a complete
single-version graph; immutable cache trees are content-checked before imports.
"""
from __future__ import annotations

import bz2
import gzip
import hashlib
import lzma
import io
import json
import os
import posixpath
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import signal
import stat
import subprocess
import tarfile
import tempfile
import time
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile

from .frontend import RuError

LOCK_NAME = '集锁.json'
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_UNPACKED_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_ENTRIES = 4096
MAX_ARCHIVE_DEPTH = 64
TREE_HASH_ALGORITHM = 'relative-posix-v1'
MAX_PACKAGES = 256
MAX_GIT_BYTES = 128 * 1024 * 1024
VERSION = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'


def _error(message, manifest=None):
    error = RuError(message, category='包错误')
    # A manifest can contain a rejected credential-bearing URL. Never echo its
    # raw source or transport diagnostics, including in CLI error handling.
    error.suppress_source = True
    if manifest is not None:
        error.source_name = str(getattr(manifest, 'path', manifest))
    return error


def _version(value):
    if not isinstance(value, str) or len(value) > 80 or not re.fullmatch(VERSION, value):
        raise _error('版本须为无前导零的三段整数，例如 1.2.3')
    return tuple(int(part) for part in value.split('.'))


def validate_constraint(constraint):
    if not isinstance(constraint, str) or not constraint.strip() or len(constraint) > 4096:
        raise _error('版本约束不能为空')
    if re.fullmatch(VERSION, constraint):
        _version(constraint)
        return
    for part in constraint.split():
        if len(part) > 82 or not re.fullmatch(r'(?:>=|<=|>|<|=)' + VERSION, part):
            raise _error('版本约束仅支持三段 exact 或空格分隔比较区间，例如 >=1.0.0 <2.0.0')


def version_satisfies(version, constraint):
    value = _version(version)
    validate_constraint(constraint)
    if re.fullmatch(VERSION, constraint):
        return value == _version(constraint)
    for part in constraint.split():
        match = re.fullmatch(r'(>=|<=|>|<|=)(' + VERSION + ')', part)
        other = _version(match[2])
        if not {'>=': value >= other, '<=': value <= other, '>': value > other,
                '<': value < other, '=': value == other}[match[1]]:
            return False
    return True


def validate_https_url(url):
    if not isinstance(url, str) or any(ord(char) < 33 for char in url) or '\\' in url or '?' in url or '#' in url:
        raise _error('远程来源须为有效 HTTPS URL，不能含凭据、查询参数或片段')
    try:
        parts = urlsplit(url)
        port = parts.port
        if (parts.scheme != 'https' or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.query or parts.fragment):
            raise ValueError()
        host = parts.hostname.lower()
        # Reject alternate spellings whose transport normalization could split
        # one source into several graph identities. Non-ASCII UTF-8 escapes
        # remain supported for registry package names, then canonicalized.
        if '%' in host or re.search(r'%(?![0-9A-Fa-f]{2})', parts.path):
            raise ValueError()
        if any(int(code, 16) < 128 for code in re.findall(r'%([0-9A-Fa-f]{2})', parts.path)):
            raise ValueError()
        decoded = unquote(parts.path, encoding='utf-8', errors='strict')
        if (any(part in ('.', '..') for part in decoded.split('/')) or '//' in decoded
                or any(ord(char) < 33 for char in decoded) or any(char in decoded for char in '\\%?#')):
            raise ValueError()
        path = quote(decoded, safe="/-._~!$&'()*+,;=:@").rstrip('/')
        if ':' in host:
            host = '[' + host + ']'
        if port is not None and port != 443:
            host += ':' + str(port)
        return urlunsplit(('https', host, path, '', ''))
    except (TypeError, ValueError, UnicodeError):
        raise _error('远程来源须为有效 HTTPS URL，不能含凭据、查询参数或片段') from None


def _git_url(url):
    if isinstance(url, str) and url.startswith('https://'):
        return validate_https_url(url)
    if not isinstance(url, str) or any(ord(c) < 33 for c in url) or '\\' in url:
        raise _error('Git 来源仅支持不含密码的 HTTPS 或 SSH')
    # Conventional scp-style SSH URLs are accepted; their user is an SSH login,
    # never a password or token. Arguments are never passed through a shell.
    if re.fullmatch(r'[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[A-Za-z0-9_./~-]+', url):
        user_host, path = url.split(':', 1)
        if '..' in path.split('/') or path.startswith('-') or user_host.startswith('-') or user_host.split('@', 1)[1].startswith('-'):
            raise _error('Git SSH 路径无效')
        return url
    try:
        parts = urlsplit(url)
        _ = parts.port
        if (parts.scheme != 'ssh' or not parts.hostname or parts.hostname.startswith('-') or parts.password is not None
                or parts.query or parts.fragment or not parts.path or parts.path.startswith('/-')
                or '%' in url or '//' in parts.path or any(part in ('.', '..') for part in parts.path.split('/'))
                or (parts.username is not None and (parts.username.startswith('-') or not re.fullmatch(r'[A-Za-z0-9._-]+', parts.username)))):
            raise ValueError()
        return url.rstrip('/')
    except ValueError:
        raise _error('Git 来源仅支持不含密码的 HTTPS 或 SSH') from None


def _git_identity(url):
    """Normalize transport spellings without guessing repository aliases."""
    url = _git_url(url)
    if url.startswith('https://'):
        return url
    if not url.startswith('ssh://'):
        user_host, path = url.split(':', 1)
        user, host = user_host.split('@', 1)
        # scp repository paths without a slash are relative to the login home;
        # ssh://host/path is absolute and must not be conflated with them.
        if path.startswith('~'):
            path = '/' + path
        elif not path.startswith('/'):
            path = '/~/' + path
        return 'ssh://' + user + '@' + host.lower() + posixpath.normpath(path).rstrip('/')
    parts = urlsplit(url)
    host = parts.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    if parts.username:
        host = parts.username + '@' + host
    if parts.port is not None and parts.port != 22:
        host += ':' + str(parts.port)
    return 'ssh://' + host + posixpath.normpath(parts.path).rstrip('/')


def _subdir(value):
    if value in ('', '.'):
        return ''
    if (not isinstance(value, str) or '\\' in value or ':' in value or value.startswith('/')
            or any(part in ('', '.', '..') for part in value.split('/'))
            or any(ord(c) < 32 for c in value)):
        raise _error('Git 子目录必须为仓库内的相对路径')
    return value


def _native_path(value):
    """Do not reinterpret another operating system's absolute path as relative."""
    if not isinstance(value, str) or not value or '\0' in value:
        raise _error('路径依赖须为有效本机路径')
    path = Path(value)
    if os.name != 'nt' and (re.match(r'^[A-Za-z]:', value) or value.startswith('\\\\')):
        raise _error('Windows 盘符或 UNC 路径不能在此平台作为相对路径使用')
    if os.name == 'nt' and (path.drive or path.root) and not path.is_absolute():
        raise _error('Windows 路径须为明确绝对路径或相对包含它的集录.ru')
    return path


def validate_dependency(descriptor):
    if not isinstance(descriptor, dict) or not descriptor:
        raise _error('依赖须为单一来源描述典')
    sources = set(descriptor) & {'路径', 'Git', '目录'}
    if len(sources) != 1:
        raise _error('每项依赖必须且只能选择 路径、Git、目录 之一')
    source = next(iter(sources))
    allowed = {'路径': {'路径'}, 'Git': {'Git', '引用', '子目录'}, '目录': {'目录', '包', '版'}}[source]
    if set(descriptor) - allowed or not all(isinstance(value, str) and value for value in descriptor.values()):
        raise _error('依赖来源字段未知或不是非空字符串')
    if source == '路径':
        _native_path(descriptor[source])
    elif source == 'Git':
        _git_url(descriptor[source])
        _subdir(descriptor.get('子目录', '.'))
        ref = descriptor.get('引用', 'HEAD')
        if (ref.startswith('-') or any(c.isspace() or ord(c) < 32 for c in ref)
                or any(c in ref for c in ('..', '~', '^', ':', '?', '*', '[', '\\', '@{'))):
            raise _error('Git 引用须为分支、标签或完整 commit，不能含修订表达式')
    else:
        if set(descriptor) != allowed:
            raise _error('目录依赖须同时指定 目录、包、版')
        validate_https_url(descriptor[source])
        if not descriptor['包'].isidentifier():
            raise _error('目录包名须为一个合法标识符')
        validate_constraint(descriptor['版'])


class _SecureRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        validate_https_url(newurl)
        return super().redirect_request(request, response, code, message, headers, newurl)


def download_bytes(url, limit=MAX_ARCHIVE_BYTES):
    url = validate_https_url(url)
    try:
        request = Request(url, headers={'User-Agent': 'ru-package/1', 'Accept-Encoding': 'identity'})
        with build_opener(_SecureRedirect()).open(request, timeout=30) as response:
            validate_https_url(response.url)
            length = response.headers.get('Content-Length')
            if length is not None and (not length.isdigit() or int(length) > limit):
                raise _error('下载内容超过允许大小')
            chunks, count = [], 0
            while True:
                chunk = response.read(min(65536, limit + 1 - count))
                if not chunk:
                    break
                count += len(chunk)
                if count > limit:
                    raise _error('下载内容超过允许大小')
                chunks.append(chunk)
            return b''.join(chunks)
    except RuError:
        raise
    except (OSError, ValueError):
        raise _error('HTTPS 下载失败；请检查来源、证书与网络，未写入锁文件') from None


def _archive_name(name):
    if (not isinstance(name, str) or name.startswith('/') or '\\' in name or ':' in name
            or any(ord(c) < 32 for c in name) or '..' in name.split('/')):
        raise _error('包归档含绝对路径或路径穿越')
    parts = tuple(part for part in name.split('/') if part not in ('', '.'))
    if not parts:
        return None
    if len(parts) > MAX_ARCHIVE_DEPTH:
        raise _error('包归档路径层级超过限制')
    # Windows strips trailing dots/spaces and has reserved device names.
    for part in parts:
        if part.endswith(('.', ' ')) or re.fullmatch(r'(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part):
            raise _error('包归档含不安全或不可移植文件名')
    return '/'.join(parts)


def safe_extract_archive(data, destination):
    """Extract only regular files/directories into a new, empty staging tree."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise _error('包归档超过下载大小限制')
    destination = Path(destination)
    if destination.is_symlink() or (destination.exists() and any(destination.iterdir())):
        raise _error('归档目标必须为空目录')
    existed, started, complete = destination.exists(), False, False
    # Each implicit directory is a node too; spelling is fixed at first use.
    children, nodes, total, count = {}, [], 0, 0

    def target(name, size, directory):
        nonlocal total, count, started
        count += 1
        if count > MAX_ENTRIES or size < 0 or size > MAX_FILE_BYTES:
            raise _error('包归档条目或单个文件超过限制')
        total += size
        if total > MAX_UNPACKED_BYTES:
            raise _error('包归档解压总量超过限制')
        name = _archive_name(name)
        if name is None:
            if not directory:
                raise _error('包归档文件名为空')
            return None
        parts, parent = name.split('/'), -1
        for index, part in enumerate(parts):
            key = (parent, part.casefold())
            node_id = children.get(key)
            final = index == len(parts) - 1
            if node_id is None:
                if len(nodes) >= MAX_ENTRIES:
                    raise _error('包归档含隐式目录在内的条目超过限制')
                node_id = len(nodes)
                children[key] = node_id
                nodes.append([part, 'directory' if final and directory else 'file' if final else None])
            else:
                spelling, kind = nodes[node_id]
                if spelling != part:
                    raise _error('包归档目录前缀或文件含大小写冲突')
                if final:
                    if directory and kind is None:
                        nodes[node_id][1] = 'directory'
                    else:
                        raise _error('包归档含重复覆盖或文件与目录冲突')
                elif kind == 'file':
                    raise _error('包归档文件与目录冲突')
            parent = node_id
        path = destination.joinpath(*parts)
        started = True
        if directory:
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def copy(stream, path, expected):
        if path is None:
            return
        with path.open('xb') as output:
            remaining = expected
            while remaining:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    raise _error('包归档条目被截断')
                output.write(chunk)
                remaining -= len(chunk)
            if stream.read(1):
                raise _error('包归档条目大小不一致')

    try:
        if zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if len(archive.infolist()) > MAX_ENTRIES:
                    raise _error('包归档条目超过限制')
                for item in archive.infolist():
                    mode = item.external_attr >> 16
                    kind = stat.S_IFMT(mode)
                    if item.flag_bits & 1 or kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                        raise _error('包归档不允许链接、特殊文件或加密条目')
                    path = target(item.filename, item.file_size, item.is_dir())
                    if not item.is_dir():
                        with archive.open(item) as stream:
                            copy(stream, path, item.file_size)
        else:
            # Bound decompressed tar headers as well as member bodies. PAX
            # records are consumed by tarfile before a member can be inspected.
            limit = MAX_UNPACKED_BYTES + MAX_ENTRIES * 4096 + 1024
            raw = io.BytesIO(data)
            if data.startswith(b'\x1f\x8b'):
                raw = gzip.GzipFile(fileobj=raw)
            elif data.startswith(b'BZh'):
                raw = bz2.BZ2File(raw)
            elif data.startswith(b'\xfd7zXZ\x00'):
                raw = lzma.LZMAFile(raw)
            unpacked = raw.read(limit + 1)
            if len(unpacked) > limit:
                raise _error('包归档解压总量超过限制')
            with tarfile.open(fileobj=io.BytesIO(unpacked), mode='r:') as archive:
                for item in archive:
                    if not (item.isfile() or item.isdir()) or item.issparse():
                        raise _error('包归档不允许链接、稀疏文件或特殊文件')
                    path = target(item.name, item.size, item.isdir())
                    if item.isfile():
                        with archive.extractfile(item) as stream:
                            copy(stream, path, item.size)
        destination.mkdir(parents=True, exist_ok=True)
        complete = True
    except RuError:
        raise
    except (tarfile.TarError, zipfile.BadZipFile, lzma.LZMAError, OSError, ValueError, RuntimeError, EOFError, NotImplementedError, OverflowError):
        raise _error('包归档无效或不安全') from None
    finally:
        if not complete and started and destination.is_dir():
            shutil.rmtree(destination)
            if existed:
                destination.mkdir()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def _read_json(path):
    try:
        with Path(path).open('rb') as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ValueError()
        def pairs(entries):
            result = {}
            for key, value in entries:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        result = json.loads(data, object_pairs_hook=pairs)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise _error('锁或缓存元数据无效；请运行 ru deps sync') from None


def _atomic_json(path, value):
    path = Path(path)
    if path.is_symlink():
        raise _error('拒绝覆盖符号链接锁文件')
    with tempfile.NamedTemporaryFile(prefix='.ru-lock-', dir=path.parent, delete=False) as output:
        temp = Path(output.name)
        try:
            output.write(_json_bytes(value))
            output.flush()
            os.fsync(output.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _tree_digests(root, algorithm):
    root = Path(root)
    files, payloads, total, entries = [], [], 0, 0
    for parent, directories, names in os.walk(root, followlinks=False):
        entries += len(directories) + len(names)
        if entries > MAX_ENTRIES:
            raise _error('包缓存超过安全条目限制')
        for name in directories + names:
            path = Path(parent) / name
            if path.is_symlink():
                raise _error('包缓存含符号链接；请运行 ru deps sync')
        for name in names:
            path = Path(parent) / name
            if not path.is_file():
                raise _error('包缓存含特殊文件；请运行 ru deps sync')
            files.append(path)
            if len(files) > MAX_ENTRIES:
                raise _error('包缓存超过安全条目限制')
    for path in files:
        with path.open('rb') as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        total += len(data)
        if len(data) > MAX_FILE_BYTES or total > MAX_UNPACKED_BYTES:
            raise _error('包缓存超过安全大小限制')
        payloads.append((path.relative_to(root).as_posix(), hashlib.sha256(data).digest()))
    # Untagged public 0.22 locks used native pathlib component ordering.
    # Read/validate bytes once, then compose exactly the two historical orders.
    keys = (PurePosixPath, PureWindowsPath) if algorithm is None else (str,)
    results = []
    for key in keys:
        digest = hashlib.sha256()
        for name, file_digest in sorted(payloads, key=lambda item: key(item[0])):
            digest.update(name.encode('utf-8') + b'\0' + file_digest + b'\0')
        results.append(digest.hexdigest())
    return results


def _tree_algorithm(record):
    if 'tree_hash_algorithm' not in record:
        return None
    if record['tree_hash_algorithm'] != TREE_HASH_ALGORITHM:
        raise _error('远程依赖锁的源码树摘要算法未知')
    return TREE_HASH_ALGORITHM


def _tree_hash(root):
    return _tree_digests(root, TREE_HASH_ALGORITHM)[0]


def _tree_matches(root, record):
    return record['tree_sha256'] in _tree_digests(root, _tree_algorithm(record))


def _cache_dir(cache_dir=None):
    return Path(cache_dir or os.environ.get('RU_PACKAGE_CACHE') or Path.home() / '.cache/ru/packages').expanduser().resolve()


def _git_command(args, cwd, *, output=None):
    # Ignore ambient Git config, credential helpers, executable filters, aliases,
    # hooks, URL rewrites and transport overrides. SSH uses existing agent/keys
    # with strict known-host checks; it never prompts or runs local commands.
    env = {key: value for key, value in os.environ.items() if key in (
        'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR', 'SSH_AUTH_SOCK',
        'HTTPS_PROXY', 'https_proxy', 'NO_PROXY', 'no_proxy', 'SSL_CERT_FILE', 'SSL_CERT_DIR')}
    env.update({'HOME': str(cwd), 'XDG_CONFIG_HOME': str(cwd), 'GIT_CONFIG_NOSYSTEM': '1',
                'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_TERMINAL_PROMPT': '0',
                'GIT_ALLOW_PROTOCOL': 'https:ssh', 'GIT_PROTOCOL_FROM_USER': '0',
                'GIT_SSH_COMMAND': 'ssh -F ' + os.devnull + ' -oBatchMode=yes -oPermitLocalCommand=no -oClearAllForwardings=yes -oProxyCommand=none -oStrictHostKeyChecking=yes'})
    command = ['git', '-c', 'core.hooksPath=' + str(Path(cwd) / 'empty-hooks'),
               '-c', 'protocol.file.allow=never', '-c', 'protocol.ext.allow=never',
               '-c', 'http.followRedirects=false'] + args
    try:
        with tempfile.TemporaryFile() as capture:
            destination = output if output is not None else capture
            with subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                  stdout=destination, stderr=subprocess.DEVNULL,
                                  start_new_session=os.name != 'nt') as process:
                try:
                    start = time.monotonic()
                    while process.poll() is None:
                        size, entries = 0, 0
                        for path in Path(cwd).rglob('*'):
                            entries += 1
                            if path.is_file():
                                size += path.stat().st_size
                            if entries > MAX_ENTRIES * 4 or size > MAX_GIT_BYTES:
                                break
                        if (time.monotonic() - start > 120 or size > MAX_GIT_BYTES
                                or entries > MAX_ENTRIES * 4 or destination.tell() > MAX_ARCHIVE_BYTES):
                            raise _error('Git 获取超过时间或大小限制')
                        time.sleep(0.05)
                    if process.returncode:
                        raise _error('Git 获取失败；请检查来源、引用和 SSH 授权（未运行安装脚本）')
                finally:
                    if process.poll() is None:
                        # Kill transport helpers too, including on Ctrl-C.
                        if os.name == 'nt':
                            try:
                                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL, timeout=10)
                            except (OSError, subprocess.TimeoutExpired):
                                process.kill()
                        else:
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                        process.wait()
            if destination.tell() > MAX_ARCHIVE_BYTES:
                raise _error('Git 归档超过大小限制')
            if output is None:
                capture.seek(0)
                return capture.read(MAX_ARCHIVE_BYTES + 1)
    except RuError:
        raise
    except OSError:
        raise _error('无法运行 Git；请安装 Git 并检查网络或 SSH 配置') from None


def _fetch_git(descriptor, staging):
    with tempfile.TemporaryDirectory(prefix='.ru-git-') as work:
        work = Path(work)
        _git_command(['init', '--bare', '.'], work)
        _git_command(['fetch', '--depth=1', '--no-tags', '--', _git_url(descriptor['Git']), descriptor.get('引用', 'HEAD')], work)
        commit = _git_command(['rev-parse', '--verify', 'FETCH_HEAD^{commit}'], work).decode('ascii').strip()
        if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit):
            raise _error('Git 未返回完整 commit')
        tree = commit + (':' + _subdir(descriptor['子目录']) if descriptor.get('子目录', '.') != '.' else '')
        data = _git_command(['archive', '--format=tar', tree], work)
    safe_extract_archive(data, staging)
    return commit


def _source_identity(owner, descriptor):
    if '路径' in descriptor:
        return 'path:' + str((owner.root / descriptor['路径']).resolve())
    if 'Git' in descriptor:
        return 'git:' + _git_identity(descriptor['Git']) + '#' + _subdir(descriptor.get('子目录', '.'))
    return 'registry:' + validate_https_url(descriptor['目录']) + '#' + descriptor['包']


def _record_cache_key(record):
    """Bind a lock record to its canonical source and immutable revision."""
    try:
        if record.get('mutable') is not False or not isinstance(record.get('name'), str) or not record['name']:
            raise ValueError()
        _version(record.get('version'))
        _tree_algorithm(record)
        if record.get('kind') == 'git':
            subdir = _subdir(record.get('subdir'))
            identity = 'git:' + _git_identity(record.get('url')) + '#' + subdir
            commit = record.get('commit')
            if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit):
                raise ValueError()
            key = _sha((identity + '\0' + commit).encode())
        elif record.get('kind') == 'registry':
            identity = 'registry:' + validate_https_url(record.get('url')) + '#' + record['name']
            digest = record.get('sha256')
            if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                raise ValueError()
            key = _sha((identity + '\0' + record['version'] + '\0' + digest).encode())
        else:
            raise ValueError()
        if record.get('identity') != identity or record.get('cache_key') != key:
            raise ValueError()
        if not isinstance(record.get('tree_sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', record['tree_sha256']):
            raise ValueError()
        return key
    except (RuError, TypeError, ValueError, AttributeError):
        raise _error('远程依赖锁的来源、版本或缓存身份无效；请运行 ru deps sync') from None


def _validate_cached(record, cache):
    from .packages import load_manifest
    key = _record_cache_key(record)
    root = cache / key / 'package'
    if root.parent.is_symlink() or root.is_symlink() or not root.is_dir() or not _tree_matches(root, record):
        raise _error('远程依赖缓存缺失或已改变；请运行 ru deps sync')
    try:
        manifest = load_manifest(root)
    except RuError:
        raise _error('缓存集录无效；请运行 ru deps sync') from None
    if manifest.name != record['name'] or manifest.version != record['version']:
        raise _error('缓存集录包名或版本与依赖锁不符；请运行 ru deps sync')
    return root



def _lock_error(message, manifest=None):
    return _error(message + '；锁定恢复未重新选版，需要重选时请运行 ru deps sync --update', manifest)


def _manifest_digest(manifest):
    from .packages import MAX_MANIFEST_BYTES
    with manifest.path.open('rb') as stream:
        data = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(data) > MAX_MANIFEST_BYTES:
        raise _lock_error('集录超过大小限制', manifest)
    return _sha(data)


def _physical(path):
    return os.path.normcase(str(Path(path).resolve()))


def _owner_id(locator):
    if locator == {'kind': 'project'}:
        return 'root'
    if locator.get('kind') == 'via':
        if (set(locator) != {'kind', 'owner', 'alias'} or not isinstance(locator['owner'], str)
                or not isinstance(locator['alias'], str) or not locator['alias']):
            raise _lock_error('本地包定位无效')
        return 'local:' + _sha(_json_bytes(locator))
    if locator.get('kind') == 'cache':
        if (set(locator) != {'kind', 'cache_key', 'path'} or not isinstance(locator['cache_key'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', locator['cache_key'])):
            raise _lock_error('远程包定位无效')
        path = locator['path']
        if not isinstance(path, str) or path != (_subdir(path) or '.'):
            raise _lock_error('远程包内相对位置无效')
        if path == '.':
            return 'remote:' + locator['cache_key']
        return 'bundled:' + _sha((locator['cache_key'] + '\0' + path).encode())
    raise _lock_error('包定位类型无效')


def _descriptor_matches(record, descriptor):
    """Validate the declaration-to-record binding independently of cache paths."""
    validate_dependency(descriptor)
    if '路径' in descriptor:
        if record.get('kind') != 'path' or record.get('mutable') is not True:
            raise _lock_error('路径依赖与锁来源不符')
        if _native_path(descriptor['路径']).is_absolute() and record.get('portable') is not False:
            raise _lock_error('绝对路径依赖必须标记为不可搬迁')
        return
    _record_cache_key(record)
    if 'Git' in descriptor:
        if (record['kind'] != 'git' or _git_identity(record['url']) != _git_identity(descriptor['Git'])
                or record['subdir'] != _subdir(descriptor.get('子目录', '.'))):
            raise _lock_error('Git 锁来源与集录不符')
        ref = descriptor.get('引用', 'HEAD')
        if re.fullmatch(r'[0-9a-fA-F]{40}|[0-9a-fA-F]{64}', ref) and record['commit'] != ref.lower():
            raise _lock_error('Git 锁 commit 与指定引用不符')
    elif (record['kind'] != 'registry' or record['url'] != validate_https_url(descriptor['目录'])
          or record['name'] != descriptor['包'] or not version_satisfies(record['version'], descriptor['版'])):
        raise _lock_error('目录锁来源、包名或版本与集录不符')


def _dependency_path(owner, descriptor, *, boundary=None):
    raw = _native_path(descriptor['路径'])
    if boundary is not None and raw.is_absolute():
        raise _lock_error('远程包不能声明绝对路径依赖', owner)
    path = (owner.root / raw).resolve()
    if boundary is not None and not path.is_relative_to(boundary):
        raise _lock_error('远程包的路径依赖不能越过其归档边界', owner)
    return path


def _publish_cache(temporary, record, cache):
    """Publish a fully verified tree, preserving any existing valid cache."""
    destination = cache / record['cache_key']
    if destination.exists() or destination.is_symlink():
        try:
            return _validate_cached(record, cache)
        except RuError:
            backup = cache / ('.ru-damaged-' + Path(temporary).name)
            os.replace(destination, backup)
            try:
                os.replace(temporary, destination)
            except BaseException:
                try:
                    os.replace(backup, destination)
                except OSError:
                    raise _error('缓存替换失败且无法回滚；旧缓存备份保留于 ' + str(backup)) from None
                raise
            else:
                if backup.is_dir() and not backup.is_symlink():
                    shutil.rmtree(backup)
                else:
                    backup.unlink(missing_ok=True)
    else:
        try:
            os.replace(temporary, destination)
        except OSError:
            return _validate_cached(record, cache)
    return _validate_cached(record, cache)


def _check_downloaded_manifest(record, staging, metadata=None):
    from .packages import load_manifest
    child = load_manifest(staging)
    if child.name != record['name'] or child.version != record['version']:
        raise _lock_error('下载归档集录的包名或版本与锁定身份不符')
    if metadata is not None and ('dependencies' in metadata and metadata['dependencies'] != child.dependencies
                                 or 'requires' in metadata and metadata['requires'] != child.requires):
        raise _lock_error('目录元数据与归档集录的依赖或需如言约束不符')
    for dep in child.dependencies.values():
        if '路径' in dep:
            _dependency_path(child, dep, boundary=Path(staging).resolve())
    return child


def _ensure_locked_cache(record, cache):
    """Recover one exact locked artifact; never query versions or follow a ref."""
    _record_cache_key(record)
    try:
        return _validate_cached(record, cache)
    except RuError:
        pass
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ru-stage-', dir=cache) as temporary:
        staging = Path(temporary) / 'package'
        metadata = None
        if record['kind'] == 'git':
            commit = _fetch_git({'Git': record['url'], '引用': record['commit'],
                                 '子目录': record['subdir'] or '.'}, staging)
            if commit != record['commit']:
                raise _lock_error('Git 返回的 commit 与锁定 commit 不符')
        else:
            from .package_registry import RegistryClient
            data, metadata = RegistryClient(record['url']).download(record['name'], record['version'])
            if metadata.get('sha256') != record['sha256'] or _sha(data) != record['sha256']:
                raise _lock_error('目录归档 SHA-256 与原依赖锁不符')
            safe_extract_archive(data, staging)
        _check_downloaded_manifest(record, staging, metadata)
        if not _tree_matches(staging, record):
            raise _lock_error('下载源码树 SHA-256 与原依赖锁不符')
        return _publish_cache(temporary, record, cache)


def _path_portability(owners, packages, edges):
    """Conservative whole-graph portability, independent of alias traversal."""
    records = {record['identity']: record for record in packages}
    children = {owner: [] for owner in owners}
    blocked = set()
    for edge in edges:
        target = records[edge['identity']]['owner']
        children[edge['owner']].append(target)
        if '路径' in edge['descriptor'] and _native_path(edge['descriptor']['路径']).is_absolute():
            blocked.add(target)
    pending = list(blocked)
    while pending:
        for target in children[pending.pop()]:
            if target not in blocked:
                blocked.add(target)
                pending.append(target)
    return {owner: owner not in blocked for owner in owners}


class _LockedGraph:
    """Validated portable owner locators, shared by restore and offline imports."""
    def __init__(self, root, lock, cache):
        self.root, self.lock, self.cache = root, lock, cache
        self.owners, self.records, self.by_owner, self.edges, self.anchors = {}, {}, {}, {}, {}
        self.resolved, self.real_owners, self.validated_caches = {}, {}, set()
        try:
            self._structure()
            self.check_manifest('root', root)
        except RuError as error:
            if '--update' in str(error):
                raise
            raise _lock_error('依赖锁记录、约束或定位无效', root) from None
        except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
            raise _lock_error('依赖锁格式或定位关系无效', root) from None

    def _structure(self):
        lock = self.lock
        if (type(lock.get('format')) is not int or lock['format'] != 2
                or set(lock) != {'format', 'owners', 'packages', 'edges'}):
            raise _lock_error('需要可搬运的 format 2 依赖锁；旧格式不会自动迁移', self.root)
        owners, packages, edges = lock['owners'], lock['packages'], lock['edges']
        if (not isinstance(owners, dict) or not 1 <= len(owners) <= MAX_PACKAGES
                or not isinstance(packages, list) or len(packages) > MAX_PACKAGES
                or not isinstance(edges, list) or len(edges) > MAX_PACKAGES * MAX_PACKAGES):
            raise _lock_error('依赖锁图结构或数量无效')
        for owner_id, value in owners.items():
            if (not isinstance(owner_id, str) or not isinstance(value, dict)
                    or set(value) != {'locator', 'manifest_sha256'} or not isinstance(value['locator'], dict)
                    or _owner_id(value['locator']) != owner_id or not isinstance(value['manifest_sha256'], str)
                    or not re.fullmatch(r'[0-9a-f]{64}', value['manifest_sha256'])):
                raise _lock_error('依赖锁 owner 身份或集录摘要无效')
        if owners.get('root', {}).get('locator') != {'kind': 'project'}:
            raise _lock_error('依赖锁缺少工程根')
        self.owners = owners
        for record in packages:
            if not isinstance(record, dict) or record.get('owner') not in owners or record['owner'] == 'root':
                raise _lock_error('依赖锁包 owner 无效')
            owner_id, kind, identity = record['owner'], record.get('kind'), record.get('identity')
            if not isinstance(identity, str) or identity in self.records or owner_id in self.by_owner:
                raise _lock_error('依赖锁存在重复来源或包节点')
            if kind == 'path':
                if (set(record) != {'identity', 'kind', 'mutable', 'portable', 'name', 'version', 'owner'}
                        or record.get('mutable') is not True or type(record.get('portable')) is not bool
                        or identity != 'path:' + owner_id or not isinstance(record.get('name'), str)
                        or not record['name']):
                    raise _lock_error('路径依赖锁记录无效')
                _version(record.get('version'))
            else:
                common = {'identity', 'kind', 'url', 'mutable', 'name', 'version', 'cache_key', 'tree_sha256', 'owner'}
                required = common | ({'commit', 'subdir'} if kind == 'git' else {'sha256'})
                if set(record) not in (required, required | {'tree_hash_algorithm'}):
                    raise _lock_error('远程依赖锁含缺失或未知字段')
                _record_cache_key(record)
                expected = {'kind': 'cache', 'cache_key': record['cache_key'], 'path': '.'}
                if owners[owner_id]['locator'] != expected:
                    raise _lock_error('远程包与缓存 owner 身份不符')
                if record['cache_key'] in self.anchors:
                    raise _lock_error('远程缓存身份重复')
                self.anchors[record['cache_key']] = record
            self.records[identity], self.by_owner[owner_id] = record, record
        if set(self.by_owner) != set(owners) - {'root'}:
            raise _lock_error('依赖锁存在未绑定的 owner')
        for edge in edges:
            if (not isinstance(edge, dict) or set(edge) != {'owner', 'alias', 'descriptor', 'identity'}
                    or edge.get('owner') not in owners or not isinstance(edge.get('alias'), str)
                    or edge.get('identity') not in self.records):
                raise _lock_error('依赖锁边无效')
            key = (edge['owner'], edge['alias'])
            if key in self.edges:
                raise _lock_error('依赖锁存在重复 alias 边')
            record = self.records[edge['identity']]
            _descriptor_matches(record, edge['descriptor'])
            locator = owners[edge['owner']]['locator']
            if (locator['kind'] == 'cache' and '路径' in edge['descriptor']
                    and _native_path(edge['descriptor']['路径']).is_absolute()):
                raise _lock_error('远程包不能锁定绝对路径依赖')
            self.edges[key] = edge
        for owner_id, entry in owners.items():
            locator = entry['locator']
            if locator['kind'] == 'via':
                edge = self.edges.get((locator['owner'], locator['alias']))
                if (edge is None or '路径' not in edge['descriptor']
                        or self.records[edge['identity']]['owner'] != owner_id
                        or owners[locator['owner']]['locator']['kind'] == 'cache'):
                    raise _lock_error('本地 owner 定位不是经验证的声明边')
            elif locator['kind'] == 'cache' and locator['cache_key'] not in self.anchors:
                raise _lock_error('嵌套 owner 没有锁定的远程归档锚点')
        visited, active = set(), set()
        def walk(owner_id):
            if owner_id in active:
                raise _lock_error('依赖锁存在循环')
            if owner_id in visited:
                return
            active.add(owner_id)
            for (source, _), edge in self.edges.items():
                if source == owner_id:
                    walk(self.records[edge['identity']]['owner'])
            active.remove(owner_id)
            visited.add(owner_id)
        walk('root')
        if visited != set(owners):
            raise _lock_error('依赖锁存在不可达节点')
        portable = _path_portability(owners, packages, edges)
        for record in packages:
            if record['kind'] == 'path' and record['portable'] != portable[record['owner']]:
                raise _lock_error('路径可搬迁标记与完整声明图不符')

    def check_manifest(self, owner_id, manifest):
        if _manifest_digest(manifest) != self.owners[owner_id]['manifest_sha256']:
            raise _lock_error('集录指纹已改变', manifest)
        expected = {alias: edge['descriptor'] for (owner, alias), edge in self.edges.items() if owner == owner_id}
        if manifest.dependencies != expected:
            raise _lock_error('集录依赖与锁声明边不符', manifest)
        record = self.by_owner.get(owner_id)
        if record and (record['name'] != manifest.name or record['version'] != manifest.version):
            raise _lock_error('集录包名或版本与锁不符', manifest)
        key = _physical(manifest.root)
        previous = self.real_owners.get(key)
        if previous is not None and previous != owner_id:
            raise _lock_error('不同锁 owner 指向同一真实包目录', manifest)
        previous_manifest = self.resolved.get(owner_id)
        if previous_manifest is not None and _physical(previous_manifest.root) != key:
            raise _lock_error('同一锁 owner 的声明边指向不同真实目录', manifest)
        self.real_owners[key], self.resolved[owner_id] = owner_id, manifest
        return manifest

    def boundary(self, owner_id):
        locator = self.owners[owner_id]['locator']
        if locator['kind'] == 'cache':
            return self.cache / locator['cache_key'] / 'package'
        return None

    def locate(self, owner_id):
        from .packages import load_manifest
        if owner_id in self.resolved:
            return self.resolved[owner_id]
        locator = self.owners[owner_id]['locator']
        if locator['kind'] == 'cache':
            key = locator['cache_key']
            if key not in self.validated_caches:
                _validate_cached(self.anchors[key], self.cache)
                self.validated_caches.add(key)
            base = self.cache / key / 'package'
            path = (base / locator['path']).resolve()
            if not path.is_relative_to(base.resolve()):
                raise _lock_error('远程 owner 越过归档边界')
        elif locator['kind'] == 'via':
            parent = self.locate(locator['owner'])
            descriptor = parent.dependencies.get(locator['alias'])
            edge = self.edges[(locator['owner'], locator['alias'])]
            if descriptor != edge['descriptor']:
                raise _lock_error('本地 owner 的声明边已改变', parent)
            path = _dependency_path(parent, descriptor, boundary=self.boundary(locator['owner']))
        else:
            path = self.root.root
        return self.check_manifest(owner_id, load_manifest(path))

    def owner_for(self, manifest):
        key = _physical(manifest.root)
        if key == _physical(self.root.root):
            self.check_manifest('root', manifest)
            return 'root'
        matches = []
        for owner_id, entry in self.owners.items():
            if owner_id == 'root':
                continue
            locator = entry['locator']
            if locator['kind'] == 'cache':
                expected = self.cache / locator['cache_key'] / 'package' / locator['path']
                if _physical(expected) != key:
                    continue
            try:
                candidate = self.locate(owner_id)
            except RuError:
                if locator['kind'] == 'cache':
                    raise
                continue
            if _physical(candidate.root) == key:
                matches.append(owner_id)
        if len(matches) != 1:
            raise _lock_error('当前包无法匹配唯一锁 owner', manifest)
        self.check_manifest(matches[0], manifest)
        return matches[0]


def _restore_locked(root, lock, cache):
    from .packages import load_manifest
    graph = _LockedGraph(root, lock, cache)
    visited = set()
    def visit(owner_id, owner):
        graph.check_manifest(owner_id, owner)
        if owner_id in visited:
            return
        visited.add(owner_id)
        for alias, descriptor in sorted(owner.dependencies.items()):
            record = graph.records[graph.edges[(owner_id, alias)]['identity']]
            if '路径' in descriptor:
                path = _dependency_path(owner, descriptor, boundary=graph.boundary(owner_id))
            else:
                path = _ensure_locked_cache(record, cache)
                graph.validated_caches.add(record['cache_key'])
            child = load_manifest(path)
            located = graph.locate(record['owner'])
            if _physical(child.root) != _physical(located.root):
                raise _lock_error('路径依赖与其锁定 owner 的真实位置不符', owner)
            visit(record['owner'], child)
    visit('root', root)
    return lock


def _resolve_new(root, cache):
    """Resolve a fresh graph only for a missing lock or explicit --update."""
    from .packages import load_manifest
    packages, edges, owners, selected, active = [], [], {}, {}, set()
    paths = {}
    constraints, preferences, clients, available, downloads = {}, {}, {}, {}, {}

    class RetryResolution(Exception):
        pass

    def registry_versions(identity, descriptor):
        if identity not in clients:
            from .package_registry import RegistryClient
            clients[identity] = RegistryClient(descriptor['目录'])
        if identity not in available:
            available[identity] = clients[identity].versions(descriptor['包'])
        return [version for version in available[identity]
                if all(version_satisfies(version, constraint) for constraint in constraints[identity])]

    def register(owner, locator):
        real = _physical(owner.root)
        if real in paths:
            previous = paths[real]
            if locator['kind'] == 'cache' and owners[previous]['locator'] != locator:
                raise _lock_error('路径来源与远程来源不能混淆同一缓存目录', owner)
            return previous
        owner_id = _owner_id(locator)
        if owner_id in owners or len(owners) >= MAX_PACKAGES:
            raise _error('包定位重复或依赖图超过安全数量限制', owner)
        owners[owner_id] = {'locator': locator, 'manifest_sha256': _manifest_digest(owner)}
        paths[real] = owner_id
        return owner_id

    def boundary(owner_id):
        locator = owners[owner_id]['locator']
        return cache / locator['cache_key'] / 'package' if locator['kind'] == 'cache' else None

    def visit(owner_id, owner):
        if owner_id in active:
            raise _error('包依赖存在循环', owner)
        if owner_id in visited:
            return
        visited.add(owner_id)
        active.add(owner_id)
        for alias, descriptor in sorted(owner.dependencies.items()):
            validate_dependency(descriptor)
            if '路径' in descriptor:
                anchor = boundary(owner_id)
                child = load_manifest(_dependency_path(owner, descriptor, boundary=anchor))
                portable = not _native_path(descriptor['路径']).is_absolute()
                if anchor is not None:
                    locator = {'kind': 'cache', 'cache_key': owners[owner_id]['locator']['cache_key'],
                               'path': child.root.relative_to(anchor).as_posix()}
                else:
                    locator = {'kind': 'via', 'owner': owner_id, 'alias': alias}
                child_id = register(child, locator)
                identity = 'path:' + child_id
                record = {'identity': identity, 'kind': 'path', 'mutable': True, 'portable': portable,
                          'name': child.name, 'version': child.version, 'owner': child_id}
                previous = selected.get(identity)
                if previous:
                    previous['record']['portable'] &= portable
                    record = previous['record']
            else:
                identity = _source_identity(owner, descriptor)
                previous = selected.get(identity)
                if '目录' in descriptor:
                    constraints.setdefault(identity, []).append(descriptor['版'])
                    if previous is not None and not all(version_satisfies(previous['record']['version'], bound)
                                                         for bound in constraints[identity]):
                        candidates = registry_versions(identity, descriptor)
                        if not candidates:
                            raise _error('同一来源包的版本约束冲突；首版不支持多版本', owner)
                        preferences[identity] = max(candidates, key=_version)
                        raise RetryResolution()
                cache.mkdir(parents=True, exist_ok=True)
                if previous is not None and ('目录' in descriptor or previous['descriptor'] == descriptor):
                    record = previous['record']
                    child = load_manifest(_validate_cached(record, cache))
                else:
                    with tempfile.TemporaryDirectory(prefix='.ru-stage-', dir=cache) as temporary:
                        staging = Path(temporary) / 'package'
                        metadata = None
                        if 'Git' in descriptor:
                            commit = _fetch_git(descriptor, staging)
                            record = {'identity': identity, 'kind': 'git', 'url': _git_url(descriptor['Git']),
                                      'commit': commit, 'subdir': _subdir(descriptor.get('子目录', '.')), 'mutable': False}
                            key = _sha((identity + '\0' + commit).encode())
                        else:
                            versions = registry_versions(identity, descriptor)
                            if not versions:
                                raise _error('目录没有满足约束的包版本', owner)
                            version = preferences.get(identity)
                            if version not in versions:
                                version = max(versions, key=_version)
                            download_key = (identity, version)
                            if download_key not in downloads:
                                downloads[download_key] = clients[identity].download(descriptor['包'], version)
                            data, metadata = downloads[download_key]
                            digest = metadata.get('sha256')
                            if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest) or _sha(data) != digest:
                                raise _error('目录归档 SHA-256 不匹配', owner)
                            safe_extract_archive(data, staging)
                            record = {'identity': identity, 'kind': 'registry', 'url': validate_https_url(descriptor['目录']),
                                      'name': descriptor['包'], 'version': version, 'sha256': digest, 'mutable': False}
                            key = _sha((identity + '\0' + version + '\0' + digest).encode())
                        child = load_manifest(staging)
                        if record['kind'] == 'git':
                            record.update(name=child.name, version=child.version)
                        _check_downloaded_manifest(record, staging, metadata)
                        record.update(cache_key=key, tree_sha256=_tree_hash(staging),
                                      tree_hash_algorithm=TREE_HASH_ALGORITHM)
                        child = load_manifest(_publish_cache(temporary, record, cache))
                locator = {'kind': 'cache', 'cache_key': record['cache_key'], 'path': '.'}
                child_id = register(child, locator)
                record['owner'] = child_id
            if previous is not None:
                old = previous['record']
                if (old['version'] != record['version'] or old.get('commit') != record.get('commit')
                        or old.get('sha256') != record.get('sha256') or old['owner'] != record['owner']):
                    raise _error('同一来源包解析为不同版本或 commit；首版不支持多版本', owner)
            else:
                selected[identity] = {'record': record, 'descriptor': descriptor}
                packages.append(record)
            edges.append({'owner': owner_id, 'alias': alias, 'descriptor': descriptor, 'identity': identity})
            visit(child_id, child)
        active.remove(owner_id)

    attempts = set()
    while True:
        signature = tuple(sorted(preferences.items()))
        if signature in attempts or len(attempts) >= MAX_PACKAGES:
            raise _error('版本约束无法得到稳定的单版本依赖图', root)
        attempts.add(signature)
        packages, edges, owners, selected, active, visited = [], [], {}, {}, set(), set()
        paths, constraints = {}, {}
        register(root, {'kind': 'project'})
        try:
            visit('root', root)
            break
        except RetryResolution:
            continue
    portable = _path_portability(owners, packages, edges)
    for record in packages:
        if record['kind'] == 'path':
            record['portable'] = portable[record['owner']]
    lock = {'format': 2, 'owners': owners, 'packages': packages, 'edges': edges}
    _LockedGraph(root, lock, cache)
    return lock


def sync_dependencies(directory='.', *, cache_dir=None, locked=False, update=False):
    """Restore an existing lock exactly; only --update reselects remote versions."""
    from .packages import load_manifest
    if locked and update:
        raise _error('--locked 与 --update 不能同时使用')
    root = load_manifest(directory)
    cache, path = _cache_dir(cache_dir), root.root / LOCK_NAME
    try:
        if path.is_symlink():
            raise _lock_error('依赖锁不能为符号链接', root)
        if path.exists() and not update:
            try:
                lock = _read_json(path)
            except RuError:
                raise _lock_error('依赖锁已损坏，未自动重新解析', root) from None
            return _restore_locked(root, lock, cache)
        if locked:
            raise _lock_error('--locked 要求已有有效依赖锁', root)
        lock = _resolve_new(root, cache)
        _atomic_json(path, lock)
        return lock
    except RuError as error:
        error.source_name = getattr(error, 'source_name', str(root.path))
        error.suppress_source = True
        raise
    except (OSError, ValueError, UnicodeError):
        raise _error('依赖同步失败；原有锁文件及有效缓存保持不变', root) from None


def resolve_cached_dependency(owner_manifest, alias, descriptor, *, project_root=None, cache_dir=None):
    """Resolve using the current machine's cache, without any network calls."""
    from .packages import load_manifest
    validate_dependency(descriptor)
    if '路径' in descriptor:
        return _dependency_path(owner_manifest, descriptor)
    try:
        root = load_manifest(project_root or owner_manifest.root)
        path = root.root / LOCK_NAME
        if path.is_symlink():
            raise _lock_error('依赖锁不能为符号链接', owner_manifest)
        try:
            lock = _read_json(path)
        except RuError:
            raise _lock_error('依赖锁缺失或损坏；请运行 ru deps sync', owner_manifest) from None
        graph = _LockedGraph(root, lock, _cache_dir(cache_dir))
        owner_id = graph.owner_for(owner_manifest)
        edge = graph.edges.get((owner_id, alias))
        if edge is None or edge['descriptor'] != descriptor or owner_manifest.dependencies.get(alias) != descriptor:
            raise _lock_error('依赖锁声明边与当前集录不符', owner_manifest)
        record = graph.records[edge['identity']]
        _descriptor_matches(record, descriptor)
        path = _validate_cached(record, graph.cache)
        child = graph.locate(record['owner'])
        if _physical(child.root) != _physical(path):
            raise _lock_error('依赖缓存与 owner 定位不符', owner_manifest)
        return path
    except RuError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise _lock_error('依赖锁或缓存缺失／过期', owner_manifest) from None
