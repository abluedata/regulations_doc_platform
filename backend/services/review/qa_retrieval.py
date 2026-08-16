"""Immutable document retrieval and canonical citation construction."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, Callable
from uuid import uuid4

from services.knowledge.document_store import UPLOADS_DIR
from services.knowledge.search import DocumentScope, search_document


class CitationValidationError(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceCandidate:
    candidate_id: str
    scope: DocumentScope
    block_id: str
    canonical_text: str
    section_path: list[str]
    locator: dict[str, Any]
    chunk_id: int | None = None
    filename: str = ""
    score: float = 0.0


@dataclass(frozen=True)
class Citation:
    citation_id: str
    document_id: str
    document_version_id: str
    filename: str
    block_id: str
    chunk_id: int | None
    section_path: list[str]
    quote: str
    quote_start: int
    quote_end: int
    locator: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _load_version_ir(scope: DocumentScope) -> tuple[dict[str, Any], str]:
    """加载版本 IR，返回 (IR, 真实版本号)。

    旧数据兼容：成员 document_version_id 可能是上传接口返回的文档 ID（legacy 别名），
    此时回退到 meta.json 的 current_version_id；引用必须携带真实版本号。
    """
    candidate_ids: list[str] = []
    if _looks_like_version_id(scope.document_version_id):
        candidate_ids.append(scope.document_version_id)
    current = _current_version_id(scope.document_id)
    if current and _looks_like_version_id(current):
        candidate_ids.append(current)
    for version_id in dict.fromkeys(candidate_ids):
        path = UPLOADS_DIR / scope.document_id / "versions" / version_id / "ir.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            raise ValueError("document version IR must be an object")
        return payload, version_id
    raise FileNotFoundError(f"document version IR unavailable: {scope.document_id}:{scope.document_version_id}")


def _looks_like_version_id(value: str | None) -> bool:
    return bool(value) and re.fullmatch(r"[0-9a-f]{64}", str(value)) is not None


def _current_version_id(doc_id: str) -> str | None:
    try:
        meta = json.loads((UPLOADS_DIR / doc_id / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    current = meta.get("current_version_id") if isinstance(meta, dict) else None
    return current if isinstance(current, str) else None


def _block_text(block: dict[str, Any]) -> str:
    return str(block.get("text") or block.get("markdown") or block.get("html") or "")


def _query_chars(query: str) -> set[str]:
    return {char.lower() for char in query if char.isalnum() and not char.isspace()}


def _useful_text(text: str) -> str:
    return "".join(char for char in text if not char.isspace())


def _usable_block(text: str) -> bool:
    """跳过纯空白、目录符号等无信息块。"""
    return len(_useful_text(text)) >= 4


MIN_ES_SCORE = 0.1


def retrieve_evidence(
    query: str,
    scope: DocumentScope,
    *,
    filename: str = "",
    searcher: Callable[..., list[dict[str, Any]]] = search_document,
    k: int = 6,
) -> list[EvidenceCandidate]:
    ir, version_id = _load_version_ir(scope)
    effective_scope = DocumentScope(scope.document_id, version_id)
    blocks = [block for block in ir.get("blocks", []) if isinstance(block, dict) and _usable_block(_block_text(block))]
    block_by_id = {str(block.get("block_id")): block for block in blocks if block.get("block_id")}
    try:
        hits = searcher(query, scope=effective_scope, k=k)
    except Exception:
        hits = []

    selected: list[tuple[dict[str, Any], int | None, float]] = []
    seen: set[str] = set()
    best_es_score = 0.0
    for hit in hits:
        best_es_score = max(best_es_score, float(hit.get("score") or 0.0))
        block_id = str(hit.get("block_id") or "")
        block = block_by_id.get(block_id)
        if block is None:
            content = str(hit.get("content") or "")
            block = next((candidate for candidate in blocks if _block_text(candidate) and _block_text(candidate) in content), None)
        if block is None or str(block.get("block_id")) in seen:
            continue
        seen.add(str(block.get("block_id")))
        selected.append((block, hit.get("chunk_id"), float(hit.get("score") or 0.0)))

    # ES 得分过低（噪音命中）或不可用时，退回子串 IDF 加权排名
    if not selected or best_es_score < MIN_ES_SCORE:
        ranked = _substring_rank(query, blocks, k)
        query_chars = _query_chars(query)
        selected = [
            (block, None, float(len(query_chars & _query_chars(_block_text(block)))))
            for block in ranked
            if len(query_chars & _query_chars(_block_text(block))) > 0
        ]

    return [
        EvidenceCandidate(
            candidate_id=f"c{index}", scope=effective_scope, block_id=str(block.get("block_id") or f"block-{index}"),
            canonical_text=_block_text(block), section_path=list(block.get("section_path") or []),
            locator=dict(block.get("locator") or _page_locator(block)), chunk_id=chunk_id,
            filename=filename, score=score,
        )
        for index, (block, chunk_id, score) in enumerate(selected, 1)
    ]


def _substring_rank(query: str, blocks: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    """子串 IDF 加权排名：罕见子串（内容词）权重高，通用词权重低。

    把问题切成 2~4 字子串，按其在全部块中的文档频率加权（DF 低 → 判别力强），
    对每个块累计命中子串的权重，取前 k 个。对 OCR 碎片与目录/大表格同样鲁棒。
    """
    q = _useful_text(query)
    if len(q) < 2:
        return blocks[:k]
    subs: set[str] = set()
    for length in (4, 3, 2):
        for i in range(len(q) - length + 1):
            subs.add(q[i : i + length])
    texts = [_useful_text(_block_text(block)) for block in blocks]
    total = max(1, len(texts))
    df: dict[str, int] = {}
    for sub in subs:
        df[sub] = sum(1 for text in texts if sub in text)
    weights = {
        sub: (len(sub) ** 2) * (1 + math.log(total / max(1, df[sub])))
        for sub in subs
    }
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for index, (block, text) in enumerate(zip(blocks, texts)):
        score = sum(weights[sub] for sub in subs if sub in text)
        if score > 0:
            length = max(1, len(text))
            # 长度归一化：下限 20 防碎片块爆分，上限 300 防长表格堆分
            normalized = score / math.sqrt(min(max(length, 20), 300))
            # 内容带奖励：20~300 字符的正文条款块
            if 20 <= length <= 300:
                normalized *= 1.2
            scored.append((normalized, index, block))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:k]]


def _page_locator(block: dict[str, Any]) -> dict[str, Any]:
    page = block.get("page_start") or block.get("page")
    return {"kind": "pdf", "page_number": page, "precision": "page", "rects": []} if page else {
        "kind": "block", "block_id": block.get("block_id"), "precision": "block"
    }


def evidence_snippet(text: str, query: str, radius: int = 600) -> str:
    """截取证据文本中与问题相关的窗口（否则长表格前缀截断会丢失关键行）。"""
    q = _useful_text(query)
    if len(q) < 2 or not text:
        return text[: radius * 3]
    best_pos, best_len = -1, 0
    for length in range(min(len(q), 8), 1, -1):
        for i in range(len(q) - length + 1):
            sub = q[i : i + length]
            pos = text.find(sub)
            if pos >= 0:
                best_pos, best_len = pos, length
                break
        if best_pos >= 0:
            break
    if best_pos < 0:
        return text[: radius * 3]
    start = max(0, best_pos - radius)
    end = min(len(text), best_pos + best_len + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end] + suffix


def build_citation(candidate: EvidenceCandidate, *, quote: str | None = None) -> Citation:
    canonical = candidate.canonical_text
    selected = quote if quote is not None else canonical
    start = canonical.find(selected)
    if not selected or start < 0:
        raise CitationValidationError("citation quote is not an exact canonical substring")
    return Citation(
        citation_id=str(uuid4()), document_id=candidate.scope.document_id,
        document_version_id=candidate.scope.document_version_id, filename=candidate.filename,
        block_id=candidate.block_id, chunk_id=candidate.chunk_id, section_path=candidate.section_path,
        quote=selected, quote_start=start, quote_end=start + len(selected), locator=candidate.locator,
    )


__all__ = ["Citation", "CitationValidationError", "DocumentScope", "EvidenceCandidate", "build_citation", "retrieve_evidence"]
