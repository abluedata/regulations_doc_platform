"""Fail-closed HTTP client factories used by all outbound integrations."""
from __future__ import annotations

from typing import Any

import httpx
import requests

from core.config import TLS_CA_BUNDLE


def tls_verify() -> bool | str:
    """Return the configured trust store, never an opt-out value."""
    return TLS_CA_BUNDLE or True


def httpx_client(**kwargs: Any) -> httpx.Client:
    if kwargs.get("verify") is False:
        raise ValueError("TLS verification cannot be disabled")
    options = {"verify": tls_verify(), "trust_env": False}
    options.update(kwargs)
    options.setdefault("verify", tls_verify())
    return httpx.Client(**options)


def httpx_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
    with httpx_client() as client:
        return client.request(method, url, **kwargs)


def requests_session() -> requests.Session:
    session = requests.Session()
    session.verify = tls_verify()
    session.trust_env = False
    return session


def elasticsearch_client(url: str, *, username: str = "", password: str = "", **kwargs: Any):
    from elasticsearch import Elasticsearch

    options: dict[str, Any] = {
        "basic_auth": (username, password),
        "verify_certs": True,
        "ssl_show_warn": True,
    }
    if TLS_CA_BUNDLE:
        options["ca_certs"] = TLS_CA_BUNDLE
    if kwargs.get("verify_certs") is False:
        raise ValueError("TLS verification cannot be disabled")
    options.update(kwargs)
    # Keep the factory incapable of silently disabling certificate validation.
    options["verify_certs"] = True
    return Elasticsearch(url, **options)
