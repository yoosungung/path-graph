"""PDF text_chars / image_ratio router metrics (#280)."""

from __future__ import annotations

import fitz
import pytest

from path_graph.parsers.pdf_metrics import (
    PdfKind,
    classify_pdf,
    measure_pdf,
)


def _text_pdf(*, chars: str = "Hello digital PDF text layer.") -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 40), chars)
    data = doc.tobytes()
    doc.close()
    return data


def _image_heavy_pdf() -> bytes:
    """Near-full-page raster, no extractable text → scan candidate."""
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    # Solid RGB pixmap covering the page (no alpha).
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), 0)
    pix.set_rect(pix.irect, (180, 180, 180))
    page.insert_image(page.rect, pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


def test_measure_pdf_text_document():
    metrics = measure_pdf(_text_pdf())
    assert metrics.page_count == 1
    assert metrics.text_chars >= 20
    assert metrics.image_ratio < 0.5


def test_measure_pdf_scan_like_image_page():
    metrics = measure_pdf(_image_heavy_pdf())
    assert metrics.page_count == 1
    assert metrics.text_chars < 32
    assert metrics.image_ratio >= 0.5


def test_classify_digital_vs_scan():
    assert classify_pdf(_text_pdf()) is PdfKind.DIGITAL
    assert classify_pdf(_image_heavy_pdf()) is PdfKind.SCAN


def test_classify_respects_thresholds():
    # Explicit low-text + high image_ratio → scan even if some chars present.
    assert (
        classify_pdf(
            _text_pdf(chars="x"),
            min_text_chars=32,
            min_image_ratio=0.5,
        )
        is PdfKind.DIGITAL
    )  # image_ratio low → digital despite few chars
    assert classify_pdf(_image_heavy_pdf(), min_text_chars=32, min_image_ratio=0.5) is PdfKind.SCAN
