from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from path_graph.collectors.remote import GDriveCollector
from path_graph.config import get_settings
from path_graph.steps.ingest_helpers import resolve_project_slug, run_ingest_loop


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Google Drive collect → parse → chunk → optional RAG"
    )
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--source-id", default="gdrive")
    parser.add_argument("--folder-id", help="Drive folder ID (overrides GDRIVE_FOLDER_ID)")
    parser.add_argument("--folder-path", help="Folder path from root (overrides GDRIVE_FOLDER_PATH)")
    parser.add_argument("--file-id", help="Single file ID instead of folder collect")
    parser.add_argument("--batch-id", help="Batch id for manifest (default: UTC date)")
    parser.add_argument("--no-recursive", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--rag", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    collector = GDriveCollector()
    project_slug = resolve_project_slug(args.tenant, args.project_id, settings)

    if args.file_id:
        meta = collector.collect_file(args.file_id, args.tenant, args.project_id, args.source_id)
        batch_id = args.batch_id or datetime.now(UTC).strftime("%Y%m%d")
        print(collector.write_batch_manifest(args.tenant, batch_id, [meta]))
        if args.collect_only:
            return 0
        return run_ingest_loop(
            [meta],
            args.tenant,
            args.source_id,
            args.project_id,
            project_slug,
            rag=args.rag,
            settings=settings,
        )

    if args.dry_run:
        items = collector.enumerate_files(
            folder_id=args.folder_id,
            folder_path=args.folder_path,
            recursive=not args.no_recursive,
        )
        for item in items:
            print(item.get("name", ""))
        print(f"would collect {len(items)} file(s)", file=sys.stderr)
        return 0

    items = collector.collect_folder(
        args.tenant,
        args.project_id,
        args.source_id,
        folder_id=args.folder_id,
        folder_path=args.folder_path,
        recursive=not args.no_recursive,
    )
    batch_id = args.batch_id or datetime.now(UTC).strftime("%Y%m%d")
    print(collector.write_batch_manifest(args.tenant, batch_id, items))

    if args.collect_only:
        print(f"collected {len(items)} file(s)")
        return 0

    return run_ingest_loop(
        items,
        args.tenant,
        args.source_id,
        args.project_id,
        project_slug,
        rag=args.rag,
        settings=settings,
    )


if __name__ == "__main__":
    raise SystemExit(main())
