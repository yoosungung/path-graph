from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from path_graph.collectors.remote import SharePointCollector
from path_graph.config import get_settings
from path_graph.steps.ingest_helpers import run_ingest_loop


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SharePoint collect → parse → chunk → optional RAG"
    )
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--source-id", default="sharepoint:kms")
    parser.add_argument("--site", help="SharePoint site path (host:/sites/name)")
    parser.add_argument("--drive", help="Document library drive name")
    parser.add_argument("--folder", help="Folder path within drive")
    parser.add_argument("--batch-id", help="Batch id for manifest (default: UTC date)")
    parser.add_argument("--no-recursive", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="List files only, no download/ingest")
    parser.add_argument("--collect-only", action="store_true", help="Download to raw S3 only")
    parser.add_argument("--rag", action="store_true", help="Run embed + Qdrant index")
    args = parser.parse_args(argv)

    settings = get_settings()
    collector = SharePointCollector()

    if args.dry_run:
        items = collector.enumerate_files(
            site=args.site,
            drive_name=args.drive,
            folder=args.folder,
            recursive=not args.no_recursive,
        )
        for item in items:
            print(item.get("name", ""))
        print(f"would collect {len(items)} file(s)", file=sys.stderr)
        return 0

    items = collector.collect_folder(
        args.tenant,
        args.source_id,
        site=args.site,
        drive_name=args.drive,
        folder=args.folder,
        recursive=not args.no_recursive,
    )
    batch_id = args.batch_id or datetime.now(UTC).strftime("%Y%m%d")
    manifest_uri = collector.write_batch_manifest(args.tenant, batch_id, items)
    print(manifest_uri)

    if args.collect_only:
        print(f"collected {len(items)} file(s)")
        return 0

    return run_ingest_loop(items, args.tenant, args.source_id, rag=args.rag, settings=settings)


if __name__ == "__main__":
    raise SystemExit(main())
