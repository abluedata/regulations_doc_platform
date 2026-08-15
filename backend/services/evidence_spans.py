"""
证据坐标服务：把 MinerU original_content_list 精简为版本级 evidence_spans.json。

职责：
  1. 解析管线落库：新解析的版本在 write_version_artifacts 时一并写入
     evidence_spans.json（PDF 原始坐标 pt，page 为 1-based）。
  2. 存量 backfill：按 meta 解析时间窗 + 文本重叠匹配 .data/mineru_output
     下的 mineru job 目录，为已 ready 的版本补写 evidence_spans.json。
  3. 引用查找：find_span_for_quote 供 findings API 回填真实 evidence_anchor。

evidence_spans.json 结构：
  {"spans": [{"text": "...", "bbox": [x0, y0, x1, y1], "page": 1}, ...],
   "task_id": "...", "engine": "..."}
bbox 为 PDF 原始坐标（pt），原点左上、y 轴向下；page 为 1-based 页码。
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.config import DATA_ROOT
from services.document_store import (
    list_docs,
    load_ir,
    load_meta,
    load_preview_md,
    version_dir,
)

EVIDENCE_SPANS_FILENAME = "evidence_spans.json"

# 解析时间窗左右放宽量（mineru job 目录 mtime 与文档解析时间段对齐）
_PARSE_WINDOW_SLACK = timedelta(minutes=10)
# 时间窗候选的文本重叠验证：至少 N 个 >=6 字符的 span 文本命中文档文本
_MIN_OVERLAP_HITS = 3

_ensure_cache: dict[str, dict | None] = {}
_ensure_cache_lock = threading.Lock()

_NUMERIC_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def mineru_output_root() -> Path:
    env = os.environ.get("MINERU_API_OUTPUT_ROOT", "").strip()
    if env:
        return Path(env)
    return Path(DATA_ROOT) / "mineru_output"


def normalize_text(text: Any) -> str:
    """折叠所有空白（含换行/全角空格），便于跨行匹配。"""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _normalize_bbox(raw: Any) -> list[float] | None:
    if isinstance(raw, dict):
        raw = [raw.get("x0"), raw.get("y0"), raw.get("x1"), raw.get("y1")]
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        values = [float(v) for v in raw]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in values):
        return None
    x0, y0, x1, y1 = values
    if x1 <= x0 or y1 <= y0 or x0 < 0 or y0 < 0:
        return None
    return values


def spans_from_content_list(
    items: Any, *, task_id: str | None = None, engine: str | None = None
) -> dict[str, Any]:
    """把 original_content_list.json 精简为 evidence_spans 结构（page 1-based）。"""
    spans: list[dict] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        text = str(it.get("text") or "").strip()
        if not text:
            continue
        bbox = _normalize_bbox(it.get("bbox") or it.get("box") or it.get("rect"))
        if bbox is None:
            continue
        page_idx = it.get("page_idx", it.get("page", it.get("page_no")))
        if not isinstance(page_idx, int) or page_idx < 0:
            continue
        spans.append({"text": text, "bbox": bbox, "page": int(page_idx) + 1})
    payload: dict[str, Any] = {"spans": spans}
    if task_id:
        payload["task_id"] = str(task_id)
    if engine:
        payload["engine"] = str(engine)
    return payload


def find_span_for_quote(spans: list[dict], quote: Any) -> dict | None:
    """返回归一化文本包含 quote 的 span；找不到返回 None。"""
    q = normalize_text(quote)
    if not q:
        return None
    fallback: list[dict] = []
    for span in spans or []:
        if not isinstance(span, dict):
            continue
        text = normalize_text(span.get("text"))
        if not text:
            continue
        if q in text:
            return span
        fallback.append(span)
    # 兜底：去掉全部空白再匹配（PDF 换行 / 断字导致的空白错位）
    q_flat = re.sub(r"\s+", "", q)
    if len(q_flat) >= 2:
        for span in fallback:
            if q_flat in re.sub(r"\s+", "", normalize_text(span.get("text"))):
                return span
    return None


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def evidence_spans_path(doc_id: str, version_id: str) -> Path | None:
    try:
        return version_dir(doc_id, version_id) / EVIDENCE_SPANS_FILENAME
    except ValueError:
        return None


def write_evidence_spans(doc_id: str, version_id: str, spans: dict) -> Path | None:
    """把 evidence spans 写入版本目录（版本目录可已存在，用于 backfill）。"""
    path = evidence_spans_path(doc_id, version_id)
    if path is None:
        return None
    _atomic_write_json(path, spans)
    return path


def _resolve_version_dir(doc_id: str, version_id: str | None = None) -> Path | None:
    """解析版本目录：显式 version_id 优先，其次 meta.current_version_id。"""
    if version_id:
        try:
            explicit = version_dir(doc_id, version_id)
        except ValueError:
            explicit = None
        if explicit is not None and explicit.is_dir():
            return explicit
    meta = load_meta(doc_id)
    current = (meta or {}).get("current_version_id")
    if not isinstance(current, str) or not current:
        return None
    try:
        directory = version_dir(doc_id, current)
    except ValueError:
        return None
    return directory if directory.is_dir() else None


def load_evidence_spans(
    doc_id: str, version_id: str | None = None
) -> dict | None:
    """读取版本 evidence_spans.json；不存在或损坏返回 None。"""
    directory = _resolve_version_dir(doc_id, version_id)
    if directory is None:
        return None
    path = directory / EVIDENCE_SPANS_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("spans"), list):
        return None
    return data


def ensure_doc_evidence_spans(
    doc_id: str, version_id: str | None = None
) -> dict | None:
    """读取 evidence spans；缺失时尝试一次 backfill（进程内缓存结果）。"""
    key = f"{doc_id}:{version_id or ''}"
    with _ensure_cache_lock:
        if key in _ensure_cache:
            return _ensure_cache[key]
    spans = load_evidence_spans(doc_id, version_id)
    if spans is None:
        try:
            spans = backfill_doc_evidence_spans(doc_id, version_id)
        except Exception:
            spans = None
    with _ensure_cache_lock:
        _ensure_cache[key] = spans
    return spans


def clear_ensure_cache() -> None:
    with _ensure_cache_lock:
        _ensure_cache.clear()


# ─── backfill：doc_id → mineru job 目录匹配 ─────────────────

def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _content_list_candidates(job_dir: Path) -> Path | None:
    for rel in (
        "original/auto/original_content_list.json",
        "original/original_content_list.json",
    ):
        path = job_dir / rel
        if path.is_file():
            return path
    matches = sorted(job_dir.glob("**/original_content_list.json"))
    return matches[0] if matches else None


def _read_content_list(path: Path) -> list | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, list) else None


def _doc_text(doc_id: str) -> str:
    parts = [load_preview_md(doc_id)]
    ir = load_ir(doc_id) or {}
    for block in ir.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        parts.append(block.get("text") or "")
        parts.append(block.get("markdown") or "")
    return normalize_text("\n".join(parts))


def _overlap_hits(content_list: list, doc_text: str) -> int:
    hits = 0
    sampled = 0
    for it in content_list:
        if not isinstance(it, dict):
            continue
        text = normalize_text(it.get("text"))
        if len(text) < 6:
            continue
        sampled += 1
        if text in doc_text:
            hits += 1
        if sampled >= 300:
            break
    return hits


def _job_mtime(content_list: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(content_list.stat().st_mtime)
    except OSError:
        return None


def find_mineru_content_list(meta: dict, doc_text: str) -> Path | None:
    """按解析时间窗 + 文本重叠为文档匹配 mineru job 的 content_list 文件。"""
    root = mineru_output_root()
    if not root.is_dir():
        return None
    created = _parse_time(meta.get("created_at"))
    updated = _parse_time(meta.get("updated_at"))
    window_lo = created - _PARSE_WINDOW_SLACK if created else None
    window_hi = updated + _PARSE_WINDOW_SLACK if updated else None

    candidates: list[Path] = []
    try:
        job_dirs = sorted(root.iterdir())
    except OSError:
        return None
    for job_dir in job_dirs:
        if not job_dir.is_dir():
            continue
        content_list = _content_list_candidates(job_dir)
        if content_list is None:
            continue
        mtime = _job_mtime(content_list)
        if mtime is None:
            continue
        if window_lo is not None and mtime < window_lo:
            continue
        if window_hi is not None and mtime > window_hi:
            continue
        candidates.append(content_list)

    best: Path | None = None
    best_score = 0
    for content_list in candidates:
        items = _read_content_list(content_list)
        if items is None:
            continue
        score = _overlap_hits(items, doc_text)
        if score > best_score:
            best, best_score = content_list, score
    if best is None or best_score < _MIN_OVERLAP_HITS:
        return None
    return best


def backfill_doc_evidence_spans(
    doc_id: str, version_id: str | None = None
) -> dict | None:
    """为已 ready 的存量文档一次性生成 evidence_spans.json。"""
    meta = load_meta(doc_id)
    if not meta:
        return None
    if version_id is None and meta.get("status") != "ready":
        return None
    directory = _resolve_version_dir(doc_id, version_id)
    if directory is None:
        return None
    path = directory / EVIDENCE_SPANS_FILENAME
    if path.is_file():
        return load_evidence_spans(doc_id, version_id)

    content_list = find_mineru_content_list(meta, _doc_text(doc_id))
    if content_list is None:
        return None
    items = _read_content_list(content_list)
    if items is None:
        return None
    spans = spans_from_content_list(
        items,
        task_id=content_list.parent.parent.parent.name,
        engine=meta.get("engine"),
    )
    if not spans["spans"]:
        return None
    spans["source"] = "mineru-output-backfill"
    write_evidence_spans(doc_id, directory.name, spans)
    # 可选加分项：文本前缀匹配回填 ir.json 页码
    try:
        backfill_ir_pages(doc_id, directory.name, spans=spans)
    except Exception:
        pass
    return spans


def backfill_ir_pages(
    doc_id: str, version_id: str | None = None, spans: dict | None = None
) -> int:
    """可选加分项：用 spans 文本前缀匹配回填 ir.json 的 page_start/page_end。

    只处理 page_start 为空的 block；匹配不到保持原样。幂等。
    """
    directory = _resolve_version_dir(doc_id, version_id)
    if directory is None:
        return 0
    ir_path = directory / "ir.json"
    try:
        ir = json.loads(ir_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(ir, dict):
        return 0
    if spans is None:
        spans = load_evidence_spans(doc_id, version_id)
    span_list = (spans or {}).get("spans") or []
    changed = 0
    for block in ir.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        if block.get("page_start"):
            continue
        text = normalize_text(block.get("text") or block.get("markdown"))
        if not text:
            continue
        page = _match_block_page(text, span_list)
        if page:
            block["page_start"] = page
            block["page_end"] = page
            changed += 1
    if changed:
        _atomic_write_json(ir_path, ir)
    return changed


def _match_block_page(text: str, span_list: list[dict]) -> int | None:
    """按文本前缀匹配 block → span 页码；取最长公共前缀的候选。"""
    best_page: int | None = None
    best_prefix = 0
    for span in span_list:
        if not isinstance(span, dict):
            continue
        span_text = normalize_text(span.get("text"))
        if not span_text:
            continue
        overlap = 0
        limit = min(len(text), len(span_text))
        for i in range(limit):
            if text[i] != span_text[i]:
                break
            overlap = i + 1
        # 要求至少 8 字符的公共前缀，或短文本完全包含
        contained = text in span_text or span_text in text
        if overlap >= 8 or (contained and overlap >= 4):
            if overlap > best_prefix:
                best_prefix = overlap
                best_page = int(span["page"])
    return best_page


def backfill_all_ready_docs() -> list[dict]:
    """启动时懒生成：为所有 ready 文档补齐 evidence_spans.json（幂等）。"""
    results: list[dict] = []
    docs, _ = list_docs(status="ready", page=1, page_size=200)
    for row in docs:
        doc_id = row.get("id")
        if not doc_id:
            continue
        try:
            spans = ensure_doc_evidence_spans(doc_id)
            # ir.json 页码回填（幂等，仅对已生成 spans 的文档）
            if spans:
                try:
                    backfill_ir_pages(doc_id, spans=spans)
                except Exception:
                    pass
            results.append(
                {
                    "doc_id": doc_id,
                    "ok": bool(spans),
                    "spans": len(spans["spans"]) if spans else 0,
                }
            )
        except Exception as exc:  # 单个文档失败不阻断其他文档
            results.append({"doc_id": doc_id, "ok": False, "error": str(exc)[:200]})
    return results


def enrich_evidence_anchor(finding: dict) -> dict:
    """用 evidence_spans 回填 finding 的 evidence_anchor；找不到时保持原样。"""
    anchor = finding.get("evidence_anchor")
    if not isinstance(anchor, dict):
        return finding
    if anchor.get("precision") == "rect":
        return finding
    quote = finding.get("quote") or anchor.get("quote") or ""
    doc_id = finding.get("document_id") or anchor.get("document_id") or ""
    version_id = (
        finding.get("document_version_id") or anchor.get("document_version_id") or ""
    )
    if not doc_id or not quote:
        return finding
    spans = ensure_doc_evidence_spans(doc_id, version_id or None)
    span = find_span_for_quote((spans or {}).get("spans") or [], quote)
    if span is None:
        return finding
    page = int(span["page"])
    x0, y0, x1, y1 = (float(v) for v in span["bbox"])
    enriched_anchor = dict(anchor)
    enriched_anchor.update(
        {
            "precision": "rect",
            "validation_status": "exact",
            "page_number": page,
            "coordinate_space": "pdf-pt",
            "rects": [
                {
                    "page": page,
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                    "space": "pdf-pt",
                }
            ],
        }
    )
    enriched = dict(finding)
    enriched["evidence_anchor"] = enriched_anchor
    return enriched


__all__ = [
    "EVIDENCE_SPANS_FILENAME",
    "backfill_all_ready_docs",
    "backfill_doc_evidence_spans",
    "backfill_ir_pages",
    "clear_ensure_cache",
    "enrich_evidence_anchor",
    "ensure_doc_evidence_spans",
    "find_mineru_content_list",
    "find_span_for_quote",
    "load_evidence_spans",
    "mineru_output_root",
    "normalize_text",
    "spans_from_content_list",
    "write_evidence_spans",
]
