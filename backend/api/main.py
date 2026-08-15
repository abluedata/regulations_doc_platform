"""
FastAPI 入口 — Vue3 前端配套 API 服务。

启动：
  uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import sys
import io
import logging
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

from api.routes import chat, docs, favorites, history, review
from api.schemas import HealthResponse
from api.middleware.auth import LocalOnlyAuthMiddleware, validate_bind_host
from api.middleware.errors import ErrorProtocolMiddleware, install_error_handlers
from api.middleware.logging import RequestLoggingMiddleware
from core.log_redactor import SecretRedactionFilter, validate_startup_secrets

app = FastAPI(
    title="审核智规 API",
    description="Vue3 前端配套 REST / SSE 接口",
    version="1.0.0",
)

install_error_handlers(app)
app.add_middleware(ErrorProtocolMiddleware)
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
app.add_middleware(LocalOnlyAuthMiddleware)
app.add_middleware(RequestLoggingMiddleware)

for handler in logging.getLogger().handlers:
    handler.addFilter(SecretRedactionFilter())

app.include_router(chat.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(favorites.router, prefix="/api")
app.include_router(docs.router, prefix="/api")
app.include_router(review.router, prefix="/api")


def reconcile_document_publications() -> None:
    from services import document_store

    document_store.reconcile_pending_publications()
    document_store.reconcile_pending_deletions()


def validate_security_boundary() -> None:
    validate_bind_host()
    validate_startup_secrets()


app.router.add_event_handler("startup", validate_security_boundary)
app.router.add_event_handler("startup", reconcile_document_publications)
app.router.add_event_handler("startup", review.startup_drift_scan)


@app.get("/api/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok")


@app.get("/api/health/index")
def health_index():
    """检查 ES 索引是否可用。"""
    try:
        from core.config import ES_HOST, ES_USER, ES_PASS, INDEX_NAME
        from core.http_client import elasticsearch_client
        es = elasticsearch_client(ES_HOST, username=ES_USER, password=ES_PASS)
        exists = es.indices.exists(index=INDEX_NAME)
        count = es.count(index=INDEX_NAME)["count"] if exists else 0
        return {
            "status": "ok" if exists else "missing",
            "index": INDEX_NAME,
            "exists": bool(exists),
            "count": count,
        }
    except Exception:
        return {"status": "error", "message": "index dependency unavailable"}


@app.get("/api/health/dependencies")
def health_dependencies():
    """Read-only dependency status; never returns provider errors or credentials."""
    result = {"status": "ok", "dependencies": {}}
    try:
        from core.config import ES_HOST, ES_USER, ES_PASS
        from core.http_client import elasticsearch_client
        result["dependencies"]["elasticsearch"] = "ok" if elasticsearch_client(ES_HOST, username=ES_USER, password=ES_PASS).ping() else "unavailable"
    except Exception:
        result["dependencies"]["elasticsearch"] = "unavailable"
    result["status"] = "ok" if all(v == "ok" for v in result["dependencies"].values()) else "degraded"
    return result


@app.get("/api/health/metrics")
def health_metrics():
    """Return aggregate process metrics without request or document payloads."""
    from core.metrics import metrics

    return metrics.snapshot()
