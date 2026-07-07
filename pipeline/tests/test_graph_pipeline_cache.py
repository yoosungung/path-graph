"""Graph pipeline uses cached graph-extractor output on retry."""

from __future__ import annotations

import json
from unittest.mock import patch

from path_graph.contracts.s3_keys import s3_key_graph_extract, s3_key_graph_extract_meta
from path_graph.graph.nebula_store import NebulaGraphStore
from path_graph.ids import sha256_bytes
from path_graph.steps.graph_pipeline import run_graph_pipeline
from path_graph.storage.blob import LocalBlobStore, write_jsonl

from constants import PROJECT_ID

SEMANTIC = {
    "entities": [
        {"id": "entity:A", "name": "A"},
        {"id": "entity:B", "name": "B"},
    ],
    "edges": [
        {"type": "EXTRACTED", "source": "entity:A", "target": "entity:B", "confidence": 1.0},
    ],
}


def test_graph_pipeline_reuses_cached_semantic_without_invoke(local_store, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(local_store))
    from path_graph.config import get_settings

    get_settings.cache_clear()

    store = LocalBlobStore(local_store)
    chunks_key = "chunks/dev/doc/chunks.jsonl"
    write_jsonl(chunks_key, [{"chunk_id": "c1", "text": "plain text"}], store)
    project_chunks = f"chunks/dev/{PROJECT_ID}/b-cache/chunks.jsonl"
    write_jsonl(project_chunks, [{"chunk_id": "c1", "text": "plain text"}], store)

    extract_key = s3_key_graph_extract("dev", PROJECT_ID, "b-cache")
    meta_key = s3_key_graph_extract_meta("dev", PROJECT_ID, "b-cache")
    store.put_bytes(extract_key, json.dumps(SEMANTIC).encode())
    store.put_bytes(
        meta_key,
        json.dumps(
            {
                "chunks_key": project_chunks,
                "chunks_sha256": sha256_bytes(store.get_bytes(project_chunks)),
                "output_schema": "graph_v1",
                "agent": "graph-extractor",
            }
        ).encode(),
    )

    memory: dict = {}
    nebula = NebulaGraphStore("h", 9669, "root", "pw", memory=memory)

    with (
        patch(
            "path_graph.graph.chunk_partition.copy_chunks_to_project_batch",
            return_value=project_chunks,
        ),
        patch("path_graph.steps.graph_pipeline.make_nebula_store", return_value=nebula),
        patch("path_graph.steps.agent_cache.invoke_agent") as mock_invoke,
    ):
        run_graph_pipeline(
            "dev",
            PROJECT_ID,
            "default",
            "b-cache",
            chunks_key,
            "sess",
        )

    mock_invoke.assert_not_called()
    space = memory["path_graph_dev_default"]
    assert len(space.entities) == 2
    assert len(space.edges) == 1
