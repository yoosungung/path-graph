"""Tests for wiki-synthesizer output_schema and structured LLM invoke."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WIKI_SRC = REPO_ROOT / "agents" / "wiki-synthesizer" / "src"


@pytest.fixture
def wiki_modules():
    sys.path.insert(0, str(WIKI_SRC))
    try:
        import wiki_synthesizer.graph as graph_mod
        import wiki_synthesizer.output_schema as schema_mod

        yield graph_mod, schema_mod
    finally:
        sys.path.remove(str(WIKI_SRC))


def test_wiki_v1_response_format(wiki_modules):
    _, schema_mod = wiki_modules
    fmt = schema_mod.wiki_v1_response_format()
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "wiki_v1"
    assert set(fmt["json_schema"]["schema"]["required"]) == {
        "slug",
        "title",
        "executive_summary",
        "key_entities",
    }


@pytest.mark.asyncio
async def test_synthesize_page_binds_json_schema(wiki_modules):
    graph_mod, schema_mod = wiki_modules
    llm = MagicMock()
    bound = AsyncMock()
    llm.bind.return_value = bound
    bound.ainvoke.return_value = MagicMock(
        content=json.dumps(
            {
                "slug": "p6907e343-community-L0-abc12345",
                "title": "Community",
                "executive_summary": "Summary.",
                "key_entities": ["Alpha"],
            }
        )
    )

    out = await graph_mod.synthesize_page(
        {
            "graph_context_text": '{"entities":[]}',
            "project_slug": "p_6907e343",
            "community_level": 0,
            "community_id": "abc12345",
        },
        llm,
    )
    llm.bind.assert_called_once_with(response_format=schema_mod.wiki_v1_response_format())
    assert out["pages"][0]["title"] == "Community"
