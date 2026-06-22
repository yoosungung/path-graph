from __future__ import annotations

import json

from path_graph.config import Settings, get_settings
from path_graph.contracts.community import CommunityRecord
from path_graph.contracts.s3_keys import s3_key_wiki
from path_graph.contracts.schemas import WikiSynthesizerInput
from path_graph.ids import wiki_slug_for_community
from path_graph.meta.pg import PgMetaStore
from path_graph.steps.agent_invoke import invoke_agent
from path_graph.storage.blob import make_blob_store


def wiki_synthesize(
    tenant: str,
    project: int,
    community_id: str,
    community_level: int,
    graph_context_s3: str,
    batch_id: str,
    session_id: str,
    *,
    skip_agent: bool = False,
) -> dict:
    if skip_agent:
        return {"pages": []}
    inp = WikiSynthesizerInput(
        tenant=tenant,
        project=project,
        community_id=community_id,
        community_level=community_level,
        graph_context_s3=graph_context_s3,
        idempotency_key=f"{batch_id}:{project}:{community_id}",
    )
    return invoke_agent("wiki-synthesizer", inp, session_id)


def store_wiki_pages(
    tenant: str,
    project: int,
    pages: list[dict],
    *,
    community_id: str | None = None,
    batch_id: str | None = None,
    pg: PgMetaStore | None = None,
) -> list[str]:
    store = make_blob_store(get_settings())
    uris: list[str] = []
    for page in pages:
        slug = page["slug"]
        body = page.get("markdown") or page.get("content") or ""
        key = s3_key_wiki(tenant, project, slug)
        uri = store.put_bytes(key, body.encode("utf-8"))
        uris.append(uri)
        if pg:
            pg.upsert_wiki_page(
                tenant,
                project,
                slug,
                uri,
                title=page.get("title"),
                community_id=community_id,
                batch_id=batch_id,
            )
    return uris


def _stub_page_from_context(graph_context_key: str, record: CommunityRecord) -> dict:
    store = make_blob_store(get_settings())
    raw = store.get_bytes(graph_context_key)
    ctx = json.loads(raw)
    entities = ", ".join(e.get("name", "") for e in ctx.get("entities", [])[:10])
    slug = wiki_slug_for_community(record.project, record.level, record.community_id)
    return {
        "slug": slug,
        "title": f"Community L{record.level} ({record.project})",
        "markdown": f"# Community Report\n\nEntities: {entities}\n",
    }


def run_wiki_for_community(
    tenant: str,
    record: CommunityRecord,
    session_id: str,
    *,
    skip_agent: bool = False,
    pg: PgMetaStore | None = None,
) -> dict:
    store = make_blob_store(get_settings())
    ctx_uri = store.uri_for(record.graph_context_key)
    result = wiki_synthesize(
        tenant,
        record.project,
        record.community_id,
        record.level,
        ctx_uri,
        record.batch_id,
        session_id,
        skip_agent=skip_agent,
    )
    pages = result.get("pages") or []
    if not pages and skip_agent:
        pages = [_stub_page_from_context(record.graph_context_key, record)]
    uris = (
        store_wiki_pages(
            tenant,
            record.project,
            pages,
            community_id=record.community_id,
            batch_id=record.batch_id,
            pg=pg,
        )
        if pages
        else []
    )
    return {"agent_result": result, "wiki_uris": uris, "community_id": record.community_id}


def run_wiki_pipeline(
    tenant: str,
    batch_id: str,
    community_records: list[CommunityRecord],
    session_id: str,
    *,
    skip_agent: bool = False,
    pg: PgMetaStore | None = None,
    settings: Settings | None = None,
) -> dict:
    _ = settings or get_settings()
    results = []
    for record in community_records:
        results.append(
            run_wiki_for_community(
                tenant,
                record,
                session_id,
                skip_agent=skip_agent,
                pg=pg,
            )
        )
    return {"communities": results}


def run_wiki_pipeline_legacy(
    tenant: str,
    batch_id: str,
    chunks_key: str,
    session_id: str,
    *,
    skip_agent: bool = False,
) -> dict:
    """Deprecated: chunks-based wiki. Use run_wiki_pipeline with community records."""
    from path_graph.steps.community_pipeline import run_community_pipeline_for_project
    from path_graph.graph.chunk_partition import partition_chunks_by_project

    settings = get_settings()
    project_chunks = partition_chunks_by_project(
        tenant, batch_id, chunks_key, settings.path_graph_projects_per_tenant
    )
    all_records: list[CommunityRecord] = []
    nebula = None
    from path_graph.graph.chunk_partition import make_nebula_store

    nebula = make_nebula_store(settings)
    for project, key in project_chunks.items():
        comm = run_community_pipeline_for_project(
            tenant, project, batch_id, key, nebula=nebula, settings=settings
        )
        all_records.extend(comm.get("records") or [])
    return run_wiki_pipeline(
        tenant, batch_id, all_records, session_id, skip_agent=skip_agent
    )
