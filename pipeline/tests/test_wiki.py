from unittest.mock import patch

from path_graph.contracts.community import CommunityRecord
from path_graph.graph.nebula_store import NebulaGraphStore
from path_graph.steps.community_pipeline import run_community_pipeline_for_project
from path_graph.steps.wiki_pipeline import run_wiki_for_community
from constants import PROJECT_ID


@patch("path_graph.steps.wiki_pipeline.write_wiki_page")
@patch("path_graph.steps.wiki_pipeline.invoke_agent")
def test_wiki_pipeline_stores_agent_pages(mock_invoke_agent, mock_write_wiki, local_store, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    mock_invoke_agent.return_value = {
        "pages": [
            {
                "slug": "default-community-L0-abc12345",
                "title": "Community Report",
                "markdown": "# Report\n\nFrom LLM.",
            }
        ],
    }
    mock_write_wiki.return_value = "/default-community-L0-abc12345.md"

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
    record = comm["records"][0]

    wiki = run_wiki_for_community("dev", record, "sess", skip_agent=False)
    assert wiki["wiki_paths"] == ["/default-community-L0-abc12345.md"]
    mock_invoke_agent.assert_called_once()
    mock_write_wiki.assert_called_once_with(
        "dev",
        PROJECT_ID,
        "default-community-L0-abc12345",
        "# Report\n\nFrom LLM.",
    )


@patch("path_graph.steps.wiki_pipeline.write_wiki_page")
def test_community_and_wiki_stub_pipeline(mock_write_wiki, local_store, monkeypatch):
    mock_write_wiki.return_value = "/stub-page.md"
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
    assert wiki["wiki_paths"]
