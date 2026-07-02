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


def test_split_chunk_line_groups_splits_by_chunk_count(batching_mod):
    lines = [{"text": f"c{i}"} for i in range(250)]
    groups = batching_mod.split_chunk_line_groups(lines, max_chunks_per_group=100)
    assert len(groups) == 3
    assert len(groups[0]) == 100
    assert len(groups[1]) == 100
    assert len(groups[2]) == 50


def test_split_chunk_line_groups_skips_empty_text(batching_mod):
    lines = [{"text": ""}, {"text": "a"}, {"text": "  "}, {"text": "b"}]
    groups = batching_mod.split_chunk_line_groups(lines, max_chunks_per_group=100)
    assert len(groups) == 1
    assert len(groups[0]) == 2


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
async def test_extract_graph_splits_batch_on_empty_llm_response():
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
        if calls["n"] <= 2:
            return MagicMock(content="")
        return MagicMock(content=json.dumps({"entities": [], "edges": []}))

    bound.ainvoke.side_effect = _ainvoke

    big = "word " * 800
    out = await graph_mod.extract_graph(
        {"chunk_batches": [big]},
        llm,
        max_completion_tokens=8192,
        min_split_chars=400,
    )
    assert out["entities"] == []
    assert bound.ainvoke.await_count >= 3


@pytest.mark.asyncio
async def test_extract_graph_returns_empty_for_tiny_batch_on_empty_llm():
    sys.path.insert(0, str(GRAPH_SRC))
    try:
        import graph_extractor.graph as graph_mod
    finally:
        sys.path.remove(str(GRAPH_SRC))

    from unittest.mock import AsyncMock, MagicMock

    llm = MagicMock()
    bound = AsyncMock()
    llm.bind.return_value = bound
    bound.ainvoke.return_value = MagicMock(content="")

    out = await graph_mod.extract_graph(
        {"chunk_batches": ["short text"]},
        llm,
        max_completion_tokens=8192,
        min_split_chars=400,
    )
    assert out == {"entities": [], "edges": []}
    assert bound.ainvoke.await_count == 2


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
async def test_load_chunks_builds_chunk_groups():
    sys.path.insert(0, str(GRAPH_SRC))
    try:
        import graph_extractor.graph as graph_mod
    finally:
        sys.path.remove(str(GRAPH_SRC))

    from unittest.mock import patch

    lines = [{"text": f"chunk-{i}"} for i in range(150)]
    raw = "\n".join(json.dumps(line) for line in lines).encode()

    with patch("graph_extractor.graph.fetch_bytes", return_value=raw):
        out = await graph_mod.load_chunks(
            {"chunks_s3": "file:///tmp/chunks.jsonl"},
            max_batch_chars=10_000,
            chunks_per_group=100,
        )

    assert len(out["chunk_groups"]) == 2
    assert len(out["chunk_groups"][0]) >= 1
    assert "chunk-0" in out["chunk_groups"][0][0]
    assert "chunk-149" in out["chunk_groups"][1][-1]


@pytest.mark.asyncio
async def test_extract_graph_limits_concurrent_workers_within_group():
    sys.path.insert(0, str(GRAPH_SRC))
    try:
        import graph_extractor.graph as graph_mod
    finally:
        sys.path.remove(str(GRAPH_SRC))

    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    llm = MagicMock()
    bound = AsyncMock()
    llm.bind.return_value = bound

    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def _ainvoke(_messages):
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        async with lock:
            active -= 1
        return MagicMock(content=json.dumps({"entities": [], "edges": []}))

    bound.ainvoke.side_effect = _ainvoke

    state = {
        "chunk_groups": [
            ["batch-1", "batch-2", "batch-3"],
            ["batch-4"],
        ]
    }
    await graph_mod.extract_graph(
        state,
        llm,
        max_completion_tokens=8192,
        max_concurrent_workers=2,
    )
    assert max_active <= 2
    assert bound.ainvoke.await_count == 4


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
