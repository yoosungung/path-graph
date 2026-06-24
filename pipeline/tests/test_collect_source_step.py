from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from path_graph.contracts.source import SourceDriver, SourceProfile
from path_graph.steps.collect_source_step import run_collect


def _profile(**kwargs) -> SourceProfile:
    defaults = dict(
        tenant="dev",
        id="11111111-1111-4111-8111-111111111111",
        name="kms",
        driver=SourceDriver.SHAREPOINT,
        source_id="sharepoint:kms",
        config={"folder": "회사규정"},
    )
    defaults.update(kwargs)
    return SourceProfile(**defaults)


def test_run_collect_writes_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH_GRAPH_DSN", "postgresql://localhost/test")
    profile = _profile()
    mock_store = MagicMock()
    mock_store.get_source.return_value = profile

    collected = {
        "batch_id": "batch-1",
        "manifest_key": "batches/dev/batch-1/manifest.jsonl",
        "file_count": 2,
    }

    with patch("path_graph.steps.collect_source_step.SourceStore", return_value=mock_store):
        with patch("path_graph.steps.collect_source_step.resolve_settings_from_env") as mock_resolve:
            with patch("path_graph.steps.collect_source_step.collect_source", return_value=collected):
                mock_resolve.return_value = MagicMock()
                out = run_collect(
                    tenant="dev",
                    source_pg_id=profile.id,
                    batch_id="batch-1",
                    output_dir=str(tmp_path),
                )

    assert out["file_count"] == 2
    assert (tmp_path / "manifest_key").read_text() == collected["manifest_key"]
    mock_store.get_source.assert_called_once_with("dev", profile.id)


def test_run_collect_source_not_found(monkeypatch):
    monkeypatch.setenv("PATH_GRAPH_DSN", "postgresql://localhost/test")
    mock_store = MagicMock()
    mock_store.get_source.return_value = None

    with patch("path_graph.steps.collect_source_step.SourceStore", return_value=mock_store):
        with pytest.raises(ValueError, match="source not found"):
            run_collect(tenant="dev", source_pg_id="missing")
