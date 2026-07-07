"""Admin retrieval API (BFF wraps via agents-runtime)."""

from __future__ import annotations

from typing import Any

from path_graph.admin.projects import ProjectStore
from path_graph.config import Settings, get_settings
from path_graph.retrieval.contracts import SearchMode, SearchRequest
from path_graph.retrieval.unified import knowledge_search


def api_search_project(
    tenant: str,
    project_id: str,
    query: str,
    *,
    top_k: int = 10,
    mode: str = "auto",
    include_graph: bool = False,
    sub_queries: list[str] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    s = settings or get_settings()
    if not s.path_graph_dsn:
        raise ValueError("PATH_GRAPH_DSN required")
    store = ProjectStore(s.path_graph_dsn)
    profile = store.get_project(tenant, project_id)
    if profile is None:
        raise ValueError(f"project not found: {project_id}")
    q = query.strip()
    if not q:
        empty = knowledge_search(
            tenant=tenant,
            project_id=project_id,
            project_slug=profile.slug,
            request=SearchRequest(query=""),
            settings=s,
        )
        return empty.to_api_dict()

    mode_enum = SearchMode(mode)
    response = knowledge_search(
        tenant=tenant,
        project_id=project_id,
        project_slug=profile.slug,
        request=SearchRequest(
            query=q,
            mode=mode_enum,
            top_k=top_k,
            include_graph=include_graph,
            sub_queries=sub_queries or [],
        ),
        settings=s,
    )
    return response.to_api_dict()
