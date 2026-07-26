"""
混合搜索模块 — BM25 + Vector (手动 RRF) + Route 路由

流程：
  用户提问 → BM25 + Vector 混合搜索本地
    → LLM 判断本地知识是否足够
    → 足够: 只用本地结果
    → 不足: 再调用 Tavily 补充
"""
import json
import logging

import httpx
import requests

from core.config import (
    ES_HOST,
    ES_PASS,
    ES_USER,
    EMBED_API_BASE,
    EMBED_API_KEY,
    EMBED_DIMS,
    EMBED_IS_JINA,
    EMBED_MODEL,
    HYBRID_NUM_CANDIDATES,
    HYBRID_SEARCH_K,
    INDEX_NAME,
    RRF_RANK_CONSTANT,
    TAVILY_API_KEY,
    LLM_API_BASE,
    LLM_API_KEY,
    LLM_MODEL,
    LLM_MODEL_FAST,
    ROUTE_SYSTEM_PROMPT,
    TABLE_CONTEXT_MAX_CHARS,
)
from services.utils import (
    looks_like_html_table,
    looks_like_markdown_table,
    normalize_table_fields,
)
from services.document_store import index_visibility_snapshot
from elasticsearch import Elasticsearch

logger = logging.getLogger(__name__)


def _safe_log(msg: str, level: int = logging.INFO) -> None:
    """写日志；Windows 后台进程 stdout 损坏时 print 会抛 [Errno 22]，不可直接 print。"""
    try:
        logger.log(level, msg)
    except Exception:
        pass
    try:
        print(msg, flush=True)
    except OSError:
        pass


# ─── Embedding 客户端 ──────────────────────────────────────
from functools import lru_cache

EMBED_HEADERS = {
    "Authorization": f"Bearer {EMBED_API_KEY}",
    "Content-Type": "application/json",
}

# ES 连接池（复用）
_es_instance = None

_embed_cache = {}


def get_embeddings(texts: list[str], task: str = "retrieval.query", max_retries: int = 2) -> list[list[float]]:
    """获取 Embedding（OpenAI 兼容，默认 SiliconFlow；带缓存 + 重试机制）"""
    cache_key = "||".join(texts) + "::" + task
    if cache_key in _embed_cache:
        return _embed_cache[cache_key]

    url = f"{EMBED_API_BASE}/embeddings"
    for attempt in range(max_retries + 1):
        try:
            payload: dict = {"model": EMBED_MODEL, "input": texts}
            if EMBED_IS_JINA:
                payload["task"] = task
                payload["dimensions"] = EMBED_DIMS
            resp = requests.post(url, headers=EMBED_HEADERS, json=payload, timeout=60)
            resp.raise_for_status()
            result = [d["embedding"] for d in resp.json()["data"]]
            _embed_cache[cache_key] = result
            return result
        except Exception as e:
            if attempt < max_retries:
                import time
                wait = 2 ** attempt
                _safe_log(f"Embedding 重试 {attempt+1}/{max_retries}: {e}，等待 {wait}s", logging.WARNING)
                time.sleep(wait)
            else:
                _safe_log(f"Embedding 最终失败 ({max_retries+1} 次): {e}", logging.WARNING)
                raise


# ─── ES 客户端（复用连接池）─────────────────────────────────

def get_es() -> Elasticsearch:
    global _es_instance
    if _es_instance is None:
        _es_instance = Elasticsearch(
            ES_HOST,
            basic_auth=(ES_USER, ES_PASS),
            verify_certs=False,
            ssl_show_warn=False,
        )
    return _es_instance


# ─── Tavily 搜索 ────────────────────────────────────────────

