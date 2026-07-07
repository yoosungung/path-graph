"""Basic chunk hybrid search mode."""

from __future__ import annotations

from typing import Any

from path_graph.config import Settings
from path_graph.rag.hybrid_search import hybrid_search
from path_graph.retrieval.hits import chunk_row_to_hit


def search_basic(
    *,
    tenant: str,
    project_id: str,
    project_slug: str,
    query: str,
    top_k: int = 10,
    channel_limit: int = 20,
    rrf_k: int = 60,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    rows = hybrid_search(
        tenant=tenant,
        project_id=project_id,
        project_slug=project_slug,
        query=query,
        top_k=top_k,
        channel_limit=channel_limit,
        rrf_k=rrf_k,
        settings=settings,
    )
    return [chunk_row_to_hit(row) for row in rows]
