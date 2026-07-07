from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from path_graph.config import Settings, get_settings
from path_graph.contracts.s3_keys import (
    s3_key_graph_extract,
    s3_key_graph_extract_meta,
    s3_key_wiki_agent,
    s3_key_wiki_agent_meta,
)
from path_graph.contracts.schemas import (
    GraphExtractorInput,
    WikiSynthesizerInput,
    unwrap_agent_graph_output,
)
from path_graph.ids import sha256_bytes
from path_graph.steps.agent_invoke import invoke_agent
from path_graph.storage.blob import BlobStore, make_blob_store


def artifact_sha256(store: BlobStore, key: str) -> str:
    return sha256_bytes(store.get_bytes(key))


def _load_cached_agent_output(
    store: BlobStore,
    artifact_key: str,
    meta_key: str,
    *,
    validate_meta: dict[str, str],
) -> dict[str, Any] | None:
    if not store.exists(artifact_key) or not store.exists(meta_key):
        return None
    meta = json.loads(store.get_bytes(meta_key))
    for field, expected in validate_meta.items():
        if meta.get(field) != expected:
            return None
    return json.loads(store.get_bytes(artifact_key))


def _write_cached_agent_output(
    store: BlobStore,
    artifact_key: str,
    meta_key: str,
    *,
    payload: dict[str, Any],
    meta: dict[str, Any],
) -> None:
    store.put_bytes(artifact_key, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    body = {
        **meta,
        "created_at": datetime.now(UTC).isoformat(),
    }
    store.put_bytes(meta_key, json.dumps(body, ensure_ascii=False).encode("utf-8"))


def load_or_invoke_graph_semantic(
    tenant: str,
    project_id: str,
    batch_id: str,
    chunks_key: str,
    session_id: str,
    *,
    store: BlobStore | None = None,
    settings: Settings | None = None,
    force_agent: bool = False,
) -> dict[str, Any]:
    s = settings or get_settings()
    blob = store or make_blob_store(s)
    chunks_sha256 = artifact_sha256(blob, chunks_key)
    artifact_key = s3_key_graph_extract(tenant, project_id, batch_id)
    meta_key = s3_key_graph_extract_meta(tenant, project_id, batch_id)

    if not force_agent:
        cached = _load_cached_agent_output(
            blob,
            artifact_key,
            meta_key,
            validate_meta={
                "chunks_key": chunks_key,
                "chunks_sha256": chunks_sha256,
                "output_schema": "graph_v1",
            },
        )
        if cached is not None:
            return cached

    inp = GraphExtractorInput(
        tenant=tenant,
        project_id=project_id,
        batch_id=batch_id,
        chunks_s3=blob.agent_artifact_uri(chunks_key),
        output_schema="graph_v1",
        idempotency_key=f"{batch_id}:{project_id}",
    )
    result = unwrap_agent_graph_output(
        invoke_agent("graph-extractor", inp, session_id, settings=s)
    )
    _write_cached_agent_output(
        blob,
        artifact_key,
        meta_key,
        payload=result,
        meta={
            "chunks_key": chunks_key,
            "chunks_sha256": chunks_sha256,
            "output_schema": "graph_v1",
            "agent": "graph-extractor",
        },
    )
    return result


def load_or_invoke_wiki_synthesize(
    tenant: str,
    project_id: str,
    project_slug: str,
    community_id: str,
    community_level: int,
    graph_context_key: str,
    batch_id: str,
    session_id: str,
    *,
    store: BlobStore | None = None,
    settings: Settings | None = None,
    force_agent: bool = False,
) -> dict[str, Any]:
    s = settings or get_settings()
    blob = store or make_blob_store(s)
    graph_context_sha256 = artifact_sha256(blob, graph_context_key)
    artifact_key = s3_key_wiki_agent(tenant, project_id, batch_id, community_id)
    meta_key = s3_key_wiki_agent_meta(tenant, project_id, batch_id, community_id)

    if not force_agent:
        cached = _load_cached_agent_output(
            blob,
            artifact_key,
            meta_key,
            validate_meta={
                "graph_context_key": graph_context_key,
                "graph_context_sha256": graph_context_sha256,
                "output_schema": "wiki_v1",
            },
        )
        if cached is not None:
            return cached

    inp = WikiSynthesizerInput(
        tenant=tenant,
        project_id=project_id,
        project_slug=project_slug,
        community_id=community_id,
        community_level=community_level,
        graph_context_s3=blob.agent_artifact_uri(graph_context_key),
        idempotency_key=f"{batch_id}:{project_id}:{community_id}",
    )
    result = invoke_agent("wiki-synthesizer", inp, session_id, settings=s)
    _write_cached_agent_output(
        blob,
        artifact_key,
        meta_key,
        payload=result,
        meta={
            "graph_context_key": graph_context_key,
            "graph_context_sha256": graph_context_sha256,
            "output_schema": "wiki_v1",
            "agent": "wiki-synthesizer",
        },
    )
    return result
