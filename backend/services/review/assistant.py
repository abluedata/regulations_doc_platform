"""Document-scoped review assistant with unique SSE terminal semantics."""

from __future__ import annotations

import json
from types import GeneratorType
from typing import Any, Callable, Generator, Mapping
from uuid import uuid4

from .qa_answer import GroundedAnswer, stream_answer_document
from .qa_retrieval import DocumentScope
from .store import ReviewStore, utc_now


def sse(event: str, data: Mapping[str, Any] | list[Any] | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


class ReviewAssistant:
    def __init__(
        self,
        store: ReviewStore,
        *,
        answerer: Callable[..., Any] = stream_answer_document,
    ) -> None:
        self.store = store
        self.answerer = answerer
        self._stopped: set[str] = set()

    def stream_answer(self, conversation_id: str, body: Mapping[str, Any]) -> Generator[str, None, None]:
        conversation = self.store.require("conversations", conversation_id)
        request_id = str(body["request_id"])
        existing = self._completed_message(conversation, request_id)
        if existing:
            yield sse("meta", self._meta(conversation, request_id, existing))
            yield sse(existing["terminal_event"], existing["terminal_payload"])
            return

        question = str(body.get("message") or "").strip()
        user_message, assistant_message = self._begin_messages(conversation, request_id, question)
        yield sse("meta", self._meta(conversation, request_id, assistant_message, user_message))
        yield sse("status", {"request_id": request_id, "type": "retrieving"})
        try:
            if request_id in self._stopped:
                raise InterruptedError("request cancelled")
            scope = DocumentScope(str(conversation["document_id"]), str(conversation["document_version_id"]))
            history = [dict(item) for item in (body.get("history") or []) if isinstance(item, dict)]
            finding = None
            if body.get("finding_id"):
                try:
                    finding = self.store.find_finding(str(body["finding_id"]))
                except KeyError:
                    finding = None
            outcome = self.answerer(
                question,
                scope,
                str(conversation.get("filename") or ""),
                history=history,
                finding=finding,
            )
            generating_emitted = False
            streamed_chars = 0
            if isinstance(outcome, GeneratorType):
                # 流式回答器：逐个 token 推送，返回值为最终 GroundedAnswer
                try:
                    while True:
                        chunk = next(outcome)
                        if not generating_emitted:
                            yield sse("status", {"request_id": request_id, "type": "generating"})
                            generating_emitted = True
                        text = str(chunk)
                        if text:
                            streamed_chars += len(text)
                            yield sse("token", {"request_id": request_id, "content": text})
                except StopIteration as exc:
                    result: GroundedAnswer = exc.value
            else:
                result = outcome
            if request_id in self._stopped:
                raise InterruptedError("request cancelled")
            if not generating_emitted:
                yield sse("status", {"request_id": request_id, "type": "generating"})
            # 回答器未逐段输出时才补发整段 token，避免与流式内容重复
            if result.answer and streamed_chars == 0:
                yield sse("token", {"request_id": request_id, "content": result.answer})
            payload = {
                "request_id": request_id, "answer": result.answer, "refused": result.refused,
                "refusal_code": result.refusal_code, "citations": result.citations,
            }
            yield sse("done", payload)
            self._finish_messages(conversation, user_message["id"], assistant_message["id"], result, "done", payload)
        except InterruptedError:
            payload = {"request_id": request_id, "code": "request_cancelled", "message": "请求已停止", "retryable": False}
            yield sse("error", payload)
            self._finish_messages(conversation, user_message["id"], assistant_message["id"], None, "error", payload)
        except Exception:
            payload = {"request_id": request_id, "code": "assistant_unavailable", "message": "审查问答服务暂时不可用", "retryable": True}
            yield sse("error", payload)
            self._finish_messages(conversation, user_message["id"], assistant_message["id"], None, "error", payload)

    def stop(self, request_id: str) -> dict[str, Any]:
        self._stopped.add(request_id)
        return {"request_id": request_id, "accepted": True}

    def clear(self, conversation_id: str) -> None:
        conversation = self.store.require("conversations", conversation_id)
        conversation["messages"] = []
        conversation["revision"] = int(conversation.get("revision", 0)) + 1
        self.store.save_conversation(conversation)

    def _meta(self, conversation: Mapping[str, Any], request_id: str, assistant: Mapping[str, Any], user: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return {key: conversation.get(key) for key in ("document_membership_id", "document_id", "document_version_id")} | {
            "conversation_id": conversation.get("id"), "request_id": request_id,
            "user_message_id": (user or self._message_for_request(conversation, request_id, "user") or {}).get("id"),
            "assistant_message_id": assistant.get("id"),
        }

    def _completed_message(self, conversation: Mapping[str, Any], request_id: str) -> Mapping[str, Any] | None:
        return next((item for item in conversation.get("messages", []) if item.get("request_id") == request_id and item.get("terminal_event")), None)

    def _begin_messages(self, conversation: dict[str, Any], request_id: str, question: str) -> tuple[dict[str, Any], dict[str, Any]]:
        now = utc_now()
        user = {"id": str(uuid4()), "request_id": request_id, "role": "user", "content": question, "status": "streaming", "citations": [], "created_at": now}
        assistant = {"id": str(uuid4()), "request_id": request_id, "role": "assistant", "content": "", "status": "streaming", "citations": [], "created_at": now}
        conversation.setdefault("messages", []).extend([user, assistant])
        conversation["revision"] = int(conversation.get("revision", 0)) + 1
        self.store.save_conversation(conversation)
        return user, assistant

    def _finish_messages(self, conversation: dict[str, Any], user_id: str, assistant_id: str, result: GroundedAnswer | None, event: str, payload: Mapping[str, Any]) -> None:
        for message in conversation.get("messages", []):
            if message.get("id") == user_id:
                message["status"] = "completed" if event == "done" else "error"
            elif message.get("id") == assistant_id:
                message["status"] = "completed" if event == "done" else "error"
                message["terminal_event"] = event
                message["terminal_payload"] = dict(payload)
                if result is not None:
                    message.update({"content": result.answer, "refused": result.refused, "refusal_code": result.refusal_code, "citations": result.citations})
        conversation["revision"] = int(conversation.get("revision", 0)) + 1
        self.store.save_conversation(conversation)

    def _message_for_request(self, conversation: Mapping[str, Any], request_id: str, role: str) -> Mapping[str, Any] | None:
        return next((item for item in conversation.get("messages", []) if item.get("request_id") == request_id and item.get("role") == role), None)


__all__ = ["ReviewAssistant", "sse"]
