"""BFF contract tests for admin lifecycle API (agents-runtime wraps these)."""

from unittest.mock import MagicMock, patch

from path_graph.admin.lifecycle import (
    api_delete_project,
    api_get_binding,
    api_list_tombstones,
    api_purge_document,
    api_restore_document,
)
from constants import PROJECT_ID


@patch("path_graph.admin.lifecycle.get_settings")
@patch("path_graph.admin.lifecycle.purge_document")
@patch("path_graph.admin.lifecycle.PgMetaStore")
def test_api_purge_document(mock_pg_cls, mock_purge, mock_settings):
    mock_settings.return_value.path_graph_dsn = "postgresql://x"
    mock_pg_cls.return_value.get_document.return_value = {
        "project_id": PROJECT_ID,
        "document_id": "d1",
    }
    mock_purge.return_value = {"status": "purged"}
    out = api_purge_document("dev", "d1", reason="test")
    assert out["status"] == "purged"
    mock_purge.assert_called_once()


@patch("path_graph.admin.lifecycle.get_settings")
@patch("path_graph.admin.lifecycle.PgMetaStore")
def test_api_restore_document(mock_pg_cls, mock_settings):
    mock_settings.return_value.path_graph_dsn = "postgresql://x"
    pg = mock_pg_cls.return_value
    pg.get_document.return_value = {
        "project_id": PROJECT_ID,
        "content_hash": "abc",
    }
    pg.clear_tombstone.return_value = True
    out = api_restore_document("dev", "d1")
    assert out["status"] == "restored"


@patch("path_graph.contracts.project.resolve_knowledge_binding")
@patch("path_graph.admin.lifecycle.get_settings")
@patch("path_graph.admin.lifecycle.ProjectStore")
def test_api_get_binding(mock_proj, mock_settings, mock_resolve):
    from path_graph.contracts.project import KnowledgeBinding, KnowledgeBindingGraph, KnowledgeBindingRag, KnowledgeBindingWiki

    mock_settings.return_value.path_graph_dsn = "postgresql://x"
    mock_proj.return_value.get_project.return_value = MagicMock(
        id=PROJECT_ID, slug="default"
    )
    mock_resolve.return_value = KnowledgeBinding(
        tenant="dev",
        project_id=PROJECT_ID,
        project_slug="default",
        rag=KnowledgeBindingRag(index_namespace="path_graph_dev_default"),
        graph=KnowledgeBindingGraph(nebula_space="path_graph_dev_default"),
        wiki=KnowledgeBindingWiki(s3_prefix=f"wiki/dev/{PROJECT_ID}/"),
    )
    out = api_get_binding("dev", PROJECT_ID)
    assert out["rag"]["index_namespace"] == "path_graph_dev_default"


@patch("path_graph.admin.lifecycle.get_settings")
def test_api_list_tombstones_no_dsn(mock_settings):
    mock_settings.return_value.path_graph_dsn = ""
    assert api_list_tombstones("dev") == []


@patch("path_graph.admin.lifecycle.delete_project")
def test_api_delete_project(mock_delete):
    mock_delete.return_value = {"status": "deleted", "pg_deleted": {"projects": 1}}
    out = api_delete_project("dev", PROJECT_ID, reason="test")
    assert out["status"] == "deleted"
    mock_delete.assert_called_once_with("dev", PROJECT_ID, reason="test")
