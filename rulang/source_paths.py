"""Explicit display-only source path mapping for generated C diagnostics."""
import ntpath
import os
from pathlib import Path, PurePosixPath, PureWindowsPath

from .frontend import RuError

_WINDOWS_HOST = os.name == 'nt'


def _resolve_host_path(path):
    try:
        return str(Path(path).resolve())
    except (OSError, RuntimeError) as error:
        raise RuError(f'源码路径映射无法解析路径：{path}（{error}）', category='编译错误') from None


def _parts(path):
    """Normalize path components without interpreting foreign drive paths."""
    drive, tail = ntpath.splitdrive(path)
    windows = bool(drive) or _WINDOWS_HOST
    if windows:
        if drive and not tail.startswith(('\\', '/')) and tail:
            raise RuError('源码路径映射不接受 Windows 盘符相对路径；请使用完整绝对路径', category='编译错误')
        if drive.endswith(':') and not tail:
            raise RuError('源码路径映射的 Windows 盘符须包含根目录分隔符', category='编译错误')
        if _WINDOWS_HOST:
            # Match the module loader's canonicalization, including junctions.
            # A foreign Windows path cannot be resolved on a POSIX host.
            path = _resolve_host_path(path)
        normalized = ntpath.normpath(path)
        parts = PureWindowsPath(normalized).parts
        return True, parts, tuple(ntpath.normcase(part) for part in parts)
    # Source modules already use resolved host paths. Resolve prefixes in the
    # same way, but never alter module identities or the original source text.
    parts = PurePosixPath(_resolve_host_path(path)).parts
    return False, parts, parts


class SourcePathMapper:
    def __init__(self, specifications=()):
        if isinstance(specifications, SourcePathMapper):
            self.rules = specifications.rules
            return
        if isinstance(specifications, str):
            raise RuError('源码路径映射须为 OLD=NEW 列表', category='编译错误')
        rules = []
        for specification in specifications:
            if not isinstance(specification, str) or '=' not in specification:
                raise RuError('源码路径映射须为 OLD=NEW', category='编译错误')
            old, new = specification.split('=', 1)
            if not old or any(c in old + new for c in '\x00\r\n'):
                raise RuError('源码路径映射的 OLD 不能为空，路径不能含 NUL 或换行', category='编译错误')
            windows, _, key = _parts(old)
            rules.append((windows, key, new))
        self.rules = tuple(rules)

    def __bool__(self):
        return bool(self.rules)

    def __call__(self, source):
        if not self.rules or (source.startswith('<') and source.endswith('>')):
            return source
        windows, parts, key = _parts(source)
        match = None
        for rule_windows, prefix, replacement in self.rules:
            if windows == rule_windows and key[:len(prefix)] == prefix:
                # Component boundaries prevent /work from matching /worker.
                # Later rules win ties; deeper prefixes always win otherwise.
                if match is None or len(prefix) >= match[0]:
                    match = len(prefix), replacement
        if match is None:
            return source
        length, replacement = match
        suffix = '/'.join(parts[length:])
        if not suffix:
            return replacement or '.'
        return replacement.rstrip('/\\') + '/' + suffix if replacement else suffix
