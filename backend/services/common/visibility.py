"""Elasticsearch visibility-field setup shared by indexing and search."""

from __future__ import annotations

from typing import Any


VISIBILITY_FIELD = "visibility_key_v2"


def response_body(response: Any, *, operation: str) -> dict:
    """Normalize Elasticsearch 8 response objects and validate their body."""
    body = getattr(response, "body", response)
    if not isinstance(body, dict):
        raise RuntimeError(f"{operation} returned an invalid response")
    return body


def ensure_visibility_mapping(es: Any, index_name: str) -> None:
    """Install the v2 keyword mapping or reject an incompatible field."""
    mapping = response_body(
        es.indices.get_mapping(index=index_name),
        operation="visibility mapping lookup",
    )
    index_mapping = mapping.get(index_name)
    if not isinstance(index_mapping, dict):
        raise RuntimeError(
            f"visibility mapping lookup did not return index {index_name!r}"
        )
    mappings = index_mapping.get("mappings", {})
    if not isinstance(mappings, dict):
        raise RuntimeError("visibility mapping lookup returned invalid mappings")
    properties = mappings.get("properties", {})
    if not isinstance(properties, dict):
        raise RuntimeError("visibility mapping lookup returned invalid properties")

    field_mapping = properties.get(VISIBILITY_FIELD)
    if field_mapping is None:
        update = response_body(
            es.indices.put_mapping(
                index=index_name,
                properties={VISIBILITY_FIELD: {"type": "keyword"}},
            ),
            operation="visibility mapping update",
        )
        if update.get("acknowledged") is not True:
            raise RuntimeError("visibility mapping update was not acknowledged")
        return
    if not isinstance(field_mapping, dict) or field_mapping.get("type") != "keyword":
        actual_type = (
            field_mapping.get("type", "unknown")
            if isinstance(field_mapping, dict)
            else "invalid"
        )
        raise RuntimeError(
            f"{VISIBILITY_FIELD} must be mapped as keyword, found {actual_type}; "
            "create a compatible index and reindex documents before retrying"
        )
