from __future__ import annotations

from unittest.mock import MagicMock, patch

from path_graph.admin.runner import collect_source
from path_graph.contracts.source import CollectSyncMode, SourceDriver, SourceProfile
from constants import PROJECT_ID


def _sharepoint_profile(**config) -> SourceProfile:
    return SourceProfile(
        tenant="dev",
        id="11111111-1111-4111-8111-111111111111",
        project_id=PROJECT_ID,
        name="kms",
        driver=SourceDriver.SHAREPOINT,
        source_id="sharepoint:kms",
        config={"folder": "회사규정", **config},
    )


@patch("path_graph.admin.runner.write_batch_manifest")
@patch("path_graph.admin.runner.make_blob_store")
@patch("path_graph.admin.runner._sharepoint_collector")
def test_collect_source_sharepoint_uses_delta_by_default(mock_collector_fn, _store, mock_manifest):
    collector = MagicMock()
    collector.collect_delta.return_value = {
        "items": [{"filename": "a.txt"}],
        "purged_document_ids": [],
        "delta_link": "https://graph/delta/new",
        "project_id": PROJECT_ID,
    }
    mock_collector_fn.return_value = collector
    mock_manifest.return_value = "s3://bucket/batches/dev/b1/manifest.jsonl"

    result = collect_source(_sharepoint_profile(delta_link="https://graph/delta/old"))

    collector.collect_delta.assert_called_once()
    assert collector.collect_delta.call_args.kwargs["delta_link"] == "https://graph/delta/old"
    collector.collect_folder.assert_not_called()
    assert result["sync_mode"] == "delta"
    assert result["delta_link"] == "https://graph/delta/new"


@patch("path_graph.admin.runner.write_batch_manifest")
@patch("path_graph.admin.runner.make_blob_store")
@patch("path_graph.admin.runner._sharepoint_collector")
def test_collect_source_sharepoint_full_override(mock_collector_fn, _store, mock_manifest):
    collector = MagicMock()
    collector.collect_folder.return_value = [{"filename": "a.txt"}, {"filename": "b.pdf"}]
    mock_collector_fn.return_value = collector
    mock_manifest.return_value = "s3://bucket/batches/dev/b1/manifest.jsonl"

    result = collect_source(_sharepoint_profile(), sync_mode=CollectSyncMode.FULL)

    collector.collect_folder.assert_called_once()
    collector.collect_delta.assert_not_called()
    assert result["sync_mode"] == "full"
    assert result["file_count"] == 2
