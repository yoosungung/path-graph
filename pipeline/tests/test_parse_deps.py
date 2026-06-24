from __future__ import annotations

from pathlib import Path

import pytest

from path_graph.parsers.parse import parse_document


def test_markitdown_extras_cover_manual_spreadsheet_formats():
  root = Path(__file__).resolve().parents[1]
  text = (root / "pyproject.toml").read_text(encoding="utf-8")
  assert 'markitdown[pdf,docx,xlsx,xls]' in text


def test_legacy_doc_rejected_before_markitdown():
    with pytest.raises(ValueError, match="legacy .doc"):
        parse_document(b"data", "report.doc")
