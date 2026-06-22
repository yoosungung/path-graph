from unittest.mock import MagicMock, patch

import httpx
import pytest

from path_graph.config import Settings
from path_graph.rag.embed import EmbeddingClient, embed_chunks
from path_graph.contracts.schemas import ChunkRecord


def test_embedding_defaults():
    fields = Settings.model_fields
    assert fields["embedding_model"].default == "BAAI/bge-m3"
    assert fields["embedding_dim"].default == 1024
    assert fields["embedding_batch_size"].default == 8
    assert "bge-m3-tei" in fields["embedding_base_url"].default


@patch("path_graph.rag.embed.httpx.Client")
def test_embedding_client_openai_api(mock_client_cls):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": [
            {"index": 0, "embedding": [0.1] * 1024},
            {"index": 1, "embedding": [0.2] * 1024},
        ]
    }
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp
    mock_client_cls.return_value = mock_client

    s = Settings(
        embedding_base_url="http://bge-m3-tei.llm-serving.svc.cluster.local:8080",
        embedding_model="BAAI/bge-m3",
        embedding_dim=1024,
    )
    vecs = EmbeddingClient(s).embed(["hello", "world"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 1024
    mock_client.post.assert_called_once()
    call = mock_client.post.call_args
    assert call.args[0].endswith("/v1/embeddings")
    assert call.kwargs["json"]["model"] == "BAAI/bge-m3"
    assert call.kwargs["json"]["input"] == ["hello", "world"]


@patch("path_graph.rag.embed.httpx.Client")
def test_embedding_client_splits_large_batches(mock_client_cls):
    dim = 4

    def make_resp(batch_texts: list[str]):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"index": i, "embedding": [float(i)] * dim} for i in range(len(batch_texts))
            ]
        }
        return mock_resp

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.side_effect = lambda *args, **kwargs: make_resp(kwargs["json"]["input"])
    mock_client_cls.return_value = mock_client

    texts = [f"t{i}" for i in range(10)]
    s = Settings(embedding_dim=dim, embedding_batch_size=8)
    vecs = EmbeddingClient(s).embed(texts)

    assert len(vecs) == 10
    assert mock_client.post.call_count == 2
    first_batch = mock_client.post.call_args_list[0].kwargs["json"]["input"]
    second_batch = mock_client.post.call_args_list[1].kwargs["json"]["input"]
    assert len(first_batch) == 8
    assert len(second_batch) == 2
    assert first_batch[0] == "t0"
    assert second_batch[0] == "t8"


@patch("path_graph.rag.embed.EmbeddingClient.embed")
def test_embed_chunks(mock_embed):
    mock_embed.return_value = [[0.0] * 1024]
    chunks = [
        ChunkRecord(
            chunk_id="c1",
            document_id="d1",
            tenant="t",
            chunk_index=0,
            text="hi",
            text_hash="h",
        )
    ]
    vecs = embed_chunks(chunks, Settings())
    assert len(vecs[0]) == 1024
