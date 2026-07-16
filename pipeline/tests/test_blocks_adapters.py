"""#293 — Unstructured / PyMuPDF(4LLM) → content.json blocks adapters."""

from __future__ import annotations

from path_graph.chunkers.chunk import chunk_from_blocks
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
