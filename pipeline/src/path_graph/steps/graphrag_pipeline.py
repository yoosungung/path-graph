from __future__ import annotations

from path_graph.admin.downstream import apply_graphrag_success
from path_graph.config import get_settings
from path_graph.graph.chunk_partition import make_nebula_store
from path_graph.meta.pg import PgMetaStore
from path_graph.steps.community_pipeline import run_community_pipeline
from path_graph.steps.graph_pipeline import run_graph_pipeline
from path_graph.steps.wiki_pipeline import run_wiki_pipeline


def run_graphrag_pipeline(
    tenant: str,
    project_id: str,
    project_slug: str,
    batch_id: str,
    chunks_key: str,
    session_id: str,
    *,
    skip_agent: bool = False,
    force_agent: bool = False,
) -> dict:
    settings = get_settings()
    nebula = make_nebula_store(settings)
    pg = PgMetaStore(settings.path_graph_dsn) if settings.path_graph_dsn else None

    graph_result = run_graph_pipeline(
        tenant,
        project_id,
        project_slug,
        batch_id,
        chunks_key,
        session_id,
        skip_agent=skip_agent,
        force_agent=force_agent,
        nebula=nebula,
        pg=pg,
    )
    project_chunks = graph_result["project_chunks"]
    community_results = run_community_pipeline(
        tenant,
        batch_id,
        project_chunks,
        project_slug,
        nebula=nebula,
        settings=settings,
        pg=pg,
        batch_entity_ids_by_project=graph_result.get("batch_entity_ids"),
    )
    all_records = []
    for comm in community_results:
        all_records.extend(comm.get("records") or [])

    wiki_result = run_wiki_pipeline(
        tenant,
        batch_id,
        all_records,
        session_id,
        skip_agent=skip_agent,
        force_agent=force_agent,
        pg=pg,
        settings=settings,
    )
    if settings.path_graph_dsn:
        apply_graphrag_success(tenant, project_id, batch_id, settings=settings)
    return {
        "graph": graph_result,
        "communities": community_results,
        "wiki": wiki_result,
    }
