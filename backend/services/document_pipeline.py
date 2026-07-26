"""
知识库解析流水线（一期骨架）。

阶段：queued → parsing → normalizing → chunking → indexing → ready | failed

PDF / DOCX：优先调用独立 MinerU 适配服务（pipeline + CPU）；
  - 默认 MINERU_URL=http://127.0.0.1:8003 （适配层）
  - 上游官方 mineru-api 在 8001
  - 不可用时降级：PDF→pdfplumber，DOCX→python-docx
分块：结构感知（表整包 + 父标题注入 + 句界二次切）；不依赖 SBERT。
索引：复用 indexer 的 embedding + ES 写入；版本先暂存，发布后清理旧版本。
"""
from __future__ import annotations

import math
import mimetypes
import os
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from html import escape
from pathlib import Path
from typing import Any

import httpx

from core.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBED_API_BASE,
    EMBED_API_KEY,
    EMBED_DIMS,
    EMBED_IS_JINA,
    EMBED_MODEL,
    ES_HOST,
    ES_PASS,
    ES_USER,
    INDEX_NAME,
)
from services.utils import (
    grid_to_html,
    grid_to_markdown,
    looks_like_html_table,
    normalize_table_fields,
    promote_raw_blocks,
)
from services.document_store import (
    compute_version_id,
    document_publication_guard,
    load_meta,
    original_file,
    set_current_version,
    source_sha256,
    update_status,
    version_artifacts_match,
    write_version_artifacts,
)
from services.visibility import ensure_visibility_mapping, response_body

# MinerU 适配服务（默认 8003；见 mineru_service/）
MINERU_URL = os.environ.get("MINERU_URL", "http://127.0.0.1:8003").rstrip("/")
# 是否允许降级本地解析器（默认允许，便于开发）
MINERU_FALLBACK = os.environ.get("MINERU_FALLBACK", "true").lower() in (
    "1",
    "true",
    "yes",
)
PARSER_SCHEMA_VERSION = "1"
PARSER_BUILD_VERSION = os.environ.get(
    "PARSER_BUILD_VERSION", "document-pipeline-v1"
)
MINERU_SERVICE_VERSION = os.environ.get(
    "MINERU_SERVICE_VERSION", "mineru-adapter-1.0.0"
)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="doc-parse")


def current_parse_config() -> dict[str, Any]:
    return {
        "chunk_overlap": CHUNK_OVERLAP,
        "chunk_size": CHUNK_SIZE,
        "mineru_fallback": MINERU_FALLBACK,
        "mineru_service_version": MINERU_SERVICE_VERSION,
        "mineru_url": MINERU_URL,
        "parser_build_version": PARSER_BUILD_VERSION,
    }


def enqueue_parse(doc_id: str) -> None:
    """异步投递解析任务（单线程队列，适配 CPU）。"""
    update_status(doc_id, "queued")
    _executor.submit(_run_pipeline, doc_id)


def _run_pipeline(doc_id: str) -> None:
    t0 = time.time()
    try:
        meta = load_meta(doc_id)
        if not meta:
            return
        src = original_file(doc_id)
        if not src or not src.exists():
            update_status(doc_id, "failed", error="原始文件不存在")
            return

        source_digest = source_sha256(src)
        parse_config = current_parse_config()

        ext = (meta.get("ext") or src.suffix.lstrip(".")).lower()

        # ── parsing ──
        update_status(doc_id, "parsing", engine=_engine_name(ext))
        if ext in ("pdf", "docx"):
            raw_blocks, page_count, engine = _parse_with_mineru_or_fallback(src, ext)
        else:
            update_status(
                doc_id,
                "failed",
                error=f"不支持的文件类型: .{ext}（仅支持 PDF、DOCX）",
            )
            return

        if not raw_blocks:
            update_status(doc_id, "failed", error="未能提取到有效内容")
            return

        parse_config = {**parse_config, "effective_engine": engine}
        version_id = compute_version_id(
            source_digest, PARSER_SCHEMA_VERSION, parse_config
        )

        # ── table normalization (promote pseudo-tables to atomic table blocks) ──
        raw_blocks = promote_raw_blocks(raw_blocks)

        # ── normalizing ──
        update_status(doc_id, "normalizing", page_count=page_count, engine=engine)
        ir = _normalize_ir(
            doc_id=doc_id,
            title=meta.get("title") or meta.get("filename") or doc_id,
            filename=meta.get("filename", ""),
            mime=meta.get("mime", ""),
            pages=page_count,
            raw_blocks=raw_blocks,
        )
        preview_md = _ir_to_preview_md(ir)

        # ── chunking ──
        update_status(doc_id, "chunking")
        chunks = structure_aware_chunk(ir)
        if not chunks:
            update_status(doc_id, "failed", error="分块结果为空")
            return

        elapsed = round(time.time() - t0, 1)
        manifest = {
            "version_id": version_id,
            "source_sha256": source_digest,
            "parser_schema_version": PARSER_SCHEMA_VERSION,
            "parse_config": parse_config,
            "status": "ready",
            "engine": engine,
        }
        try:
            write_version_artifacts(doc_id, version_id, ir, preview_md, manifest)
        except FileExistsError:
            if not version_artifacts_match(
                doc_id, version_id, ir, preview_md, manifest
            ):
                raise RuntimeError(
                    f"版本 ID 冲突，已存产物与本次解析不同: {version_id}"
                )

        # Deletion must not clean ES between indexing and current publication.
        with document_publication_guard(doc_id):
            if not update_status(doc_id, "indexing", chunk_count=len(chunks)):
                raise RuntimeError("文档已删除，无法写入检索索引")
            _index_chunks(doc_id, version_id, meta, chunks)

            if not set_current_version(
                doc_id,
                version_id,
                status="ready",
                page_count=page_count,
                chunk_count=len(chunks),
                duration_sec=elapsed,
                engine=engine,
                indexed_version_id=version_id,
            ):
                raise RuntimeError("解析版本发布失败")
    except Exception as e:
        traceback.print_exc()
        update_status(
            doc_id,
            "failed",
            error=str(e)[:500],
            duration_sec=round(time.time() - t0, 1),
        )


