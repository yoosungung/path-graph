"""PDF image/chart crop → Vision caption (#280)."""

from __future__ import annotations

from unittest.mock import MagicMock

import fitz
import pytest

from path_graph.config import Settings
from path_graph.parsers.image_caption import (
    crop_pdf_region_png,
    enrich_image_block_captions,
)
from path_graph.parsers.ocr_prompt import DEFAULT_CAPTION_PROMPT


def _pdf_with_image_and_text() -> bytes:
    """Page with a solid image rect and separate body text (no adjacent caption)."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 80), 0)
    pix.set_rect(pix.irect, (40, 120, 200))
    page.insert_image(fitz.Rect(50, 50, 170, 130), pixmap=pix)
    page.insert_text((50, 200), "Body paragraph after the figure.")
    data = doc.tobytes()
    doc.close()
    return data


def test_crop_pdf_region_png_returns_png_bytes():
    data = _pdf_with_image_and_text()
    png = crop_pdf_region_png(data, page=1, bbox=[50.0, 50.0, 170.0, 130.0], dpi=72)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_enrich_image_block_captions_fills_empty_via_vlm(monkeypatch):
    data = _pdf_with_image_and_text()
    blocks_doc = {
        "schema_version": "1",
        "extractor": "pymupdf4llm",
        "blocks": [
            {
                "type": "image",
                "caption": "",
                "heading_path": [],
                "metadata": {"page": 1, "bbox": [50.0, 50.0, 170.0, 130.0]},
            },
            {
                "type": "paragraph",
                "text": "Body paragraph after the figure.",
                "heading_path": [],
                "metadata": {"page": 1},
            },
        ],
    }
    client = MagicMock()
    client.ocr_page_png.return_value = "Blue rectangle chart showing values."
    settings = Settings(
        ocr_llm_base_url="http://ocr.test",
        ocr_llm_model="test-model",
    )
    out = enrich_image_block_captions(
        blocks_doc,
        data,
        settings=settings,
        client=client,
    )
    assert out["blocks"][0]["caption"] == "Blue rectangle chart showing values."
    assert out["blocks"][1]["type"] == "paragraph"  # order preserved
    client.ocr_page_png.assert_called_once()
    _, kwargs = client.ocr_page_png.call_args
    assert kwargs["prompt"] == DEFAULT_CAPTION_PROMPT


def test_enrich_skips_when_caption_already_present():
    blocks_doc = {
        "blocks": [
            {
                "type": "image",
                "caption": "Existing caption",
                "heading_path": [],
                "metadata": {"page": 1, "bbox": [0, 0, 10, 10]},
            }
        ]
    }
    client = MagicMock()
    out = enrich_image_block_captions(
        blocks_doc,
        _pdf_with_image_and_text(),
        settings=Settings(ocr_llm_base_url="http://x", ocr_llm_model="m"),
        client=client,
    )
    assert out["blocks"][0]["caption"] == "Existing caption"
    client.ocr_page_png.assert_not_called()
