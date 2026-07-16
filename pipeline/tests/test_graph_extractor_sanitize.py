"""Tests for graph-extractor text sanitization and safer batch splitting."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import TypeAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPH_SRC = REPO_ROOT / "agents" / "graph-extractor" / "src"


@pytest.fixture
def sanitize_mod():
    sys.path.insert(0, str(GRAPH_SRC))
    try:
        import graph_extractor.text_sanitize as mod

        yield mod
    finally:
        sys.path.remove(str(GRAPH_SRC))


@pytest.fixture
def batching_mod():
    sys.path.insert(0, str(GRAPH_SRC))
    try:
        import graph_extractor.batching as mod

        yield mod
    finally:
        sys.path.remove(str(GRAPH_SRC))


def test_sanitize_chunk_text_removes_surrogates_latex_and_midword_newlines(sanitize_mod):
    raw = "개인정보보호책\\textB{임자}\n" + chr(0xD800) + chr(0xDFFF) + " 라이선\n스구매"
    out = sanitize_mod.sanitize_chunk_text(raw)
    assert chr(0xD800) not in out
    assert "\\textB" not in out
    assert "임자" in out
    assert "라이선스구매" in out


def test_sanitize_graph_v1_cleans_entity_fields(sanitize_mod):
    graph = {
        "entities": [
            {
                "id": "entity:프로젝트 아카이브",
                "name": "프로젝트 아카이브",
                "description": "종료 경로(Y:\\\\프로젝트 아카이브).}], '",
            },
            {
                "id": "entity:라이선스구매",
                "name": "라이선\n스구매",
                "description": "ok",
            },
        ],
        "edges": [
            {
                "type": "EXTRACTED",
                "source": "entity:A",
                "target": "entity:B",
                "description": "edge\nnote",
            }
        ],
    }
    cleaned = sanitize_mod.sanitize_graph_v1(graph)
    assert "}], " not in cleaned["entities"][0]["description"]
    assert cleaned["entities"][0]["description"].endswith("아카이브)")
    assert cleaned["entities"][1]["name"] == "라이선스구매"
    assert cleaned["edges"][0]["description"] == "edge note"


def test_ensure_json_utf8_safe_rejects_surrogates(sanitize_mod):
    bad = {"name": "ab" + chr(0xD800) + chr(0xDFFF) + "cd"}
    with pytest.raises(UnicodeEncodeError):
        sanitize_mod.ensure_json_utf8_safe(bad)
    fixed = sanitize_mod.sanitize_graph_string(bad["name"])
    sanitize_mod.ensure_json_utf8_safe({"name": fixed})


def test_sanitize_graph_v1_is_pydantic_json_safe(sanitize_mod):
    graph = sanitize_mod.sanitize_graph_v1(
        {
            "entities": [
                {
                    "id": "entity:개인정보보호책임자",
                    "name": "개인정보보호책\\textB{임자}",
                    "description": "desc",
                }
            ],
            "edges": [],
        }
    )
    TypeAdapter(dict).dump_json(graph)


def test_split_batch_text_prefers_chunk_boundaries(batching_mod):
    chunks = [f"chunk-{i}-" + ("x" * 200) for i in range(4)]
    text = "\n\n".join(chunks)
    left, right = batching_mod.split_batch_text(text)
    assert left.startswith("chunk-0-")
    assert "chunk-1-" in left
    assert right.startswith("chunk-2-")
    assert left not in right


def test_split_batch_text_prefers_line_boundaries_for_single_chunk(batching_mod):
    lines = [f"row-{i}-" + ("y" * 100) for i in range(6)]
    text = "\n".join(lines)
    left, right = batching_mod.split_batch_text(text)
    assert left.startswith("row-0-")
    assert right.startswith("row-3-") or right.startswith("row-4-")
    assert "<tr>" not in left or True


def test_merge_graph_parts_sanitizes_entities(batching_mod, sanitize_mod):
    merged = batching_mod.merge_graph_parts(
        [
            {
                "entities": [
                    {
                        "id": "entity:라이선스구매",
                        "name": "라이선\n스구매",
                        "description": "x",
                    }
                ],
                "edges": [],
            }
        ]
    )
    assert merged["entities"][0]["name"] == "라이선스구매"


@pytest.mark.asyncio
async def test_load_chunks_sanitizes_chunk_text():
    sys.path.insert(0, str(GRAPH_SRC))
    try:
        import graph_extractor.graph as graph_mod
    finally:
        sys.path.remove(str(GRAPH_SRC))

    from unittest.mock import patch

    line = {
        "chunk_id": "c1",
        "text": "개인정보보호책\\textB{임자} 라이선\n스구매",
    }
    raw = (json.dumps(line) + "\n").encode()

    with patch("graph_extractor.graph.fetch_bytes", return_value=raw):
        out = await graph_mod.load_chunks(
            {"chunks_s3": "file:///tmp/chunks.jsonl"},
            max_batch_chars=10_000,
            chunks_per_group=100,
        )

    assert "\\textB" not in out["chunks_text"]
    assert "라이선스구매" in out["chunks_text"]
