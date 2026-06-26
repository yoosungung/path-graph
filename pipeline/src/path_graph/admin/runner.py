from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from path_graph.collectors.remote import (
    GDriveCollector,
    OneDriveCollector,
    SharePointCollector,
    write_batch_manifest,
)
from path_graph.admin.credential_settings import merge_credential_into_settings
from path_graph.admin.credentials import CredentialStore
from path_graph.config import Settings, get_settings
from path_graph.contracts.source import SourceDriver, SourceProfile
from path_graph.storage.blob import make_blob_store, read_jsonl


def _sharepoint_collector(settings: Settings | None = None) -> SharePointCollector:
    return SharePointCollector(settings=settings or get_settings())


def _gdrive_collector(settings: Settings | None = None) -> GDriveCollector:
    return GDriveCollector(settings=settings or get_settings())


def _onedrive_collector(settings: Settings | None = None) -> OneDriveCollector:
    return OneDriveCollector(settings=settings or get_settings())


def resolve_source_settings(
    profile: SourceProfile,
    *,
    dsn: str | None = None,
    secret_values: dict[str, str] | None = None,
    platform_client_id: str = "",
    platform_client_secret: str = "",
    platform_ms_tenant_id: str = "",
    settings: Settings | None = None,
) -> Settings:
    """Build Settings for a source, optionally overlaying per-source OAuth secrets."""
    base = settings or get_settings()
    if not profile.credential_id or not secret_values:
        return base
    store = CredentialStore(dsn or base.path_graph_dsn)
    credential = store.get_credential(profile.tenant, profile.credential_id)
    if credential is None:
        return base
    return merge_credential_into_settings(
        base,
        profile=profile,
        credential=credential,
        secret_values=secret_values,
        platform_client_id=platform_client_id,
        platform_client_secret=platform_client_secret,
        platform_ms_tenant_id=platform_ms_tenant_id,
    )


def resolve_settings_from_env(
    profile: SourceProfile,
    *,
    dsn: str | None = None,
    platform_client_id: str = "",
    platform_client_secret: str = "",
    platform_ms_tenant_id: str = "",
    settings: Settings | None = None,
) -> Settings:
    """Resolve Settings using credential metadata from PG and token env vars in the pod."""
    base = settings or get_settings()
    if not profile.credential_id:
        return base
    store = CredentialStore(dsn or base.path_graph_dsn)
    credential = store.get_credential(profile.tenant, profile.credential_id)
    if credential is None:
        raise ValueError(f"credential not found: {profile.credential_id}")
    secret_values = {key: os.environ.get(key, "").strip() for key in credential.secret_keys}
    return merge_credential_into_settings(
        base,
        profile=profile,
        credential=credential,
        secret_values=secret_values,
        platform_client_id=platform_client_id,
        platform_client_secret=platform_client_secret,
        platform_ms_tenant_id=platform_ms_tenant_id,
    )


def probe_source(profile: SourceProfile, *, settings: Settings | None = None) -> dict[str, Any]:
    """Dry-run enumerate — returns file count and sample names."""
    s = settings or get_settings()
    cfg = profile.config
    if profile.driver == SourceDriver.SHAREPOINT:
        collector = _sharepoint_collector(s)
        items = collector.enumerate_files(
            site=cfg.get("site"),
            drive_name=cfg.get("drive"),
            folder=cfg.get("folder"),
            recursive=cfg.get("recursive", True),
        )
    elif profile.driver == SourceDriver.GDRIVE:
        collector = _gdrive_collector(s)
        items = collector.enumerate_files(
            folder_id=cfg.get("folder_id"),
            folder_path=cfg.get("folder_path"),
            recursive=cfg.get("recursive", True),
        )
    elif profile.driver == SourceDriver.ONEDRIVE:
        collector = _onedrive_collector(s)
        items = collector.enumerate_files(
            folder=cfg.get("folder"),
            recursive=cfg.get("recursive", True),
        )
    elif profile.driver == SourceDriver.MANUAL:
        from path_graph.admin.uploads import list_documents_for_source

        docs = list_documents_for_source(profile.tenant, profile, limit=100, dsn=s.path_graph_dsn)
        names = [d.get("filename", "") for d in docs[:10]]
        return {"file_count": len(docs), "sample_names": names}
    else:
        raise ValueError(f"unsupported driver: {profile.driver}")
    names = [i.get("name", "") for i in items[:10]]
    return {"file_count": len(items), "sample_names": names}


def collect_source(
    profile: SourceProfile,
    batch_id: str | None = None,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Collect files to raw/ and write manifest; returns manifest_key and file_count."""
    s = settings or get_settings()
    bid = batch_id or datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    cfg = profile.config
    tenant = profile.tenant
    source_id = profile.source_id

    if profile.driver == SourceDriver.SHAREPOINT:
        collector = _sharepoint_collector(s)
        items = collector.collect_folder(
            tenant,
            profile.project_id,
            source_id,
            site=cfg.get("site"),
            drive_name=cfg.get("drive"),
            folder=cfg.get("folder"),
            recursive=cfg.get("recursive", True),
        )
    elif profile.driver == SourceDriver.GDRIVE:
        collector = _gdrive_collector(s)
        items = collector.collect_folder(
            tenant,
            profile.project_id,
            source_id,
            folder_id=cfg.get("folder_id"),
            folder_path=cfg.get("folder_path"),
            recursive=cfg.get("recursive", True),
        )
    elif profile.driver == SourceDriver.ONEDRIVE:
        collector = _onedrive_collector(s)
        items = collector.collect_folder(
            tenant,
            profile.project_id,
            source_id,
            folder=cfg.get("folder"),
            recursive=cfg.get("recursive", True),
        )
    elif profile.driver == SourceDriver.MANUAL:
        raise ValueError("manual sources use upload API, not collect_source")
    else:
        raise ValueError(f"unsupported driver: {profile.driver}")

    manifest_uri = write_batch_manifest(tenant, bid, items, s)
    store = make_blob_store(s)
    from path_graph.contracts.s3_keys import s3_key_batch_manifest

    manifest_key = s3_key_batch_manifest(tenant, bid)
    return {
        "batch_id": bid,
        "manifest_key": manifest_key,
        "manifest_uri": manifest_uri,
        "file_count": len(items),
    }


def read_manifest_lines(manifest_key: str, *, settings: Settings | None = None) -> list[dict[str, Any]]:
    """Read manifest jsonl and return list of BatchManifestLine dicts for Argo withParam."""
    s = settings or get_settings()
    store = make_blob_store(s)
    lines = read_jsonl(store, manifest_key)
    out: list[dict[str, Any]] = []
    for line in lines:
        row = {
            "tenant": line["tenant"],
            "project_id": line["project_id"],
            "source_id": line["source_id"],
            "content_hash": line["content_hash"],
            "s3_raw_uri": line["s3_raw_uri"],
            "filename": line["filename"],
        }
        if line.get("mime"):
            row["mime"] = line["mime"]
        if line.get("document_id"):
            row["document_id"] = line["document_id"]
        out.append(row)
    return out


def manifest_lines_to_json(manifest_key: str, *, settings: Settings | None = None) -> str:
    return json.dumps(read_manifest_lines(manifest_key, settings=settings), separators=(",", ":"))
