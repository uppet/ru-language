"""Static package manifests and offline package/module identity resolution.

No manifest expression is evaluated, and this module never starts a download.
All filesystem identities use real paths, including boundary and cache checks.
"""
from dataclasses import dataclass
from pathlib import Path
import re

from .frontend import KEYWORDS, Parser, RuError, lex

MANIFEST_NAME = '集录.ru'
MAX_MANIFEST_BYTES = 1024 * 1024
FIELDS = frozenset(('名', '版', '需如言', '源码根', '公开', '依赖'))


class _StaticMap(dict):
    def __init__(self, token):
        super().__init__()
        self.token, self.locations, self.keys_at = token, {}, {}


class _StaticList(list):
    def __init__(self, items):
        self.locations = [item.token for item in items]
        super().__init__(_literal(item) for item in items)


def _error(message, token=None):
    raise RuError(message, token.line if token else 1, token.col if token else 1, '包错误')


def _literal(n):
    if n.kind in ('string', 'number', 'fact'):
        return n.data['value']
    if n.kind == 'null':
        return None
    if n.kind == 'unary' and n.data['op'] in ('+', '-') and n.data['expr'].kind == 'number':
        value = n.data['expr'].data['value']
        return -value if n.data['op'] == '-' else value
    if n.kind == 'array':
        return _StaticList(n.data['items'])
    if n.kind == 'map':
        result = _StaticMap(n.token)
        for key, value in n.data['entries']:
            if key.kind != 'string':
                _error('集录的典目须为字符串字面量', key.token)
            name = key.data['value']
            if name in result:
                _error('集录存在重复字段', key.token)
            result.locations[name] = value.token
            result.keys_at[name] = key.token
            result[name] = _literal(value)
        return result
    _error('集录只接受静态字面量及阵／典容器，不执行表达式', n.token)


def _identifier(value):
    if not isinstance(value, str):
        return False
    try:
        tokens = lex(value)
    except RuError:
        return False
    return (len(tokens) == 2 and tokens[0].kind == 'NAME' and tokens[0].value == value
            and value not in KEYWORDS)


def _inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _relative_path(value, base, label, token):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        _error(label + '须为非空相对路径，使用 / 分隔', token)
    raw = Path(value)
    if raw.is_absolute() or '..' in raw.parts:
        _error(label + '不能使用绝对路径或 ..', token)
    result = (base / raw).resolve()
    if not _inside(result, base):
        _error(label + '不能通过符号链接越过包边界', token)
    return result


@dataclass(frozen=True)
class Manifest:
    path: Path
    root: Path
    name: str
    version: str
    requires: str
    source_root: Path
    public: dict
    dependencies: dict


