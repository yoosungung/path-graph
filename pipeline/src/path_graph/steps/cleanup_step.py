"""Argo / CLI entrypoint for artifact cleanup."""

from __future__ import annotations

import argparse
import json
import sys

from path_graph.config import get_settings
from path_graph.lifecycle.artifact_cleanup import artifact_cleanup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Temp artifact cleanup")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--project-id", default="")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    result = artifact_cleanup(
        args.tenant,
        args.project_id or None,
        dry_run=not args.execute,
        settings=get_settings(),
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
