"""Local entity-centric graph search mode."""

from __future__ import annotations

from typing import Any

from path_graph.config import Settings, get_settings
from path_graph.graph.chunk_partition import make_nebula_store
from path_graph.ids import nebula_space_name
from path_graph.meta.pg import PgMetaStore
from path_graph.rag.embed import EmbeddingClient
from path_graph.rag.rrf import reciprocal_rank_fusion
from path_graph.retrieval.hits import chunk_row_to_hit, entity_row_to_hit, relationship_row_to_hit
from path_graph.retrieval.modes.basic import search_basic


def _entity_ranked(rows: list[dict], *, channel: str) -> list[dict]:
    ranked: list[dict] = []
    for row in rows:
        eid = str(row.get("entity_id") or "")
        if not eid:
            continue
        ranked.append(
            {
                "id": eid,
                **row,
                f"{channel}_score": float(row.get("score") or 0.0),
            }
        )
    return ranked


def search_local(
    *,
    tenant: str,
    project_id: str,
    project_slug: str,
    query: str,
    top_k: int = 10,
    channel_limit: int = 20,
    rrf_k: int = 60,
    settings: Settings | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]] | None]:
    q = query.strip()
    if not q:
        return [], None

    s = settings or get_settings()
    if not s.path_graph_dsn:
        raise ValueError("PATH_GRAPH_DSN is required for local search")

    pg = PgMetaStore(s.path_graph_dsn)
    fts_entities = pg.search_entities_fts(tenant, project_id, q, limit=channel_limit)

    vector_entities: list[dict] = []
    if s.embedding_base_url:
        embedder = EmbeddingClient(s)
        query_vector = embedder.embed([q])[0]
        vector_entities = pg.search_entities_vector(
            tenant, project_id, query_vector, limit=channel_limit
        )

    entity_merged = reciprocal_rank_fusion(
        [
            _entity_ranked(fts_entities, channel="fts"),
            _entity_ranked(vector_entities, channel="vector"),
        ],
        k=rrf_k,
        top_n=min(channel_limit, top_k),
    )
    seed_ids = [
        str(row.get("entity_id") or row.get("id") or "") for row in entity_merged
    ]
    seed_ids = [sid for sid in seed_ids if sid]

    space = nebula_space_name(tenant, project_slug)
    nebula = make_nebula_store(s)
    graph_context = None
    chunk_hits: list[dict[str, Any]] = []
    rel_hits: list[dict[str, Any]] = []
    if seed_ids:
        graph_context = nebula.expand_entity_neighborhood(
            space,
            seed_ids,
            max_entities=s.graph_context_max_entities,
            max_relationships=s.graph_context_max_relationships,
        )
        rel_hits = [
            relationship_row_to_hit(rel)
            for rel in (graph_context or {}).get("relationships") or []
        ]
        chunk_ids = nebula.get_chunks_for_entities(space, seed_ids)
        if chunk_ids:
            chunks = pg.get_chunks_by_ids(tenant, project_id, chunk_ids)
            for chunk in chunks[:channel_limit]:
                chunk["entity_ids"] = seed_ids
                chunk_hits.append(chunk_row_to_hit(chunk))

    basic_hits = search_basic(
        tenant=tenant,
        project_id=project_id,
        project_slug=project_slug,
        query=q,
        top_k=channel_limit,
        channel_limit=channel_limit,
        rrf_k=rrf_k,
        settings=s,
    )
    entity_hits = [entity_row_to_hit(row) for row in entity_merged]

    merged = reciprocal_rank_fusion(
        [
            [{**h, "id": h["id"]} for h in entity_hits],
            [{**h, "id": h["id"]} for h in chunk_hits],
            [{**h, "id": h["id"]} for h in basic_hits],
        ],
        k=rrf_k,
        top_n=top_k,
    )

    final = list(merged)
    seen = {h["id"] for h in final}
    for rel in rel_hits[:3]:
        if rel["id"] not in seen and len(final) < top_k:
            final.append(rel)
            seen.add(rel["id"])
    return final, graph_context
