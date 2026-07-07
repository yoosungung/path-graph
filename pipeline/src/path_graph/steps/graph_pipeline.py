from __future__ import annotations

from path_graph.config import get_settings
from path_graph.contracts.schemas import unwrap_agent_graph_output
from path_graph.graph.chunk_partition import make_nebula_store
from path_graph.graph.entity_vid import normalize_semantic_graph
from path_graph.graph.nebula_store import NebulaGraphStore
from path_graph.ids import nebula_space_name
from path_graph.steps.agent_cache import load_or_invoke_graph_semantic
from path_graph.steps.agent_invoke import extract_wikilinks
from path_graph.storage.blob import BlobStore, make_blob_store, read_jsonl


def graph_extract_deterministic(chunks_key: str, tenant: str) -> list[dict]:
    store = make_blob_store(get_settings())
    lines = read_jsonl(store, chunks_key)
    edges: list[dict] = []
    for line in lines:
        text = line.get("text") or ""
        chunk_id_value = line.get("chunk_id")
        for target in extract_wikilinks(text):
            edges.append(
                {
                    "type": "EXTRACTED",
                    "source_chunk": chunk_id_value,
                    "target": target,
                    "confidence": 1.0,
                }
            )
    return edges


def graph_extract_semantic(
    tenant: str,
    project_id: str,
    batch_id: str,
    chunks_key: str,
    session_id: str,
    *,
    store: BlobStore | None = None,
    force_agent: bool = False,
) -> dict:
    return load_or_invoke_graph_semantic(
        tenant,
        project_id,
        batch_id,
        chunks_key,
        session_id,
        store=store,
        force_agent=force_agent,
    )


def semantic_batch_entity_ids(semantic: dict) -> set[str] | None:
    """Entity ids from graph-extractor output; None when empty (wikilink fallback)."""
    normalized = normalize_semantic_graph(unwrap_agent_graph_output(semantic))
    ids = {str(ent["id"]) for ent in normalized.get("entities") or []}
    return ids if ids else None


def _upsert_semantic_edges(
    nebula: NebulaGraphStore,
    space: str,
    semantic: dict,
) -> None:
    normalized = normalize_semantic_graph(unwrap_agent_graph_output(semantic))
    entities = normalized.get("entities") or []
    if entities:
        nebula.upsert_entities(space, entities)

    entity_edges = normalized.get("edges") or []
    if entity_edges:
        nebula.upsert_edges(space, entity_edges)


def run_graph_pipeline_for_project(
    tenant: str,
    project_id: str,
    project_slug: str,
    batch_id: str,
    chunks_key: str,
    session_id: str,
    *,
    skip_agent: bool = False,
    force_agent: bool = False,
    nebula: NebulaGraphStore | None = None,
) -> dict:
    settings = get_settings()
    store = make_blob_store(settings)
    nebula = nebula or make_nebula_store(settings)
    space = nebula_space_name(tenant, project_slug)

    deterministic = graph_extract_deterministic(chunks_key, tenant)

    nebula.ensure_space(space)
    for line in read_jsonl(store, chunks_key):
        entities = extract_wikilinks(line.get("text") or "")
        if entities:
            nebula.upsert_mentions(space, line["chunk_id"], entities)

    semantic: dict = {}
    if not skip_agent:
        semantic = graph_extract_semantic(
            tenant,
            project_id,
            batch_id,
            chunks_key,
            session_id,
            store=store,
            force_agent=force_agent,
        )
    if semantic:
        _upsert_semantic_edges(nebula, space, semantic)

    return {
        "project_id": project_id,
        "project_slug": project_slug,
        "deterministic": deterministic,
        "semantic": semantic,
    }


def run_graph_pipeline(
    tenant: str,
    project_id: str,
    project_slug: str,
    batch_id: str,
    chunks_key: str,
    session_id: str,
    *,
    skip_agent: bool = False,
    force_agent: bool = False,
    nebula: NebulaGraphStore | None = None,
) -> dict:
    from path_graph.graph.chunk_partition import copy_chunks_to_project_batch

    settings = get_settings()
    nebula = nebula or make_nebula_store(settings)
    project_chunks_key = copy_chunks_to_project_batch(
        tenant, project_id, batch_id, chunks_key, settings=settings
    )
    result = run_graph_pipeline_for_project(
        tenant,
        project_id,
        project_slug,
        batch_id,
        project_chunks_key,
        session_id,
        skip_agent=skip_agent,
        force_agent=force_agent,
        nebula=nebula,
    )
    batch_entity_ids = semantic_batch_entity_ids(result.get("semantic") or {})
    return {
        "project": result,
        "project_chunks": {project_id: project_chunks_key},
        "batch_entity_ids": {project_id: batch_entity_ids} if batch_entity_ids else {},
    }
