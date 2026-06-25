from unittest.mock import MagicMock, patch

from path_graph.contracts.schemas import ChunkRecord
from path_graph.rag.qdrant_store import QdrantStore
from path_graph.config import Settings
from constants import PROJECT_ID


def test_qdrant_upsert_calls_client():
    client = MagicMock()
    client.collection_exists.return_value = True
    store = QdrantStore(client, Settings(embedding_dim=4))
    store.upsert_chunks(
        "dev",
        "default",
        ["id1"],
        [[0.1, 0.2, 0.3, 0.4]],
        [{"tenant": "dev", "project_id": PROJECT_ID, "chunk_id": "id1"}],
    )
    client.upsert.assert_called_once()
    assert client.upsert.call_args.kwargs["collection_name"] == "path_graph_dev_default"


def test_qdrant_upsert_single_collection_per_project():
    client = MagicMock()
    client.collection_exists.return_value = True
    store = QdrantStore(client, Settings(embedding_dim=2))
    store.upsert_chunks(
        "dev",
        "default",
        ["chunk-0", "chunk-1"],
        [[0.1, 0.2], [0.3, 0.4]],
        [
            {"tenant": "dev", "project_id": PROJECT_ID, "chunk_id": "chunk-0"},
            {"tenant": "dev", "project_id": PROJECT_ID, "chunk_id": "chunk-1"},
        ],
    )
    assert client.upsert.call_count == 1
    assert client.upsert.call_args.kwargs["collection_name"] == "path_graph_dev_default"


@patch("path_graph.steps.rag_index.embed_chunks")
@patch("path_graph.steps.rag_index.make_qdrant_store")
def test_index_rag_skips_qdrant(mock_qdrant, mock_embed, tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(tmp_path))
    monkeypatch.delenv("PATH_GRAPH_DSN", raising=False)

    from path_graph.storage.blob import write_jsonl
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
    write_jsonl(key, [line], __import__("path_graph.storage.blob", fromlist=["make_blob_store"]).make_blob_store())

    mock_embed.return_value = [[0.1] * 1024]
    mock_store = MagicMock()
    mock_qdrant.return_value = mock_store

    n = index_rag_for_document("dev", key, doc_id, "default", skip_pg=True)
    assert n == 1
    mock_store.upsert_chunks.assert_called_once()
