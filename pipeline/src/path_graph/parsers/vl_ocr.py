from __future__ import annotations

import time
from enum import Enum
from typing import Any

import httpx

from path_graph.config import Settings, get_settings
from path_graph.parsers.ocr_prompt import DEFAULT_OCR_PROMPT
from path_graph.parsers.pdf_render import render_pdf_pages


class ParseBackend(str, Enum):
    PYMUPDF4LLM = "pymupdf4llm"
    PYMUPDF4LLM_VL_OCR_FALLBACK = "pymupdf4llm+vl_ocr_fallback"
    VL_OCR = "vl_ocr"


_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class VlOcrClient:
    """OpenAI-compatible vision chat client for page OCR."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport

    def ocr_page_png(self, png_bytes: bytes, *, prompt: str) -> str:
        settings = self._settings
        if not settings.ocr_llm_base_url or not settings.ocr_llm_model:
            raise ValueError("OCR_LLM_BASE_URL and OCR_LLM_MODEL are required")

        base = settings.ocr_llm_base_url.rstrip("/")
        url = f"{base}/v1/chat/completions"
        headers: dict[str, str] = {}
        if settings.ocr_llm_api_key:
            headers["Authorization"] = f"Bearer {settings.ocr_llm_api_key}"

        import base64

        encoded = base64.standard_b64encode(png_bytes).decode("ascii")
        payload = {
            "model": settings.ocr_llm_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{encoded}"},
                        },
                    ],
                }
            ],
            "max_tokens": settings.ocr_max_tokens,
            "temperature": 0,
        }

        last_error: Exception | None = None
        with httpx.Client(
            timeout=settings.ocr_llm_timeout_s,
            transport=self._transport,
        ) as client:
            for attempt in range(settings.ocr_max_retries + 1):
                try:
                    resp = client.post(url, json=payload, headers=headers)
                    if resp.status_code in _RETRYABLE_STATUS:
                        raise httpx.HTTPStatusError(
                            "retryable OCR status",
                            request=resp.request,
                            response=resp,
                        )
                    resp.raise_for_status()
                    body = resp.json()
                    content = (body["choices"][0]["message"].get("content") or "").strip()
                    if not content:
                        raise ValueError("empty OCR response content")
                    return content
                except (httpx.HTTPError, ValueError) as exc:
                    last_error = exc
                    if attempt >= settings.ocr_max_retries:
                        break
                    time.sleep(2**attempt)

        assert last_error is not None
        raise last_error


def _ocr_prompt(settings: Settings) -> str:
    custom = (settings.ocr_prompt or "").strip()
    return custom or DEFAULT_OCR_PROMPT


def vl_ocr_pdf_to_markdown(
    data: bytes,
    *,
    settings: Settings | None = None,
    client: VlOcrClient | None = None,
    parse_backend: ParseBackend = ParseBackend.VL_OCR,
) -> tuple[str, dict[str, Any]]:
    settings = settings or get_settings()
    ocr = client or VlOcrClient(settings)
    prompt = _ocr_prompt(settings)
    page_pngs = render_pdf_pages(data, dpi=settings.ocr_render_dpi)
    if not page_pngs:
        raise ValueError("PDF has no renderable pages")
    if settings.ocr_max_pages > 0 and len(page_pngs) > settings.ocr_max_pages:
        raise ValueError(
            f"PDF has {len(page_pngs)} pages, exceeds OCR_MAX_PAGES ({settings.ocr_max_pages})"
        )

    page_mds: list[str] = []
    for png in page_pngs:
        page_mds.append(ocr.ocr_page_png(png, prompt=prompt))

    combined = "\n\n---\n\n".join(page_mds)
    return combined, {
        "page_count": len(page_pngs),
        "page_pngs": page_pngs,
        "page_mds": page_mds,
        "parse_backend": parse_backend.value,
    }
