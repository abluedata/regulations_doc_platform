"""
文档索引模块 — 读取 docs/ → 分块 → Embedding → ES 入库
"""

import glob
import json
import os
import sys
import time

import requests

from core.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    DOCS_DIR,
    EMBED_API_BASE,
    EMBED_API_KEY,
    EMBED_DIMS,
    EMBED_IS_JINA,
    EMBED_MAX_CHARS,
    EMBED_MODEL,
    ES_HOST,
    ES_PASS,
    ES_USER,
    INDEX_NAME,
)
from services.knowledge.chunk_strategy import chunk_documents
from services.common.utils import truncate_for_embedding
from elasticsearch import Elasticsearch
from core.http_client import elasticsearch_client, requests_session


# ─── ES 连接 ────────────────────────────────────────────────

def get_es() -> Elasticsearch:
    es = elasticsearch_client(ES_HOST, username=ES_USER, password=ES_PASS)
    if not es.ping():
        raise RuntimeError(f"❌ 无法连接 ES: {ES_HOST}")
    print(f"✅ ES 已连接  (v{es.info()['version']['number']})")
    return es


# ─── Embedding（OpenAI 兼容 /v1/embeddings）────────────────

EMBED_HEADERS = {
    "Authorization": f"Bearer {EMBED_API_KEY}",
    "Content-Type": "application/json",
}


def get_embeddings(texts: list[str], task: str = "retrieval.passage") -> list[list[float]]:
    """调用 Embedding API 批量获取向量（默认硅基流动 SiliconFlow，兼容 Jina）

    Args:
        texts: 文本列表
        task: retrieval.passage (入库) 或 retrieval.query (搜索) —— 仅 Jina 生效

    Returns:
        list[list[float]]: 每个文本对应的向量
    """
    if not EMBED_API_KEY:
        raise ValueError("EMBED_API_KEY 未设置！请在 .env 或环境变量中配置 EMBED_API_KEY")

    # token 安全截断兜底：BAAI/bge-large-zh-v1.5 上下文 512 token，
    # 超 ~616 字符即被 SiliconFlow 拒绝（HTTP 400 code 20015）。
    # 截断保留 [文档]/[章节] 标题头部，确保任何超限 chunk 都不会导致入库失败。
    texts = [truncate_for_embedding(t, EMBED_MAX_CHARS) for t in texts]

    # 每次最多 100 条，分批
    all_embeddings = []
    batch_size = 100
    url = f"{EMBED_API_BASE}/embeddings"
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        payload: dict = {"model": EMBED_MODEL, "input": batch}
        # task / dimensions 仅 Jina 支持；SiliconFlow 的 bge-m3 等不支持 dimensions
        if EMBED_IS_JINA:
            payload["task"] = task
            payload["dimensions"] = EMBED_DIMS
        with requests_session() as session:
            resp = session.post(url, headers=EMBED_HEADERS, json=payload, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"Embedding API 错误 ({resp.status_code}): {resp.text}")

        data = resp.json()
        for d in data["data"]:
            all_embeddings.append(d["embedding"])

        print(f"   ↪ 已向量化 {len(all_embeddings)}/{len(texts)} 条", end="\r")

    print()
    return all_embeddings


# ─── 文档读取 ────────────────────────────────────────────────

def get_title_from_filename(filename: str) -> str:
    """从文件名提取语义标题"""
    name = filename.replace(".txt", "").replace(".pdf", "")
    if name[0].isdigit() and "-" in name:
        name = name.split("-", 1)[1]
    return name


