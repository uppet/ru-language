"""Resolve local imports once, with a deterministic, self-contained module graph.

Imports are string literals, resolved relative to the file containing them.
Both backends use this loader; the native backend bundles the resulting ASTs
at build time, so the executable never needs the source files.
"""
from pathlib import Path

from .frontend import Node, RuError, parse, validate


GENERATION_MARKER = "如是我言"


def read_source(path):
    source = Path(path).read_text(encoding="utf-8-sig")
    if source.rstrip().endswith(GENERATION_MARKER):
        raise RuError("检测到以「如是我言」结尾的意图文档。LLM 生成入口尚未连接提供方；未发送文档，也未生成或执行代码。请先手写 .ru 源码。", category="生成功能未配置")
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
                if not requested or "://" in requested:
                    raise RuError("外言只接受非空的本地文件路径", imported.token.line,
                                  imported.token.col, "模块错误")
                resolved = str((Path(path).parent / requested).resolve())
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
