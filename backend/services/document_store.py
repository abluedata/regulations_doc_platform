"""
知识库文档元数据与 IR 本地存储。

布局：
  .data/uploads/{doc_id}/original.{ext}
  .data/uploads/{doc_id}/meta.json
  .data/uploads/{doc_id}/versions/{version_id}/{ir.json,preview.md,manifest.json}
  .data/uploads/{doc_id}/{ir.json,preview.md}  — 旧版兼容
  .data/docs_index.json   — 文档列表索引
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import DATA_ROOT

UPLOADS_DIR = DATA_ROOT / "uploads"
INDEX_FILE = DATA_ROOT / "docs_index.json"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

_index_lock = threading.RLock()
_doc_locks_guard = threading.Lock()
_doc_locks: dict[str, threading.RLock] = {}


def _doc_lock(doc_id: str) -> threading.RLock:
    with _doc_locks_guard:
        return _doc_locks.setdefault(doc_id, threading.RLock())

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


def _validate_version_id(version_id: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", version_id):
        raise ValueError("version_id must be a lowercase SHA-256 hex digest")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_meta_file(meta: dict) -> None:
    _atomic_write_text(
        meta_path(meta["id"]), json.dumps(meta, ensure_ascii=False, indent=2)
    )


def _load_index() -> list[dict]:
    if not INDEX_FILE.exists():
        return []
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _load_publication_index(*, allow_missing: bool) -> list[dict]:
    if not INDEX_FILE.exists():
        if allow_missing:
            return []
        raise RuntimeError("document index disappeared during publication recovery")
    try:
        items = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("document index is unreadable during publication") from exc
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise RuntimeError("document index has invalid publication structure")
    return items


def _save_index(items: list[dict]) -> None:
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        INDEX_FILE, json.dumps(items, ensure_ascii=False, indent=2)
    )


def doc_dir(doc_id: str) -> Path:
    return UPLOADS_DIR / doc_id


def meta_path(doc_id: str) -> Path:
    return doc_dir(doc_id) / "meta.json"


def _publication_journal_dir() -> Path:
    return INDEX_FILE.parent / "publication_journal"


def _publication_journal_path(doc_id: str) -> Path:
    name = hashlib.sha256(doc_id.encode("utf-8")).hexdigest()
    return _publication_journal_dir() / f"{name}.json"


def _deletion_tombstone_dir() -> Path:
    return INDEX_FILE.parent / "deletion_tombstones"


def _deletion_tombstone_path(doc_id: str) -> Path:
    name = hashlib.sha256(doc_id.encode("utf-8")).hexdigest()
    return _deletion_tombstone_dir() / f"{name}.json"


_DELETION_PHASES = (
    "pending_filesystem",
    "pending_index",
    "pending_es",
    "complete",
)


def _read_deletion_tombstone(path: Path) -> dict:
    try:
        tombstone = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"deletion tombstone is unreadable: {path.name}") from exc
    if not isinstance(tombstone, dict):
        raise RuntimeError(f"deletion tombstone is invalid: {path.name}")
    doc_id = tombstone.get("doc_id")
    generation = tombstone.get("generation")
    phase = tombstone.get("phase", "pending_filesystem")
    if (
        not isinstance(doc_id, str)
        or not doc_id
        or not isinstance(generation, str)
        or not generation
        or phase not in _DELETION_PHASES
        or path != _deletion_tombstone_path(doc_id)
    ):
        raise RuntimeError(f"deletion tombstone is invalid: {path.name}")
    return {**tombstone, "phase": phase}


def _deletion_tombstones_locked() -> dict[str, dict]:
    directory = _deletion_tombstone_dir()
    if not directory.exists():
        return {}
    tombstones: dict[str, dict] = {}
    for path in sorted(directory.glob("*.json")):
        tombstone = _read_deletion_tombstone(path)
        tombstones[tombstone["doc_id"]] = tombstone
    return tombstones


def _write_deletion_phase_locked(
    doc_id: str, phase: str, tombstone: dict | None = None
) -> dict:
    if phase not in _DELETION_PHASES:
        raise ValueError(f"invalid deletion phase: {phase}")
    path = _deletion_tombstone_path(doc_id)
    if tombstone is None and path.exists():
        tombstone = _read_deletion_tombstone(path)
    target = {
        **(tombstone or {}),
        "doc_id": doc_id,
        "generation": (tombstone or {}).get("generation") or uuid.uuid4().hex,
        "created_at": (tombstone or {}).get("created_at") or _now(),
        "phase": phase,
        "updated_at": _now(),
    }
    _atomic_write_text(
        path, json.dumps(target, ensure_ascii=False, indent=2)
    )
    return target


def _is_tombstoned(doc_id: str) -> bool:
    return _deletion_tombstone_path(doc_id).exists()


def _ensure_document_writable_locked(doc_id: str) -> None:
    if _is_tombstoned(doc_id):
        raise RuntimeError(f"document deletion is in progress: {doc_id}")


def deletion_pending(doc_id: str) -> bool:
    with _doc_lock(doc_id):
        return _is_tombstoned(doc_id)


@contextmanager
def document_publication_guard(doc_id: str):
    """Serialize ES indexing/current publication with document deletion."""
    with _doc_lock(doc_id):
        _ensure_document_writable_locked(doc_id)
        if not doc_dir(doc_id).is_dir():
            raise RuntimeError(f"document no longer exists: {doc_id}")
        yield


def ir_path(doc_id: str) -> Path:
    return doc_dir(doc_id) / "ir.json"


def preview_path(doc_id: str) -> Path:
    return doc_dir(doc_id) / "preview.md"


def version_dir(doc_id: str, version_id: str) -> Path:
    _validate_version_id(version_id)
    return doc_dir(doc_id) / "versions" / version_id


def source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_version_id(
    source_digest: str,
    parser_schema_version: str,
    parse_config: dict[str, Any] | None,
) -> str:
    """Return a stable, path-safe ID for source and parser inputs."""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", source_digest):
        raise ValueError("source_digest must be a SHA-256 hex digest")
    normalized_config = json.loads(
        json.dumps(
            parse_config or {},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    payload = {
        "parse_config": normalized_config,
        "parser_schema_version": str(parser_schema_version),
        "source_sha256": source_digest.lower(),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _upsert_index_row(items: list[dict], row: dict) -> None:
    for index, item in enumerate(items):
        if item.get("id") == row["id"]:
            items[index] = row
            return
    items.insert(0, row)


def _read_publication_journal(path: Path) -> dict:
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"publication journal is unreadable: {path.name}") from exc
    if not isinstance(journal, dict):
        raise RuntimeError(f"publication journal is invalid: {path.name}")
    doc_id = journal.get("doc_id")
    generation = journal.get("generation")
    index_existed = journal.get("index_existed")
    meta = journal.get("meta")
    index_row = journal.get("index_row")
    if (
        not isinstance(doc_id, str)
        or not doc_id
        or not isinstance(generation, str)
        or not generation
        or type(index_existed) is not bool
        or not isinstance(meta, dict)
        or meta.get("id") != doc_id
        or meta.get("publication_generation") != generation
        or not isinstance(index_row, dict)
        or index_row.get("id") != doc_id
        or index_row.get("publication_generation") != generation
    ):
        raise RuntimeError(f"publication journal is invalid: {path.name}")
    return journal


def _reconcile_publication_locked(doc_id: str) -> None:
    path = _publication_journal_path(doc_id)
    if not path.exists():
        return
    _ensure_document_writable_locked(doc_id)
    journal = _read_publication_journal(path)
    if journal["doc_id"] != doc_id:
        raise RuntimeError(f"publication journal document mismatch: {path.name}")
    with _index_lock:
        _write_meta_file(journal["meta"])
        items = _load_publication_index(
            allow_missing=not journal["index_existed"]
        )
        _upsert_index_row(items, journal["index_row"])
        _save_index(items)
        path.unlink()


def reconcile_pending_publications() -> None:
    """Complete durable metadata/index publications left by interrupted writes."""
    directory = _publication_journal_dir()
    if not directory.exists():
        return
    for path in sorted(directory.glob("*.json")):
        journal = _read_publication_journal(path)
        doc_id = journal["doc_id"]
        if path != _publication_journal_path(doc_id):
            raise RuntimeError(f"publication journal path is invalid: {path.name}")
        with _doc_lock(doc_id):
            _reconcile_publication_locked(doc_id)


def load_meta(doc_id: str) -> dict | None:
    with _doc_lock(doc_id):
        if _is_tombstoned(doc_id):
            return None
        _reconcile_publication_locked(doc_id)
        p = meta_path(doc_id)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None


def _current_artifact_path(doc_id: str, filename: str) -> Path | None:
    meta = load_meta(doc_id)
    version_id = (meta or {}).get("current_version_id")
    if not isinstance(version_id, str):
        return None
    try:
        candidate = version_dir(doc_id, version_id) / filename
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def save_meta(meta: dict) -> None:
    doc_id = meta["id"]
    with _doc_lock(doc_id):
        _ensure_document_writable_locked(doc_id)
        _reconcile_publication_locked(doc_id)
        if not doc_dir(doc_id).is_dir():
            raise RuntimeError(f"document no longer exists: {doc_id}")
        target_meta = dict(meta)
        target_meta["updated_at"] = _now()
        generation = uuid.uuid4().hex
        target_meta["publication_generation"] = generation
        target_row = _index_row(target_meta)
        with _index_lock:
            index_existed = INDEX_FILE.exists()
            items = _load_publication_index(allow_missing=True)
            _upsert_index_row(items, target_row)
            journal_path = _publication_journal_path(doc_id)
            _atomic_write_text(
                journal_path,
                json.dumps(
                    {
                        "doc_id": doc_id,
                        "generation": generation,
                        "index_existed": index_existed,
                        "meta": target_meta,
                        "index_row": target_row,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            _write_meta_file(target_meta)
            _save_index(items)
            journal_path.unlink()
        meta.clear()
        meta.update(target_meta)


def _index_row(meta: dict) -> dict:
    row = {
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
        "visibility_migrated": True,
        "publication_generation": meta.get("publication_generation"),
    }
    if meta.get("current_version_id"):
        row["current_version_id"] = meta["current_version_id"]
    if meta.get("indexed_version_id"):
        row["indexed_version_id"] = meta["indexed_version_id"]
    return row


def _load_visibility_index_locked() -> list[dict]:
    if not INDEX_FILE.exists():
        try:
            storage_empty = not UPLOADS_DIR.exists() or next(
                UPLOADS_DIR.iterdir(), None
            ) is None
        except OSError as exc:
            raise RuntimeError("document storage state is unreadable") from exc
        if storage_empty:
            return []
        raise RuntimeError("document visibility index is missing")
    try:
        items = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("document visibility index is unreadable") from exc
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise RuntimeError("document visibility index has invalid structure")
    return items


def migrate_index_visibility() -> None:
    """Upgrade pre-versioning index rows once, then persist the snapshot source."""
    reconcile_pending_publications()
    with _index_lock:
        items = _load_visibility_index_locked()
        tombstoned_doc_ids = set(_deletion_tombstones_locked())
        changed = False
        for item in items:
            if item.get("id") in tombstoned_doc_ids:
                continue
            if item.get("visibility_migrated") is True:
                continue
            doc_id = item.get("id")
            path = meta_path(doc_id or "")
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"visibility metadata is unreadable for document: {doc_id}"
                ) from exc
            if not isinstance(meta, dict) or meta.get("id") != doc_id:
                raise RuntimeError(f"visibility metadata is invalid for document: {doc_id}")
            if meta.get("current_version_id"):
                item["current_version_id"] = meta["current_version_id"]
            if meta.get("indexed_version_id"):
                item["indexed_version_id"] = meta["indexed_version_id"]
            item["visibility_migrated"] = True
            changed = True
        if changed:
            _save_index(items)


def index_visibility_snapshot() -> tuple[list[str], list[str], list[str]]:
    """Return active keys plus versioned and legacy IDs from the list index."""
    migrate_index_visibility()
    with _index_lock:
        items = _load_visibility_index_locked()
        tombstoned_doc_ids = set(_deletion_tombstones_locked())

    active_keys: list[str] = []
    versioned_doc_ids: list[str] = []
    legacy_doc_ids: list[str] = []
    for item in items:
        doc_id = item.get("id")
        version_id = item.get("indexed_version_id")
        if not doc_id or doc_id in tombstoned_doc_ids:
            continue
        if version_id:
            active_keys.append(f"{doc_id}:{version_id}")
            versioned_doc_ids.append(doc_id)
        else:
            legacy_doc_ids.append(doc_id)
    return (
        sorted(active_keys),
        sorted(versioned_doc_ids),
        sorted(legacy_doc_ids),
    )


def list_docs(
    q: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict], int]:
    reconcile_pending_publications()
    with _index_lock:
        items = _load_index()
        tombstoned_doc_ids = set(_deletion_tombstones_locked())
        items = [item for item in items if item.get("id") not in tombstoned_doc_ids]
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
    with _doc_lock(doc_id):
        _ensure_document_writable_locked(doc_id)
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
    with _doc_lock(doc_id):
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
    with _doc_lock(doc_id):
        _ensure_document_writable_locked(doc_id)
        _atomic_write_text(
            ir_path(doc_id), json.dumps(ir, ensure_ascii=False, indent=2)
        )


def load_ir(doc_id: str) -> dict | None:
    p = _current_artifact_path(doc_id, "ir.json") or ir_path(doc_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_preview_md(doc_id: str, md: str) -> None:
    with _doc_lock(doc_id):
        _ensure_document_writable_locked(doc_id)
        _atomic_write_text(preview_path(doc_id), md)


def load_preview_md(doc_id: str) -> str:
    p = _current_artifact_path(doc_id, "preview.md") or preview_path(doc_id)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def write_version_artifacts(
    doc_id: str,
    version_id: str,
    ir: dict,
    preview_md: str,
    manifest: dict,
    evidence_spans: dict | None = None,
) -> Path:
    """Atomically create a complete immutable version directory."""
    with _doc_lock(doc_id):
        _ensure_document_writable_locked(doc_id)
        final_dir = version_dir(doc_id, version_id)
        if manifest.get("version_id") != version_id:
            raise ValueError("manifest version_id does not match directory version_id")
        versions_dir = final_dir.parent
        versions_dir.mkdir(parents=True, exist_ok=True)
        if final_dir.exists():
            raise FileExistsError(f"document version already exists: {version_id}")

        temporary_dir = versions_dir / f".{version_id}.{uuid.uuid4().hex}.tmp"
        temporary_dir.mkdir()
        try:
            (temporary_dir / "ir.json").write_text(
                json.dumps(ir, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (temporary_dir / "preview.md").write_text(preview_md, encoding="utf-8")
            (temporary_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if evidence_spans is not None:
                (temporary_dir / "evidence_spans.json").write_text(
                    json.dumps(evidence_spans, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            temporary_dir.replace(final_dir)
        except Exception:
            if temporary_dir.exists():
                shutil.rmtree(temporary_dir, ignore_errors=True)
            raise
        return final_dir


def version_artifacts_match(
    doc_id: str,
    version_id: str,
    ir: dict,
    preview_md: str,
    manifest: dict,
) -> bool:
    """Verify that a deterministic ID refers to exactly the parsed output."""
    try:
        directory = version_dir(doc_id, version_id)
        stored_ir = json.loads((directory / "ir.json").read_text("utf-8"))
        stored_preview = (directory / "preview.md").read_text("utf-8")
        stored_manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    return (
        stored_ir == ir
        and stored_preview == preview_md
        and stored_manifest == manifest
    )


def set_current_version(
    doc_id: str, version_id: str, *, status: str | None = None, **fields: Any
) -> bool:
    """Publish a complete, successful version as the document's current version."""
    try:
        directory = version_dir(doc_id, version_id)
    except ValueError:
        return False
    required = ("ir.json", "preview.md", "manifest.json")
    if not all((directory / name).is_file() for name in required):
        return False
    try:
        manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if manifest.get("version_id") != version_id or manifest.get("status") != "ready":
        return False

    with _doc_lock(doc_id):
        meta = load_meta(doc_id)
        if not meta:
            return False
        meta["current_version_id"] = version_id
        if status is not None:
            meta["status"] = status
            meta["stage_label"] = STATUS_LABELS.get(status, status)
            if status != "failed":
                meta["error"] = None
        meta.update(fields)
        save_meta(meta)
    return True


