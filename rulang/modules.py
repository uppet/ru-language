"""Resolve local imports once, with a deterministic, self-contained module graph.

Imports are string literals, resolved relative to the file containing them.
The interpreter and both compilers use this loader. Both compilers lower all
resolved modules into standalone outputs that need no source files at runtime.
"""
from pathlib import Path

from .frontend import Node, RuError, parse, validate, comment_marker, block_comment_end


GENERATION_MARKER = "如是我言"
STANDARD_MODULES = {"如:竞": "如竞.ru", "如:观": "如观.ru", "如:文本": "文本.ru",
                    "如:数学": "数学.ru", "如:随机": "随机.ru"}


RENAMED_MODULES = {"如竞": "如:竞", "如观": "如:观", "如:竞赛": "如:竞"}


def reject_renamed_import(requested):
    """Diagnose retired bare names before any local resolution or file read."""
    replacement = RENAMED_MODULES.get(requested)
    if replacement is not None:
        raise RuError(f"标准外言「{requested}」已改名为「{replacement}」；请改用 外言 '{replacement}'", category="模块错误")


def resolve_import(requested, importer_path):
    """Reserve exact bundled/retired names and 如: names, without local fallback."""
    reject_renamed_import(requested)
    filename = STANDARD_MODULES.get(requested)
    if filename is not None:
        return str((Path(__file__).parent / "stdlib" / filename).resolve())
    if requested.startswith("如:"):
        raise RuError("未知的标准外言：" + requested, category="模块错误")
    if not requested or "://" in requested:
        raise RuError("外言只接受本地文件路径或已知的标准库名称", category="模块错误")
    return str((Path(importer_path).parent / requested).resolve())


def generation_intent(source):
    """Return the document before a final standalone, unquoted marker, or None.

    Intent may be loose Markdown/Org rather than valid Ru. This scanner only
    tracks Ru strings/comments; lexing the entire document would reject prose.
    Quotes follow the source lexer, except apostrophes between ASCII letters
    (English prose contractions). Quotes adjacent to Chinese names still open
    source strings. This convention permits loose Markdown/Org English prose.
    """
    lines = source.splitlines(keepends=True)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines or lines[-1].strip() != GENERATION_MARKER:
        return None
    prefix = "".join(lines[:-1])
    quotes, closing, i = {"'": "'", '"': '"', "‘": "’", "“": "”"}, None, 0
    while i < len(prefix):
        char = prefix[i]
        if closing:
            if char == "\\":
                i += 2
                continue
            if char == closing:
                closing = None
        elif char == "#" or prefix.startswith("//", i) or comment_marker(prefix, i, "批"):
            newline = prefix.find("\n", i)
            i = len(prefix) if newline < 0 else newline
        elif comment_marker(prefix, i, "解"):
            end = block_comment_end(prefix, i)
            if end is None:
                return None
            i = end
            continue
        elif char in quotes:
            contraction = (char == "'" and i > 0 and i + 1 < len(prefix)
                           and prefix[i - 1].isascii() and prefix[i - 1].isalpha()
                           and prefix[i + 1].isascii() and prefix[i + 1].isalpha())
            if not contraction:
                closing = quotes[char]
        i += 1
    return prefix if closing is None else None


def reject_generation_document(source):
    if generation_intent(source) is not None:
        error = RuError("检测到意图文档；请显式使用 ru generate 文档路径 生成独立源码，再审阅并运行。此命令未联网或执行文档。", category="生成入口错误")
        error.suppress_source = True
        raise error


def read_source(path):
    source = Path(path).read_text(encoding="utf-8-sig")
    reject_generation_document(source)
    return source


def import_nodes(value):
    """Yield imports even inside functions, classes and unreachable branches."""
    if isinstance(value, Node):
        if value.kind == "import":
            yield value
        for child in value.data.values():
            yield from import_nodes(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from import_nodes(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from import_nodes(child)


class ModuleGraph(dict):
    """Canonical absolute paths map to programs; source text is diagnostic-only."""

    def __init__(self, root):
        super().__init__()
        self.root = root
        self.sources = {}


def load_module_graph(source_path, program=None):
    """Parse/validate imports without executing any top-level statements.

    Supplying a program supports compiler clients whose root AST did not come
    from a file. Relative imports in such a program still use source_path.
    Import cycles are a diagnosed v0.2 restriction, including dormant imports.
    """
    root = str(Path(source_path).resolve())
    graph, active = ModuleGraph(root), []

    def visit(path, supplied=None, origin=None, origin_path=None):
        if path in active:
            chain = " → ".join(Path(p).name for p in active[active.index(path):] + [path])
            error = RuError("不支持循环外言：" + chain,
                            origin.token.line if origin else 1,
                            origin.token.col if origin else 1, "模块错误")
            error.source_name = origin_path or path
            error.source_text = graph.sources.get(error.source_name, "")
            raise error
        if path in graph:
            return
        if len(active) >= 128:
            raise RuError("外言依赖嵌套超过 128 层", category="模块错误")
        active.append(path)
        try:
            if supplied is None:
                try:
                    source = read_source(path)
                except (OSError, UnicodeError) as exc:
                    error = RuError(f"无法读取外言「{path}」：{exc}",
                                    origin.token.line if origin else 1,
                                    origin.token.col if origin else 1, "模块错误")
                    error.source_name = origin_path or path
                    error.source_text = graph.sources.get(error.source_name, "")
                    raise error from None
                graph.sources[path] = source
                supplied = parse(source)
            validate(supplied)
            graph[path] = supplied
            for imported in import_nodes(supplied):
                requested = imported.data["path"]
                try:
                    resolved = resolve_import(requested, path)
                except RuError as error:
                    error.line, error.col = imported.token.line, imported.token.col
                    raise
                imported.data["resolved"] = resolved
                visit(resolved, origin=imported, origin_path=path)
        except RuError as error:
            if not hasattr(error, "source_name"):
                error.source_name = path
                error.source_text = graph.sources.get(path, "")
            raise
        finally:
            active.pop()

    visit(root, supplied=program)
    return graph
