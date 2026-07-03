from unittest.mock import MagicMock, patch

from path_graph.graph.nebula_store import NebulaGraphStore, _MemorySpace
from path_graph.lifecycle.compensation import compensate_document_index
from path_graph.lifecycle.purge import delete_project, purge_project
from path_graph.meta.pg import iter_migration_sql
from path_graph.storage.blob import LocalBlobStore
from constants import PROJECT_ID


def test_rls_migration_includes_policies():
    sql = "\n".join(iter_migration_sql())
    assert "CREATE POLICY tenant_isolation" in sql
    assert "document_tombstones" in sql
    assert "reconcile_reports" in sql
    assert "pipeline_runs" in sql
    assert "started_at TIMESTAMPTZ" in sql
    assert "embedding vector(1024)" in sql


def test_local_blob_delete_prefix(tmp_path):
    store = LocalBlobStore(tmp_path)
    store.put_bytes("raw/t/p/s/h/f1", b"x")
    store.put_bytes("raw/t/p/s/h/f2", b"y")
    assert store.delete_prefix("raw/t/") == 2
    assert store.list_keys("raw/") == []


def test_nebula_memory_delete_chunks():
    mem: dict[str, _MemorySpace] = {}
    store = NebulaGraphStore("h", 9669, "u", "p", memory=mem)
    space = "path_graph_dev_default"
    store.ensure_space(space)
    store.upsert_mentions(space, "chunk-1", ["Alice"])
    assert store.delete_chunks(space, ["chunk-1"]) == 1
    assert store.list_chunk_vertices(space) == []


@patch("path_graph.lifecycle.compensation.make_nebula_store")
@patch("path_graph.lifecycle.compensation.ProjectStore")
def test_compensate_document_index(mock_proj, mock_nebula):
    pg = MagicMock()
    pg.get_document.return_value = {
        "document_id": "d1",
        "project_id": PROJECT_ID,
        "content_hash": "h",
    }
    pg.list_chunk_ids_for_document.return_value = ["c1"]
    pg.clear_embeddings_for_document.return_value = 1
    mock_proj.return_value.get_project.return_value = MagicMock(slug="default")
    mock_nebula.return_value.delete_chunks.return_value = 1

    result = compensate_document_index(
        "dev", PROJECT_ID, "d1", settings=MagicMock(path_graph_dsn="x"), pg=pg
    )
    assert result["embeddings_cleared"] == 1
    assert result["nebula_deleted"] == 1


def test_lifecycle_step_modules_import_without_cycle():
    """Argo entrypoints must load without admin↔lifecycle circular imports."""
    import importlib

    for mod in (
        "path_graph.steps.cleanup_step",
        "path_graph.steps.purge_step",
        "path_graph.steps.reconcile_step",
    ):
        importlib.import_module(mod)


@patch("path_graph.lifecycle.purge.delete_project_wiki_tree", return_value=0)
@patch("path_graph.lifecycle.purge.make_nebula_store")
@patch("path_graph.lifecycle.purge.make_blob_store")
@patch("path_graph.lifecycle.purge.PgMetaStore")
@patch("path_graph.lifecycle.purge.ProjectStore")
def test_purge_project_deletes_raw_prefix_for_already_purged_docs(
    mock_proj_store_cls,
    mock_pg_cls,
    mock_blob_factory,
    mock_nebula_factory,
    mock_delete_wiki,
    tmp_path,
):
    tenant = "didim"
    blob = LocalBlobStore(tmp_path)
    raw_key = f"raw/{tenant}/{PROJECT_ID}/manual/abc123/doc.pdf"
    blob.put_bytes(raw_key, b"pdf")
    mock_blob_factory.return_value = blob

    mock_proj_store_cls.return_value.get_project.return_value = MagicMock(slug="default")
    pg = mock_pg_cls.return_value
    pg.list_documents_for_project.return_value = [
        {"document_id": "d1", "ingest_state": "purged"},
    ]
    conn = MagicMock()
    pg._conn.return_value.__enter__.return_value = conn

    mock_nebula_factory.return_value.drop_space.return_value = None

    settings = MagicMock(path_graph_dsn="postgresql://x")
    result = purge_project(tenant, PROJECT_ID, settings=settings)

    assert result["status"] == "purged"
    assert result["raw_prefix_deleted"] == 1
    assert blob.list_keys(f"raw/{tenant}/{PROJECT_ID}/") == []
    assert result["purged_documents"] == 0
    pg.clear_embeddings_for_project.assert_called_once_with(tenant, PROJECT_ID)


@patch("path_graph.lifecycle.purge.purge_project")
@patch("path_graph.lifecycle.purge.make_blob_store")
@patch("path_graph.lifecycle.purge.PgMetaStore")
@patch("path_graph.lifecycle.purge.ProjectStore")
def test_delete_project_purges_then_hard_deletes_pg(
    mock_proj_store_cls,
    mock_pg_cls,
    mock_blob_factory,
    mock_purge_project,
):
    tenant = "didim"
    mock_proj_store_cls.return_value.get_project.return_value = MagicMock(slug="default")
    pg = mock_pg_cls.return_value
    pg.list_documents_for_project.return_value = [
        {"document_id": "doc-1", "ingest_state": "indexed"},
    ]
    pg.delete_project_data.return_value = {"projects": 1, "documents": 1}

    blob = MagicMock()
    blob.delete_prefix.return_value = 2
    mock_blob_factory.return_value = blob
    mock_purge_project.return_value = {
        "status": "purged",
        "project_id": PROJECT_ID,
        "raw_prefix_deleted": 3,
        "purged_documents": 1,
    }

    settings = MagicMock(path_graph_dsn="postgresql://x")
    result = delete_project(tenant, PROJECT_ID, settings=settings)

    assert result["status"] == "deleted"
    mock_purge_project.assert_called_once()
    pg.delete_project_data.assert_called_once_with(tenant, PROJECT_ID)
    assert blob.delete_prefix.call_count == 4
    assert result["pg_deleted"]["projects"] == 1


def test_purge_step_delete_scope(monkeypatch):
    import path_graph.steps.purge_step as mod

    monkeypatch.setattr(mod, "delete_project", lambda *a, **k: {"status": "deleted"})
    assert mod.main(["--tenant", "t", "--project-id", PROJECT_ID, "--scope", "delete"]) == 0
