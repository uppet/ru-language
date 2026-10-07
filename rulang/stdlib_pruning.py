"""Conservative declaration reachability for the bundled contest library.

This is deliberately not a general dead-code eliminator. User modules, including
unused functions and their validation errors, remain intact. Only the exact
bundled declaration-only module is eligible. All other ASTs are roots, and names
are over-approximated across lexical scopes rather than guessed from spelling.

The caller must validate the original, complete module graph before lowering the
returned graph. In particular, export collisions must not disappear because an
unused declaration was removed. Names in bindings and declaration metadata are
also roots, preserving runtime protected-name and import-all checks.
"""
from pathlib import Path

from .frontend import Node, RuError, parse
from .modules import import_nodes


_BUNDLED_PATH = str((Path(__file__).parent / 'stdlib' / '竞赛.ru').resolve())
_KNOWN_KINDS = frozenset((
    'function', 'type', 'bind', 'assign', 'import_all', 'print', 'expr',
    'return', 'break', 'if', 'loop', 'try', 'panic', 'number', 'string',
    'null', 'self', 'name', 'call', 'function_ref', 'invoke', 'array',
    'convert', 'unary', 'binary', 'member', 'index', 'slice', 'new', 'import',
))


def _walk(value):
    if isinstance(value, Node):
        yield value
        yield from _walk(value.data)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def _strings(value):
    """Include declaration/binding metadata, not only expression references.

    Counting matching literal strings too is a harmless conservative choice;
    this avoids any assumptions about which metadata can affect name lookup.
    Tokens are intentionally excluded because they duplicate syntax, not uses.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, Node):
        yield from _strings(value.data)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _strings(child)


def _shape(value):
    """Compare source ASTs without depending on token positions or identities."""
    if isinstance(value, Node):
        return value.kind, _shape(value.data)
    if isinstance(value, dict):
        return {key: _shape(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_shape(child) for child in value)
    return value


def _trusted_declarations(statements):
    # A client can supply its own AST at any path; a trusted path alone does not
    # prove that those declarations are the shipped library. Refuse substitutes
    # and future library versions with observable top-level initialization.
    if not statements or any(n.kind != 'function' for n in statements):
        return False
    try:
        bundled = parse(Path(_BUNDLED_PATH).read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, RuError):
        return False
    return _shape(statements) == _shape(bundled)


def _module_escapes(modules, candidate):
    """Fail closed when a library-containing module value escapes analysis.

    Imports and simple aliases may be used as static member receivers. We track
    aliases flow-insensitively, across every scope and re-exporting module; a
    shadowed name therefore only retains too much. Passing, returning, storing
    in a container, or otherwise observing a module keeps all its declarations.
    First-class *functions* selected from modules need only their own names.
    """
    nodes = [n for body in modules.values() for n in _walk(body)]
    if any(n.kind not in _KNOWN_KINDS for n in nodes):
        return True
    dependencies = {}
    for path, body in modules.items():
        targets = set()
        for imported in import_nodes(body):
            target = imported.data.get('resolved')
            if target not in modules:
                return True
            targets.add(target)
        dependencies[path] = targets
    relevant = {candidate}
    while True:
        expanded = relevant | {path for path, targets in dependencies.items()
                               if targets & relevant}
        if expanded == relevant:
            break
        relevant = expanded

    aliases = set()

    def module_value(n):
        if not isinstance(n, Node):
            return False
        if n.kind == 'import':
            return n.data.get('resolved') in relevant
        if n.kind in ('name', 'member'):
            # A module's public binding may itself hold a module alias. Global
            # member-name taint includes chains through arbitrary re-exports.
            return n.data['name'] in aliases
        return False

    bindings = [n for n in nodes if n.kind == 'bind']
    while True:
        expanded = aliases | {n.data['name'] for n in bindings
                              if module_value(n.data['expr'])}
        if expanded == aliases:
            break
        aliases = expanded

    def escapes(value, context=None):
        if isinstance(value, Node):
            if module_value(value) and context not in (
                    'receiver', 'alias', 'import_all', 'discard'):
                return True
            d = value.data
            if value.kind == 'bind':
                return escapes(d['expr'], 'alias')
            if value.kind == 'member':
                return escapes(d['receiver'], 'receiver') or escapes(d['args'])
            if value.kind == 'import_all':
                return escapes(d['expr'], 'import_all')
            if value.kind == 'expr':
                return escapes(d['expr'], 'discard')
            if value.kind in ('call', 'new') and d['name'] in aliases:
                return True
            return escapes(d)
        if isinstance(value, dict):
            return any(escapes(child) for child in value.values())
        if isinstance(value, (list, tuple)):
            return any(escapes(child) for child in value)
        return False

    return any(escapes(body) for body in modules.values())


def prune_bundled_stdlib(program, source_name, modules):
    """Return a fresh module mapping with unreachable bundled functions removed.

    ``modules`` is the already-resolved, fully validated graph. Its source lists
    and AST nodes are never modified. Returned statement lists are new; retained
    AST nodes are shared so compiler diagnostic locations and identity stay
    intact. A caller's full-runtime/debug mode should skip this function.
    """
    root = str(Path(source_name).resolve()) if modules else str(source_name)
    result = {path: list(body) for path, body in (modules or {}).items()}
    result[root] = list(program)
    candidate = result.get(_BUNDLED_PATH)
    if not _trusted_declarations(candidate or []):
        return result
    if _module_escapes(result, _BUNDLED_PATH):
        return result

    declarations = {n.data['name']: n for n in candidate}
    names = set(declarations)
    needed = set()
    for path, body in result.items():
        if path != _BUNDLED_PATH:
            needed.update(names.intersection(_strings(body)))
    pending = list(needed)
    while pending:
        name = pending.pop()
        dependencies = names.intersection(_strings(declarations[name])) - needed
        needed.update(dependencies)
        pending.extend(dependencies)
    result[_BUNDLED_PATH] = [n for n in candidate if n.data['name'] in needed]
    return result
