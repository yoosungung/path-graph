from __future__ import annotations

from pathlib import Path

import pytest

from path_graph.parsers.parse import parse_document, parse_non_pdf_to_blocks
from path_graph.parsers.route import UnsupportedFormatError, allowed_extensions_csv


def test_native_parse_deps_listed_without_markitdown() -> None:
    """PDF=pymupdf4llm, Office=unstructured; markitdown removed (#280)."""
    root = Path(__file__).resolve().parents[1]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "markitdown" not in text
    assert "pymupdf>=" in text
    assert "pymupdf4llm>=" in text
    assert "unstructured[docx,pptx,xlsx]" in text


def test_legacy_doc_rejected_via_router() -> None:
    with pytest.raises(UnsupportedFormatError, match="not supported"):
        parse_document(b"data", "report.doc")


def test_legacy_ppt_rejected_via_router() -> None:
    with pytest.raises(UnsupportedFormatError, match="not supported"):
        parse_non_pdf_to_blocks(b"data", "slides.ppt")


def test_allowed_extensions_csv_sorted() -> None:
    assert allowed_extensions_csv() == (
        ".docx,.hwp,.hwpx,.md,.pdf,.pptx,.txt,.xls,.xlsx"
    )
