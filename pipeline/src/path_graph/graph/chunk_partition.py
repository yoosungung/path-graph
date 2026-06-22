from __future__ import annotations

from collections import defaultdict

from path_graph.config import Settings, get_settings
from path_graph.contracts.s3_keys import s3_key_chunks_project_batch
from path_graph.graph.nebula_store import NebulaGraphStore
from path_graph.ids import nebula_space_for_chunk, tenant_project_index
from path_graph.storage.blob import make_blob_store, read_jsonl, write_jsonl


def partition_chunks_by_project(
    tenant: str,
    batch_id: str,
    chunks_key: str,
    project_count: int,
    *,
    settings: Settings | None = None,
) -> dict[int, str]:
    """Split batch chunks.jsonl into per-project artifacts."""
    s = settings or get_settings()
    store = make_blob_store(s)
    lines = read_jsonl(store, chunks_key)
    by_project: dict[int, list[dict]] = defaultdict(list)
    for line in lines:
        chunk_id_value = line["chunk_id"]
        project = tenant_project_index(chunk_id_value, project_count)
        by_project[project].append(line)

    keys: dict[int, str] = {}
    for project, project_lines in by_project.items():
        key = s3_key_chunks_project_batch(tenant, project, batch_id)
        write_jsonl(key, project_lines, store)
        keys[project] = key
    return keys


def make_nebula_store(settings: Settings | None = None) -> NebulaGraphStore:
    s = settings or get_settings()
    return NebulaGraphStore(
        s.nebula_host,
        s.nebula_port,
        s.nebula_user,
        s.nebula_password,
    )
