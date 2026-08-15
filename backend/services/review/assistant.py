"""Review-scoped assistant with deterministic SSE terminal semantics."""

from __future__ import annotations

from typing import Any, Iterable, Mapping
from uuid import uuid4

from .store import ReviewStore, utc_now


def sse(event: str, data: Mapping[str, Any] | list[Any] | str) -> str:
    import json

    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


class ReviewAssistant:
    def __init__(self, store: ReviewStore) -> None:
        self.store = store
        self._stopped: set[str] = set()

    def stream_answer(self, conversation_id: str, body: Mapping[str, Any]) -> list[str]:
        conversation = self.store.require("conversations", conversation_id)
        request_id = str(body["request_id"])
        question = str(body.get("message") or "").strip()
        job_id = str(conversation["analysis_job_id"])
        findings = self.store.list_findings(job_id)
        events = [sse("meta", {"request_id": request_id}), sse("status", {"type": "retrieving"})]
        if request_id in self._stopped:
            events.append(sse("error", {"message": "request stopped", "request_id": request_id}))
            return events
        answer = self._answer(question, findings)
        events.append(sse("token", {"content": answer}))
        events.append(sse("done", {"request_id": request_id, "citations": [item.get("evidence_anchor") for item in findings[:3]]}))
        self._append_messages(conversation, request_id, question, answer, findings)
        return events

    def stop(self, request_id: str) -> dict[str, Any]:
        self._stopped.add(request_id)
        return {"request_id": request_id, "accepted": True}

    def clear(self, conversation_id: str) -> None:
        conversation = self.store.require("conversations", conversation_id)
        conversation["messages"] = []
        conversation["revision"] = int(conversation.get("revision", 0)) + 1
        self.store.save_conversation(conversation)

    def _answer(self, question: str, findings: list[dict[str, Any]]) -> str:
        if not findings:
            return "当前审查任务没有可引用的风险证据，无法给出超出任务范围的回答。"
        first = findings[0]
        return f"基于当前审查任务，主要风险是 {first.get('title') or first.get('rule_id')}：{first.get('reason') or first.get('quote')}。"

    def _append_messages(self, conversation: dict[str, Any], request_id: str, question: str, answer: str, findings: Iterable[Mapping[str, Any]]) -> None:
        now = utc_now()
        conversation.setdefault("messages", []).extend(
            [
                {"id": str(uuid4()), "request_id": request_id, "role": "user", "content": question, "status": "complete", "citations": [], "created_at": now},
                {
                    "id": str(uuid4()),
                    "request_id": request_id,
                    "role": "assistant",
                    "content": answer,
                    "status": "complete",
                    "citations": [item.get("evidence_anchor") for item in findings],
                    "created_at": now,
                },
            ]
        )
        conversation["revision"] = int(conversation.get("revision", 0)) + 1
        self.store.save_conversation(conversation)


__all__ = ["ReviewAssistant", "sse"]
