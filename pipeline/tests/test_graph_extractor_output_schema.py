"""Tests for graph-extractor output_schema and structured LLM invoke."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPH_SRC = REPO_ROOT / "agents" / "graph-extractor" / "src"


@pytest.fixture
def graph_extractor_modules():
    sys.path.insert(0, str(GRAPH_SRC))
    try:
        import graph_extractor.graph as graph_mod
        import graph_extractor.output_schema as schema_mod

        yield graph_mod, schema_mod
    finally:
        sys.path.remove(str(GRAPH_SRC))


def test_graph_v1_response_format(graph_extractor_modules):
    _, schema_mod = graph_extractor_modules
    fmt = schema_mod.graph_v1_response_format()
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "graph_v1"
    assert "entities" in fmt["json_schema"]["schema"]["properties"]
    edge_type = fmt["json_schema"]["schema"]["properties"]["edges"]["items"]["properties"]["type"]
    assert edge_type["enum"] == ["EXTRACTED", "INFERRED"]


@pytest.mark.asyncio
async def test_extract_graph_binds_json_schema(graph_extractor_modules):
    graph_mod, schema_mod = graph_extractor_modules
    llm = MagicMock()
    bound = AsyncMock()
    llm.bind.return_value = bound
    bound.ainvoke.return_value = MagicMock(
        content=json.dumps(
            {
                "entities": [{"id": "entity:Alpha", "name": "Alpha"}],
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

    out = await graph_mod.extract_graph({"chunks_text": "Alpha relates to Beta."}, llm)
    llm.bind.assert_called_once_with(
        response_format=schema_mod.graph_v1_response_format(),
        max_tokens=graph_mod.DEFAULT_MAX_COMPLETION_TOKENS,
    )
    assert out["entities"][0]["name"] == "Alpha"
