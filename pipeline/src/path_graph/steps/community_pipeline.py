from __future__ import annotations

import json

from path_graph.config import Settings, get_settings
from path_graph.contracts.community import CommunityRecord
from path_graph.contracts.s3_keys import s3_key_communities
from path_graph.graph.chunk_partition import make_nebula_store
from path_graph.graph.community_detector import HierarchicalCluster, detect_communities
from path_graph.graph.graph_context import build_graph_context, graph_context_key_for
from path_graph.graph.nebula_store import NebulaGraphStore
from path_graph.ids import nebula_space_name
from path_graph.meta.pg import PgMetaStore
from path_graph.storage.blob import make_blob_store, read_jsonl, write_jsonl


def clusters_to_records(
    tenant: str,
    project_id: str,
    project_slug: str,
    batch_id: str,
    clusters: list[HierarchicalCluster],
) -> list[CommunityRecord]:
    parent_ids: dict[tuple[int, str], str] = {}
    records: list[CommunityRecord] = []
    for cluster in sorted(clusters, key=lambda c: (c.level, c.cluster_key)):
        parent_community_id = None
        if cluster.parent_cluster_key is not None:
            parent_community_id = parent_ids.get(
                (cluster.level - 1, cluster.parent_cluster_key)
            )
        rec = CommunityRecord.build(
            tenant=tenant,
            project_id=project_id,
            project_slug=project_slug,
            batch_id=batch_id,
            level=cluster.level,
            cluster_key=cluster.cluster_key,
            entity_ids=cluster.entity_ids,
            parent_community_id=parent_community_id,
        )
        parent_ids[(cluster.level, cluster.cluster_key)] = rec.community_id
        records.append(rec)
    return records


def run_community_pipeline_for_project(
    tenant: str,
    project_id: str,
    project_slug: str,
    batch_id: str,
    chunks_key: str,
    *,
    nebula: NebulaGraphStore | None = None,
    settings: Settings | None = None,
    pg: PgMetaStore | None = None,
    batch_entity_ids: set[str] | None = None,
) -> dict:
    s = settings or get_settings()
    store = make_blob_store(s)
    nebula = nebula or make_nebula_store(s)
    space = nebula_space_name(tenant, project_slug)

    lines = read_jsonl(store, chunks_key)
    batch_chunk_ids = {line["chunk_id"] for line in lines}
    edges = nebula.export_project_graph(
        space,
        batch_chunk_ids=batch_chunk_ids,
        batch_entity_ids=batch_entity_ids,
    )
    clusters = detect_communities(
        edges,
        max_cluster_size=s.community_max_cluster_size,
        use_lcc=s.community_use_lcc,
        seed=s.community_seed,
    )
    records = clusters_to_records(tenant, project_id, project_slug, batch_id, clusters)

    comm_key = s3_key_communities(tenant, project_id, batch_id)
    comm_uri = write_jsonl(comm_key, [r.model_dump() for r in records], store)

    context_uris: list[str] = []
    for rec in records:
        ctx = build_graph_context(
            rec,
            nebula,
            max_entities=s.graph_context_max_entities,
        )
        ctx_key = graph_context_key_for(rec)
        ctx_uri = store.put_bytes(ctx_key, json.dumps(ctx, ensure_ascii=False).encode())
        context_uris.append(ctx_uri)

    if pg and records:
        pg.upsert_communities(records, comm_uri)

    return {
        "project_id": project_id,
        "project_slug": project_slug,
        "communities_uri": comm_uri,
        "communities_key": comm_key,
        "community_count": len(records),
        "context_uris": context_uris,
        "records": records,
    }


def run_community_pipeline(
    tenant: str,
    batch_id: str,
    project_chunks: dict[str, str],
    project_slug: str,
    *,
    nebula: NebulaGraphStore | None = None,
    settings: Settings | None = None,
    pg: PgMetaStore | None = None,
    batch_entity_ids_by_project: dict[str, set[str]] | None = None,
) -> list[dict]:
    entity_ids_map = batch_entity_ids_by_project or {}
    results: list[dict] = []
    for project_id in sorted(project_chunks):
        results.append(
            run_community_pipeline_for_project(
                tenant,
                project_id,
                project_slug,
                batch_id,
                project_chunks[project_id],
                nebula=nebula,
                settings=settings,
                pg=pg,
                batch_entity_ids=entity_ids_map.get(project_id),
            )
        )
    return results
