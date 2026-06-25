"""Argo / CLI entrypoint for index reconcile."""

from __future__ import annotations

import argparse
import json
import sys

from path_graph.config import get_settings
from path_graph.lifecycle.reconcile import reconcile_project_index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile PG vs Qdrant/Nebula")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--project-id", required=True)
    args = parser.parse_args(argv)
    result = reconcile_project_index(
        args.tenant, args.project_id, settings=get_settings()
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
