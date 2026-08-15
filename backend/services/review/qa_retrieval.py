"""Immutable document retrieval and canonical citation construction."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Callable
from uuid import uuid4

from services.document_store import UPLOADS_DIR
from services.search import DocumentScope, search_document


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


def _load_version_ir(scope: DocumentScope) -> dict[str, Any]:
    path = UPLOADS_DIR / scope.document_id / "versions" / scope.document_version_id / "ir.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FileNotFoundError(f"document version IR unavailable: {scope.document_id}:{scope.document_version_id}") from exc
    if not isinstance(payload, dict):
        raise ValueError("document version IR must be an object")
    return payload


def _block_text(block: dict[str, Any]) -> str:
    return str(block.get("text") or block.get("markdown") or block.get("html") or "")


def _query_chars(query: str) -> set[str]:
    return {char.lower() for char in query if char.isalnum() and not char.isspace()}


def retrieve_evidence(
    query: str,
    scope: DocumentScope,
    *,
    filename: str = "",
    searcher: Callable[..., list[dict[str, Any]]] = search_document,
    k: int = 6,
) -> list[EvidenceCandidate]:
    ir = _load_version_ir(scope)
    blocks = [block for block in ir.get("blocks", []) if isinstance(block, dict) and _block_text(block)]
    block_by_id = {str(block.get("block_id")): block for block in blocks if block.get("block_id")}
    try:
        hits = searcher(query, scope=scope, k=k)
    except Exception:
        hits = []

    selected: list[tuple[dict[str, Any], int | None, float]] = []
    seen: set[str] = set()
    for hit in hits:
        block_id = str(hit.get("block_id") or "")
        block = block_by_id.get(block_id)
        if block is None:
            content = str(hit.get("content") or "")
            block = next((candidate for candidate in blocks if _block_text(candidate) and _block_text(candidate) in content), None)
        if block is None or str(block.get("block_id")) in seen:
            continue
        seen.add(str(block.get("block_id")))
        selected.append((block, hit.get("chunk_id"), float(hit.get("score") or 0.0)))

    if not selected:
        query_chars = _query_chars(query)
        ranked = sorted(
            blocks,
            key=lambda block: len(query_chars & _query_chars(_block_text(block))),
            reverse=True,
        )
        selected = [(block, None, float(len(query_chars & _query_chars(_block_text(block))))) for block in ranked[:k]]

    return [
        EvidenceCandidate(
            candidate_id=f"c{index}", scope=scope, block_id=str(block.get("block_id") or f"block-{index}"),
            canonical_text=_block_text(block), section_path=list(block.get("section_path") or []),
            locator=dict(block.get("locator") or _page_locator(block)), chunk_id=chunk_id,
            filename=filename, score=score,
        )
        for index, (block, chunk_id, score) in enumerate(selected, 1)
    ]


def _page_locator(block: dict[str, Any]) -> dict[str, Any]:
    page = block.get("page_start") or block.get("page")
    return {"kind": "pdf", "page_number": page, "precision": "page", "rects": []} if page else {
        "kind": "block", "block_id": block.get("block_id"), "precision": "block"
    }


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
