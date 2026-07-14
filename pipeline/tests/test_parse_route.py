from __future__ import annotations

import pytest

from path_graph.parsers.route import (
    ParseBackend,
    UnsupportedFormatError,
    allowed_extensions,
    route_parse,
)


@pytest.mark.parametrize(
    ("filename", "backend"),
    [
        ("a.docx", ParseBackend.UNSTRUCTURED),
        ("b.PPTX", ParseBackend.UNSTRUCTURED),
        ("c.xlsx", ParseBackend.UNSTRUCTURED),
        ("d.xls", ParseBackend.UNSTRUCTURED),
        ("e.pdf", ParseBackend.PYMUPDF),
        ("f.hwp", ParseBackend.RHWP_BATCH),
        ("g.hwpx", ParseBackend.RHWP_BATCH),
        ("h.txt", ParseBackend.TEXT),
        ("i.md", ParseBackend.TEXT),
    ],
)
def test_route_parse_by_extension(filename: str, backend: ParseBackend) -> None:
    assert route_parse(filename) == backend


@pytest.mark.parametrize("filename", ["report.doc", "slides.ppt", "x.DOC", "y.PPT"])
def test_route_rejects_legacy_office(filename: str) -> None:
    with pytest.raises(UnsupportedFormatError, match="not supported"):
        route_parse(filename)


def test_route_rejects_unknown_extension() -> None:
    with pytest.raises(UnsupportedFormatError, match="not supported"):
        route_parse("archive.zip")


def test_allowed_extensions_match_parser_policy() -> None:
    allowed = allowed_extensions()
    assert ".docx" in allowed and ".pptx" in allowed
    assert ".xlsx" in allowed and ".xls" in allowed
    assert ".pdf" in allowed
    assert ".hwp" in allowed and ".hwpx" in allowed
    assert ".txt" in allowed and ".md" in allowed
    assert ".doc" not in allowed and ".ppt" not in allowed
