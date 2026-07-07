"""GraphRAG integration: semantic-only graph (no wikilinks) → communities."""

from __future__ import annotations

from unittest.mock import patch

from path_graph.graph.nebula_store import NebulaGraphStore
from path_graph.steps.graphrag_pipeline import run_graphrag_pipeline
from path_graph.storage.blob import LocalBlobStore, write_jsonl

from constants import PROJECT_ID

PLAIN_REGULATION_CHUNK = {
    "chunk_id": "2c74e221-6216-510b-a310-b033f08e687e",
    "document_id": "fb4366a7-d6d8-5804-bdb0-94750acd2213",
    "tenant": "dev",
    "project_id": PROJECT_ID,
    "chunk_index": 0,
    "text": (
        "프로젝트 지원 규정\n\n"
        "제 3조 (집행대상 및 권한)\n\n"
        "프로젝트 지원비의 집행 대상 및 권한은 현장대리인(PM)에 한한다."
    ),
    "text_hash": "abc",
    "heading_path": [],
}

SEMANTIC_GRAPH = {
    "entities": [
        {"id": "entity:프로젝트 지원 규정", "name": "프로젝트 지원 규정"},
        {"id": "entity:현장대리인(PM)", "name": "현장대리인(PM)"},
        {"id": "entity:프로젝트 지원비", "name": "프로젝트 지원비"},
    ],
    "edges": [
        {
            "type": "EXTRACTED",
            "source": "entity:현장대리인(PM)",
            "target": "entity:프로젝트 지원비",
            "confidence": 0.9,
        },
        {
            "type": "EXTRACTED",
            "source": "entity:프로젝트 지원비",
            "target": "entity:프로젝트 지원 규정",
            "confidence": 0.85,
        },
    ],
}


def _mock_invoke_agent(agent, _inp, _session_id, **_kwargs):
    if agent == "graph-extractor":
        return SEMANTIC_GRAPH
    if agent == "wiki-synthesizer":
        return {
            "pages": [
                {
                    "title": "Community Report",
                    "markdown": "# Report\n",
                }
            ]
        }
    raise AssertionError(f"unexpected agent: {agent}")


def test_graphrag_semantic_only_plain_chunk_builds_communities(local_store, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(local_store))
    monkeypatch.setenv("PATH_GRAPH_DSN", "")
    from path_graph.config import get_settings

    get_settings.cache_clear()

    store = LocalBlobStore(local_store)
    chunks_key = "chunks/dev/doc/chunks.jsonl"
    write_jsonl(chunks_key, [PLAIN_REGULATION_CHUNK], store)

    memory: dict = {}
    nebula = NebulaGraphStore("h", 1, "u", "p", memory=memory)

    monkeypatch.setattr(
        "path_graph.steps.graphrag_pipeline.make_nebula_store",
        lambda settings=None: nebula,
    )
    monkeypatch.setattr(
        "path_graph.steps.graph_pipeline.make_nebula_store",
        lambda settings=None: nebula,
    )
    monkeypatch.setattr(
        "path_graph.steps.community_pipeline.make_nebula_store",
        lambda settings=None: nebula,
    )

    with patch(
        "path_graph.steps.agent_cache.invoke_agent",
        side_effect=_mock_invoke_agent,
    ), patch(
        "path_graph.steps.wiki_pipeline.write_wiki_page",
        lambda tenant, project_id, slug, content, **kwargs: f"/{slug}.md",
    ):
        result = run_graphrag_pipeline(
            "dev",
            PROJECT_ID,
            "default",
            "b-semantic",
            chunks_key,
            "sess",
            skip_agent=False,
        )

    assert result["graph"]["batch_entity_ids"][PROJECT_ID]
    assert result["communities"][0]["community_count"] > 0
    assert result["wiki"]["communities"]
