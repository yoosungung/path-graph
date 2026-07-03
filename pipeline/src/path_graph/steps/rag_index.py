from __future__ import annotations

from path_graph.config import get_settings
from path_graph.meta.pg import PgMetaStore
from path_graph.rag.embed import embed_chunks
from path_graph.storage.blob import read_jsonl, make_blob_store
from path_graph.contracts.schemas import ChunkRecord


def index_rag_for_document(
    tenant: str,
    chunks_key: str,
    document_id: str,
    project_slug: str,
    *,
    skip_pg: bool = False,
) -> int:
    settings = get_settings()
    if not skip_pg and not settings.path_graph_dsn:
        raise ValueError("PATH_GRAPH_DSN is required for RAG index")
    store = make_blob_store(settings)
    lines = read_jsonl(store, chunks_key)
    chunks = [ChunkRecord.model_validate(line) for line in lines]
    if not chunks:
        return 0

    vectors = embed_chunks(chunks, settings)

    if not skip_pg:
        pg = PgMetaStore(settings.path_graph_dsn)
        pg.upsert_chunks(
            tenant,
            chunks,
            store.uri_for(chunks_key),
            embeddings=vectors,
        )
        pg.mark_rag_indexed(tenant, document_id)

    return len(chunks)
