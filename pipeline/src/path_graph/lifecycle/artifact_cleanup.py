from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from path_graph.config import Settings, get_settings
from path_graph.contracts.s3_keys import s3_key_batch_manifest
from path_graph.meta.pg import PgMetaStore
from path_graph.storage.blob import make_blob_store


def artifact_cleanup(
    tenant: str,
    project_id: str | None = None,
    *,
    dry_run: bool = True,
    batch_ttl_days: int = 14,
    orphan_raw_days: int = 30,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Temp artifact cleanup — does not touch indexed RAG/graph stores."""
    s = settings or get_settings()
    blob = make_blob_store(s)
    now = datetime.now(UTC)
    batch_cutoff = now - timedelta(days=batch_ttl_days)
    raw_cutoff = now - timedelta(days=orphan_raw_days)

    to_delete: list[str] = []
    prefix = f"batches/{tenant}/"
    for key in blob.list_keys(prefix):
        if key.endswith("manifest.jsonl"):
            to_delete.append(key)

    # raw orphans: keys under raw/{tenant}/{project_id}/ without PG document
    pg_doc_hashes: set[str] = set()
    if s.path_graph_dsn:
        pg = PgMetaStore(s.path_graph_dsn)
        if project_id:
            docs = pg.list_documents_for_project(tenant, project_id)
        else:
            docs = []
        pg_doc_hashes = {d["content_hash"] for d in docs}

    raw_prefix = f"raw/{tenant}/"
    if project_id:
        raw_prefix = f"raw/{tenant}/{project_id}/"
    for key in blob.list_keys(raw_prefix):
        parts = key.split("/")
        if len(parts) >= 5:
            content_hash = parts[4]
            if content_hash not in pg_doc_hashes:
                to_delete.append(key)

    deleted = 0
    if not dry_run:
        for key in to_delete:
            if blob.delete_object(key):
                deleted += 1

    return {
        "dry_run": dry_run,
        "candidate_count": len(to_delete),
        "deleted_count": deleted,
        "candidates": to_delete[:50],
    }
