"""Global community wiki search mode."""

from __future__ import annotations

from typing import Any

from path_graph.config import Settings, get_settings
from path_graph.meta.pg import PgMetaStore
from path_graph.rag.embed import EmbeddingClient
from path_graph.rag.rrf import reciprocal_rank_fusion
from path_graph.retrieval.graph_context_loader import load_graph_context_from_s3_uri
from path_graph.retrieval.hits import wiki_row_to_hit


def _as_wiki_ranked(rows: list[dict], *, channel: str) -> list[dict]:
    ranked: list[dict] = []
    for row in rows:
        slug = str(row.get("slug") or "")
        if not slug:
            continue
        ranked.append(
            {
                "id": slug,
                **row,
                f"{channel}_score": float(row.get("score") or 0.0),
            }
        )
    return ranked


def search_global(
    *,
    tenant: str,
    project_id: str,
    query: str,
    top_k: int = 10,
    channel_limit: int = 20,
    rrf_k: int = 60,
    include_graph: bool = False,
    graph_attach_limit: int = 2,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    q = query.strip()
    if not q:
        return []

    s = settings or get_settings()
    if not s.path_graph_dsn:
        raise ValueError("PATH_GRAPH_DSN is required for global search")

    pg = PgMetaStore(s.path_graph_dsn)
    fts_rows = pg.search_wiki_fts(tenant, project_id, q, limit=channel_limit)

    vector_rows: list[dict] = []
    if s.embedding_base_url:
        embedder = EmbeddingClient(s)
        query_vector = embedder.embed([q])[0]
        vector_rows = pg.search_wiki_vector(
            tenant, project_id, query_vector, limit=channel_limit
        )

    merged = reciprocal_rank_fusion(
        [
            _as_wiki_ranked(fts_rows, channel="fts"),
            _as_wiki_ranked(vector_rows, channel="vector"),
        ],
        k=rrf_k,
        top_n=top_k,
    )

    stale_ids = pg.stale_community_ids(tenant, project_id)
    hits: list[dict[str, Any]] = []
    for idx, row in enumerate(merged):
        community_id = str(row.get("community_id") or "")
        graph_context = None
        if include_graph and idx < graph_attach_limit and community_id:
            community = pg.get_community(tenant, project_id, community_id)
            if community and community.get("s3_uri"):
                graph_context = load_graph_context_from_s3_uri(
                    str(community["s3_uri"]),
                    settings=s,
                )
        hits.append(
            wiki_row_to_hit(
                row,
                stale=community_id in stale_ids if community_id else False,
                graph_context=graph_context,
            )
        )
    return hits
