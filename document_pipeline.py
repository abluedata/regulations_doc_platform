"""
知识库解析流水线（一期骨架）。

阶段：queued → parsing → normalizing → chunking → indexing → ready | failed

PDF / DOCX：优先调用独立 MinerU 适配服务（pipeline + CPU）；
  - 默认 MINERU_URL=http://127.0.0.1:8003 （适配层）
  - 上游官方 mineru-api 在 8001
  - 不可用时降级：PDF→pdfplumber，DOCX→python-docx
分块：结构感知（表整包 + 父标题注入 + 句界二次切）；不依赖 SBERT。
索引：复用 indexer 的 embedding + ES 写入；按 doc_id 先删后写。
"""
from __future__ import annotations

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

from config import (
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
from document_store import (
    load_meta,
    original_file,
    save_ir,
    save_preview_md,
    update_status,
)

from table_utils import (
    grid_to_html,
    grid_to_markdown,
    looks_like_html_table,
    normalize_table_fields,
    promote_raw_blocks,
)

# MinerU 适配服务（默认 8003；见 mineru_service/）
MINERU_URL = os.environ.get("MINERU_URL", "http://127.0.0.1:8003").rstrip("/")
# 是否允许降级本地解析器（默认允许，便于开发）
MINERU_FALLBACK = os.environ.get("MINERU_FALLBACK", "true").lower() in (
    "1",
    "true",
    "yes",
)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="doc-parse")


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
        save_ir(doc_id, ir)
        preview_md = _ir_to_preview_md(ir)
        save_preview_md(doc_id, preview_md)

        # ── chunking ──
        update_status(doc_id, "chunking")
        chunks = structure_aware_chunk(ir)
        if not chunks:
            update_status(doc_id, "failed", error="分块结果为空")
            return

        # ── indexing ──
        update_status(doc_id, "indexing", chunk_count=len(chunks))
        _index_chunks(doc_id, meta, chunks)

        elapsed = round(time.time() - t0, 1)
        update_status(
            doc_id,
            "ready",
            page_count=page_count,
            chunk_count=len(chunks),
            duration_sec=elapsed,
            engine=engine,
        )
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
            for ti, table in enumerate(tables):
                if not table:
                    continue
                html, md = _table_to_html_md(table)
                blocks.append(
                    {
                        "type": "table",
                        "text": md,
                        "html": html,
                        "markdown": md,
                        "page": i,
                        "meta": {"table_index": ti},
                    }
                )
            text = page.extract_text() or ""
            text = text.strip()
            if not text:
                continue
            # 粗分段
            for para in re.split(r"\n{2,}", text):
                p = para.strip()
                if not p:
                    continue
                if _looks_like_heading(p):
                    blocks.append(
                        {
                            "type": "heading",
                            "level": _heading_level(p),
                            "text": p.replace("\n", " "),
                            "page": i,
                        }
                    )
                else:
                    blocks.append(
                        {
                            "type": "paragraph",
                            "text": p.replace("\n", " "),
                            "page": i,
                        }
                    )
    return blocks, n if blocks else None


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

    # 正文顺序：段落与表交错遍历
    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            para = Paragraph(child, doc)
            text = (para.text or "").strip()
            if not text:
                continue
            style = (para.style.name if para.style else "") or ""
            if style.startswith("Heading"):
                try:
                    level = int(style.replace("Heading", "").strip() or "1")
                except ValueError:
                    level = 1
                blocks.append(
                    {"type": "heading", "level": level, "text": text, "page": 1}
                )
            elif _looks_like_heading(text):
                blocks.append(
                    {
                        "type": "heading",
                        "level": _heading_level(text),
                        "text": text,
                        "page": 1,
                    }
                )
            else:
                blocks.append({"type": "paragraph", "text": text, "page": 1})
        elif tag == "tbl":
            table = Table(child, doc)
            rows = [[(c.text or "").strip() for c in row.cells] for row in table.rows]
            if not rows:
                continue
            html, md = _table_to_html_md(rows)
            blocks.append(
                {
                    "type": "table",
                    "text": md,
                    "html": html,
                    "markdown": md,
                    "page": 1,
                }
            )

    return blocks, None, "python-docx"


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
                    "block_id": f"b{bid}",
                    "type": "heading",
                    "level": level,
                    "page_start": raw.get("page") or raw.get("page_start"),
                    "page_end": raw.get("page_end") or raw.get("page"),
                    "section_path": path,
                    "text": text,
                    "html": None,
                    "markdown": None,
                    "meta": raw.get("meta") or {},
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
                    "block_id": f"b{bid}",
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
                }
            )
        else:
            if not text:
                continue
            blocks.append(
                {
                    "block_id": f"b{bid}",
                    "type": "list" if btype == "list" else "paragraph",
                    "level": None,
                    "page_start": raw.get("page") or raw.get("page_start"),
                    "page_end": raw.get("page_end") or raw.get("page"),
                    "section_path": path,
                    "text": text,
                    "html": None,
                    "markdown": None,
                    "meta": raw.get("meta") or {},
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

def _index_chunks(doc_id: str, meta: dict, chunks: list[dict]) -> None:
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

    # 删除该 doc 旧 chunk
    try:
        es.delete_by_query(
            index=INDEX_NAME,
            body={"query": {"term": {"doc_id": doc_id}}},
            refresh=True,
            conflicts="proceed",
        )
    except Exception as e:
        print(f"⚠️ delete_by_query: {e}")

    filename = meta.get("filename") or ""
    file_type = meta.get("ext") or ""
    for c in chunks:
        c["filename"] = filename
        c["file_type"] = file_type

    texts = [c["content"] for c in chunks]
    embeddings = _embed(texts)

    batch_size = 50
    for i in range(0, len(chunks), batch_size):
        batch_c = chunks[i : i + batch_size]
        batch_e = embeddings[i : i + batch_size]
        bulk_body = ""
        for chunk, emb in zip(batch_c, batch_e):
            action = {"index": {"_index": INDEX_NAME}}
            doc = {
                "doc_id": chunk["doc_id"],
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
            es.bulk(body=bulk_body, refresh=True)


def delete_doc_from_index(doc_id: str) -> None:
    try:
        from elasticsearch import Elasticsearch

        es = Elasticsearch(
            ES_HOST,
            basic_auth=(ES_USER, ES_PASS),
            verify_certs=False,
            ssl_show_warn=False,
        )
        if es.indices.exists(index=INDEX_NAME):
            es.delete_by_query(
                index=INDEX_NAME,
                body={"query": {"term": {"doc_id": doc_id}}},
                refresh=True,
                conflicts="proceed",
            )
    except Exception as e:
        print(f"⚠️ ES 删除 doc {doc_id}: {e}")


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
