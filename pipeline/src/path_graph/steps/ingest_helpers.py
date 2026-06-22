from __future__ import annotations

import sys

from path_graph.config import get_settings
from path_graph.contracts.s3_keys import s3_key_raw
from path_graph.meta.pg import PgMetaStore
from path_graph.steps.ingest import ParseError, ingest_raw_bytes
from path_graph.steps.rag_index import index_rag_for_document
from path_graph.storage.blob import make_blob_store


def load_raw_for(tenant: str, meta: dict) -> bytes:
    store = make_blob_store(get_settings())
    key = s3_key_raw(tenant, meta["source_id"], meta["content_hash"], meta["filename"])
    return store.get_bytes(key)


def ingest_item(
    meta: dict,
    tenant: str,
    source_id: str,
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
        pg.upsert_document(
            tenant,
            meta["document_id"],
            meta["source_id"],
            meta["content_hash"],
            meta["s3_raw_uri"],
            "",
        )
    try:
        result = ingest_raw_bytes(data, meta["filename"], tenant, source_id, meta)
    except ParseError as exc:
        if settings.path_graph_dsn:
            PgMetaStore(settings.path_graph_dsn).record_dead_letter(
                tenant, meta["document_id"], {"stage": "parse", "error": str(exc)}
            )
        return False, str(exc)

    if rag:
        index_rag_for_document(
            tenant,
            result["chunks_key"],
            meta["document_id"],
            skip_pg=not settings.path_graph_dsn,
            skip_qdrant=not settings.qdrant_url,
        )
    return True, result["chunks_uri"]


def run_ingest_loop(
    items: list[dict],
    tenant: str,
    source_id: str,
    *,
    rag: bool,
    settings,
) -> int:
    ok = 0
    errors: list[str] = []
    for meta in items:
        success, detail = ingest_item(
            meta, tenant, source_id, rag=rag, settings=settings
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
