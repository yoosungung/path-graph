"""Load pre-indexed community graph_context from S3."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from path_graph.config import Settings, get_settings
from path_graph.storage.blob import make_blob_store


def _s3_key_from_uri(s3_uri: str) -> str:
    parsed = urlparse(s3_uri)
    if parsed.scheme in ("s3", "garage"):
        return parsed.path.lstrip("/")
    if parsed.scheme == "file":
        return parsed.path.lstrip("/")
    return s3_uri.lstrip("/")


def load_graph_context_from_s3_uri(
    s3_uri: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    if not s3_uri:
        return None
    store = make_blob_store(settings or get_settings())
    key = _s3_key_from_uri(s3_uri)
    try:
        raw = store.get_bytes(key)
    except Exception:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return {
        "community_id": payload.get("community_id"),
        "level": payload.get("level"),
        "entities": payload.get("entities") or [],
        "relationships": payload.get("relationships") or [],
    }
