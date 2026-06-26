from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from path_graph.admin.sources import SourceStore
from path_graph.contracts.source import SourceCreate, SourceDriver, SourceUpdate


def _row(**overrides):
    base = (
        "dev",
        "11111111-1111-4111-8111-111111111111",
        "550e8400-e29b-41d4-a716-446655440000",
        "kms",
        "sharepoint",
        "sharepoint:kms",
        {"folder": "회사규정"},
        True,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    items = list(base)
    for key, val in overrides.items():
        idx = {
            "tenant": 0,
            "id": 1,
            "project_id": 2,
            "name": 3,
            "driver": 4,
            "source_id": 5,
            "config": 6,
        }[key]
        items[idx] = val
    return tuple(items)


@patch("path_graph.admin.sources.ProjectStore")
@patch("path_graph.admin.sources.psycopg.connect")
def test_list_sources(mock_connect, mock_project_store_cls):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.fetchall.return_value = [_row()]
    mock_project_store_cls.return_value.backfill_orphan_project_ids.return_value = 0

    store = SourceStore("postgresql://localhost/test")
    profiles = store.list_sources("dev")

    mock_project_store_cls.return_value.backfill_orphan_project_ids.assert_called_once_with("dev")

    assert len(profiles) == 1
    assert profiles[0].name == "kms"
    assert profiles[0].driver == SourceDriver.SHAREPOINT


@patch("path_graph.admin.sources.psycopg.connect")
def test_create_source(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.fetchone.return_value = _row(name="new-src")

    store = SourceStore("postgresql://localhost/test")
    body = SourceCreate(
        project_id="550e8400-e29b-41d4-a716-446655440000",
        name="new-src",
        driver=SourceDriver.GDRIVE,
        source_id="gdrive:reports",
        config={"folder_path": "Reports"},
    )
    profile = store.create_source("dev", body)

    assert profile.name == "new-src"
    conn.commit.assert_called_once()


@patch("path_graph.admin.sources.psycopg.connect")
def test_get_pipeline_run_by_batch(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.fetchone.return_value = (
        "run-uuid",
        "ingest-manual-docs-abc",
        "argo-uid",
        "batch-1",
        "submitted",
        None,
        None,
    )

    store = SourceStore("postgresql://localhost/test")
    run = store.get_pipeline_run_by_batch("dev", "batch-1")

    assert run is not None
    assert run["workflow_name"] == "ingest-manual-docs-abc"
    assert run["batch_id"] == "batch-1"


@patch("path_graph.admin.sources.psycopg.connect")
def test_delete_source(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.rowcount = 1

    store = SourceStore("postgresql://localhost/test")
    assert store.delete_source("dev", "11111111-1111-4111-8111-111111111111") is True
