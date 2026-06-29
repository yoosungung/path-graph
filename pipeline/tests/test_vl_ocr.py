from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock

import httpx
import pytest

from path_graph.config import Settings
from path_graph.parsers.ocr_prompt import DEFAULT_OCR_PROMPT
from path_graph.parsers.pdf_render import render_pdf_pages
from path_graph.parsers.vl_ocr import VlOcrClient, vl_ocr_pdf_to_markdown
from path_graph.steps.ingest import ParseError, ingest_raw_bytes
from path_graph.steps.ingest_helpers import ingest_item
from path_graph.storage.blob import LocalBlobStore

from constants import PROJECT_ID


def _minimal_pdf_bytes(*, pages: int = 1) -> bytes:
    import fitz

    doc = fitz.open()
    for idx in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"scan fixture page {idx + 1}")
    return doc.tobytes()


def _ocr_response(text: str) -> dict:
    return {
        "choices": [{"message": {"content": text, "reasoning_content": "ignored"}}],
    }


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(tmp_path))
    return tmp_path


def test_render_pdf_pages_produces_one_png_per_page():
    pages = render_pdf_pages(_minimal_pdf_bytes(), dpi=72)
    assert len(pages) == 1
    assert pages[0][:8] == b"\x89PNG\r\n\x1a\n"


def test_vl_ocr_client_sends_base64_image(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json=_ocr_response("# Page OCR\n\nBody"))

    transport = httpx.MockTransport(handler)
    settings = Settings(
        ocr_llm_base_url="http://ocr.test",
        ocr_llm_model="test-model",
        ocr_llm_api_key="EMPTY",
        ocr_max_retries=0,
    )
    client = VlOcrClient(settings, transport=transport)
    out = client.ocr_page_png(b"\x89PNG\r\n\x1a\n\x00", prompt="read this")

    assert out == "# Page OCR\n\nBody"
    content = captured["json"]["messages"][0]["content"]
    image_part = next(part for part in content if part["type"] == "image_url")
    url = image_part["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.standard_b64decode(url.split(",", 1)[1]) == b"\x89PNG\r\n\x1a\n\x00"
    assert captured["json"]["temperature"] == 0
    assert captured["json"]["max_tokens"] == 2048


def test_vl_ocr_pdf_rejects_when_page_count_exceeds_max():
    settings = Settings(
        ocr_llm_base_url="http://ocr.test",
        ocr_llm_model="test-model",
        ocr_max_pages=1,
    )
    with pytest.raises(ValueError, match="exceeds OCR_MAX_PAGES"):
        vl_ocr_pdf_to_markdown(_minimal_pdf_bytes(pages=2), settings=settings)


def test_vl_ocr_pdf_allows_unlimited_pages_when_max_pages_zero():
    settings = Settings(
        ocr_llm_base_url="http://ocr.test",
        ocr_llm_model="test-model",
        ocr_max_pages=0,
    )
    client = MagicMock()
    client.ocr_page_png.side_effect = ["# One", "# Two"]
    md, meta = vl_ocr_pdf_to_markdown(
        _minimal_pdf_bytes(pages=2),
        settings=settings,
        client=client,
    )
    assert meta["page_count"] == 2
    assert "# One" in md
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json=_ocr_response("ok"))

    transport = httpx.MockTransport(handler)
    settings = Settings(
        ocr_llm_base_url="http://ocr.test",
        ocr_llm_model="test-model",
        ocr_max_retries=1,
    )
    client = VlOcrClient(settings, transport=transport)
    assert client.ocr_page_png(b"png", prompt=DEFAULT_OCR_PROMPT) == "ok"
    assert calls["n"] == 2


def test_vl_ocr_pdf_to_markdown_joins_pages():
    settings = Settings(
        ocr_llm_base_url="http://ocr.test",
        ocr_llm_model="test-model",
    )
    client = MagicMock()
    client.ocr_page_png.side_effect = ["# One", "# Two"]
    md, meta = vl_ocr_pdf_to_markdown(
        _minimal_pdf_bytes(pages=2),
        settings=settings,
        client=client,
    )
    assert "# One" in md and "# Two" in md
    assert meta["page_count"] == 2
    assert client.ocr_page_png.call_count == 2


