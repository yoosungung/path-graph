"""Unit tests for graph-extractor LangGraph (no live LLM)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPH_SRC = REPO_ROOT / "agents" / "graph-extractor" / "src"


@pytest.fixture
def graph_extractor_modules():
    sys.path.insert(0, str(GRAPH_SRC))
    try:
        import graph_extractor.agent as agent_mod
        import graph_extractor.graph as graph_mod

        yield agent_mod, graph_mod
    finally:
        sys.path.remove(str(GRAPH_SRC))


@pytest.mark.asyncio
async def test_extract_node_parses_llm_json(graph_extractor_modules, tmp_path):
    _, graph_mod = graph_extractor_modules
    chunks_uri = tmp_path / "chunks.jsonl"
    chunks_uri.write_text(
        json.dumps({"chunk_id": "c1", "text": "Alpha relates to Beta."}) + "\n",
        encoding="utf-8",
    )

    llm = MagicMock()
    bound = AsyncMock()
    llm.bind.return_value = bound
    bound.ainvoke.return_value = MagicMock(
        content=json.dumps(
            {
                "entities": [
                    {"id": "entity:Alpha", "name": "Alpha"},
                    {"id": "entity:Beta", "name": "Beta"},
                ],
                "edges": [
                    {
                        "type": "EXTRACTED",
                        "source": "entity:Alpha",
                        "target": "entity:Beta",
                        "confidence": 0.9,
                    }
                ],
            }
        )
    )

    state = {
        "tenant": "dev",
        "project_id": "00000000-0000-0000-0000-000000000001",
        "chunks_s3": chunks_uri.as_uri(),
    }
    loaded = await graph_mod.load_chunks(state)
    assert "Alpha" in loaded["chunks_text"]

    extracted = await graph_mod.extract_graph({**state, **loaded}, llm)
    assert len(extracted["entities"]) == 2
    assert extracted["edges"][0]["target"] == "entity:Beta"


def test_factory_returns_compiled_graph(graph_extractor_modules):
    agent_mod, _ = graph_extractor_modules
    pytest.importorskip("langgraph")

    mock_llm = MagicMock()
    with patch("graph_extractor.graph.prepare_langgraph_llm", return_value=mock_llm):
        graph = agent_mod.factory({"langgraph": {"model": "openai:gpt-4o-mini"}}, MagicMock())

    assert hasattr(graph, "ainvoke")


@pytest.mark.asyncio
async def test_compiled_graph_ainvoke_end_to_end(graph_extractor_modules, tmp_path):
    agent_mod, _ = graph_extractor_modules
    pytest.importorskip("langgraph")

    chunks_uri = tmp_path / "chunks.jsonl"
    chunks_uri.write_text(
        json.dumps({"chunk_id": "c1", "text": "Alpha relates to Beta."}) + "\n",
        encoding="utf-8",
    )

    llm = MagicMock()
    bound = AsyncMock()
    llm.bind.return_value = bound
    bound.ainvoke.return_value = MagicMock(
        content=json.dumps(
            {
                "entities": [
                    {"id": "entity:Alpha", "name": "Alpha"},
                    {"id": "entity:Beta", "name": "Beta"},
                ],
                "edges": [
                    {
                        "type": "EXTRACTED",
                        "source": "entity:Alpha",
                        "target": "entity:Beta",
                        "confidence": 0.9,
                    }
                ],
            }
        )
    )

    with patch("graph_extractor.graph.prepare_langgraph_llm", return_value=llm):
        graph = agent_mod.factory({"langgraph": {"model": "openai:gpt-4o-mini"}}, MagicMock())

    result = await graph.ainvoke(
        {
            "tenant": "dev",
            "project_id": "00000000-0000-0000-0000-000000000001",
            "batch_id": "b1",
            "chunks_s3": chunks_uri.as_uri(),
        }
    )

    assert "Alpha" in result["chunks_text"]
    assert len(result["entities"]) == 2
    assert result["edges"][0]["target"] == "entity:Beta"
