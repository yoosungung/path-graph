"""Hybrid PG FTS + pgvector search with RRF fusion."""

from __future__ import annotations

from path_graph.config import Settings, get_settings
from path_graph.meta.pg import PgMetaStore
from path_graph.rag.embed import EmbeddingClient
from path_graph.rag.rrf import reciprocal_rank_fusion


def _as_ranked_rows(rows: list[dict], *, channel: str) -> list[dict]:
    ranked: list[dict] = []
    for row in rows:
        chunk_id = str(row.get("chunk_id") or row.get("id") or "")
        if not chunk_id:
            continue
        ranked.append(
            {
                "id": chunk_id,
                "chunk_id": chunk_id,
                "document_id": str(row.get("document_id") or ""),
                "project_id": str(row.get("project_id") or ""),
                "text": str(row.get("text") or ""),
                "content": str(row.get("text") or ""),
                f"{channel}_score": float(row.get("score") or 0.0),
            }
        )
    return ranked


def hybrid_search(
    *,
    tenant: str,
    project_id: str,
    project_slug: str,
    query: str,
    top_k: int = 10,
    channel_limit: int = 20,
    rrf_k: int = 60,
    settings: Settings | None = None,
) -> list[dict]:
    """Run PG FTS and pgvector search in parallel channels, merge with RRF."""
    q = query.strip()
    if not q:
        return []
    if not project_slug:
        raise ValueError("project_slug is required")

    s = settings or get_settings()
    if not s.path_graph_dsn:
        raise ValueError("PATH_GRAPH_DSN is required for hybrid search")

    pg = PgMetaStore(s.path_graph_dsn)
    fts_rows = pg.search_fts(tenant, project_id, q, limit=channel_limit)

    embedder = EmbeddingClient(s)
    query_vector = embedder.embed([q])[0]
    vector_rows = pg.search_vector(
        tenant,
        project_id,
        query_vector,
        limit=channel_limit,
    )

    merged = reciprocal_rank_fusion(
        [
            _as_ranked_rows(fts_rows, channel="fts"),
            _as_ranked_rows(vector_rows, channel="vector"),
        ],
        k=rrf_k,
        top_n=top_k,
    )
    return merged
