"""Mark stale communities and optionally trigger wiki/graph refresh (Phase 2 hook)."""

from __future__ import annotations

from typing import Any

from path_graph.config import Settings, get_settings
from path_graph.meta.pg import PgMetaStore


def list_stale_for_project(
    tenant: str, project_id: str, *, settings: Settings | None = None
) -> list[dict[str, Any]]:
    s = settings or get_settings()
    if not s.path_graph_dsn:
        return []
    return PgMetaStore(s.path_graph_dsn).list_stale_communities(tenant, project_id)


def mark_project_wiki_stale(
    tenant: str,
    project_id: str,
    *,
    trigger_document_id: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Record project-level stale flag for downstream graphrag/wiki WF."""
    s = settings or get_settings()
    if not s.path_graph_dsn:
        return {"marked": 0}
    pg = PgMetaStore(s.path_graph_dsn)
    rows = pg.list_stale_communities(tenant, project_id)
    if not rows and trigger_document_id:
        # Placeholder community id for document-triggered stale (wiki regen picks up)
        pg.mark_stale_community(
            tenant,
            project_id,
            trigger_document_id,
            trigger_document_id=trigger_document_id,
        )
        return {"marked": 1}
    return {"marked": len(rows), "stale": rows}
