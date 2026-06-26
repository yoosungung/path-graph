from __future__ import annotations

from unittest.mock import MagicMock, patch

from path_graph.admin.sources import SourceStore
from path_graph.meta.pg import PgMetaStore


@patch("path_graph.admin.sources.psycopg.connect")
def test_list_pipeline_runs_orders_by_started_at_desc(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.fetchall.return_value = []

    store = SourceStore("postgresql://localhost/test")
    store.list_pipeline_runs("dev", limit=10, offset=5)

    sql = conn.execute.call_args[0][0]
    assert "ORDER BY started_at DESC NULLS LAST, id DESC" in sql
    assert conn.execute.call_args[0][1] == ("dev", 10, 5)


@patch("path_graph.admin.sources.psycopg.connect")
def test_count_pipeline_runs(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.fetchone.return_value = (42,)

    store = SourceStore("postgresql://localhost/test")
    total = store.count_pipeline_runs("dev")

    assert total == 42
    sql = conn.execute.call_args[0][0]
    assert "SELECT COUNT(*)" in sql
    assert "FROM path_graph.pipeline_runs" in sql


@patch("path_graph.meta.pg.psycopg.connect")
def test_list_documents_for_project_pagination(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.fetchall.return_value = [
        ("doc-1", "manual:a", "proj", "hash", "s3://b/a.pdf", "pending"),
    ]

    pg = PgMetaStore("postgresql://localhost/test")
    docs = pg.list_documents_for_project(
        "dev",
        "550e8400-e29b-41d4-a716-446655440000",
        limit=25,
        offset=50,
    )

    assert len(docs) == 1
    sql = conn.execute.call_args[0][0]
    assert "ORDER BY id DESC" in sql
    assert "LIMIT %s" in sql
    assert "OFFSET %s" in sql
    params = conn.execute.call_args[0][1]
    assert params[-2:] == [25, 50]


@patch("path_graph.meta.pg.psycopg.connect")
def test_count_documents_for_project_with_filename_filter(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.fetchone.return_value = (3,)

    pg = PgMetaStore("postgresql://localhost/test")
    total = pg.count_documents_for_project(
        "dev",
        "550e8400-e29b-41d4-a716-446655440000",
        filename_contains="report",
    )

    assert total == 3
    sql = conn.execute.call_args[0][0]
    assert "ILIKE" in sql
    assert conn.execute.call_args[0][1][-1] == "%report%"
