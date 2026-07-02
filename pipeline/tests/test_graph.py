from unittest.mock import MagicMock, patch

from path_graph.config import Settings
from path_graph.graph.nebula_store import NebulaGraphStore
from path_graph.steps.graph_pipeline import run_graph_pipeline
from constants import PROJECT_ID


@patch("path_graph.steps.graph_pipeline.invoke_agent")
@patch("path_graph.steps.graph_pipeline.make_nebula_store")
@patch("path_graph.graph.chunk_partition.copy_chunks_to_project_batch")
@patch("path_graph.steps.graph_pipeline.read_jsonl")
@patch("path_graph.steps.graph_pipeline.make_blob_store")
@patch("path_graph.steps.graph_pipeline.get_settings")
def test_graph_pipeline_upserts_semantic_edges_from_agent(
    mock_settings,
    mock_blob,
    mock_read_jsonl,
    mock_copy,
    mock_nebula_factory,
    mock_invoke_agent,
):
    mock_settings.return_value = Settings()
    mock_copy.return_value = "chunks/dev/project/b1/chunks.jsonl"
    mock_read_jsonl.return_value = [
        {"chunk_id": "chunk-0", "text": "[[Alpha]]"},
    ]
    mock_invoke_agent.return_value = {
        "entities": [{"id": "entity:Alpha", "name": "Alpha"}],
        "edges": [
            {
                "type": "EXTRACTED",
                "source": "entity:Alpha",
                "target": "entity:Beta",
                "confidence": 0.9,
            }
        ],
    }
    nebula = MagicMock(spec=NebulaGraphStore)
    mock_nebula_factory.return_value = nebula
    store = MagicMock()
    store.agent_artifact_uri.return_value = "https://garage.example/presigned/chunks.jsonl"
    mock_blob.return_value = store

    run_graph_pipeline(
        "dev",
        PROJECT_ID,
        "default",
        "batch-1",
        "chunks/dev/doc/chunks.jsonl",
        "sess",
        skip_agent=False,
    )

    mock_invoke_agent.assert_called_once()
    inp = mock_invoke_agent.call_args.args[1]
    assert inp.chunks_s3 == "https://garage.example/presigned/chunks.jsonl"
    nebula.upsert_entities.assert_called_once()
    nebula.upsert_edges.assert_called_once()


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
