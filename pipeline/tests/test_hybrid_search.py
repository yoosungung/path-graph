from unittest.mock import MagicMock, patch

from path_graph.config import Settings
from path_graph.rag.hybrid_search import hybrid_search


@patch("path_graph.rag.hybrid_search.make_qdrant_store")
@patch("path_graph.rag.hybrid_search.EmbeddingClient")
@patch("path_graph.rag.hybrid_search.PgMetaStore")
def test_hybrid_search_rrf_merges_channels(mock_pg_cls, mock_embed_cls, mock_qdrant_factory):
    mock_pg = MagicMock()
    mock_pg_cls.return_value = mock_pg
    mock_pg.search_fts.return_value = [
        {
            "chunk_id": "a",
            "document_id": "d1",
            "project_id": "p1",
            "text": "alpha",
            "score": 0.9,
        },
        {
            "chunk_id": "b",
            "document_id": "d1",
            "project_id": "p1",
            "text": "beta",
            "score": 0.5,
        },
    ]

    mock_embed = MagicMock()
    mock_embed_cls.return_value = mock_embed
    mock_embed.embed.return_value = [[0.1, 0.2]]

    mock_qdrant = MagicMock()
    mock_qdrant_factory.return_value = mock_qdrant
    mock_qdrant.search.return_value = [
        {
            "chunk_id": "b",
            "document_id": "d1",
            "project_id": "p1",
            "text": "beta vec",
            "score": 0.95,
        },
        {
            "chunk_id": "c",
            "document_id": "d2",
            "project_id": "p1",
            "text": "gamma",
            "score": 0.8,
        },
    ]

    settings = Settings(
        path_graph_dsn="postgresql://localhost/test",
        qdrant_url="http://qdrant:6333",
        qdrant_api_key="key",
        embedding_dim=2,
    )
    results = hybrid_search(
        tenant="dev",
        project_id="p1",
        project_slug="default",
        query="hello",
        top_k=3,
        settings=settings,
    )

    ids = [row["id"] for row in results]
    assert ids[0] == "b"
    assert set(ids) == {"a", "b", "c"}
    assert all("rrf_score" in row for row in results)
    mock_pg.search_fts.assert_called_once_with("dev", "p1", "hello", limit=20)
    mock_qdrant.search.assert_called_once()


def test_hybrid_search_empty_query():
    assert (
        hybrid_search(
            tenant="dev",
            project_id="p1",
            project_slug="default",
            query="   ",
            settings=Settings(path_graph_dsn="postgresql://localhost/test"),
        )
        == []
    )
