"""#293 — Unstructured / PyMuPDF(4LLM) → content.json blocks adapters."""

from __future__ import annotations

from path_graph.chunkers.chunk import chunk_from_blocks
from path_graph.parsers.adapters.pymupdf import blocks_from_pymupdf_page_chunks
from path_graph.parsers.adapters.unstructured import blocks_from_unstructured_elements
from path_graph.parsers.blocks_contract import BLOCKS_SCHEMA_VERSION
from constants import PROJECT_ID


def test_unstructured_typed_elements_to_blocks_with_page_bbox():
    elements = [
        {
            "type": "Title",
            "text": "Doc Title",
            "metadata": {"page_number": 1, "coordinates": {"points": [[0, 0], [10, 0], [10, 2], [0, 2]]}},
        },
        {
            "type": "NarrativeText",
            "text": "Intro paragraph.",
            "metadata": {"page_number": 1, "coordinates": {"points": [[0, 3], [20, 3], [20, 5], [0, 5]]}},
        },
        {
            "type": "Table",
            "text": "a b 1 2",
            "metadata": {
                "page_number": 2,
                "text_as_html": "<table><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr></table>",
                "coordinates": {"points": [[1, 1], [9, 1], [9, 4], [1, 4]]},
            },
        },
        {
            "type": "Image",
            "text": "",
            "metadata": {"page_number": 2, "coordinates": {"points": [[0, 10], [5, 10], [5, 15], [0, 15]]}},
        },
        {
            "type": "FigureCaption",
            "text": "Figure 1. Overview",
            "metadata": {"page_number": 2},
        },
    ]

    doc = blocks_from_unstructured_elements(elements)
    assert doc["schema_version"] == BLOCKS_SCHEMA_VERSION
    assert doc["extractor"] == "unstructured"
    types = [b["type"] for b in doc["blocks"]]
    assert types == ["heading", "paragraph", "table", "image"]

    heading, para, table, image = doc["blocks"]
    assert heading["text"] == "Doc Title"
    assert para["heading_path"] == ["Doc Title"]
    assert para["metadata"]["page"] == 1
    assert para["metadata"]["bbox"] == [0.0, 3.0, 20.0, 5.0]

    assert table["markdown"].startswith("<table>")
    assert table["metadata"]["page"] == 2
    assert table["metadata"]["bbox"] == [1.0, 1.0, 9.0, 4.0]

    assert image["caption"] == "Figure 1. Overview"
    assert image["heading_path"] == ["Doc Title"]
    assert image["metadata"]["page"] == 2


def test_pymupdf_page_chunks_to_blocks_preserves_order_and_metadata():
    pages = [
        {
            "metadata": {"page_number": 1, "page_count": 1},
            "text": "## Section\n\nBody text.\n\n| h1 | h2 |\n| --- | --- |\n| a | b |\n\n![img](x.png)\n\nCaption under image.\n",
            "tables": [{"bbox": [10, 40, 90, 70], "row_count": 2, "col_count": 2}],
            "images": [{"bbox": [10, 80, 50, 120], "width": 40, "height": 40}],
            "page_boxes": [
                {"index": 0, "class": "text", "bbox": [10, 10, 90, 20], "pos": [0, 10]},
                {"index": 1, "class": "text", "bbox": [10, 22, 90, 35], "pos": [12, 22]},
                {"index": 2, "class": "table", "bbox": [10, 40, 90, 70], "pos": [24, 58]},
                {"index": 3, "class": "picture", "bbox": [10, 80, 50, 120], "pos": [60, 74]},
                {"index": 4, "class": "text", "bbox": [10, 125, 90, 140], "pos": [76, 96]},
            ],
        }
    ]

    doc = blocks_from_pymupdf_page_chunks(pages)
    assert doc["extractor"] == "pymupdf4llm"
    types = [b["type"] for b in doc["blocks"]]
    assert "heading" in types or "paragraph" in types
    assert "table" in types
    assert "image" in types

    table = next(b for b in doc["blocks"] if b["type"] == "table")
    assert "| h1 | h2 |" in table["markdown"]
    assert table["metadata"]["page"] == 1
    assert table["metadata"]["bbox"] == [10.0, 40.0, 90.0, 70.0]

    image = next(b for b in doc["blocks"] if b["type"] == "image")
    assert image["caption"] == "Caption under image."
    assert image["metadata"]["page"] == 1
    assert image["metadata"]["bbox"] == [10.0, 80.0, 50.0, 120.0]

    # reading order: table before image
    assert types.index("table") < types.index("image")


def test_chunk_type_aware_table_whole_image_caption_no_metadata_on_chunk():
    doc = {
        "schema_version": BLOCKS_SCHEMA_VERSION,
        "extractor": "unstructured",
        "blocks": [
            {"type": "heading", "text": "H1", "heading_path": ["H1"]},
            {
                "type": "paragraph",
                "text": "Body",
                "heading_path": ["H1"],
                "metadata": {"page": 1, "bbox": [0, 0, 1, 1]},
            },
            {
                "type": "table",
                "markdown": "<table><tr><td>long</td></tr></table>",
                "heading_path": ["H1"],
                "metadata": {"page": 2, "bbox": [1, 1, 2, 2]},
            },
            {
                "type": "image",
                "caption": "Fig caption",
                "heading_path": ["H1"],
                "metadata": {"page": 2, "bbox": [3, 3, 4, 4]},
            },
        ],
    }
    chunks = chunk_from_blocks(doc, "t1", "hash", PROJECT_ID, max_chars=1000)
    assert [c.source_block_type for c in chunks] == ["paragraph", "table", "image"]
    assert chunks[0].text == "Body"
    assert chunks[0].heading_path == ["H1"]
    assert chunks[1].text == "<table><tr><td>long</td></tr></table>"
    assert chunks[2].text == "Fig caption"
    dumped = chunks[1].model_dump()
    assert "page" not in dumped
    assert "bbox" not in dumped
    assert "metadata" not in dumped
