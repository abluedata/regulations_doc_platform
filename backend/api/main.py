"""
FastAPI 入口 — Vue3 前端配套 API 服务。

启动：
  uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import sys
import io
from pathlib import Path

# 保证项目根目录在 sys.path（uvicorn 从任意 cwd 启动时）
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Windows 控制台编码兼容（后台/无控制台进程可能无 buffer 或 write 抛 OSError 22）
if sys.platform == "win32":
    def _rewrap(stream):
        try:
            buf = getattr(stream, "buffer", None)
            if buf is None:
                return stream
            return io.TextIOWrapper(
                buf, encoding="utf-8", errors="replace", line_buffering=True
            )
        except Exception:
            return stream

    try:
        sys.stdout = _rewrap(sys.stdout)
        sys.stderr = _rewrap(sys.stderr)
    except Exception:
        pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import chat, docs, favorites, history
from api.schemas import HealthResponse

app = FastAPI(
    title="审核智规 API",
    description="Vue3 前端配套 REST / SSE 接口",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(favorites.router, prefix="/api")
app.include_router(docs.router, prefix="/api")


@app.get("/api/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok")


@app.get("/api/health/index")
def health_index():
    """检查 ES 索引是否可用。"""
    try:
        from elasticsearch import Elasticsearch
        from core.config import ES_HOST, ES_USER, ES_PASS, INDEX_NAME

        es = Elasticsearch(
            ES_HOST,
            basic_auth=(ES_USER, ES_PASS),
            verify_certs=False,
            ssl_show_warn=False,
        )
        exists = es.indices.exists(index=INDEX_NAME)
        count = es.count(index=INDEX_NAME)["count"] if exists else 0
        return {
            "status": "ok" if exists else "missing",
            "index": INDEX_NAME,
            "exists": bool(exists),
            "count": count,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
