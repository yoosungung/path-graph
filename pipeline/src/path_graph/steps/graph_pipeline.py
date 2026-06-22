from __future__ import annotations

from collections import defaultdict

from path_graph.config import get_settings
from path_graph.contracts.schemas import GraphExtractorInput
from path_graph.graph.chunk_partition import make_nebula_store, partition_chunks_by_project
from path_graph.graph.nebula_store import NebulaGraphStore
from path_graph.ids import nebula_space_for_chunk
from path_graph.steps.agent_invoke import extract_wikilinks, invoke_agent
from path_graph.storage.blob import make_blob_store, read_jsonl


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
    project: int,
    batch_id: str,
    chunks_s3: str,
    session_id: str,
) -> dict:
    inp = GraphExtractorInput(
        tenant=tenant,
        project=project,
        batch_id=batch_id,
        chunks_s3=chunks_s3,
        output_schema="graph_v1",
        idempotency_key=f"{batch_id}:{project}",
    )
    return invoke_agent("graph-extractor", inp, session_id)


def _entity_id(name: str) -> str:
    return f"entity:{name}"


def _upsert_semantic_edges(
    nebula: NebulaGraphStore,
    space: str,
    semantic: dict,
    chunk_id_by_entity: dict[str, str],
) -> None:
    entities = semantic.get("entities") or []
    if entities:
        nebula.upsert_entities(space, entities)

    edges = semantic.get("edges") or []
    entity_edges: list[dict] = []
    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if not src or not tgt:
            continue
        if not str(src).startswith("entity:"):
            src = _entity_id(str(src))
        if not str(tgt).startswith("entity:"):
            tgt = _entity_id(str(tgt))
        entity_edges.append(
            {
                "type": edge.get("type", "EXTRACTED"),
                "source": src,
                "target": tgt,
                "confidence": edge.get("confidence", 1.0),
                "description": edge.get("description", ""),
            }
        )
    if entity_edges:
        nebula.upsert_edges(space, entity_edges)


def run_graph_pipeline_for_project(
    tenant: str,
    project: int,
    batch_id: str,
    chunks_key: str,
    session_id: str,
    *,
    skip_agent: bool = False,
    nebula: NebulaGraphStore | None = None,
) -> dict:
    settings = get_settings()
    store = make_blob_store(settings)
    nebula = nebula or make_nebula_store(settings)
    project_count = settings.path_graph_projects_per_tenant

    deterministic = graph_extract_deterministic(chunks_key, tenant)
    semantic: dict = {}
    if not skip_agent:
        semantic = graph_extract_semantic(
            tenant, project, batch_id, store.uri_for(chunks_key), session_id
        )

    by_space: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    for line in read_jsonl(store, chunks_key):
        entities = extract_wikilinks(line.get("text") or "")
        if entities:
            chunk_id_value = line["chunk_id"]
            space = nebula_space_for_chunk(tenant, chunk_id_value, project_count)
            by_space[space].append((chunk_id_value, entities))

    for space in by_space:
        nebula.ensure_space(space)
    for space, mentions in by_space.items():
        for chunk_id_value, entities in mentions:
            nebula.upsert_mentions(space, chunk_id_value, entities)
        if semantic:
            _upsert_semantic_edges(nebula, space, semantic, {})

    return {
        "project": project,
        "deterministic": deterministic,
        "semantic": semantic,
    }


def run_graph_pipeline(
    tenant: str,
    batch_id: str,
    chunks_key: str,
    session_id: str,
    *,
    skip_agent: bool = False,
    nebula: NebulaGraphStore | None = None,
) -> dict:
    settings = get_settings()
    project_count = settings.path_graph_projects_per_tenant
    nebula = nebula or make_nebula_store(settings)
    project_chunks = partition_chunks_by_project(
        tenant, batch_id, chunks_key, project_count, settings=settings
    )
    results = []
    for project, pchunks_key in sorted(project_chunks.items()):
        results.append(
            run_graph_pipeline_for_project(
                tenant,
                project,
                batch_id,
                pchunks_key,
                session_id,
                skip_agent=skip_agent,
                nebula=nebula,
            )
        )
    return {"projects": results, "project_chunks": project_chunks}
