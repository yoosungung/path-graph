from __future__ import annotations

import argparse
import json
import os
import sys

from path_graph.config import get_settings
from path_graph.steps.ingest_helpers import ingest_item, parse_manifest_line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest one BatchManifestLine (manifest.jsonl row) → parse → chunk → optional RAG"
    )
    parser.add_argument("--tenant", required=True)
    parser.add_argument(
        "--manifest-line",
        help="JSON object (BatchManifestLine). Falls back to MANIFEST_LINE env (Argo WF).",
    )
    parser.add_argument("--rag", action="store_true", help="Run embed + Qdrant index")
    args = parser.parse_args(argv)

    raw = args.manifest_line or os.environ.get("MANIFEST_LINE", "").strip()
    if not raw:
        parser.error("--manifest-line or MANIFEST_LINE env required")

    try:
        meta = parse_manifest_line(raw, tenant=args.tenant)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"invalid manifest line: {exc}", file=sys.stderr)
        return 1

    settings = get_settings()
    success, detail = ingest_item(
        meta,
        meta["tenant"],
        meta["source_id"],
        rag=args.rag,
        settings=settings,
    )
    if success:
        print(detail)
        return 0
    print(f"ingest failed: {detail}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