def _engine_name(ext: str) -> str:
    if ext in ("pdf", "docx"):
        return "mineru-pipeline"
    return "unknown"


# ─── MinerU（独立模块 / 适配服务）──────────────────────────

def _parse_with_mineru_or_fallback(
    path: Path, ext: str
) -> tuple[list[dict], int | None, str]:
    """PDF/DOCX 优先走 MinerU pipeline 适配服务，失败按类型降级。"""
    try:
        blocks, pages, backend = _parse_via_mineru(path)
        if blocks:
            engine = f"mineru:{backend}" if backend else "mineru"
            return blocks, pages, engine
        raise RuntimeError("MinerU 返回空 blocks")
    except Exception as e:
        print(f"⚠️ MinerU 不可用 ({ext}): {e}")
        if not MINERU_FALLBACK:
            raise

    if ext == "pdf":
        blocks, pages = _parse_pdf_pdfplumber(path)
        return blocks, pages, "pdfplumber"
    if ext == "docx":
        blocks, pages, _ = _parse_docx(path)
        return blocks, pages, "python-docx"
    raise RuntimeError(f"无降级解析器: {ext}")


def _parse_via_mineru(path: Path) -> tuple[list[dict], int | None, str | None]:
    """调用独立 MinerU 适配服务。

    约定：
      POST {MINERU_URL}/parse  multipart file →
      { "pages": N, "blocks": [...], "markdown": "...", "backend": "pipeline" }
    """
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        if path.suffix.lower() == ".docx":
            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            mime = "application/pdf"

    # trust_env=False：避免系统代理把 127.0.0.1 打成 502
    with path.open("rb") as f:
        with httpx.Client(proxy=None, trust_env=False) as client:
            resp = client.post(
                f"{MINERU_URL}/parse",
                files={"file": (path.name, f, mime)},
                timeout=httpx.Timeout(3600.0, connect=5.0),
            )
    if resp.status_code == 404:
        raise RuntimeError(f"MinerU /parse 不存在: {MINERU_URL}/parse")
    if resp.status_code >= 400:
        raise RuntimeError(f"MinerU HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    pages = data.get("pages") or data.get("page_count")
    backend = data.get("backend")
    if data.get("blocks"):
        return data["blocks"], pages, backend
    md = data.get("markdown") or data.get("md") or ""
    if md:
        return _markdown_to_raw_blocks(md), pages, backend
    raise RuntimeError("MinerU 返回空结果")


def _parse_pdf_pdfplumber(path: Path) -> tuple[list[dict], int | None]:
    import pdfplumber

    blocks: list[dict] = []
    with pdfplumber.open(path) as pdf:
        n = len(pdf.pages)
        for i, page in enumerate(pdf.pages, 1):
            # 表格优先
            tables = page.extract_tables() or []
            found_tables = []
            find_tables = getattr(page, "find_tables", None)
            if callable(find_tables):
                try:
                    found_tables = find_tables() or []
                except Exception:
                    found_tables = []
            for ti, table in enumerate(tables):
                if not table:
                    continue
                html, md = _table_to_html_md(table)
                table_bbox = (
                    getattr(found_tables[ti], "bbox", None)
                    if ti < len(found_tables)
                    else None
                )
                blocks.append(
                    {
                        "type": "table",
                        "text": md,
                        "html": html,
                        "markdown": md,
                        "page": i,
                        "meta": {"table_index": ti},
                        "locator": _pdf_locator(
                            i, page.width, page.height, [table_bbox]
                        ),
                    }
                )
            words = page.extract_words() or []
            for line_words in _group_pdf_words(words):
                text = " ".join(
                    str(word.get("text") or "").strip() for word in line_words
                ).strip()
                rects = [
                    rect
                    for word in line_words
                    if (
                        rect := _normalize_pdf_rect(
                            [
                                word.get("x0"),
                                word.get("top"),
                                word.get("x1"),
                                word.get("bottom"),
                            ],
                            page.width,
                            page.height,
                        )
                    )
                ]
                if not text or not rects:
                    continue
                locator = _pdf_locator(i, page.width, page.height, rects=rects)
                if _looks_like_heading(text):
                    blocks.append(
                        {
                            "type": "heading",
                            "level": _heading_level(text),
                            "text": text,
                            "page": i,
                            "locator": locator,
                        }
                    )
                else:
                    blocks.append(
                        {
                            "type": "paragraph",
                            "text": text,
                            "page": i,
                            "locator": locator,
                        }
                    )
    return blocks, n if blocks else None


def _group_pdf_words(words: list[dict], line_tolerance: float = 2.0) -> list[list[dict]]:
    ordered: list[tuple[float, float, int, dict]] = []
    for index, word in enumerate(words):
        if not isinstance(word, dict) or not str(word.get("text") or "").strip():
            continue
        try:
            top = float(word.get("top"))
            x0 = float(word.get("x0"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(top) and math.isfinite(x0):
            ordered.append((top, x0, index, word))
    ordered.sort(key=lambda item: (item[0], item[1], item[2]))

    lines: list[list[dict]] = []
    line_tops: list[float] = []
    for top, _x0, _index, word in ordered:
        if not lines or abs(top - line_tops[-1]) > line_tolerance:
            lines.append([word])
            line_tops.append(top)
        else:
            lines[-1].append(word)
    return lines


def _normalize_pdf_rect(raw: Any, width: Any, height: Any) -> dict | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        page_width = float(width)
        page_height = float(height)
        x0, y0, x1, y1 = [float(value) for value in raw]
    except (TypeError, ValueError):
        return None
    values = [page_width, page_height, x0, y0, x1, y1]
    if not all(math.isfinite(value) for value in values):
        return None
    if page_width <= 0 or page_height <= 0 or x1 <= x0 or y1 <= y0:
        return None
    if x1 < 0 or y1 < 0 or x0 > page_width or y0 > page_height:
        return None
    x0 = max(0.0, min(page_width, x0))
    x1 = max(0.0, min(page_width, x1))
    y0 = max(0.0, min(page_height, y0))
    y1 = max(0.0, min(page_height, y1))
    if x1 <= x0 or y1 <= y0:
        return None
    return {
        "x0": x0 / page_width * 1000.0,
        "y0": y0 / page_height * 1000.0,
        "x1": x1 / page_width * 1000.0,
        "y1": y1 / page_height * 1000.0,
    }


def _pdf_locator(
    page_number: int,
    width: Any,
    height: Any,
    raw_rects: list[Any] | None = None,
    *,
    rects: list[dict] | None = None,
) -> dict:
    normalized = list(rects or [])
    normalized.extend(
        rect
        for raw in raw_rects or []
        if (rect := _normalize_pdf_rect(raw, width, height))
    )
    return {
        "kind": "pdf",
        "page_number": page_number,
        "origin": "top_left",
        "coordinate_system": "normalized_0_1000",
        "rects": normalized,
        "precision": "exact" if normalized else "page",
    }


# ─── DOCX ──────────────────────────────────────────────────

def _parse_docx(path: Path) -> tuple[list[dict], int | None, str]:
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as e:
        raise RuntimeError(
            "未安装 python-docx，请执行: pip install python-docx"
        ) from e

    doc = Document(str(path))
    blocks: list[dict] = []
    document_order = 0

    # 正文顺序：段落与表交错遍历
    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            para = Paragraph(child, doc)
            text = (para.text or "").strip()
            if not text:
                continue
            style = (para.style.name if para.style else "") or ""
            block_id = f"b{len(blocks) + 1}"
            locator = _docx_locator("paragraph", document_order, block_id, text)
            document_order += 1
            if style.startswith("Heading"):
                try:
                    level = int(style.replace("Heading", "").strip() or "1")
                except ValueError:
                    level = 1
                blocks.append(
                    {
                        "block_id": block_id,
                        "type": "heading",
                        "level": level,
                        "text": text,
                        "locator": locator,
                    }
                )
            elif _looks_like_heading(text):
                blocks.append(
                    {
                        "type": "heading",
                        "level": _heading_level(text),
                        "text": text,
                        "block_id": block_id,
                        "locator": locator,
                    }
                )
            else:
                blocks.append(
                    {
                        "block_id": block_id,
                        "type": "paragraph",
                        "text": text,
                        "locator": locator,
                    }
                )
        elif tag == "tbl":
            table = Table(child, doc)
            rows = [[(c.text or "").strip() for c in row.cells] for row in table.rows]
            if not rows:
                continue
            block_id = f"b{len(blocks) + 1}"
            locators: list[dict] = []
            for cell_text in _docx_xml_cell_texts(child, table):
                locators.append(
                    _docx_locator("table_cell", document_order, block_id, cell_text)
                )
                document_order += 1
            html, md = _table_to_html_md(rows)
            blocks.append(
                {
                    "block_id": block_id,
                    "type": "table",
                    "text": md,
                    "html": html,
                    "markdown": md,
                    "locators": locators,
                }
            )

    return blocks, None, "python-docx"


def _docx_xml_cell_texts(table_element: Any, table: Any) -> list[str]:
    from docx.table import _Cell

    return [
        (_Cell(cell, table).text or "").strip()
        for row in table_element.tr_lst
        for cell in row.tc_lst
    ]


def _docx_locator(
    container_kind: str, document_order: int, block_id: str, text: str
) -> dict:
    kind_code = "p" if container_kind == "paragraph" else "tc"
    return {
        "kind": "docx",
        "locator_id": f"docx-{kind_code}-{document_order:06d}",
        "container_kind": container_kind,
        "document_order": document_order,
        "block_id": block_id,
        "text_range": {
            "start": 0,
            "end": len(text),
            "unit": "unicode_code_point",
        },
        "precision": "exact",
    }


# ─── Normalize → IR ────────────────────────────────────────

def _normalize_ir(
    doc_id: str,
    title: str,
    filename: str,
    mime: str,
    pages: int | None,
    raw_blocks: list[dict],
) -> dict:
    section_stack: list[tuple[int, str]] = []
    blocks: list[dict] = []
    bid = 0

    # 简单跨页表合并（相邻 table、列数一致）
    merged_raw = _merge_adjacent_tables(raw_blocks)

    for raw in merged_raw:
        btype = (raw.get("type") or "paragraph").lower()
        if btype in ("header", "footer"):
            continue
        text = (raw.get("text") or "").strip()
        if btype == "heading":
            level = int(raw.get("level") or 1)
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()
            section_stack.append((level, text))
            path = [s[1] for s in section_stack]
            bid += 1
            blocks.append(
                {
                    "block_id": raw.get("block_id") or f"b{bid}",
                    "type": "heading",
                    "level": level,
                    "page_start": raw.get("page") or raw.get("page_start"),
                    "page_end": raw.get("page_end") or raw.get("page"),
                    "section_path": path,
                    "text": text,
                    "html": None,
                    "markdown": None,
                    "meta": raw.get("meta") or {},
                    **_raw_locator_fields(raw),
                }
            )
            continue

        path = [s[1] for s in section_stack]
        bid += 1
        if btype == "table":
            # Always normalize to dual-form (html/markdown/text) from same grid.
            # Never fall back to <pre>md</pre> as primary html when grid succeeds.
            norm = normalize_table_fields(
                html=raw.get("html") or None,
                markdown=raw.get("markdown") or None,
                text=raw.get("text") or text or None,
            )
            blocks.append(
                {
                    "block_id": raw.get("block_id") or f"b{bid}",
                    "type": "table",
                    "level": None,
                    "page_start": raw.get("page") or raw.get("page_start"),
                    "page_end": raw.get("page_end") or raw.get("page"),
                    "section_path": path,
                    "text": norm.get("text", ""),
                    "html": norm.get("html", ""),
                    "markdown": norm.get("markdown", ""),
                    "meta": {
                        **(raw.get("meta") or {}),
                        "merged": bool(raw.get("merged")),
                    },
                    **_raw_locator_fields(raw),
                }
            )
        else:
            if not text:
                continue
            blocks.append(
                {
                    "block_id": raw.get("block_id") or f"b{bid}",
                    "type": "list" if btype == "list" else "paragraph",
                    "level": None,
                    "page_start": raw.get("page") or raw.get("page_start"),
                    "page_end": raw.get("page_end") or raw.get("page"),
                    "section_path": path,
                    "text": text,
                    "html": None,
                    "markdown": None,
                    "meta": raw.get("meta") or {},
                    **_raw_locator_fields(raw),
                }
            )

    return {
        "doc_id": doc_id,
        "title": title,
        "source": {
            "filename": filename,
            "mime": mime,
            "pages": pages,
        },
        "blocks": blocks,
    }


def _raw_locator_fields(raw: dict) -> dict:
    fields = {}
    if isinstance(raw.get("locator"), dict):
        fields["locator"] = raw["locator"]
    if isinstance(raw.get("locators"), list):
        fields["locators"] = raw["locators"]
    return fields


def _merge_adjacent_tables(raw_blocks: list[dict]) -> list[dict]:
    out: list[dict] = []
    i = 0
    while i < len(raw_blocks):
        cur = raw_blocks[i]
        if (cur.get("type") or "").lower() != "table":
            out.append(cur)
            i += 1
            continue
        acc = dict(cur)
        j = i + 1
        while j < len(raw_blocks) and (raw_blocks[j].get("type") or "").lower() == "table":
            nxt = raw_blocks[j]
            # 列数粗判
            c1 = _md_col_count(acc.get("markdown") or acc.get("text") or "")
            c2 = _md_col_count(nxt.get("markdown") or nxt.get("text") or "")
            if c1 and c2 and c1 == c2:
                md1 = (acc.get("markdown") or acc.get("text") or "").strip()
                md2 = (nxt.get("markdown") or nxt.get("text") or "").strip()
                # 去掉第二表可能重复的表头行
                lines2 = md2.splitlines()
                if len(lines2) >= 2 and lines2[1].strip().startswith("|"):
                    # 跳过 header + separator
                    body2 = "\n".join(lines2[2:]) if _is_md_sep(lines2[1]) else md2
                else:
                    body2 = md2
                acc["markdown"] = md1.rstrip() + "\n" + body2.lstrip()
                acc["text"] = acc["markdown"]
                acc["html"] = acc.get("html") or ""
                if nxt.get("html"):
                    acc["html"] = (acc.get("html") or "") + "\n" + nxt["html"]
                acc["page_end"] = nxt.get("page") or nxt.get("page_end") or acc.get("page_end")
                if nxt.get("locators"):
                    acc["locators"] = list(acc.get("locators") or []) + list(nxt["locators"])
                acc["merged"] = True
                j += 1
            else:
                break
        # After successful merge (or single), re-normalize to keep html/markdown/text in sync from grid
        try:
            norm = normalize_table_fields(
                html=acc.get("html") or None,
                markdown=acc.get("markdown") or None,
                text=acc.get("text") or None,
            )
            if norm.get("markdown"):
                acc["html"] = norm.get("html", "")
                acc["markdown"] = norm.get("markdown", "")
                acc["text"] = norm.get("text", "")
        except Exception:
            pass
        out.append(acc)
        i = j if j > i else i + 1
    return out


def _md_col_count(md: str) -> int:
    for line in md.splitlines():
        if "|" in line:
            return line.count("|") - 1 if line.strip().startswith("|") else line.count("|")
    return 0


def _is_md_sep(line: str) -> bool:
    s = line.replace("|", "").replace(":", "").replace("-", "").replace(" ", "")
    return len(s) == 0 and "-" in line


# ─── Structure-aware chunk ─────────────────────────────────

def structure_aware_chunk(ir: dict) -> list[dict]:
    """结构分块：表整包 + 父标题注入 + 超长句界切 + ~12% overlap。"""
    title = ir.get("title") or ""
    doc_id = ir.get("doc_id") or ""
    max_len = CHUNK_SIZE
    overlap = max(32, int(max_len * 0.12))  # ~12%，贴近设计 10%–15%
    chunks: list[dict] = []
    cid = 0

    for block in ir.get("blocks") or []:
        btype = block.get("type")
        if btype == "heading":
            continue
        if btype in ("header", "footer"):
            continue

        path = block.get("section_path") or []
        header = _context_header(title, path)
        page_start = block.get("page_start")
        page_end = block.get("page_end")

        if btype == "table":
            body = block.get("markdown") or block.get("text") or ""
            # If body looks like HTML table, normalize to markdown first
            if looks_like_html_table(body):
                try:
                    norm = normalize_table_fields(html=body)
                    if norm.get("markdown"):
                        body = norm["markdown"]
                except Exception:
                    pass
            content = f"{header}\n\n{body}".strip()
            # 超长表：按行窗口，重复表头
            if len(content) <= max_len * 2:
                cid += 1
                chunks.append(
                    _chunk_row(
                        doc_id,
                        title,
                        cid,
                        content,
                        btype,
                        path,
                        page_start,
                        page_end,
                        block,
                    )
                )
            else:
                for part in _split_table_rows(body, max_len, header):
                    cid += 1
                    chunks.append(
                        _chunk_row(
                            doc_id,
                            title,
                            cid,
                            part,
                            btype,
                            path,
                            page_start,
                            page_end,
                            block,
                        )
                    )
            continue

        text = (block.get("text") or "").strip()
        if not text:
            continue

        # 整段未超限则不再切：避免「不得认定…」与「（一）故意犯罪…」拆成碎片
        full_block = f"{header}\n\n{text}".strip()
        if len(full_block) <= max_len:
            cid += 1
            chunks.append(
                _chunk_row(
                    doc_id,
                    title,
                    cid,
                    full_block,
                    btype,
                    path,
                    page_start,
                    page_end,
                    block,
                )
            )
            continue

        # 超长块：仅按「第X条」切开，不按「（一）（二）」拆短列举
        parts = _split_by_legal_markers(text)
        parts = _merge_short_parts(parts, max_len - len(header) - 4)
        for part in parts:
            full = f"{header}\n\n{part}".strip()
            if len(full) <= max_len:
                cid += 1
                chunks.append(
                    _chunk_row(
                        doc_id,
                        title,
                        cid,
                        full,
                        btype,
                        path,
                        page_start,
                        page_end,
                        block,
                    )
                )
            else:
                for piece in _sentence_window(full, max_len, overlap):
                    cid += 1
                    chunks.append(
                        _chunk_row(
                            doc_id,
                            title,
                            cid,
                            piece,
                            btype,
                            path,
                            page_start,
                            page_end,
                            block,
                        )
                    )
    return chunks


def _chunk_row(
    doc_id: str,
    title: str,
    chunk_id: int,
    content: str,
    block_type: str,
    path: list,
    page_start,
    page_end,
    block: dict,
) -> dict:
    return {
        "doc_id": doc_id,
        "title": title,
        "content": content,
        "chunk_id": chunk_id,
        "block_type": block_type,
        "section_path": " > ".join(path) if path else "",
        "page_start": page_start,
        "page_end": page_end,
        "block_id": block.get("block_id"),
        **_raw_locator_fields(block),
        "filename": "",  # filled at index time
    }


def _context_header(title: str, path: list) -> str:
    lines = [f"[文档] {title}"]
    if path:
        lines.append(f"[章节] {' > '.join(path)}")
    return "\n".join(lines)


def _split_by_legal_markers(text: str) -> list[str]:
    """按「第X条」切开（保留分隔符在后段开头）。

    不再按「（一）（二）」切：列举项通常很短，拆开后召回会丢关键句。
    """
    pattern = re.compile(r"(?=(?:第[一二三四五六七八九十百零〇0-9]+条))")
    parts = [p.strip() for p in pattern.split(text) if p and p.strip()]
    return parts if parts else [text]


def _merge_short_parts(parts: list[str], budget: int, min_keep: int = 80) -> list[str]:
    """合并过短片段，避免索引里出现几十字符的碎片 chunk。"""
    if not parts:
        return parts
    out: list[str] = []
    buf = ""
    for p in parts:
        if not buf:
            buf = p
            continue
        # 后段过短或合并后仍不超预算 → 并入
        if len(p) < min_keep or len(buf) + 1 + len(p) <= budget:
            buf = f"{buf}\n{p}"
        else:
            out.append(buf)
            buf = p
    if buf:
        out.append(buf)
    return out


def _sentence_window(text: str, max_len: int, overlap: int) -> list[str]:
    # 按句号切，再拼窗口
    sents = re.split(r"(?<=[。！？；\n])", text)
    sents = [s for s in sents if s.strip()]
    if not sents:
        return [text[i : i + max_len] for i in range(0, len(text), max_len - overlap)]
    out: list[str] = []
    buf = ""
    for s in sents:
        if len(buf) + len(s) <= max_len:
            buf += s
        else:
            if buf:
                out.append(buf.strip())
            # overlap: 取上一块尾部
            if out and overlap > 0:
                prev = out[-1]
                tail = prev[-overlap:] if len(prev) > overlap else prev
                buf = tail + s
            else:
                buf = s
            while len(buf) > max_len:
                out.append(buf[:max_len].strip())
                buf = buf[max_len - overlap :]
    if buf.strip():
        out.append(buf.strip())
    return out or [text[:max_len]]


def _split_table_rows(md: str, max_len: int, header: str) -> list[str]:
    lines = md.splitlines()
    if len(lines) < 2:
        return [f"{header}\n\n{md}"]
    head = "\n".join(lines[:2])  # header + sep
    body = lines[2:]
    out: list[str] = []
    buf_lines: list[str] = []
    for row in body:
        trial = header + "\n\n" + head + "\n" + "\n".join(buf_lines + [row])
        if len(trial) > max_len and buf_lines:
            out.append(header + "\n\n" + head + "\n" + "\n".join(buf_lines))
            buf_lines = [row]
        else:
            buf_lines.append(row)
    if buf_lines:
        out.append(header + "\n\n" + head + "\n" + "\n".join(buf_lines))
    return out


# ─── Preview MD ────────────────────────────────────────────

def _ir_to_preview_md(ir: dict) -> str:
    parts = [f"# {ir.get('title') or '文档'}\n"]
    for b in ir.get("blocks") or []:
        t = b.get("type")
        if t == "heading":
            level = min(int(b.get("level") or 1), 6)
            parts.append(f"\n{'#' * (level + 1)} {b.get('text', '')}\n")
        elif t == "table":
            note = ""
            if (b.get("meta") or {}).get("merged"):
                note = "\n> 跨页已合并\n"
            parts.append(note + "\n" + (b.get("markdown") or b.get("text") or "") + "\n")
        else:
            parts.append("\n" + (b.get("text") or "") + "\n")
    return "\n".join(parts)


# ─── Index to ES ───────────────────────────────────────────

def _index_chunks(
    doc_id: str, version_id: str, meta: dict, chunks: list[dict]
) -> None:
    from elasticsearch import Elasticsearch
    import json
    import requests

    es = Elasticsearch(
        ES_HOST,
        basic_auth=(ES_USER, ES_PASS),
        verify_certs=False,
        ssl_show_warn=False,
    )
    # 确保索引存在（兼容旧 mapping；新字段动态加入）
    if not es.indices.exists(index=INDEX_NAME):
        es.indices.create(
            index=INDEX_NAME,
            body={
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": {
                    "properties": {
                        "doc_id": {"type": "keyword"},
                        "document_version_id": {"type": "keyword"},
                        "visibility_key": {"type": "keyword"},
                        "visibility_key_v2": {"type": "keyword"},
                        "filename": {"type": "keyword"},
                        "title": {"type": "text"},
                        "chunk_id": {"type": "integer"},
                        "content": {"type": "text"},
                        "file_type": {"type": "keyword"},
                        "block_type": {"type": "keyword"},
                        "section_path": {"type": "text"},
                        "page_start": {"type": "integer"},
                        "page_end": {"type": "integer"},
                        "embedding": {
                            "type": "dense_vector",
                            "dims": EMBED_DIMS,
                            "index": True,
                            "similarity": "cosine",
                        },
                    }
                },
            },
        )

    ensure_visibility_mapping(es, INDEX_NAME)

    filename = meta.get("filename") or ""
    file_type = meta.get("ext") or ""
    for c in chunks:
        c["filename"] = filename
        c["file_type"] = file_type

    texts = [c["content"] for c in chunks]
    embeddings = _embed(texts)
    if not isinstance(embeddings, list) or len(embeddings) != len(chunks):
        raise RuntimeError(
            "embedding result count does not match document chunk count"
        )

    batch_size = 50
    for i in range(0, len(chunks), batch_size):
        batch_c = chunks[i : i + batch_size]
        batch_e = embeddings[i : i + batch_size]
        bulk_body = ""
        for chunk, emb in zip(batch_c, batch_e):
            action = {
                "index": {
                    "_index": INDEX_NAME,
                    "_id": f"{doc_id}:{version_id}:{chunk['chunk_id']}",
                }
            }
            doc = {
                "doc_id": chunk["doc_id"],
                "document_version_id": version_id,
                "visibility_key": f"{doc_id}:{version_id}",
                "visibility_key_v2": f"{doc_id}:{version_id}",
                "filename": chunk.get("filename", ""),
                "title": chunk.get("title", ""),
                "chunk_id": chunk["chunk_id"],
                "content": chunk["content"],
                "file_type": chunk.get("file_type", ""),
                "block_type": chunk.get("block_type"),
                "section_path": chunk.get("section_path"),
                "page_start": chunk.get("page_start"),
                "page_end": chunk.get("page_end"),
                "embedding": emb,
            }
            bulk_body += json.dumps(action, ensure_ascii=False) + "\n"
            bulk_body += json.dumps(doc, ensure_ascii=False) + "\n"
        if bulk_body:
            result = response_body(
                es.bulk(body=bulk_body, refresh=True),
                operation="document chunk bulk indexing",
            )
            items = result.get("items")
            if result.get("errors") is not False or not isinstance(items, list):
                raise RuntimeError("document chunk bulk indexing did not complete")
            if len(items) != len(batch_c):
                raise RuntimeError("document chunk bulk item count is incomplete")
            for item in items:
                operation = item.get("index") if isinstance(item, dict) else None
                status = operation.get("status") if isinstance(operation, dict) else None
                if (
                    type(status) is not int
                    or not 200 <= status < 300
                    or operation.get("error") is not None
                ):
                    raise RuntimeError("document chunk bulk item failed")


def delete_doc_from_index(doc_id: str) -> None:
    from elasticsearch import Elasticsearch

    es = Elasticsearch(
        ES_HOST,
        basic_auth=(ES_USER, ES_PASS),
        verify_certs=False,
        ssl_show_warn=False,
    )
    if not es.indices.exists(index=INDEX_NAME):
        return
    response = es.delete_by_query(
        index=INDEX_NAME,
        body={"query": {"term": {"doc_id": doc_id}}},
        refresh=True,
        conflicts="proceed",
    )
    result = response_body(response, operation="document delete by query")
    response_status = getattr(getattr(response, "meta", None), "status", None)
    counters = ("total", "deleted", "batches", "noops", "version_conflicts")
    if (
        (hasattr(response, "body") and response_status is None)
        or (
            response_status is not None
            and (
                type(response_status) is not int
                or not 200 <= response_status < 300
            )
        )
    ):
        raise RuntimeError("document delete by query returned a bad status")
    if (
        result.get("timed_out") is not False
        or result.get("failures") != []
        or any(
            type(result.get(name)) is not int or result[name] < 0
            for name in counters
        )
        or result.get("version_conflicts") != 0
        or result.get("noops") != 0
        or result.get("deleted") != result.get("total")
    ):
        raise RuntimeError("document delete by query did not complete")


def _embed(texts: list[str]) -> list[list[float]]:
    if not EMBED_API_KEY:
        raise RuntimeError("EMBED_API_KEY 未配置，无法写入向量索引")
    import requests

    url = f"{EMBED_API_BASE}/embeddings"
    headers = {
        "Authorization": f"Bearer {EMBED_API_KEY}",
        "Content-Type": "application/json",
    }
    all_emb: list[list[float]] = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        payload: dict[str, Any] = {"model": EMBED_MODEL, "input": batch}
        if EMBED_IS_JINA:
            payload["task"] = "retrieval.passage"
            payload["dimensions"] = EMBED_DIMS
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(f"Embedding 失败 ({resp.status_code}): {resp.text[:300]}")
        data = resp.json()
        for d in data["data"]:
            all_emb.append(d["embedding"])
    return all_emb


# ─── helpers ───────────────────────────────────────────────

def _looks_like_heading(text: str) -> bool:
    t = text.strip()
    if len(t) > 40:
        return False
    if re.match(
        r"^(第[一二三四五六七八九十百零0-9]+[章节条款]|[一二三四五六七八九十]+[、.．]|（[一二三四五六七八九十]）|\d+[\.、])",
        t,
    ):
        return True
    return False


def _heading_level(text: str) -> int:
    t = text.strip()
    if re.match(r"^第[一二三四五六七八九十百零0-9]+章", t):
        return 1
    if re.match(r"^第[一二三四五六七八九十百零0-9]+节", t):
        return 2
    if re.match(r"^第[一二三四五六七八九十百零0-9]+条", t):
        return 3
    return 2


def _table_to_html_md(rows: list[list]) -> tuple[str, str]:
    """Delegate to table_utils grid functions to avoid drift.

    Converts rows to plain grid, then uses grid_to_html / grid_to_markdown.
    """
    if not rows:
        return "", ""
    # normalize to list[list[str]]
    width = max(len(r) for r in rows)
    grid: list[list[str]] = []
    for r in rows:
        cells = [(str(c) if c is not None else "") for c in r]
        while len(cells) < width:
            cells.append("")
        grid.append(cells)
    html = grid_to_html(grid)
    md = grid_to_markdown(grid)
    return html, md


def _markdown_to_raw_blocks(md: str) -> list[dict]:
    blocks: list[dict] = []
    lines = md.splitlines()
    buf: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#"):
            if buf:
                blocks.append({"type": "paragraph", "text": "\n".join(buf).strip()})
                buf = []
            level = len(line) - len(line.lstrip("#"))
            text = line.lstrip("#").strip()
            blocks.append({"type": "heading", "level": min(level, 6), "text": text})
            i += 1
        elif line.strip().startswith("|"):
            if buf:
                blocks.append({"type": "paragraph", "text": "\n".join(buf).strip()})
                buf = []
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            md_table = "\n".join(table_lines)
            blocks.append(
                {
                    "type": "table",
                    "text": md_table,
                    "markdown": md_table,
                    "html": f"<pre>{escape(md_table)}</pre>",
                }
            )
        else:
            if line.strip() == "":
                if buf:
                    blocks.append({"type": "paragraph", "text": "\n".join(buf).strip()})
                    buf = []
            else:
                buf.append(line)
            i += 1
    if buf:
        blocks.append({"type": "paragraph", "text": "\n".join(buf).strip()})
    return blocks