def delete_doc(doc_id: str) -> bool:
    with _doc_lock(doc_id):
        _reconcile_publication_locked(doc_id)
        with _index_lock:
            items = _load_publication_index(allow_missing=False)
            directory = doc_dir(doc_id)
            row_exists = any(item.get("id") == doc_id for item in items)
            tombstone_path = _deletion_tombstone_path(doc_id)
            if not directory.exists() and not row_exists and not tombstone_path.exists():
                return False
            tombstone = (
                _read_deletion_tombstone(tombstone_path)
                if tombstone_path.exists()
                else _write_deletion_phase_locked(doc_id, "pending_filesystem")
            )
            if tombstone["phase"] == "complete":
                return True
            if directory.exists():
                shutil.rmtree(directory)
            if directory.exists():
                raise RuntimeError(f"document directory deletion did not complete: {doc_id}")
            if tombstone["phase"] == "pending_filesystem":
                tombstone = _write_deletion_phase_locked(
                    doc_id, "pending_index", tombstone
                )
            items = [item for item in items if item.get("id") != doc_id]
            _save_index(items)
            if tombstone["phase"] != "pending_es":
                _write_deletion_phase_locked(doc_id, "pending_es", tombstone)
            return True


def mark_deletion_complete(doc_id: str) -> None:
    with _doc_lock(doc_id):
        with _index_lock:
            path = _deletion_tombstone_path(doc_id)
            if not path.exists():
                raise RuntimeError(f"deletion tombstone is missing: {doc_id}")
            tombstone = _read_deletion_tombstone(path)
            if doc_dir(doc_id).exists():
                raise RuntimeError(f"document directory still exists: {doc_id}")
            items = _load_publication_index(allow_missing=False)
            if any(item.get("id") == doc_id for item in items):
                raise RuntimeError(f"document index row still exists: {doc_id}")
            _write_deletion_phase_locked(doc_id, "complete", tombstone)


def reconcile_pending_deletions() -> None:
    """Finish durable local and Elasticsearch deletion phases after restart."""
    with _index_lock:
        pending = [
            doc_id
            for doc_id, tombstone in _deletion_tombstones_locked().items()
            if tombstone["phase"] != "complete"
        ]
    from services.document_pipeline import delete_doc_from_index

    for doc_id in sorted(pending):
        delete_doc(doc_id)
        delete_doc_from_index(doc_id)
        mark_deletion_complete(doc_id)


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
