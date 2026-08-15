"""Lightweight HITL decision state machine for W3."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

from .store import ReviewStore, utc_now


class HitlDecisionMachine:
    def __init__(self, store: ReviewStore) -> None:
        self.store = store

    def start(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = {
            "id": str(uuid4()),
            "analysis_job_id": payload["analysis_job_id"],
            "finding_id": payload.get("finding_id"),
            "decision_type": payload["decision_type"],
            "comment": payload.get("comment"),
            "status": "waiting_confirmation",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        saved = self.store.create_hitl(record)
        self.store.append_audit("decision.started", "analysis_job", payload["analysis_job_id"], {"decision_id": saved["id"]})
        return saved

    def resume(self, decision_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = self.store.require("hitl", decision_id)
        action = payload.get("action")
        record["status"] = "completed" if action == "confirm" else "cancelled"
        record["resume_comment"] = payload.get("comment")
        record["updated_at"] = utc_now()
        saved = self.store.put("hitl", record)
        self.store.append_audit("decision.resumed", "analysis_job", saved["analysis_job_id"], {"decision_id": decision_id, "status": saved["status"]})
        return saved


__all__ = ["HitlDecisionMachine"]
