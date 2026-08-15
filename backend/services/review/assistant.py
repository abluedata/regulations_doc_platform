"""Document-scoped review assistant with unique SSE terminal semantics."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping
from uuid import uuid4

from .qa_answer import GroundedAnswer, answer_document
from .qa_retrieval import DocumentScope
from .store import ReviewStore, utc_now


def sse(event: str, data: Mapping[str, Any] | list[Any] | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


class ReviewAssistant:
    def __init__(self, store: ReviewStore, *, answerer: Callable[[str, DocumentScope, str], GroundedAnswer] = answer_document) -> None:
        self.store = store
        self.answerer = answerer
        self._stopped: set[str] = set()

    def stream_answer(self, conversation_id: str, body: Mapping[str, Any]) -> list[str]:
        conversation = self.store.require("conversations", conversation_id)
        request_id = str(body["request_id"])
        existing = self._completed_message(conversation, request_id)
        if existing:
            return [sse("meta", self._meta(conversation, request_id)), sse(existing["terminal_event"], existing["terminal_payload"])]

        events = [sse("meta", self._meta(conversation, request_id)), sse("status", {"request_id": request_id, "type": "retrieving"})]
        try:
            if request_id in self._stopped:
                raise InterruptedError("request cancelled")
            scope = DocumentScope(str(conversation["document_id"]), str(conversation["document_version_id"]))
            result = self.answerer(str(body.get("message") or "").strip(), scope, str(conversation.get("filename") or ""))
            if request_id in self._stopped:
                raise InterruptedError("request cancelled")
            events.append(sse("status", {"request_id": request_id, "type": "generating"}))
            if result.answer:
                events.append(sse("token", {"request_id": request_id, "content": result.answer}))
            payload = {
                "request_id": request_id, "answer": result.answer, "refused": result.refused,
                "refusal_code": result.refusal_code, "citations": result.citations,
            }
            events.append(sse("done", payload))
            self._append_messages(conversation, request_id, str(body.get("message") or ""), result, "done", payload)
        except InterruptedError:
            payload = {"request_id": request_id, "code": "request_cancelled", "message": "请求已停止", "retryable": False}
            events.append(sse("error", payload))
            self._append_terminal(conversation, request_id, "error", payload)
        except Exception:
            payload = {"request_id": request_id, "code": "assistant_unavailable", "message": "审查问答服务暂时不可用", "retryable": True}
            events.append(sse("error", payload))
            self._append_terminal(conversation, request_id, "error", payload)
        return events

    def stop(self, request_id: str) -> dict[str, Any]:
        self._stopped.add(request_id)
        return {"request_id": request_id, "accepted": True}

    def clear(self, conversation_id: str) -> None:
        conversation = self.store.require("conversations", conversation_id)
        conversation["messages"] = []
        conversation["revision"] = int(conversation.get("revision", 0)) + 1
        self.store.save_conversation(conversation)

    def _meta(self, conversation: Mapping[str, Any], request_id: str) -> dict[str, Any]:
        return {key: conversation.get(key) for key in ("document_membership_id", "document_id", "document_version_id")} | {"request_id": request_id}

    def _completed_message(self, conversation: Mapping[str, Any], request_id: str) -> Mapping[str, Any] | None:
        return next((item for item in conversation.get("messages", []) if item.get("request_id") == request_id and item.get("terminal_event")), None)

    def _append_messages(self, conversation: dict[str, Any], request_id: str, question: str, result: GroundedAnswer, event: str, payload: Mapping[str, Any]) -> None:
        now = utc_now()
        conversation.setdefault("messages", []).extend([
            {"id": str(uuid4()), "request_id": request_id, "role": "user", "content": question, "status": "complete", "citations": [], "created_at": now},
            {"id": str(uuid4()), "request_id": request_id, "role": "assistant", "content": result.answer, "status": "complete",
             "refused": result.refused, "refusal_code": result.refusal_code, "citations": result.citations,
             "terminal_event": event, "terminal_payload": dict(payload), "created_at": now},
        ])
        conversation["revision"] = int(conversation.get("revision", 0)) + 1
        self.store.save_conversation(conversation)

    def _append_terminal(self, conversation: dict[str, Any], request_id: str, event: str, payload: Mapping[str, Any]) -> None:
        conversation.setdefault("messages", []).append({
            "id": str(uuid4()), "request_id": request_id, "role": "assistant", "content": "", "status": "error",
            "citations": [], "terminal_event": event, "terminal_payload": dict(payload), "created_at": utc_now(),
        })
        conversation["revision"] = int(conversation.get("revision", 0)) + 1
        self.store.save_conversation(conversation)


__all__ = ["ReviewAssistant", "sse"]
