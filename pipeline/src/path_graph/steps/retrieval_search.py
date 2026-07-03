"""CLI for project-scoped hybrid retrieval (local E2E / debugging)."""

from __future__ import annotations

import argparse
import json
import sys

from path_graph.admin.retrieval import api_search_project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hybrid PG FTS + pgvector search for a Knowledge Project"
    )
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    try:
        payload = api_search_project(
            args.tenant,
            args.project_id,
            args.query,
            top_k=args.top_k,
        )
    except ValueError as exc:
        print(f"retrieval failed: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(
        f"query={payload['query']!r} project={payload['project_slug']} "
        f"hits={len(payload['results'])}"
    )
    for rank, row in enumerate(payload["results"], start=1):
        chunk_id = row.get("chunk_id") or row.get("id") or "?"
        score = row.get("rrf_score", 0.0)
        text = str(row.get("text") or row.get("content") or "")
        snippet = text.replace("\n", " ")[:120]
        print(f"{rank}. {chunk_id} rrf={score:.4f} {snippet!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
