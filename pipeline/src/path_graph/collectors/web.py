from __future__ import annotations

import httpx


def fetch_url(url: str, *, timeout: float = 60.0) -> tuple[bytes, str]:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "application/octet-stream")
        return resp.content, content_type.split(";")[0].strip()


def filename_from_url(url: str) -> str:
    path = url.rstrip("/").split("/")[-1] or "index.html"
    if "?" in path:
        path = path.split("?", 1)[0]
    return path or "download.bin"
