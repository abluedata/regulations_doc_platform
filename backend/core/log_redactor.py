"""Secret redaction for logs and diagnostic payloads."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

_SECRET_KEYS = re.compile(r"(api[_-]?key|token|password|secret|authorization|private[_-]?key)", re.I)
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_ASSIGNMENT = re.compile(
    r"(?i)(api[_-]?key|token|password|secret|authorization)(\s*[=:]\s*)([^\s,;&]+)"
)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _SECRET_KEYS.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(redact(v) for v in value)
    if isinstance(value, str):
        return _ASSIGNMENT.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", _BEARER.sub(r"\1[REDACTED]", value))
    return value


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.msg)
        if record.args:
            record.args = redact(record.args)
        return True


def validate_startup_secrets() -> None:
    """Fail closed in production when configured external providers lack keys."""
    from core import config

    if not config.REQUIRE_SECRETS:
        return
    missing: list[str] = []
    for name, base, key in (
        ("LLM_API_KEY", config.LLM_API_BASE, config.LLM_API_KEY),
        ("EMBED_API_KEY", config.EMBED_API_BASE, config.EMBED_API_KEY),
        ("TAVILY_API_KEY", "https://api.tavily.com", config.TAVILY_API_KEY),
    ):
        if base.startswith(("http://127.0.0.1", "http://localhost", "https://127.0.0.1", "https://localhost")):
            continue
        if not key:
            missing.append(name)
    if missing:
        raise RuntimeError("Missing required secrets: " + ", ".join(missing))


def redact_json(value: Any) -> str:
    return json.dumps(redact(value), ensure_ascii=False, default=str)
