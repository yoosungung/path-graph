"""#293 — type-aware chunk_from_blocks rules."""

from __future__ import annotations

from path_graph.chunkers.chunk import chunk_from_blocks
from path_graph.parsers.blocks_contract import BLOCKS_SCHEMA_VERSION
from constants import PROJECT_ID


def test_heading_blocks_are_not_emitted_as_chunks():
    doc = {
        "schema_version": BLOCKS_SCHEMA_VERSION,
        "extractor": "test",
        "blocks": [
            {"type": "heading", "text": "Only Heading", "heading_path": ["Only Heading"]},
            {"type": "paragraph", "text": "Under", "heading_path": ["Only Heading"]},
        ],
    }
    chunks = chunk_from_blocks(doc, "t1", "h", PROJECT_ID)
    assert len(chunks) == 1
    assert chunks[0].text == "Under"
    assert chunks[0].source_block_type == "paragraph"


def test_oversized_table_still_hard_splits_when_unavoidable():
    huge = "<table>" + ("x" * 50) + "</table>"
    doc = {
        "schema_version": BLOCKS_SCHEMA_VERSION,
        "extractor": "test",
        "blocks": [{"type": "table", "markdown": huge, "heading_path": []}],
    }
    chunks = chunk_from_blocks(doc, "t1", "h", PROJECT_ID, max_chars=20)
    assert len(chunks) >= 2
    assert all(c.source_block_type == "table" for c in chunks)
    assert "".join(c.text for c in chunks).replace(" ", "") == huge.replace(" ", "")
