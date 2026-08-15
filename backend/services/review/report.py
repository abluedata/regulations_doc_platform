"""Markdown report snapshots for review exports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .store import ReviewStore, stable_hash, utc_now


def build_markdown_report(store: ReviewStore, job_id: str) -> str:
    job = store.require("jobs", job_id)
    findings = store.list_findings(job_id)
    snapshot = job.get("snapshot") or {}
    version_tuple = snapshot.get("version_tuple") or {}
    lines = [
        "# 审查报告",
        "",
        f"- 任务 ID: {job_id}",
        f"- 任务状态: {job.get('status')}",
        f"- 结果版本: {job.get('result_revision', 0)}",
        f"- 决策版本: {job.get('decision_revision', 0)}",
        f"- 生成时间: {utc_now()}",
        "",
        "## 版本六元组",
        "",
        f"- rule_version: {version_tuple.get('rule_version')}",
        f"- template_version: {version_tuple.get('template_version')}",
        f"- llm_model: {version_tuple.get('llm_model')}",
        f"- temperature: {version_tuple.get('temperature')}",
        f"- prompt_hash: {version_tuple.get('prompt_hash')}",
        f"- eval_set_hash: {version_tuple.get('eval_set_hash')}",
        "",
        "## 风险清单",
        "",
    ]
    if not findings:
        lines.append("未发现风险。")
    for index, finding in enumerate(findings, 1):
        lines.extend(
            [
                f"### {index}. {finding.get('title') or finding.get('rule_id')}",
                "",
                f"- 规则版本: {finding.get('rule_version_id')}",
                f"- 严重度: {finding.get('severity')}",
                f"- 原文: {finding.get('quote')}",
                f"- 原因: {finding.get('reason')}",
                f"- 建议: {finding.get('suggestion')}",
                f"- 处置: {(finding.get('decision') or {}).get('decision_type') or 'open'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def create_markdown_artifact(store: ReviewStore, job_id: str, *, artifact_format: str = "markdown") -> dict[str, Any]:
    content = build_markdown_report(store, job_id)
    artifact_id = None
    artifact = {
        "analysis_job_id": job_id,
        "status": "completed",
        "format": artifact_format,
        "result_revision": store.require("jobs", job_id).get("result_revision", 0),
        "decision_revision": store.require("jobs", job_id).get("decision_revision", 0),
        "filename": f"review-{job_id}.md",
        "sha256": stable_hash({"content": content}),
        "size_bytes": len(content.encode("utf-8")),
        "error": None,
        "completed_at": utc_now(),
        "content": content,
    }
    saved = store.create_export(artifact)
    artifact_id = saved["id"]
    export_dir = store.root / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"{artifact_id}.md"
    path.write_text(content, encoding="utf-8")
    saved["path"] = str(path)
    store.create_export(saved)
    store.append_audit("export.completed", "analysis_job", job_id, {"artifact_id": artifact_id})
    return saved


__all__ = ["build_markdown_report", "create_markdown_artifact"]
