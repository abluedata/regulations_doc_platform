"""Append-only, hash chained audit event writer."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from core.config import DATA_ROOT


class AuditWriter:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or DATA_ROOT / "audit.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _read_verified(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        previous = "0" * 64
        for expected_seq, event in enumerate(events, 1):
            if event.get("seq") != expected_seq or event.get("previous_hash") != previous:
                raise ValueError("audit chain integrity check failed")
            supplied = event.get("hash")
            body = {key: value for key, value in event.items() if key != "hash"}
            canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            if supplied != hashlib.sha256(canonical.encode("utf-8")).hexdigest():
                raise ValueError("audit chain integrity check failed")
            previous = str(supplied)
        return events

    def _last(self) -> tuple[int, str]:
        events = self._read_verified()
        if not events:
            return 0, "0" * 64
        return int(events[-1]["seq"]), str(events[-1]["hash"])

    def append(self, action: str, *, actor: str = "system", request_id: str | None = None, **data: Any) -> dict[str, Any]:
        with self._lock:
            seq, previous_hash = self._last()
            event = {
                "seq": seq + 1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": action,
                "actor": actor,
                "request_id": request_id,
                "data": data,
                "previous_hash": previous_hash,
            }
            canonical = json.dumps(event, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            event["hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return event

    def export(self) -> list[dict[str, Any]]:
        """Read events without exposing a mutation handle."""
        with self._lock:
            return [dict(e) for e in self._read_verified()]


_default_writer = AuditWriter()


def audit(action: str, **data: Any) -> dict[str, Any]:
    return _default_writer.append(action, **data)


def export_audit() -> Iterable[dict[str, Any]]:
    return iter(_default_writer.export())
