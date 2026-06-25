from __future__ import annotations

import argparse
import sys
from pathlib import Path

from path_graph.admin.projects import ProjectStore
from path_graph.collectors.remote import collect_local_file, collect_web
from path_graph.config import get_settings
from path_graph.contracts.s3_keys import s3_key_raw
from path_graph.meta.pg import PgMetaStore
from path_graph.steps.ingest import ParseError, ingest_raw_bytes
from path_graph.steps.rag_index import index_rag_for_document
from path_graph.storage.blob import make_blob_store


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Web/local ingest → parse → chunk → optional RAG")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--url", help="HTTP URL to collect")
    parser.add_argument("--file", help="Local file path")
    parser.add_argument("--source-id", default="web")
    parser.add_argument("--rag", action="store_true", help="Run embed + Qdrant index")
    args = parser.parse_args(argv)

    settings = get_settings()
    project_slug = args.project_id
    if settings.path_graph_dsn:
        profile = ProjectStore(settings.path_graph_dsn).get_project(args.tenant, args.project_id)
        if profile is not None:
            project_slug = profile.slug

    if args.url:
        meta = collect_web(args.url, args.tenant, args.project_id, args.source_id)
        data = load_raw_for(args.tenant, meta)
    elif args.file:
        meta = collect_local_file(Path(args.file), args.tenant, args.project_id, args.source_id)
        data = load_raw_for(args.tenant, meta)
    else:
        parser.error("one of --url or --file required")

    if settings.path_graph_dsn:
        pg = PgMetaStore(settings.path_graph_dsn)
        try:
            pg.migrate()
        except Exception:
            pass
        pg.upsert_document(
            args.tenant,
            meta["document_id"],
            meta["source_id"],
            args.project_id,
            meta["content_hash"],
            meta["s3_raw_uri"],
            "",
        )

    try:
        result = ingest_raw_bytes(
            data,
            meta["filename"],
            args.tenant,
            args.source_id,
            meta,
        )
    except ParseError as exc:
        if settings.path_graph_dsn:
            PgMetaStore(settings.path_graph_dsn).record_dead_letter(
                args.tenant, meta["document_id"], {"stage": "parse", "error": str(exc)}
            )
        print(f"parse failed: {exc}", file=sys.stderr)
        return 2

    print(result["chunks_uri"])
    if args.rag:
        n = index_rag_for_document(
            args.tenant,
            result["chunks_key"],
            meta["document_id"],
            project_slug,
            skip_pg=not settings.path_graph_dsn,
            skip_qdrant=not settings.qdrant_url,
        )
        print(f"indexed {n} chunks")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
