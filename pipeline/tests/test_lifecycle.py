from unittest.mock import MagicMock, patch

from path_graph.graph.nebula_store import NebulaGraphStore, _MemorySpace
from path_graph.lifecycle.compensation import compensate_document_index
from path_graph.meta.pg import iter_migration_sql
from path_graph.rag.qdrant_store import QdrantStore
from path_graph.storage.blob import LocalBlobStore
from constants import PROJECT_ID


def test_rls_migration_includes_policies():
    sql = "\n".join(iter_migration_sql())
    assert "CREATE POLICY tenant_isolation" in sql
    assert "document_tombstones" in sql
    assert "reconcile_reports" in sql


def test_local_blob_delete_prefix(tmp_path):
    store = LocalBlobStore(tmp_path)
    store.put_bytes("raw/t/p/s/h/f1", b"x")
    store.put_bytes("raw/t/p/s/h/f2", b"y")
    assert store.delete_prefix("raw/t/") == 2
    assert store.list_keys("raw/") == []


def test_qdrant_delete_by_document_id():
    client = MagicMock()
    client.collection_exists.return_value = True
    store = QdrantStore(client, __import__("path_graph.config", fromlist=["Settings"]).Settings(embedding_dim=4))
    n = store.delete_by_document_id("dev", "default", "doc-1", project_id=PROJECT_ID)
    assert n >= 1
    client.delete.assert_called_once()


def test_nebula_memory_delete_chunks():
    mem: dict[str, _MemorySpace] = {}
    store = NebulaGraphStore("h", 9669, "u", "p", memory=mem)
    space = "path_graph_dev_default"
    store.ensure_space(space)
    store.upsert_mentions(space, "chunk-1", ["Alice"])
    assert store.delete_chunks(space, ["chunk-1"]) == 1
    assert store.list_chunk_vertices(space) == []


@patch("path_graph.lifecycle.compensation.make_qdrant_store")
@patch("path_graph.lifecycle.compensation.make_nebula_store")
@patch("path_graph.lifecycle.compensation.ProjectStore")
def test_compensate_document_index(mock_proj, mock_nebula, mock_qdrant):
    pg = MagicMock()
    pg.get_document.return_value = {
        "document_id": "d1",
        "project_id": PROJECT_ID,
        "content_hash": "h",
    }
    pg.list_chunk_ids_for_document.return_value = ["c1"]
    mock_proj.return_value.get_project.return_value = MagicMock(slug="default")
    mock_qdrant.return_value.delete_by_document_id.return_value = 1
    mock_nebula.return_value.delete_chunks.return_value = 1

    result = compensate_document_index(
        "dev", PROJECT_ID, "d1", settings=MagicMock(path_graph_dsn="x", qdrant_url="http://q"), pg=pg
    )
    assert result["qdrant_deleted"] == 1
    assert result["nebula_deleted"] == 1
