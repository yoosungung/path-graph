from __future__ import annotations

import json
import sys
from typing import Any

from path_graph.admin.projects import ProjectStore
from path_graph.lifecycle.compensation import compensate_document_index
from path_graph.lifecycle.tombstone import TombstoneError, check_tombstone
from path_graph.config import get_settings
from path_graph.contracts.schemas import BatchManifestLine
from path_graph.contracts.s3_keys import s3_key_dead_letter, s3_key_raw
from path_graph.ids import document_id
from path_graph.meta.pg import PgMetaStore
from path_graph.steps.ingest import ParseError, ingest_raw_bytes
from path_graph.steps.rag_index import index_rag_for_document
from path_graph.storage.blob import make_blob_store


def resolve_project_slug(
    tenant: str,
    project_id: str,
    settings,
    *,
    project_slug: str | None = None,
) -> str:
    if project_slug:
        return project_slug
    if settings.path_graph_dsn:
        profile = ProjectStore(settings.path_graph_dsn).get_project(tenant, project_id)
        if profile is not None:
            return profile.slug
    raise ValueError(f"project not found: {project_id}")


def parse_manifest_line(raw: str | dict[str, Any], *, tenant: str | None = None) -> dict[str, Any]:
    """Parse BatchManifestLine JSON (manifest.jsonl one line) into ingest meta dict."""
    data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    t = (tenant or data.get("tenant") or "").strip()
    if not t:
        raise ValueError("tenant is required")
    line = BatchManifestLine.model_validate({**data, "tenant": t})
    meta = line.model_dump(exclude_none=True)
    meta["document_id"] = data.get("document_id") or document_id(
        t, meta["project_id"], meta["content_hash"]
    )
    return meta


def load_raw_for(tenant: str, meta: dict) -> bytes:
    store = make_blob_store(get_settings())
    key = s3_key_raw(
        tenant,
        meta["project_id"],
        meta["source_id"],
        meta["content_hash"],
        meta["filename"],
    )
    return store.get_bytes(key)


def ingest_item(
    meta: dict,
    tenant: str,
    source_id: str,
    project_id: str,
    project_slug: str,
    *,
    rag: bool,
    settings,
) -> tuple[bool, str]:
    data = load_raw_for(tenant, meta)
    if settings.path_graph_dsn:
        pg = PgMetaStore(settings.path_graph_dsn)
        try:
            pg.migrate()
        except Exception:
            pass
        try:
            check_tombstone(pg, tenant, project_id, meta["content_hash"])
        except TombstoneError as exc:
            return False, str(exc)
        existing = pg.get_document(tenant, meta["document_id"])
        if existing and existing.get("ingest_state") in ("indexed_rag", "indexed_graph"):
            compensate_document_index(
                tenant, project_id, meta["document_id"], settings=settings, pg=pg
            )
        pg.upsert_document(
            tenant,
            meta["document_id"],
            meta["source_id"],
            project_id,
            meta["content_hash"],
            meta["s3_raw_uri"],
            "",
        )
    try:
        result = ingest_raw_bytes(data, meta["filename"], tenant, source_id, meta)
    except ParseError as exc:
        if settings.path_graph_dsn:
            store = make_blob_store(settings)
            dl_key = s3_key_dead_letter(tenant, meta["content_hash"])
            stage = "parse"
            if store.exists(dl_key):
                try:
                    stage = json.loads(store.get_bytes(dl_key)).get("stage", stage)
                except Exception:
                    pass
            PgMetaStore(settings.path_graph_dsn).record_dead_letter(
                tenant, meta["document_id"], {"stage": stage, "error": str(exc)}
            )
        return False, str(exc)

    if rag:
        index_rag_for_document(
            tenant,
            result["chunks_key"],
            meta["document_id"],
            project_slug,
            skip_pg=not settings.path_graph_dsn,
        )
    return True, result["chunks_uri"]


def run_ingest_loop(
    items: list[dict],
    tenant: str,
    source_id: str,
    project_id: str,
    project_slug: str,
    *,
    rag: bool,
    settings,
) -> int:
    ok = 0
    errors: list[str] = []
    for meta in items:
        success, detail = ingest_item(
            meta,
            tenant,
            source_id,
            project_id,
            project_slug,
            rag=rag,
            settings=settings,
        )
        if success:
            ok += 1
            print(detail)
        else:
            errors.append(f"{meta['filename']}: {detail}")
            print(f"parse failed: {meta['filename']}: {detail}", file=sys.stderr)

    print(f"ingested {ok}/{len(items)} file(s)", file=sys.stderr)
    if errors:
        print("failures:", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 2 if ok == 0 else 0
    return 0