def load_manifest(path):
    path = Path(path).absolute()
    source = ''
    try:
        if path.is_dir():
            path = path.resolve() / MANIFEST_NAME
        if path.is_symlink():
            _error('集录文件不能是符号链接；包根必须来自其真实所在目录')
        path = path.resolve()
        with path.open('rb') as stream:
            data = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(data) > MAX_MANIFEST_BYTES:
            _error('集录超过 1 MiB 大小上限')
        source = data.decode('utf-8-sig')
        parser = Parser(source)
        value = _literal(parser.expression(allow_call=False))
        parser.accept('.')
        if parser.current.kind != 'EOF':
            _error('集录只能包含一个静态典', parser.current)
        if not isinstance(value, _StaticMap):
            _error('集录须为一个静态典')
        for key in value:
            if key not in FIELDS:
                _error('未知集录字段', value.keys_at[key])
        def token(key):
            return value.locations.get(key, value.token)
        def string(key, default=None):
            result = value.get(key, default)
            if not isinstance(result, str):
                _error('集录「' + key + '」须为句', token(key))
            return result
        name = string('名')
        if not _identifier(name):
            _error('集录「名」须为一个如言名称', token('名'))
        if name in ('如见', '如观', '如竞'):
            _error('包名与固定随附外言名称冲突', token('名'))
        version = string('版', '0.0.0')
        if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
            _error('集录「版」须为三段非负整数版本，例如 1.0.0', token('版'))
        requires = string('需如言', '')
        if '需如言' in value:
            from .package_sources import validate_constraint, version_satisfies
            from . import __version__
            try:
                validate_constraint(requires)
                if not version_satisfies(__version__, requires):
                    _error('当前如言版本不满足「需如言」约束', token('需如言'))
            except RuError as error:
                error.line, error.col = token('需如言').line, token('需如言').col
                raise
        root = path.parent
        source_root = _relative_path(string('源码根', 'src'), root, '源码根', token('源码根'))
        raw_public = value.get('公开', [])
        if not isinstance(raw_public, (list, dict)):
            _error('集录「公开」须为模块名阵或模块名到路径的典', token('公开'))
        public, used_paths = {}, set()
        for index, relative in enumerate(raw_public):
            location = (raw_public.locations.get(relative, token('公开')) if isinstance(raw_public, _StaticMap)
                        else raw_public.locations[index])
            if not isinstance(relative, str):
                _error('公开模块名须为句', location)
            parts = () if relative == '.' else tuple(relative.split('/'))
            if not parts and relative != '.' or any(not _identifier(part) for part in parts):
                _error('公开模块名须为 / 分隔的包内名称，包根使用 .', location)
            canonical = (name,) + parts
            if canonical in public:
                _error('重复的公开模块名：' + relative, location)
            if isinstance(raw_public, dict):
                target = _relative_path(raw_public[relative], root, '公开路径', location)
            else:
                target = (source_root.joinpath(*parts).with_suffix('.ru') if parts
                          else source_root / (name + '.ru')).resolve()
                if not _inside(target, root):
                    _error('公开路径不能通过符号链接越过包边界', location)
            if target.suffix != '.ru':
                _error('公开路径须指向 .ru 源码', location)
            if target in used_paths:
                _error('同一源码不能公开为多个模块名', location)
            used_paths.add(target)
            public[canonical] = target
        dependencies = value.get('依赖', {})
        if not isinstance(dependencies, dict):
            _error('集录「依赖」须为典', token('依赖'))
        for alias, descriptor in dependencies.items():
            location = dependencies.locations.get(alias, token('依赖'))
            if not _identifier(alias) or alias == name or alias in ('如见', '如观', '如竞'):
                _error('依赖别名无效或与当前包／固定外言名称冲突', location)
            if not isinstance(descriptor, dict):
                _error('依赖来源须为典', location)
            source_keys = set(descriptor) & {'路径', 'Git', '目录'}
            if len(source_keys) == 1:
                allowed = {'路径': {'路径'}, 'Git': {'Git', '引用', '子目录'},
                           '目录': {'目录', '包', '版'}}[next(iter(source_keys))]
                for key, item in descriptor.items():
                    if key not in allowed:
                        _error('未知依赖来源字段', descriptor.keys_at[key])
                    if not isinstance(item, str) or not item:
                        _error('依赖来源字段须为非空句', descriptor.locations[key])
            from .package_sources import validate_dependency
            try:
                validate_dependency(descriptor)
            except RuError as error:
                error.line, error.col = location.line, location.col
                raise
        return Manifest(path, root, name, version, requires, source_root, public, dependencies)
    except (OSError, UnicodeError, RuntimeError):
        error = RuError('无法读取 UTF-8 集录', category='包错误')
        error.source_name, error.suppress_source = str(path), True
        raise error from None
    except RuError as error:
        if error.category != '包错误':
            error.message = '集录语法无效；请使用单个静态典字面量'
            error.args = (error.message,)
        error.category = '包错误'
        error.source_name, error.source_text = str(path), source
        # Manifests may contain a mistakenly pasted URL credential. Position is
        # enough; never quote the source line in CLI diagnostics or logs.
        error.suppress_source = True
        raise


def find_manifest(source_path):
    path = Path(source_path).resolve()
    directory = path if path.is_dir() else path.parent
    for root in (directory, *directory.parents):
        manifest = root / MANIFEST_NAME
        if manifest.is_file():
            return load_manifest(manifest)
    return None


