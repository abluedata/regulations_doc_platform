"""
兼容本平台约定的薄适配层。

官方 mineru-api 接口：
  POST /file_parse  multipart files + backend=pipeline ...

本平台约定：
  POST /parse  multipart file → { pages, markdown, blocks?, engine, backend }

运行方式（推荐在 venv-mineru 中）：
  1) 先起官方 API（pipeline 不需要 VLM）：
       set MINERU_MODEL_SOURCE=modelscope
       mineru-api --host 127.0.0.1 --port 8001
  2) 再起本适配层（默认 8003，业务侧 MINERU_URL 指向它）：
       python -m mineru_service.server

也可只起 mineru-api，并把业务 MINERU_URL 指到适配层地址。
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any

import httpx

MINERU_API_URL = os.environ.get("MINERU_API_URL", "http://127.0.0.1:8001").rstrip("/")
MINERU_BACKEND = os.environ.get("MINERU_BACKEND", "pipeline")
MINERU_PARSE_METHOD = os.environ.get("MINERU_PARSE_METHOD", "auto")
MINERU_LANG = os.environ.get("MINERU_LANG", "ch")
# CPU 场景默认关闭公式，加速；表格保持开启
MINERU_FORMULA_ENABLE = os.environ.get("MINERU_FORMULA_ENABLE", "false").lower() in (
    "1",
    "true",
    "yes",
)
MINERU_TABLE_ENABLE = os.environ.get("MINERU_TABLE_ENABLE", "true").lower() in (
    "1",
    "true",
    "yes",
)


def _http_client(timeout: float | httpx.Timeout = 5.0) -> httpx.Client:
    # 避免系统代理把 127.0.0.1 打成 502
    return httpx.Client(proxy=None, trust_env=False, timeout=timeout)


def health_upstream() -> dict[str, Any]:
    try:
        with _http_client(5.0) as client:
            r = client.get(f"{MINERU_API_URL}/health")
            r.raise_for_status()
            data = r.json() if r.content else {}
        return {"ok": True, "upstream": MINERU_API_URL, "detail": data}
    except Exception as e:
        return {"ok": False, "upstream": MINERU_API_URL, "error": str(e)}


def parse_file_bytes(
    filename: str,
    content: bytes,
    content_type: str | None = None,
) -> dict[str, Any]:
    """调用上游 mineru-api /file_parse，归一化为平台约定。"""
    if not content:
        raise ValueError("空文件")

    mime = content_type or _guess_mime(filename)
    data = {
        "backend": MINERU_BACKEND,
        "parse_method": MINERU_PARSE_METHOD,
        "lang_list": MINERU_LANG,
        "formula_enable": str(MINERU_FORMULA_ENABLE).lower(),
        "table_enable": str(MINERU_TABLE_ENABLE).lower(),
        "return_md": "true",
        "return_content_list": "true",
        "return_images": "false",
        "return_middle_json": "false",
        "return_model_output": "false",
        "response_format_zip": "false",
        "return_original_file": "false",
    }
    files = {"files": (filename, content, mime)}

    with _http_client(httpx.Timeout(3600.0, connect=10.0)) as client:
        resp = client.post(f"{MINERU_API_URL}/file_parse", data=data, files=files)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"mineru-api 失败 HTTP {resp.status_code}: {resp.text[:500]}"
            )
        payload = resp.json()

    md, pages, content_list = _extract_markdown_and_pages(payload)
    if not md and not content_list:
        raise RuntimeError("MinerU 返回空结果")

    blocks = _content_list_to_blocks(content_list) if content_list else []
    if not blocks and md:
        blocks = _markdown_to_blocks(md)

    return {
        "pages": pages,
        "markdown": md,
        "blocks": blocks,
        # 原始 content_list（含 PDF pt bbox 与 0-based page_idx），供业务侧
        # 落库 evidence_spans.json；task_id 即 mineru-api 的 job 目录名。
        "content_list": content_list,
        "task_id": payload.get("task_id"),
        "engine": "mineru",
        "backend": payload.get("backend") or MINERU_BACKEND,
        "version": payload.get("version"),
        "raw_keys": list(payload.keys()) if isinstance(payload, dict) else [],
    }


def _guess_mime(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(ext, "application/octet-stream")


def _extract_markdown_and_pages(payload: dict) -> tuple[str, int | None, list]:
    """兼容 mineru-api results 字典结构。"""
    results = payload.get("results") if isinstance(payload, dict) else None
    md_parts: list[str] = []
    pages = payload.get("pages") or payload.get("page_count")
    content_list: list = []

    if isinstance(results, dict):
        # results: { file_stem: { md_content / markdown / content_list ... } }
        for _name, item in results.items():
            if not isinstance(item, dict):
                continue
            md = (
                item.get("md_content")
                or item.get("markdown")
                or item.get("md")
                or ""
            )
            if md:
                md_parts.append(str(md))
            cl = item.get("content_list") or item.get("contentList") or []
            if isinstance(cl, list):
                content_list.extend(cl)
            if item.get("page_count") and not pages:
                pages = item.get("page_count")
            if item.get("pages") and not pages:
                pages = item.get("pages")
    elif isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            md = item.get("md_content") or item.get("markdown") or item.get("md") or ""
            if md:
                md_parts.append(str(md))
            cl = item.get("content_list") or []
            if isinstance(cl, list):
                content_list.extend(cl)

    # 顶层直接给 markdown
    if not md_parts:
        top_md = payload.get("markdown") or payload.get("md") or ""
        if top_md:
            md_parts.append(str(top_md))

    md = "\n\n".join(md_parts).strip()

    # 从 content_list 估页数
    if pages is None and content_list:
        max_page = 0
        for it in content_list:
            if isinstance(it, dict):
                p = it.get("page_idx", it.get("page", it.get("page_no")))
                if isinstance(p, int):
                    max_page = max(max_page, p + 1 if p >= 0 else p)
        pages = max_page or None

    return md, pages if isinstance(pages, int) else None, content_list


def _content_list_to_blocks(content_list: list) -> list[dict]:
    blocks: list[dict] = []
    for it in content_list:
        if not isinstance(it, dict):
            continue
        btype = (it.get("type") or it.get("category") or "text").lower()
        page = it.get("page_idx", it.get("page", it.get("page_no")))
        if isinstance(page, int) and page >= 0:
            # mineru content_list 多为 0-based
            page = page + 1
        locator = _mineru_pdf_locator(page, it)
        text = (
            it.get("text")
            or it.get("content")
            or it.get("md")
            or it.get("markdown")
            or ""
        )
        text = str(text).strip() if text is not None else ""

        if btype in ("table", "table_body"):
            html = it.get("table_body") or it.get("html") or ""
            md = it.get("table_body") or it.get("markdown") or text or str(html)
            # 有的版本 table_body 是 html
            if "<table" in str(html).lower() and not text:
                text = _html_table_to_md(str(html))
                md = text
            blocks.append(
                {
                    "type": "table",
                    "text": md if isinstance(md, str) else text,
                    "html": html if isinstance(html, str) else None,
                    "markdown": md if isinstance(md, str) else text,
                    "page": page,
                    "locator": locator,
                }
            )
            continue

        if btype in ("title", "heading", "header"):
            if not text:
                continue
            level = it.get("text_level") or it.get("level") or 1
            try:
                level = int(level)
            except (TypeError, ValueError):
                level = 1
            blocks.append(
                {
                    "type": "heading",
                    "level": max(1, min(level, 6)),
                    "text": text.replace("\n", " "),
                    "page": page,
                    "locator": locator,
                }
            )
            continue

        if btype in ("image", "figure", "equation", "discarded"):
            # 图片说明可保留
            if text:
                blocks.append(
                    {
                        "type": "paragraph",
                        "text": text,
                        "page": page,
                        "locator": locator,
                    }
                )
            continue

        if not text:
            continue
        blocks.append(
            {
                "type": "list" if btype in ("list", "list_item") else "paragraph",
                "text": text.replace("\n", " ") if btype != "list" else text,
                "page": page,
                "locator": locator,
            }
        )
    return blocks


def _mineru_pdf_locator(page: Any, item: dict) -> dict:
    """Normalize MinerU 3.4.x content-list geometry without guessing its scale."""
    page_number = page if isinstance(page, int) and page > 0 else None
    locator = {
        "kind": "pdf",
        "page_number": page_number,
        "origin": "top_left",
        "coordinate_system": "normalized_0_1000",
        "rects": [],
        "precision": "page" if page_number else "unknown",
    }
    raw = item.get("bbox", item.get("box", item.get("rect")))
    if isinstance(raw, dict):
        raw = [raw.get("x0"), raw.get("y0"), raw.get("x1"), raw.get("y1")]
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return locator
    try:
        values = [float(v) for v in raw]
    except (TypeError, ValueError):
        return locator
    if not all(math.isfinite(v) for v in values):
        return locator
    x0, y0, x1, y1 = values
    if x1 <= x0 or y1 <= y0 or max(x0, y0) > 1000 or min(x1, y1) < 0:
        return locator
    # MinerU content-list bboxes are already in its documented 0..1000 space.
    x0, y0, x1, y1 = [max(0.0, min(1000.0, v)) for v in values]
    if x1 <= x0 or y1 <= y0:
        return locator
    locator["rects"] = [{"x0": x0, "y0": y0, "x1": x1, "y1": y1}]
    locator["precision"] = "exact"
    return locator


def _markdown_to_blocks(md: str) -> list[dict]:
    blocks: list[dict] = []
    lines = md.splitlines()
    i = 0
    para_buf: list[str] = []

    def flush_para() -> None:
        nonlocal para_buf
        text = "\n".join(para_buf).strip()
        para_buf = []
        if text:
            blocks.append({"type": "paragraph", "text": text.replace("\n", " ")})

    while i < len(lines):
        line = lines[i]
        # table
        if line.strip().startswith("|") and i + 1 < len(lines) and re.search(
            r"\|\s*[-:]+", lines[i + 1]
        ):
            flush_para()
            table_lines = [line]
            i += 1
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            md_table = "\n".join(table_lines)
            blocks.append(
                {
                    "type": "table",
                    "text": md_table,
                    "markdown": md_table,
                    "html": None,
                }
            )
            continue
        m = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if m:
            flush_para()
            blocks.append(
                {
                    "type": "heading",
                    "level": len(m.group(1)),
                    "text": m.group(2).strip(),
                }
            )
            i += 1
            continue
        if not line.strip():
            flush_para()
            i += 1
            continue
        para_buf.append(line)
        i += 1
    flush_para()
    return blocks


def _html_table_to_md(html: str) -> str:
    # 极简：去标签按行列粗提
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.I | re.S)
    if not rows:
        return re.sub(r"<[^>]+>", " ", html)
    md_rows: list[list[str]] = []
    for row in rows:
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.I | re.S)
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if cells:
            md_rows.append(cells)
    if not md_rows:
        return ""
    width = max(len(r) for r in md_rows)
    norm = [r + [""] * (width - len(r)) for r in md_rows]
    lines = ["| " + " | ".join(norm[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    for r in norm[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)
