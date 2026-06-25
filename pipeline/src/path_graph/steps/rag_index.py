from __future__ import annotations

from path_graph.config import get_settings
from path_graph.meta.pg import PgMetaStore
from path_graph.rag.embed import embed_chunks
from path_graph.rag.qdrant_store import make_qdrant_store
from path_graph.storage.blob import read_jsonl, make_blob_store
from path_graph.contracts.schemas import ChunkRecord


def index_rag_for_document(
    tenant: str,
    chunks_key: str,
    document_id: str,
    project_slug: str,
    *,
    skip_pg: bool = False,
    skip_qdrant: bool = False,
) -> int:
    settings = get_settings()
    store = make_blob_store(settings)
    lines = read_jsonl(store, chunks_key)
    chunks = [ChunkRecord.model_validate(line) for line in lines]
    if not chunks:
        return 0

    vectors = embed_chunks(chunks, settings)

    if not skip_qdrant:
        qdrant = make_qdrant_store(settings)
        payloads = [
            {
                "tenant": c.tenant,
                "project_id": c.project_id,
                "document_id": c.document_id,
                "chunk_id": c.chunk_id,
                "chunk_index": c.chunk_index,
                "heading_path": c.heading_path,
                "s3_chunk_uri": store.uri_for(chunks_key),
            }
            for c in chunks
        ]
        qdrant.upsert_chunks(
            tenant,
            project_slug,
            [c.chunk_id for c in chunks],
            vectors,
            payloads,
        )

    if not skip_pg and settings.path_graph_dsn:
        pg = PgMetaStore(settings.path_graph_dsn)
        pg.upsert_chunks(tenant, chunks, store.uri_for(chunks_key))
        pg.mark_rag_indexed(tenant, document_id)

    return len(chunks)
