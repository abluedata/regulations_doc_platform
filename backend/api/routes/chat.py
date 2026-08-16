"""聊天流式问答 / 停止 / 保存会话 API。"""
from __future__ import annotations

import asyncio
import json
import threading
import uuid
from typing import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api.schemas import (
    ChatStreamRequest,
    ExamplesResponse,
    SaveSessionRequest,
    SessionIdResponse,
    StopRequest,
)
from services.knowledge.chat_manager import save_history_session
from services.knowledge.qa_service import EXAMPLES, stream_answer

router = APIRouter(prefix="/chat", tags=["chat"])

# request_id -> cancel Event（支持多路并发取消）
_cancel_registry: dict[str, threading.Event] = {}
_registry_lock = threading.Lock()


def _register_cancel(request_id: str) -> threading.Event:
    ev = threading.Event()
    with _registry_lock:
        _cancel_registry[request_id] = ev
    return ev


def _unregister_cancel(request_id: str) -> None:
    with _registry_lock:
        _cancel_registry.pop(request_id, None)


def _get_cancel(request_id: str) -> threading.Event | None:
    with _registry_lock:
        return _cancel_registry.get(request_id)


def _sse(event: str, data: dict | list | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@router.get("/examples", response_model=ExamplesResponse)
def get_examples():
    return ExamplesResponse(examples=list(EXAMPLES))


@router.post("/stream")
async def chat_stream(body: ChatStreamRequest):
    text = (body.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="请输入问题")

    request_id = body.request_id or str(uuid.uuid4())
    cancel_event = _register_cancel(request_id)
    loop = asyncio.get_event_loop()

    def sync_events() -> Iterator[str]:
        yield _sse("meta", {"request_id": request_id})
        try:
            for event in stream_answer(text, cancel_event=cancel_event):
                etype = event.get("type", "token")
                if etype == "status":
                    yield _sse("status", {"type": event.get("status", "searching")})
                elif etype == "token":
                    yield _sse("token", {"content": event.get("content", "")})
                elif etype == "done":
                    yield _sse(
                        "done",
                        {
                            "route": event.get("route", "local"),
                            "has_web": event.get("has_web", False),
                        },
                    )
                elif etype == "error":
                    yield _sse("error", {"message": event.get("message", "未知错误")})
        except Exception as e:
            yield _sse("error", {"message": str(e)})
        finally:
            _unregister_cancel(request_id)

    async def async_events():
        # 在线程中跑同步生成器，避免阻塞事件循环
        queue: asyncio.Queue = asyncio.Queue()
        sentinel = object()

        def worker():
            try:
                for chunk in sync_events():
                    asyncio.run_coroutine_threadsafe(queue.put(chunk), loop).result()
            except Exception as e:
                asyncio.run_coroutine_threadsafe(
                    queue.put(_sse("error", {"message": str(e)})), loop
                ).result()
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(sentinel), loop).result()

        threading.Thread(target=worker, daemon=True).start()
        while True:
            item = await queue.get()
            if item is sentinel:
                break
            yield item

    return StreamingResponse(
        async_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/stop")
def stop_chat(body: StopRequest):
    ev = _get_cancel(body.request_id)
    if ev is None:
        return {"success": False, "message": "未找到进行中的请求"}
    ev.set()
    return {"success": True, "message": "已请求停止"}


@router.post("/sessions", response_model=SessionIdResponse)
def save_session(body: SaveSessionRequest):
    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    if len(messages) < 2:
        raise HTTPException(status_code=400, detail="消息不足，无法保存")
    sid = save_history_session(messages, route=body.route, has_web=body.has_web)
    if not sid:
        raise HTTPException(status_code=400, detail="保存失败")
    return SessionIdResponse(id=sid)