class PackageResolver:
    """One graph, one offline resolution context and canonical module identity."""
    def __init__(self, source_path):
        self.manifests, self.dependencies = {}, {}
        project = self.owner(source_path)
        self.project_root = project.root if project else None

    def owner(self, path):
        directory = Path(path).resolve().parent
        if directory not in self.manifests:
            self.manifests[directory] = find_manifest(path)
        return self.manifests[directory]

    def dependency(self, owner, alias):
        key = (owner.path, alias)
        if key not in self.dependencies:
            descriptor = owner.dependencies[alias]
            if '路径' in descriptor:
                root = (owner.root / descriptor['路径']).resolve()
            else:
                from .package_sources import resolve_cached_dependency
                root = resolve_cached_dependency(owner, alias, descriptor, project_root=self.project_root)
            target = load_manifest(root)
            self.dependencies[key] = target
        return self.dependencies[key]

    def expected_name(self, owner, path):
        path = Path(path).resolve()
        for name, public_path in owner.public.items():
            if path == public_path:
                return name
        if _inside(path, owner.source_root) and path.suffix == '.ru':
            parts = path.relative_to(owner.source_root).with_suffix('').parts
            return (owner.name,) if parts == (owner.name,) else (owner.name, *parts)
        return None

    def named(self, parts, importer):
        owner = self.owner(importer)
        if owner is None:
            _error('具名外言需要集录.ru；本地脚本可继续使用字符串路径')
        if parts[0] == owner.name:
            target = owner
        elif parts[0] in owner.dependencies:
            target = self.dependency(owner, parts[0])
        else:
            _error('具名外言根未声明为依赖：' + parts[0])
        canonical = (target.name, *parts[1:])
        path = target.public.get(canonical)
        if path is None:
            if target.root == owner.root:
                # Self-names may reference private modules under the source root.
                path = (target.source_root.joinpath(*parts[1:]).with_suffix('.ru') if len(parts) > 1
                        else target.source_root / (target.name + '.ru')).resolve()
                actual = self.owner(path)
                if not _inside(path, target.root) or actual is None or actual.root != target.root:
                    _error('自身具名外言不能越过包边界')
            else:
                _error('依赖未公开此模块：' + ' 其 '.join(parts))
        actual = self.owner(path)
        if actual is None or actual.root != target.root:
            _error('公开模块不能越过包边界')
        if self.expected_name(target, path) != canonical:
            _error('具名外言须使用模块的唯一正式名称')
        return str(path)

    def path(self, resolved, importer):
        source, target = self.owner(importer), self.owner(resolved)
        path = Path(resolved).resolve()
        if source is not None and target is not None and source.root == target.root:
            return str(path)
        if source is not None:
            if target is None:
                _error('路径外言不能越过包边界；请在集录中声明依赖')
            # Local edges can be matched without resolving unrelated remote
            # dependencies, so a local import never demands an unrelated sync.
            declared = False
            for alias, descriptor in source.dependencies.items():
                if '路径' in descriptor:
                    candidate = (source.root / descriptor['路径']).resolve()
                    if candidate == target.root:
                        declared = self.dependency(source, alias).root == target.root
                        break
            if not declared:
                for alias, descriptor in source.dependencies.items():
                    if '路径' in descriptor:
                        continue
                    try:
                        candidate = self.dependency(source, alias)
                    except RuError:
                        continue  # An unusable edge cannot grant path access.
                    if candidate.root == target.root:
                        declared = True
                        break
            if not declared:
                _error('跨包路径外言未声明可用依赖；远程依赖缺失时请运行 ru deps sync')
        if target is not None and path not in target.public.values():
            _error('跨包路径外言只能访问依赖的公开入口')
        return str(path)

    def check_declaration(self, path, program):
        declarations = [n for n in program if n.kind == 'module_decl']
        if not declarations:
            return
        owner = self.owner(path)
        if owner is None:
            return  # A standalone file may document its name without a package.
        expected = self.expected_name(owner, path)
        declaration = declarations[0]
        if expected is None or declaration.data['name'] != expected:
            _error('模块声明与包中正式名称不一致' +
                   ('；应为「吾 言 ' + ' 其 '.join(expected) + '.」' if expected else ''), declaration.token)
