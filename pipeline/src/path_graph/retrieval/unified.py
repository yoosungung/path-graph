"""Unified knowledge search entry point."""

from __future__ import annotations

from path_graph.config import Settings, get_settings
from path_graph.retrieval.contracts import (
    GraphContextBundle,
    SearchHit,
    SearchMode,
    SearchRequest,
    SearchResponse,
)
from path_graph.retrieval.modes.basic import search_basic
from path_graph.retrieval.modes.drift import search_drift
from path_graph.retrieval.modes.global_ import search_global
from path_graph.retrieval.modes.local import search_local
from path_graph.retrieval.router import resolve_mode


def knowledge_search(
    *,
    tenant: str,
    project_id: str,
    project_slug: str,
    request: SearchRequest | None = None,
    query: str | None = None,
    mode: SearchMode | str = SearchMode.auto,
    top_k: int = 10,
    include_graph: bool = False,
    sub_queries: list[str] | None = None,
    settings: Settings | None = None,
) -> SearchResponse:
    s = settings or get_settings()
    if request is None:
        mode_val = SearchMode(mode) if isinstance(mode, str) else mode
        request = SearchRequest(
            query=query or "",
            mode=mode_val,
            top_k=top_k,
            include_graph=include_graph,
            sub_queries=sub_queries or [],
        )

    q = request.query.strip()
    resolved = resolve_mode(q, request.mode)
    graph_context = None
    drift_sub_queries: list[str] = []
    hits_raw: list[dict] = []

    if not q:
        return SearchResponse(
            query="",
            mode_resolved=resolved.value,
            project_id=project_id,
            project_slug=project_slug,
            hits=[],
        )

    if resolved == SearchMode.basic:
        hits_raw = search_basic(
            tenant=tenant,
            project_id=project_id,
            project_slug=project_slug,
            query=q,
            top_k=request.top_k,
            channel_limit=request.channel_limit,
            rrf_k=request.rrf_k,
            settings=s,
        )
    elif resolved == SearchMode.global_:
        hits_raw = search_global(
            tenant=tenant,
            project_id=project_id,
            query=q,
            top_k=request.top_k,
            channel_limit=request.channel_limit,
            rrf_k=request.rrf_k,
            include_graph=request.include_graph,
            graph_attach_limit=s.search_graph_context_attach_limit,
            settings=s,
        )
    elif resolved == SearchMode.local:
        hits_raw, graph_context = search_local(
            tenant=tenant,
            project_id=project_id,
            project_slug=project_slug,
            query=q,
            top_k=request.top_k,
            channel_limit=request.channel_limit,
            rrf_k=request.rrf_k,
            settings=s,
        )
    elif resolved == SearchMode.drift:
        hits_raw, graph_context, drift_sub_queries = search_drift(
            tenant=tenant,
            project_id=project_id,
            project_slug=project_slug,
            query=q,
            top_k=request.top_k,
            channel_limit=request.channel_limit,
            rrf_k=request.rrf_k,
            include_graph=request.include_graph,
            sub_queries=request.sub_queries or sub_queries,
            settings=s,
        )

    hits = [SearchHit.model_validate(h) for h in hits_raw]
    ctx_bundle = None
    if graph_context:
        ctx_bundle = GraphContextBundle(
            entities=graph_context.get("entities") or [],
            relationships=graph_context.get("relationships") or [],
        )

    return SearchResponse(
        query=q,
        mode_resolved=resolved.value,
        project_id=project_id,
        project_slug=project_slug,
        hits=hits,
        graph_context=ctx_bundle,
        sub_queries=drift_sub_queries,
    )
