from unittest.mock import MagicMock, patch

from path_graph.admin.projects import ProjectStore


@patch("path_graph.admin.projects.psycopg.connect")
def test_list_all_projects(mock_connect):
    conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = conn
    conn.execute.return_value.fetchall.return_value = [
        ("dev", "550e8400-e29b-41d4-a716-446655440000", "default", "Default", None),
        ("prod", "660e8400-e29b-41d4-a716-446655440001", "docs", "Docs", None),
    ]

    store = ProjectStore("postgresql://localhost/test")
    profiles = store.list_all_projects()

    assert len(profiles) == 2
    assert profiles[0].tenant == "dev"
    assert profiles[1].tenant == "prod"
    sql = conn.execute.call_args[0][0]
    assert "FROM path_graph.projects" in sql
    assert "WHERE tenant" not in sql
