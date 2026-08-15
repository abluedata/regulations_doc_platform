"""Evidence anchor construction for review findings."""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Mapping


def quote_sha256(quote: str) -> str:
    return hashlib.sha256((quote or "").encode("utf-8")).hexdigest()


def bbox_to_quadpoints(rect: Mapping[str, Any], *, page_height: float = 1000.0) -> list[float]:
    """Convert a top-left bbox to normalized PDF-style quadpoints.

    Input bboxes use the platform IR convention: 0-1000 normalized coordinates
    with origin at the page top-left.  Returned quadpoints use a bottom-left
    vertical axis so they can be consumed by PDF highlighters.
    """

    x0 = float(rect["x0"])
    y0 = float(rect["y0"])
    x1 = float(rect["x1"])
    y1 = float(rect["y1"])
    top = page_height - y0
    bottom = page_height - y1
    return [x0, top, x1, top, x0, bottom, x1, bottom]


def locate_evidence(
    ir: Mapping[str, Any],
    quote: str,
    *,
    block_index: int | None = None,
    block_id: str | None = None,
    start: int | None = None,
    end: int | None = None,
    document_version_id: str | None = None,
) -> dict[str, Any]:
    """Locate a quote in document IR using PDF/DOCX format-specific fallbacks."""

    blocks = list(ir.get("blocks") or [])
    selected_index, block = _select_block(blocks, quote, block_index=block_index, block_id=block_id)
    version_id = document_version_id or str(ir.get("document_version_id") or "")
    source = ir.get("source") if isinstance(ir.get("source"), Mapping) else {}
    kind = _document_kind(source, block)
    if kind == "docx":
        return _docx_anchor(version_id, quote, selected_index, block, start=start, end=end)
    return _pdf_anchor(version_id, quote, selected_index, block, ir)


def _pdf_anchor(
    version_id: str,
    quote: str,
    block_index: int,
    block: Mapping[str, Any],
    ir: Mapping[str, Any],
) -> dict[str, Any]:
    text_layer = _find_pdf_text_layer_rect(quote, block, ir)
    if text_layer:
        return _pdf_payload(version_id, quote, block_index, block, text_layer, "pdf_text_layer", "exact")

    span_rect = _find_layout_span_rect(quote, block, ir)
    if span_rect:
        return _pdf_payload(version_id, quote, block_index, block, span_rect, "mineru_layout_span", "exact")

    paragraph_rect = _paragraph_rect(block)
    if paragraph_rect:
        return _pdf_payload(version_id, quote, block_index, block, paragraph_rect, "paragraph_bbox", "degraded")

    return {
        "kind": "pdf",
        "document_version_id": version_id,
        "quote": quote,
        "quote_hash": quote_sha256(quote),
        "source_block_id": block.get("block_id"),
        "para_index": block_index,
        "page_number": block.get("page_start") or block.get("page"),
        "bounding_box": [],
        "rects": [],
        "coordinate_system": "pdf_quadpoints_normalized_0_1000",
        "fallback_level": "unlocated",
        "precision": "unlocated",
    }


def _docx_anchor(
    version_id: str,
    quote: str,
    block_index: int,
    block: Mapping[str, Any],
    *,
    start: int | None,
    end: int | None,
) -> dict[str, Any]:
    text = str(block.get("text") or "")
    if start is None or end is None:
        found = text.find(quote)
        start = found if found >= 0 else 0
        end = start + len(quote) if found >= 0 else min(len(text), len(quote))
    locator = _best_docx_locator(block, quote)
    return {
        "kind": "docx",
        "document_version_id": version_id,
        "quote": quote,
        "quote_hash": quote_sha256(quote),
        "block_id": block.get("block_id") or locator.get("block_id"),
        "locator_id": locator.get("locator_id"),
        "container_kind": locator.get("container_kind", "paragraph"),
        "para_index": locator.get("document_order", block_index),
        "document_order": locator.get("document_order", block_index),
        "text_range": {"start": int(start), "end": int(end), "unit": "unicode_code_point"},
        "fallback_level": "docx_anchor",
        "precision": locator.get("precision", "exact"),
    }


def _pdf_payload(
    version_id: str,
    quote: str,
    block_index: int,
    block: Mapping[str, Any],
    rect_record: Mapping[str, Any],
    fallback_level: str,
    precision: str,
) -> dict[str, Any]:
    rects = [dict(rect) for rect in rect_record.get("rects", []) if _valid_rect(rect)]
    page_number = rect_record.get("page_number") or block.get("page_start") or block.get("page")
    quadpoints: list[float] = []
    for rect in rects:
        quadpoints.extend(bbox_to_quadpoints(rect))
    return {
        "kind": "pdf",
        "document_version_id": version_id,
        "quote": quote,
        "quote_hash": quote_sha256(quote),
        "source_block_id": block.get("block_id"),
        "para_index": block_index,
        "page_number": page_number,
        "bounding_box": quadpoints,
        "rects": rects,
        "coordinate_system": "pdf_quadpoints_normalized_0_1000",
        "source_coordinate_system": rect_record.get("coordinate_system", "normalized_0_1000"),
        "fallback_level": fallback_level,
        "precision": precision,
    }


def _find_pdf_text_layer_rect(
    quote: str, block: Mapping[str, Any], ir: Mapping[str, Any]
) -> dict[str, Any] | None:
    for candidate in _iter_records(block.get("pdf_text_layer")):
        rect = _rect_from_record(candidate)
        text = str(candidate.get("text") or "")
        if rect and _text_matches(text, quote):
            return {"page_number": candidate.get("page_number"), "rects": [rect], "coordinate_system": "normalized_0_1000"}
    for candidate in _iter_records(ir.get("pdf_text_layer")):
        rect = _rect_from_record(candidate)
        text = str(candidate.get("text") or "")
        if rect and _text_matches(text, quote):
            return {"page_number": candidate.get("page_number"), "rects": [rect], "coordinate_system": "normalized_0_1000"}
    return None


