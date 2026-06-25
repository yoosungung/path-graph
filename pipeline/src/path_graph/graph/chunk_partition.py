from __future__ import annotations

from path_graph.config import Settings, get_settings
from path_graph.contracts.s3_keys import s3_key_chunks_project_batch
from path_graph.graph.nebula_store import NebulaGraphStore
from path_graph.storage.blob import make_blob_store, read_jsonl, write_jsonl


def copy_chunks_to_project_batch(
    tenant: str,
    project_id: str,
    batch_id: str,
    chunks_key: str,
    *,
    settings: Settings | None = None,
) -> str:
    """Copy batch chunks.jsonl into project-scoped artifact path."""
    s = settings or get_settings()
    store = make_blob_store(s)
    lines = read_jsonl(store, chunks_key)
    key = s3_key_chunks_project_batch(tenant, project_id, batch_id)
    write_jsonl(key, lines, store)
    return key


def make_nebula_store(settings: Settings | None = None) -> NebulaGraphStore:
    s = settings or get_settings()
    return NebulaGraphStore(
        s.nebula_host,
        s.nebula_port,
        s.nebula_user,
        s.nebula_password,
    )
