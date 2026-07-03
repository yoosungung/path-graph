"""export_project_graph batch_entity_ids scoping (GraphRAG semantic path)."""

from __future__ import annotations

from path_graph.graph.entity_vid import entity_vid
from path_graph.graph.nebula_store import NebulaGraphStore


def test_export_semantic_only_with_batch_entity_ids() -> None:
    """PDF/HWP: semantic edges without MENTIONS — batch_entity_ids must export edges."""
    memory: dict = {}
    nebula = NebulaGraphStore("h", 1, "u", "p", memory=memory)
    space = "path_graph_dev_default"
    pm_vid = entity_vid("PM")
    project_vid = entity_vid("프로젝트")
    nebula.ensure_space(space)
    nebula.upsert_entities(
        space,
        [
            {"id": "entity:PM", "name": "PM"},
            {"id": "entity:프로젝트", "name": "프로젝트"},
        ],
    )
    nebula.upsert_edges(
        space,
        [
            {
                "type": "EXTRACTED",
                "source": "entity:PM",
                "target": "entity:프로젝트",
                "confidence": 0.9,
            }
        ],
    )

    scoped = nebula.export_project_graph(
        space,
        batch_chunk_ids={"chunk-no-wikilink"},
        batch_entity_ids={pm_vid, project_vid},
    )
    assert len(scoped) == 1
    assert scoped[0][:2] == (pm_vid, project_vid)


def test_export_mentions_only_without_batch_entity_ids() -> None:
    """Wikilink 보조 경로: MENTIONS 스코프 + co-mention fallback."""
    memory: dict = {}
    nebula = NebulaGraphStore("h", 1, "u", "p", memory=memory)
    space = "path_graph_dev_default"
    nebula.ensure_space(space)
    nebula.upsert_mentions(space, "chunk-1", ["Alpha", "Beta"])

    scoped = nebula.export_project_graph(
        space,
        batch_chunk_ids={"chunk-1"},
    )
    assert len(scoped) >= 1
    endpoints = {scoped[0][0], scoped[0][1]}
    assert endpoints <= {entity_vid("Alpha"), entity_vid("Beta")}


def test_export_semantic_batch_entity_ids_ignores_empty_mentions_scope() -> None:
    """batch_entity_ids가 있으면 빈 MENTIONS 스코프로 semantic edge가 걸러지지 않는다."""
    memory: dict = {}
    nebula = NebulaGraphStore("h", 1, "u", "p", memory=memory)
    space = "path_graph_dev_default"
    a_vid = entity_vid("A")
    b_vid = entity_vid("B")
    nebula.ensure_space(space)
    nebula.upsert_edges(
        space,
        [
            {
                "type": "EXTRACTED",
                "source": "entity:A",
                "target": "entity:B",
                "confidence": 1.0,
            }
        ],
    )

    without_semantic_scope = nebula.export_project_graph(
        space,
        batch_chunk_ids={"plain-chunk"},
    )
    assert without_semantic_scope == []

    with_semantic_scope = nebula.export_project_graph(
        space,
        batch_chunk_ids={"plain-chunk"},
        batch_entity_ids={a_vid, b_vid},
    )
    assert len(with_semantic_scope) == 1
