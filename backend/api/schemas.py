"""Pydantic 请求 / 响应模型。"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatStreamRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)
    request_id: Optional[str] = None


class StopRequest(BaseModel):
    request_id: str


class SaveSessionRequest(BaseModel):
    messages: list[ChatMessage]
    route: str = "local"
    has_web: bool = False


class SessionIdResponse(BaseModel):
    id: str


class BatchIdsRequest(BaseModel):
    ids: list[str]


class BatchResultResponse(BaseModel):
    ok: int
    message: str


class HistoryListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int


class FavoritesListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int


class HealthResponse(BaseModel):
    status: str


class ExamplesResponse(BaseModel):
    examples: list[str]


class SimpleMessageResponse(BaseModel):
    message: str
    success: bool = True


# ─── 知识库文档 ─────────────────────────────────────────────

class DocListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int


class DocDetailResponse(BaseModel):
    item: dict[str, Any]


class DocPreviewResponse(BaseModel):
    id: str
    status: str
    stage_label: Optional[str] = None
    ready: bool = False
    message: Optional[str] = None
    markdown: str = ""
    outline: list[dict[str, Any]] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
    ir_summary: dict[str, Any] = Field(default_factory=dict)