def tavily_search(query: str, max_results: int = 3) -> list[dict]:
    """通过 Tavily API 搜索网络"""
    resp = httpx.post(
        "https://api.tavily.com/search",
        json={
            "api_key": TAVILY_API_KEY,
            "query": query,
            "max_results": max_results,
            "search_depth": "advanced",
        },
        verify=False,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return [
        {
            "title": r["title"],
            "content": r["content"],
            "url": r["url"],
            "score": r.get("score", 0.5),
            "source": "tavily",
            "chunk_id": -1,
            "doc_id": r["url"],
        }
        for r in data.get("results", [])
    ]


# ─── Route 路由 ────────────────────────────────────────────

def route_decision(query: str, local_context: str) -> str:
    """让 LLM 判断本地知识是否足够回答用户问题

    Returns:
        "local" — 本地知识足够
        "web"   — 需要网络搜索补充
    """
    try:
        resp = httpx.post(
            f"{LLM_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_MODEL_FAST,  # 路由判断用 fast 模型（v4flash）加速
                "messages": [
                    {"role": "system", "content": ROUTE_SYSTEM_PROMPT},
                    {"role": "user", "content": f"""用户问题: {query}

本地知识库检索到的内容:
{local_context}"""},
                ],
                "max_tokens": 16,
                "temperature": 0.0,
                "stream": False,
            },
            timeout=30,
            verify=False,
        )
        resp.raise_for_status()
        decision = resp.json()["choices"][0]["message"]["content"].strip().lower()
        # 只取 local 或 web
        if "local" in decision:
            return "local"
        return "web"
    except Exception as e:
        _safe_log(f"Route 判断失败: {e}，默认走 local", logging.WARNING)
        return "local"


# ─── 本地搜索 (BM25 + Vector) ─────────────────────────────

def search_local(query: str, k: int = None) -> list[dict]:
    """仅在本地 ES 搜索（BM25 + Vector + 手动 RRF）"""
    es = get_es()
    k = k or HYBRID_SEARCH_K

    # 1. 向量化查询
    try:
        q_emb = get_embeddings([query])[0]
    except Exception as e:
        _safe_log(f"Embedding 失败: {e}", logging.WARNING)
        q_emb = None

    active_keys, versioned_doc_ids = index_visibility_snapshot()
    legacy_filter: dict = {
        "bool": {"must_not": [{"exists": {"field": "visibility_key"}}]}
    }
    if versioned_doc_ids:
        legacy_filter["bool"]["must_not"].append(
            {"terms": {"doc_id": versioned_doc_ids}}
        )
    visibility_should = [legacy_filter]
    if active_keys:
        visibility_should.insert(0, {"terms": {"visibility_key": active_keys}})
    visibility_filter = {
        "bool": {"should": visibility_should, "minimum_should_match": 1}
    }

    # --- 2a. BM25 搜索 ---
    bm25_body = {
        "query": {
            "bool": {
                "must": [{
                    "multi_match": {
                        "query": query,
                        "fields": ["title^3", "content"],
                        "type": "best_fields",
                    }
                }],
                "filter": [visibility_filter],
            }
        },
        "size": k * 2,
        "_source": {"excludes": ["embedding"]},
    }
    bm25_result = es.search(index=INDEX_NAME, body=bm25_body)

    # --- 2b. Vector 搜索 ---
    knn_results_raw = []
    if q_emb:
        knn_body = {
            "knn": {
                "field": "embedding",
                "query_vector": q_emb,
                "k": k,
                "num_candidates": HYBRID_NUM_CANDIDATES,
                "filter": visibility_filter,
            },
            "size": k * 2,
            "_source": {"excludes": ["embedding"]},
        }
        knn_result = es.search(index=INDEX_NAME, body=knn_body)
        knn_results_raw = knn_result["hits"]["hits"]

    # --- 2c. 手动 RRF 融合 ---
    bm25_hits = bm25_result["hits"]["hits"]
    ranked = {}

    def _rrf_score(rank: int, const: float = RRF_RANK_CONSTANT) -> float:
        return 1.0 / (const + rank + 1)

    for rank, hit in enumerate(bm25_hits):
        src = hit["_source"]
        key = (
            f"{src.get('doc_id','')}:{src.get('document_version_id','legacy')}:"
            f"{src.get('chunk_id','')}"
        )
        ranked.setdefault(key, {"doc": src, "score": 0})
        ranked[key]["score"] += _rrf_score(rank)

    for rank, hit in enumerate(knn_results_raw):
        src = hit["_source"]
        key = (
            f"{src.get('doc_id','')}:{src.get('document_version_id','legacy')}:"
            f"{src.get('chunk_id','')}"
        )
        ranked.setdefault(key, {"doc": src, "score": 0})
        ranked[key]["score"] += _rrf_score(rank)

    sorted_items = sorted(ranked.items(), key=lambda x: x[1]["score"], reverse=True)

    results = []
    for key, item in sorted_items[:k]:
        src = item["doc"]
        results.append({
            "title": src.get("title", ""),
            "content": src.get("content", ""),
            "doc_id": src.get("doc_id", ""),
            "chunk_id": src.get("chunk_id", -1),
            "filename": src.get("filename", ""),
            "score": item["score"],
            "source": "local",
            "block_type": src.get("block_type"),
            "section_path": src.get("section_path") or "",
        })
    return results


