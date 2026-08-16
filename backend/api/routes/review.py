"""Review-domain API routes for batches, rules, jobs, HITL, reports, and QA."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from fastapi import APIRouter, Header, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse, StreamingResponse

from api.review_schemas import (
    AddBatchDocumentRequest,
    ConfigurationWrite,
    CreateBatchRequest,
    CreateConversationRequest,
    CreateExportRequest,
    CreateRuleRequest,
    CreateTemplateVersionRequest,
    FindingDecisionWrite,
    OverallDecisionWrite,
    ResumeDecisionRequest,
    RetryAnalysisRequest,
    ReviewStreamRequest,
    StartAnalysisRequest,
    StartDecisionRequest,
    StopRequest,
    UpdateBatchRequest,
)
from core.config import DATA_ROOT
from services.knowledge import document_store
from services.common import evidence_spans
from services.review.assistant import ReviewAssistant
from services.review.hitl import HitlDecisionMachine
from services.review.job_runner import PersistentReviewQueue
from services.review.report import create_markdown_artifact
from services.review.store import ReviewStore, page, stable_hash, utc_now
from services.review.suggestions import generate_suggestions


router = APIRouter(prefix="/review", tags=["review"])

_store = ReviewStore(Path(DATA_ROOT) / "platform.db")
_queue = PersistentReviewQueue(_store, suggestion_generator=generate_suggestions)
_assistant = ReviewAssistant(_store)
_hitl = HitlDecisionMachine(_store)


def configure_for_tests(store: ReviewStore) -> None:
    global _store, _queue, _assistant, _hitl
    _queue.shutdown(wait=True)
    _store = store
    _queue = PersistentReviewQueue(_store)
    _assistant = ReviewAssistant(_store)
    _hitl = HitlDecisionMachine(_store)


def startup_drift_scan() -> dict[str, list[str]]:
    return _store.startup_drift_scan()


@router.post("/rules", status_code=201)
def create_rule(body: CreateRuleRequest):
    return _store.create_rule(body.model_dump())


@router.get("/rules")
def list_rules(
    page_number: int = Query(1, alias="page", ge=1),
    page_size: int = Query(50, ge=1, le=200),
    category: str | None = None,
    q: str | None = None,
):
    items, _ = _store.list("rules", page=1, page_size=1000)
    # 每逻辑规则只返回最新版本（历史版本供已启动/已完成任务快照使用）
    latest_by_rule: dict[str, dict[str, Any]] = {}
    for item in items:
        key = str(item.get("rule_id") or item["id"])
        current = latest_by_rule.get(key)
        if current is None or int(item.get("version", 1)) > int(current.get("version", 1)):
            latest_by_rule[key] = item
    items = sorted(latest_by_rule.values(), key=lambda item: str(item.get("created_at") or ""))
    if category:
        items = [item for item in items if item.get("category") == category]
    if q:
        needle = q.lower()
        items = [item for item in items if needle in str(item.get("name", "")).lower()]
    return page(items, page_number=page_number, page_size=page_size)


@router.put("/rules/{rule_version_id}", status_code=200)
def update_rule(rule_version_id: str, body: CreateRuleRequest):
    """修改规则产生新版本（FR-018）：旧版本保持不可变，新版本发布。"""
    _require("rules", rule_version_id)
    updated = _store.create_rule_version(rule_version_id, body.model_dump(exclude_none=True))
    _store.append_audit(
        "rule.version_created",
        "rule",
        updated["id"],
        {"rule_id": updated.get("rule_id"), "version": updated.get("version"), "based_on": rule_version_id},
    )
    return updated


@router.get("/rule-versions/{rule_version_id}")
def get_rule(rule_version_id: str):
    return _require("rules", rule_version_id)


@router.delete("/rules/{rule_version_id}", status_code=204)
def delete_rule(rule_version_id: str):
    rule = _require("rules", rule_version_id)
    _store.delete_record("rules", rule_version_id)
    _store.append_audit("rule.deleted", "rule", rule_version_id, {"rule_id": rule.get("rule_id"), "name": rule.get("name")})
    return Response(status_code=204)


@router.post("/templates", status_code=201)
def create_template(body: CreateTemplateVersionRequest):
    _require_rules(body.rule_version_ids)
    return _store.create_template(body.model_dump())


@router.get("/templates")
def list_templates(page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(50, ge=1, le=200), status: str | None = None):
    items, _ = _store.list("templates", page=1, page_size=1000)
    if status:
        items = [item for item in items if item.get("status") == status]
    return page(items, page_number=page_number, page_size=page_size)


@router.get("/template-versions/{template_version_id}")
def get_template(template_version_id: str):
    return _require("templates", template_version_id)


@router.post("/template-versions/{template_version_id}/publish")
def publish_template(template_version_id: str, idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    return _idempotent("template_publish", idempotency_key, {"template_version_id": template_version_id}, lambda: _store.publish_template(template_version_id))


@router.post("/configurations", status_code=201)
def create_configuration(body: ConfigurationWrite):
    return _store.create_configuration(body.model_dump())


@router.get("/configurations")
def list_configurations(page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(50, ge=1, le=200)):
    items, _ = _store.list("configurations", page=1, page_size=1000)
    return page(items, page_number=page_number, page_size=page_size)


@router.put("/configurations/{configuration_id}")
def update_configuration(configuration_id: str, body: ConfigurationWrite, if_match: str | None = Header(None, alias="If-Match")):
    current = _require("configurations", configuration_id)
    _check_revision(current, if_match)
    payload = body.model_dump()
    payload.update({"id": configuration_id, "revision": int(current.get("revision", 0)) + 1})
    return _store.put("configurations", payload)


@router.post("/batches", status_code=201)
def create_batch(body: CreateBatchRequest):
    batch = _store.create_batch(body.model_dump())
    _store.append_audit("batch.created", "batch", batch["id"])
    return batch


@router.get("/batches")
def list_batches(page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(50, ge=1, le=200)):
    items, _ = _store.list("batches", page=1, page_size=1000)
    return page(items, page_number=page_number, page_size=page_size)


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str):
    return _require("batches", batch_id)


@router.patch("/batches/{batch_id}")
def update_batch(batch_id: str, body: UpdateBatchRequest, if_match: str | None = Header(None, alias="If-Match")):
    batch = _require("batches", batch_id)
    _check_revision(batch, if_match)
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    changes["revision"] = int(batch.get("revision", 0)) + 1
    return _store.patch("batches", batch_id, changes)


@router.post("/batches/{batch_id}/documents", status_code=201)
def add_batch_document(batch_id: str, body: AddBatchDocumentRequest):
    membership = _store.add_batch_document(batch_id, body.model_dump())
    _store.append_audit("batch.document_added", "batch", batch_id, {"membership_id": membership["id"]})
    return membership


@router.delete("/batches/{batch_id}/documents/{membership_id}", status_code=204)
def remove_batch_document(batch_id: str, membership_id: str):
    _store.remove_batch_document(batch_id, membership_id)
    return Response(status_code=204)


@router.get("/batches/{batch_id}/template-suggestions")
def template_suggestions(batch_id: str):
    _require("batches", batch_id)
    templates, _ = _store.list("templates", page=1, page_size=1000)
    return page([{"template_version_id": item["id"], "confidence": 0.5, "reason": "category match"} for item in templates])


@router.post("/analysis-jobs", status_code=202)
def start_analysis(body: StartAnalysisRequest, idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    request_payload = body.model_dump()
    request_hash = stable_hash(request_payload)
    if idempotency_key:
        existing = _store.check_idempotency("analysis", idempotency_key, request_hash)
        if existing:
            if existing.get("request_hash") != request_hash:
                raise HTTPException(status_code=409, detail="idempotency key reused with different payload")
            return _job_response(_require("jobs", existing["result_id"]))

    batch = _require("batches", body.batch_id)
    docs = [_store.batch_document(body.batch_id, membership_id) for membership_id in body.document_membership_ids]
    configuration: dict[str, Any] | None = None
    if body.configuration_id:
        # 优先根据已有配置进行审查：配置内的规则选择、灵敏度、分析方案与标记模式为准
        configuration = _require("configurations", body.configuration_id)
        selections = list(configuration.get("rule_selections") or [])
        invalid_ids = [
            str(selection.get("rule_version_id"))
            for selection in selections
            if selection.get("rule_version_id") and _store.get("rules", str(selection.get("rule_version_id"))) is None
        ]
        if invalid_ids:
            raise HTTPException(
                status_code=409,
                detail={"code": "invalid_configuration_rules", "rule_version_ids": invalid_ids},
            )
        rules = [
            _engine_rule(_require("rules", str(selection.get("rule_version_id"))), selection.get("overrides"))
            for selection in selections
            if selection.get("enabled", True)
        ]
    else:
        rules = [_engine_rule(_require("rules", selection.rule_version_id), selection.overrides) for selection in body.rule_selections if selection.enabled]
    snapshot = _snapshot(body, docs, rules, configuration=configuration)
    job = _store.create_analysis_job(
        {
            "batch_id": body.batch_id,
            "snapshot": snapshot,
            "documents": [
                {
                    "id": doc["id"],
                    "document_id": doc["document_id"],
                    "document_version_id": doc["document_version_id"],
                    "status": "queued",
                    "progress": 0,
                    "attempt": 0,
                    "error": None,
                }
                for doc in docs
            ],
            "events": [],
            "idempotency": {"key": idempotency_key, "request_hash": request_hash},
        }
    )
    if idempotency_key:
        _store.record_idempotency("analysis", idempotency_key, request_hash, job["id"])
    _store.append_audit("analysis.created", "analysis_job", job["id"], {"batch_id": batch["id"]})
    documents = [_document_ir(doc) for doc in docs]
    # 异步执行：POST 立即返回 202，进度/发现经 SSE 实时推送
    job = _queue.start_analysis(job["id"], documents, rules)
    return _job_response(job)


@router.get("/analysis-jobs")
def list_analysis_jobs(page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(50, ge=1, le=200), batch_id: str | None = None):
    items, _ = _store.list("jobs", page=1, page_size=1000)
    if batch_id:
        items = [item for item in items if item.get("batch_id") == batch_id]
    return page([_job_response(item) for item in items], page_number=page_number, page_size=page_size)


@router.get("/analysis-jobs/{job_id}")
def get_analysis_job(job_id: str):
    return _job_response(_require("jobs", job_id))


@router.get("/analysis-jobs/{job_id}/stream")
def analysis_stream(job_id: str):
    _require("jobs", job_id)
    return StreamingResponse(_queue.sse_events(job_id), media_type="text/event-stream")


@router.get("/analysis-jobs/{job_id}/findings")
def list_findings(job_id: str, page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(50, ge=1, le=200), include_suppressed: bool = False):
    _require("jobs", job_id)
    findings = _store.list_findings(job_id)
    findings = [_enrich_finding_anchor(item) for item in findings]
    if not include_suppressed:
        findings = [item for item in findings if not item.get("suppressed")]
    counts: dict[str, int] = {}
    for item in findings:
        counts[item.get("severity", "unknown")] = counts.get(item.get("severity", "unknown"), 0) + 1
    current = _store.require("jobs", job_id)
    payload = page(findings, page_number=page_number, page_size=page_size)
    payload.update({"result_revision": current.get("result_revision", 0), "counts": counts})
    return payload


def _enrich_finding_anchor(finding: Mapping[str, Any]) -> dict[str, Any]:
    """用 evidence_spans 回填真实 evidence_anchor；失败时保持退化现状。"""
    try:
        return evidence_spans.enrich_evidence_anchor(dict(finding))
    except Exception:
        return dict(finding)


@router.post("/analysis-jobs/{job_id}/retries", status_code=202)
def retry_analysis(job_id: str, body: RetryAnalysisRequest | None = None, idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    _require("jobs", job_id)
    return _job_response(_queue.retry_failed_chunks(job_id))


@router.put("/findings/{finding_id}/decision")
def put_finding_decision(finding_id: str, body: FindingDecisionWrite, if_match: str | None = Header(None, alias="If-Match")):
    finding = _store.find_finding(finding_id)
    job = _store.require("jobs", finding["analysis_job_id"])
    _check_revision(job, if_match, field="decision_revision")
    revision = int(job.get("decision_revision", 0)) + 1
    decision = _store.create_decision({**body.model_dump(), "analysis_job_id": job["id"], "finding_id": finding_id, "revision": revision})
    finding["decision"] = decision
    _store.save_finding(finding)
    _store.update_analysis_job(job["id"], {"decision_revision": revision})
    _store.append_audit("finding.decision", "analysis_job", job["id"], {"finding_id": finding_id, "decision_type": body.decision_type})
    return decision


@router.put("/analysis-jobs/{job_id}/decision")
def put_overall_decision(job_id: str, body: OverallDecisionWrite, if_match: str | None = Header(None, alias="If-Match")):
    job = _require("jobs", job_id)
    _check_revision(job, if_match, field="decision_revision")
    revision = int(job.get("decision_revision", 0)) + 1
    decision = _store.create_decision({**body.model_dump(), "analysis_job_id": job_id, "finding_id": None, "revision": revision})
    _store.update_analysis_job(job_id, {"decision_revision": revision, "overall_decision": decision})
    _store.append_audit("overall.decision", "analysis_job", job_id, {"decision_type": body.decision_type})
    return decision


@router.get("/analysis-jobs/{job_id}/audit-events")
def list_audit_events(job_id: str, page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(50, ge=1, le=200)):
    _require("jobs", job_id)
    items, total = _store.list_audit(job_id, page=page_number, page_size=page_size)
    return {"items": items, "total": total, "page": page_number, "page_size": page_size}


@router.post("/decisions/start", status_code=201)
def start_decision(body: StartDecisionRequest):
    _require("jobs", body.analysis_job_id)
    return _hitl.start(body.model_dump())


@router.post("/decisions/{decision_id}/resume")
def resume_decision(decision_id: str, body: ResumeDecisionRequest):
    return _hitl.resume(decision_id, body.model_dump())


@router.post("/analysis-jobs/{job_id}/exports", status_code=202)
def create_export(job_id: str, body: CreateExportRequest | None = None, idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    _require("jobs", job_id)
    request_hash = stable_hash({"job_id": job_id, "format": (body.format if body else "markdown")})
    if idempotency_key:
        existing = _store.check_idempotency("export", idempotency_key, request_hash)
        if existing:
            if existing.get("request_hash") != request_hash:
                raise HTTPException(status_code=409, detail="idempotency key reused with different payload")
            return _require("exports", existing["result_id"])
    artifact = create_markdown_artifact(_store, job_id, artifact_format=(body.format if body else "markdown"))
    if idempotency_key:
        _store.record_idempotency("export", idempotency_key, request_hash, artifact["id"])
    return artifact


@router.get("/export-artifacts/{artifact_id}")
def get_export_artifact(artifact_id: str):
    artifact = _require("exports", artifact_id)
    return {key: value for key, value in artifact.items() if key != "content"}


@router.get("/export-artifacts/{artifact_id}/download")
def download_export_artifact(artifact_id: str):
    artifact = _require("exports", artifact_id)
    content = artifact.get("content")
    if content is None and artifact.get("path"):
        content = Path(artifact["path"]).read_text(encoding="utf-8")
    return PlainTextResponse(str(content or ""), media_type="text/markdown; charset=utf-8")


@router.post("/conversations", status_code=201)
def create_conversation(body: CreateConversationRequest):
    job = _require("jobs", body.analysis_job_id)
    try:
        membership = _store.batch_document(str(job["batch_id"]), body.document_membership_id)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail="document_scope_mismatch") from exc
    in_job_scope = any(
        item.get("document_id") == membership.get("document_id")
        and item.get("document_version_id") == membership.get("document_version_id")
        for item in job.get("documents", [])
    )
    if not in_job_scope:
        raise HTTPException(status_code=409, detail="document_scope_mismatch")
    if not _document_ready(membership):
        raise HTTPException(status_code=409, detail="document_not_ready")
    if membership.get("status") != "ready":
        # 自愈：成员状态滞后于文档管线事实（前端在解析完成前入批且无人回写）
        _store.set_batch_document_status(str(job["batch_id"]), body.document_membership_id, "ready")
    return _store.create_conversation(body.analysis_job_id, membership)


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    conversation = _require("conversations", conversation_id)
    return conversation

@router.get("/jobs/{job_id}/documents/{document_version_id}/conversation")
def get_or_create_document_conversation(job_id: str, document_version_id: str):
    job = _require("jobs", job_id)
    for item in _store.list("conversations", page=1, page_size=1000)[0]:
        if item.get("analysis_job_id") == job_id and item.get("document_version_id") == document_version_id:
            return {
                "conversation": {
                    "id": item.get("id"), "job_id": item.get("analysis_job_id"),
                    "document_id": item.get("document_id"), "document_version_id": item.get("document_version_id"),
                },
                "messages": item.get("messages", []),
                "recommended_questions": item.get("recommended_questions", []),
            }
    for item in job.get("documents", []):
        if item.get("document_version_id") == document_version_id:
            created = _store.create_conversation(job_id, item)
            return {
                "conversation": {
                    "id": created.get("id"), "job_id": created.get("analysis_job_id"),
                    "document_id": created.get("document_id"), "document_version_id": created.get("document_version_id"),
                },
                "messages": created.get("messages", []),
                "recommended_questions": created.get("recommended_questions", []),
            }
    raise HTTPException(status_code=404, detail="document_scope_mismatch")

@router.get("/conversations/{conversation_id}/messages")
def list_conversation_messages(conversation_id: str):
    return {"items": list(_require("conversations", conversation_id).get("messages", []))}

@router.post("/conversations/{conversation_id}/recommended-questions/regenerate")
def regenerate_recommended_questions(conversation_id: str):
    conversation = _require("conversations", conversation_id)
    from services.review.recommended_questions import generate_recommended_questions
    findings = [finding for finding in _store.list_findings(str(conversation.get("analysis_job_id")))
                if finding.get("document_version_id") == conversation.get("document_version_id")]
    questions = generate_recommended_questions(conversation, findings)
    conversation["recommended_questions"] = questions
    _store.save_conversation(conversation)
    return {"items": questions}


@router.delete("/conversations/{conversation_id}/messages", status_code=204)
def clear_conversation(conversation_id: str):
    _assistant.clear(conversation_id)
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/messages/stream")
def stream_review_answer(conversation_id: str, body: ReviewStreamRequest):
    _require("conversations", conversation_id)
    return StreamingResponse(
        _assistant.stream_answer(conversation_id, body.model_dump()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/conversations/{conversation_id}/stream", include_in_schema=False)
def stream_review_answer_legacy(conversation_id: str, body: ReviewStreamRequest):
    return stream_review_answer(conversation_id, body)


@router.post("/conversations/{conversation_id}/stop", status_code=202)
def stop_review_answer(conversation_id: str, body: StopRequest):
    _require("conversations", conversation_id)
    return _assistant.stop(body.request_id)


def _require(collection: str, record_id: str) -> dict[str, Any]:
    try:
        return _store.require(collection, record_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _require_rules(rule_ids: list[str]) -> None:
    for rule_id in rule_ids:
        _require("rules", rule_id)


def _check_revision(record: Mapping[str, Any], if_match: str | None, *, field: str = "revision") -> None:
    if if_match is None:
        return
    try:
        expected = int(if_match)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="invalid If-Match revision") from exc
    if expected != int(record.get(field, 0)):
        raise HTTPException(status_code=409, detail="revision conflict")


def _idempotent(scope: str, key: str | None, payload: Mapping[str, Any], factory):
    if not key:
        return factory()
    request_hash = stable_hash(payload)
    existing = _store.check_idempotency(scope, key, request_hash)
    if existing:
        if existing.get("request_hash") != request_hash:
            raise HTTPException(status_code=409, detail="idempotency key reused with different payload")
        collection = "templates" if scope == "template_publish" else "jobs"
        return _require(collection, existing["result_id"])
    result = factory()
    _store.record_idempotency(scope, key, request_hash, result["id"])
    return result


def _engine_rule(rule: Mapping[str, Any], overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    definition = dict(rule.get("definition") or {})
    definition.update(dict(overrides or {}))
    return {
        "rule_id": rule["id"],
        "rule_version": rule["id"],
        "template_version": None,
        "name": rule["name"],
        "risk_level": rule.get("severity", "medium"),
        "matcher": definition.get("matcher") or {},
        "llm_fallback": bool(rule.get("llm_fallback", False)),
        "description": definition.get("description", ""),
        "suggested_fix": definition.get("suggested_fix", ""),
    }


def _document_ready(membership: Mapping[str, Any]) -> bool:
    """成员就绪判定：批成员状态以文档管线事实为准，避免成员状态滞后导致误拒绝。"""
    if membership.get("status") == "ready":
        return True
    meta = document_store.load_meta(membership.get("document_id") or "")
    return bool(meta and meta.get("status") == "ready")


def _document_ir(membership: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(membership.get("ir"), Mapping):
        return dict(membership["ir"])
    loaded = document_store.load_ir(membership.get("document_id"))
    if isinstance(loaded, Mapping):
        ir = dict(loaded)
        ir.setdefault("doc_id", membership.get("document_id"))
        ir.setdefault("document_version_id", membership.get("document_version_id"))
        ir.setdefault("source", {"filename": membership.get("filename")})
        return ir
    return {
        "doc_id": membership.get("document_id"),
        "document_version_id": membership.get("document_version_id"),
        "source": {"filename": membership.get("filename")},
        "blocks": [],
    }


def _snapshot(
    body: StartAnalysisRequest,
    docs: list[Mapping[str, Any]],
    rules: list[Mapping[str, Any]],
    *,
    configuration: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rule_hash = stable_hash([rule.get("rule_version") for rule in rules])
    template_hash = body.template_version_id or stable_hash([rule.get("template_version") for rule in rules])
    version_tuple = {
        "rule_version": rule_hash,
        "template_version": template_hash,
        "llm_model": "deterministic-review",
        "temperature": 0.2,
        "prompt_hash": stable_hash({"rules": rules}),
        "eval_set_hash": "",
        "seed": 20260815,
    }
    effective_sensitivity = int(configuration.get("sensitivity", body.sensitivity)) if configuration else body.sensitivity
    effective_profile = (configuration or {}).get("analysis_profile_id") or body.analysis_profile_id
    effective_marking = (configuration or {}).get("marking_mode") or body.marking_mode
    if configuration is None:
        rule_version_ids = [selection.rule_version_id for selection in body.rule_selections if selection.enabled]
    else:
        rule_version_ids = [
            str(selection.get("rule_version_id"))
            for selection in configuration.get("rule_selections", [])
            if selection.get("enabled", True)
        ]
    snapshot: dict[str, Any] = {
        "id": stable_hash({"body": body.model_dump(), "docs": docs})[:32],
        "batch_id": body.batch_id,
        "document_versions": [
            {"document_id": doc.get("document_id"), "document_version_id": doc.get("document_version_id"), "filename": doc.get("filename")}
            for doc in docs
        ],
        "template_version_id": body.template_version_id,
        "rule_version_ids": rule_version_ids,
        "sensitivity": effective_sensitivity,
        "analysis_profile_id": effective_profile,
        "marking_mode": effective_marking,
        "input_hash": stable_hash(body.model_dump()),
        "version_tuple": version_tuple,
    }
    if configuration:
        snapshot["configuration"] = {
            "id": configuration.get("id"),
            "name": configuration.get("name"),
            "revision": configuration.get("revision", 0),
        }
    return snapshot


def _job_response(job: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "parent_job_id": job.get("parent_job_id"),
        "snapshot": job.get("snapshot") or {},
        "status": job.get("status", "queued"),
        "progress": int(job.get("progress", 0)),
        "revision": int(job.get("revision", 0)),
        "result_revision": int(job.get("result_revision", 0)),
        "decision_revision": int(job.get("decision_revision", 0)),
        "documents": list(job.get("documents") or []),
        "error": (job.get("errors") or [None])[0],
        "created_at": job.get("created_at") or utc_now(),
        "updated_at": job.get("updated_at") or utc_now(),
    }
