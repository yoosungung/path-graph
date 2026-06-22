from path_graph.graph.nebula_store import NebulaGraphStore
from path_graph.steps.graphrag_pipeline import run_graphrag_pipeline
from path_graph.storage.blob import LocalBlobStore, write_jsonl


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

    result = run_graphrag_pipeline("dev", "b1", chunks_key, "sess", skip_agent=True)

    assert result["communities"]
    assert result["wiki"]["communities"]
    assert 0 <= result["communities"][0]["project"] < 4
