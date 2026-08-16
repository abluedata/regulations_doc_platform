"""收藏 API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.schemas import (
    BatchIdsRequest,
    BatchResultResponse,
    FavoritesListResponse,
    SimpleMessageResponse,
)
from services.knowledge.chat_manager import add_favorite, list_favorites_filtered, remove_favorite

router = APIRouter(prefix="/favorites", tags=["favorites"])


@router.get("", response_model=FavoritesListResponse)
def list_favorites(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    items, total = list_favorites_filtered(page=page, page_size=page_size)
    return FavoritesListResponse(items=items, total=total)


@router.post("/batch-delete", response_model=BatchResultResponse)
def batch_delete_favorites(body: BatchIdsRequest):
    ok = 0
    for sid in body.ids:
        if remove_favorite(sid):
            ok += 1
    return BatchResultResponse(ok=ok, message=f"已删除 {ok} 条")


@router.post("/{session_id}", response_model=SimpleMessageResponse)
def favorite_item(session_id: str):
    if add_favorite(session_id):
        return SimpleMessageResponse(message="已收藏", success=True)
    raise HTTPException(status_code=400, detail="收藏失败（可能已收藏或不存在）")


@router.delete("/{session_id}", response_model=SimpleMessageResponse)
def unfavorite_item(session_id: str):
    if remove_favorite(session_id):
        return SimpleMessageResponse(message="已取消收藏", success=True)
    raise HTTPException(status_code=404, detail="未找到该收藏")
