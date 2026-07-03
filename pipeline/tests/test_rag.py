from unittest.mock import MagicMock, patch

from path_graph.contracts.schemas import ChunkRecord
from path_graph.meta.pg import PgMetaStore
from constants import PROJECT_ID


@patch.object(PgMetaStore, "_register_vector")
@patch("path_graph.meta.pg.psycopg.connect")
def test_upsert_chunks_with_embeddings(mock_connect, _mock_register):
    conn = MagicMock()
    mock_connect.return_value.__enter__ = MagicMock(return_value=conn)
    mock_connect.return_value.__exit__ = MagicMock(return_value=False)
    pg = PgMetaStore("postgresql://localhost/test")
    chunk = ChunkRecord(
        chunk_id="00000000-0000-0000-0000-000000000011",
        document_id="00000000-0000-0000-0000-000000000010",
        tenant="dev",
        project_id=PROJECT_ID,
        chunk_index=0,
        text="hello",
        text_hash="h",
    )
    pg.upsert_chunks("dev", [chunk], "s3://b/k", embeddings=[[0.1] * 1024])
    conn.execute.assert_called()
    sql = conn.execute.call_args[0][0]
    assert "embedding" in sql


@patch.object(PgMetaStore, "_register_vector")
@patch("path_graph.meta.pg.psycopg.connect")
def test_search_vector_returns_rows(mock_connect, _mock_register):
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        ("chunk-1", "doc-1", PROJECT_ID, "hello", 0.9),
    ]
    mock_connect.return_value.__enter__ = MagicMock(return_value=conn)
    mock_connect.return_value.__exit__ = MagicMock(return_value=False)
    pg = PgMetaStore("postgresql://localhost/test")
    rows = pg.search_vector("dev", PROJECT_ID, [0.1] * 1024, limit=5)
    assert rows[0]["chunk_id"] == "chunk-1"
    assert rows[0]["text"] == "hello"


@patch("path_graph.steps.rag_index.embed_chunks")
@patch("path_graph.steps.rag_index.PgMetaStore")
def test_index_rag_upserts_embeddings(mock_pg_cls, mock_embed, tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("PATH_GRAPH_DSN", "postgresql://localhost/test")

    from path_graph.storage.blob import write_jsonl, make_blob_store
    from path_graph.contracts.s3_keys import s3_key_chunks
    from path_graph.steps.rag_index import index_rag_for_document

    doc_id = "00000000-0000-0000-0000-000000000010"
    key = s3_key_chunks("dev", doc_id)
    line = ChunkRecord(
        chunk_id="00000000-0000-0000-0000-000000000011",
        document_id=doc_id,
        tenant="dev",
        project_id=PROJECT_ID,
        chunk_index=0,
        text="t",
        text_hash="h",
    ).model_dump()
    write_jsonl(key, [line], make_blob_store())

    mock_embed.return_value = [[0.1] * 1024]
    mock_pg = MagicMock()
    mock_pg_cls.return_value = mock_pg

    n = index_rag_for_document("dev", key, doc_id, "default")
    assert n == 1
    mock_pg.upsert_chunks.assert_called_once()
    assert mock_pg.upsert_chunks.call_args.kwargs["embeddings"] == [[0.1] * 1024]
    mock_pg.mark_rag_indexed.assert_called_once()
