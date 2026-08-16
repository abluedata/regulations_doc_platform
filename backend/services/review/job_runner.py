"""Review job runner primitives for degradation, retry, and dead letters."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from concurrent.futures import ThreadPoolExecutor
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
        *,
        on_document_start: Callable[[int, int, Mapping[str, Any]], None] | None = None,
        on_document_result: Callable[[Mapping[str, Any], Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]]], None] | None = None,
    ) -> dict[str, Any]:
        if self.engine is None:
            raise ValueError("run_job requires a ReviewEngine")
        findings: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        snapshots: list[dict[str, Any]] = []
        document_status: dict[str, str] = {}

        try:
            for index, document in enumerate(documents):
                if on_document_start is not None:
                    on_document_start(index, len(documents), dict(document))
                result = self.engine.analyze_document(document, rules)
                findings.extend(result["findings"])
                errors.extend(result.get("errors", []))
                snapshots.append(result["snapshot"])
                document_status[str(document.get("doc_id") or "")] = result["status"]
                if on_document_result is not None:
                    on_document_result(dict(document), list(result["findings"]), list(result.get("errors", [])))
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
                    if on_document_result is not None:
                        on_document_result(dict(document), list(result["findings"]), list(result.get("errors", [])))
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

    def __init__(
        self,
        store: Any,
        engine: ReviewEngine | None = None,
        *,
        suggestion_generator: Callable[[Sequence[Mapping[str, Any]]], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.store = store
        self.engine = engine or ReviewEngine(llm_client=None)
        self.suggestion_generator = suggestion_generator
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="review-analysis")

    def shutdown(self, wait: bool = True) -> None:
        """等待在途分析结束并释放线程池（测试/进程退出前调用）。"""
        self._executor.shutdown(wait=wait)

    def start_analysis(self, job_id: str, documents: Sequence[Mapping[str, Any]], rules: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """异步启动分析：立即返回 queued 状态，进度/发现通过 job.events + SSE 实时推送。"""
        self._transition(job_id, "queued", 5)
        self._executor.submit(self.run_analysis, job_id, documents, rules)
        return self.store.require("jobs", job_id)

    def run_analysis(self, job_id: str, documents: Sequence[Mapping[str, Any]], rules: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """同步执行完整分析（实时反馈路径）：逐文档持久化发现并追加 progress/issues 事件。"""
        total = max(len(documents), 1)
        stored_counts: list[int] = []

        def _emit_document_start(index: int, _total: int, document: Mapping[str, Any]) -> None:
            source = document.get("source") or {}
            filename = source.get("filename") if isinstance(source, Mapping) else None
            doc_id = document.get("doc_id") or document.get("document_id") or ""
            self.store.append_job_event(
                job_id,
                "progress",
                {
                    "status": "running",
                    "progress": 40 + round(55 * index / total),
                    "document_index": index,
                    "document_total": len(documents),
                    "document_id": doc_id,
                    "message": f"正在分析文档 {index + 1}/{len(documents)}：{filename or doc_id or '未命名'}",
                },
            )

        def _persist_document(document: Mapping[str, Any], doc_findings: Sequence[Mapping[str, Any]], _doc_errors: Sequence[Mapping[str, Any]]) -> None:
            findings = list(doc_findings)
            if self.suggestion_generator is not None and findings:
                # 模型能力：根据常规规则为确定性发现生成贴合原文的修改建议（失败时保留规则静态建议）
                try:
                    findings = self.suggestion_generator(findings)
                except Exception:
                    for finding in findings:
                        finding.setdefault("suggestion_source", "rule")
            stored = [self._store_finding(job_id, finding) for finding in findings]
            stored_counts.append(len(stored))
            visible = [finding for finding in stored if not finding.get("suppressed")]
            if visible:
                # 每完成一个文档即推送可见发现；suppressed 结果仅保留用于审计/报告。
                self.store.append_job_event(job_id, "issues", visible)

        runner = ReviewJobRunner(
            self.engine,
            sleeper=lambda _seconds: None,
        )
        try:
            self._transition(job_id, "parsing", 10)
            self._transition(job_id, "running", 40)
            result = runner.run_job(
                job_id,
                documents,
                rules,
                on_document_start=_emit_document_start,
                on_document_result=_persist_document,
            )
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
            self.store.append_job_event(
                job_id,
                "complete",
                {"status": terminal, "finding_count": sum(stored_counts)},
            )
            self.store.append_audit(
                "analysis.completed",
                "analysis_job",
                job_id,
                {"status": terminal, "finding_count": sum(stored_counts)},
            )
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
        """SSE 事件流：先回放已落盘的历史事件，再以 0.5s 间隔尾随新事件直至终态。

        终态（complete/error）yield 后立即结束；客户端断开时 StreamingResponse
        会在下一次 yield 处触发 GeneratorExit，轮询自然终止。
        """
        import json

        _terminal_events = {"complete", "error"}
        seen = 0
        try:
            while True:
                job = self.store.require("jobs", job_id)
                events = list(job.get("events") or [])
                status = job.get("status")
                yielded_terminal = False
                for item in events[seen:]:
                    seen += 1
                    event = item.get("event", "message")
                    data = item.get("data", {})
                    if event in _terminal_events:
                        yielded_terminal = True
                    yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                    if yielded_terminal:
                        return
                # 历史中无终态事件但任务已到终态：合成终态事件补齐（如重启后丢事件/空文档任务）
                if status in {"complete", "complete_degraded"}:
                    yield f"event: complete\ndata: {json.dumps({'status': status}, ensure_ascii=False)}\n\n"
                    return
                if status == "failed":
                    yield f"event: error\ndata: {json.dumps({'message': 'analysis failed'}, ensure_ascii=False)}\n\n"
                    return
                if status == "cancelled":
                    yield f"event: error\ndata: {json.dumps({'message': 'cancelled'}, ensure_ascii=False)}\n\n"
                    return
                if status not in {"complete", "complete_degraded", "failed", "cancelled"}:
                    time.sleep(0.5)
                    continue
                return
        except GeneratorExit:
            return

    def _transition(self, job_id: str, status: str, progress: int) -> None:
        self.store.update_analysis_job(job_id, {"status": status, "progress": progress})
        self.store.append_audit(f"analysis.{status}", "analysis_job", job_id, {"progress": progress})

    def _store_finding(self, job_id: str, finding: Mapping[str, Any]) -> dict[str, Any]:
        job = self.store.require("jobs", job_id)
        snapshot = job.get("snapshot") or {}
        title = finding.get("title") or finding.get("rule_id") or "审查风险"
        evidence = normalize_evidence_anchor(finding.get("evidence") or {}, finding)
        severity = finding.get("severity") or "medium"
        suppressed = (
            str(snapshot.get("marking_mode") or "standard").lower() == "high_only"
            and str(severity).lower() != "high"
        )
        return self.store.create_finding(
            {
                "analysis_job_id": job_id,
                "snapshot_id": snapshot.get("id"),
                "document_id": finding.get("document_id"),
                "document_version_id": finding.get("document_version_id"),
                "rule_version_id": finding.get("rule_version") or finding.get("rule_id"),
                "checker_id": finding.get("confidence"),
                "conclusion": "direct_violation",
                "severity": severity,
                "title": title,
                "reason": finding.get("explanation") or finding.get("quote", ""),
                "suggestion": finding.get("suggested_fix", ""),
                "location_label": str(finding.get("block_id") or finding.get("para_index") or ""),
                "evidence_anchor": evidence,
                "reference_anchor": None,
                "conflict_group_id": None,
                "suppressed": suppressed,
                "quote": finding.get("quote", ""),
                "quote_hash": finding.get("quote_hash"),
                "suggestion_source": finding.get("suggestion_source", "rule"),
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
