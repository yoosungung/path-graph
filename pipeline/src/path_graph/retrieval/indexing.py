"""Wiki / entity search index helpers."""

from __future__ import annotations

from typing import Any

from path_graph.config import Settings, get_settings
from path_graph.meta.pg import PgMetaStore
from path_graph.rag.embed import EmbeddingClient


def _search_text(title: str | None, body: str) -> str:
    parts = []
    if title and title.strip():
        parts.append(title.strip())
    if body.strip():
        parts.append(body.strip())
    return "\n".join(parts)


def index_wiki_page(
    pg: PgMetaStore,
    *,
    tenant: str,
    project_id: str,
    slug: str,
    title: str | None,
    body: str,
    vfs_path: str,
    community_id: str | None = None,
    batch_id: str | None = None,
    settings: Settings | None = None,
) -> None:
    s = settings or get_settings()
    embedding = None
    text = _search_text(title, body)
    if text and s.embedding_base_url:
        embedder = EmbeddingClient(s)
        embedding = embedder.embed([text[:8000]])[0]
    pg.upsert_wiki_page(
        tenant,
        project_id,
        slug,
        title=title,
        community_id=community_id,
        batch_id=batch_id,
        vfs_path=vfs_path,
        body_text=body,
        embedding=embedding,
    )


def sync_entities_to_pg(
    pg: PgMetaStore,
    *,
    tenant: str,
    project_id: str,
    entities: list[dict[str, Any]],
    settings: Settings | None = None,
) -> None:
    if not entities:
        return
    s = settings or get_settings()
    texts = [
        f"{ent.get('name', '')}\n{ent.get('description', '')}".strip()
        for ent in entities
    ]
    embeddings = None
    if s.embedding_base_url and any(texts):
        embedder = EmbeddingClient(s)
        embeddings = embedder.embed([t[:8000] or " " for t in texts])
    pg.upsert_entities(
        tenant,
        project_id,
        entities,
        embeddings=embeddings,
    )
