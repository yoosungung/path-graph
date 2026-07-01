"""Admin retrieval API (BFF wraps via agents-runtime)."""

from __future__ import annotations

from typing import Any

from path_graph.admin.projects import ProjectStore
from path_graph.config import Settings, get_settings
from path_graph.rag.hybrid_search import hybrid_search


def api_search_project(
    tenant: str,
    project_id: str,
    query: str,
    *,
    top_k: int = 10,
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
        return {
            "query": "",
            "project_id": project_id,
            "project_slug": profile.slug,
            "results": [],
        }
    results = hybrid_search(
        tenant=tenant,
        project_id=project_id,
        project_slug=profile.slug,
        query=q,
        top_k=top_k,
        settings=s,
    )
    return {
        "query": q,
        "project_id": project_id,
        "project_slug": profile.slug,
        "results": results,
    }
