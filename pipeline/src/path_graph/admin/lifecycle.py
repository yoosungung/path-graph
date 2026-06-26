"""Admin-facing lifecycle operations (BFF wraps these in agents-runtime)."""

from __future__ import annotations

from typing import Any

from path_graph.admin.projects import ProjectStore
from path_graph.admin.sources import SourceStore
from path_graph.config import get_settings
from path_graph.contracts.source import SourceProfile
from path_graph.lifecycle.artifact_cleanup import artifact_cleanup
from path_graph.lifecycle.compensation import compensate_document_index
from path_graph.lifecycle.purge import delete_project, purge_document, purge_project, purge_source
from path_graph.lifecycle.reconcile import reconcile_project_index
from path_graph.lifecycle.tombstone import TombstoneError, check_tombstone
from path_graph.meta.pg import PgMetaStore


class ProjectLifecycleBusyError(Exception):
    """Project purge/delete already in progress or completed."""


LIFECYCLE_BATCH_ID = {
    "purge": "lifecycle:purge",
    "delete": "lifecycle:delete",
}


def assert_project_lifecycle_idle(
    project_store: ProjectStore,
    source_store: SourceStore,
    tenant: str,
    project_id: str,
    *,
    operation: str,
) -> None:
    state = project_store.get_purge_state(tenant, project_id)
    if state == "purged":
        raise ProjectLifecycleBusyError("project already purged")
    if state in ("purging", "deleting"):
        raise ProjectLifecycleBusyError(f"project lifecycle in progress: {state}")
    if source_store.has_active_lifecycle_run(tenant, project_id, operation):
        raise ProjectLifecycleBusyError(
            f"active {operation} workflow already running for project"
        )


def mark_project_lifecycle_started(
    project_store: ProjectStore,
    tenant: str,
    project_id: str,
    *,
    operation: str,
) -> None:
    purge_state = "purging" if operation == "purge" else "deleting"
    project_store.set_purge_state(tenant, project_id, purge_state)


def clear_project_lifecycle_on_failure(
    project_store: ProjectStore,
    tenant: str,
    project_id: str,
) -> bool:
    return project_store.clear_in_progress_purge_state(tenant, project_id)


def api_purge_document(
    tenant: str,
    document_id: str,
    *,
    reason: str | None = None,
    hard_raw: bool = False,
) -> dict[str, Any]:
    s = get_settings()
    if not s.path_graph_dsn:
        raise ValueError("PATH_GRAPH_DSN required")
    pg = PgMetaStore(s.path_graph_dsn)
    doc = pg.get_document(tenant, document_id)
    if doc is None:
        return {"status": "not_found"}
    return purge_document(
        tenant,
        doc["project_id"],
        document_id,
        reason=reason,
        hard_raw=hard_raw,
    )


def api_restore_document(tenant: str, document_id: str) -> dict[str, Any]:
    s = get_settings()
    if not s.path_graph_dsn:
        raise ValueError("PATH_GRAPH_DSN required")
    pg = PgMetaStore(s.path_graph_dsn)
    doc = pg.get_document(tenant, document_id)
    if doc is None:
        return {"status": "not_found"}
    cleared = pg.clear_tombstone(tenant, doc["project_id"], doc["content_hash"])
    pg.set_document_ingest_state(tenant, document_id, "pending")
    return {"status": "restored", "tombstone_cleared": cleared}


def api_reingest_document(tenant: str, document_id: str) -> dict[str, Any]:
    s = get_settings()
    if not s.path_graph_dsn:
        raise ValueError("PATH_GRAPH_DSN required")
    pg = PgMetaStore(s.path_graph_dsn)
    doc = pg.get_document(tenant, document_id)
    if doc is None:
        return {"status": "not_found"}
    if doc.get("ingest_state") == "purged":
        return {"status": "error", "reason": "document purged; restore first"}
    comp = compensate_document_index(
        tenant, doc["project_id"], document_id, settings=s, pg=pg
    )
    pg.set_document_ingest_state(tenant, document_id, "pending")
    return {"status": "pending", "compensation": comp}


def api_purge_source(tenant: str, source_uuid: str, *, reason: str | None = None) -> dict[str, Any]:
    s = get_settings()
    if not s.path_graph_dsn:
        raise ValueError("PATH_GRAPH_DSN required")
    profile = SourceStore(s.path_graph_dsn).get_source(tenant, source_uuid)
    if profile is None:
        return {"status": "not_found"}
    return purge_source(
        tenant, profile.project_id, profile.source_id, reason=reason, settings=s
    )


def api_purge_project(tenant: str, project_id: str, *, reason: str | None = None) -> dict[str, Any]:
    return purge_project(tenant, project_id, reason=reason)


def api_delete_project(tenant: str, project_id: str, *, reason: str | None = None) -> dict[str, Any]:
    return delete_project(tenant, project_id, reason=reason)


def api_cleanup_project(
    tenant: str,
    project_id: str | None,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    return artifact_cleanup(tenant, project_id, dry_run=dry_run)


def api_reconcile_project(tenant: str, project_id: str) -> dict[str, Any]:
    return reconcile_project_index(tenant, project_id)


def api_list_tombstones(
    tenant: str, *, project_id: str | None = None
) -> list[dict[str, Any]]:
    s = get_settings()
    if not s.path_graph_dsn:
        return []
    return PgMetaStore(s.path_graph_dsn).list_tombstones(tenant, project_id=project_id)


def api_get_binding(tenant: str, project_id: str) -> dict[str, Any]:
    from path_graph.contracts.project import resolve_knowledge_binding

    s = get_settings()
    if not s.path_graph_dsn:
        raise ValueError("PATH_GRAPH_DSN required")
    profile = ProjectStore(s.path_graph_dsn).get_project(tenant, project_id)
    if profile is None:
        raise ValueError("project not found")
    binding = resolve_knowledge_binding(tenant, profile.id, profile.slug)
    return binding.model_dump()


__all__ = [
    "TombstoneError",
    "check_tombstone",
    "ProjectLifecycleBusyError",
    "LIFECYCLE_BATCH_ID",
    "assert_project_lifecycle_idle",
    "mark_project_lifecycle_started",
    "clear_project_lifecycle_on_failure",
    "api_purge_document",
    "api_restore_document",
    "api_reingest_document",
    "api_purge_source",
    "api_purge_project",
    "api_delete_project",
    "api_cleanup_project",
    "api_reconcile_project",
    "api_list_tombstones",
    "api_get_binding",
]