def test_ingest_empty_markitdown_triggers_ocr_fallback(local_store, monkeypatch):
    monkeypatch.setenv("OCR_LLM_BASE_URL", "http://ocr.test")
    monkeypatch.setenv("OCR_LLM_MODEL", "test-model")

    monkeypatch.setattr(
        "path_graph.steps.ingest.parse_document",
        lambda data, filename, rhwp_bin="rhwp-batch": ("", None),
    )
    monkeypatch.setattr(
        "path_graph.steps.ingest.vl_ocr_pdf_to_markdown",
        lambda data, **kwargs: (
            "# Scanned title\n\nRecovered body text for chunking.",
            {"page_count": 1, "parse_backend": "markitdown+vl_ocr_fallback"},
        ),
    )

    meta = {
        "tenant": "dev",
        "document_id": "00000000-0000-0000-0000-000000000001",
        "content_hash": "scanhash",
        "source_id": "manual",
        "project_id": PROJECT_ID,
        "s3_raw_uri": "file://x",
        "filename": "scan.pdf",
    }
    result = ingest_raw_bytes(b"%PDF", "scan.pdf", "dev", "manual", meta)
    assert result["chunks"]
    store = LocalBlobStore(local_store)
    saved_meta = json.loads(store.get_bytes("parsed/dev/00000000-0000-0000-0000-000000000001/meta.json"))
    assert saved_meta["parse_backend"] == "markitdown+vl_ocr_fallback"


def test_ingest_ocr_fallback_still_empty_records_dead_letter(local_store, monkeypatch):
    monkeypatch.setenv("OCR_LLM_BASE_URL", "http://ocr.test")
    monkeypatch.setenv("OCR_LLM_MODEL", "test-model")

    monkeypatch.setattr(
        "path_graph.steps.ingest.parse_document",
        lambda data, filename, rhwp_bin="rhwp-batch": ("", None),
    )
    monkeypatch.setattr(
        "path_graph.steps.ingest.vl_ocr_pdf_to_markdown",
        lambda data, **kwargs: ("", {"page_count": 1}),
    )

    meta = {
        "tenant": "dev",
        "document_id": "00000000-0000-0000-0000-000000000002",
        "content_hash": "emptyocr",
        "source_id": "manual",
        "project_id": PROJECT_ID,
        "s3_raw_uri": "file://x",
        "filename": "scan.pdf",
    }
    with pytest.raises(ParseError, match="no chunks"):
        ingest_raw_bytes(b"%PDF", "scan.pdf", "dev", "manual", meta)

    store = LocalBlobStore(local_store)
    err = json.loads(store.get_bytes("dead_letter/dev/emptyocr/error.json"))
    assert err["stage"] == "ocr_empty"


def test_ingest_item_returns_false_when_chunks_empty_after_fallback(local_store, monkeypatch):
    monkeypatch.setenv("OCR_LLM_BASE_URL", "http://ocr.test")
    monkeypatch.setenv("OCR_LLM_MODEL", "test-model")
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(local_store))

    raw_key = f"raw/dev/{PROJECT_ID}/manual/ocrfail/scan.pdf"
    store = LocalBlobStore(local_store)
    store.put_bytes(raw_key, b"%PDF")

    monkeypatch.setattr(
        "path_graph.steps.ingest.parse_document",
        lambda data, filename, rhwp_bin="rhwp-batch": ("", None),
    )
    monkeypatch.setattr(
        "path_graph.steps.ingest.vl_ocr_pdf_to_markdown",
        lambda data, **kwargs: ("", {"page_count": 1}),
    )

    settings = Settings(
        pipeline_storage_backend="local",
        pipeline_storage_dir=str(local_store),
        ocr_llm_base_url="http://ocr.test",
        ocr_llm_model="test-model",
    )
    meta = {
        "tenant": "dev",
        "document_id": "00000000-0000-0000-0000-000000000003",
        "content_hash": "ocrfail",
        "source_id": "manual",
        "project_id": PROJECT_ID,
        "s3_raw_uri": f"file://{raw_key}",
        "filename": "scan.pdf",
    }
    ok, detail = ingest_item(
        meta,
        "dev",
        "manual",
        PROJECT_ID,
        "proj",
        rag=False,
        settings=settings,
    )
    assert ok is False
    assert "no chunks" in detail
