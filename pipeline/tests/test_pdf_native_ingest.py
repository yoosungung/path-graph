"""Native PDF ingest: pymupdf4llm blocks + scan OCR/dead_letter (#280)."""

from __future__ import annotations

import json

import fitz
import pytest

from path_graph.parsers.parse import parse_pdf_to_json
from path_graph.steps.ingest import ParseError, ingest_raw_bytes
from path_graph.storage.blob import LocalBlobStore

from constants import PROJECT_ID


def _digital_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Digital PDF body text for native pymupdf4llm blocks.")
    data = doc.tobytes()
    doc.close()
    return data


def _scan_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), 0)
    pix.set_rect(pix.irect, (180, 180, 180))
    page.insert_image(page.rect, pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(tmp_path))
    return tmp_path


def _meta(doc_id: str, content_hash: str) -> dict:
    return {
        "tenant": "dev",
        "document_id": doc_id,
        "content_hash": content_hash,
        "source_id": "manual",
        "project_id": PROJECT_ID,
        "s3_raw_uri": "file://x",
        "filename": "doc.pdf",
    }


def test_parse_pdf_to_json_digital():
    doc = parse_pdf_to_json(_digital_pdf())
    assert "pages" in doc
    assert doc["page_count"] >= 1
    assert "blocks" not in doc


def test_ingest_digital_pdf_uses_pymupdf4llm_backend(local_store):
    meta = _meta("00000000-0000-0000-0000-000000000011", "digitalhash")
    result = ingest_raw_bytes(_digital_pdf(), "doc.pdf", "dev", "manual", meta)
    assert result["chunks"]
    assert result["parse_backend"] == "pymupdf4llm"
    store = LocalBlobStore(local_store)
    blocks = json.loads(store.get_bytes(f"parsed/dev/{meta['document_id']}/content.json"))
    assert "pages" in blocks
    assert blocks["page_count"] >= 1
    saved = json.loads(store.get_bytes(f"parsed/dev/{meta['document_id']}/meta.json"))
    assert saved["pdf_kind"] == "digital"
    assert saved["parse_backend"] == "pymupdf4llm"


def test_ingest_scan_pdf_without_ocr_dead_letters(local_store):
    meta = _meta("00000000-0000-0000-0000-000000000012", "scannoocr")
    with pytest.raises(ParseError, match="scan PDF requires OCR"):
        ingest_raw_bytes(_scan_pdf(), "scan.pdf", "dev", "manual", meta)
    store = LocalBlobStore(local_store)
    err = json.loads(store.get_bytes("dead_letter/dev/scannoocr/error.json"))
    assert err["stage"] == "parse_empty"
    assert err["pdf_kind"] == "scan"


def test_ingest_scan_pdf_with_ocr_uses_vl_ocr(local_store, monkeypatch):
    monkeypatch.setenv("OCR_LLM_BASE_URL", "http://ocr.test")
    monkeypatch.setenv("OCR_LLM_MODEL", "test-model")
    monkeypatch.setattr(
        "path_graph.steps.ingest.vl_ocr_pdf_to_markdown",
        lambda data, **kwargs: (
            "# Scanned title\n\nRecovered body text for chunking.",
            {"page_count": 1, "parse_backend": "vl_ocr"},
        ),
    )
    meta = _meta("00000000-0000-0000-0000-000000000013", "scanocr")
    result = ingest_raw_bytes(_scan_pdf(), "scan.pdf", "dev", "manual", meta)
    assert result["chunks"]
    assert result["parse_backend"] == "vl_ocr"
    store = LocalBlobStore(local_store)
    saved = json.loads(store.get_bytes(f"parsed/dev/{meta['document_id']}/meta.json"))
    assert saved["fallback_reason"] == "scan"
    assert saved["pdf_kind"] == "scan"


def test_ingest_digital_empty_triggers_pymupdf_ocr_fallback(local_store, monkeypatch):
    monkeypatch.setenv("OCR_LLM_BASE_URL", "http://ocr.test")
    monkeypatch.setenv("OCR_LLM_MODEL", "test-model")
    monkeypatch.setattr(
        "path_graph.steps.ingest.parse_pdf_to_json",
        lambda data: {"pages": [], "page_count": 0},
    )
    monkeypatch.setattr(
        "path_graph.steps.ingest.vl_ocr_pdf_to_markdown",
        lambda data, **kwargs: (
            "# Recovered\n\nFallback body after empty digital parse.",
            {"page_count": 1, "parse_backend": "pymupdf4llm+vl_ocr_fallback"},
        ),
    )
    meta = _meta("00000000-0000-0000-0000-000000000014", "fallbackhash")
    # Use digital-looking bytes so classify stays digital.
    result = ingest_raw_bytes(_digital_pdf(), "doc.pdf", "dev", "manual", meta)
    assert result["chunks"]
    assert result["parse_backend"] == "pymupdf4llm+vl_ocr_fallback"
