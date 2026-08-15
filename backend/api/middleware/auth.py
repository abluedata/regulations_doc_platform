"""Local-only deployment boundary and optional local token authentication."""
from __future__ import annotations

import ipaddress
import os
import uuid
from typing import Callable

from starlette.requests import Request
from starlette.responses import JSONResponse


def is_loopback(value: str | None) -> bool:
    try:
        return bool(value and ipaddress.ip_address(value).is_loopback)
    except ValueError:
        return False


def validate_bind_host(host: str | None = None) -> None:
    value = host or os.getenv("API_BIND_HOST", "127.0.0.1")
    if value in ("0.0.0.0", "::", "") or not is_loopback(value):
        raise RuntimeError("API must bind to loopback; public/proxy exposure is disabled")


class LocalOnlyAuthMiddleware:
    def __init__(self, app: Callable, token: str | None = None):
        self.app = app
        self.token = token if token is not None else os.getenv("LOCAL_API_TOKEN", "").strip()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope, receive=receive)
        client_host = request.client.host if request.client else None
        forwarded = request.headers.get("x-forwarded-for") or request.headers.get("forwarded")
        forwarded_hosts = [p.strip().split(",", 1)[0].strip() for p in forwarded.split(",")] if forwarded else []
        if not (is_loopback(client_host) or client_host in {"testclient", "testserver"}):
            return await self._reject(scope, receive, send, "AUTH_LOOPBACK_REQUIRED", "loopback access required")
        if any(not is_loopback(host) for host in forwarded_hosts if host):
            return await self._reject(scope, receive, send, "AUTH_PROXY_REJECTED", "reverse-proxy exposure is not allowed")
        if self.token and request.url.path not in {"/api/health", "/api/health/index", "/api/health/dependencies"}:
            supplied = request.headers.get("authorization", "")
            supplied = supplied[7:] if supplied.lower().startswith("bearer ") else request.headers.get("x-api-token", "")
            if supplied != self.token:
                return await self._reject(scope, receive, send, "AUTH_REQUIRED", "authentication required", 401)
        return await self.app(scope, receive, send)

    @staticmethod
    async def _reject(scope, receive, send, code: str, message: str, status: int = 403):
        from api.middleware.logging import request_id_var

        support_id = request_id_var.get()
        if support_id == "-":
            support_id = str(uuid.uuid4())
        response = JSONResponse(
            {"error": {"code": code, "message": message, "retryable": False, "support_id": support_id}},
            status_code=status,
        )
        await response(scope, receive, send)
