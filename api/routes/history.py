"""历史记录 API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.schemas import (
    BatchIdsRequest,
    BatchResultResponse,
    HistoryListResponse,
    SimpleMessageResponse,
)
from services.chat_manager import (
    add_favorite,
    clear_all_history,
    count_history,
    delete_history,
    get_session,
    list_history_filtered,
)

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=HistoryListResponse)
def list_history(
    id: str | None = Query(None, description="ID 模糊搜索"),
    q: str | None = Query(None, description="问题模糊搜索"),
    date_start: str | None = Query(None),
    date_end: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    items, total = list_history_filtered(
        id_query=id,
        q=q,
        date_start=date_start,
        date_end=date_end,
        page=page,
        page_size=page_size,
    )
    return HistoryListResponse(items=items, total=total)


@router.delete("", response_model=SimpleMessageResponse)
def clear_history():
    n = count_history()
    clear_all_history()
    return SimpleMessageResponse(message=f"已清空（{n} 条）", success=True)


# 静态路径须写在 /{session_id} 之前，避免被路径参数吞掉
@router.post("/batch-delete", response_model=BatchResultResponse)
def batch_delete(body: BatchIdsRequest):
    ok = 0
    for sid in body.ids:
        if delete_history(sid):
            ok += 1
    return BatchResultResponse(ok=ok, message=f"已删除 {ok} 条")


@router.post("/batch-favorite", response_model=BatchResultResponse)
def batch_favorite(body: BatchIdsRequest):
    ok = 0
    for sid in body.ids:
        if add_favorite(sid):
            ok += 1
    return BatchResultResponse(ok=ok, message=f"已收藏 {ok} 条")


@router.get("/{session_id}")
def get_history_detail(session_id: str):
    sess = get_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="未找到该对话")
    return sess


@router.delete("/{session_id}", response_model=SimpleMessageResponse)
def delete_history_item(session_id: str):
    ok = delete_history(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="未找到该对话")
    return SimpleMessageResponse(message="已删除", success=True)
