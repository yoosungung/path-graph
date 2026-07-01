from __future__ import annotations

from unittest.mock import MagicMock, patch

from path_graph.admin.sources import SourceStore
from path_graph.contracts.source import SourceDriver, SourceUpdate


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
            "last_batch_id": 10,
        }[key]
        items[idx] = val
    return tuple(items)


@patch("path_graph.admin.sources.psycopg.connect")
def test_get_source_by_last_batch(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.fetchone.return_value = _row(last_batch_id="batch-42")

    store = SourceStore("postgresql://localhost/test")
    profile = store.get_source_by_last_batch("dev", "batch-42")

    assert profile is not None
    assert profile.driver == SourceDriver.SHAREPOINT


@patch("path_graph.admin.sources.psycopg.connect")
def test_patch_source_config_sets_and_unsets(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    existing = _row(config={"folder": "회사규정", "delta_link": "https://old"})
    updated = _row(config={"folder": "회사규정", "delta_link": "https://new"})
    conn.execute.return_value.fetchone.side_effect = [existing, existing, updated]

    store = SourceStore("postgresql://localhost/test")
    profile = store.patch_source_config(
        "dev",
        "11111111-1111-4111-8111-111111111111",
        set_fields={"delta_link": "https://new"},
        unset_fields=("stale",),
    )

    assert profile is not None
    assert profile.config["delta_link"] == "https://new"
    assert "stale" not in profile.config


@patch("path_graph.admin.sources.psycopg.connect")
def test_patch_source_config_clears_delta_link_on_full(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    existing = _row(config={"folder": "x", "delta_link": "https://old", "sync_mode": "delta"})
    cleared = _row(config={"folder": "x", "sync_mode": "delta"})
    conn.execute.return_value.fetchone.side_effect = [existing, existing, cleared]

    store = SourceStore("postgresql://localhost/test")
    profile = store.patch_source_config(
        "dev",
        "11111111-1111-4111-8111-111111111111",
        unset_fields=("delta_link",),
    )

    assert profile is not None
    assert "delta_link" not in profile.config
