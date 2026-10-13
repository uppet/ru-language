"""Bounded, memory-only public diagnostics. Never retain request/config objects."""
from datetime import datetime, timezone
import json
import re
import threading
import time
from urllib.parse import quote

MAX_EVENTS = 64
MAX_EVENT_BYTES = 1024 * 1024
MAX_TRACE_BYTES = 2 * 1024 * 1024


class GenerationTrace:
    def __init__(self, generation_id):
        self.generation_id = generation_id
        self.started = time.monotonic()
        self._lock = threading.RLock()
        self._secrets = ()
        self._events = []
        self._bytes = 0
        self.truncated = False
        self.complete = False
        self.cleared = False

    def protect(self, secret):
        with self._lock:
            if self.complete or self.cleared:
                return
            self._secrets = tuple({secret, quote(secret, safe=""),
                                   json.dumps(secret, ensure_ascii=True)[1:-1]}) if secret else ()

    def redact(self, value):
        value = str(value)
        for secret in sorted(self._secrets, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"\b[a-z][a-z0-9+.-]{0,31}://[^\s<>\"']+", "[URL REDACTED]", value, flags=re.I)
        value = re.sub(r"(?im)(?:authorization|proxy-authorization|set-cookie|cookie)\s*[\"']?\s*[:=][^\r\n]*", "[AUTH REDACTED]", value)
        value = re.sub(r"(?i)(?:bearer\s+)[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", value)
        value = re.sub(r"(?i)(?:api[-_]?key|access[-_]?token|password|secret)\s*[\"']?\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)", "[CREDENTIAL REDACTED]", value)
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[REDACTED]", value)
        return value

    def emit(self, stage, detail, text=None):
        with self._lock:
            if self.complete or self.cleared:
                return
            if len(self._events) >= MAX_EVENTS - 1 and not stage.startswith("final_"):
                self.truncated = True
                return
            event = {"seq": len(self._events) + 1, "stage": stage,
                     "time": datetime.now(timezone.utc).isoformat(),
                     "elapsed_ms": round((time.monotonic() - self.started) * 1000),
                     "detail": self.redact(detail)[:1024]}
            if text is not None:
                safe = self.redact(text).encode("utf-8", errors="replace")
                available = min(MAX_EVENT_BYTES, max(0, MAX_TRACE_BYTES - self._bytes))
                event["text"] = safe[:available].decode("utf-8", errors="ignore")
                event["truncated"] = len(safe) > available
                self.truncated |= event["truncated"]
                self._bytes += len(event["text"].encode("utf-8"))
            self._events.append(event)
            if stage.startswith("final_"):
                self.complete = True
                self._secrets = ()

    def snapshot(self, after=0):
        with self._lock:
            return {"schema_version": 1, "generation_id": self.generation_id,
                    "events": [dict(e) for e in self._events if e["seq"] > after],
                    "complete": self.complete, "truncated": self.truncated,
                    "limits": {"events": MAX_EVENTS, "event_bytes": MAX_EVENT_BYTES,
                               "text_bytes": MAX_TRACE_BYTES}}

    def clear(self):
        with self._lock:
            self.cleared = True
            self.complete = True
            self._events.clear()
            self._secrets = ()


class TraceStore:
    """Per-server: eight 2MiB text budgets plus bounded event metadata."""
    def __init__(self):
        self._lock = threading.Lock()
        self._traces = {}
        self._claimed = {}
        self._precleared = set()

    def _prune(self):
        for identifier, started in list(self._claimed.items()):
            if time.monotonic() - started > 3600:
                del self._claimed[identifier]
                self._precleared.discard(identifier)
        for identifier, trace in list(self._traces.items()):
            if time.monotonic() - trace.started > 3600:
                self._traces.pop(identifier).clear()

    def create(self, identifier):
        with self._lock:
            self._prune()
            if identifier in self._precleared:
                # Preserve the paid-request semantics of an already sent POST:
                # clearing logs does not cancel generation, even in this race.
                self._precleared.remove(identifier)
                trace = GenerationTrace(identifier)
                trace.clear()
                return trace
            if identifier in self._claimed or len(self._claimed) >= 1024:
                raise ValueError("duplicate generation id")
            while len(self._traces) >= 8:
                expired = next((key for key, value in self._traces.items() if value.complete), None)
                if expired is None:
                    raise ValueError("trace capacity reached")
                self._traces.pop(expired).clear()
            trace = GenerationTrace(identifier)
            self._traces[identifier] = trace
            self._claimed[identifier] = trace.started
            return trace

    def get(self, identifier):
        with self._lock:
            self._prune()
            return self._traces.get(identifier)

    def delete(self, identifier):
        with self._lock:
            self._prune()
            # A cancel/clear may race the POST arriving at this server.
            # Claim even a not-yet-created id so a late POST cannot resurrect it.
            if identifier not in self._claimed and len(self._claimed) < 1024:
                self._claimed[identifier] = time.monotonic()
                self._precleared.add(identifier)
            trace = self._traces.pop(identifier, None)
            if trace:
                trace.clear()
