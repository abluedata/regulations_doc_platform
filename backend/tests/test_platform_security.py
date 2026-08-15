"""Focused contracts for W0 platform security primitives."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from api.middleware.auth import is_loopback, validate_bind_host
from api.middleware.errors import ErrorProtocolMiddleware, error_payload, install_error_handlers
from core.audit import AuditWriter
from core.http_client import tls_verify


class TestAuditWriter(unittest.TestCase):
    def test_append_is_monotonic_and_hash_chained(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = AuditWriter(Path(directory) / "audit.jsonl")
            first = writer.append("document.created", actor="operator", document_id="a")
            second = writer.append("document.deleted", actor="operator", document_id="a")

            exported = writer.export()

        self.assertEqual([event["seq"] for event in exported], [1, 2])
        self.assertEqual(second["previous_hash"], first["hash"])
        self.assertEqual(exported[0]["action"], "document.created")

    def test_export_rejects_tampered_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            writer = AuditWriter(path)
            writer.append("document.created")
            path.write_text(path.read_text(encoding="utf-8").replace("document.created", "document.changed"), encoding="utf-8")
            with self.assertRaises(ValueError):
                writer.export()
            with self.assertRaises(ValueError):
                writer.append("document.deleted")


class TestErrorProtocol(unittest.TestCase):
    def test_payload_has_stable_contract(self):
        payload = error_payload("VALIDATION_ERROR", "request validation failed", retryable=False, support_id="req-1")
        self.assertEqual(payload, {"error": {"code": "VALIDATION_ERROR", "message": "request validation failed", "retryable": False, "support_id": "req-1"}})

    def test_http_exception_uses_protocol_and_request_id(self):
        app = FastAPI()
        install_error_handlers(app)

        @app.get("/denied")
        def denied():
            raise HTTPException(status_code=403, detail="forbidden")

        response = TestClient(app).get("/denied", headers={"x-request-id": "trace-1"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], {"code": "HTTP_403", "message": "forbidden", "retryable": False, "support_id": "trace-1"})

    def test_unhandled_exception_never_exposes_details(self):
        app = FastAPI()
        app.add_middleware(ErrorProtocolMiddleware)

        @app.get("/boom")
        def boom():
            raise RuntimeError("password=do-not-expose")

        response = TestClient(app, raise_server_exceptions=False).get("/boom")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn("do-not-expose", response.text)


class TestDeploymentBoundary(unittest.TestCase):
    def test_only_loopback_is_accepted(self):
        self.assertTrue(is_loopback("127.0.0.1"))
        self.assertTrue(is_loopback("::1"))
        self.assertFalse(is_loopback("0.0.0.0"))
        with self.assertRaises(RuntimeError):
            validate_bind_host("0.0.0.0")

    def test_tls_factory_never_returns_false(self):
        self.assertNotEqual(tls_verify(), False)

    def test_httpx_factory_enables_verification(self):
        with mock.patch("core.http_client.httpx.Client") as client:
            from core.http_client import httpx_client
            httpx_client(timeout=1)
        self.assertIsNot(client.call_args.kwargs["verify"], False)


if __name__ == "__main__":
    unittest.main()
