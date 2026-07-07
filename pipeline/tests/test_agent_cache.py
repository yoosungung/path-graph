"""Agent output S3 cache — skip re-invoke on graphrag retry."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from path_graph.contracts.s3_keys import (
    s3_key_graph_extract,
    s3_key_graph_extract_meta,
    s3_key_wiki_agent,
    s3_key_wiki_agent_meta,
)
from path_graph.steps.agent_cache import (
    load_or_invoke_graph_semantic,
    load_or_invoke_wiki_synthesize,
)
from path_graph.storage.blob import LocalBlobStore, write_jsonl

SEMANTIC = {
    "entities": [{"id": "entity:A", "name": "A"}],
    "edges": [],
}

WIKI_RESULT = {
    "pages": [{"slug": "page-1", "title": "T", "markdown": "# T\n"}],
}


def test_graph_cache_hit_skips_invoke(local_store):
    store = LocalBlobStore(local_store)
    chunks_key = "chunks/dev/proj/b1/chunks.jsonl"
    write_jsonl(chunks_key, [{"chunk_id": "c1", "text": "hello"}], store)

    extract_key = s3_key_graph_extract("dev", "proj-id", "b1")
    meta_key = s3_key_graph_extract_meta("dev", "proj-id", "b1")
    chunks_sha = store.get_bytes(chunks_key)
    from path_graph.ids import sha256_bytes

    store.put_bytes(extract_key, json.dumps(SEMANTIC).encode())
    store.put_bytes(
        meta_key,
        json.dumps(
            {
                "chunks_key": chunks_key,
                "chunks_sha256": sha256_bytes(chunks_sha),
                "output_schema": "graph_v1",
                "agent": "graph-extractor",
            }
        ).encode(),
    )

    with patch("path_graph.steps.agent_cache.invoke_agent") as mock_invoke:
        out = load_or_invoke_graph_semantic(
            "dev",
            "proj-id",
            "b1",
            chunks_key,
            "sess",
            store=store,
        )

    assert out == SEMANTIC
    mock_invoke.assert_not_called()


def test_graph_cache_miss_when_chunks_changed(local_store):
    store = LocalBlobStore(local_store)
    chunks_key = "chunks/dev/proj/b1/chunks.jsonl"
    write_jsonl(chunks_key, [{"chunk_id": "c1", "text": "hello"}], store)

    extract_key = s3_key_graph_extract("dev", "proj-id", "b1")
    meta_key = s3_key_graph_extract_meta("dev", "proj-id", "b1")
    store.put_bytes(extract_key, json.dumps(SEMANTIC).encode())
    store.put_bytes(
        meta_key,
        json.dumps(
            {
                "chunks_key": chunks_key,
                "chunks_sha256": "stale-hash",
                "output_schema": "graph_v1",
                "agent": "graph-extractor",
            }
        ).encode(),
    )

    with patch(
        "path_graph.steps.agent_cache.invoke_agent", return_value=SEMANTIC
    ) as mock_invoke:
        out = load_or_invoke_graph_semantic(
            "dev",
            "proj-id",
            "b1",
            chunks_key,
            "sess",
            store=store,
        )

    assert out == SEMANTIC
    mock_invoke.assert_called_once()
    assert store.exists(extract_key)


def test_graph_force_agent_bypasses_cache(local_store):
    store = LocalBlobStore(local_store)
    chunks_key = "chunks/dev/proj/b1/chunks.jsonl"
    write_jsonl(chunks_key, [{"chunk_id": "c1", "text": "hello"}], store)
    extract_key = s3_key_graph_extract("dev", "proj-id", "b1")
    store.put_bytes(extract_key, json.dumps({"entities": [], "edges": []}).encode())

    with patch(
        "path_graph.steps.agent_cache.invoke_agent", return_value=SEMANTIC
    ) as mock_invoke:
        out = load_or_invoke_graph_semantic(
            "dev",
            "proj-id",
            "b1",
            chunks_key,
            "sess",
            store=store,
            force_agent=True,
        )

    assert out == SEMANTIC
    mock_invoke.assert_called_once()


def test_wiki_cache_hit_skips_invoke(local_store):
    store = LocalBlobStore(local_store)
    ctx_key = "graph_context/dev/proj/b1/comm-1.json"
    store.put_bytes(ctx_key, json.dumps({"entities": []}).encode())
    wiki_key = s3_key_wiki_agent("dev", "proj-id", "b1", "comm-1")
    meta_key = s3_key_wiki_agent_meta("dev", "proj-id", "b1", "comm-1")
    from path_graph.ids import sha256_bytes

    ctx_sha = sha256_bytes(store.get_bytes(ctx_key))
    store.put_bytes(wiki_key, json.dumps(WIKI_RESULT).encode())
    store.put_bytes(
        meta_key,
        json.dumps(
            {
                "graph_context_key": ctx_key,
                "graph_context_sha256": ctx_sha,
                "agent": "wiki-synthesizer",
            }
        ).encode(),
    )

    with patch("path_graph.steps.agent_cache.invoke_agent") as mock_invoke:
        out = load_or_invoke_wiki_synthesize(
            "dev",
            "proj-id",
            "slug",
            "comm-1",
            0,
            ctx_key,
            "b1",
            "sess",
            store=store,
        )

    assert out == WIKI_RESULT
    mock_invoke.assert_not_called()
