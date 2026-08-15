"""Stable JSON error protocol for every API failure."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def _support_id(request: Request) -> str:
    from api.middleware.logging import request_id_var

    correlation_id = request.headers.get("x-request-id") or request_id_var.get()
    return correlation_id if correlation_id and correlation_id != "-" else str(uuid.uuid4())


def error_payload(code: str, message: str, *, retryable: bool = False, support_id: str | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "retryable": retryable, "support_id": support_id or str(uuid.uuid4())}}


def install_error_handlers(app) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        status = int(exc.status_code)
        code = f"HTTP_{status}"
        return JSONResponse(error_payload(code, str(exc.detail), retryable=status in {408, 429} or status >= 500, support_id=_support_id(request)), status_code=status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(error_payload("VALIDATION_ERROR", "request validation failed", support_id=_support_id(request)), status_code=422)

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        support_id = _support_id(request)
        logger.error("unhandled request error support_id=%s exception_type=%s", support_id, type(exc).__name__)
        return JSONResponse(error_payload("INTERNAL_ERROR", "internal server error", retryable=True, support_id=support_id), status_code=500)


class ErrorProtocolMiddleware:
    def __init__(self, app: Callable):
        self.app = app

    async def __call__(self, scope, receive, send):
        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            if scope["type"] != "http":
                raise
            request = Request(scope, receive=receive)
            support_id = _support_id(request)
            logger.error("unhandled request error support_id=%s exception_type=%s", support_id, type(exc).__name__)
            response = JSONResponse(
                error_payload("INTERNAL_ERROR", "internal server error", retryable=True, support_id=support_id),
                status_code=500,
            )
            await response(scope, receive, send)
