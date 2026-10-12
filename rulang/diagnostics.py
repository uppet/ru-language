"""Editor-neutral diagnostics. Positions are one-based Unicode code points.

Source identities contain metadata only, never the source text. Notebook tokens
retain the defining execution identity even when functions escape that execution.
"""
from dataclasses import dataclass, asdict
import hashlib
import re
from urllib.parse import quote


@dataclass(frozen=True)
class SourceOrigin:
    source_name: str
    kind: str = "file"
    cell_id: str = None
    execution_count: int = None
    generation: int = None
    source_version: str = None

    @classmethod
    def cell(cls, session_id, cell_id, execution_count, generation, code):
        name = f"rushu://{session_id}/{generation}/{quote(cell_id, safe='')}/{execution_count}.ru"
        return cls(name, "cell", cell_id, execution_count, generation,
                   hashlib.sha256(code.encode("utf-8")).hexdigest())

    def metadata(self):
        return {key: value for key, value in asdict(self).items()
                if key != "source_name" and value is not None}


def locate(error, origin):
    """Attach provenance once; an outer call must not overwrite its callee."""
    if origin is not None and not getattr(error, "source_name", None):
        error.source_name = origin.source_name
        error.source_origin = origin
    return error


def at_token(error, token):
    return locate(error, getattr(token, "source_origin", None))


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u2028-\u202e\u2066-\u2069]")


def display_text(value):
    """Escape presentation controls only; preserve navigable raw source fields."""
    short = {"\r": "\\r", "\n": "\\n", "\t": "\\t"}
    return _CONTROL.sub(lambda match: short.get(match[0], f"\\u{ord(match[0]):04x}"), str(value))


def diagnostic(error, source_name="<源码>", origin=None):
    locate(error, origin)
    name = str(getattr(error, "source_name", None) or source_name)
    provenance = getattr(error, "source_origin", None)
    known = getattr(error, "location_known", True)
    line, col = (max(1, error.line), max(1, error.col)) if known else (None, None)
    message = str(error.message)
    # One primary diagnostic per line; provider/compiler multiline detail stays
    # in the structured message and is escaped in the editor-facing header.
    one_line = display_text(message)
    display_name = display_text(name)
    return {"source_name": name, "line": line, "col": col,
            "severity": "error", "category": error.category, "message": message,
            "source": provenance.metadata() if provenance else {"kind": "file"},
            "formatted": (f"{display_name}:{line}:{col}" if known else display_name) + f": error: {display_text(error.category)}：{one_line}"}
