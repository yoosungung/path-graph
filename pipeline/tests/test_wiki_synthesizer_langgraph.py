"""Unit tests for wiki-synthesizer LangGraph (no live LLM)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WIKI_SRC = REPO_ROOT / "agents" / "wiki-synthesizer" / "src"


@pytest.fixture
def wiki_modules():
    sys.path.insert(0, str(WIKI_SRC))
    try:
        import wiki_synthesizer.agent as agent_mod
        import wiki_synthesizer.graph as graph_mod

        yield agent_mod, graph_mod
    finally:
        sys.path.remove(str(WIKI_SRC))


@pytest.mark.asyncio
async def test_synthesize_node_builds_page(wiki_modules, tmp_path):
    _, graph_mod = wiki_modules
    ctx_path = tmp_path / "ctx.json"
    ctx_path.write_text(
        json.dumps(
            {
                "entities": [{"name": "Alpha"}, {"name": "Beta"}],
                "edges": [{"source": "entity:Alpha", "target": "entity:Beta"}],
            }
        ),
        encoding="utf-8",
    )

    llm = MagicMock()
    bound = AsyncMock()
    llm.bind.return_value = bound
    bound.ainvoke.return_value = MagicMock(
        content=json.dumps(
            {
                "slug": "p6907e343-community-L0-abc12345",
                "title": "Community Alpha-Beta",
                "executive_summary": "Summary here.",
                "key_entities": ["Alpha", "Beta"],
            }
        )
    )

    state = {
        "tenant": "didim",
        "project_id": "7ba730bd-4a8a-40a2-8779-7c1f83069dd8",
        "project_slug": "p_6907e343",
        "community_id": "abc12345-0000-0000-0000-000000000099",
        "community_level": 0,
        "graph_context_s3": ctx_path.as_uri(),
    }
    loaded = await graph_mod.load_context(state)
    assert "Alpha" in loaded["graph_context_text"]

    out = await graph_mod.synthesize_page({**state, **loaded}, llm)
    assert out["pages"][0]["title"] == "Community Alpha-Beta"
    assert out["pages"][0]["slug"] == "p6907e343-community-L0-abc12345"


def test_factory_returns_compiled_graph(wiki_modules):
    agent_mod, _ = wiki_modules
    pytest.importorskip("langgraph")

    mock_llm = MagicMock()
    with patch("wiki_synthesizer.graph.prepare_langgraph_llm", return_value=mock_llm):
        graph = agent_mod.factory({"langgraph": {"model": "openai:gpt-4o-mini"}}, MagicMock())

    assert hasattr(graph, "ainvoke")


@pytest.mark.asyncio
async def test_compiled_graph_ainvoke_end_to_end(wiki_modules, tmp_path):
    agent_mod, _ = wiki_modules
    pytest.importorskip("langgraph")

    ctx_path = tmp_path / "ctx.json"
    ctx_path.write_text(
        json.dumps(
            {
                "entities": [{"name": "Alpha"}, {"name": "Beta"}],
                "edges": [{"source": "entity:Alpha", "target": "entity:Beta"}],
            }
        ),
        encoding="utf-8",
    )

    llm = MagicMock()
    bound = AsyncMock()
    llm.bind.return_value = bound
    bound.ainvoke.return_value = MagicMock(
        content=json.dumps(
            {
                "slug": "p6907e343-community-L0-abc12345",
                "title": "Community Alpha-Beta",
                "executive_summary": "Summary here.",
                "key_entities": ["Alpha", "Beta"],
            }
        )
    )

    with patch("wiki_synthesizer.graph.prepare_langgraph_llm", return_value=llm):
        graph = agent_mod.factory({"langgraph": {"model": "openai:gpt-4o-mini"}}, MagicMock())

    result = await graph.ainvoke(
        {
            "tenant": "didim",
            "project_id": "7ba730bd-4a8a-40a2-8779-7c1f83069dd8",
            "project_slug": "p_6907e343",
            "community_id": "abc12345-0000-0000-0000-000000000099",
            "community_level": 0,
            "graph_context_s3": ctx_path.as_uri(),
        }
    )

    assert "Alpha" in result["graph_context_text"]
    assert result["pages"][0]["title"] == "Community Alpha-Beta"
    assert result["pages"][0]["markdown"].startswith("# Community Alpha-Beta")
