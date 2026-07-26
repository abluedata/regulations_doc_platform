"""知识库文档：上传 / 列表 / 详情 / 预览 / 删除 / 重析。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from api.schemas import (
    DocDetailResponse,
    DocListResponse,
    DocPreviewResponse,
    SimpleMessageResponse,
)
from services.document_pipeline import delete_doc_from_index, enqueue_parse
from services.document_store import (
    ALLOWED_EXT,
    MAX_UPLOAD_BYTES,
    create_doc_record,
    delete_doc,
    deletion_pending,
    doc_dir,
    list_docs,
    load_ir,
    load_meta,
    load_preview_md,
    mark_deletion_complete,
    safe_filename,
)

router = APIRouter(prefix="/docs", tags=["docs"])


@router.get("", response_model=DocListResponse)
def api_list_docs(
    q: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="all|ready|failed|processing|具体状态"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    items, total = list_docs(q=q, status=status, page=page, page_size=page_size)
    return DocListResponse(items=items, total=total)


@router.post("/upload")
async def api_upload(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    original = Path(file.filename).name
    ext = Path(original).suffix.lower()
    if ext == ".doc":
        raise HTTPException(
            status_code=400,
            detail="暂不支持 .doc，请另存为 .docx 后上传",
        )
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail="仅支持 PDF、DOCX",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大（上限 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB）",
        )

    stored = "original" + ext
    meta = create_doc_record(
        filename=stored,
        ext=ext,
        file_size=len(data),
        original_name=safe_filename(original),
    )
    dest = doc_dir(meta["id"]) / stored
    dest.write_bytes(data)

    enqueue_parse(meta["id"])
    return {
        "id": meta["id"],
        "filename": meta["filename"],
        "status": meta["status"],
        "stage_label": meta["stage_label"],
        "message": "已上传，正在排队解析",
    }


@router.get("/{doc_id}", response_model=DocDetailResponse)
def api_get_doc(doc_id: str):
    meta = load_meta(doc_id)
    if not meta:
        raise HTTPException(status_code=404, detail="文档不存在")
    return DocDetailResponse(item=meta)


@router.get("/{doc_id}/preview", response_model=DocPreviewResponse)
def api_preview(doc_id: str):
    meta = load_meta(doc_id)
    if not meta:
        raise HTTPException(status_code=404, detail="文档不存在")

    status = meta.get("status")
    if status not in ("ready", "failed"):
        return DocPreviewResponse(
            id=doc_id,
            status=status or "unknown",
            stage_label=meta.get("stage_label"),
            ready=False,
            message="文档仍在处理中，完成后可查看结构预览",
            markdown="",
            outline=[],
            tables=[],
            meta=meta,
        )

    ir = load_ir(doc_id) or {}
    md = load_preview_md(doc_id)
    outline = []
    tables = []
    for b in ir.get("blocks") or []:
        if b.get("type") == "heading":
            outline.append(
                {
                    "block_id": b.get("block_id"),
                    "text": b.get("text"),
                    "level": b.get("level") or 1,
                    "section_path": b.get("section_path") or [],
                }
            )
        if b.get("type") == "table":
            tables.append(
                {
                    "block_id": b.get("block_id"),
                    "section_path": b.get("section_path") or [],
                    "page_start": b.get("page_start"),
                    "page_end": b.get("page_end"),
                    "merged": bool((b.get("meta") or {}).get("merged")),
                    "html": b.get("html") or "",
                    "markdown": b.get("markdown") or b.get("text") or "",
                }
            )

    return DocPreviewResponse(
        id=doc_id,
        status=status,
        stage_label=meta.get("stage_label"),
        ready=status == "ready",
        message=meta.get("error") if status == "failed" else None,
        markdown=md,
        outline=outline,
        tables=tables,
        meta=meta,
        ir_summary={
            "block_count": len(ir.get("blocks") or []),
            "title": ir.get("title"),
            "pages": (ir.get("source") or {}).get("pages"),
        },
    )


@router.delete("/{doc_id}", response_model=SimpleMessageResponse)
def api_delete(doc_id: str):
    meta = load_meta(doc_id)
    if not meta and not deletion_pending(doc_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    delete_doc(doc_id)
    delete_doc_from_index(doc_id)
    mark_deletion_complete(doc_id)
    return SimpleMessageResponse(message="已删除文档及索引", success=True)


@router.post("/{doc_id}/reparse", response_model=SimpleMessageResponse)
def api_reparse(doc_id: str):
    meta = load_meta(doc_id)
    if not meta:
        raise HTTPException(status_code=404, detail="文档不存在")
    src = doc_dir(doc_id)
    if not src.exists():
        raise HTTPException(status_code=400, detail="原始文件目录不存在")
    enqueue_parse(doc_id)
    return SimpleMessageResponse(message="已重新排队解析", success=True)
