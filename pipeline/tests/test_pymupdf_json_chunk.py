"""PyMuPDF4LLM to_json() — store as-is, chunk without blocks conversion."""

from __future__ import annotations

import fitz

from path_graph.chunkers.pymupdf_json import chunk_from_pymupdf_json
from path_graph.parsers.parse import parse_pdf_to_json
from path_graph.parsers.pymupdf_json import is_pymupdf_json_document

from constants import PROJECT_ID


def _text_box(
    *,
    boxclass: str,
    text: str,
    bbox: list[float],
    caption: str = "",
) -> dict:
    box: dict = {
        "x0": bbox[0],
        "y0": bbox[1],
        "x1": bbox[2],
        "y1": bbox[3],
        "boxclass": boxclass,
        "image": None,
        "table": None,
        "textlines": [
            {
                "bbox": bbox,
                "spans": [{"text": text}],
            }
        ],
    }
    if caption:
        box["caption"] = caption
    return box


def _page(page: int, boxes: list[dict]) -> dict:
    return {"page_number": page, "boxes": boxes}


def test_parse_pdf_to_json_returns_pymupdf_document_shape():
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Digital PDF body text.")
    data = doc.tobytes()
    doc.close()

    parsed = parse_pdf_to_json(data)
    assert is_pymupdf_json_document(parsed)
    assert parsed["page_count"] >= 1
    assert isinstance(parsed["pages"], list)
    assert "blocks" not in parsed


def test_chunk_from_pymupdf_json_uses_boxclass_and_numbered_headings():
    doc = {
        "page_count": 2,
        "pages": [
            _page(
                1,
                [
                    _text_box(
                        boxclass="section-header",
                        text="15. First question?",
                        bbox=[68, 402, 427, 415],
                    ),
                    _text_box(
                        boxclass="text",
                        text="Answer under 15.",
                        bbox=[54, 469, 544, 560],
                    ),
                ],
            ),
            _page(
                2,
                [
                    _text_box(
                        boxclass="text",
                        text="16. Second question on new page?",
                        bbox=[68, 67, 534, 99],
                    ),
                ],
            ),
        ],
    }
    chunks = chunk_from_pymupdf_json(doc, "dev", "hash", PROJECT_ID)
    assert [c.text for c in chunks] == ["Answer under 15."]
    assert chunks[0].heading_path == ["15. First question?"]


def test_chunk_from_pymupdf_json_numbered_heading_updates_path_for_following_body():
    doc = {
        "page_count": 1,
        "pages": [
            _page(
                1,
                [
                    _text_box(
                        boxclass="text",
                        text="16. Second question on new page?",
                        bbox=[68, 67, 534, 99],
                    ),
                    _text_box(
                        boxclass="text",
                        text="Answer under 16.",
                        bbox=[54, 110, 544, 140],
                    ),
                ],
            )
        ],
    }
    chunks = chunk_from_pymupdf_json(doc, "dev", "hash", PROJECT_ID)
    assert [c.text for c in chunks] == ["Answer under 16."]
    assert chunks[0].heading_path == ["16. Second question on new page?"]


def test_chunk_from_pymupdf_json_table_and_caption():
    doc = {
        "page_count": 1,
        "pages": [
            {
                "page_number": 1,
                "boxes": [
                    {
                        "x0": 10,
                        "y0": 40,
                        "x1": 90,
                        "y1": 70,
                        "boxclass": "table",
                        "table": {
                            "markdown": "| h1 | h2 |\n| --- | --- |\n| a | b |",
                        },
                    },
                    {
                        "x0": 10,
                        "y0": 80,
                        "x1": 50,
                        "y1": 120,
                        "boxclass": "picture",
                        "textlines": [],
                        "caption": "Caption under image.",
                    },
                ],
            }
        ],
    }
    chunks = chunk_from_pymupdf_json(doc, "dev", "hash", PROJECT_ID)
    assert [c.source_block_type for c in chunks] == ["table", "image"]
    assert "| h1 | h2 |" in chunks[0].text
    assert chunks[1].text == "Caption under image."


def test_parse_pdf_to_json_integration_numbered_headings():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((68, 402), "15. DB 접속기록을 주기적으로 모니터링하여 통제하고 있습니까?", fontsize=11)
    page.insert_text((68, 430), "Body under 15.")
    page2 = doc.new_page()
    page2.insert_text(
        (68, 67),
        "16. DB서버에 접속하는 관리자 PC가 인터넷 접속되는 내부망의 네트워크와 분리되어 있습니까?",
        fontsize=11,
    )
    page2.insert_text((68, 100), "Body under 16.")
    data = doc.tobytes()
    doc.close()

    parsed = parse_pdf_to_json(data)
    chunks = chunk_from_pymupdf_json(parsed, "dev", "hash", PROJECT_ID)
    assert any(c.text == "Body under 16." for c in chunks)
    body16 = next(c for c in chunks if c.text == "Body under 16.")
    assert body16.heading_path[0].startswith("16.")
