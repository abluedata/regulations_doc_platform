"""
知识库文档元数据与 IR 本地存储。

布局：
  .data/uploads/{doc_id}/original.{ext}
  .data/uploads/{doc_id}/meta.json
  .data/uploads/{doc_id}/ir.json
  .data/uploads/{doc_id}/preview.md
  .data/docs_index.json   — 文档列表索引
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import DATA_ROOT

UPLOADS_DIR = DATA_ROOT / "uploads"
INDEX_FILE = DATA_ROOT / "docs_index.json"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.RLock()

# 对外状态（与设计简报一致）
STATUS_LABELS = {
    "uploaded": "已上传",
    "queued": "排队中",
    "parsing": "解析版面",
    "normalizing": "整理结构",
    "chunking": "语义分块",
    "indexing": "写入检索",
    "ready": "已入库",
    "failed": "失败",
    "needs_ocr": "需 OCR",
}

ALLOWED_EXT = {".pdf", ".docx"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50MB


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_index() -> list[dict]:
    if not INDEX_FILE.exists():
        return []
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_index(items: list[dict]) -> None:
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def doc_dir(doc_id: str) -> Path:
    return UPLOADS_DIR / doc_id


def meta_path(doc_id: str) -> Path:
    return doc_dir(doc_id) / "meta.json"


def ir_path(doc_id: str) -> Path:
    return doc_dir(doc_id) / "ir.json"


def preview_path(doc_id: str) -> Path:
    return doc_dir(doc_id) / "preview.md"


def load_meta(doc_id: str) -> dict | None:
    p = meta_path(doc_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_meta(meta: dict) -> None:
    doc_id = meta["id"]
    d = doc_dir(doc_id)
    d.mkdir(parents=True, exist_ok=True)
    meta["updated_at"] = _now()
    meta_path(doc_id).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with _lock:
        items = _load_index()
        found = False
        for i, it in enumerate(items):
            if it.get("id") == doc_id:
                items[i] = _index_row(meta)
                found = True
                break
        if not found:
            items.insert(0, _index_row(meta))
        _save_index(items)


def _index_row(meta: dict) -> dict:
    return {
        "id": meta["id"],
        "filename": meta.get("filename", ""),
        "title": meta.get("title", ""),
        "ext": meta.get("ext", ""),
        "status": meta.get("status", "uploaded"),
        "stage_label": meta.get("stage_label")
        or STATUS_LABELS.get(meta.get("status", ""), meta.get("status", "")),
        "error": meta.get("error"),
        "page_count": meta.get("page_count"),
        "chunk_count": meta.get("chunk_count"),
        "file_size": meta.get("file_size"),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "duration_sec": meta.get("duration_sec"),
        "engine": meta.get("engine"),
    }


def list_docs(
    q: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict], int]:
    with _lock:
        items = _load_index()
    if status and status != "all":
        if status == "processing":
            items = [
                x
                for x in items
                if x.get("status")
                in (
                    "uploaded",
                    "queued",
                    "parsing",
                    "normalizing",
                    "chunking",
                    "indexing",
                )
            ]
        else:
            items = [x for x in items if x.get("status") == status]
    if q:
        ql = q.lower()
        items = [
            x
            for x in items
            if ql in (x.get("filename") or "").lower()
            or ql in (x.get("title") or "").lower()
            or ql in (x.get("id") or "").lower()
        ]
    total = len(items)
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    start = (page - 1) * page_size
    return items[start : start + page_size], total


def create_doc_record(
    filename: str,
    ext: str,
    file_size: int,
    original_name: str,
) -> dict:
    doc_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    title = _title_from_filename(filename)
    meta = {
        "id": doc_id,
        "filename": original_name,
        "stored_name": filename,
        "title": title,
        "ext": ext.lstrip(".").lower(),
        "mime": _mime(ext),
        "file_size": file_size,
        "status": "queued",
        "stage_label": STATUS_LABELS["queued"],
        "error": None,
        "page_count": None,
        "chunk_count": None,
        "duration_sec": None,
        "engine": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    d = doc_dir(doc_id)
    d.mkdir(parents=True, exist_ok=True)
    save_meta(meta)
    return meta


def update_status(
    doc_id: str,
    status: str,
    *,
    error: str | None = None,
    **fields: Any,
) -> dict | None:
    meta = load_meta(doc_id)
    if not meta:
        return None
    meta["status"] = status
    meta["stage_label"] = STATUS_LABELS.get(status, status)
    if error is not None:
        meta["error"] = error
    elif status != "failed":
        meta["error"] = None
    for k, v in fields.items():
        meta[k] = v
    save_meta(meta)
    return meta


def save_ir(doc_id: str, ir: dict) -> None:
    ir_path(doc_id).write_text(
        json.dumps(ir, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_ir(doc_id: str) -> dict | None:
    p = ir_path(doc_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_preview_md(doc_id: str, md: str) -> None:
    preview_path(doc_id).write_text(md, encoding="utf-8")


def load_preview_md(doc_id: str) -> str:
    p = preview_path(doc_id)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def delete_doc(doc_id: str) -> bool:
    with _lock:
        items = _load_index()
        items = [x for x in items if x.get("id") != doc_id]
        _save_index(items)
    d = doc_dir(doc_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
        return True
    return False


def original_file(doc_id: str) -> Path | None:
    meta = load_meta(doc_id)
    if not meta:
        return None
    name = meta.get("stored_name") or meta.get("filename")
    if not name:
        return None
    p = doc_dir(doc_id) / name
    if p.exists():
        return p
    # fallback: any original.*
    for cand in doc_dir(doc_id).iterdir():
        if cand.name.startswith("original") or cand.suffix.lower() in ALLOWED_EXT:
            if cand.name not in ("meta.json", "ir.json", "preview.md"):
                return cand
    return None


def _title_from_filename(filename: str) -> str:
    name = Path(filename).stem
    if name and name[0].isdigit() and "-" in name:
        name = name.split("-", 1)[1]
    return name or filename


def _mime(ext: str) -> str:
    e = ext.lower().lstrip(".")
    if e == "pdf":
        return "application/pdf"
    if e == "docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "application/octet-stream"


def safe_filename(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^\w\u4e00-\u9fff.\-()（）\[\] ]+", "_", base)
    return base[:180] or "document"
