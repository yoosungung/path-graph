from path_graph.graph.nebula_store import NebulaGraphStore
from path_graph.steps.graphrag_pipeline import run_graphrag_pipeline
from path_graph.storage.blob import LocalBlobStore, write_jsonl
from unittest.mock import MagicMock


from constants import PROJECT_ID


def test_graphrag_pipeline_skip_agent(local_store, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(local_store))
    monkeypatch.setenv("PATH_GRAPH_DSN", "")
    from path_graph.config import get_settings

    get_settings.cache_clear()

    store = LocalBlobStore(local_store)
    chunks_key = "chunks/dev/doc/chunks.jsonl"
    write_jsonl(
        chunks_key,
        [{"chunk_id": "00000000-0000-0000-0000-000000000011", "text": "[[Alpha]] [[Beta]]"}],
        store,
    )

    memory: dict = {}
    nebula = NebulaGraphStore("h", 1, "u", "p", memory=memory)

    monkeypatch.setattr(
        "path_graph.steps.graphrag_pipeline.make_nebula_store",
        lambda settings=None: nebula,
    )
    monkeypatch.setattr(
        "path_graph.steps.graph_pipeline.make_nebula_store",
        lambda settings=None: nebula,
    )

    result = run_graphrag_pipeline(
        "dev", PROJECT_ID, "default", "b1", chunks_key, "sess", skip_agent=True
    )

    assert result["communities"]
    assert result["wiki"]["communities"]
    assert result["communities"][0]["project_id"] == PROJECT_ID


def test_graphrag_pipeline_marks_ingest_state(local_store, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(local_store))
    monkeypatch.setenv("PATH_GRAPH_DSN", "postgresql://localhost/test")
    from path_graph.config import get_settings

    get_settings.cache_clear()

    mock_pg = MagicMock()
    monkeypatch.setattr(
        "path_graph.steps.graphrag_pipeline.PgMetaStore",
        lambda _dsn: mock_pg,
    )

    store = LocalBlobStore(local_store)
    batch_id = "b-graph-state"
    chunks_key = "chunks/dev/doc/chunks.jsonl"
    write_jsonl(
        chunks_key,
        [{"chunk_id": "00000000-0000-0000-0000-000000000011", "text": "[[Alpha]] [[Beta]]"}],
        store,
    )

    memory: dict = {}
    nebula = NebulaGraphStore("h", 1, "u", "p", memory=memory)

    monkeypatch.setattr(
        "path_graph.steps.graphrag_pipeline.make_nebula_store",
        lambda settings=None: nebula,
    )
    monkeypatch.setattr(
        "path_graph.steps.graph_pipeline.make_nebula_store",
        lambda settings=None: nebula,
    )

    mark_mock = MagicMock(return_value=1)
    monkeypatch.setattr(
        "path_graph.steps.graphrag_pipeline.apply_graphrag_success",
        mark_mock,
    )

    run_graphrag_pipeline(
        "dev", PROJECT_ID, "default", batch_id, chunks_key, "sess", skip_agent=True
    )

    mark_mock.assert_called_once_with("dev", PROJECT_ID, batch_id, settings=get_settings())
