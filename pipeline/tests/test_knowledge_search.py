"""Tests for unified knowledge retrieval."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from path_graph.retrieval.contracts import SearchMode, SearchRequest
from path_graph.retrieval.router import resolve_mode
from path_graph.retrieval.unified import knowledge_search

from constants import PROJECT_ID


def test_resolve_mode_global_hint():
    assert resolve_mode("주요 패턴은?", SearchMode.auto) == SearchMode.global_


def test_resolve_mode_wikilink_local():
    assert resolve_mode("[[인사팀]] 정책", SearchMode.auto) == SearchMode.local


def test_resolve_mode_explicit_basic():
    assert resolve_mode("anything", SearchMode.basic) == SearchMode.basic


@patch("path_graph.retrieval.unified.search_basic")
def test_knowledge_search_basic_mode(mock_basic):
    mock_basic.return_value = [
        {
            "kind": "chunk",
            "id": "c1",
            "text": "hello",
            "score": 0.5,
            "provenance": {"chunk_id": "c1"},
        }
    ]
    from path_graph.config import Settings

    resp = knowledge_search(
        tenant="dev",
        project_id=PROJECT_ID,
        project_slug="demo",
        request=SearchRequest(query="hello", mode=SearchMode.basic),
        settings=Settings(path_graph_dsn="postgresql://localhost/test"),
    )
    assert resp.mode_resolved == "basic"
    assert len(resp.hits) == 1
    assert resp.hits[0].kind == "chunk"


@patch("path_graph.retrieval.unified.search_global")
def test_knowledge_search_global_mode(mock_global):
    mock_global.return_value = [
        {
            "kind": "wiki",
            "id": "comm-1",
            "text": "summary",
            "score": 0.8,
            "provenance": {"community_id": "comm-1"},
        }
    ]
    from path_graph.config import Settings

    resp = knowledge_search(
        tenant="dev",
        project_id=PROJECT_ID,
        project_slug="demo",
        request=SearchRequest(query="overview", mode=SearchMode.global_),
        settings=Settings(path_graph_dsn="postgresql://localhost/test"),
    )
    assert resp.mode_resolved == "global"
    assert resp.hits[0].kind == "wiki"


@patch("path_graph.retrieval.modes.global_.PgMetaStore")
@patch("path_graph.retrieval.modes.global_.EmbeddingClient")
def test_search_global_rrf(mock_embed_cls, mock_pg_cls):
    from path_graph.config import Settings
    from path_graph.retrieval.modes.global_ import search_global

    mock_pg = MagicMock()
    mock_pg_cls.return_value = mock_pg
    mock_pg.search_wiki_fts.return_value = [
        {
            "slug": "L0/report-a",
            "title": "A",
            "community_id": "c1",
            "vfs_path": "/wiki/a.md",
            "body_text": "wiki body",
            "batch_id": "b1",
            "score": 0.4,
        }
    ]
    mock_pg.search_wiki_vector.return_value = [
        {
            "slug": "L0/report-b",
            "title": "B",
            "community_id": "c2",
            "vfs_path": "/wiki/b.md",
            "body_text": "other",
            "batch_id": "b1",
            "score": 0.9,
        }
    ]
    mock_pg.stale_community_ids.return_value = set()
    mock_embed_cls.return_value.embed.return_value = [[0.1] * 1024]

    hits = search_global(
        tenant="dev",
        project_id=PROJECT_ID,
        query="wiki",
        top_k=2,
        settings=Settings(
            path_graph_dsn="postgresql://localhost/test",
            embedding_base_url="http://embed",
        ),
    )
    assert len(hits) == 2
    kinds = {h["kind"] for h in hits}
    assert kinds == {"wiki"}


@patch("path_graph.retrieval.modes.local.make_nebula_store")
@patch("path_graph.retrieval.modes.local.PgMetaStore")
@patch("path_graph.retrieval.modes.local.search_basic")
@patch("path_graph.retrieval.modes.local.EmbeddingClient")
def test_search_local_entity_seed(
    mock_embed_cls, mock_basic, mock_pg_cls, mock_nebula_factory
):
    from path_graph.config import Settings
    from path_graph.retrieval.modes.local import search_local

    mock_pg = MagicMock()
    mock_pg_cls.return_value = mock_pg
    mock_pg.search_entities_fts.return_value = [
        {"entity_id": "e1", "name": "HR", "description": "team", "score": 0.7}
    ]
    mock_pg.search_entities_vector.return_value = []
    mock_pg.get_chunks_by_ids.return_value = [
        {
            "chunk_id": "ch1",
            "document_id": "d1",
            "project_id": PROJECT_ID,
            "text": "chunk text",
        }
    ]
    mock_embed_cls.return_value.embed.return_value = [[0.1] * 1024]
    mock_basic.return_value = []

    nebula = MagicMock()
    mock_nebula_factory.return_value = nebula
    nebula.expand_entity_neighborhood.return_value = {
        "entities": [{"id": "e1", "name": "HR", "description": "team"}],
        "relationships": [
            {"source": "e1", "target": "e2", "type": "EXTRACTED", "description": ""}
        ],
    }
    nebula.get_chunks_for_entities.return_value = ["ch1"]

    hits, ctx = search_local(
        tenant="dev",
        project_id=PROJECT_ID,
        project_slug="demo",
        query="HR",
        top_k=5,
        settings=Settings(
            path_graph_dsn="postgresql://localhost/test",
            embedding_base_url="http://embed",
        ),
    )
    assert ctx is not None
    assert any(h["kind"] == "entity" for h in hits)
    assert any(h["kind"] == "chunk" for h in hits)


def test_nebula_get_chunks_for_entities_memory():
    from path_graph.graph.nebula_store import NebulaGraphStore, _MemorySpace

    memory = {
        "space": _MemorySpace(
            mentions=[("chunk-1", "entity-1"), ("chunk-2", "entity-2")]
        )
    }
    store = NebulaGraphStore("h", 1, "u", "p", memory=memory)
    ids = store.get_chunks_for_entities("space", ["entity-1"])
    assert ids == ["chunk-1"]
