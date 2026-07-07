"""Tests for wiki-synthesizer bounded output schema and markdown assembly."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WIKI_SRC = REPO_ROOT / "agents" / "wiki-synthesizer" / "src"


@pytest.fixture
def schema_mod():
    sys.path.insert(0, str(WIKI_SRC))
    try:
        import wiki_synthesizer.output_schema as mod

        yield mod
    finally:
        sys.path.remove(str(WIKI_SRC))


def test_wiki_v1_schema_uses_bounded_sections(schema_mod):
    schema = schema_mod.WIKI_V1_SCHEMA
    required = set(schema["required"])
    assert required == {"title", "executive_summary", "key_entities"}
    assert "markdown" not in schema["properties"]
    assert schema["properties"]["key_entities"]["maxItems"] == schema_mod.WIKI_MAX_ENTITY_BULLETS


def test_assemble_wiki_markdown_renders_sections(schema_mod):
    md = schema_mod.assemble_wiki_markdown(
        {
            "title": "Cluster A",
            "executive_summary": "Short summary.",
            "key_entities": ["Alpha — lead"],
            "notable_relationships": ["Alpha employs Beta"],
            "open_questions": ["Missing vendor data"],
        }
    )
    assert "# Cluster A" in md
    assert "## Executive Summary" in md
    assert "## Key Entities" in md
    assert "- Alpha — lead" in md
    assert "## Notable Relationships" in md
    assert "## Open Questions" in md
