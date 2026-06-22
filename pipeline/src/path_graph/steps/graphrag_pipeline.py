from __future__ import annotations

from path_graph.config import get_settings
from path_graph.graph.chunk_partition import make_nebula_store
from path_graph.meta.pg import PgMetaStore
from path_graph.steps.community_pipeline import run_community_pipeline
from path_graph.steps.graph_pipeline import run_graph_pipeline
from path_graph.steps.wiki_pipeline import run_wiki_pipeline


def run_graphrag_pipeline(
    tenant: str,
    batch_id: str,
    chunks_key: str,
    session_id: str,
    *,
    skip_agent: bool = False,
) -> dict:
    settings = get_settings()
    nebula = make_nebula_store(settings)
    pg = PgMetaStore(settings.path_graph_dsn) if settings.path_graph_dsn else None

    graph_result = run_graph_pipeline(
        tenant,
        batch_id,
        chunks_key,
        session_id,
        skip_agent=skip_agent,
        nebula=nebula,
    )
    project_chunks = graph_result["project_chunks"]
    community_results = run_community_pipeline(
        tenant,
        batch_id,
        project_chunks,
        nebula=nebula,
        settings=settings,
        pg=pg,
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
        pg=pg,
        settings=settings,
    )
    return {
        "graph": graph_result,
        "communities": community_results,
        "wiki": wiki_result,
    }
