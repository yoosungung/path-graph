"""DRIFT-lite iterative search mode."""

from __future__ import annotations

from typing import Any

from path_graph.config import Settings, get_settings
from path_graph.rag.rrf import reciprocal_rank_fusion
from path_graph.retrieval.modes.basic import search_basic
from path_graph.retrieval.modes.global_ import search_global
from path_graph.retrieval.modes.local import search_local


def search_drift(
    *,
    tenant: str,
    project_id: str,
    project_slug: str,
    query: str,
    top_k: int = 10,
    channel_limit: int = 20,
    rrf_k: int = 60,
    include_graph: bool = True,
    sub_queries: list[str] | None = None,
    settings: Settings | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]] | None, list[str]]:
    s = settings or get_settings()
    primer_hits = search_global(
        tenant=tenant,
        project_id=project_id,
        query=query,
        top_k=min(3, top_k),
        channel_limit=channel_limit,
        rrf_k=rrf_k,
        include_graph=include_graph,
        graph_attach_limit=s.search_graph_context_attach_limit,
        settings=s,
    )

    followups = [q.strip() for q in (sub_queries or []) if q and q.strip()]
    if not followups:
        followups = [query]

    depth = max(1, min(s.drift_max_depth, 2))
    lists: list[list[dict[str, Any]]] = [primer_hits]
    graph_context = None

    for sub_q in followups[: s.drift_k_followups]:
        local_hits, ctx = search_local(
            tenant=tenant,
            project_id=project_id,
            project_slug=project_slug,
            query=sub_q,
            top_k=channel_limit,
            channel_limit=channel_limit,
            rrf_k=rrf_k,
            settings=s,
        )
        if ctx and graph_context is None:
            graph_context = ctx
        lists.append(local_hits)
        if depth > 1:
            basic_hits = search_basic(
                tenant=tenant,
                project_id=project_id,
                project_slug=project_slug,
                query=sub_q,
                top_k=channel_limit,
                channel_limit=channel_limit,
                rrf_k=rrf_k,
                settings=s,
            )
            lists.append(basic_hits)

    flat_lists: list[list[dict]] = []
    for group in lists:
        flat_lists.append([{**h, "id": h["id"]} for h in group])

    merged = reciprocal_rank_fusion(flat_lists, k=rrf_k, top_n=top_k)
    return merged, graph_context, followups
