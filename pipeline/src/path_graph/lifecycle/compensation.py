from __future__ import annotations

from typing import Any

from path_graph.admin.projects import ProjectStore
from path_graph.config import Settings, get_settings
from path_graph.graph.chunk_partition import make_nebula_store
from path_graph.ids import nebula_space_name
from path_graph.meta.pg import PgMetaStore


def compensate_document_index(
    tenant: str,
    project_id: str,
    document_id: str,
    *,
    settings: Settings | None = None,
    pg: PgMetaStore | None = None,
) -> dict[str, Any]:
    """Clear pgvector embeddings and Nebula chunk vertices before re-ingest."""
    s = settings or get_settings()
    if not s.path_graph_dsn:
        return {"skipped": True, "reason": "no_dsn"}
    store = pg or PgMetaStore(s.path_graph_dsn)
    doc = store.get_document(tenant, document_id)
    if doc is None:
        return {"skipped": True, "reason": "document_not_found"}

    chunk_ids = store.list_chunk_ids_for_document(tenant, document_id)
    profile = ProjectStore(s.path_graph_dsn).get_project(tenant, project_id)
    if profile is None:
        raise ValueError(f"project not found: {project_id}")
    project_slug = profile.slug

    embeddings_cleared = store.clear_embeddings_for_document(tenant, document_id)

    nebula_deleted = 0
    if chunk_ids:
        nebula = make_nebula_store(s)
        space = nebula_space_name(tenant, project_slug)
        nebula_deleted = nebula.delete_chunks(space, chunk_ids)
        nebula.prune_orphan_entities(space)

    store.insert_purge_audit(
        tenant,
        project_id,
        "document",
        document_id,
        "compensation",
        "ok",
        {
            "chunk_count": len(chunk_ids),
            "embeddings_cleared": embeddings_cleared,
            "nebula_deleted": nebula_deleted,
        },
    )
    return {
        "document_id": document_id,
        "chunk_ids": chunk_ids,
        "embeddings_cleared": embeddings_cleared,
        "nebula_deleted": nebula_deleted,
    }
