"""Tests for graph-extractor chunk batching (SGLang 16K context limit)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPH_SRC = REPO_ROOT / "agents" / "graph-extractor" / "src"


@pytest.fixture
def batching_mod():
    sys.path.insert(0, str(GRAPH_SRC))
    try:
        import graph_extractor.batching as mod

        yield mod
    finally:
        sys.path.remove(str(GRAPH_SRC))


def test_split_chunk_batches_respects_char_budget(batching_mod):
    lines = [{"text": "x" * 3000}, {"text": "y" * 3000}, {"text": "z" * 1000}]
    batches = batching_mod.split_chunk_batches(lines, max_batch_chars=4000)
    assert len(batches) == 2
    assert batches[0] == "x" * 3000
    assert batches[1] == "y" * 3000 + "\n\n" + "z" * 1000


def test_split_chunk_batches_processes_all_lines(batching_mod):
    lines = [{"text": f"chunk-{i}"} for i in range(20)]
    batches = batching_mod.split_chunk_batches(lines, max_batch_chars=50)
    joined = "\n\n".join(batches)
    for i in range(20):
        assert f"chunk-{i}" in joined


def test_compute_graph_extractor_budgets_for_16k(batching_mod):
    batch_chars, completion = batching_mod.compute_graph_extractor_budgets(16384, 8192)
    assert completion == 8192
    assert batch_chars > 4000


def test_resolve_graph_extractor_budgets_uses_preset_env(batching_mod, monkeypatch):
    monkeypatch.setenv("LLM_PRESET_SGLANG_GEMMA4_CONTEXT_WINDOW", "16384")
    monkeypatch.setenv("LLM_PRESET_SGLANG_GEMMA4_MAX_OUTPUT_TOKENS", "8192")
    cfg = {"langgraph": {"model": "preset:SGLANG_GEMMA4"}}
    batch_chars, completion = batching_mod.resolve_graph_extractor_budgets(cfg)
    assert completion == 8192
    assert batch_chars > 4000


def test_resolve_graph_extractor_budgets_fallback_without_preset(batching_mod, monkeypatch):
    monkeypatch.delenv("LLM_PRESET_MISSING_CONTEXT_WINDOW", raising=False)
    cfg = {"langgraph": {"model": "preset:MISSING"}}
    batch_chars, completion = batching_mod.resolve_graph_extractor_budgets(cfg)
    assert batch_chars == batching_mod.DEFAULT_MAX_BATCH_CHARS
    assert completion == batching_mod.DEFAULT_MAX_COMPLETION_TOKENS


def test_merge_graph_parts_dedupes_entities_and_edges(batching_mod):
    merged = batching_mod.merge_graph_parts(
        [
            {
                "entities": [
                    {"id": "entity:A", "name": "A"},
                    {"id": "entity:B", "name": "B"},
                ],
                "edges": [
                    {
                        "type": "EXTRACTED",
                        "source": "entity:A",
                        "target": "entity:B",
                        "confidence": 0.9,
                    }
                ],
            },
            {
                "entities": [
                    {"id": "entity:A", "name": "A-dup"},
                    {"id": "entity:C", "name": "C"},
                ],
                "edges": [
                    {
                        "type": "EXTRACTED",
                        "source": "entity:A",
                        "target": "entity:B",
                        "confidence": 1.0,
                    },
                    {
                        "type": "INFERRED",
                        "source": "entity:B",
                        "target": "entity:C",
                        "confidence": 0.5,
                    },
                ],
            },
        ]
    )
    assert [e["id"] for e in merged["entities"]] == ["entity:A", "entity:B", "entity:C"]
    assert len(merged["edges"]) == 2


def test_split_text_half_prefers_paragraph_boundary(batching_mod):
    text = ("para-a\n\n" + "x" * 2000) + ("\n\npara-b\n\n" + "y" * 2000)
    left, right = batching_mod.split_text_half(text)
    assert left.startswith("para-a")
    assert right.startswith("para-b")
    assert left and right


@pytest.mark.asyncio
async def test_extract_graph_splits_batch_on_length_limit():
    sys.path.insert(0, str(GRAPH_SRC))
    try:
        import graph_extractor.graph as graph_mod
    finally:
        sys.path.remove(str(GRAPH_SRC))

    from unittest.mock import AsyncMock, MagicMock

    llm = MagicMock()
    bound = AsyncMock()
    llm.bind.return_value = bound
    calls = {"n": 0}

    async def _ainvoke(_messages):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError(
                "Could not parse response content as the length limit was reached"
            )
        return MagicMock(content=json.dumps({"entities": [], "edges": []}))

    bound.ainvoke.side_effect = _ainvoke

    big = "word " * 800
    state = {"chunk_batches": [big]}
    await graph_mod.extract_graph(state, llm, max_completion_tokens=8192)
    assert bound.ainvoke.await_count == 3


@pytest.mark.asyncio
async def test_extract_graph_invokes_llm_per_batch():
    sys.path.insert(0, str(GRAPH_SRC))
    try:
        import graph_extractor.graph as graph_mod
    finally:
        sys.path.remove(str(GRAPH_SRC))

    from unittest.mock import AsyncMock, MagicMock

    llm = MagicMock()
    bound = AsyncMock()
    llm.bind.return_value = bound
    bound.ainvoke.return_value = MagicMock(
        content=json.dumps({"entities": [], "edges": []})
    )

    state = {"chunk_batches": ["batch-a", "batch-b", ""]}
    await graph_mod.extract_graph(state, llm, max_completion_tokens=8192)
    assert bound.ainvoke.await_count == 2
    llm.bind.assert_called_with(
        response_format=graph_mod.graph_v1_response_format(),
        max_tokens=8192,
    )
