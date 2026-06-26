from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from path_graph.admin.runner import manifest_lines_to_json
from path_graph.config import get_settings
from path_graph.contracts.schemas import BatchManifestLine


def _inline_manifest_rows(parsed: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in parsed:
        if not isinstance(row, dict):
            raise ValueError("batch_manifest items must be objects")
        line = BatchManifestLine.model_validate(row)
        out = line.model_dump(exclude_none=True)
        if row.get("document_id"):
            out["document_id"] = row["document_id"]
        rows.append(out)
    return rows


def resolve_manifest_json(
    *,
    manifest_key: str = "",
    batch_manifest: str = "",
    settings=None,
) -> str:
    """Return compact JSON array for Argo withParam."""
    key = (manifest_key or os.environ.get("BATCH_MANIFEST_KEY", "")).strip()
    inline = (batch_manifest or os.environ.get("BATCH_MANIFEST", "")).strip()
    if key:
        return manifest_lines_to_json(key, settings=settings or get_settings())
    if inline:
        parsed = json.loads(inline)
        if not isinstance(parsed, list):
            raise ValueError("batch_manifest must be a JSON array")
        rows = _inline_manifest_rows(parsed)
        return json.dumps(rows, separators=(",", ":"))
    raise ValueError("batch_manifest_key or batch_manifest required")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Load batch manifest from S3 key or inline JSON for Argo withParam"
    )
    parser.add_argument("--tenant", required=True)
    parser.add_argument(
        "--manifest-key",
        help="S3 object key (batches/{tenant}/{batch_id}/manifest.jsonl). "
        "Falls back to BATCH_MANIFEST_KEY env.",
    )
    parser.add_argument(
        "--batch-manifest",
        help="Inline JSON array when manifest-key is empty. Falls back to BATCH_MANIFEST env.",
    )
    parser.add_argument(
        "--output",
        default="/tmp/batch_manifest.json",
        help="Write JSON array here for Argo output parameter (default: /tmp/batch_manifest.json)",
    )
    args = parser.parse_args(argv)

    try:
        payload = resolve_manifest_json(
            manifest_key=args.manifest_key or "",
            batch_manifest=args.batch_manifest or "",
        )
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"load batch manifest failed: {exc}", file=sys.stderr)
        return 1

    out_path = args.output
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(payload)
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
