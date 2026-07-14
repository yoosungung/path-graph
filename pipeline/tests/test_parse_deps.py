from __future__ import annotations

from pathlib import Path

import pytest

from path_graph.parsers.parse import parse_document
from path_graph.parsers.route import UnsupportedFormatError, allowed_extensions_csv


def test_markitdown_extras_still_listed_until_native_adapters() -> None:
    """#279 swaps markitdown → unstructured[docx,pptx,xlsx]; keep until then."""
    root = Path(__file__).resolve().parents[1]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "markitdown[pdf,docx,xlsx,xls]" in text
    assert "pymupdf>=" in text


def test_legacy_doc_rejected_via_router() -> None:
    with pytest.raises(UnsupportedFormatError, match="not supported"):
        parse_document(b"data", "report.doc")


def test_legacy_ppt_rejected_via_router() -> None:
    with pytest.raises(UnsupportedFormatError, match="not supported"):
        parse_document(b"data", "slides.ppt")


def test_allowed_extensions_csv_sorted() -> None:
    assert allowed_extensions_csv() == (
        ".docx,.hwp,.hwpx,.md,.pdf,.pptx,.txt,.xls,.xlsx"
    )
