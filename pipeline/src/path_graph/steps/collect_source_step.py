from __future__ import annotations

import argparse
import os
import sys

from path_graph.contracts.source import CollectSyncMode
from path_graph.admin.runner import collect_source, resolve_settings_from_env
from path_graph.admin.sources import SourceStore
from path_graph.config import get_settings


def _platform_env(driver) -> tuple[str, str, str]:
    from path_graph.contracts.source import SourceDriver

    if driver == SourceDriver.GDRIVE:
        return (
            os.environ.get("GDRIVE_CLIENT_ID", os.environ.get("PIPELINE_GDRIVE_CLIENT_ID", "")),
            os.environ.get("GDRIVE_CLIENT_SECRET", os.environ.get("PIPELINE_GDRIVE_CLIENT_SECRET", "")),
            "",
        )
    return (
        os.environ.get("MS_CLIENT_ID", os.environ.get("PIPELINE_MS_CLIENT_ID", "")),
        os.environ.get("MS_CLIENT_SECRET", os.environ.get("PIPELINE_MS_CLIENT_SECRET", "")),
        os.environ.get("MS_TENANT_ID", os.environ.get("PIPELINE_MS_TENANT_ID", "")),
    )


def run_collect(
    *,
    tenant: str,
    source_pg_id: str,
    batch_id: str = "",
    sync_mode: str = "",
    output_dir: str = "/tmp",
) -> dict[str, str | int]:
    settings = get_settings()
    dsn = settings.path_graph_dsn
    if not dsn:
        raise ValueError("PATH_GRAPH_DSN not configured")

    store = SourceStore(dsn)
    profile = store.get_source(tenant, source_pg_id)
    if profile is None:
        raise ValueError(f"source not found: {source_pg_id}")
    if not profile.enabled:
        raise ValueError("source is disabled")

    client_id, client_secret, ms_tenant_id = _platform_env(profile.driver)
    pg_settings = resolve_settings_from_env(
        profile,
        dsn=dsn,
        platform_client_id=client_id,
        platform_client_secret=client_secret,
        platform_ms_tenant_id=ms_tenant_id,
        settings=settings,
    )
    collected = collect_source(
        profile,
        batch_id=batch_id or None,
        settings=pg_settings,
        sync_mode=CollectSyncMode(sync_mode) if sync_mode else None,
    )
    out = {
        "batch_id": collected["batch_id"],
        "manifest_key": collected["manifest_key"],
        "file_count": collected["file_count"],
        "sync_mode": collected.get("sync_mode", ""),
    }
    if collected.get("delta_link"):
        out["delta_link"] = collected["delta_link"]
    os.makedirs(output_dir, exist_ok=True)
    for key, filename in (
        ("batch_id", "batch_id"),
        ("manifest_key", "manifest_key"),
        ("file_count", "file_count"),
        ("sync_mode", "sync_mode"),
    ):
        if key not in out:
            continue
        path = os.path.join(output_dir, filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(str(out[key]))
    if out.get("delta_link"):
        path = os.path.join(output_dir, "delta_link")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(str(out["delta_link"]))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect source files and write batch manifest (Argo step)")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--source-id", required=True, help="path_graph.sources.id (UUID)")
    parser.add_argument("--batch-id", default="", help="Optional batch id (default: UTC timestamp)")
    parser.add_argument(
        "--sync-mode",
        default="",
        choices=["", "delta", "full"],
        help="Override source sync_mode (default: source config or delta)",
    )
    parser.add_argument(
        "--output-dir",
        default="/tmp",
        help="Write batch_id, manifest_key, file_count files for Argo outputs",
    )
    args = parser.parse_args(argv)

    try:
        result = run_collect(
            tenant=args.tenant,
            source_pg_id=args.source_id,
            batch_id=args.batch_id,
            sync_mode=args.sync_mode,
            output_dir=args.output_dir,
        )
    except ValueError as exc:
        print(f"collect failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"collect failed: {exc}", file=sys.stderr)
        return 2

    print(result["manifest_key"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
