from __future__ import annotations

from path_graph.meta.pg import PgMetaStore


class TombstoneError(ValueError):
    """Upload or ingest blocked by tombstone."""


def check_tombstone(
    pg: PgMetaStore,
    tenant: str,
    project_id: str,
    content_hash: str,
) -> None:
    if pg.is_tombstoned(tenant, project_id, content_hash):
        raise TombstoneError(
            f"content_hash tombstoned in project {project_id}: {content_hash}"
        )
