"""Regression: Opik graph-extractor output → Nebula semantic upsert."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from path_graph.config import Settings
from path_graph.contracts.schemas import unwrap_agent_graph_output
from path_graph.graph.entity_vid import entity_vid
from path_graph.graph.nebula_store import NebulaGraphStore, _ngql_string
from path_graph.steps.graph_pipeline import run_graph_pipeline
from constants import PROJECT_ID

_FIXTURE = Path(__file__).parent / "fixtures" / "graph_extractor" / "opik_span_019f2579-93b7.json"


def _load_opik_graph_v1() -> dict:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return payload["agent_job_output"]


def _langgraph_job_output(graph_v1: dict) -> dict:
    return {
        "tenant": "didim",
        "project_id": "7ba730bd-4a8a-40a2-8779-7c1f83069dd8",
        "batch_id": "batch-opik",
        "chunks_s3": "https://garage.example/presigned/chunks.jsonl",
        "chunk_batches": ["프로젝트 지원 규정"],
        **graph_v1,
    }


def test_unwrap_agent_graph_output_peels_runtime_envelope() -> None:
    graph_v1 = _load_opik_graph_v1()
    wrapped = {"output": _langgraph_job_output(graph_v1)}

    unwrapped = unwrap_agent_graph_output(wrapped)

    assert len(unwrapped["entities"]) == 7
    assert len(unwrapped["edges"]) == 5
    assert unwrapped["entities"][0]["id"] == "entity:프로젝트 지원 규정"


@patch("path_graph.steps.agent_cache.invoke_agent")
@patch("path_graph.steps.graph_pipeline.make_nebula_store")
@patch("path_graph.graph.chunk_partition.copy_chunks_to_project_batch")
@patch("path_graph.steps.graph_pipeline.read_jsonl")
@patch("path_graph.steps.graph_pipeline.make_blob_store")
@patch("path_graph.steps.graph_pipeline.get_settings")
def test_graph_pipeline_upserts_opik_fixture_to_nebula(
    mock_settings,
    mock_blob,
    mock_read_jsonl,
    mock_copy,
    mock_nebula_factory,
    mock_invoke_agent,
) -> None:
    graph_v1 = _load_opik_graph_v1()
    mock_settings.return_value = Settings()
    mock_copy.return_value = "chunks/didim/project/batch-opik/chunks.jsonl"
    mock_read_jsonl.return_value = [
        {
            "chunk_id": "2c74e221-6216-510b-a310-b033f08e687e",
            "text": "제 3조 프로젝트 지원비의 집행 권한은 현장대리인(PM)에 한한다.",
        },
    ]
    mock_invoke_agent.return_value = {"output": _langgraph_job_output(graph_v1)}

    memory: dict = {}
    nebula = NebulaGraphStore("h", 9669, "root", "pw", memory=memory)
    mock_nebula_factory.return_value = nebula
    store = MagicMock()
    store.agent_artifact_uri.return_value = "https://garage.example/presigned/chunks.jsonl"
    store.exists.return_value = False
    store.get_bytes.return_value = (
        b'{"chunk_id": "2c74e221-6216-510b-a310-b033f08e687e", "text": "x"}\n'
    )
    mock_blob.return_value = store

    run_graph_pipeline(
        "didim",
        PROJECT_ID,
        "default",
        "batch-opik",
        "chunks/didim/doc/chunks.jsonl",
        "graphrag-session",
        skip_agent=False,
    )

    space = memory["path_graph_didim_default"]
    assert len(space.entities) == 7
    assert len(space.edges) == 5
    assert entity_vid("현장대리인(PM)") in space.entities
    assert any(
        edge["source"] == entity_vid("프로젝트")
        and edge["target"] == entity_vid("프로젝트 지원비")
        for edge in space.edges
    )


def test_upsert_opik_fixture_entities_generates_korean_ngql() -> None:
    graph_v1 = _load_opik_graph_v1()
    store = NebulaGraphStore("h", 9669, "root", "pw")
    session = MagicMock()
    session.execute.return_value = MagicMock(is_succeeded=lambda: True, error_msg=lambda: "")

    with (
        patch.object(store, "_ensure_live_schema"),
        patch.object(store, "_session", return_value=session),
    ):
        store.upsert_entities("space", graph_v1["entities"])

    joined = "\n".join(call.args[0] for call in session.execute.call_args_list)
    ent = graph_v1["entities"][2]
    eid = _ngql_string(entity_vid(ent["name"]))
    assert f'VALUES {eid}:(' in joined
    assert "현장대리인(PM)" in joined
