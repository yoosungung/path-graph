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


def test_md_heuristic_merges_paragraph_on_single_blank_line():
    md = """# Title

First line.

Second line after one blank.


New paragraph after two blanks.
"""
    doc = MdHeuristicBlocksExtractor().extract(md)
    paras = [b for b in doc["blocks"] if b["type"] == "paragraph"]
    assert len(paras) == 2
    assert "First line." in paras[0]["text"]
    assert "Second line" in paras[0]["text"]
    assert paras[0]["heading_path"] == ["Title"]
    assert paras[1]["text"] == "New paragraph after two blanks."


def test_md_heuristic_setext_and_bold_headings():
    md = """Document Title
==============

**Bold Section**

Body text.
"""
    doc = MdHeuristicBlocksExtractor().extract(md)
    headings = [b for b in doc["blocks"] if b["type"] == "heading"]
    assert [h["text"] for h in headings] == ["Document Title", "Bold Section"]
    assert headings[0]["level"] == 1
    assert headings[1]["level"] == 2
    body = [b for b in doc["blocks"] if b["type"] == "paragraph"][0]
    assert body["heading_path"] == ["Document Title", "Bold Section"]


def test_md_heuristic_table_boundary_and_false_positive():
    md = """| only one pipe row |

Real paragraph.

| h1 | h2 |
| --- | --- |
| a | b |

After table.
"""
    doc = MdHeuristicBlocksExtractor().extract(md)
    types = [b["type"] for b in doc["blocks"]]
    assert types.count("table") == 1
    assert types.count("paragraph") >= 2
    table = next(b for b in doc["blocks"] if b["type"] == "table")
    assert "| h1 | h2 |" in table["markdown"]
    assert "| a | b |" in table["markdown"]


def test_md_heuristic_heading_stack_resets_on_sibling():
    md = """# A

## B1
text b1

## B2
text b2
"""
    doc = MdHeuristicBlocksExtractor().extract(md)
    b2_para = [b for b in doc["blocks"] if b["type"] == "paragraph" and "text b2" in b["text"]][0]
    assert b2_para["heading_path"] == ["A", "B2"]
    b1_para = [b for b in doc["blocks"] if b["type"] == "paragraph" and "text b1" in b["text"]][0]
    assert b1_para["heading_path"] == ["A", "B1"]
