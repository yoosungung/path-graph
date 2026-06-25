"""Argo / CLI entrypoints for lifecycle operations."""

from __future__ import annotations

import argparse
import json
import sys

from path_graph.config import get_settings
from path_graph.lifecycle.artifact_cleanup import artifact_cleanup
from path_graph.lifecycle.purge import purge_document, purge_project, purge_source
from path_graph.lifecycle.reconcile import reconcile_project_index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Purge documents/sources/projects")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--scope", choices=("document", "source", "project"), default="document")
    parser.add_argument("--document-id", default="")
    parser.add_argument("--source-id", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--hard-raw", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.scope == "document":
        if not args.document_id:
            print("document-id required", file=sys.stderr)
            return 1
        result = purge_document(
            args.tenant,
            args.project_id,
            args.document_id,
            reason=args.reason or None,
            hard_raw=args.hard_raw,
            settings=settings,
        )
    elif args.scope == "source":
        if not args.source_id:
            print("source-id required", file=sys.stderr)
            return 1
        result = purge_source(
            args.tenant,
            args.project_id,
            args.source_id,
            reason=args.reason or None,
            settings=settings,
        )
    else:
        result = purge_project(
            args.tenant,
            args.project_id,
            reason=args.reason or None,
            settings=settings,
        )
    print(json.dumps(result))
    return 0 if result.get("status") != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
