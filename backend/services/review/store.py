"""JSON persistence for review-domain resources.

The W3 service layer keeps storage intentionally small and auditable: each
resource is one JSON file, every write is atomic, and startup scans repair
recoverable in-flight job drift before routes serve state.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable, Mapping
from uuid import uuid4


RUNNING_STATUSES = {"parsing", "running"}
TERMINAL_STATUSES = {"complete", "complete_degraded", "failed", "cancelled"}
COLLECTIONS = (
    "batches",
    "rules",
    "templates",
    "configurations",
    "jobs",
    "findings",
    "decisions",
    "audit",
    "conversations",
    "exports",
    "hitl",
    "idempotency",
    "quarantine",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ReviewStore:
    """Atomic JSON store used by the review API and runner."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        for collection in COLLECTIONS:
            (self.root / collection).mkdir(parents=True, exist_ok=True)

    def startup_drift_scan(self) -> dict[str, list[str]]:
        requeued: list[str] = []
        quarantined: list[str] = []
        for path in sorted(self.root.rglob("*.json")):
            if "quarantine" in path.relative_to(self.root).parts:
                continue
            try:
                record = self._read_path(path)
            except json.JSONDecodeError:
                rel = path.relative_to(self.root).as_posix()
                quarantined.append(rel)
                dest = self.root / "quarantine" / rel.replace("/", "__")
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(dest))
                continue
            if path.parent.name == "jobs" and record.get("status") in RUNNING_STATUSES:
                record["status"] = "queued"
                record["updated_at"] = utc_now()
                record.setdefault("errors", []).append(
                    {"code": "startup_recovered", "message": "running job recovered to queued", "retryable": True}
                )
                self._write_path(path, record)
                requeued.append(str(record.get("id") or path.stem))
        return {"requeued_jobs": requeued, "quarantined_files": quarantined}

    # Generic records -----------------------------------------------------

    def get(self, collection: str, record_id: str) -> dict[str, Any] | None:
        path = self._path(collection, record_id)
        if not path.exists():
            return None
        return self._read_path(path)

    def list(self, collection: str, *, page: int = 1, page_size: int = 50) -> tuple[list[dict[str, Any]], int]:
        records = [self._read_path(path) for path in sorted((self.root / collection).glob("*.json"))]
        records.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        total = len(records)
        start = max(page - 1, 0) * page_size
        return records[start : start + page_size], total

    def put(self, collection: str, record: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(record)
        if not payload.get("id"):
            payload["id"] = str(uuid4())
        now = utc_now()
        payload.setdefault("created_at", now)
        payload["updated_at"] = now
        self._write_path(self._path(collection, str(payload["id"])), payload)
        return payload

    def patch(self, collection: str, record_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        record = self.require(collection, record_id)
        record.update(dict(changes))
        record["updated_at"] = utc_now()
        self._write_path(self._path(collection, record_id), record)
        return record

    def require(self, collection: str, record_id: str) -> dict[str, Any]:
        record = self.get(collection, record_id)
        if record is None:
            raise KeyError(f"{collection} record not found: {record_id}")
        return record

    # Batches -------------------------------------------------------------

    def create_batch(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = {
            "id": str(uuid4()),
            "name": payload.get("name", "Untitled review"),
            "document_type": payload.get("document_type") or payload.get("declared_document_type") or "unknown",
            "ocr_required": bool(payload.get("ocr_required", False)),
            "status": "draft",
            "revision": 0,
            "documents": [],
        }
        return self.put("batches", record)

    def add_batch_document(self, batch_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        batch = self.require("batches", batch_id)
        membership = {
            "id": str(uuid4()),
            "batch_id": batch_id,
            "document_id": payload["document_id"],
            "document_version_id": payload["document_version_id"],
            "filename": payload.get("filename") or payload["document_id"],
            "status": payload.get("status", "ready"),
            "ir": payload.get("ir"),
            "created_at": utc_now(),
        }
        batch.setdefault("documents", []).append(membership)
        batch["revision"] = int(batch.get("revision", 0)) + 1
        self.put("batches", batch)
        return membership

    def remove_batch_document(self, batch_id: str, membership_id: str) -> None:
        batch = self.require("batches", batch_id)
        batch["documents"] = [item for item in batch.get("documents", []) if item.get("id") != membership_id]
        batch["revision"] = int(batch.get("revision", 0)) + 1
        self.put("batches", batch)

    def batch_document(self, batch_id: str, membership_id: str) -> dict[str, Any]:
        batch = self.require("batches", batch_id)
        for item in batch.get("documents", []):
            if item.get("id") == membership_id:
                return dict(item)
        raise KeyError(f"batch membership not found: {membership_id}")

    # Rules/templates/configurations -------------------------------------

    def create_rule(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        rule_id = str(payload.get("rule_id") or uuid4())
        record = {
            "id": str(uuid4()),
            "rule_id": rule_id,
            "name": payload["name"],
            "category": payload.get("category", "general"),
            "version": int(payload.get("version", 1)),
            "severity": payload.get("severity") or payload.get("risk_level") or "medium",
            "definition": payload.get("definition") or {},
            "source_anchor": payload.get("source_anchor"),
            "configurable_fields": payload.get("configurable_fields", []),
            "status": payload.get("status", "published"),
            "llm_fallback": bool(payload.get("llm_fallback", False)),
            "published_at": utc_now(),
        }
        return self.put("rules", record)

    def create_template(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        template_id = str(payload.get("template_id") or uuid4())
        record = {
            "id": str(uuid4()),
            "template_id": template_id,
            "name": payload["name"],
            "category": payload.get("category", "general"),
            "description": payload.get("description", ""),
            "version": int(payload.get("version", 1)),
            "source_version_id": payload["source_version_id"],
            "applicable_document_types": list(payload.get("applicable_document_types") or []),
            "rule_version_ids": list(payload.get("rule_version_ids") or []),
            "status": payload.get("status", "draft"),
            "published_at": None,
        }
        return self.put("templates", record)

    def publish_template(self, template_version_id: str) -> dict[str, Any]:
        template = self.require("templates", template_version_id)
        template["status"] = "published"
        template["published_at"] = utc_now()
        return self.put("templates", template)

    def create_configuration(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        rule_ids = [item.get("rule_version_id") for item in payload.get("rule_selections", [])]
        invalid = [rule_id for rule_id in rule_ids if rule_id and self.get("rules", str(rule_id)) is None]
        record = {
            "id": str(uuid4()),
            "name": payload["name"],
            "rule_selections": list(payload.get("rule_selections") or []),
            "sensitivity": int(payload.get("sensitivity", 50)),
            "analysis_profile_id": payload.get("analysis_profile_id", "accurate"),
            "marking_mode": payload.get("marking_mode", "standard"),
            "invalid_rule_ids": invalid,
            "revision": 0,
        }
        return self.put("configurations", record)

    # Jobs/findings/decisions --------------------------------------------

    def create_analysis_job(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = {
            "id": str(uuid4()),
            "kind": "analysis",
            "status": payload.get("status", "queued"),
            "progress": int(payload.get("progress", 0)),
            "revision": 0,
            "result_revision": 0,
            "decision_revision": 0,
            "batch_id": payload.get("batch_id"),
            "snapshot": payload.get("snapshot") or {},
            "documents": list(payload.get("documents") or []),
            "events": list(payload.get("events") or []),
            "errors": list(payload.get("errors") or []),
            "parent_job_id": payload.get("parent_job_id"),
            "idempotency": payload.get("idempotency") or {},
        }
        return self.put("jobs", record)

    def get_analysis_job(self, job_id: str) -> dict[str, Any] | None:
        return self.get("jobs", job_id)

    def update_analysis_job(self, job_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        job = self.require("jobs", job_id)
        job.update(dict(changes))
        job["revision"] = int(job.get("revision", 0)) + 1
        job["updated_at"] = utc_now()
        self._write_path(self._path("jobs", job_id), job)
        return job

    def append_job_event(self, job_id: str, event: str, data: Any) -> dict[str, Any]:
        job = self.require("jobs", job_id)
        item = {"event": event, "data": data, "created_at": utc_now()}
        job.setdefault("events", []).append(item)
        job["updated_at"] = utc_now()
        self._write_path(self._path("jobs", job_id), job)
        return item

    def create_finding(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = dict(payload)
        record["id"] = str(uuid4())
        record.setdefault("decision", None)
        return self.put("findings", record)

    def list_findings(self, job_id: str) -> list[dict[str, Any]]:
        findings, _ = self.list("findings", page=1, page_size=1000)
        return [item for item in findings if item.get("analysis_job_id") == job_id]

    def find_finding(self, finding_id: str) -> dict[str, Any]:
        return self.require("findings", finding_id)

    def save_finding(self, finding: Mapping[str, Any]) -> dict[str, Any]:
        return self.put("findings", finding)

    def create_decision(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = {
            "id": str(uuid4()),
            "analysis_job_id": payload["analysis_job_id"],
            "finding_id": payload.get("finding_id"),
            "decision_type": payload["decision_type"],
            "comment": payload.get("comment"),
            "revision": int(payload.get("revision", 1)),
        }
        return self.put("decisions", record)

    def append_audit(self, event_type: str, target_type: str, target_id: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        record = {
            "id": str(uuid4()),
            "event_type": event_type,
            "target_type": target_type,
            "target_id": target_id,
            "payload": dict(payload or {}),
            "created_at": utc_now(),
        }
        return self.put("audit", record)

    def list_audit(self, job_id: str, *, page: int = 1, page_size: int = 50) -> tuple[list[dict[str, Any]], int]:
        events, _ = self.list("audit", page=1, page_size=1000)
        selected = [
            item
            for item in events
            if item.get("target_id") == job_id or item.get("payload", {}).get("analysis_job_id") == job_id
        ]
        selected.sort(key=lambda item: str(item.get("created_at", "")))
        total = len(selected)
        start = max(page - 1, 0) * page_size
        return selected[start : start + page_size], total

    # Idempotency ---------------------------------------------------------

    def check_idempotency(self, scope: str, key: str, request_hash: str) -> dict[str, Any] | None:
        return self.get("idempotency", self._idempotency_id(scope, key))

    def record_idempotency(self, scope: str, key: str, request_hash: str, result_id: str) -> dict[str, Any]:
        return self.put(
            "idempotency",
            {"id": self._idempotency_id(scope, key), "scope": scope, "key": key, "request_hash": request_hash, "result_id": result_id},
        )

    # Conversations/exports/HITL -----------------------------------------

    def create_conversation(self, analysis_job_id: str) -> dict[str, Any]:
        return self.put(
            "conversations",
            {"id": str(uuid4()), "analysis_job_id": analysis_job_id, "revision": 0, "messages": []},
        )

    def save_conversation(self, conversation: Mapping[str, Any]) -> dict[str, Any]:
        return self.put("conversations", conversation)

    def create_export(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.put("exports", payload)

    def create_hitl(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.put("hitl", payload)

    # Internals -----------------------------------------------------------

    def _path(self, collection: str, record_id: str) -> Path:
        if collection not in COLLECTIONS:
            raise ValueError(f"unknown review collection: {collection}")
        safe = str(record_id).replace("/", "_").replace("\\", "_")
        return self.root / collection / f"{safe}.json"

    def _read_path(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_path(self, path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def _idempotency_id(self, scope: str, key: str) -> str:
        return stable_hash({"scope": scope, "key": key})


def page(items: Iterable[Mapping[str, Any]], *, page_number: int = 1, page_size: int = 50) -> dict[str, Any]:
    values = [dict(item) for item in items]
    total = len(values)
    start = max(page_number - 1, 0) * page_size
    return {"items": values[start : start + page_size], "total": total, "page": page_number, "page_size": page_size}


__all__ = ["ReviewStore", "TERMINAL_STATUSES", "RUNNING_STATUSES", "page", "stable_hash", "utc_now"]
