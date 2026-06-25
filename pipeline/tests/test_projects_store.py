from unittest.mock import MagicMock, patch

from path_graph.admin.projects import ProjectStore
from path_graph.contracts.project import ProjectCreate


@patch("path_graph.admin.projects.psycopg.connect")
def test_create_project(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.fetchone.return_value = (
        "dev",
        "550e8400-e29b-41d4-a716-446655440000",
        "default",
        "Default",
        None,
    )

    store = ProjectStore("postgresql://localhost/test")
    profile = store.create_project("dev", ProjectCreate(name="Default", slug="default"))

    assert profile.slug == "default"
    conn.commit.assert_called_once()


@patch("path_graph.admin.projects.psycopg.connect")
def test_resolve_binding(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.fetchone.return_value = (
        "dev",
        "550e8400-e29b-41d4-a716-446655440000",
        "default",
        "Default",
        None,
    )

    store = ProjectStore("postgresql://localhost/test")
    binding = store.resolve_binding("dev", "550e8400-e29b-41d4-a716-446655440000")

    assert binding.project_slug == "default"
    assert binding.rag.qdrant_collection == "path_graph_dev_default"
