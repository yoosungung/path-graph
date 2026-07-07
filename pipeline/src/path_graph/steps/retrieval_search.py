"""CLI for project-scoped unified knowledge retrieval."""

from __future__ import annotations

import argparse
import json
import sys

from path_graph.admin.retrieval import api_search_project
from path_graph.retrieval.contracts import SearchMode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Unified wiki/graph/vector knowledge search for a Knowledge Project"
    )
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--mode",
        choices=[m.value for m in SearchMode],
        default=SearchMode.auto.value,
    )
    parser.add_argument("--include-graph", action="store_true")
    parser.add_argument("--sub-query", action="append", dest="sub_queries", default=[])
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    try:
        payload = api_search_project(
            args.tenant,
            args.project_id,
            args.query,
            top_k=args.top_k,
            mode=args.mode,
            include_graph=args.include_graph,
            sub_queries=args.sub_queries or None,
        )
    except ValueError as exc:
        print(f"retrieval failed: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    hits = payload.get("hits") or payload.get("results") or []
    print(
        f"query={payload['query']!r} mode={payload.get('mode_resolved', args.mode)} "
        f"project={payload['project_slug']} hits={len(hits)}"
    )
    for rank, row in enumerate(hits, start=1):
        hit_id = row.get("id") or "?"
        kind = row.get("kind") or "chunk"
        score = row.get("rrf_score") or row.get("score") or 0.0
        text = str(row.get("text") or "")
        snippet = text.replace("\n", " ")[:120]
        print(f"{rank}. [{kind}] {hit_id} score={score:.4f} {snippet!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
