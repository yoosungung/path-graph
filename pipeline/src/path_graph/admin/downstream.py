from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from path_graph.admin.projects import ProjectStore
from path_graph.admin.sources import SourceStore
from path_graph.config import Settings, get_settings
from path_graph.contracts.s3_keys import s3_key_batch_manifest, s3_key_chunks, s3_key_chunks_project_batch
from path_graph.meta.pg import PgMetaStore
from path_graph.storage.blob import make_blob_store, read_jsonl, write_jsonl


class DownstreamValidationError(ValueError):
    """Invalid batch or document state for downstream GraphRAG."""


class DownstreamBusyError(Exception):
    """An active GraphRAG workflow already exists for this batch."""


@dataclass(frozen=True)
class AggregateBatchResult:
    chunks_key: str
    document_count: int
    chunk_line_count: int
    document_ids: list[str]


@dataclass(frozen=True)
class GraphragSubmitPlan:
    tenant: str
    project_id: str
    project_slug: str
    batch_id: str
    chunks_key: str
    document_count: int
    document_ids: list[str]

    def argo_parameters(self, *, skip_agent: bool = False) -> list[dict[str, str]]:
        return [
            {"name": "tenant", "value": self.tenant},
            {"name": "project_id", "value": self.project_id},
            {"name": "project_slug", "value": self.project_slug},
            {"name": "batch_id", "value": self.batch_id},
            {"name": "chunks_key", "value": self.chunks_key},
            {"name": "skip_agent", "value": "1" if skip_agent else "0"},
        ]


def _require_pg(dsn: str | None, settings: Settings) -> PgMetaStore:
    resolved = dsn or settings.path_graph_dsn
    if not resolved:
        raise DownstreamValidationError("PATH_GRAPH_DSN is required for downstream GraphRAG")
    return PgMetaStore(resolved)


def aggregate_batch_chunks(
    tenant: str,
    project_id: str,
    batch_id: str,
    *,
    settings: Settings | None = None,
    dsn: str | None = None,
) -> AggregateBatchResult:
    s = settings or get_settings()
    store = make_blob_store(s)
    manifest_key = s3_key_batch_manifest(tenant, batch_id)
    if not store.exists(manifest_key):
        raise DownstreamValidationError(f"batch manifest not found: {manifest_key}")

    manifest_lines = read_jsonl(store, manifest_key)
    if not manifest_lines:
        raise DownstreamValidationError("batch manifest is empty")

    pg = _require_pg(dsn, s)
    merged: list[dict[str, Any]] = []
    document_ids: list[str] = []

    for line in manifest_lines:
        line_project = str(line.get("project_id") or "").strip()
        if line_project and line_project != project_id:
            raise DownstreamValidationError(
                f"manifest project_id mismatch: expected {project_id}, got {line_project}"
            )
        doc_id = str(line.get("document_id") or "").strip()
        if not doc_id:
            raise DownstreamValidationError("manifest line missing document_id")
        doc = pg.get_document(tenant, doc_id)
        if not doc or doc.get("ingest_state") != "indexed_rag":
            raise DownstreamValidationError(
                f"document {doc_id} is not indexed_rag (required for GraphRAG)"
            )
        chunks_key = s3_key_chunks(tenant, doc_id)
        if not store.exists(chunks_key):
            raise DownstreamValidationError(f"chunks not found for document {doc_id}")
        merged.extend(read_jsonl(store, chunks_key))
        document_ids.append(doc_id)

    out_key = s3_key_chunks_project_batch(tenant, project_id, batch_id)
    write_jsonl(out_key, merged, store)
    return AggregateBatchResult(
        chunks_key=out_key,
        document_count=len(document_ids),
        chunk_line_count=len(merged),
        document_ids=document_ids,
    )


def prepare_graphrag_submission(
    tenant: str,
    project_id: str,
    batch_id: str,
    *,
    settings: Settings | None = None,
    dsn: str | None = None,
) -> GraphragSubmitPlan:
    s = settings or get_settings()
    resolved_dsn = dsn or s.path_graph_dsn
    if not resolved_dsn:
        raise DownstreamValidationError("PATH_GRAPH_DSN is required")

    project = ProjectStore(resolved_dsn).get_project(tenant, project_id)
    if project is None:
        raise DownstreamValidationError(f"project not found: {project_id}")

    aggregate = aggregate_batch_chunks(
        tenant,
        project_id,
        batch_id,
        settings=s,
        dsn=resolved_dsn,
    )
    return GraphragSubmitPlan(
        tenant=tenant,
        project_id=project_id,
        project_slug=project.slug,
        batch_id=batch_id,
        chunks_key=aggregate.chunks_key,
        document_count=aggregate.document_count,
        document_ids=aggregate.document_ids,
    )


def assert_project_graphrag_idle(
    store: SourceStore,
    tenant: str,
    project_id: str,
    batch_id: str,
) -> None:
    if store.has_active_graphrag_run(tenant, project_id, batch_id):
        raise DownstreamBusyError(
            f"GraphRAG workflow already active for batch {batch_id}"
        )


def apply_graphrag_success(
    tenant: str,
    project_id: str,
    batch_id: str,
    *,
    settings: Settings | None = None,
    dsn: str | None = None,
) -> int:
    """Mark manifest documents graph+wiki indexed after GraphRAG WF succeeds."""
    s = settings or get_settings()
    pg = _require_pg(dsn, s)
    store = make_blob_store(s)
    manifest_key = s3_key_batch_manifest(tenant, batch_id)
    if not store.exists(manifest_key):
        return 0
    document_ids = [
        str(line.get("document_id"))
        for line in read_jsonl(store, manifest_key)
        if line.get("document_id")
    ]
    return pg.mark_graphrag_indexed(tenant, document_ids)