def read_all_docs() -> list[dict]:
    """扫描 docs/ 下所有 .txt/.pdf，返回 [{text, title, doc_id, filename}]"""
    files = sorted(glob.glob(os.path.join(DOCS_DIR, "*.txt"))) + \
            sorted(glob.glob(os.path.join(DOCS_DIR, "*.pdf")))

    if not files:
        raise FileNotFoundError(f"❌ {DOCS_DIR} 下没有 .txt 或 .pdf 文件")

    docs = []
    for fp in files:
        fn = os.path.basename(fp)
        ext = os.path.splitext(fn)[1].lower()
        title = get_title_from_filename(fn)

        if ext == ".txt":
            with open(fp, "r", encoding="utf-8") as f:
                text = f.read()
        elif ext == ".pdf":
            # 复用已有的 pdf 提取逻辑（或使用 pdfplumber）
            try:
                import pdfplumber
                pdf = pdfplumber.open(fp)
                pages = []
                for page in pdf.pages:
                    t = page.extract_text()
                    if t and t.strip():
                        pages.append(t.strip())
                pdf.close()
                text = "\n".join(pages) if pages else ""
            except ImportError:
                print(f"  ⚠️ pdfplumber 未安装，跳过 {fn}")
                continue
        else:
            continue

        if not text.strip():
            print(f"  ⚠️ 空内容跳过: {fn}")
            continue

        docs.append({
            "text": text,
            "title": title,
            "doc_id": fn,
            "filename": fn,
            "file_type": ext.replace(".", ""),
        })
        print(f"  📄 {fn:55s} {len(text):>7} chars")

    print(f"   共 {len(docs)} 篇文档")
    return docs


# ─── ES 索引管理 ────────────────────────────────────────────

def create_index_if_not_exists(es: Elasticsearch):
    """如果 knowledge_base 索引不存在则创建"""
    if es.indices.exists(index=INDEX_NAME):
        print(f"📂 索引 '{INDEX_NAME}' 已存在，跳过创建")
        return

    mapping = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
        "mappings": {
            "properties": {
                "doc_id":    {"type": "keyword"},
                "filename":  {"type": "keyword"},
                "title":     {"type": "text"},
                "chunk_id":  {"type": "integer"},
                "content":   {"type": "text"},
                "file_type": {"type": "keyword"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": EMBED_DIMS,
                    "index": True,
                    "similarity": "cosine",
                },
            }
        },
    }

    es.indices.create(index=INDEX_NAME, body=mapping)
    print(f"✅ 索引 '{INDEX_NAME}' 已创建 (dims={EMBED_DIMS})")


# ─── 批量写入 ES ────────────────────────────────────────────

def index_chunks(es: Elasticsearch, chunks: list[dict], embeddings: list[list[float]]):
    """将分块+向量写入 ES，每批 50 条"""
    batch_size = 50
    total = len(chunks)

    for i in range(0, total, batch_size):
        batch_chunks = chunks[i : i + batch_size]
        batch_embs = embeddings[i : i + batch_size]

        bulk_body = ""
        for chunk, emb in zip(batch_chunks, batch_embs):
            action = {"index": {"_index": INDEX_NAME}}
            doc = {**chunk, "embedding": emb}
            bulk_body += json.dumps(action, ensure_ascii=False) + "\n"
            bulk_body += json.dumps(doc, ensure_ascii=False) + "\n"

        resp = es.bulk(body=bulk_body, refresh=True)
        if resp.get("errors"):
            print(f"\n⚠️ 写入错误: {resp['items'][0]['index'].get('error', 'unknown')}")

        print(f"   ↪ 已写入 {min(i + batch_size, total)}/{total}", end="\r")

    print()
    print(f"✅ 全部 {total} 条 chunk 已写入 '{INDEX_NAME}'")


# ─── 主流程 ────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Embedding → ES 文档索引")
    print("=" * 60)

    # 1. 连接 ES
    es = get_es()

    # 2. 创建索引
    create_index_if_not_exists(es)

    # 3. 读取文档
    print("\n📖 读取文档 ...")
    docs = read_all_docs()

    # 4. 分块
    print(f"\n✂️  分块 (chunk_size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}) ...")
    chunks = chunk_documents(docs)
    print(f"   → {len(chunks)} 个 chunk")

    # 5. 向量化
    print(f"\n🧠  Embedding ...")
    texts = [c["content"] for c in chunks]
    embeddings = get_embeddings(texts, task="retrieval.passage")

    # 6. 写入 ES
    print(f"\n💾 写入 ES ...")
    index_chunks(es, chunks, embeddings)

    # 7. 统计
    es.indices.refresh(index=INDEX_NAME)
    count = es.count(index=INDEX_NAME)["count"]
    print(f"\n🎉 完成！索引 '{INDEX_NAME}' 中共 {count} 条文档")


if __name__ == "__main__":
    main()
