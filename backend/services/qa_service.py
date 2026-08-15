"""
问答服务 — FastAPI /api/chat 流式回答。

产出事件（dict）：
  {"type": "status", "status": "searching"|"parallel"}
  {"type": "token", "content": str}
  {"type": "done", "route": str, "has_web": bool, "answer": str}
  {"type": "error", "message": str}
"""
from __future__ import annotations

import json
import threading
import time
from typing import Iterator

import httpx

from core.config import (
    LLM_API_BASE,
    LLM_API_KEY,
    LLM_MODEL,
    ANSWER_ATTACH_TABLES,
    ANSWER_MAX_TABLES,
)
from core.http_client import httpx_client
from services.utils import extract_tables_from_hits
from services.search import hybrid_search, format_results_for_llm

COMPLEX_KEYWORDS = ("比较", "区别", "各", "分别", "所有", "总结", "汇总")

SYSTEM_PROMPT = """你是一个专业的保险条款问答助手。请根据提供的参考文档回答用户问题。
要求：
1. 仅基于提供的参考文档回答
2. 如果参考文档不足以回答，明确说明
3. 引用来源（文档标题）
4. 用中文回答，专业、简洁、准确
5. 如果参考文档包含表格，请用散文总结要点并引用来源；不要逐格列出每个单元格；系统会在回答后附加原文表格"""

EXAMPLES = [
    "工伤保险和雇主险有什么区别？",
    "雇主责任险的赔偿范围是什么？",
    "商业综合责任保险是什么？",
    "比较所有保险产品的保障范围区别",
]


def is_complex_question(text: str) -> bool:
    return len(text) > 20 or any(kw in text for kw in COMPLEX_KEYWORDS)


def _cancelled(cancel_event: threading.Event | None) -> bool:
    return bool(cancel_event and cancel_event.is_set())


def ask_llm_stream(
    query: str,
    context: str,
    cancel_event: threading.Event | None = None,
) -> Iterator[str]:
    """流式生成回答；cancel_event 置位时停止。"""
    try:
        with httpx_client(
            timeout=httpx.Timeout(300.0, connect=15.0, read=300.0, write=30.0, pool=10.0),
            http2=False,
            trust_env=False,
        ) as client:
            with client.stream(
                "POST",
                f"{LLM_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": f"## 参考文档\n\n{context}\n\n## 用户问题\n\n{query}",
                        },
                    ],
                    "max_tokens": 4096,
                    "temperature": 0.3,
                    "stream": True,
                },
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if _cancelled(cancel_event):
                        resp.close()
                        break
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data: "):
                        ds = line[6:].strip()
                        if ds == "[DONE]":
                            break
                        try:
                            chunk = json.loads(ds)
                            for c in chunk.get("choices", []):
                                d = c.get("delta", {})
                                if d.get("content"):
                                    yield d["content"]
                        except json.JSONDecodeError:
                            continue
    except Exception as e:
        if not _cancelled(cancel_event):
            yield f"❌ LLM 流式调用失败: {e}"


def build_table_appendix(tables: list[dict]) -> str:
    if not tables:
        return ""
    parts = ["\n\n---\n\n## 原文表格\n"]
    for t in tables:
        src = t.get("filename") or t.get("doc_id") or "文档"
        sec = t.get("section_path") or ""
        cite = f"{src}" + (f" · {sec}" if sec else "")
        parts.append(f"\n> 来源：{cite}\n\n")
        parts.append((t.get("markdown") or "").strip() + "\n")
    return "".join(parts)


def stream_answer(
    query: str,
    cancel_event: threading.Event | None = None,
) -> Iterator[dict]:
    """统一流式问答：状态 → token → done/error。"""
    text = (query or "").strip()
    if not text:
        yield {"type": "error", "message": "请输入问题"}
        return

    start_time = time.time()
    route = "local"
    has_web = False
    accumulated = ""
    tables: list[dict] = []

    try:
        if is_complex_question(text):
            yield {"type": "status", "status": "parallel"}
            from services.parallel_qa import parallel_qa

            result = parallel_qa(text)
            if _cancelled(cancel_event):
                yield {
                    "type": "done",
                    "route": route,
                    "has_web": has_web,
                    "answer": accumulated,
                }
                return

            elapsed = time.time() - start_time
            header = (
                f"> 🚀 并行问答 *(处理 {result['chunks_used']} 个片段, "
                f"耗时 {elapsed:.1f}s)*\n\n"
            )
            accumulated = header
            yield {"type": "token", "content": header}

            for token in result["final_answer"]:
                if _cancelled(cancel_event):
                    break
                accumulated += token
                yield {"type": "token", "content": token}

            # parallel branch: extract tables from parallel_search hits for complex Qs
            if ANSWER_ATTACH_TABLES:
                try:
                    from services.parallel_qa import parallel_search
                    hits = parallel_search(text) or []
                    tables = extract_tables_from_hits(hits, max_tables=ANSWER_MAX_TABLES)
                except Exception:
                    tables = []
            if tables and not _cancelled(cancel_event):
                appendix = build_table_appendix(tables)
                if appendix:
                    accumulated += appendix
                    yield {"type": "token", "content": appendix}
        else:
            yield {"type": "status", "status": "searching"}
            search_result = hybrid_search(text)
            if _cancelled(cancel_event):
                yield {
                    "type": "done",
                    "route": route,
                    "has_web": has_web,
                    "answer": accumulated,
                }
                return

            context = format_results_for_llm(search_result)
            route = search_result.get("route", "local")
            has_web = bool(search_result.get("has_web", False))
            elapsed = time.time() - start_time
            header = f"> 📚 本地知识库 *(耗时 {elapsed:.1f}s)*\n\n"
            accumulated = header
            yield {"type": "token", "content": header}

            # local branch: extract tables after hybrid_search
            if ANSWER_ATTACH_TABLES:
                tables = extract_tables_from_hits(
                    search_result.get("local") or [], max_tables=ANSWER_MAX_TABLES
                )

            for token in ask_llm_stream(text, context, cancel_event=cancel_event):
                if _cancelled(cancel_event):
                    break
                accumulated += token
                yield {"type": "token", "content": token}

            if tables and not _cancelled(cancel_event):
                appendix = build_table_appendix(tables)
                if appendix:
                    accumulated += appendix
                    yield {"type": "token", "content": appendix}

        yield {
            "type": "done",
            "route": route,
            "has_web": has_web,
            "answer": accumulated,
        }
    except Exception as e:
        yield {"type": "error", "message": str(e)}
