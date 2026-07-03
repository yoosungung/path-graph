from unittest.mock import MagicMock, patch

from path_graph.rag.hybrid_search import hybrid_search
from constants import PROJECT_ID


@patch("path_graph.rag.hybrid_search.PgMetaStore")
@patch("path_graph.rag.hybrid_search.EmbeddingClient")
def test_hybrid_search_rrf_merges_channels(mock_embed_cls, mock_pg_cls):
    mock_pg = MagicMock()
    mock_pg_cls.return_value = mock_pg
    mock_pg.search_fts.return_value = [
        {
            "chunk_id": "fts-1",
            "document_id": "doc-1",
            "project_id": PROJECT_ID,
            "text": "fts hit",
            "score": 0.5,
        }
    ]
    mock_pg.search_vector.return_value = [
        {
            "chunk_id": "vec-1",
            "document_id": "doc-2",
            "project_id": PROJECT_ID,
            "text": "vector hit",
            "score": 0.9,
        }
    ]
    mock_embed_cls.return_value.embed.return_value = [[0.1] * 1024]

    from path_graph.config import Settings

    results = hybrid_search(
        tenant="dev",
        project_id=PROJECT_ID,
        project_slug="default",
        query="test query",
        top_k=2,
        settings=Settings(path_graph_dsn="postgresql://localhost/test"),
    )
    assert len(results) == 2
    ids = {r["chunk_id"] for r in results}
    assert ids == {"fts-1", "vec-1"}
    mock_pg.search_fts.assert_called_once()
    mock_pg.search_vector.assert_called_once()


def test_hybrid_search_empty_query():
    assert (
        hybrid_search(
            tenant="dev",
            project_id=PROJECT_ID,
            project_slug="default",
            query="   ",
            settings=MagicMock(path_graph_dsn="postgresql://localhost/test"),
        )
        == []
    )