# ─── 主搜索入口（带路由） ─────────────────────────────────

def hybrid_search(query: str, k: int = None) -> dict:
    """混合搜索主入口（带 Route 路由）

    流程：
      1. 始终先搜索本地 ES (BM25 + Vector + RRF)
      2. 用 LLM 判断本地知识是否足够回答
      3. 不够时才调用 Tavily

    Returns:
        dict: {
            "local": [...],   # ES 本地搜索结果
            "web": [...],     # Tavily 搜索结果 (可能为空)
            "has_web": bool,  # 是否使用了 Tavily
            "route": str,     # "local" 或 "web" 路由决策
        }
    """
    k = k or HYBRID_SEARCH_K

    # 1. 始终先搜索本地
    local_results = search_local(query, k)

    # 2. 构造本地上下文给 Route 判断
    local_context_parts = []
    for r in local_results[:3]:
        local_context_parts.append(f"[{r['title']}]\n{r['content'][:300]}")
    local_context = "\n\n".join(local_context_parts)

    # 3. Route 判断
    route = route_decision(query, local_context)
    _safe_log(f"Route 决策: {route}")

    # 4. 已禁用网络搜索：即便路由判定 web，也不调用 Tavily
    #    路由结果只作为标签展示（"本地足够" / "本地不足"）
    _safe_log(f"路由判定={route}，已禁用网络搜索，仅用本地结果")

    return {
        "local": local_results,
        "web": [],
        "has_web": False,
        "route": route,
    }


def _is_table_hit(r: dict) -> bool:
    """Return True if this result represents a table (by block_type or content)."""
    if (r.get("block_type") or "").lower() == "table":
        return True
    content = r.get("content", "") or ""
    return looks_like_html_table(content) or looks_like_markdown_table(content)


def format_results_for_llm(search_result: dict, max_chars: int = 6000) -> str:
    """将搜索结果格式化为 LLM 能消费的上下文"""
    parts = []
    has_table = False

    if search_result["local"]:
        parts.append("## 📄 本地文档检索结果\n")
        for i, r in enumerate(search_result["local"][:6], 1):
            parts.append(f"### [{i}] {r['title']}\n")
            if r.get("filename"):
                parts.append(f"> 来源: {r['filename']}  (chunk {r['chunk_id']})\n")
            if r.get("section_path"):
                parts.append(f"> 章节: {r['section_path']}\n")
            content = r["content"]
            if _is_table_hit(r):
                has_table = True
                limit = TABLE_CONTEXT_MAX_CHARS
                # Try convert embedded HTML in content to markdown while keeping [文档]/[章节] headers if present
                if looks_like_html_table(content):
                    try:
                        norm = normalize_table_fields(html=content)
                        md = norm.get("markdown", "")
                        if md:
                            # Preserve any leading [文档]/[章节] header lines
                            lines = content.splitlines()
                            header_lines = []
                            for ln in lines:
                                stripped = ln.strip()
                                if stripped.startswith("[文档]") or stripped.startswith("[章节]"):
                                    header_lines.append(ln)
                                else:
                                    break
                            prefix = "\n".join(header_lines).strip()
                            if prefix:
                                content = f"{prefix}\n\n{md}"
                            else:
                                content = md
                    except Exception:
                        pass
                if len(content) > limit:
                    content = content[:limit] + "..."
            else:
                if len(content) > 800:
                    content = content[:800] + "..."
            parts.append(f"{content}\n")

    if search_result["web"]:
        parts.append("\n## 🌐 网络搜索结果\n")
        for i, r in enumerate(search_result["web"], 1):
            parts.append(f"### [Web {i}] {r['title']}\n")
            parts.append(f"> 链接: {r['url']}\n")
            content = r["content"]
            if len(content) > 800:
                content = content[:800] + "..."
            parts.append(f"{content}\n")

    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n...(截断)"

    if has_table:
        # Instruction: system will attach original table; don't re-list every cell; don't invent rows
        instr = "\n注意：系统将在答案后附加原文表格，请不要逐格复述表格内容，也不要编造表格行。"
        text = text + instr

    return text
