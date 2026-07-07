from __future__ import annotations

import json

from path_graph.config import Settings, get_settings
from path_graph.contracts.community import CommunityRecord
from path_graph.ids import wiki_path_for_community
from path_graph.meta.pg import PgMetaStore
from path_graph.steps.agent_cache import load_or_invoke_wiki_synthesize
from path_graph.storage.blob import make_blob_store
from path_graph.storage.wiki_vfs import write_wiki_page


def wiki_synthesize(
    tenant: str,
    project_id: str,
    project_slug: str,
    community_id: str,
    community_level: int,
    graph_context_key: str,
    batch_id: str,
    session_id: str,
    *,
    skip_agent: bool = False,
    force_agent: bool = False,
) -> dict:
    if skip_agent:
        return {"pages": []}
    return load_or_invoke_wiki_synthesize(
        tenant,
        project_id,
        project_slug,
        community_id,
        community_level,
        graph_context_key,
        batch_id,
        session_id,
        force_agent=force_agent,
    )


def store_wiki_pages(
    tenant: str,
    project_id: str,
    pages: list[dict],
    *,
    community_id: str | None = None,
    community_level: int | None = None,
    batch_id: str | None = None,
    pg: PgMetaStore | None = None,
) -> list[str]:
    paths: list[str] = []
    for page in pages:
        title = page.get("title") or "Community Report"
        if community_id is not None and community_level is not None:
            slug = wiki_path_for_community(community_level, title, community_id)
        else:
            slug = page.get("slug") or wiki_path_for_community(0, title, community_id or "")
        body = page.get("markdown") or page.get("content") or ""
        vfs_path = write_wiki_page(tenant, project_id, slug, body)
        paths.append(vfs_path)
        if pg:
            pg.upsert_wiki_page(
                tenant,
                project_id,
                slug,
                title=title,
                community_id=community_id,
                batch_id=batch_id,
            )
    return paths


def _stub_page_from_context(graph_context_key: str, record: CommunityRecord) -> dict:
    store = make_blob_store(get_settings())
    raw = store.get_bytes(graph_context_key)
    ctx = json.loads(raw)
    entities = ", ".join(e.get("name", "") for e in ctx.get("entities", [])[:10])
    title = f"Community L{record.level} ({record.project_slug})"
    return {
        "title": title,
        "markdown": f"# Community Report\n\nEntities: {entities}\n",
    }


def run_wiki_for_community(
    tenant: str,
    record: CommunityRecord,
    session_id: str,
    *,
    skip_agent: bool = False,
    force_agent: bool = False,
    pg: PgMetaStore | None = None,
) -> dict:
    result = wiki_synthesize(
        tenant,
        record.project_id,
        record.project_slug,
        record.community_id,
        record.level,
        record.graph_context_key,
        record.batch_id,
        session_id,
        skip_agent=skip_agent,
        force_agent=force_agent,
    )
    pages = result.get("pages") or []
    if not pages and skip_agent:
        pages = [_stub_page_from_context(record.graph_context_key, record)]
    paths = (
        store_wiki_pages(
            tenant,
            record.project_id,
            pages,
            community_id=record.community_id,
            community_level=record.level,
            batch_id=record.batch_id,
            pg=pg,
        )
        if pages
        else []
    )
    return {"agent_result": result, "wiki_paths": paths, "community_id": record.community_id}


def run_wiki_pipeline(
    tenant: str,
    batch_id: str,
    community_records: list[CommunityRecord],
    session_id: str,
    *,
    skip_agent: bool = False,
    force_agent: bool = False,
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
                force_agent=force_agent,
                pg=pg,
            )
        )
    return {"communities": results}
