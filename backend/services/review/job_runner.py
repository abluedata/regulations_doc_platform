"""Review job runner primitives for degradation, retry, and dead letters."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from threading import Lock
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from .engine import LLMUnavailableError, ReviewEngine


class TransientReviewError(RuntimeError):
    """Retryable chunk/rule failure."""


class PermanentReviewError(RuntimeError):
    """Non-retryable chunk/rule failure."""


class CapacityExceeded(RuntimeError):
    """Admission rejected by a review capacity boundary."""


class CapacityGovernor:
    """Thread-safe FIFO admission with bounded concurrency, queue, and rate."""

    def __init__(self, *, max_concurrent: int, max_queued: int, rate_limit: int, rate_window_seconds: float) -> None:
        if min(max_concurrent, rate_limit) < 1 or max_queued < 0 or rate_window_seconds <= 0:
            raise ValueError("capacity limits must be positive")
        self.max_concurrent = max_concurrent
        self.max_queued = max_queued
        self.rate_limit = rate_limit
        self.rate_window_seconds = rate_window_seconds
        self._running: set[str] = set()
        self._queued: deque[str] = deque()
        self._admissions: deque[float] = deque()
        self._lock = Lock()

    def admit(self, job_id: str, *, now: float | None = None) -> str:
        timestamp = time.monotonic() if now is None else now
        with self._lock:
            cutoff = timestamp - self.rate_window_seconds
            while self._admissions and self._admissions[0] <= cutoff:
                self._admissions.popleft()
            if len(self._admissions) >= self.rate_limit:
                raise CapacityExceeded("review rate limit exceeded")
            if job_id in self._running:
                return "running"
            if job_id in self._queued:
                return "queued"
            if len(self._running) < self.max_concurrent:
                self._running.add(job_id)
                state = "running"
            elif len(self._queued) < self.max_queued:
                self._queued.append(job_id)
                state = "queued"
            else:
                raise CapacityExceeded("review queue capacity exceeded")
            self._admissions.append(timestamp)
            return state

    def complete(self, job_id: str) -> str | None:
        with self._lock:
            self._running.discard(job_id)
            if not self._queued:
                return None
            next_job = self._queued.popleft()
            self._running.add(next_job)
            return next_job

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "running": len(self._running),
                "queued": len(self._queued),
                "max_concurrent": self.max_concurrent,
                "max_queued": self.max_queued,
            }


@dataclass(frozen=True)
class ChunkRuleTask:
    job_id: str
    document_id: str
    chunk_id: str
    rule_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeadLetter:
    job_id: str
    document_id: str
    chunk_id: str
    rule_id: str
    attempts: int
    error: str
    retryable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "rule_id": self.rule_id,
            "attempts": self.attempts,
            "error": self.error,
            "retryable": self.retryable,
        }


Processor = Callable[[ChunkRuleTask], Sequence[Mapping[str, Any]]]


class ReviewJobRunner:
    """Small single-process runner boundary used by review jobs.

    It intentionally keeps persistence pluggable.  The in-memory idempotency map
    mirrors the required storage invariant: one result per job/chunk/rule key.
    """

    def __init__(
        self,
        engine: ReviewEngine | None = None,
        *,
        max_retries: int = 2,
        backoff_base_seconds: float = 0.05,
        sleeper: Callable[[float], None] | None = None,
        metrics_registry: Any | None = None,
    ) -> None:
        if max_retries < 0 or max_retries > 2:
            raise ValueError("max_retries must be between 0 and 2")
        self.engine = engine
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.sleeper = sleeper or time.sleep
        self.metrics_registry = metrics_registry
        self._completed: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

    def run_job(
        self,
        job_id: str,
        documents: Sequence[Mapping[str, Any]],
        rules: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if self.engine is None:
            raise ValueError("run_job requires a ReviewEngine")
        findings: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        snapshots: list[dict[str, Any]] = []
        document_status: dict[str, str] = {}

        try:
            for document in documents:
                result = self.engine.analyze_document(document, rules)
                findings.extend(result["findings"])
                errors.extend(result.get("errors", []))
                snapshots.append(result["snapshot"])
                document_status[str(document.get("doc_id") or "")] = result["status"]
        except LLMUnavailableError as exc:
            findings.clear()
            errors = [{"code": "llm_unavailable", "message": str(exc), "retryable": True}]
            snapshots.clear()
            document_status.clear()
            for document in documents:
                try:
                    result = self.engine.analyze_document(document, rules, allow_llm=False)
                    findings.extend(result["findings"])
                    snapshots.append(result["snapshot"])
                    document_status[str(document.get("doc_id") or "")] = "complete_degraded"
                except Exception as doc_exc:  # isolate single-document failures
                    document_status[str(document.get("doc_id") or "")] = "failed"
                    errors.append(
                        {
                            "code": "document_failed",
                            "document_id": document.get("doc_id"),
                            "message": str(doc_exc),
                            "retryable": True,
                        }
                    )
            return {
                "job_id": job_id,
                "status": "complete_degraded",
                "findings": findings,
                "errors": errors,
                "dead_letters": [],
                "document_status": document_status,
                "snapshots": snapshots,
            }
        except Exception as exc:
            errors.append({"code": "job_failed", "message": str(exc), "retryable": True})

        status = "completed" if not errors else "partial_failed"
        return {
            "job_id": job_id,
            "status": status,
            "findings": findings,
            "errors": errors,
            "dead_letters": [],
            "document_status": document_status,
            "snapshots": snapshots,
        }

    def run_tasks(
        self,
        job_id: str,
        tasks: Sequence[ChunkRuleTask],
        processor: Processor,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        findings: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        dead_letters: list[dict[str, Any]] = []
        attempts_by_key: dict[str, int] = {}

        for task in tasks:
            key = (job_id, task.chunk_id, task.rule_id)
            key_label = f"{task.chunk_id}:{task.rule_id}"
            if key in self._completed:
                findings.extend(self._completed[key])
                attempts_by_key[key_label] = 0
                continue

            task_findings, dead_letter, attempts = self._process_with_retry(task, processor)
            attempts_by_key[key_label] = attempts
            if dead_letter:
                record = dead_letter.to_dict()
                dead_letters.append(record)
                errors.append(
                    {
                        "code": "chunk_rule_dead_letter",
                        "chunk_id": task.chunk_id,
                        "rule_id": task.rule_id,
                        "message": dead_letter.error,
                        "retryable": dead_letter.retryable,
                    }
                )
                continue
            self._completed[key] = task_findings
            findings.extend(task_findings)

        result = {
            "job_id": job_id,
            "status": "completed" if not errors else "partial_failed",
            "findings": findings,
            "errors": errors,
            "dead_letters": dead_letters,
            "attempts": attempts_by_key,
        }
        if self.metrics_registry is not None:
            self.metrics_registry.record_job(
                status=result["status"],
                duration_ms=(time.perf_counter() - started) * 1000,
                error_count=len(errors),
                dead_letter_count=len(dead_letters),
            )
        return result

    def _process_with_retry(
        self,
        task: ChunkRuleTask,
        processor: Processor,
    ) -> tuple[list[dict[str, Any]], DeadLetter | None, int]:
        attempts = 0
        while attempts <= self.max_retries:
            attempts += 1
            try:
                return [dict(item) for item in processor(task)], None, attempts
            except PermanentReviewError as exc:
                return [], DeadLetter(
                    task.job_id,
                    task.document_id,
                    task.chunk_id,
                    task.rule_id,
                    attempts,
                    str(exc),
                    retryable=False,
                ), attempts
            except TransientReviewError as exc:
                if attempts > self.max_retries:
                    return [], DeadLetter(
                        task.job_id,
                        task.document_id,
                        task.chunk_id,
                        task.rule_id,
                        attempts,
                        str(exc),
                        retryable=True,
                    ), attempts
                self.sleeper(self.backoff_base_seconds * (2 ** (attempts - 1)))
        raise AssertionError("unreachable retry state")


class PersistentReviewQueue:
    """Synchronous durable queue boundary for W3 route tests and local runtime.

    The class records every state transition into the JSON store so a server
    restart can replay authoritative status and SSE history from disk.
    """

    def __init__(self, store: Any, engine: ReviewEngine | None = None) -> None:
        self.store = store
        self.engine = engine or ReviewEngine(llm_client=None)

    def run_analysis(self, job_id: str, documents: Sequence[Mapping[str, Any]], rules: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        self._transition(job_id, "parsing", 10)
        self._transition(job_id, "running", 40)
        runner = ReviewJobRunner(self.engine, sleeper=lambda _seconds: None)
        try:
            result = runner.run_job(job_id, documents, rules)
            findings = [self._store_finding(job_id, finding) for finding in result.get("findings", [])]
            self.store.append_job_event(job_id, "issues", findings)
            terminal = "complete_degraded" if result.get("status") == "complete_degraded" else "complete"
            job = self.store.update_analysis_job(
                job_id,
                {
                    "status": terminal,
                    "progress": 100,
                    "errors": result.get("errors", []),
                    "result_revision": 1,
                    "documents": [
                        {
                            "id": str(doc.get("doc_id") or doc.get("document_id") or index),
                            "document_id": doc.get("doc_id") or doc.get("document_id"),
                            "document_version_id": doc.get("document_version_id") or doc.get("version_id"),
                            "status": terminal,
                            "progress": 100,
                            "attempt": 1,
                            "error": None,
                        }
                        for index, doc in enumerate(documents)
                    ],
                },
            )
            self.store.append_job_event(job_id, "complete", {"status": terminal, "finding_count": len(findings)})
            self.store.append_audit("analysis.completed", "analysis_job", job_id, {"status": terminal, "finding_count": len(findings)})
            return job
        except Exception as exc:
            self.store.append_job_event(job_id, "error", {"message": str(exc)})
            self.store.append_audit("analysis.failed", "analysis_job", job_id, {"error": str(exc)})
            return self.store.update_analysis_job(
                job_id,
                {
                    "status": "failed",
                    "progress": 100,
                    "errors": [{"code": "analysis_failed", "message": str(exc), "retryable": True}],
                },
            )

    def retry_failed_chunks(self, parent_job_id: str) -> dict[str, Any]:
        parent = self.store.require("jobs", parent_job_id)
        child = self.store.create_analysis_job(
            {
                "parent_job_id": parent_job_id,
                "batch_id": parent.get("batch_id"),
                "snapshot": parent.get("snapshot") or {},
                "documents": [doc for doc in parent.get("documents", []) if doc.get("status") == "failed"],
                "events": [],
            }
        )
        self.store.append_audit("analysis.retry_created", "analysis_job", parent_job_id, {"child_job_id": child["id"]})
        return child

    def cancel(self, job_id: str) -> dict[str, Any]:
        self.store.append_job_event(job_id, "error", {"message": "cancelled"})
        self.store.append_audit("analysis.cancelled", "analysis_job", job_id)
        return self.store.update_analysis_job(job_id, {"status": "cancelled", "progress": 100})

    def sse_events(self, job_id: str) -> Iterable[str]:
        import json

        job = self.store.require("jobs", job_id)
        events = list(job.get("events") or [])
        if not events:
            events = [{"event": "issues", "data": []}]
        terminal_count = 0
        for item in events:
            event = item.get("event", "message")
            if event in {"complete", "error"}:
                terminal_count += 1
                if terminal_count > 1:
                    continue
            data = item.get("data", {})
            yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        if terminal_count == 0 and job.get("status") in {"complete", "complete_degraded"}:
            yield f"event: complete\ndata: {json.dumps({'status': job.get('status')}, ensure_ascii=False)}\n\n"
        elif terminal_count == 0 and job.get("status") == "failed":
            yield f"event: error\ndata: {json.dumps({'message': 'analysis failed'}, ensure_ascii=False)}\n\n"

    def _transition(self, job_id: str, status: str, progress: int) -> None:
        self.store.update_analysis_job(job_id, {"status": status, "progress": progress})
        self.store.append_audit(f"analysis.{status}", "analysis_job", job_id, {"progress": progress})

    def _store_finding(self, job_id: str, finding: Mapping[str, Any]) -> dict[str, Any]:
        job = self.store.require("jobs", job_id)
        snapshot = job.get("snapshot") or {}
        title = finding.get("title") or finding.get("rule_id") or "审查风险"
        evidence = normalize_evidence_anchor(finding.get("evidence") or {}, finding)
        return self.store.create_finding(
            {
                "analysis_job_id": job_id,
                "snapshot_id": snapshot.get("id"),
                "document_id": finding.get("document_id"),
                "document_version_id": finding.get("document_version_id"),
                "rule_version_id": finding.get("rule_version") or finding.get("rule_id"),
                "checker_id": finding.get("confidence"),
                "conclusion": "direct_violation",
                "severity": finding.get("severity", "medium"),
                "title": title,
                "reason": finding.get("explanation") or finding.get("quote", ""),
                "suggestion": finding.get("suggested_fix", ""),
                "location_label": str(finding.get("block_id") or finding.get("para_index") or ""),
                "evidence_anchor": evidence,
                "reference_anchor": None,
                "conflict_group_id": None,
                "suppressed": False,
                "quote": finding.get("quote", ""),
                "quote_hash": finding.get("quote_hash"),
                "decision": None,
            }
        )


def normalize_evidence_anchor(anchor: Mapping[str, Any], finding: Mapping[str, Any]) -> dict[str, Any]:
    kind = anchor.get("kind") or "docx"
    if kind == "pdf":
        return {
            "kind": "pdf",
            "document_id": finding.get("document_id", ""),
            "document_version_id": finding.get("document_version_id", ""),
            "precision": "exact" if anchor.get("rects") else "page",
            "quote": anchor.get("quote") or finding.get("quote") or "",
            "quote_sha256": anchor.get("quote_sha256") or anchor.get("quote_hash") or finding.get("quote_hash") or "",
            "validation_status": "valid" if anchor.get("precision") == "exact" else "degraded",
            "page_number": anchor.get("page_number") or 1,
            "coordinate_space": "normalized-1000-top-left",
            "rects": anchor.get("rects") or [],
            "block_ids": [value for value in [anchor.get("source_block_id") or finding.get("block_id")] if value],
        }
    text_range = anchor.get("text_range") or {}
    return {
        "kind": "docx",
        "document_id": finding.get("document_id", ""),
        "document_version_id": finding.get("document_version_id", ""),
        "precision": anchor.get("precision", "exact"),
        "quote": anchor.get("quote") or finding.get("quote") or "",
        "quote_sha256": anchor.get("quote_sha256") or anchor.get("quote_hash") or finding.get("quote_hash") or "",
        "validation_status": "valid",
        "container_kind": anchor.get("container_kind", "paragraph"),
        "locator_id": anchor.get("locator_id") or "",
        "document_order": anchor.get("document_order") or anchor.get("para_index") or 0,
        "start": text_range.get("start", 0),
        "end": text_range.get("end", max(1, len(str(anchor.get("quote") or finding.get("quote") or "")))),
        "block_id": anchor.get("block_id") or finding.get("block_id") or "",
    }


__all__ = [
    "ChunkRuleTask",
    "CapacityExceeded",
    "CapacityGovernor",
    "DeadLetter",
    "PermanentReviewError",
    "PersistentReviewQueue",
    "ReviewJobRunner",
    "TransientReviewError",
    "normalize_evidence_anchor",
]
