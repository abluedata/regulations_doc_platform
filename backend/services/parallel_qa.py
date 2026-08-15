"""
并行问答模块 — 大上下文模式

对大文档/多文档场景，用大上下文窗口一次处理，避免多轮串行 LLM 调用。

流程：
  1. 搜索 top-K 个相关 chunks（K=30）
  2. 把 chunks 拼接成一个大 context
  3. 一次 LLM 调用出完整回答（3-5 秒）
"""

import logging

from core.config import (
    LLM_API_BASE,
    LLM_API_KEY,
    LLM_MODEL_FAST,
    PARALLEL_SEARCH_K,
)
from core.http_client import httpx_client

logger = logging.getLogger(__name__)


def _safe_log(msg: str) -> None:
    try:
        logger.info(msg)
    except Exception:
        pass
    try:
        print(msg, flush=True)
    except OSError:
        pass


# ─── 搜索 ────────────────────────────────────────────────────

def parallel_search(query: str, k: int = None) -> list[dict]:
    """获取更多候选 chunks（单次搜索 + 更大 K）"""
    from services.search import search_local
    k = k or PARALLEL_SEARCH_K
    return search_local(query, k)


# ─── 大上下文一次性回答 ─────────────────────────────────────

SYSTEM_PROMPT = """你是一个专业的保险条款问答助手。请根据提供的参考文档回答用户问题。

要求：
1. 仅基于提供的参考文档回答，不要编造信息
2. 如果文档不足以回答，明确说明
3. 引用来源（文档标题 + chunk 编号）
4. 用中文回答，专业、简洁、准确
5. 如果是多文档对比，用表格形式呈现
6. 如果参考文档包含表格，请用散文总结要点并引用来源；不要逐格列出每个单元格；系统会在回答后附加原文表格"""


def parallel_qa(query: str) -> dict:
    """大上下文模式：一次搜索 + 一次 LLM 回答

    Returns:
        dict: {"final_answer": str, "chunks_used": int}
    """
    _safe_log(f"大上下文模式: {query!r}")

    # 1. 搜索
    _safe_log("搜索 chunks ...")
    chunks = parallel_search(query)
    _safe_log(f"  → {len(chunks)} 个 chunks")

    if not chunks:
        return {"final_answer": "未检索到相关文档内容", "chunks_used": 0}

    # 2. 拼接大 context
    context_parts = []
    for i, c in enumerate(chunks, 1):
        context_parts.append(
            f"[{i}] 文档: {c.get('title', '未知')} (chunk {c.get('chunk_id', '?')})\n"
            f"{c.get('content', '')}"
        )
    context = "\n\n---\n\n".join(context_parts)

    # 3. 一次 LLM
    _safe_log(f"生成回答（{len(context)} 字符 context，fast model）...")
    try:
        with httpx_client(timeout=120) as client:
            resp = client.post(
                f"{LLM_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_MODEL_FAST,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"""## 参考文档

{context}

## 用户问题

{query}"""},
                ],
                "max_tokens": 4096,
                "temperature": 0.3,
                "stream": False,
            },
            )
        resp.raise_for_status()
        final_answer = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        # 流式降级
        from services.qa_service import ask_llm_stream

        final_answer = ""
        for token in ask_llm_stream(query, context):
            final_answer += token

    return {"final_answer": final_answer, "chunks_used": len(chunks)}
