from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from path_graph.admin.projects import ProjectStore
from path_graph.config import Settings, get_settings
from path_graph.contracts.s3_keys import (
    s3_key_chunks,
    s3_key_dead_letter,
    s3_key_parsed_json,
    s3_key_parsed_md,
    s3_key_parsed_meta,
    s3_key_raw_prefix,
    s3_key_wiki_prefix,
)
from path_graph.graph.chunk_partition import make_nebula_store
from path_graph.ids import nebula_space_name, qdrant_collection_name
from path_graph.lifecycle.compensation import compensate_document_index
from path_graph.lifecycle.wiki_stale import mark_project_wiki_stale
from path_graph.meta.pg import PgMetaStore
from path_graph.rag.qdrant_store import make_qdrant_store
from path_graph.storage.blob import make_blob_store


def _delete_parsed_artifacts(
    blob, tenant: str, document_id: str
) -> int:
    keys = [
        s3_key_parsed_md(tenant, document_id),
        s3_key_parsed_json(tenant, document_id),
        s3_key_parsed_meta(tenant, document_id),
        s3_key_chunks(tenant, document_id),
    ]
    return sum(1 for k in keys if blob.delete_object(k))


def purge_document(
    tenant: str,
    project_id: str,
    document_id: str,
    *,
    reason: str | None = None,
    hard_raw: bool = False,
    purged_by: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    s = settings or get_settings()
    if not s.path_graph_dsn:
        raise ValueError("PATH_GRAPH_DSN required for purge")
    pg = PgMetaStore(s.path_graph_dsn)
    doc = pg.get_document(tenant, document_id)
    if doc is None:
        return {"status": "not_found"}
    if doc.get("ingest_state") == "purged":
        return {"status": "already_purged", "document_id": document_id}

    pg.set_document_ingest_state(tenant, document_id, "purging")
    comp = compensate_document_index(tenant, project_id, document_id, settings=s, pg=pg)

    blob = make_blob_store(s)
    s3_deleted = _delete_parsed_artifacts(blob, tenant, document_id)
    s3_deleted += (
        1
        if blob.delete_object(s3_key_dead_letter(tenant, doc["content_hash"]))
        else 0
    )

    purge_after = None if hard_raw else datetime.now(UTC) + timedelta(days=30)
    if hard_raw and doc.get("s3_raw_uri"):
        raw_key = doc["s3_raw_uri"].split("://", 1)[-1]
        if "/" in raw_key and not raw_key.startswith("/"):
            raw_key = raw_key.split("/", 1)[-1]
        s3_deleted += 1 if blob.delete_object(raw_key) else 0

    pg.delete_chunks_for_document(tenant, document_id)
    pg.insert_tombstone(
        tenant,
        project_id,
        doc["content_hash"],
        document_id,
        reason=reason,
        purged_by=purged_by,
    )
    pg.mark_document_purged(
        tenant, document_id, reason=reason, purge_after_at=purge_after
    )
    pg.insert_purge_audit(
        tenant,
        project_id,
        "document",
        document_id,
        "pg",
        "purged",
        {"reason": reason, "s3_deleted": s3_deleted, **comp},
    )
    mark_project_wiki_stale(
        tenant,
        project_id,
        trigger_document_id=document_id,
        settings=s,
    )
    return {
        "status": "purged",
        "document_id": document_id,
        "compensation": comp,
        "s3_deleted": s3_deleted,
    }


def purge_source(
    tenant: str,
    project_id: str,
    source_id: str,
    *,
    reason: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    s = settings or get_settings()
    if not s.path_graph_dsn:
        raise ValueError("PATH_GRAPH_DSN required")
    pg = PgMetaStore(s.path_graph_dsn)
    docs = pg.list_documents_for_project(
        tenant, project_id, source_id=source_id
    )
    results = []
    for doc in docs:
        if doc["ingest_state"] in ("purged", "purging"):
            continue
        results.append(
            purge_document(
                tenant,
                project_id,
                doc["document_id"],
                reason=reason or f"source_purge:{source_id}",
                settings=s,
            )
        )
    return {"status": "ok", "purged_count": len(results), "results": results}


def purge_project(
    tenant: str,
    project_id: str,
    *,
    reason: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    s = settings or get_settings()
    if not s.path_graph_dsn:
        raise ValueError("PATH_GRAPH_DSN required")
    profile = ProjectStore(s.path_graph_dsn).get_project(tenant, project_id)
    if profile is None:
        raise ValueError(f"project not found: {project_id}")

    pg = PgMetaStore(s.path_graph_dsn)
    docs = pg.list_documents_for_project(tenant, project_id)
    results = []
    for doc in docs:
        if doc["ingest_state"] not in ("purged", "purging"):
            results.append(
                purge_document(
                    tenant,
                    project_id,
                    doc["document_id"],
                    reason=reason or "project_purge",
                    hard_raw=True,
                    settings=s,
                )
            )

    blob = make_blob_store(s)
    wiki_prefix_deleted = blob.delete_prefix(s3_key_wiki_prefix(tenant, project_id))
    raw_prefix_deleted = blob.delete_prefix(s3_key_raw_prefix(tenant, project_id))

    if s.qdrant_url:
        qdrant = make_qdrant_store(s)
        collection = qdrant_collection_name(tenant, profile.slug)
        qdrant.delete_collection(collection)

    nebula = make_nebula_store(s)
    space = nebula_space_name(tenant, profile.slug)
    nebula.drop_space(space)

    with pg._conn() as conn:
        pg._set_tenant(conn, tenant)
        conn.execute(
            """
            UPDATE path_graph.projects
            SET deleted_at = now(), purge_state = 'purged'
            WHERE tenant = %s AND id = %s::uuid
            """,
            (tenant, project_id),
        )
        conn.commit()

    return {
        "status": "purged",
        "project_id": project_id,
        "prefix_deleted": wiki_prefix_deleted,
        "raw_prefix_deleted": raw_prefix_deleted,
        "purged_documents": len(results),
    }


def delete_project(
    tenant: str,
    project_id: str,
    *,
    reason: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    s = settings or get_settings()
    if not s.path_graph_dsn:
        raise ValueError("PATH_GRAPH_DSN required")
    pg = PgMetaStore(s.path_graph_dsn)
    if ProjectStore(s.path_graph_dsn).get_project(tenant, project_id) is None:
        raise ValueError(f"project not found: {project_id}")

    doc_ids = [
        d["document_id"]
        for d in pg.list_documents_for_project(tenant, project_id)
    ]
    purge_result = purge_project(
        tenant,
        project_id,
        reason=reason or "project_delete",
        settings=s,
    )

    blob = make_blob_store(s)
    parsed_prefix_deleted = sum(
        blob.delete_prefix(f"parsed/{tenant}/{doc_id}/") for doc_id in doc_ids
    )
    communities_prefix_deleted = blob.delete_prefix(
        f"communities/{tenant}/{project_id}/"
    )
    graph_context_prefix_deleted = blob.delete_prefix(
        f"graph_context/{tenant}/{project_id}/"
    )
    batch_chunks_prefix_deleted = blob.delete_prefix(
        f"chunks/{tenant}/{project_id}/"
    )

    pg_deleted = pg.delete_project_data(tenant, project_id)
    return {
        "status": "deleted",
        "project_id": project_id,
        "parsed_prefix_deleted": parsed_prefix_deleted,
        "communities_prefix_deleted": communities_prefix_deleted,
        "graph_context_prefix_deleted": graph_context_prefix_deleted,
        "batch_chunks_prefix_deleted": batch_chunks_prefix_deleted,
        "pg_deleted": pg_deleted,
        **{
            k: v
            for k, v in purge_result.items()
            if k not in ("status", "project_id")
        },
    }
