from unittest.mock import MagicMock, patch

from path_graph.config import Settings
from path_graph.graph.nebula_store import NebulaGraphStore
from path_graph.steps.graph_pipeline import run_graph_pipeline


@patch("path_graph.steps.graph_pipeline.make_nebula_store")
@patch("path_graph.steps.graph_pipeline.partition_chunks_by_project")
@patch("path_graph.steps.graph_pipeline.read_jsonl")
@patch("path_graph.steps.graph_pipeline.make_blob_store")
@patch("path_graph.steps.graph_pipeline.get_settings")
def test_graph_pipeline_routes_chunks_by_project(
    mock_settings,
    mock_blob,
    mock_read_jsonl,
    mock_partition,
    mock_nebula_factory,
):
    mock_settings.return_value = Settings(path_graph_projects_per_tenant=2)
    mock_partition.return_value = {
        0: "chunks/dev/0/b1/chunks.jsonl",
        1: "chunks/dev/1/b1/chunks.jsonl",
    }
    mock_read_jsonl.return_value = [
        {"chunk_id": "chunk-0", "text": "[[Alpha]]"},
    ]
    nebula = MagicMock(spec=NebulaGraphStore)
    mock_nebula_factory.return_value = nebula

    run_graph_pipeline("dev", "batch-1", "chunks/dev/doc/chunks.jsonl", "sess", skip_agent=True)

    assert nebula.upsert_mentions.called
