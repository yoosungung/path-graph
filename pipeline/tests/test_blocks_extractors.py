from __future__ import annotations

import pytest

from path_graph.chunkers.chunk import chunk_from_blocks
from path_graph.parsers.blocks_contract import BLOCKS_SCHEMA_VERSION
from path_graph.parsers.blocks_extractors import get_blocks_extractor, register_blocks_extractor
from path_graph.parsers.blocks_extractors.md_heuristic import MdHeuristicBlocksExtractor
from constants import PROJECT_ID


def test_md_heuristic_extracts_heading_table_paragraph():
    md = """# Title

Intro paragraph.

## Section

| a | b |
| --- | --- |
| 1 | 2 |

Closing.
"""
    doc = MdHeuristicBlocksExtractor().extract(md)
    assert doc["schema_version"] == BLOCKS_SCHEMA_VERSION
    assert doc["extractor"] == "md_heuristic"
    types = [b["type"] for b in doc["blocks"]]
    assert "heading" in types
    assert "table" in types
    assert "paragraph" in types
    section_blocks = [b for b in doc["blocks"] if b.get("heading_path") == ["Title", "Section"]]
    assert any(b["type"] == "table" for b in section_blocks)


def test_chunk_from_blocks_uses_heading_path():
    doc = MdHeuristicBlocksExtractor().extract("# H1\n\nBody under heading.")
    chunks = chunk_from_blocks(doc, "t1", "abc", PROJECT_ID, max_chars=1000)
    assert len(chunks) >= 1
    assert chunks[-1].heading_path == ["H1"]
    assert chunks[-1].source_block_type == "paragraph"


def test_get_blocks_extractor_unknown_raises():
    with pytest.raises(ValueError, match="unknown blocks extractor"):
        get_blocks_extractor("not_registered")


def test_register_custom_extractor():
    class EchoExtractor:
        name = "echo_test"

        def extract(self, markdown: str) -> dict:
            return {
                "schema_version": BLOCKS_SCHEMA_VERSION,
                "extractor": self.name,
                "blocks": [{"type": "paragraph", "text": markdown, "heading_path": []}],
            }

    register_blocks_extractor(EchoExtractor())
    doc = get_blocks_extractor("echo_test").extract("hi")
    assert doc["extractor"] == "echo_test"
    assert doc["blocks"][0]["text"] == "hi"
