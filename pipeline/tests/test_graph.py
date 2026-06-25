from unittest.mock import MagicMock, patch

from path_graph.config import Settings
from path_graph.graph.nebula_store import NebulaGraphStore
from path_graph.steps.graph_pipeline import run_graph_pipeline
from constants import PROJECT_ID


@patch("path_graph.steps.graph_pipeline.make_nebula_store")
@patch("path_graph.graph.chunk_partition.copy_chunks_to_project_batch")
@patch("path_graph.steps.graph_pipeline.read_jsonl")
@patch("path_graph.steps.graph_pipeline.make_blob_store")
@patch("path_graph.steps.graph_pipeline.get_settings")
def test_graph_pipeline_uses_single_project_space(
    mock_settings,
    mock_blob,
    mock_read_jsonl,
    mock_copy,
    mock_nebula_factory,
):
    mock_settings.return_value = Settings()
    mock_copy.return_value = "chunks/dev/project/b1/chunks.jsonl"
    mock_read_jsonl.return_value = [
        {"chunk_id": "chunk-0", "text": "[[Alpha]]"},
    ]
    nebula = MagicMock(spec=NebulaGraphStore)
    mock_nebula_factory.return_value = nebula

    run_graph_pipeline(
        "dev",
        PROJECT_ID,
        "default",
        "batch-1",
        "chunks/dev/doc/chunks.jsonl",
        "sess",
        skip_agent=True,
    )

    assert nebula.upsert_mentions.called