def _find_layout_span_rect(
    quote: str, block: Mapping[str, Any], ir: Mapping[str, Any]
) -> dict[str, Any] | None:
    for span in _layout_spans(block, ir):
        span_text = str(span.get("text") or "")
        rect = _substring_rect_from_span(span, quote)
        if rect and _text_matches(span_text, quote):
            return {
                "page_number": span.get("page_number") or span.get("page"),
                "rects": [rect],
                "coordinate_system": "normalized_0_1000",
            }
    return None


def _substring_rect_from_span(span: Mapping[str, Any], quote: str) -> dict[str, float] | None:
    rect = _rect_from_record(span)
    if not rect:
        return None
    span_text = str(span.get("text") or "")
    if not span_text:
        return rect
    index = span_text.find(quote)
    if index < 0:
        compact_text = "".join(span_text.split())
        compact_quote = "".join((quote or "").split())
        index = compact_text.find(compact_quote)
        if index < 0:
            return None
        span_len = max(len(compact_text), 1)
        quote_len = len(compact_quote)
    else:
        span_len = max(len(span_text), 1)
        quote_len = len(quote)
    x0 = float(rect["x0"])
    x1 = float(rect["x1"])
    width = x1 - x0
    sub_x0 = x0 + width * (index / span_len)
    sub_x1 = x0 + width * ((index + quote_len) / span_len)
    return {"x0": sub_x0, "y0": float(rect["y0"]), "x1": sub_x1, "y1": float(rect["y1"])}


def _paragraph_rect(block: Mapping[str, Any]) -> dict[str, Any] | None:
    locator = block.get("locator")
    if not isinstance(locator, Mapping):
        return None
    rects = [dict(rect) for rect in locator.get("rects") or [] if _valid_rect(rect)]
    if not rects:
        return None
    return {
        "page_number": locator.get("page_number") or block.get("page_start") or block.get("page"),
        "rects": rects,
        "coordinate_system": locator.get("coordinate_system", "normalized_0_1000"),
    }


def _select_block(
    blocks: list[Mapping[str, Any]],
    quote: str,
    *,
    block_index: int | None,
    block_id: str | None,
) -> tuple[int, Mapping[str, Any]]:
    if block_index is not None and 0 <= block_index < len(blocks):
        return block_index, blocks[block_index]
    if block_id:
        for index, block in enumerate(blocks):
            if str(block.get("block_id") or "") == block_id:
                return index, block
    for index, block in enumerate(blocks):
        if quote and quote in str(block.get("text") or ""):
            return index, block
    return 0, blocks[0] if blocks else {}


def _document_kind(source: Mapping[str, Any], block: Mapping[str, Any]) -> str:
    locator = block.get("locator")
    if isinstance(locator, Mapping) and locator.get("kind") == "docx":
        return "docx"
    filename = str(source.get("filename") or "").lower()
    mime = str(source.get("mime") or "").lower()
    if filename.endswith(".docx") or "wordprocessingml" in mime:
        return "docx"
    return "pdf"


def _best_docx_locator(block: Mapping[str, Any], quote: str) -> Mapping[str, Any]:
    locator = block.get("locator")
    if isinstance(locator, Mapping):
        return locator
    locators = block.get("locators")
    if isinstance(locators, list) and locators:
        return next((loc for loc in locators if isinstance(loc, Mapping)), {})
    return {}


def _layout_spans(block: Mapping[str, Any], ir: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for key in ("layout_spans", "spans"):
        yield from _iter_records(block.get(key))
    meta = block.get("meta")
    if isinstance(meta, Mapping):
        for key in ("layout_spans", "spans"):
            yield from _iter_records(meta.get(key))
    yield from _iter_records(ir.get("layout_spans"))


def _iter_records(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, Mapping):
                yield item


def _rect_from_record(record: Mapping[str, Any]) -> dict[str, float] | None:
    if isinstance(record.get("rect"), Mapping):
        rect = record["rect"]
    elif isinstance(record.get("bbox"), Mapping):
        rect = record["bbox"]
    elif isinstance(record.get("bbox"), (list, tuple)) and len(record["bbox"]) == 4:
        x0, y0, x1, y1 = record["bbox"]
        rect = {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
    elif all(key in record for key in ("x0", "y0", "x1", "y1")):
        rect = record
    else:
        locator = record.get("locator")
        if isinstance(locator, Mapping) and isinstance(locator.get("rects"), list) and locator["rects"]:
            rect = locator["rects"][0]
        else:
            return None
    return _coerce_rect(rect)


def _coerce_rect(rect: Mapping[str, Any]) -> dict[str, float] | None:
    try:
        value = {
            "x0": float(rect["x0"]),
            "y0": float(rect["y0"]),
            "x1": float(rect["x1"]),
            "y1": float(rect["y1"]),
        }
    except (KeyError, TypeError, ValueError):
        return None
    return value if _valid_rect(value) else None


def _valid_rect(rect: Mapping[str, Any]) -> bool:
    try:
        return float(rect["x1"]) > float(rect["x0"]) and float(rect["y1"]) > float(rect["y0"])
    except (KeyError, TypeError, ValueError):
        return False


def _text_matches(text: str, quote: str) -> bool:
    if not quote:
        return False
    return quote in text or "".join(quote.split()) in "".join(text.split())


__all__ = ["bbox_to_quadpoints", "locate_evidence", "quote_sha256"]
