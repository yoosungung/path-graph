from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from path_graph.admin.sources import SourceStore
from path_graph.collectors.remote import store_raw, write_batch_manifest
from path_graph.config import Settings, get_settings
from path_graph.contracts.s3_keys import s3_key_batch_manifest, s3_key_raw
from path_graph.contracts.source import SourceDriver, SourceProfile
from path_graph.ids import sha256_bytes
from path_graph.meta.pg import PgMetaStore
from path_graph.storage.blob import make_blob_store


class UploadValidationError(ValueError):
    """Client-facing upload validation failure."""


MANUAL_DEFAULT_ALLOWED_EXTENSIONS = (
    ".pdf,.hwp,.hwpx,.doc,.docx,.xls,.xlsx,.txt,.md"
)
_LEGACY_MANUAL_ALLOWED_EXTENSIONS = ".pdf,.hwp,.docx,.txt,.md"


def effective_allowed_extensions(config: dict[str, Any]) -> str:
    raw = config.get("allowed_extensions")
    if not isinstance(raw, str) or not raw.strip():
        return MANUAL_DEFAULT_ALLOWED_EXTENSIONS
    stripped = raw.strip()
    if stripped.replace(" ", "") == _LEGACY_MANUAL_ALLOWED_EXTENSIONS.replace(" ", ""):
        return MANUAL_DEFAULT_ALLOWED_EXTENSIONS
    return stripped


def filename_from_raw_uri(uri: str) -> str:
    path_part = uri.split("://", 1)[-1]
    if not path_part.startswith("/") and "/" in path_part:
        path_part = path_part.split("/", 1)[-1]
    else:
        path_part = path_part.lstrip("/")
    return path_part.rsplit("/", 1)[-1]


def _parse_extensions(raw: str | list[str] | None) -> set[str] | None:
    if not raw:
        return None
    if isinstance(raw, list):
        parts = raw
    else:
        parts = str(raw).split(",")
    ext_set = {
        p.strip().lower() if p.strip().startswith(".") else f".{p.strip().lower()}"
        for p in parts
        if p.strip()
    }
    return ext_set or None


def validate_upload_file(
    filename: str,
    size: int,
    config: dict[str, Any],
    *,
    server_max_mb: int,
) -> None:
    ext_set = _parse_extensions(effective_allowed_extensions(config))
    if ext_set:
        lower = filename.lower()
        if not any(lower.endswith(ext) for ext in ext_set):
            raise UploadValidationError(
                f"extension not allowed: {filename} (allowed: {', '.join(sorted(ext_set))})"
            )
    max_mb = config.get("max_file_mb")
    limit_mb = int(max_mb) if max_mb is not None else server_max_mb
    if size > limit_mb * 1024 * 1024:
        raise UploadValidationError(f"file exceeds size limit ({limit_mb} MB): {filename}")


def _document_row(doc: dict[str, Any]) -> dict[str, Any]:
    uri = doc.get("s3_raw_uri") or ""
    filename = doc.get("filename") or filename_from_raw_uri(uri)
    return {**doc, "filename": filename}


def list_documents_for_source(
    tenant: str,
    profile: SourceProfile,
    *,
    ingest_state: str | None = None,
    limit: int = 50,
    dsn: str | None = None,
) -> list[dict[str, Any]]:
    s = get_settings()
    resolved = dsn or s.path_graph_dsn
    if not resolved:
        return []
    store = SourceStore(resolved)
    docs = store.list_documents_by_source(
        tenant,
        profile.source_id,
        ingest_state=ingest_state,
        limit=limit,
    )
    return [_document_row(d) for d in docs]


def upload_raw_file(
    profile: SourceProfile,
    data: bytes,
    filename: str,
    mime: str = "application/octet-stream",
    *,
    settings: Settings | None = None,
    server_max_mb: int = 100,
) -> dict[str, Any]:
    if profile.driver != SourceDriver.MANUAL:
        raise UploadValidationError("upload only supported for manual driver")
    validate_upload_file(filename, len(data), profile.config, server_max_mb=server_max_mb)

    s = settings or get_settings()
    tenant = profile.tenant
    source_id = profile.source_id
    content_hash = sha256_bytes(data)
    key = s3_key_raw(tenant, source_id, content_hash, filename)
    blob = make_blob_store(s)
    already_exists = blob.exists(key)

    meta = store_raw(data, filename, tenant, source_id, mime, settings=s, store=blob)

    if not already_exists and s.path_graph_dsn:
        pg = PgMetaStore(s.path_graph_dsn)
        pg.upsert_document(
            tenant,
            meta["document_id"],
            source_id,
            content_hash,
            meta["s3_raw_uri"],
            "",
            ingest_state="pending",
        )

    if already_exists:
        return {
            "filename": filename,
            "status": "skipped",
            "skipped": True,
            "reason": "already_exists",
            "content_hash": content_hash,
            "document_id": meta["document_id"],
            "s3_raw_uri": meta["s3_raw_uri"],
        }

    return {
        "filename": filename,
        "status": "uploaded",
        "skipped": False,
        "content_hash": content_hash,
        "document_id": meta["document_id"],
        "s3_raw_uri": meta["s3_raw_uri"],
    }


def upload_raw_files(
    profile: SourceProfile,
    files: list[tuple[str, bytes, str]],
    *,
    settings: Settings | None = None,
    server_max_mb: int = 100,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    uploaded_count = 0
    skipped_count = 0
    for filename, data, mime in files:
        try:
            item = upload_raw_file(
                profile,
                data,
                filename,
                mime,
                settings=settings,
                server_max_mb=server_max_mb,
            )
        except UploadValidationError as exc:
            item = {
                "filename": filename,
                "status": "rejected",
                "skipped": False,
                "reason": str(exc),
            }
        if item.get("status") == "uploaded":
            uploaded_count += 1
        elif item.get("status") == "skipped":
            skipped_count += 1
        items.append(item)
    return {
        "items": items,
        "uploaded_count": uploaded_count,
        "skipped_count": skipped_count,
    }


def build_ingest_manifest(
    profile: SourceProfile,
    document_ids: list[str] | None,
    batch_id: str | None = None,
    *,
    settings: Settings | None = None,
    dsn: str | None = None,
) -> dict[str, Any]:
    if profile.driver != SourceDriver.MANUAL:
        raise UploadValidationError("ingest manifest only supported for manual driver")

    s = settings or get_settings()
    bid = batch_id or datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    docs = list_documents_for_source(
        profile.tenant,
        profile,
        ingest_state="pending",
        limit=500,
        dsn=dsn,
    )
    if document_ids:
        wanted = set(document_ids)
        docs = [d for d in docs if d["document_id"] in wanted]

    manifest_items = [
        {
            "tenant": profile.tenant,
            "source_id": profile.source_id,
            "content_hash": d["content_hash"],
            "document_id": d["document_id"],
            "s3_raw_uri": d["s3_raw_uri"],
            "filename": d["filename"],
        }
        for d in docs
    ]
    write_batch_manifest(profile.tenant, bid, manifest_items, s)
    manifest_key = s3_key_batch_manifest(profile.tenant, bid)
    return {
        "batch_id": bid,
        "manifest_key": manifest_key,
        "file_count": len(manifest_items),
    }
