from __future__ import annotations

from unittest.mock import MagicMock, patch

from path_graph.admin.sources import SourceStore


@patch("path_graph.admin.sources.psycopg.connect")
def test_finalize_pipeline_run_updates_terminal_status(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.rowcount = 1

    store = SourceStore("postgresql://localhost/test")
    updated = store.finalize_pipeline_run(
        "dev",
        "run-uuid",
        "Succeeded",
        started_at="2026-06-26T12:00:01Z",
        ended_at="2026-06-26T12:05:00Z",
    )

    assert updated is True
    conn.commit.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "UPDATE path_graph.pipeline_runs" in sql


@patch("path_graph.admin.sources.psycopg.connect")
def test_finalize_pipeline_run_rejects_non_terminal_status(mock_connect):
    store = SourceStore("postgresql://localhost/test")
    assert store.finalize_pipeline_run("dev", "run-uuid", "Running") is False
    mock_connect.assert_not_called()


@patch("path_graph.admin.sources.psycopg.connect")
def test_list_non_finalized_pipeline_runs(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.fetchall.return_value = [
        (
            "dev",
            "run-uuid",
            "ingest-manual-docs-abc",
            "argo-uid",
            "batch-1",
            "submitted",
            None,
            None,
        )
    ]

    store = SourceStore("postgresql://localhost/test")
    runs = store.list_non_finalized_pipeline_runs(limit=10)

    assert len(runs) == 1
    assert runs[0]["tenant"] == "dev"
    assert runs[0]["status"] == "submitted"
    assert runs[0]["started_at"] is None
