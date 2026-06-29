"""Fetch pipeline artifacts (presigned HTTP / file URI)."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse


def fetch_bytes(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return Path(parsed.path).read_bytes()
    if parsed.scheme in ("http", "https"):
        import httpx

        resp = httpx.get(uri, timeout=120.0, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    raise ValueError(f"unsupported artifact uri scheme: {parsed.scheme}")


def read_jsonl_bytes(data: bytes) -> list[dict]:
    lines: list[dict] = []
    for line in data.decode("utf-8").splitlines():
        line = line.strip()
        if line:
            lines.append(json.loads(line))
    return lines
