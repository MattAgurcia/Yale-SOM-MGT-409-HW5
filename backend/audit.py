"""Append-only audit trail for the agent team: output/audit_trail.json.

Every agent-loop step is appended as one JSON object as it happens: run
start and end, each agent's start and end, every model request (what the
model asked for, finish reason, tokens), every tool call (arguments, result,
time), and every delegation between agents.

The file is a JSON array that only grows. Entries are never removed or
rewritten. A file that is not valid JSON is renamed aside, never overwritten.
Set CAMPUS_AUDIT_PATH to write somewhere else (e.g. for tests).
"""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

try:
    import fcntl  # cross-process lock on macOS / Linux
except ImportError:  # Windows: the in-process lock still applies; run one backend process at a time
    fcntl = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = "output/audit_trail.json"
MAX_TEXT = 4000  # longer strings are clipped, and marked as clipped


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def clip(value: Any, limit: int = MAX_TEXT) -> Any:
    """Make a value JSON-safe and keep long text from bloating the trail."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): clip(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clip(v, limit) for v in value]
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"... [clipped, {len(value)} chars]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return clip(str(value), limit)


class AuditTrail:
    def __init__(self, path: str | Path | None = None) -> None:
        path = Path(path or os.environ.get("CAMPUS_AUDIT_PATH") or DEFAULT_PATH)
        self.path = path if path.is_absolute() else PROJECT_ROOT / path
        self._lock = threading.Lock()

    def append(self, event: str, **fields: Any) -> dict[str, Any]:
        entry = {"ts": _now(), "event": event, **{k: clip(v) for k, v in fields.items() if v is not None}}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        # Thread lock for this process, file lock for any other process writing too.
        with self._lock, open(lock_path, "a") as lock:
            if fcntl is not None:
                fcntl.flock(lock, fcntl.LOCK_EX)
            entries = self._read()
            entry = {"seq": len(entries) + 1, **entry}
            entries.append(entry)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text("[\n" + ",\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n]\n", encoding="utf-8")
            os.replace(tmp, self.path)  # atomic: readers see the old file or the new one, never half
        return entry

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        # Never overwrite a trail we cannot read: keep it under a new name and start a new one.
        aside = self.path.with_name(f"{self.path.stem}.unreadable-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.json")
        self.path.rename(aside)
        return [{"seq": 1, "ts": _now(), "event": "audit_file_set_aside", "moved_to": aside.name}]
