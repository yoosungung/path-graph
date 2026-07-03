from __future__ import annotations

import time
from typing import Any

from path_graph.admin.projects import ProjectStore
from path_graph.config import Settings, get_settings
from path_graph.graph.chunk_partition import make_nebula_store
from path_graph.ids import nebula_space_name
from path_graph.meta.pg import PgMetaStore


def reconcile_project_index(
    tenant: str,
    project_id: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """PG chunks as source of truth; delete Nebula orphans."""
    started = time.monotonic()
    s = settings or get_settings()
    if not s.path_graph_dsn:
        raise ValueError("PATH_GRAPH_DSN required")
    pg = PgMetaStore(s.path_graph_dsn)
    profile = ProjectStore(s.path_graph_dsn).get_project(tenant, project_id)
    if profile is None:
        raise ValueError(f"project not found: {project_id}")

    active_chunks = pg.list_active_chunk_ids(tenant, project_id)
    nebula_orphans = 0

    nebula = make_nebula_store(s)
    space = nebula_space_name(tenant, profile.slug)
    nebula_chunks = set(nebula.list_chunk_vertices(space))
    nebula_orphan_ids = sorted(nebula_chunks - active_chunks)
    if nebula_orphan_ids:
        nebula_orphans = nebula.delete_chunks(space, nebula_orphan_ids)
        nebula.prune_orphan_entities(space)

    duration_ms = int((time.monotonic() - started) * 1000)
    report_id = pg.insert_reconcile_report(
        tenant,
        project_id,
        vector_orphans_cleared=0,
        nebula_orphans_deleted=nebula_orphans,
        pg_missing_points=0,
        duration_ms=duration_ms,
    )
    return {
        "report_id": report_id,
        "vector_orphans_cleared": 0,
        "nebula_orphans_deleted": nebula_orphans,
        "duration_ms": duration_ms,
    }
