from path_graph.contracts.community import CommunityRecord
from path_graph.graph.nebula_store import NebulaGraphStore
from path_graph.steps.community_pipeline import run_community_pipeline_for_project
from path_graph.steps.wiki_pipeline import run_wiki_for_community
from constants import PROJECT_ID


def test_community_and_wiki_stub_pipeline(local_store, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    memory: dict = {}
    nebula = NebulaGraphStore("h", 1, "u", "p", memory=memory)
    space = "path_graph_dev_default"
    nebula.ensure_space(space)
    nebula.upsert_mentions(space, "chunk-1", ["Alpha", "Beta"])
    nebula.upsert_edges(
        space,
        [
            {
                "type": "EXTRACTED",
                "source": "entity:Alpha",
                "target": "entity:Beta",
                "confidence": 1.0,
            }
        ],
    )

    from path_graph.config import get_settings
    from path_graph.storage.blob import LocalBlobStore, write_jsonl

    get_settings.cache_clear()
    store = LocalBlobStore(local_store)
    chunks_key = "chunks/dev/0/b1/chunks.jsonl"
    write_jsonl(
        chunks_key,
        [{"chunk_id": "chunk-1", "text": "[[Alpha]] [[Beta]]"}],
        store,
    )

    comm = run_community_pipeline_for_project(
        "dev",
        PROJECT_ID,
        "default",
        "b1",
        chunks_key,
        nebula=nebula,
    )
    assert comm["community_count"] >= 1
    record = comm["records"][0]
    assert isinstance(record, CommunityRecord)
    assert record.project_id == PROJECT_ID

    wiki = run_wiki_for_community("dev", record, "sess", skip_agent=True)
    assert wiki["wiki_uris"]
