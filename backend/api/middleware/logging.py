"""Request correlation and structured access logs."""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar

from core.metrics import metrics

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
logger = logging.getLogger("api.access")


class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("ascii", "ignore").strip()
        request_id = incoming[:128] if incoming else str(uuid.uuid4())
        token = request_id_var.set(request_id)
        status = 500
        started = time.perf_counter()

        async def send_with_id(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message.get("status", 500))
                current = list(message.get("headers") or [])
                current.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": current}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            metrics.record_request(status, duration_ms)
            if scope.get("method") not in {"GET", "HEAD", "OPTIONS"}:
                try:
                    from core.audit import audit
                    audit("api.request", request_id=request_id, method=scope.get("method"), path=scope.get("path"), status=status)
                except Exception:
                    logger.exception("audit write failed request_id=%s", request_id)
            logger.info(json.dumps({"request_id": request_id, "method": scope.get("method"), "path": scope.get("path"), "status": status, "duration_ms": duration_ms}, ensure_ascii=False))
            request_id_var.reset(token)
